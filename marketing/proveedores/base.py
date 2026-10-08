"""Interfaz común de proveedores de IA. Cada capacidad (texto, imagen, video, voz) tendrá la suya."""

import json
import os
import re
from dataclasses import dataclass


class ProveedorError(Exception):
    """Fallo al llamar al proveedor (red, cuota, bloqueo de seguridad, respuesta inválida)."""


class ProveedorNoDisponible(ProveedorError):
    """No hay clave configurada para el proveedor pedido (o para ninguno)."""


@dataclass
class RespuestaTexto:
    texto: str
    modelo: str
    tokens_entrada: int = 0
    tokens_salida: int = 0


class ProveedorTexto:
    id = ''
    nombre = ''
    variable_entorno = ''

    @classmethod
    def disponible(cls):
        return bool(os.environ.get(cls.variable_entorno, '').strip())

    def generar(self, sistema, usuario, temperatura=0.8):
        """Devuelve RespuestaTexto con JSON en `texto`. Debe lanzar ProveedorError si falla."""
        raise NotImplementedError


def extraer_json(texto):
    """Parsea JSON tolerando ```json ... ``` y texto alrededor. Lanza ProveedorError si no se puede."""
    if not texto or not texto.strip():
        raise ProveedorError('La IA devolvió una respuesta vacía.')
    limpio = re.sub(r'^```(?:json)?\s*|\s*```$', '', texto.strip(), flags=re.IGNORECASE)
    try:
        return json.loads(limpio)
    except json.JSONDecodeError:
        pass
    ini, fin = limpio.find('{'), limpio.rfind('}')
    if ini != -1 and fin > ini:
        try:
            return json.loads(limpio[ini:fin + 1])
        except json.JSONDecodeError:
            pass
    raise ProveedorError('La IA no devolvió un JSON válido.')
