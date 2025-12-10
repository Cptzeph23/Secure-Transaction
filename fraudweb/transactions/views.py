from django.shortcuts import render

import os
import json
import requests
from django.shortcuts import render, redirect
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse, HttpResponse
from django.conf import settings
from .models import Transaction, FraudAlert
from . import ml

DARJA_TOKEN_URL = 'https://sandbox.safaricom.co.ke/oauth/v1/generate?grant_type=client_credentials'
DARJA_STK_PUSH_URL = 'https://sandbox.safaricom.co.ke/mpesa/stkpush/v1/processrequest'

def get_daraja_access_token():
    key = os.getenv('DARJA_CLIENT_KEY')
    secret = os.getenv('DARJA_CLIENT_SECRET')
    r = requests.get(DARJA_TOKEN_URL, auth=(key, secret))
    if r.status_code == 200:
        return r.json().get('access_token')
    else:
        raise RuntimeError("Daraja token error: " + r.text)

def send_gava_sms(phone, message):
    api_url = os.getenv('GAVA_API_URL')
    headers = {'Authorization': f'Bearer {os.getenv("GAVA_API_KEY")}', 'Content-Type': 'application/json'}
    payload = {"phone": phone, "message": message}
    try:
        r = requests.post(api_url, json=payload, headers=headers, timeout=10)
        return r.status_code == 200
    except Exception:
        return False

def compute_features(amount, phone_number, merchant_id):
    # TODO: mirror the transformations you used in Jupyter Notebook
    # This is a placeholder: you must replace with real feature engineering used in your model
    return {
        'Amount': float(amount),
        # add other fields as required, e.g., 'V1':..., 'V2':..., etc.
    }

def decide_action(prob, threshold=0.5):
    return 'FLAG' if prob >= threshold else 'ALLOW'

from django.views.decorators.http import require_POST
@require_POST
def create_transaction(request):
    data = json.loads(request.body.decode('utf-8'))
    phone = data.get('phone')
    amount = data.get('amount')
    merchant_id = data.get('merchant_id', '')
    # compute features as the model expects
    features = compute_features(amount, phone, merchant_id)
    try:
        prob = ml.predict(features)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
    status = 'PENDING'
    if decide_action(prob, threshold=0.5) == 'FLAG':
        status = 'FLAGGED'
    tx = Transaction.objects.create(
        phone_number=phone,
        amount=amount,
        merchant_id=merchant_id,
        features_json=features,
        fraud_probability=prob,
        status=status
    )
    if status == 'FLAGGED':
        # create alert and send SMS
        msg = f"Suspicious transaction flagged for KES {amount}. Our team will contact you."
        FraudAlert.objects.create(transaction=tx, message=msg)
        send_gava_sms(phone, msg)
        return JsonResponse({'transaction_id': tx.id, 'status': 'FLAGGED', 'fraud_probability': prob})
    else:
        # initiate Daraja STK Push
        try:
            token = get_daraja_access_token()
            payload = {
                "BusinessShortCode": os.getenv('DARJA_SHORTCODE'),
                "Password": os.getenv('DARJA_PASSWORD'),  # base64 encoded timestamp+shortcode+passkey as per Daraja
                "Timestamp": "20210701165500", # generate current timestamp as YYYYMMDDHHMMSS
                "TransactionType": "CustomerPayBillOnline",
                "Amount": int(float(amount)),
                "PartyA": phone.replace("+", ""),  # phone number in format 2547...
                "PartyB": os.getenv('DARJA_SHORTCODE'),
                "PhoneNumber": phone.replace("+", ""),
                "CallBackURL": os.getenv('DARJA_CALLBACK_URL'),
                "AccountReference": f"TX{tx.id}",
                "TransactionDesc": "Payment for goods"
            }
            headers = {"Authorization": f"Bearer {token}"}
            r = requests.post(DARJA_STK_PUSH_URL, json=payload, headers=headers)
            j = r.json()
            checkout_req_id = j.get('CheckoutRequestID') or j.get('ResponseCode')  # adjust to actual response
            tx.mpesa_checkout_request_id = checkout_req_id
            tx.save()
            return JsonResponse({'transaction_id': tx.id, 'status': 'PENDING', 'fraud_probability': prob})
        except Exception as e:
            tx.status='FAILED'
            tx.save()
            return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
@require_POST
def daraja_callback(request):
    """
    Daraja will post JSON to this endpoint when STK result arrives.
    Update the Transaction status based on callback.
    """
    data = json.loads(request.body.decode('utf-8'))
    # Save the callback payload for auditing if desired
    # Parse checkout request id to find transaction
    # NOTE: structure depends on Daraja response format
    callback_metadata = data.get('Body', {}).get('stkCallback', {})
    checkout_req_id = callback_metadata.get('CheckoutRequestID')
    result_code = callback_metadata.get('ResultCode')
    result_desc = callback_metadata.get('ResultDesc')
    # find transaction
    try:
        tx = Transaction.objects.get(mpesa_checkout_request_id=checkout_req_id)
    except Transaction.DoesNotExist:
        return HttpResponse(status=404)
    if result_code == 0:
        tx.status = 'SUCCESS'
        tx.save()
        # send SMS confirmation
        send_gava_sms(tx.phone_number, f"Payment of KES {tx.amount} was successful. Thank you.")
    else:
        tx.status = 'FAILED'
        tx.save()
        send_gava_sms(tx.phone_number, f"Payment failed: {result_desc}")
    return JsonResponse({'status':'ok'})

