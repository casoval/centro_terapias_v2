"""
agente/voz.py
Modulo de voz para el Agente Publico.

Funciones:
- transcribir_audio(): Convierte nota de voz (ogg/mp3) a texto usando Groq Whisper
- texto_a_voz(): Convierte texto a audio ogg/opus listo para WhatsApp (via Inworld TTS + ffmpeg)
"""

import os
import logging
import subprocess
import tempfile
import base64
import json
import requests

log = logging.getLogger('agente')

# Configuracion
def _inworld_key():
    return os.environ.get('INWORLD_API_KEY', '')

def _inworld_voice():
    return os.environ.get('INWORLD_VOICE_ID', 'default-58vxpseedhdrbc3xtv9jma__design-voice-843732bf')

def _groq_key():
    return os.environ.get('GROQ_API_KEY', '')


def transcribir_audio(ruta_audio: str):
    """
    Transcribe un archivo de audio a texto usando Groq Whisper.
    """
    try:
        from groq import Groq
        client = Groq(api_key=_groq_key())

        with open(ruta_audio, 'rb') as f:
            transcripcion = client.audio.transcriptions.create(
                file=(os.path.basename(ruta_audio), f),
                model='whisper-large-v3',
                language='es',
                response_format='text',
            )

        texto = transcripcion.strip() if isinstance(transcripcion, str) else transcripcion.text.strip()
        log.info(f'[Voz] Transcripcion exitosa: {texto[:60]}')
        return texto

    except Exception as e:
        log.error(f'[Voz] Error al transcribir audio: {e}')
        return None


def texto_a_voz(texto: str):
    """
    Convierte texto a audio ogg/opus via Inworld TTS + ffmpeg.
    Inworld devuelve chunks JSON con audioContent en base64.
    """
    try:
        r = requests.post(
            'https://api.inworld.ai/tts/v1/voice:stream',
            headers={
                'Authorization': f'Basic {_inworld_key()}',
                'Content-Type': 'application/json',
            },
            json={
                'text': texto,
                'voice_id': _inworld_voice(),
                'audio_config': {
                    'audio_encoding': 'MP3',
                    'speaking_rate': 1,
                },
                'temperature': 1,
                'model_id': 'inworld-tts-1.5-max',
            },
            stream=True,
            timeout=30,
        )

        if r.status_code != 200:
            log.error(f'[Voz] Error Inworld TTS: {r.status_code} — {r.text[:200]}')
            return None

        # Recolectar chunks base64 y decodificar a MP3
        audio_bytes = bytearray()
        for linea in r.iter_lines(decode_unicode=True):
            if not linea:
                continue
            try:
                data = json.loads(linea)
                b64 = (
                    data.get('result', {}).get('audioContent')
                    or data.get('audioContent')
                    or data.get('audio_content')
                )
                if b64:
                    audio_bytes.extend(base64.b64decode(b64))
            except Exception:
                continue

        if not audio_bytes:
            log.error('[Voz] Inworld TTS no devolvio audio')
            return None

        log.info(f'[Voz] MP3 generado ({len(audio_bytes)} bytes) — convirtiendo a ogg/opus')

        # Guardar MP3 temporal y convertir a ogg/opus con ffmpeg
        mp3_fd, mp3_path = tempfile.mkstemp(suffix='.mp3', dir='/tmp')
        ogg_path = mp3_path.replace('.mp3', '.ogg')
        try:
            with os.fdopen(mp3_fd, 'wb') as f:
                f.write(audio_bytes)

            resultado = subprocess.run(
                ['ffmpeg', '-y', '-i', mp3_path, '-c:a', 'libopus', '-b:a', '64k', ogg_path],
                capture_output=True,
                text=True,
            )
        finally:
            # Siempre limpiar el MP3 temporal, haya fallado o no
            try:
                os.unlink(mp3_path)
            except Exception:
                pass

        if resultado.returncode != 0:
            log.error(f'[Voz] Error ffmpeg: {resultado.stderr[-300:]}')
            # Limpiar ogg si quedó a medias
            try:
                os.unlink(ogg_path)
            except Exception:
                pass
            return None

        log.info(f'[Voz] Audio ogg/opus listo: {ogg_path}')
        return ogg_path

    except Exception as e:
        log.error(f'[Voz] Error inesperado en texto_a_voz: {e}')
        return None