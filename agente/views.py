import json
import logging
import requests

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# WEBHOOK — recibe mensajes entrantes desde el bot Node.js
# ─────────────────────────────────────────────────────────────

@csrf_exempt
def whatsapp_entrante(request):
    """
    Recibe mensajes entrantes desde el bot Node.js.
    Maneja tanto mensajes de texto como notas de voz.
 
    Payload para texto:
    {
        "telefono": "59176543210",
        "mensaje": "Hola quiero información...",
        "sucursal_id": 3
    }
 
    Payload para nota de voz:
    {
        "telefono": "59176543210",
        "tipo": "audio",
        "audio_url": "http://localhost:3000/audio/archivo.ogg",
        "sucursal_id": 3
    }
    """
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Método no permitido'}, status=405)
 
    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({'ok': False, 'error': 'JSON inválido'}, status=400)
 
    telefono    = data.get('telefono', '').strip()
    sucursal_id = int(data.get('sucursal_id', 3))
    tipo        = data.get('tipo', 'texto')  # 'texto' o 'audio'
 
    if not telefono:
        return JsonResponse({'ok': False, 'error': 'Falta telefono'}, status=400)
 
    from agente.models import ModoHumano, SucursalIA
 
    # 1. Verificar control global de la sucursal
    if not SucursalIA.esta_activa(sucursal_id):
        log.info(f'[Entrante] IA suspendida para sucursal {sucursal_id} — ignorado')
        return JsonResponse({'ok': True, 'modo': 'suspendido', 'telefono': telefono})
 
    # 2. Verificar modo humano individual
    modo, _ = ModoHumano.objects.get_or_create(
        telefono=telefono,
        defaults={'sucursal_id': sucursal_id, 'modo_humano': False}
    )
    if modo.modo_humano:
        log.info(f'[Entrante] {telefono} en modo humano — ignorado')
        return JsonResponse({'ok': True, 'modo': 'humano', 'telefono': telefono})
 
    es_audio = tipo == 'audio'
    mensaje  = None
    ruta_audio_entrada = None
 
    # 3. Procesar según tipo de mensaje
    if es_audio:
        audio_url = data.get('audio_url', '').strip()
        if not audio_url:
            return JsonResponse({'ok': False, 'error': 'Falta audio_url'}, status=400)
 
        log.info(f'[Entrante] Nota de voz de {telefono} — transcribiendo...')
 
        # Descargar el audio desde el bot Node.js
        ruta_audio_entrada = _descargar_audio(audio_url)
        if not ruta_audio_entrada:
            return JsonResponse({'ok': False, 'error': 'No se pudo descargar el audio'}, status=500)
 
        # Transcribir con Groq Whisper
        from agente.voz import transcribir_audio
        mensaje = transcribir_audio(ruta_audio_entrada)
 
        if not mensaje:
            # Si falla la transcripción, responder con texto
            es_audio = False
            mensaje  = '[Nota de voz no transcrita]'
            log.warning(f'[Entrante] Transcripción fallida para {telefono}')
        else:
            log.info(f'[Entrante] {telefono} transcrito: {mensaje[:80]}')
 
    else:
        mensaje = data.get('mensaje', '').strip()
        if not mensaje:
            return JsonResponse({'ok': False, 'error': 'Falta mensaje'}, status=400)
        log.info(f'[Entrante] {telefono}: {mensaje[:80]}')
 
    # 4. Detectar si es paciente registrado o público
    from agente.paciente_db import buscar_paciente_por_telefono
 
    paciente = buscar_paciente_por_telefono(telefono)
 
    if paciente:
        # Agente Paciente — tutor registrado en el sistema
        log.info(f'[Entrante] {telefono} identificado como paciente: {paciente.nombre} {paciente.apellido}')
        from agente.paciente import responder as responder_paciente
        respuesta_texto = responder_paciente(telefono, mensaje, paciente)
    else:
        # Agente Público — consulta nueva
        log.info(f'[Entrante] {telefono} no registrado — Agente Público')
        from agente.publico import responder
        respuesta_texto = responder(telefono, mensaje)
 
    # 5. Enviar respuesta
    puerto = 3000 if sucursal_id == 3 else 3001
    telefono_limpio = telefono[3:] if telefono.startswith('591') else telefono
 
    if es_audio:
        # Convertir respuesta a audio y enviar nota de voz
        _enviar_respuesta_voz(telefono_limpio, respuesta_texto, puerto)
    else:
        # Enviar respuesta como texto
        _enviar_respuesta_texto(telefono_limpio, respuesta_texto, puerto)
 
    # Limpiar archivo temporal si existe
    if ruta_audio_entrada:
        import os as _os
        try:
            _os.unlink(ruta_audio_entrada)
        except Exception:
            pass
 
    return JsonResponse({'ok': True, 'telefono': telefono, 'respuesta': respuesta_texto[:100]})

