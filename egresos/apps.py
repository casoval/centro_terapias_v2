# egresos/apps.py

from django.apps import AppConfig


class EgresosConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'egresos'
    verbose_name = 'Egresos del Centro'

    def ready(self):
        """Registra las señales al iniciar la app."""
        import egresos.signals  # noqa: F401