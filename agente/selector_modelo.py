"""
agente/selector_modelo.py
Sistema inteligente de selección de modelo para el Agente Público.
Combina múltiples criterios para elegir entre Haiku (rápido) y Sonnet (complejo).
"""

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

# ── Modelos ───────────────────────────────────────────────────────────────────
MODELO_RAPIDO   = 'claude-haiku-4-5-20251001'
MODELO_COMPLETO = 'claude-sonnet-4-6'

# ── Palabras clave por categoría ──────────────────────────────────────────────

PALABRAS_EMOCIONALES = [
    'llorar', 'llorando', 'llora', 'desesperado', 'desesperada', 'desesperacion',
    'no se que hacer', 'no sé qué hacer', 'no aguanto', 'ya no puedo',
    'me preocupa mucho', 'muy preocupado', 'muy preocupada',
    'angustia', 'angustiado', 'angustiada', 'angustiante',
    'miedo', 'asustado', 'asustada', 'aterrado', 'aterrada',
    'sufre', 'sufriendo', 'sufrimiento', 'años sufriendo',
    'no duerme', 'no come', 'no habla con nadie',
    'crisis', 'colapso', 'berrinche', 'rabieta',
    'golpea', 'se golpea', 'muerde', 'se muerde', 'se lastima',
    'agresivo', 'agresiva', 'violento', 'violenta',
    'triste', 'deprimido', 'deprimida', 'solo', 'sola', 'aislado', 'aislada',
]

PALABRAS_DIAGNOSTICO = [
    'autismo', 'tea', 'tdah', 'adhd', 'asperger',
    'retraso', 'retraso mental', 'retraso madurativo',
    'sindrome', 'síndrome', 'down',
    'diagnostico', 'diagnóstico', 'diagnosticado', 'diagnosticada',
    'evaluacion previa', 'evaluación previa',
    'otro medico', 'otro médico', 'especialista dijo', 'doctor dijo',
    'ya tiene', 'le dijeron', 'le detectaron',
    'terapia antes', 'ya fue a terapia', 'ya lleva terapia',
    'discapacidad', 'necesidades especiales',
]

PALABRAS_URGENCIA = [
    'urgente', 'urgencia', 'por favor', 'porfavor', 'ayuda',
    'necesito ayuda', 'auxilio', 'emergencia',
    'ya no sé', 'ya no se', 'no aguanto más', 'no aguanto mas',
    'desesperada', 'desesperado', 'al límite', 'al limite',
    'lo antes posible', 'cuanto antes', 'hoy mismo',
]

PALABRAS_EDAD_TEMPRANA = [
    'meses', 'mes de edad', 'recien nacido', 'recién nacido',
    'bebe', 'bebé', 'lactante',
    '1 año', 'un año', 'año y medio',
    '2 años', 'dos años',
    'estimulacion temprana', 'estimulación temprana',
]

PALABRAS_ESCUELA = [
    'colegio', 'escuela', 'kinder', 'jardín', 'jardin', 'inicial',
    'maestra', 'profesor', 'profesora', 'docente',
    'bullying', 'acoso', 'se burlan', 'lo molestan', 'la molestan',
    'no tiene amigos', 'no juega con otros', 'no se relaciona',
    'expulsado', 'problemas en el colegio', 'problemas en la escuela',
    'rendimiento', 'no aprende', 'dificultad para aprender',
]


@dataclass
class ResultadoSelector:
    modelo: str
    razon: str
    puntaje: int
    es_sonnet: bool


