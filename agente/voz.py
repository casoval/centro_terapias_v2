"""
agente/voz.py
Módulo de voz para el Agente Público.

Funciones:
- transcribir_audio(): Convierte nota de voz (ogg/mp3) a texto usando Groq Whisper
- texto_a_voz(): Convierte texto a audio ogg/opus listo para WhatsApp (via ElevenLabs + ffmpeg)
"""

import os
import logging
import subprocess
import tempfile
import requests

log = logging.getLogger('agente')

# ── Configuración ─────────────────────────────────────────────────────────────
ELEVENLABS_API_KEY  = os.environ.get('ELEVENLABS_API_KEY', '')
ELEVENLABS_VOICE_ID = os.environ.get('ELEVENLABS_VOICE_ID', 'pNInz6obpgDQGcFmaJgB')
GROQ_API_KEY        = os.environ.get('GROQ_API_KEY', '')


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
        log.info(f'[Voz] Transcripción exitosa: {texto[:60]}')
        return texto

    except Exception as e:
        log.error(f'[Voz] Error al transcribir audio: {e}')
        return None


# ── Síntesis de voz → audio ogg/opus (ElevenLabs + ffmpeg) ──────────────────

def texto_a_voz(texto: str) -> str | None:
    """
    Convierte texto a audio ogg/opus listo para enviar como nota de voz en WhatsApp.

    Flujo:
        texto → ElevenLabs (mp3) → ffmpeg → ogg/opus → ruta del archivo

    Args:
        texto: Texto a convertir en voz

    Returns:
        Ruta al archivo ogg/opus temporal, o None si falla
    """
    try:
        # 1. Generar audio mp3 con ElevenLabs
        url = f'https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}'
        r = requests.post(
            url,
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

        if r.status_code != 200:
            log.error(f'[Voz] Error ElevenLabs: {r.status_code} — {r.text[:200]}')
            return None

        # 2. Guardar mp3 temporal
        mp3_fd, mp3_path = tempfile.mkstemp(suffix='.mp3', dir='/tmp')
        with os.fdopen(mp3_fd, 'wb') as f:
            f.write(r.content)
        log.info(f'[Voz] MP3 generado ({len(r.content)} bytes) — convirtiendo a ogg/opus')

        # 3. Convertir mp3 → ogg/opus con ffmpeg (requerido por WhatsApp)
        ogg_path = mp3_path.replace('.mp3', '.ogg')
        resultado = subprocess.run(
            ['ffmpeg', '-y', '-i', mp3_path, '-c:a', 'libopus', '-b:a', '64k', ogg_path],
            capture_output=True,
            text=True,
        )
        os.unlink(mp3_path)

        if resultado.returncode != 0:
            log.error(f'[Voz] Error ffmpeg: {resultado.stderr[-300:]}')
            return None

        log.info(f'[Voz] Audio ogg/opus listo: {ogg_path}')
        return ogg_path

    except Exception as e:
        log.error(f'[Voz] Error inesperado en texto_a_voz: {e}')
        return None