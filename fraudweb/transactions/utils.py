import base64
from datetime import datetime

def get_timestamp():
    return datetime.now().strftime('%Y%m%d%H%M%S')

def get_password(shortcode, passkey, timestamp):
    data_to_encode = shortcode + passkey + timestamp
    return base64.b64encode(data_to_encode.encode()).decode('utf-8')
