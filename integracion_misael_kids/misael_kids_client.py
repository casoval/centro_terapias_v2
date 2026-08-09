"""
integracion_misael_kids/misael_kids_client.py

Cliente delgado hacia la API de Misael Kids (app misael_link del repo
misael_kids), en el sentido SALIENTE: Centro Misael preguntando si un
paciente ya está vinculado, o consultando derivaciones recibidas.

Misael Kids sigue siendo la única fuente de verdad de los vínculos —
acá no se guarda ninguna copia, se consulta en vivo en cada request.

Requiere en el .env de Centro Misael:
    MISAEL_KIDS_API_URL=https://tu-misael-kids.com
    MISAEL_KIDS_API_KEY=<misma clave que CENTRO_MISAEL_API_KEY en Misael Kids>
"""
import requests
from django.conf import settings


class MisaelKidsNoConfigurado(Exception):
    """La URL o la API key de Misael Kids no están configuradas."""


class MisaelKidsError(Exception):
    """Error de red o respuesta inesperada de Misael Kids."""


def _base_url():
    if not settings.MISAEL_KIDS_API_URL or not settings.MISAEL_KIDS_API_KEY:
        raise MisaelKidsNoConfigurado(
            'MISAEL_KIDS_API_URL / MISAEL_KIDS_API_KEY no están configurados en el .env.'
        )
    return settings.MISAEL_KIDS_API_URL.rstrip('/') + '/api/misael-link'


def _headers():
    return {'Authorization': f'ApiKey {settings.MISAEL_KIDS_API_KEY}'}


def _get(path, params=None, timeout=10):
    url = f'{_base_url()}{path}'
    try:
        resp = requests.get(url, headers=_headers(), params=params, timeout=timeout)
    except requests.RequestException as exc:
        raise MisaelKidsError(f'No se pudo conectar con Misael Kids: {exc}') from exc

    if resp.status_code == 401:
        raise MisaelKidsError('API key rechazada por Misael Kids.')
    if resp.status_code == 404:
        return None
    if not resp.ok:
        raise MisaelKidsError(f'Misael Kids respondió {resp.status_code}: {resp.text[:300]}')
    return resp.json()


def consultar_vinculo(paciente_id):
    """
    Devuelve {'vinculado': bool, 'nino_id':..., 'nino_nombre':..., ...}
    Si Misael Kids no está configurado o falla, deja pasar la excepción:
    el llamador decide cómo tratar la ambigüedad (normalmente: asumir
    'no vinculado' y avisarlo, en vez de bloquear silenciosamente).
    """
    data = _get('/consulta/vinculo/', params={'paciente_centro_id': paciente_id})
    return data or {'vinculado': False}


def esta_vinculado(paciente_id):
    """
    Atajo booleano sobre consultar_vinculo(), para chequeos rápidos en
    vistas. Deja pasar MisaelKidsNoConfigurado/MisaelKidsError: como el
    plan de trabajo EXIGE que el paciente esté vinculado, si no podemos
    verificarlo (Misael Kids caído, mal configurado) es más seguro
    bloquear la creación con un mensaje claro que crear un plan "a
    ciegas" sin saber si en realidad corresponde.
    """
    return bool(consultar_vinculo(paciente_id).get('vinculado'))


def listar_derivaciones(paciente_id):
    """Derivaciones que Misael Kids mandó para este paciente vinculado."""
    data = _get('/consulta/derivaciones/', params={'paciente_centro_id': paciente_id})
    return data or []
