import os

from .base import ProveedorError, ProveedorTexto, RespuestaTexto


class GeminiTexto(ProveedorTexto):
    id = 'gemini'
    nombre = 'Google Gemini'
    variable_entorno = 'GEMINI_API_KEY'

    @property
    def modelo(self):
        return os.environ.get('MARKETING_GEMINI_MODEL', 'gemini-2.5-flash')

    def generar(self, sistema, usuario, temperatura=0.8):
        try:
            import google.generativeai as genai
            from google.generativeai.types import HarmBlockThreshold, HarmCategory
        except ImportError as e:  # pragma: no cover
            raise ProveedorError(f'Falta la librería google-generativeai: {e}')

        # Seguridad ESTRICTA: es contenido público (no es el chat clínico).
        seguridad = {
            categoria: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE
            for categoria in (
                HarmCategory.HARM_CATEGORY_HARASSMENT, HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
            )
        }
        try:
            genai.configure(api_key=os.environ.get(self.variable_entorno))
            modelo = genai.GenerativeModel(
                model_name=self.modelo, system_instruction=sistema, safety_settings=seguridad,
            )
            resp = modelo.generate_content(
                usuario,
                generation_config=genai.types.GenerationConfig(
                    temperature=temperatura, max_output_tokens=8192,
                    response_mime_type='application/json',
                ),
            )
            texto = resp.text
        except Exception as e:
            raise ProveedorError(f'Gemini falló: {e}')
        uso = getattr(resp, 'usage_metadata', None)
        return RespuestaTexto(
            texto=texto, modelo=self.modelo,
            tokens_entrada=getattr(uso, 'prompt_token_count', 0) or 0,
            tokens_salida=getattr(uso, 'candidates_token_count', 0) or 0,
        )
