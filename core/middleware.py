"""
Middleware de control de acceso por inactividad.

✅ Objetivo puntual pedido: si un paciente, profesional, recepcionista o
gerente queda INACTIVO mientras ya tiene una sesión de navegador iniciada,
este middleware corta su acceso al sistema en la siguiente petición que
haga (cierra su sesión de Django y lo redirige al login con un mensaje).

⚠️ Importante: esto NO toca modelos de Sesion (terapia), Pago, Factura ni
ninguna otra lógica de negocio. Únicamente cierra la sesión web del
usuario (`django.contrib.auth.logout`), que es una operación estándar de
autenticación, y no borra ni invalida ningún dato del sistema.
"""
from django.contrib.auth import logout as auth_logout
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse


# Rutas que siempre deben quedar accesibles, incluso para un usuario que
# está siendo desconectado en esta misma petición (para evitar loops de
# redirección y no romper login/logout/estáticos/admin/API de bots).
_RUTAS_EXENTAS_PREFIJOS = (
    '/admin/',
    '/api/',
    '/static/',
    '/media/',
)


class AccesoActivoMiddleware:
    """
    Verifica, en cada petición de un usuario autenticado (no superusuario),
    si su perfil (o su ficha de paciente/profesional asociada) sigue activo.
    Si no lo está, cierra su sesión y lo envía al login con el motivo.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path

        if not path.startswith(_RUTAS_EXENTAS_PREFIJOS):
            user = getattr(request, 'user', None)

            if user is not None and user.is_authenticated and not user.is_superuser:
                perfil = getattr(user, 'perfil', None)

                if perfil is not None:
                    motivo = perfil.acceso_bloqueado_motivo()

                    if motivo:
                        auth_logout(request)
                        messages.error(request, f'🔒 Acceso restringido: {motivo}')

                        login_url = reverse('core:login')
                        if path != login_url:
                            return redirect(login_url)

        return self.get_response(request)
