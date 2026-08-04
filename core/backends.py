"""
Backend de autenticación personalizado.

✅ Objetivo: restringir el ACCESO al sistema (login) cuando el usuario está
inactivo, sin modificar ni invalidar nada más (sesiones existentes de
terapia, pagos, etc. no se tocan).

Hereda de ModelBackend, así que el comportamiento de autenticación
(usuario/contraseña) es exactamente el mismo de Django. Lo único que se
agrega es una verificación adicional de "¿puede este usuario entrar al
sistema en este momento?", basada en:

  - PerfilUsuario.activo
  - Paciente.estado (si el usuario es un paciente)
  - Profesional.activo (si el usuario es un profesional)

Superusuarios nunca se bloquean por esta vía.
"""
from django.contrib.auth.backends import ModelBackend


class PerfilActivoModelBackend(ModelBackend):
    """
    ModelBackend estándar + verificación de que el usuario (paciente,
    profesional, recepcionista o gerente) no esté marcado como inactivo.
    """

    def user_can_authenticate(self, user):
        # Primero aplica la verificación estándar de Django (is_active del
        # modelo User). Si ya está bloqueado por ahí, no seguimos.
        if not super().user_can_authenticate(user):
            return False

        # Los superusuarios siempre pueden entrar.
        if user.is_superuser:
            return True

        perfil = getattr(user, 'perfil', None)
        if perfil is None:
            # Usuario sin perfil (caso legado/atípico): no se restringe
            # aquí, se comporta como antes de este cambio.
            return True

        return perfil.tiene_acceso_al_sistema()
