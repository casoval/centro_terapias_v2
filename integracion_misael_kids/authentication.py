"""
integracion_misael_kids/authentication.py

Autenticación simple por API key para consumo servicio-a-servicio.
No es un usuario del sistema: Misael Kids es la única aplicación
externa que consume esta API, así que un secreto compartido (por
variable de entorno, nunca hardcodeado) es suficiente — evita tener
que mantener un modelo de tokens para un solo consumidor.
"""
import hmac

from django.conf import settings
from rest_framework import authentication, exceptions


class MisaelKidsAPIKeyAuthentication(authentication.BaseAuthentication):
    """
    Espera el header:  Authorization: ApiKey <clave>

    Se compara con hmac.compare_digest para evitar timing attacks.
    No hay usuario real detrás: request.user queda como AnonymousUser
    y las vistas se apoyan en IsAuthenticated (que igual pasa, porque
    DRF marca request.user como autenticado sólo si esta clase retorna
    una tupla) — devolvemos un usuario "virtual" mínimo.
    """

    keyword = 'ApiKey'

    def authenticate(self, request):
        auth_header = authentication.get_authorization_header(request).decode('utf-8')
        if not auth_header or not auth_header.startswith(self.keyword + ' '):
            return None

        clave_recibida = auth_header[len(self.keyword) + 1:].strip()
        clave_esperada = getattr(settings, 'MISAEL_KIDS_API_KEY', '')

        if not clave_esperada:
            raise exceptions.AuthenticationFailed(
                'MISAEL_KIDS_API_KEY no está configurada en el servidor.'
            )

        if not clave_recibida or not hmac.compare_digest(clave_recibida, clave_esperada):
            raise exceptions.AuthenticationFailed('API key inválida.')

        return (_UsuarioServicioMisaelKids(), None)

    def authenticate_header(self, request):
        return self.keyword


class _UsuarioServicioMisaelKids:
    """Usuario "falso" mínimo para que IsAuthenticated pase y quede claro en logs quién llamó."""
    is_authenticated = True
    is_active = True
    is_staff = False
    is_superuser = False
    pk = None
    id = None

    def __str__(self):
        return 'servicio:misael_kids'
