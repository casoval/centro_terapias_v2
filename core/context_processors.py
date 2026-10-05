from django.conf import settings


def perf_flags(request):
    """Expone banderas de rendimiento a los templates."""
    return {'USE_COMPILED_TAILWIND': getattr(settings, 'USE_COMPILED_TAILWIND', False)}
