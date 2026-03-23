from django.apps import AppConfig


class AsistenciaConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'asistencia'
    verbose_name = 'Control de Asistencia'

    def ready(self):
        import asistencia.signals  # noqa: F401
