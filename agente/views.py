import json
import logging
import os
import requests

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

log = logging.getLogger(__name__)

# Token secreto para autenticar webhooks del bot Node.js.
# Configurar: WEBHOOK_SECRET_TOKEN en variables de entorno.
# El bot Node.js debe enviar header: X-Webhook-Token: <token>
WEBHOOK_SECRET_TOKEN = os.environ.get('WEBHOOK_SECRET_TOKEN', '')


def _verificar_token(request) -> bool:
    """Verifica que el request venga del bot autorizado."""
    if not WEBHOOK_SECRET_TOKEN:
        log.warning('[Webhook] WEBHOOK_SECRET_TOKEN no configurado — sin autenticación')
        return True
    return request.headers.get('X-Webhook-Token', '') == WEBHOOK_SECRET_TOKEN


def _normalizar_telefono(telefono: str) -> str:
    """Normaliza el teléfono al formato canónico '591XXXXXXX' usado en toda la BD."""
    tel = telefono.strip()
    if not tel.startswith('591'):
        tel = '591' + tel
    return tel


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

    # Autenticación
    if not _verificar_token(request):
        log.warning(f'[Entrante] Token inválido desde {request.META.get("REMOTE_ADDR")}')
        return JsonResponse({'ok': False, 'error': 'No autorizado'}, status=401)

    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({'ok': False, 'error': 'JSON inválido'}, status=400)

    telefono    = data.get('telefono', '').strip()
    sucursal_id = int(data.get('sucursal_id', 3))
    tipo        = data.get('tipo', 'texto')

    if not telefono:
        return JsonResponse({'ok': False, 'error': 'Falta telefono'}, status=400)

    from agente.models import ModoHumano, SucursalIA

    # 1. Control global de sucursal
    if not SucursalIA.esta_activa(sucursal_id):
        log.info(f'[Entrante] IA suspendida sucursal {sucursal_id}')
        return JsonResponse({'ok': True, 'modo': 'suspendido', 'telefono': telefono})

    # 2. Modo humano individual
    modo, _ = ModoHumano.objects.get_or_create(
        telefono=telefono,
        defaults={'sucursal_id': sucursal_id, 'modo_humano': False}
    )
    if modo.modo_humano:
        log.info(f'[Entrante] {telefono} en modo humano — ignorado')
        return JsonResponse({'ok': True, 'modo': 'humano', 'telefono': telefono})

    es_audio           = tipo == 'audio'
    mensaje            = None
    ruta_audio_entrada = None

    # 3. Procesar tipo de mensaje
    if es_audio:
        audio_url = data.get('audio_url', '').strip()
        if not audio_url:
            return JsonResponse({'ok': False, 'error': 'Falta audio_url'}, status=400)

        ruta_audio_entrada = _descargar_audio(audio_url)
        if not ruta_audio_entrada:
            return JsonResponse({'ok': False, 'error': 'No se pudo descargar el audio'}, status=500)

        from agente.voz import transcribir_audio
        mensaje = transcribir_audio(ruta_audio_entrada)

        if not mensaje:
            # Fallback: avisar al usuario en lugar de ignorar
            es_audio = False
            log.warning(f'[Entrante] Transcripción fallida para {telefono}')
            puerto = 3000 if sucursal_id == 3 else 3001
            tel_limpio = telefono[3:] if telefono.startswith('591') else telefono
            _enviar_respuesta_texto(
                tel_limpio,
                'No pude escuchar tu nota de voz. ¿Puedes escribirme tu consulta? 🎙️',
                puerto,
            )
            if ruta_audio_entrada:
                import os as _os
                try: _os.unlink(ruta_audio_entrada)
                except Exception: pass
            return JsonResponse({'ok': True, 'telefono': telefono, 'fallback': 'audio_no_transcrito'})
        else:
            log.info(f'[Entrante] {telefono} transcrito: {mensaje[:80]}')
    else:
        mensaje = data.get('mensaje', '').strip()
        if not mensaje:
            return JsonResponse({'ok': False, 'error': 'Falta mensaje'}, status=400)
        log.info(f'[Entrante] {telefono}: {mensaje[:80]}')

    # 4. Ruteo inteligente de agentes
    respuesta_texto = _rutear_agente(telefono, mensaje)

    # 5. Enviar respuesta
    puerto      = 3000 if sucursal_id == 3 else 3001
    tel_limpio  = telefono[3:] if telefono.startswith('591') else telefono

    if es_audio:
        _enviar_respuesta_voz(tel_limpio, respuesta_texto, puerto)
    else:
        _enviar_respuesta_texto(tel_limpio, respuesta_texto, puerto)

    if ruta_audio_entrada:
        import os as _os
        try: _os.unlink(ruta_audio_entrada)
        except Exception: pass

    return JsonResponse({'ok': True, 'telefono': telefono, 'respuesta': respuesta_texto[:100]})

