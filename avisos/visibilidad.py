"""Quién ve qué: rol del usuario, alcance por sucursal y anuncios visibles."""
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from .models import Anuncio

ROL_ADMIN = 'admin'


def rol_de(user):
    """'admin' | 'gerente' | 'recepcionista' | 'profesional' | 'paciente' | None"""
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        return ROL_ADMIN
    perfil = getattr(user, 'perfil', None)
    return perfil.rol if perfil else None


def sucursales_ids(user):
    """None = sin restricción de sucursal; conjunto de ids en caso contrario."""
    rol = rol_de(user)
    if rol == ROL_ADMIN:
        return None
    perfil = user.perfil
    if rol == 'gerente':
        ids = set(perfil.sucursales.values_list('id', flat=True))
        return ids or None          # gerente sin sucursales asignadas = todas
    if rol == 'recepcionista':
        return set(perfil.sucursales.values_list('id', flat=True))
    if rol == 'profesional':
        prof = perfil.profesional
        return set(prof.sucursales.values_list('id', flat=True)) if prof else set()
    if rol == 'paciente':
        pac = perfil.paciente
        return set(pac.sucursales.values_list('id', flat=True)) if pac else set()
    return set()


_CAMPO_ROL = {
    'gerente': 'dest_gerentes',
    'recepcionista': 'dest_recepcionistas',
    'profesional': 'dest_profesionales',
    'paciente': 'dest_pacientes',
}


def _para_rol_y_sucursal(qs, user):
    rol = rol_de(user)
    campo = _CAMPO_ROL.get(rol)
    if not campo:
        return qs.none()
    qs = qs.filter(**{campo: True})
    ids = sucursales_ids(user)
    if ids is not None:
        qs = qs.filter(Q(sucursales__isnull=True) | Q(sucursales__in=ids)).distinct()
    return qs


def anuncios_vigentes(user, hoy=None):
    """Vigentes (inicio ≤ hoy ≤ fin, inclusive), urgentes primero. El admin ve todos."""
    hoy = hoy or timezone.localdate()
    qs = Anuncio.objects.filter(fecha_inicio__lte=hoy, fecha_fin__gte=hoy)
    if rol_de(user) != ROL_ADMIN:
        qs = _para_rol_y_sucursal(qs, user)
    # 'urgente' > 'normal' alfabéticamente → orden descendente
    return qs.order_by('-importancia', 'fecha_fin', '-id')


def anuncios_historial(user, hoy=None):
    """Terminados y guardados en historial."""
    hoy = hoy or timezone.localdate()
    qs = Anuncio.objects.filter(fecha_fin__lt=hoy, guardar_en_historial=True)
    if rol_de(user) != ROL_ADMIN:
        qs = _para_rol_y_sucursal(qs, user)
    return qs.order_by('-fecha_fin', '-id')


def anuncio_visible_para(user, anuncio, hoy=None):
    return anuncios_vigentes(user, hoy).filter(pk=anuncio.pk).exists()


def usuarios_destino(anuncio):
    """Usuarios a quienes apunta el anuncio (para ver quién confirmó / quién falta)."""
    User = get_user_model()
    roles = [r for r, c in _CAMPO_ROL.items() if getattr(anuncio, c)]
    if not roles:
        return User.objects.none()
    qs = User.objects.filter(is_active=True, is_superuser=False, perfil__rol__in=roles)
    suc = set(anuncio.sucursales.values_list('id', flat=True))
    if not suc:
        return qs.order_by('first_name', 'username')
    q = (
        Q(perfil__rol='gerente', perfil__sucursales__isnull=True)
        | Q(perfil__rol__in=['gerente', 'recepcionista'], perfil__sucursales__in=suc)
        | Q(perfil__rol='profesional', perfil__profesional__sucursales__in=suc)
        | Q(perfil__rol='paciente', perfil__paciente__sucursales__in=suc)
    )
    return qs.filter(q).distinct().order_by('first_name', 'username')