# ─────────────────────────────────────────────────────────────
# WEBHOOK — staff respondió manualmente → activa modo humano
# ─────────────────────────────────────────────────────────────

@csrf_exempt
def staff_respondio(request):
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Método no permitido'}, status=405)

    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({'ok': False, 'error': 'JSON inválido'}, status=400)

    telefono    = data.get('telefono', '').strip()
    sucursal_id = int(data.get('sucursal_id', 3))

    if not telefono:
        return JsonResponse({'ok': False, 'error': 'Falta telefono'}, status=400)

    from agente.models import ModoHumano
    modo, _ = ModoHumano.objects.get_or_create(
        telefono=telefono,
        defaults={'sucursal_id': sucursal_id}
    )

    if not modo.modo_humano:
        modo.modo_humano  = True
        modo.sucursal_id  = sucursal_id
        modo.activado_por = 'staff (automático)'
        modo.activado_en  = timezone.now()
        modo.save()
        log.info(f'[ModoHumano] Activado automáticamente para {telefono}')

    return JsonResponse({'ok': True, 'telefono': telefono, 'modo_humano': True})


# ─────────────────────────────────────────────────────────────
# API — toggle modo humano individual
# ─────────────────────────────────────────────────────────────

@csrf_exempt
@login_required
def toggle_modo_humano(request):
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Método no permitido'}, status=405)

    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({'ok': False, 'error': 'JSON inválido'}, status=400)

    telefono   = data.get('telefono', '').strip()
    modo_nuevo = data.get('modo_humano', False)

    if not telefono:
        return JsonResponse({'ok': False, 'error': 'Falta telefono'}, status=400)

    from agente.models import ModoHumano
    modo, _ = ModoHumano.objects.get_or_create(telefono=telefono)
    modo.modo_humano  = modo_nuevo
    modo.activado_por = request.user.get_full_name() or request.user.username
    if modo_nuevo:
        modo.activado_en = timezone.now()
    modo.save()

    log.info(f'[ModoHumano] {telefono} → {"humano" if modo_nuevo else "bot"} por {modo.activado_por}')
    return JsonResponse({'ok': True, 'telefono': telefono, 'modo_humano': modo_nuevo})


# ─────────────────────────────────────────────────────────────
# API — toggle IA global por sucursal
# ─────────────────────────────────────────────────────────────

@csrf_exempt
@login_required
def toggle_ia_sucursal(request):
    """
    Activa o suspende la IA para toda una sucursal.
    POST { "sucursal_id": 3, "ia_activa": false }
    """
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Método no permitido'}, status=405)

    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({'ok': False, 'error': 'JSON inválido'}, status=400)

    sucursal_id = int(data.get('sucursal_id', 3))
    ia_activa   = data.get('ia_activa', True)

    from agente.models import SucursalIA
    obj, _ = SucursalIA.objects.get_or_create(sucursal_id=sucursal_id)
    obj.ia_activa    = ia_activa
    obj.cambiado_por = request.user.get_full_name() or request.user.username
    obj.save()

    nombre = 'Sede Japón' if sucursal_id == 3 else 'Sede Camacho'
    log.info(f'[SucursalIA] {nombre} → {"activa" if ia_activa else "suspendida"} por {obj.cambiado_por}')
    return JsonResponse({'ok': True, 'sucursal_id': sucursal_id, 'ia_activa': ia_activa})


# ─────────────────────────────────────────────────────────────
# API — estado global de las sucursales
# ─────────────────────────────────────────────────────────────