def analizar_mensaje(mensaje: str, telefono: str) -> ResultadoSelector:
    """
    Analiza un mensaje y decide qué modelo usar.
    Devuelve el modelo elegido y la razón de la elección.
    """
    texto = mensaje.lower().strip()
    palabras = texto.split()
    razones = []
    puntaje = 0

    # ── Criterio 1: Primera vez que escribe ───────────────────────────────────
    es_primera_vez = _es_primera_vez(telefono)
    if es_primera_vez:
        puntaje += 3
        razones.append('primera vez')

    # ── Criterio 2: Historial largo (conversación en curso) ───────────────────
    total_mensajes = _contar_mensajes(telefono)
    if total_mensajes >= 6:
        puntaje += 3
        razones.append(f'conversación larga ({total_mensajes} msgs)')
    elif total_mensajes >= 3:
        puntaje += 1
        razones.append(f'conversación en curso ({total_mensajes} msgs)')

    # ── Criterio 3: Longitud del mensaje ──────────────────────────────────────
    num_palabras = len(palabras)
    if num_palabras >= 30:
        puntaje += 3
        razones.append(f'mensaje muy largo ({num_palabras} palabras)')
    elif num_palabras >= 20:
        puntaje += 2
        razones.append(f'mensaje largo ({num_palabras} palabras)')

    # ── Criterio 4: Palabras emocionales ─────────────────────────────────────
    emocionales_encontradas = [p for p in PALABRAS_EMOCIONALES if p in texto]
    if emocionales_encontradas:
        puntaje += 4
        razones.append(f'emocional: {", ".join(emocionales_encontradas[:3])}')

    # ── Criterio 5: Menciona diagnóstico previo ───────────────────────────────
    diagnostico_encontrado = [p for p in PALABRAS_DIAGNOSTICO if p in texto]
    if diagnostico_encontrado:
        puntaje += 4
        razones.append(f'diagnóstico: {", ".join(diagnostico_encontrado[:2])}')

    # ── Criterio 6: Urgencia ──────────────────────────────────────────────────
    urgencia_encontrada = [p for p in PALABRAS_URGENCIA if p in texto]
    if urgencia_encontrada:
        puntaje += 5  # máxima prioridad
        razones.append(f'urgencia: {", ".join(urgencia_encontrada[:2])}')

    # ── Criterio 7: Edad temprana ─────────────────────────────────────────────
    edad_encontrada = [p for p in PALABRAS_EDAD_TEMPRANA if p in texto]
    if edad_encontrada:
        puntaje += 3
        razones.append(f'edad temprana: {", ".join(edad_encontrada[:2])}')

    # ── Criterio 8: Problemas escolares o sociales ────────────────────────────
    escuela_encontrada = [p for p in PALABRAS_ESCUELA if p in texto]
    if escuela_encontrada:
        puntaje += 3
        razones.append(f'escuela/social: {", ".join(escuela_encontrada[:2])}')

    # ── Criterio 9: Múltiples preguntas ───────────────────────────────────────
    num_preguntas = texto.count('?')
    if num_preguntas >= 2:
        puntaje += 2
        razones.append(f'{num_preguntas} preguntas')

    # ── Decisión final ────────────────────────────────────────────────────────
    # Umbral: puntaje >= 5 → Sonnet
    # (subido de 3 a 5 para evitar que la primera vez sola active Sonnet)
    es_sonnet = puntaje >= 5
    modelo = MODELO_COMPLETO if es_sonnet else MODELO_RAPIDO
    razon_final = ' | '.join(razones) if razones else 'mensaje simple'

    log.info(
        f'[Selector] {telefono} | puntaje={puntaje} | '
        f'modelo={"Sonnet" if es_sonnet else "Haiku"} | {razon_final}'
    )

    return ResultadoSelector(
        modelo=modelo,
        razon=razon_final,
        puntaje=puntaje,
        es_sonnet=es_sonnet,
    )


def _es_primera_vez(telefono: str) -> bool:
    """Devuelve True si el tutor nunca ha escrito antes."""
    try:
        from agente.models import ConversacionAgente
        return not ConversacionAgente.objects.filter(
            agente='publico',
            telefono=telefono
        ).exists()
    except Exception:
        return False


def _contar_mensajes(telefono: str) -> int:
    """Cuenta cuántos mensajes lleva la conversación."""
    try:
        from agente.models import ConversacionAgente
        return ConversacionAgente.objects.filter(
            agente='publico',
            telefono=telefono
        ).count()
    except Exception:
        return 0