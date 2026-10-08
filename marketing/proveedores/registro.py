"""Registro de proveedores. Solo se ofrecen los que tienen su clave en el entorno."""

from marketing.models import ConfigMarketing

from .base import ProveedorNoDisponible
from .texto_gemini import GeminiTexto
from .texto_groq import GroqTexto

PROVEEDORES_TEXTO = [GeminiTexto, GroqTexto]


def listar_proveedores_texto():
    return [
        {'id': p.id, 'nombre': p.nombre, 'disponible': p.disponible(), 'variable_entorno': p.variable_entorno}
        for p in PROVEEDORES_TEXTO
    ]


def obtener_proveedor_texto(id_proveedor=None):
    """
    Prioridad: el id pedido -> el configurado en ConfigMarketing -> el primero disponible.
    Si se pide uno explícito que no tiene clave, falla (no cambia de proveedor en silencio).
    """
    por_id = {p.id: p for p in PROVEEDORES_TEXTO}
    if id_proveedor:
        clase = por_id.get(id_proveedor)
        if clase is None or not clase.disponible():
            raise ProveedorNoDisponible(
                f'El proveedor de texto "{id_proveedor}" no está disponible (falta su clave en el .env).'
            )
        return clase()
    elegido = ConfigMarketing.get().proveedor_texto
    if elegido and elegido in por_id and por_id[elegido].disponible():
        return por_id[elegido]()
    for clase in PROVEEDORES_TEXTO:
        if clase.disponible():
            return clase()
    raise ProveedorNoDisponible(
        'No hay ningún proveedor de texto con clave configurada (GEMINI_API_KEY o GROQ_API_KEY).'
    )
