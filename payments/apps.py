from django.apps import AppConfig

class PaymentsConfig(AppConfig):
    default_auto_field = 'django.db.models.AutoField'
    name = 'payments'

    def ready(self):
        import payments.signals

