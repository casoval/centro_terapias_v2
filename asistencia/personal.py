"""
Quién cuenta como personal "activo" para la asistencia, y hasta cuándo se le evalúa.

Desactivar un profesional (módulo Profesionales) marca Profesional.activo=False y guarda
Profesional.fecha_baja; no toca User.is_active. Un profesional activo es: usuario activo Y ficha activa.

La baja NO es retroactiva: el pasado no se reescribe. Un profesional dado de baja sigue apareciendo en el
panel y en los informes de los períodos en que estuvo activo, y se le evalúa hasta su baja. Nunca se oculta
una marcación: el control termina, como pronto, el último día que marcó.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.db.models import Max, Q
from django.utils import timezone


def profesionales_activos():
    """Usuarios con rol profesional, activos y con ficha activa (los que se enrolan, marcan y reciben asuetos)."""
    return (User.objects.filter(perfil__rol='profesional', is_active=True)
            .exclude(profesional__activo=False)
            .exclude(perfil__profesional__activo=False))


def profesionales_inactivos():
    """Usuarios con rol profesional dados de baja (ficha inactiva o usuario desactivado)."""
    return (User.objects.filter(perfil__rol='profesional')
            .filter(Q(is_active=False) | Q(profesional__activo=False) | Q(perfil__profesional__activo=False))
            .distinct())


def fin_control_por_usuario(user_ids=None):
    """
    {user_id: último día evaluado} solo para quienes están dados de baja (los activos no tienen tope).

    Último día = el día anterior a la baja (el día de la baja no se penaliza), pero nunca antes de la última
    marcación válida: no se puede ocultar una marcación. Sin fecha de baja registrada (bajas anteriores a
    este control, o usuario desactivado desde Usuarios) rige la última marcación. Sin ninguna marcación ni
    fecha de baja el valor es None: no hay nada que mostrar.
    """
    from .models import RegistroAsistencia
    inactivos = profesionales_inactivos()
    if user_ids is not None:
        inactivos = inactivos.filter(pk__in=list(user_ids))
    ids = list(inactivos.values_list('pk', flat=True))
    if not ids:
        return {}
    bajas = {}
    for uid, f1, f2 in inactivos.values_list('pk', 'profesional__fecha_baja', 'perfil__profesional__fecha_baja'):
        f = f1 or f2
        if f:
            bajas[uid] = f
    ultimas = {}
    for fila in (RegistroAsistencia.objects.filter(user_id__in=ids, estado__in=RegistroAsistencia.ESTADOS_VALIDOS)
                 .values('user_id').annotate(ultima=Max('fecha_hora'))):
        ultimas[fila['user_id']] = timezone.localtime(fila['ultima']).date()
    fin = {}
    for uid in ids:
        candidatos = [d for d in (bajas[uid] - timedelta(days=1) if uid in bajas else None, ultimas.get(uid)) if d]
        fin[uid] = max(candidatos) if candidatos else None
    return fin


def profesionales_en_periodo(inicio, fin):
    """
    Usuarios que estuvieron activos en algún día de [inicio, fin]: los activos hoy más los dados de baja
    cuyo control llega hasta ese período o después.
    """
    vigentes = [uid for uid, ultimo in fin_control_por_usuario().items() if ultimo and ultimo >= inicio]
    return User.objects.filter(Q(pk__in=profesionales_activos().values('pk')) | Q(pk__in=vigentes))
