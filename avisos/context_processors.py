from django.utils import timezone

# Páginas de inicio de cada rol: ahí se muestra el pop-up.
VISTAS_INICIO = {'core:dashboard', 'agenda:calendario', 'facturacion:mi_cuenta'}


def avisos_inicio(request):
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {}
    rm = getattr(request, 'resolver_match', None)
    vista = rm.view_name if rm else ''
    ctx = {'avisos_es_inicio': vista in VISTAS_INICIO}
    try:
        from .visibilidad import anuncios_vigentes
        ctx['avisos_badge'] = anuncios_vigentes(user, timezone.localdate()).count()
    except Exception:
        ctx['avisos_badge'] = 0
    return ctx
