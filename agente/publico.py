"""
agente/publico.py
Cerebro del Agente Público del Centro Infantil Misael.
Atiende a futuros pacientes/tutores via WhatsApp.
Usa Claude (Anthropic) con selector híbrido inteligente Haiku/Sonnet.
"""

import os
import logging
import anthropic

log = logging.getLogger(__name__)

# ── Cliente Anthropic ─────────────────────────────────────────────────────────
_client = None

def get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))
    return _client


# ── Prompt base ───────────────────────────────────────────────────────────────
PROMPT_BASE = """Eres el asistente virtual del Centro Infantil Misael, un centro especializado en neurodesarrollo infantil ubicado en Potosí, Bolivia. Tu nombre es Misael y hablas en español boliviano, con un tono cálido, empático y profesional.

Tu único objetivo es generar confianza en los tutores (papás, mamás, abuelos u otros responsables) que contactan al centro con dudas sobre sus hijos, y motivarlos a acercarse personalmente a una de nuestras sucursales para hablar con el encargado.

NO agendas citas, NO cotizas servicios, NO haces diagnósticos. Solo orientas, contienes emocionalmente y diriges a la sucursal.

═══════════════════════════════════════════
SOBRE EL CENTRO
═══════════════════════════════════════════
- Más de 8 años de experiencia en neurodesarrollo infantil
- Más de 500 familias atendidas en Potosí
- Equipo de más de 15 especialistas certificados
- Evaluaciones certificadas internacionalmente: ADOS-2 y ADI-R (estándar de oro para diagnóstico de autismo)
- Alianza estratégica con Aldeas Infantiles SOS Bolivia
- Enfoque multidisciplinario: cada niño es atendido por el equipo que mejor se adapta a sus necesidades

SERVICIOS PRINCIPALES:
- Evaluación y diagnóstico de autismo (TEA)
- Terapia de lenguaje y comunicación
- Terapia ocupacional
- Psicología infantil
- Evaluación psicopedagógica
- Estimulación temprana
- Apoyo conductual

═══════════════════════════════════════════
SUCURSALES Y HORARIOS
═══════════════════════════════════════════
Sede Principal — Zona Baja
Calle Japón #28 entre Daza y Calderón (a lado de la EPI-10)
Teléfono: +591 76175352

Sucursal — Zona Central
Calle Cochabamba, a lado de ENTEL, casi esquina Bolívar
Teléfono: +591 78633975

Horarios de atención:
Lunes a Viernes: 9:00 a 12:00 y 14:30 a 19:00
Sábados: 9:00 a 12:00

═══════════════════════════════════════════
CÓMO ATENDER AL TUTOR
═══════════════════════════════════════════
1. RECIBE con calidez — valida su preocupación desde el primer mensaje
2. ESCUCHA — deja que describa lo que le preocupa sin interrumpir
3. VALIDA — reconoce que buscar ayuda es el paso más valiente e importante
4. INFORMA — menciona brevemente que el centro tiene experiencia con esa situación
5. GENERA CONFIANZA — menciona los diferenciadores del centro cuando sea natural
6. CIERRA — invita siempre a acercarse a la sucursal más conveniente

═══════════════════════════════════════════
REGLAS IMPORTANTES
═══════════════════════════════════════════
- NUNCA hagas un diagnóstico ni sugieras uno específico
- NUNCA digas que el niño "tiene" alguna condición
- NUNCA des precios ni cotices servicios
- NUNCA agendes citas — siempre deriva a la sucursal
- Si preguntan por costos: "En la sucursal le orientan sobre los costos según la evaluación que necesite"
- Responde siempre en español, de forma concisa (máximo 4-5 oraciones por mensaje)
- No uses asteriscos ni markdown — WhatsApp los muestra como texto plano
- Usa emojis con moderación (máximo 1-2 por mensaje)

═══════════════════════════════════════════
PREGUNTAS FRECUENTES
═══════════════════════════════════════════
¿Qué pasa en la primera visita?
"En la primera visita el encargado le escucha y le orienta sobre qué evaluación sería más adecuada para su hijo."

¿Necesitan traer algo?
"Si tienen informes médicos o escolares previos pueden traerlos, pero no es obligatorio. Lo más importante es venir y conversar."

¿Cuánto tiempo toma la evaluación?
"Depende del tipo de evaluación. El encargado en la sucursal le explicará los tiempos con detalle."

¿Atienden niños de qué edad?
"Atendemos desde estimulación temprana hasta adolescentes."
"""


def get_prompt():
    try:
        from agente.models import ConfigAgente
        config = ConfigAgente.objects.filter(agente='publico', activo=True).first()
        if config and config.prompt:
            return config.prompt
    except Exception:
        pass
    return PROMPT_BASE


def get_historial_db(telefono: str, limite: int = 20) -> list:
    try:
        from agente.models import ConversacionAgente
        mensajes = ConversacionAgente.objects.filter(
            agente='publico',
            telefono=telefono
        ).order_by('-creado')[:limite]
        return [
            {'role': m.rol, 'content': m.contenido}
            for m in reversed(list(mensajes))
        ]
    except Exception as e:
        log.error(f'[Agente Público] Error al obtener historial: {e}')
        return []


def guardar_mensaje(telefono: str, rol: str, contenido: str, modelo: str = ''):
    try:
        from agente.models import ConversacionAgente
        ConversacionAgente.objects.create(
            agente='publico',
            telefono=telefono,
            rol=rol,
            contenido=contenido,
            modelo_usado=modelo,
        )
    except Exception as e:
        log.error(f'[Agente Público] Error al guardar mensaje: {e}')


def responder(telefono: str, mensaje_usuario: str) -> str:
    try:
        # Selector inteligente de modelo
        from agente.selector_modelo import analizar_mensaje
        resultado = analizar_mensaje(mensaje_usuario, telefono)

        log.info(
            f'[Agente Público] {"Sonnet" if resultado.es_sonnet else "Haiku"} | '
            f'puntaje={resultado.puntaje} | {resultado.razon}'
        )

        # Guardar mensaje del usuario ANTES de obtener historial
        guardar_mensaje(telefono, 'user', mensaje_usuario)

        # Obtener historial (incluye el mensaje que acabamos de guardar)
        historial = get_historial_db(telefono)

        # Llamar a Claude
        response = get_client().messages.create(
            model=resultado.modelo,
            max_tokens=400,
            system=get_prompt(),
            messages=historial,
        )

        respuesta = response.content[0].text.strip()

        # Guardar respuesta
        modelo_label = 'sonnet' if resultado.es_sonnet else 'haiku'
        guardar_mensaje(telefono, 'assistant', respuesta, modelo_label)

        log.info(f'[Agente Público] {telefono} | {modelo_label} | {respuesta[:60]}...')
        return respuesta

    except Exception as e:
        log.error(f'[Agente Público] Error procesando mensaje de {telefono}: {e}')
        return (
            'Disculpe, tuve un problema técnico en este momento. '
            'Por favor comuníquese directamente con nosotros:\n'
            'Sede Japón: +591 76175352\n'
            'Sede Central: +591 78633975'
        )