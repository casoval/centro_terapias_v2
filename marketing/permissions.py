"""
Permisos del módulo de Marketing.

Regla actual: SOLO el superusuario (el dueño) accede a este módulo.
Ni gerente, ni recepcionista, ni profesional, ni paciente.

Nota del proyecto: los superusuarios deliberadamente NO tienen PerfilUsuario,
así que aquí nunca se consulta el perfil: solo `is_superuser`.
"""

from functools import wraps

from django.core.exceptions import PermissionDenied


def puede_usar_marketing(user):
    return bool(user and user.is_authenticated and user.is_active and user.is_superuser)


def superusuario_requerido(vista):
    """
    Decorador para vistas. Usuario anónimo -> redirige al login; usuario
    autenticado que no es superusuario -> 403.
    """
    @wraps(vista)
    def envoltura(request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login
            return redirect_to_login(request.get_full_path())
        if not puede_usar_marketing(request.user):
            raise PermissionDenied
        return vista(request, *args, **kwargs)
    return envoltura
