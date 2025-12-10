from django.apps import AppConfig

from django.apps import AppConfig
import os
import joblib

class FraudappConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'transactions'

    def ready(self):
        # load model and store it in app module
        from . import ml
        model_path = os.getenv('MODEL_PATH')
        if model_path and os.path.exists(model_path):
            ml.model = joblib.load(model_path)
        else:
            ml.model = None
