from django.apps import AppConfig


class RecordatoriosConfig(AppConfig):
    name = 'recordatorios'

    def ready(self):
        import recordatorios.signals  # noqa: F401 — activa los signals al arrancar Django