# ─────────────────────────────────────────────────────────────
# RUTEO DE AGENTES — lógica central de identificación
# ─────────────────────────────────────────────────────────────

def _rutear_agente(telefono: str, mensaje: str) -> str:
    """
    Identifica quién escribe y despacha al agente correcto.

    Orden de prioridad:
      1. Staff identificado (superusuario > gerente > recepcionista+prof > recepcionista > profesional)
      2. Paciente activo con tutor registrado
      3. Público (desconocido o inactivo)
    """
    from agente.staff_db import identificar_staff

    staff = identificar_staff(telefono)

    if staff.tipo_agente:
        log.info(f'[Ruteo] {telefono} → {staff.tipo_agente} ({staff.nombre})')

        if staff.tipo_agente == 'superusuario':
            from agente.superusuario import responder
            return responder(telefono, mensaje, staff=staff)

        elif staff.tipo_agente == 'gerente':
            from agente.gerente import responder
            return responder(telefono, mensaje, staff=staff)

        elif staff.tipo_agente == 'recepcionista_profesional':
            # Combinado: acceso clínico (profesional) + financiero (recepcionista)
            from agente.superusuario import responder_combinado
            return responder_combinado(telefono, mensaje, staff=staff)

        elif staff.tipo_agente == 'recepcionista':
            from agente.recepcionista import responder
            return responder(telefono, mensaje, staff=staff)

        elif staff.tipo_agente == 'profesional':
            from agente.profesional import responder
            return responder(telefono, mensaje, staff=staff)

    # No es staff — verificar si es tutor de paciente ACTIVO
    try:
        from agente.paciente_db import buscar_paciente_y_tutor
        paciente, cual_tutor = buscar_paciente_y_tutor(telefono)

        if paciente:
            # Verificar que el paciente sigue activo
            if getattr(paciente, 'estado', 'activo') != 'activo':
                log.info(
                    f'[Ruteo] {telefono} → Paciente INACTIVO '
                    f'({paciente.nombre} {paciente.apellido}) → Agente Público'
                )
            else:
                log.info(
                    f'[Ruteo] {telefono} → Agente Paciente '
                    f'({paciente.nombre} {paciente.apellido}, {cual_tutor})'
                )
                from agente.paciente import responder
                return responder(telefono, mensaje, paciente, cual_tutor=cual_tutor)
    except Exception as e:
        log.error(f'[Ruteo] Error verificando paciente: {e}')

    # Número desconocido, inactivo o sin identificar → Agente Público
    log.info(f'[Ruteo] {telefono} → Agente Público')
    from agente.publico import responder
    return responder(telefono, mensaje)


# ─────────────────────────────────────────────────────────────
# WEBHOOK — staff respondió manualmente → activa modo humano
# ─────────────────────────────────────────────────────────────

