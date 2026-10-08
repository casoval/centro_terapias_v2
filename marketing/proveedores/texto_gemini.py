"""
Gemini para texto, vía API REST (sin SDK).

Por qué REST y no `google-generativeai`:
  - Ese paquete está en desuso y no se toca `requirements.txt` ni el SDK que
    usa la app `agente`.
  - Mismo patrón que `texto_groq.py`: solo `requests`.

El modelo es configurable con MARKETING_GEMINI_MODEL en el .env, porque Google
retira modelos con frecuencia (gemini-2.5-flash ya devuelve 404 en muchas
cuentas y su cierre oficial es el 16/oct/2026).
"""

import os

import requests

from .base import ProveedorError, ProveedorTexto, RespuestaTexto

MODELO_POR_DEFECTO = 'gemini-3.5-flash'
URL = 'https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent'

# Seguridad ESTRICTA: es contenido público (no es el chat clínico).
CATEGORIAS_SEGURIDAD = (
    'HARM_CATEGORY_HARASSMENT',
    'HARM_CATEGORY_HATE_SPEECH',
    'HARM_CATEGORY_SEXUALLY_EXPLICIT',
    'HARM_CATEGORY_DANGEROUS_CONTENT',
)


class GeminiTexto(ProveedorTexto):
    id = 'gemini'
    nombre = 'Google Gemini'
    variable_entorno = 'GEMINI_API_KEY'

    @property
    def modelo(self):
        return os.environ.get('MARKETING_GEMINI_MODEL', '').strip() or MODELO_POR_DEFECTO

    def _cuerpo(self, sistema, usuario, temperatura):
        config = {'maxOutputTokens': 16384, 'responseMimeType': 'application/json'}
        # Google recomienda no tocar la temperatura en la familia Gemini 3.
        if not self.modelo.startswith('gemini-3'):
            config['temperature'] = temperatura
        return {
            'systemInstruction': {'parts': [{'text': sistema}]},
            'contents': [{'role': 'user', 'parts': [{'text': usuario}]}],
            'generationConfig': config,
            'safetySettings': [
                {'category': c, 'threshold': 'BLOCK_MEDIUM_AND_ABOVE'} for c in CATEGORIAS_SEGURIDAD
            ],
        }

    def generar(self, sistema, usuario, temperatura=0.8):
        try:
            r = requests.post(
                URL.format(modelo=self.modelo),
                headers={'x-goog-api-key': os.environ.get(self.variable_entorno, '')},
                json=self._cuerpo(sistema, usuario, temperatura),
                timeout=90,
            )
        except requests.RequestException as e:
            raise ProveedorError(f'Gemini no respondió: {e}')

        if r.status_code != 200:
            try:
                detalle = r.json().get('error', {}).get('message', '')
            except ValueError:
                detalle = ''
            raise ProveedorError(
                f'Gemini devolvió HTTP {r.status_code} con el modelo "{self.modelo}". '
                f'{detalle or r.text[:200]}'.strip()
            )

        try:
            datos = r.json()
        except ValueError:
            raise ProveedorError('Gemini devolvió una respuesta que no es JSON.')

        bloqueo = (datos.get('promptFeedback') or {}).get('blockReason')
        if bloqueo:
            raise ProveedorError(f'Gemini bloqueó la solicitud por seguridad ({bloqueo}).')
        candidatos = datos.get('candidates') or []
        if not candidatos:
            raise ProveedorError('Gemini no devolvió ningún resultado.')
        candidato = candidatos[0]
        partes = (candidato.get('content') or {}).get('parts') or []
        texto = ''.join(p.get('text', '') for p in partes if not p.get('thought'))
        if not texto.strip():
            motivo = candidato.get('finishReason', 'desconocido')
            raise ProveedorError(f'Gemini devolvió una respuesta vacía (motivo: {motivo}).')

        uso = datos.get('usageMetadata') or {}
        return RespuestaTexto(
            texto=texto, modelo=self.modelo,
            tokens_entrada=uso.get('promptTokenCount', 0) or 0,
            tokens_salida=(uso.get('candidatesTokenCount', 0) or 0) + (uso.get('thoughtsTokenCount', 0) or 0),
        )
