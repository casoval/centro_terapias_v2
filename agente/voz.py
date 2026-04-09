"""
agente/voz.py
Módulo de voz para el Agente Público.

Funciones:
- transcribir_audio(): Convierte nota de voz (ogg/mp3) a texto usando Groq Whisper
- texto_a_voz(): Convierte texto a audio usando ElevenLabs
"""

import os
import logging
import tempfile
import requests

log = logging.getLogger(__name__)

# ── Configuración ─────────────────────────────────────────────────────────────
ELEVENLABS_API_KEY = os.environ.get('ELEVENLABS_API_KEY')
ELEVENLABS_VOICE_ID = os.environ.get('ELEVENLABS_VOICE_ID')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')

ELEVENLABS_URL = f'https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}'


# ── Transcripción de audio → texto (Groq Whisper) ────────────────────────────

def transcribir_audio(ruta_audio: str) -> str | None:
    """
    Transcribe un archivo de audio a texto usando Groq Whisper.

    Args:
        ruta_audio: Ruta local al archivo de audio (ogg, mp3, wav, etc.)

    Returns:
        Texto transcrito o None si falla
    """
    try:
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY)

        with open(ruta_audio, 'rb') as f:
            transcripcion = client.audio.transcriptions.create(
                file=(os.path.basename(ruta_audio), f),
                model='whisper-large-v3',
                language='es',
                response_format='text',
            )

        texto = transcripcion.strip() if isinstance(transcripcion, str) else transcripcion.text.strip()
        log.info(f'[Voz] Transcripción exitosa: {texto[:60]}...')
        return texto

    except Exception as e:
        log.error(f'[Voz] Error al transcribir audio: {e}')
        return None


# ── Síntesis de voz → audio (ElevenLabs) ─────────────────────────────────────

def texto_a_voz(texto: str) -> bytes | None:
    """
    Convierte texto a audio usando ElevenLabs.

    Args:
        texto: Texto a convertir en voz

    Returns:
        Bytes del audio MP3 o None si falla
    """
    try:
        response = requests.post(
            ELEVENLABS_URL,
            headers={
                'xi-api-key': ELEVENLABS_API_KEY,
                'Content-Type': 'application/json',
            },
            json={
                'text': texto,
                'model_id': 'eleven_flash_v2_5',
                'voice_settings': {
                    'stability': 0.5,
                    'similarity_boost': 0.75,
                },
            },
            timeout=30,
        )

        if response.status_code == 200:
            log.info(f'[Voz] Audio generado exitosamente ({len(response.content)} bytes)')
            return response.content
        else:
            log.error(f'[Voz] Error ElevenLabs: {response.status_code} — {response.text[:100]}')
            return None

    except Exception as e:
        log.error(f'[Voz] Error al generar audio: {e}')
        return None


def guardar_audio_temp(audio_bytes: bytes, extension: str = 'mp3') -> str | None:
    """
    Guarda bytes de audio en un archivo temporal.

    Args:
        audio_bytes: Bytes del audio
        extension: Extensión del archivo (mp3, ogg, etc.)

    Returns:
        Ruta al archivo temporal o None si falla
    """
    try:
        with tempfile.NamedTemporaryFile(
            suffix=f'.{extension}',
            delete=False,
            dir='/tmp'
        ) as f:
            f.write(audio_bytes)
            return f.name
    except Exception as e:
        log.error(f'[Voz] Error al guardar audio temporal: {e}')
        return None
