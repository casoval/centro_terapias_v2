"""
Helpers de permisos para el módulo Inventario.

Reglas resumidas (confirmadas con el usuario):
  - TODOS los roles staff (profesional, recepcionista, gerente, admin)
    tienen su propio inventario personal.
  - Cualquiera puede SUMAR a su propio inventario (o al de una sucursal
    a la que tenga acceso). Nunca puede restar directamente.
  - Solo el admin puede editar, ajustar, restar o eliminar stock/movimientos.
  - Solo el admin puede crear/editar/eliminar el catálogo de ítems y las
    categorías (gerente también gestiona catálogo, igual que categorías
    de archivos).
  - Las transferencias SIEMPRE requieren aprobación del admin, incluso
    entre dos profesionales activos.
  - Admin y gerente ven todo el inventario del centro; recepcionista y
    profesional ven su inventario personal + el de sus sucursales asignadas.
"""


def es_staff_del_centro(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    perfil = getattr(user, 'perfil', None)
    return bool(perfil and perfil.rol in ('profesional', 'recepcionista', 'gerente'))


def es_admin(user):
    return bool(user.is_authenticated and user.is_superuser)


def es_admin_o_gerente(user):
    if user.is_superuser:
        return True
    perfil = getattr(user, 'perfil', None)
    return bool(perfil and perfil.rol == 'gerente')


def ve_todo_el_inventario(user):
    """Admin y gerente ven el inventario completo del centro."""
    return es_admin_o_gerente(user)


def sucursales_visibles(user):
    """Sucursales sobre las que el usuario tiene visibilidad de inventario (None = todas)."""
    if ve_todo_el_inventario(user):
        return None
    perfil = getattr(user, 'perfil', None)
    if not perfil:
        return []
    return list(perfil.get_sucursales())


def puede_ver_titular(user, titular):
    if ve_todo_el_inventario(user):
        return True
    if titular.tipo == 'usuario':
        return titular.usuario_id == user.id
    if titular.tipo == 'sucursal':
        return titular.sucursal in (sucursales_visibles(user) or [])
    # 'servicio' y 'centro' generales: solo admin/gerente (ya cubierto arriba)
    return False


def puede_agregar_a_titular(user, titular):
    """Solo puede SUMAR a: su propio inventario personal, o el de una sucursal a la que tenga acceso. Admin siempre."""
    if es_admin(user):
        return True
    if titular.tipo == 'usuario':
        return titular.usuario_id == user.id
    if titular.tipo == 'sucursal':
        perfil = getattr(user, 'perfil', None)
        if perfil and perfil.rol == 'gerente':
            return True  # el gerente ve/gestiona todas las sucursales
        return titular.sucursal in (sucursales_visibles(user) or [])
    return False


def puede_ajustar_o_eliminar_stock(user):
    """Editar cantidades directamente, crear ajustes negativos, o eliminar: solo admin."""
    return es_admin(user)


def puede_gestionar_catalogo(user):
    """Crear/editar/desactivar ítems y categorías del catálogo: admin y gerente."""
    return es_admin_o_gerente(user)


def puede_solicitar_transferencia(user, titular_origen):
    """Cualquiera puede solicitar transferir DESDE un titular sobre el que tiene control de aporte."""
    return puede_agregar_a_titular(user, titular_origen)


def puede_resolver_transferencias(user):
    """Aprobar/rechazar transferencias: solo admin."""
    return es_admin(user)
