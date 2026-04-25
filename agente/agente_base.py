"""
agente/agente_base.py
Clase base con lógica común para todos los agentes del sistema.

Evita repetir en cada agente:
- Inicialización del cliente Anthropic
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
import anthropic

log = logging.getLogger('agente')

# Mensaje de fallback estándar cuando ocurre un error técnico
FALLBACK_ERROR = (
    'Disculpe, tuve un problema técnico. '
    'Por favor comuníquese directamente con nosotros:\n'
    'Sede Japón: +591 76175352\n'
    'Sede Camacho: +591 78633975'
)

_client = None


def get_client() -> anthropic.Anthropic:
    """Cliente Anthropic singleton — se inicializa una sola vez."""
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))
    return _client


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
    def client(self) -> anthropic.Anthropic:
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
        Retorna lista de dicts {role, content} lista para enviar a Claude.
        """
        from agente.models import ConversacionAgente
        limite = self.get_max_historial()
        mensajes = (
            ConversacionAgente.objects
            .filter(agente=self.TIPO, telefono=telefono)
            .order_by('-creado')[:limite]
        )
        # Invertir para que queden en orden cronológico (más antiguo primero)
        return [
            {'role': m.rol, 'content': m.contenido}
            for m in reversed(list(mensajes))
        ]

    # ── Guardar mensajes ──────────────────────────────────────────────────────

    def guardar_mensaje(
        self,
        telefono: str,
        rol: str,
        contenido: str,
        modelo_usado: str = '',
        origen: str = 'whatsapp',   # ← único cambio
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
                origen       = origen,          # ← único cambio
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

    # ── Llamada a Claude ──────────────────────────────────────────────────────

    def llamar_claude(
        self,
        historial: list[dict],
        system_prompt: str,
        modelo: str,
        max_tokens: int = 600,
    ) -> str:
        """
        Llama a Claude con el historial y el prompt del sistema.
        Retorna el texto de la respuesta.
        Lanza excepciones — el llamador debe manejarlas.
        """
        response = self.client.messages.create(
            model      = modelo,
            max_tokens = max_tokens,
            system     = system_prompt,
            messages   = historial,
        )
        return response.content[0].text.strip()

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
