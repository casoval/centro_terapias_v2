"""
Helpers de permisos para Archivos del Centro.

IMPORTANTE: en este proyecto los superusuarios (admin) deliberadamente
NO tienen PerfilUsuario (ver la señal post_save en core.models). Por eso
todo chequeo de permisos debe verificar `user.is_superuser` PRIMERO, y
solo después recurrir al perfil. Mismo patrón usado en
documentos/permissions.py.
"""


def es_staff_del_centro(user):
    """
    True si el usuario tiene acceso al módulo (cualquier rol excepto paciente).
    Los pacientes no ven este módulo en absoluto.
    """
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    perfil = getattr(user, 'perfil', None)
    return bool(perfil and perfil.rol in ('profesional', 'recepcionista', 'gerente'))


def puede_ver_archivo(user, archivo):
    if user.is_superuser:
        return True
    if archivo.subido_por_id == user.id:
        return True
    if archivo.visibilidad == 'todos':
        return es_staff_del_centro(user)
    if archivo.visibilidad == 'roles':
        perfil = getattr(user, 'perfil', None)
        if not perfil:
            return False
        return archivo.roles_permitidos.filter(rol=perfil.rol).exists()
    if archivo.visibilidad == 'usuarios':
        return archivo.usuarios_permitidos.filter(usuario_id=user.id).exists()
    return False  # privado y no es el dueño


def puede_subir_archivos(user):
    """Cualquier staff del centro puede subir (sin límite de cantidad)."""
    return es_staff_del_centro(user)


def puede_eliminar_archivos(user):
    """Solo admin (superusuario) puede eliminar."""
    return bool(user.is_authenticated and user.is_superuser)


def puede_editar_visibilidad_simple(user, archivo):
    """
    El dueño de un archivo puede cambiar su propia visibilidad entre las
    dos opciones simples ('privado' / 'todos'). El admin siempre puede
    (y además tiene acceso a las opciones avanzadas, ver
    `puede_gestionar_permisos_avanzados`).
    """
    if user.is_superuser:
        return True
    return archivo.subido_por_id == user.id


def puede_gestionar_permisos_avanzados(user):
    """
    Asignar visibilidad por roles específicos o por usuarios específicos,
    a CUALQUIER archivo (sin importar quién lo subió): solo admin.
    """
    return bool(user.is_authenticated and user.is_superuser)


def puede_gestionar_categorias(user):
    """Crear/editar/eliminar categorías: admin y gerente."""
    if user.is_superuser:
        return True
    perfil = getattr(user, 'perfil', None)
    return bool(perfil and perfil.rol == 'gerente')
