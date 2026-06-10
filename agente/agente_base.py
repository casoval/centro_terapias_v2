"""
agente/agente_base.py
Clase base con lógica común para todos los agentes del sistema.

Evita repetir en cada agente:
- Inicialización del cliente Gemini
- Guardado de mensajes en BD
- Recuperación del historial con límite configurable
- Manejo de errores con fallback estándar
- Logging consistente

Uso:
    from agente.agente_base import AgenteBase

    class MiAgente(AgenteBase):
        TIPO = 'recepcionista'

        def responder(self, telefono, mensaje):
            historial = self.get_historial(telefono)
            self.guardar_mensaje(telefono, 'user', mensaje)
            # ... lógica del agente ...
"""

import os
import logging
import google.generativeai as genai

log = logging.getLogger('agente')

MODELO_GEMINI = 'gemini-2.5-flash'

# Mensaje de fallback estándar cuando ocurre un error técnico
FALLBACK_ERROR = (
    'Disculpe, tuve un problema técnico. '
    'Por favor comuníquese directamente con nosotros:\n'
    'Sede Japón: +591 76175352\n'
    'Sede Camacho: +591 78633975'
)

_client_configured = False


def get_client():
    """Configura el cliente Gemini una sola vez (singleton)."""
    global _client_configured
    if not _client_configured:
        genai.configure(api_key=os.environ.get('GEMINI_API_KEY'))
        _client_configured = True
    return genai


class AgenteBase:
    """
    Clase base para todos los agentes del Centro Misael.

    Subclases deben definir:
        TIPO (str): nombre del agente, coincide con ConversacionAgente.agente
                    Ej: 'recepcionista', 'gerente', 'superusuario'

    Subclases pueden sobreescribir:
        fallback_mensaje(): texto de error personalizado
    """

    TIPO: str = 'publico'  # sobreescribir en cada subclase

    # ── Cliente ───────────────────────────────────────────────────────────────

    @property
    def client(self):
        return get_client()

    # ── Historial ─────────────────────────────────────────────────────────────

    def get_max_historial(self) -> int:
        """Obtiene el límite de historial desde ConfigAgente (editable en el admin)."""
        from agente.models import ConfigAgente
        return ConfigAgente.get_max_historial(self.TIPO)

    def get_historial(self, telefono: str) -> list[dict]:
        """
        Recupera el historial de conversación del número dado,
        limitado al máximo configurado en el admin.
        Retorna lista de dicts {role, content} lista para enviar a Gemini.
        Gemini usa 'user' y 'model' como roles (no 'assistant').
        """
        from agente.models import ConversacionAgente
        limite = self.get_max_historial()
        mensajes = (
            ConversacionAgente.objects
            .filter(agente=self.TIPO, telefono=telefono)
            .order_by('-creado')[:limite]
        )
        # Invertir para orden cronológico (más antiguo primero)
        # Gemini usa 'user' y 'model' (no 'assistant')
        return [
            {
                'role': 'model' if m.rol == 'assistant' else 'user',
                'parts': [m.contenido],
            }
            for m in reversed(list(mensajes))
        ]

    # ── Guardar mensajes ──────────────────────────────────────────────────────

    def guardar_mensaje(
        self,
        telefono: str,
        rol: str,
        contenido: str,
        modelo_usado: str = '',
        origen: str = 'whatsapp',
    ) -> None:
        """Guarda un mensaje en ConversacionAgente."""
        from agente.models import ConversacionAgente
        try:
            ConversacionAgente.objects.create(
                agente       = self.TIPO,
                telefono     = telefono,
                rol          = rol,
                contenido    = contenido,
                modelo_usado = modelo_usado,
                origen       = origen,
            )
        except Exception as e:
            log.error(f'[{self.TIPO}] Error guardando mensaje para {telefono}: {e}')

    # ── Prompt desde BD ───────────────────────────────────────────────────────

    def get_prompt(self) -> str | None:
        """
        Obtiene el prompt del sistema desde ConfigAgente.
        Retorna None si el agente no está activo o no tiene configuración.
        """
        from agente.models import ConfigAgente
        try:
            config = ConfigAgente.objects.get(agente=self.TIPO, activo=True)
            return config.prompt
        except ConfigAgente.DoesNotExist:
            log.warning(f'[{self.TIPO}] No hay ConfigAgente activo — usando prompt vacío')
            return None

    # ── Llamada a Gemini ──────────────────────────────────────────────────────

    def llamar_claude(
        self,
        historial: list[dict],
        system_prompt: str,
        modelo: str = MODELO_GEMINI,
        max_tokens: int = 600,
    ) -> str:
        """
        Llama a Gemini con el historial y el prompt del sistema.
        Mantiene el nombre 'llamar_claude' para no romper subclases existentes.
        Retorna el texto de la respuesta.
        Lanza excepciones — el llamador debe manejarlas.
        """
        get_client()  # asegura configuración
        model = genai.GenerativeModel(
            model_name=modelo,
            system_instruction=system_prompt,
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=max_tokens,
            ),
        )
        # Gemini espera el historial sin el último mensaje del usuario
        # El último mensaje se pasa como 'message' separado
        if historial and historial[-1]['role'] == 'user':
            ultimo_mensaje = historial[-1]['parts'][0]
            historial_previo = historial[:-1]
        else:
            # Si no hay mensaje de usuario al final, usar historial completo
            ultimo_mensaje = ''
            historial_previo = historial

        chat = model.start_chat(history=historial_previo)
        response = chat.send_message(ultimo_mensaje)
        return response.text.strip()

    # ── Fallback de error ─────────────────────────────────────────────────────

    def fallback_mensaje(self) -> str:
        """Mensaje de error estándar. Sobreescribir para personalizar."""
        return FALLBACK_ERROR

    # ── Log de respuesta ──────────────────────────────────────────────────────

    def log_respuesta(self, telefono: str, respuesta: str, extra: str = '') -> None:
        prefijo = f'[Agente {self.TIPO.capitalize()}]'
        info = f'{prefijo} {telefono}'
        if extra:
            info += f' | {extra}'
        log.info(f'{info} | {respuesta[:80]}')