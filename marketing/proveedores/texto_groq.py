import os

import requests

from .base import ProveedorError, ProveedorTexto, RespuestaTexto

URL = 'https://api.groq.com/openai/v1/chat/completions'


class GroqTexto(ProveedorTexto):
    id = 'groq'
    nombre = 'Groq'
    variable_entorno = 'GROQ_API_KEY'

    @property
    def modelo(self):
        # Configurable: los nombres de modelo de Groq cambian con el tiempo.
        return os.environ.get('MARKETING_GROQ_MODEL', 'llama-3.3-70b-versatile')

    def generar(self, sistema, usuario, temperatura=0.8):
        try:
            r = requests.post(
                URL,
                headers={'Authorization': f'Bearer {os.environ.get(self.variable_entorno)}'},
                json={
                    'model': self.modelo,
                    'messages': [
                        {'role': 'system', 'content': sistema},
                        {'role': 'user', 'content': usuario},
                    ],
                    'temperature': temperatura,
                    'response_format': {'type': 'json_object'},
                },
                timeout=60,
            )
            r.raise_for_status()
            datos = r.json()
            texto = datos['choices'][0]['message']['content']
        except Exception as e:
            raise ProveedorError(f'Groq falló: {e}')
        uso = datos.get('usage', {})
        return RespuestaTexto(
            texto=texto, modelo=self.modelo,
            tokens_entrada=uso.get('prompt_tokens', 0), tokens_salida=uso.get('completion_tokens', 0),
        )
