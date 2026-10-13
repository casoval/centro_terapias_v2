from django.utils import timezone

from .visibilidad import rol_de

# Página de inicio de cada rol: solo ahí se muestra el pop-up (y en ninguna otra).
INICIO_POR_ROL = {
    'admin': 'core:dashboard',
    'gerente': 'core:dashboard',
    'recepcionista': 'core:dashboard',
    'profesional': 'agenda:calendario',
    'paciente': 'facturacion:mi_cuenta',
}


def avisos_inicio(request):
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {}
    rm = getattr(request, 'resolver_match', None)
    vista = rm.view_name if rm else ''
    ctx = {'avisos_es_inicio': bool(vista) and vista == INICIO_POR_ROL.get(rol_de(user))}
    try:
        from .visibilidad import anuncios_vigentes
        ctx['avisos_badge'] = anuncios_vigentes(user, timezone.localdate()).count()
    except Exception:
        ctx['avisos_badge'] = 0
    return ctx
