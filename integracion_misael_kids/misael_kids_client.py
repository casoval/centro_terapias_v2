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


def _request(method, path, params=None, json_body=None, timeout=10):
    url = f'{_base_url()}{path}'
    try:
        resp = requests.request(
            method, url, headers=_headers(), params=params, json=json_body, timeout=timeout
        )
    except requests.RequestException as exc:
        raise MisaelKidsError(f'No se pudo conectar con Misael Kids: {exc}') from exc

    if resp.status_code == 401:
        raise MisaelKidsError('API key rechazada por Misael Kids.')
    if resp.status_code == 404:
        return None
    if not resp.ok:
        # Si Misael Kids devuelve un {"detail": "..."} legible (ej. 409
        # porque el niño o el paciente ya están vinculados), lo usamos
        # tal cual en vez de un mensaje genérico con el status code.
        detail = None
        try:
            detail = resp.json().get('detail')
        except Exception:
            pass
        raise MisaelKidsError(detail or f'Misael Kids respondió {resp.status_code}: {resp.text[:300]}')
    return resp.json()


def _get(path, params=None, timeout=10):
    return _request('GET', path, params=params, timeout=timeout)


def _post(path, json_body=None, timeout=10):
    return _request('POST', path, json_body=json_body, timeout=timeout)


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


# ═══════════════════════════════════════════════════════════════════
# Pantalla de vinculación del lado de Centro Misael: buscar niños de
# Misael Kids sin vincular, ver su detalle, crear el vínculo y listar
# los ya vinculados. El vínculo en sí (VinculoCentroMisael) sigue
# viviendo solo en Misael Kids — acá no se guarda ninguna copia.
# ═══════════════════════════════════════════════════════════════════

def buscar_ninos_sin_vincular(q):
    """
    Niños de Misael Kids que todavía no están vinculados con ningún
    paciente. El endpoint usa paginación DRF por defecto (a diferencia
    de /consulta/derivaciones/, que es un APIView simple sin paginar),
    así que la respuesta viene envuelta en {count,next,previous,results}
    — hay que extraer 'results', no tratar la respuesta como lista directa.
    """
    data = _get('/consulta/ninos-sin-vincular/', params={'q': q})
    return (data or {}).get('results', [])


def obtener_nino(nino_id):
    """Detalle completo del niño, para copiar datos al crear el Paciente."""
    return _get(f'/consulta/ninos/{nino_id}/')


def crear_vinculo(nino_id, paciente_centro_id, nombre_paciente_centro=''):
    """
    Crea el vínculo del lado de Misael Kids (única fuente de verdad).
    Propaga MisaelKidsError con el detalle si Misael Kids rechaza la
    operación (ej. 409 porque el niño o el paciente ya están
    vinculados) para que la vista lo muestre tal cual al usuario.
    """
    return _post('/consulta/vincular/', json_body={
        'nino_id': nino_id,
        'paciente_centro_id': paciente_centro_id,
        'nombre_paciente_centro': nombre_paciente_centro,
    })


def listar_vinculados():
    """
    Todos los vínculos existentes, con resumen de derivaciones.
    También paginado — mismo motivo que buscar_ninos_sin_vincular.
    """
    data = _get('/consulta/vinculados/')
    return (data or {}).get('results', [])
