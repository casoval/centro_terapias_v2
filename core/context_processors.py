import hashlib

from django.conf import settings

_tailwind_version = None


def _version_tailwind():
    """
    Huella (hash) del contenido de static/css/tailwind.css.
    Se agrega como ?v=... a la URL del CSS: nginx cachea /static/ por 30 días
    como "immutable", así que sin esto los navegadores no verían un
    tailwind.css regenerado. Si el archivo cambia, la URL cambia.
    Se calcula una sola vez por proceso.
    """
    global _tailwind_version
    if _tailwind_version is None:
        try:
            ruta = settings.BASE_DIR / 'static' / 'css' / 'tailwind.css'
            _tailwind_version = hashlib.md5(ruta.read_bytes()).hexdigest()[:10]
        except OSError:
            _tailwind_version = '0'
    return _tailwind_version


def perf_flags(request):
    """Expone banderas de rendimiento a los templates."""
    return {
        'USE_COMPILED_TAILWIND': getattr(settings, 'USE_COMPILED_TAILWIND', False),
        'TAILWIND_VERSION': _version_tailwind(),
    }