@login_required
def api_estado_sucursales(request):
    """Devuelve el estado IA de ambas sucursales."""
    from agente.models import SucursalIA
    resultado = {}
    for sid in [3, 4]:
        obj, _ = SucursalIA.objects.get_or_create(
            sucursal_id=sid,
            defaults={'ia_activa': True}
        )
        resultado[str(sid)] = {
            'ia_activa':    obj.ia_activa,
            'cambiado_por': obj.cambiado_por,
            'cambiado_en':  obj.cambiado_en.isoformat() if obj.cambiado_en else None,
        }
    return JsonResponse({'ok': True, 'sucursales': resultado})


# ─────────────────────────────────────────────────────────────
# API — lista de conversaciones
# ─────────────────────────────────────────────────────────────

@login_required
def api_conversaciones(request):
    from agente.models import ConversacionAgente, ModoHumano
    from django.db.models import Max, Count
    from agente.paciente_db import buscar_paciente_por_telefono

    # Incluir todos los agentes (publico y paciente)
    telefonos_qs = (
        ConversacionAgente.objects
        .values('telefono')
        .annotate(ultimo=Max('creado'), total=Count('id'))
        .order_by('-ultimo')
    )

    # Deduplicar teléfonos preservando el más reciente
    telefonos_dict = {}
    for t in telefonos_qs:
        tel = t['telefono']
        if tel not in telefonos_dict:
            telefonos_dict[tel] = {'ultimo': t['ultimo'], 'total': t['total']}
        else:
            if t['ultimo'] > telefonos_dict[tel]['ultimo']:
                telefonos_dict[tel]['ultimo'] = t['ultimo']
            telefonos_dict[tel]['total'] += t['total']

    modos = {m.telefono: m for m in ModoHumano.objects.all()}

    conversaciones = []
    for tel, t in telefonos_dict.items():
        ultimo_msg = (
            ConversacionAgente.objects
            .filter(telefono=tel)
            .order_by('-creado')
            .first()
        )
        modo = modos.get(tel)

        # Determinar si es paciente registrado en el sistema
        paciente = buscar_paciente_por_telefono(tel)
        es_paciente = paciente is not None

        conversaciones.append({
            'telefono':        tel,
            'ultimo_msg':      ultimo_msg.contenido[:80] if ultimo_msg else '',
            'ultimo_rol':      ultimo_msg.rol if ultimo_msg else '',
            'ultimo_en':       ultimo_msg.creado.isoformat() if ultimo_msg else '',
            'total_msgs':      t['total'],
            'modo_humano':     modo.modo_humano if modo else False,
            'sucursal_id':     modo.sucursal_id if modo else 3,
            'es_paciente':     es_paciente,
            'nombre_paciente': f'{paciente.nombre} {paciente.apellido}' if es_paciente else '',
            'nombre_tutor':    paciente.nombre_tutor if es_paciente else '',
        })

    # Ordenar por más reciente
    conversaciones.sort(key=lambda x: x['ultimo_en'], reverse=True)
    return JsonResponse({'ok': True, 'conversaciones': conversaciones})


@login_required
def api_historial_telefono(request, telefono):
    from agente.models import ConversacionAgente
    mensajes = (
        ConversacionAgente.objects
        .filter(agente='publico', telefono=telefono)
        .order_by('creado')
        .values('rol', 'contenido', 'modelo_usado', 'creado')
    )
    data = [
        {
            'rol':     m['rol'],
            'contenido': m['contenido'],
            'modelo':  m['modelo_usado'],
            'creado':  m['creado'].isoformat(),
        }
        for m in mensajes
    ]
    return JsonResponse({'ok': True, 'telefono': telefono, 'mensajes': data})


@login_required
def api_historial_telefono_all(request, telefono):
    """Historial completo (todos los agentes) para un número."""
    from agente.models import ConversacionAgente
    mensajes = (
        ConversacionAgente.objects
        .filter(telefono=telefono)
        .order_by('creado')
        .values('rol', 'contenido', 'modelo_usado', 'creado', 'agente')
    )
    data = [
        {
            'rol':       m['rol'],
            'contenido': m['contenido'],
            'modelo':    m['modelo_usado'],
            'creado':    m['creado'].isoformat(),
            'agente':    m['agente'],
        }
        for m in mensajes
    ]
    return JsonResponse({'ok': True, 'telefono': telefono, 'mensajes': data})