@csrf_exempt
def staff_respondio(request):
    """
    Webhook llamado por el bot Node.js cuando el staff responde
    desde su celular físico (NUMEROS_IGNORAR con msg.to).

    Payload:
    {
        "telefono":    "59176543210",   ← destinatario (el tutor)
        "sucursal_id": 3,
        "mensaje":     "Texto enviado"  ← contenido del mensaje (nuevo)
    }

    Hace dos cosas:
    1. Activa modo humano para ese número
    2. Guarda el mensaje en ConversacionAgente para verlo en el panel
    """
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Método no permitido'}, status=405)

    if not _verificar_token(request):
        log.warning(f'[Staff] Token inválido desde {request.META.get("REMOTE_ADDR")}')
        return JsonResponse({'ok': False, 'error': 'No autorizado'}, status=401)

    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({'ok': False, 'error': 'JSON inválido'}, status=400)

    telefono    = data.get('telefono', '').strip()
    sucursal_id = int(data.get('sucursal_id', 3))
    mensaje     = data.get('mensaje', '').strip()   # nuevo campo

    if not telefono:
        return JsonResponse({'ok': False, 'error': 'Falta telefono'}, status=400)

    from agente.models import ModoHumano, ConversacionAgente
    from agente.paciente_db import buscar_paciente_por_telefono

    # 1. Activar modo humano
    modo, _ = ModoHumano.objects.get_or_create(
        telefono=telefono,
        defaults={'sucursal_id': sucursal_id}
    )
    if not modo.modo_humano:
        modo.modo_humano  = True
        modo.sucursal_id  = sucursal_id
        modo.activado_por = 'staff (celular físico)'
        modo.activado_en  = timezone.now()
        modo.save()
        log.info(f'[ModoHumano] Activado automáticamente para {telefono}')

    # 2. Guardar el mensaje en el historial si viene con contenido
    if mensaje:
        tel_completo = _normalizar_telefono(telefono)
        # Determinar si es paciente o público para la etiqueta correcta
        paciente = buscar_paciente_por_telefono(tel_completo)
        tipo_agente = 'paciente' if paciente else 'publico'
        ConversacionAgente.objects.create(
            agente       = tipo_agente,
            telefono     = tel_completo,
            rol          = 'assistant',
            contenido    = f'[Celular] {mensaje}',
            modelo_usado = 'celular',
        )
        log.info(f'[Staff-Celular] Mensaje guardado para {telefono} ({tipo_agente})')

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
    from agente.paciente_db import buscar_paciente_y_tutor

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

        # Determinar si es paciente registrado y qué tutor es
        paciente, cual_tutor = buscar_paciente_y_tutor(tel)
        es_paciente = paciente is not None

        # Mostrar el nombre del tutor que corresponde a ese número
        if es_paciente:
            if cual_tutor == 'tutor_2':
                nombre_tutor_display = getattr(paciente, 'nombre_tutor_2', None) or paciente.nombre_tutor
            else:
                nombre_tutor_display = paciente.nombre_tutor
        else:
            nombre_tutor_display = ''

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
            'nombre_tutor':    nombre_tutor_display,
            'cual_tutor':      cual_tutor or '',
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
    tel = _normalizar_telefono(telefono)
    mensajes = (
        ConversacionAgente.objects
        .filter(telefono=tel)
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

    # Guardar en historial SIEMPRE, antes de intentar enviar al bot
    from agente.models import ConversacionAgente
    from agente.paciente_db import buscar_paciente_por_telefono
    tel_completo = _normalizar_telefono(telefono)
    try:
        paciente_db = buscar_paciente_por_telefono(tel_completo)
        tipo_agente = 'paciente' if paciente_db else 'publico'
        ConversacionAgente.objects.create(
            agente       = tipo_agente,
            telefono     = tel_completo,
            rol          = 'assistant',
            contenido    = f'[Staff] {mensaje}',
            modelo_usado = 'manual',
        )
    except Exception as e:
        log.error(f'[Staff Manual] Error guardando mensaje en BD: {e}', exc_info=True)
        return JsonResponse({'ok': False, 'error': f'Error al guardar en historial: {e}'}, status=500)

    # Enviar al bot — si falla, el mensaje ya quedó guardado en BD
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
    except Exception as e:
        log.warning(f'[Staff Manual] Bot no respondio (mensaje guardado en BD): {e}')
        return JsonResponse({
            'ok': True,
            'aviso': 'Guardado en historial, pero el bot no respondio. Verifica que el bot Node.js este activo.',
        })

    return JsonResponse({'ok': True})


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
                'tipo':       'ia',
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