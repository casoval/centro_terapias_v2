"""
Helpers de permisos para documentos de pacientes.

IMPORTANTE: en este proyecto los superusuarios (admin) deliberadamente
NO tienen PerfilUsuario (ver la señal post_save en core.models —
"No crear perfil para superusuarios"). Por eso todo chequeo de permisos
debe verificar `user.is_superuser` PRIMERO, y solo después recurrir al
perfil. Mismo patrón usado en core/utils.py (get_perfil_usuario).
"""


def puede_ver_documentos(user, paciente):
    if user.is_superuser:
        return True
    perfil = getattr(user, 'perfil', None)
    return bool(perfil and perfil.puede_ver_documentos_paciente(paciente))


def puede_subir_documentos(user, paciente):
    if user.is_superuser:
        return True
    perfil = getattr(user, 'perfil', None)
    return bool(perfil and perfil.puede_subir_documentos_paciente(paciente))


def puede_eliminar_documentos(user):
    if user.is_superuser:
        return True
    perfil = getattr(user, 'perfil', None)
    return bool(perfil and perfil.puede_eliminar_documentos())


def es_profesional(user):
    perfil = getattr(user, 'perfil', None)
    return bool(perfil and perfil.rol == 'profesional')