# ─────────────────────────────────────────────────────────────
# API — enviar mensaje manual desde el panel
# ─────────────────────────────────────────────────────────────

@csrf_exempt
@login_required
def api_enviar_manual(request):
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Método no permitido'}, status=405)

    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({'ok': False, 'error': 'JSON inválido'}, status=400)

    telefono    = data.get('telefono', '').strip()
    mensaje     = data.get('mensaje', '').strip()
    sucursal_id = int(data.get('sucursal_id', 3))

    if not telefono or not mensaje:
        return JsonResponse({'ok': False, 'error': 'Faltan datos'}, status=400)

    puerto = 3000 if sucursal_id == 3 else 3001
    try:
        requests.post(
            f'http://localhost:{puerto}/send',
            json={
                'telefono':   telefono,
                'mensaje':    mensaje,
                'paciente':   'Respuesta manual',
                'sucursal':   'Staff',
                'delay_type': 'corto',
            },
            timeout=5,
        )
        # Guardar en historial
        from agente.models import ConversacionAgente
        tel_completo = f'591{telefono}' if not telefono.startswith('591') else telefono
        ConversacionAgente.objects.create(
            agente='publico',
            telefono=tel_completo,
            rol='assistant',
            contenido=f'[Staff] {mensaje}',
            modelo_usado='manual',
        )
        return JsonResponse({'ok': True})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)


# ─────────────────────────────────────────────────────────────
# PANEL — vista principal
# ─────────────────────────────────────────────────────────────

@login_required
def panel_conversaciones(request):
    return render(request, 'agente/conversaciones.html')

def _descargar_audio(url: str) -> str | None:
    """Descarga un archivo de audio y lo guarda temporalmente."""
    import tempfile
    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            ext = 'ogg'
            if 'mp3' in url:
                ext = 'mp3'
            elif 'wav' in url:
                ext = 'wav'
            with tempfile.NamedTemporaryFile(suffix=f'.{ext}', delete=False, dir='/tmp') as f:
                f.write(response.content)
                return f.name
    except Exception as e:
        log.error(f'[Entrante] Error al descargar audio: {e}')
    return None
 
 
def _enviar_respuesta_texto(telefono: str, mensaje: str, puerto: int):
    """Envía respuesta de texto via bot Node.js."""
    try:
        requests.post(
            f'http://localhost:{puerto}/send',
            json={
                'telefono':   telefono,
                'mensaje':    mensaje,
                'paciente':   'Consulta nueva',
                'sucursal':   'Agente Público',
                'delay_type': 'corto',
            },
            timeout=5,
        )
        log.info(f'[Entrante] Texto enviado a {telefono}')
    except Exception as e:
        log.error(f'[Entrante] Error al enviar texto a {telefono}: {e}')
 
 
def _enviar_respuesta_voz(telefono: str, texto: str, puerto: int):
    """Convierte texto a audio ogg y envía nota de voz via bot Node.js."""
    import os as _os
    try:
        from agente.voz import texto_a_voz

        # texto_a_voz ahora devuelve ruta del archivo ogg/opus
        ruta_audio = texto_a_voz(texto)
        if not ruta_audio:
            log.warning(f'[Voz] Fallo TTS para {telefono} — enviando texto como respaldo')
            _enviar_respuesta_texto(telefono, texto, puerto)
            return

        # Enviar al bot Node.js
        requests.post(
            f'http://localhost:{puerto}/send-audio',
            json={
                'telefono':   telefono,
                'ruta_audio': ruta_audio,
            },
            timeout=10,
        )
        log.info(f'[Voz] Audio ogg enviado a {telefono}')

        # Limpiar archivo temporal
        try:
            _os.unlink(ruta_audio)
        except Exception:
            pass

    except Exception as e:
        log.error(f'[Voz] Error al enviar audio a {telefono}: {e}')
        _enviar_respuesta_texto(telefono, texto, puerto)