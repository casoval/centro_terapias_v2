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
from google.generativeai.types import HarmCategory, HarmBlockThreshold

log = logging.getLogger('agente')

MODELO_GEMINI = 'gemini-2.5-flash'

# Mensaje de fallback estándar cuando ocurre un error técnico
FALLBACK_ERROR = (
    'Disculpe, tuve un problema técnico. '
    'Por favor comuníquese directamente con nosotros:\n'
    'Sede Japón: +591 76175352\n'
    'Sede Camacho: +591 78633975'
)

# ── Safety settings ───────────────────────────────────────────────────────────
# Sin esto, Gemini puede bloquear respuestas sobre TEA, TDAH, medicación,
# crisis emocionales, diagnósticos, etc.
SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_HARASSMENT:        HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH:       HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# ── Temperatura por tipo de agente ────────────────────────────────────────────
# Más baja = respuestas más precisas y consistentes (agentes internos)
# Más alta = respuestas más cálidas y naturales (agentes de cara al tutor)
TEMPERATURA_POR_AGENTE = {
    'publico':       0.7,   # cálido y empático con los tutores
    'paciente':      0.7,   # ídem — atiende tutores con hijos registrados
    'recepcionista': 0.3,   # preciso, datos operativos
    'profesional':   0.3,   # clínico, preciso
    'gerente':       0.2,   # ejecutivo, datos exactos
    'superusuario':  0.2,   # máxima precisión para el dueño
}

# ── Thinking budget por tipo de agente ───────────────────────────────────────
# Tokens de razonamiento interno de Gemini.
# 0 = desactivado (más rápido), >0 = mejor calidad en consultas complejas.
THINKING_BUDGET_POR_AGENTE = {
    'publico':       2000,  # consultas emocionales y clínicas
    'paciente':      2000,  # puede preguntar cosas complejas sobre su hijo
    'recepcionista': 1024,  # consultas operativas
    'profesional':   2000,  # análisis clínico
    'gerente':       3000,  # análisis financiero y estratégico
    'superusuario':  5000,  # máximo — informes y análisis profundos
}

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
        Retorna lista en formato Gemini: {role: 'user'|'model', parts: [texto]}
        """
        from agente.models import ConversacionAgente
        limite = self.get_max_historial()
        mensajes = (
            ConversacionAgente.objects
            .filter(agente=self.TIPO, telefono=telefono)
            .order_by('-creado')[:limite]
        )
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
        Aplica temperatura y thinking budget según el tipo de agente.
        """
        get_client()  # asegura configuración

        temperatura     = TEMPERATURA_POR_AGENTE.get(self.TIPO, 0.4)
        thinking_budget = THINKING_BUDGET_POR_AGENTE.get(self.TIPO, 1024)

        generation_config = genai.types.GenerationConfig(
            max_output_tokens = max_tokens,
            temperature       = temperatura,
            thinking_config   = genai.types.ThinkingConfig(
                thinking_budget = thinking_budget,
            ),
        )

        model = genai.GenerativeModel(
            model_name        = modelo,
            system_instruction = system_prompt,
            safety_settings   = SAFETY_SETTINGS,
            generation_config = generation_config,
        )

        # Gemini: el último mensaje del usuario se pasa como 'message' separado
        if historial and historial[-1]['role'] == 'user':
            ultimo_mensaje   = historial[-1]['parts'][0]
            historial_previo = historial[:-1]
        else:
            ultimo_mensaje   = ''
            historial_previo = historial

        chat     = model.start_chat(history=historial_previo)
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
