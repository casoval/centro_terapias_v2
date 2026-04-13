from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.utils import timezone
from datetime import timedelta, datetime
from agenda.models import Sesion
from facturacion.models import CuentaCorriente
from decimal import Decimal

DIAS = ['Lunes','Martes','Miércoles','Jueves','Viernes','Sábado','Domingo']
MESES = ['enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre']

SUCURSAL_JAPON = 3
SUCURSAL_CAMACHO = 4


@api_view(['GET'])
def sesiones_proximas(request):
    sucursal_id = request.GET.get('sucursal')
    ahora = timezone.localtime()
    objetivo = ahora + timedelta(hours=2)

    # Ventana de ±5 minutos (segura porque sesiones son cada 15 min)
    desde = objetivo - timedelta(minutes=5)
    hasta = objetivo + timedelta(minutes=5)

    sesiones = Sesion.objects.filter(
        fecha=objetivo.date(),
        hora_inicio__gte=desde.time(),
        hora_inicio__lte=hasta.time(),
        estado='programada',
        mensualidad__isnull=True,
    ).select_related('paciente', 'profesional', 'servicio', 'sucursal').order_by('hora_inicio')

    if sucursal_id:
        sesiones = sesiones.filter(sucursal_id=sucursal_id)

    # Agrupar por tutor — un mensaje por tutor aunque tenga varios pacientes
    tutores = {}
    for sesion in sesiones:
        paciente = sesion.paciente
        telefono = paciente.telefono_tutor
        if not telefono:
            continue
        tipo = 'proyecto' if sesion.proyecto else 'individual'

        if telefono not in tutores:
            tutores[telefono] = {
                'tutor_nombre': paciente.nombre_tutor,
                'tutor_telefono': telefono,
                'sucursal': sesion.sucursal.nombre,
                'tipo': tipo,
                'sesiones': []
            }
        tutores[telefono]['sesiones'].append({
            'paciente_nombre': paciente.nombre_completo,
            'hora_inicio': sesion.hora_inicio.strftime('%H:%M'),
            'hora_fin': sesion.hora_fin.strftime('%H:%M'),
            'servicio': sesion.servicio.nombre,
            'profesional': f"{sesion.profesional.nombre} {sesion.profesional.apellido}",
        })

    data = []
    for telefono, tutor in tutores.items():
        sesiones_tutor = tutor['sesiones']
        if len(sesiones_tutor) == 1:
            s = sesiones_tutor[0]
            cuerpo = f"{s['paciente_nombre']} tiene su sesión de {s['servicio']} hoy a las {s['hora_inicio']}"
        else:
            cuerpo = "sus pacientes tienen sesiones hoy:\n" + "\n".join([f"• {s['paciente_nombre']} - {s['servicio']} a las {s['hora_inicio']}" for s in sesiones_tutor])

        mensaje = f"👋 Hola! Le recordamos que {cuerpo} en {tutor['sucursal']}. ¡Hasta pronto! 😊 neuromisael.com"

        data.append({
            'tutor_nombre': tutor['tutor_nombre'],
            'tutor_telefono': telefono,
            'sucursal': tutor['sucursal'],
            'mensaje': mensaje,
            'tipo': 'recordatorio',
        })

    return Response({'total': len(data), 'sesiones': data})


def _guardar_recordatorio(telefono: str, mensaje: str, tipo: str):
    """Helper: guarda un recordatorio enviado en ConversacionAgente."""
    try:
        from agente.models import ConversacionAgente
        tel = f'591{telefono}' if not telefono.startswith('591') else telefono
        ConversacionAgente.objects.create(
            agente       = 'paciente',
            telefono     = tel,
            rol          = 'assistant',
            contenido    = mensaje,
            modelo_usado = tipo,
        )
    except Exception:
        pass


@api_view(['GET'])
def mensualidades_semana(request):
    """
    Sesiones de mensualidad de la semana actual (lunes a domingo).
    Agrupadas por tutor — un solo mensaje por tutor con todos sus horarios.
    Separadas por sucursal.
    """
    sucursal_id = request.GET.get('sucursal')
    hoy = timezone.localdate()

    # Calcular lunes y domingo de la semana actual
    lunes = hoy + timedelta(days=(7 - hoy.weekday()))  # próximo lunes
    domingo = lunes + timedelta(days=6)

    sesiones = Sesion.objects.filter(
        fecha__range=[lunes, domingo],
        estado='programada',
        mensualidad__isnull=False,  # solo mensualidades
    ).select_related(
        'paciente', 'profesional', 'servicio', 'sucursal', 'mensualidad'
    ).order_by('fecha', 'hora_inicio')

    if sucursal_id:
        sesiones = sesiones.filter(sucursal_id=sucursal_id)

    # Agrupar por tutor (telefono_tutor)
    tutores = {}
    for sesion in sesiones:
        paciente = sesion.paciente
        telefono = paciente.telefono_tutor
        if not telefono:
            continue

        if telefono not in tutores:
            tutores[telefono] = {
                'tutor_nombre': paciente.nombre_tutor,
                'tutor_telefono': telefono,
                'sucursal': sesion.sucursal.nombre,
                'sesiones': []
            }

        tutores[telefono]['sesiones'].append({
            'paciente_nombre': paciente.nombre_completo,
            'dia': DIAS[sesion.fecha.weekday()],
            'fecha': f"{sesion.fecha.day} de {MESES[sesion.fecha.month - 1]}",
            'hora_inicio': sesion.hora_inicio.strftime('%H:%M'),
            'hora_fin': sesion.hora_fin.strftime('%H:%M'),
            'servicio': sesion.servicio.nombre,
            'profesional': f"{sesion.profesional.nombre} {sesion.profesional.apellido}",
        })

    data = []
    for telefono, tutor in tutores.items():
        # Agrupar sesiones por paciente
        pacientes_dict = {}
        for s in tutor['sesiones']:
            nombre = s['paciente_nombre']
            if nombre not in pacientes_dict:
                pacientes_dict[nombre] = []
            pacientes_dict[nombre].append(s)

        bloques = []
        for nombre_paciente, sesiones_paciente in pacientes_dict.items():
            lineas_paciente = "\n".join([
                f"  • {s['dia']} {s['fecha']}: {s['servicio']} a las {s['hora_inicio']}"
                for s in sesiones_paciente
            ])
            bloques.append(f"*{nombre_paciente}:*\n{lineas_paciente}")

        cuerpo = "\n\n".join(bloques)
        mensaje = f"👋 Hola! Le recordamos los horarios de la próxima semana en {tutor['sucursal']}:\n\n{cuerpo}\n\n¡Hasta pronto! 😊 neuromisael.com"
        tutor['mensaje'] = mensaje
        tutor['tipo'] = 'recordatorio'
        data.append(tutor)

    return Response({
        'semana_desde': str(lunes),
        'semana_hasta': str(domingo),
        'total_tutores': len(tutores),
        'tutores': data
    })


@api_view(['GET'])
def deudas_pendientes(request):
    """
    Retorna tutores con saldo proyectado pendiente (saldo_real < -1).
    Agrupa por teléfono del tutor — un mensaje por tutor aunque tenga varios hijos con deuda.
    Filtra por sucursal si se pasa ?sucursal=3 o ?sucursal=4.
    Construye el mensaje completo listo para enviar por WhatsApp.
    Usa saldo_real (incluye sesiones programadas y planificadas).
    """
    sucursal_id = request.GET.get('sucursal')

    cuentas = CuentaCorriente.objects.filter(
        paciente__estado='activo',
        saldo_real__lt=-1,  # deuda proyectada de al menos Bs. 1
    ).select_related('paciente').prefetch_related('paciente__sucursales').order_by('saldo_real')

    # Agrupar por teléfono del tutor
    tutores = {}
    for cuenta in cuentas:
        paciente = cuenta.paciente
        telefono = paciente.telefono_tutor
        if not telefono:
            continue

        # Determinar sucursal principal del paciente
        sucursales = list(paciente.sucursales.all())
        if len(sucursales) == 1:
            suc_id = sucursales[0].id
            suc_nombre = sucursales[0].nombre
        else:
            # Multi-sucursal: buscar la que tiene más sesiones
            from agenda.models import Sesion
            from django.db.models import Count
            resultado = Sesion.objects.filter(
                paciente=paciente,
                estado__in=['realizada', 'realizada_retraso']
            ).values('sucursal_id', 'sucursal__nombre').annotate(
                total=Count('id')
            ).order_by('-total').first()
            if resultado:
                suc_id = resultado['sucursal_id']
                suc_nombre = resultado['sucursal__nombre']
            elif sucursales:
                suc_id = sucursales[0].id
                suc_nombre = sucursales[0].nombre
            else:
                suc_id = SUCURSAL_JAPON
                suc_nombre = 'Suc. Japon'

        # Aplicar filtro de sucursal
        if sucursal_id and str(suc_id) != str(sucursal_id):
            continue

        deuda = abs(cuenta.saldo_real)

        if telefono not in tutores:
            tutores[telefono] = {
                'tutor_nombre': paciente.nombre_tutor,
                'tutor_telefono': telefono,
                'sucursal': suc_nombre,
                'sucursal_id': suc_id,
                'pacientes': []
            }

        tutores[telefono]['pacientes'].append({
            'nombre': paciente.nombre_completo,
            'deuda': deuda,
        })

    # Construir mensaje por tutor
    data = []
    for telefono, tutor in tutores.items():
        pacientes = tutor['pacientes']
        sucursal = tutor['sucursal']

        if len(pacientes) == 1:
            p = pacientes[0]
            detalle_deuda = (
                f"*{p['nombre']}* presenta un saldo pendiente de *Bs. {int(p['deuda'])}*"
            )
        else:
            lineas = "\n".join([
                f"• {p['nombre']}: Bs. {int(p['deuda'])}"
                for p in pacientes
            ])
            detalle_deuda = f"los siguientes pacientes presentan saldo pendiente:\n{lineas}"

        nombre_tutor = tutor['tutor_nombre'] or 'estimado tutor/a'
        mensaje = (
            f"👋 Hola, *{nombre_tutor}*! Esperamos que se encuentre muy bien. 😊\n\n"
            f"Le contactamos desde *{sucursal}* para informarle cordialmente que {detalle_deuda}.\n\n"
            f"💡 Para revisar el detalle de pagos, sesiones y deudas de forma rápida y sencilla, puede ingresar a su cuenta en nuestra página web: *neuromisael.com*\n\n"
            f"Si tiene alguna consulta que la página web no pueda resolver, le invitamos a apersonarse directamente a nuestras oficinas, donde nuestro equipo le atenderá con mucho gusto. 🙏\n\n"
            f"¡Gracias por su confianza y comprensión!"
        )

        data.append({
            'tutor_nombre': tutor['tutor_nombre'],
            'tutor_telefono': telefono,
            'sucursal': sucursal,
            'sucursal_id': tutor['sucursal_id'],
            'mensaje': mensaje,
            'tipo': 'recordatorio',
        })

    return Response({'total': len(data), 'deudas': data})


# ─────────────────────────────────────────────────────────────
# PROPUESTA 1 — Hitos de asistencia
# Cron: diariamente a las 20:00
# GET /recordatorios/hitos/?sucursal=3
# ─────────────────────────────────────────────────────────────
HITOS = {
    10:  ("🎉", "¡10 sesiones completadas!", "Llevan 10 sesiones juntos y eso ya se nota. El esfuerzo y la constancia de su familia están marcando una diferencia real en el proceso de {nombre_paciente}. ¡Gracias por confiar en nosotros!"),
    25:  ("⭐", "¡25 sesiones completadas!", "25 sesiones es un logro enorme. La continuidad que han mantenido es uno de los pilares más importantes en el desarrollo de {nombre_paciente}. El equipo del Centro Misael los admira y los acompaña con mucho orgullo."),
    50:  ("🏆", "¡50 sesiones completadas!", "50 sesiones es un hito extraordinario. Pocas familias llegan aquí y las que lo hacen son las que ven los cambios más profundos. Gracias por su dedicación, {nombre_tutor}. {nombre_paciente} tiene una familia increíble."),
    100: ("💫", "¡100 sesiones completadas!", "100 sesiones. Un número que habla solo. Gracias por estar siempre, por no rendirse, por creer en el proceso. Es un honor acompañar a {nombre_paciente} y a toda su familia en este camino."),
}

@api_view(['GET'])
def hitos_asistencia(request):
    """
    Detecta pacientes que completaron exactamente 10, 25, 50 o 100 sesiones hoy.
    Devuelve el mensaje listo para enviar por WhatsApp.
    Agregar al cron diariamente a las 20:00.
    """
    sucursal_id = request.GET.get('sucursal')
    hoy = timezone.localdate()

    from django.db.models import Count

    # Pacientes con sesión realizada hoy — sin distinct, usamos set para deduplicar
    sesiones_hoy = Sesion.objects.filter(
        estado__in=['realizada', 'realizada_retraso'],
        fecha=hoy,
    ).select_related('paciente', 'sucursal').order_by('paciente_id')

    # Deduplicar por paciente manualmente
    pacientes_vistos = set()
    sesiones_unicas = []
    for s in sesiones_hoy:
        if s.paciente_id not in pacientes_vistos:
            pacientes_vistos.add(s.paciente_id)
            sesiones_unicas.append(s)

    data = []
    for hito, (emoji, titulo, plantilla) in HITOS.items():
        for sesion_hoy in sesiones_unicas:

            if sucursal_id and str(sesion_hoy.sucursal_id) != str(sucursal_id):
                continue

            paciente = sesion_hoy.paciente
            total = Sesion.objects.filter(
                paciente=paciente,
                estado__in=['realizada', 'realizada_retraso'],
            ).count()

            if total != hito:
                continue

            telefono = paciente.telefono_tutor
            if not telefono:
                continue

            nombre_tutor = paciente.nombre_tutor or 'estimado tutor/a'
            nombre_paciente = paciente.nombre_completo

            mensaje_cuerpo = plantilla.format(
                nombre_tutor=nombre_tutor,
                nombre_paciente=nombre_paciente,
            )
            mensaje = (
                f"{emoji} *{titulo}*\n\n"
                f"Hola, *{nombre_tutor}*! 😊\n\n"
                f"{mensaje_cuerpo}\n\n"
                f"— Centro de Neurodesarrollo Misael 💙"
            )

            data.append({
                'tutor_nombre': nombre_tutor,
                'tutor_telefono': telefono,
                'paciente_nombre': nombre_paciente,
                'hito': hito,
                'sucursal': sesion_hoy.sucursal.nombre,
                'mensaje': mensaje,
                'tipo': 'recordatorio',
            })

    return Response({'total': len(data), 'hitos': data})


# ─────────────────────────────────────────────────────────────
# PROPUESTA 2 — Post-falta / Post-permiso  (endpoint manual)
# El signal en signals.py lo dispara automáticamente.
# POST /recordatorios/post-falta/   body: { "sesion_id": 123 }
# ─────────────────────────────────────────────────────────────
@api_view(['POST'])
def post_falta(request):
    """
    Recibe un sesion_id y devuelve el mensaje cálido para enviar al tutor
    cuando una sesión fue registrada como falta o permiso.
    Puede llamarse manualmente o desde el signal automático.
    """
    sesion_id = request.data.get('sesion_id')
    if not sesion_id:
        return Response({'error': 'sesion_id requerido'}, status=400)

    try:
        sesion = Sesion.objects.select_related(
            'paciente', 'servicio', 'profesional', 'sucursal'
        ).get(id=sesion_id)
    except Sesion.DoesNotExist:
        return Response({'error': 'Sesión no encontrada'}, status=404)

    if sesion.estado not in ('falta', 'permiso'):
        return Response({'error': f'La sesión tiene estado "{sesion.estado}", no es falta ni permiso'}, status=400)

    paciente = sesion.paciente
    telefono = paciente.telefono_tutor
    if not telefono:
        return Response({'error': 'El paciente no tiene teléfono de tutor registrado'}, status=400)

    nombre_tutor = paciente.nombre_tutor or 'estimado tutor/a'
    nombre_paciente = paciente.nombre_completo
    servicio = sesion.servicio.nombre
    fecha_str = f"{DIAS[sesion.fecha.weekday()]} {sesion.fecha.day} de {MESES[sesion.fecha.month - 1]}"

    if sesion.estado == 'permiso':
        mensaje = (
            f"Hola, *{nombre_tutor}*. 😊\n\n"
            f"Quedamos anotados del permiso de *{nombre_paciente}* para la sesión de {servicio} del {fecha_str}.\n\n"
            f"Esperamos que todo esté bien. Cuando quieran retomar, aquí estamos. "
            f"Recuerde que puede ver el detalle de sesiones y permisos en *neuromisael.com* 💙"
        )
    else:  # falta
        mensaje = (
            f"Hola, *{nombre_tutor}*. 😊\n\n"
            f"Notamos que *{nombre_paciente}* no pudo asistir a su sesión de {servicio} del {fecha_str}. "
            f"Esperamos que todo esté bien por casa.\n\n"
            f"La continuidad es muy importante en el proceso terapéutico — cada sesión tiene un propósito dentro del plan individual de {nombre_paciente}. "
            f"Cuando puedan, con gusto los esperamos. 🙏\n\n"
            f"— Centro de Neurodesarrollo Misael"
        )

    return Response({
        'tutor_nombre': nombre_tutor,
        'tutor_telefono': telefono,
        'paciente_nombre': nombre_paciente,
        'estado': sesion.estado,
        'sucursal': sesion.sucursal.nombre,
        'mensaje': mensaje,
        'tipo': 'recordatorio',
    })


# ─────────────────────────────────────────────────────────────
# PROPUESTA 3 — Orientación mensual
# Cron: día 1 de cada mes
# GET /recordatorios/orientacion-mensual/?sucursal=3
# ─────────────────────────────────────────────────────────────
TIPS_POR_TERAPIA = {
    'lenguaje': (
        "🗣️ *Tip del mes — Terapia de Lenguaje*\n\n"
        "Una cosa simple que pueden hacer en casa: hablen con {nombre_paciente} sobre lo que ven mientras caminan o hacen compras. "
        "Nombren los objetos, los colores, los sonidos. No necesitan materiales — solo unos minutos de conversación real. "
        "Eso refuerza directamente lo que trabaja en terapia. 💙"
    ),
    'ocupacional': (
        "✋ *Tip del mes — Terapia Ocupacional*\n\n"
        "Esta semana pueden darle a {nombre_paciente} una actividad con las manos: amasar plastilina, abrir y cerrar frascos, "
        "doblar ropa o ayudar con la cocina. Son tareas cotidianas que trabajan la coordinación y la autonomía — "
        "exactamente lo que se refuerza en terapia. 💙"
    ),
    'fisica': (
        "🏃 *Tip del mes — Terapia Física*\n\n"
        "Si pueden, dediquen 10 minutos al día a que {nombre_paciente} camine en diferentes superficies — pasto, arena, suelo irregular. "
        "También subir y bajar escaleras despacio. Son actividades sencillas que complementan muy bien el trabajo en terapia. 💙"
    ),
    'psicologia': (
        "💬 *Tip del mes — Psicología*\n\n"
        "Algo que ayuda mucho: al final del día, pregunten a {nombre_paciente} una sola cosa — '¿qué fue lo mejor de hoy?' "
        "No importa si la respuesta es corta. Ese pequeño ritual ayuda a procesar emociones y a sentirse escuchado. 💙"
    ),
    'neurologia': (
        "🧠 *Tip del mes — Seguimiento Neurológico*\n\n"
        "Lleven un registro breve esta semana: anoten si {nombre_paciente} tuvo cambios en el sueño, el apetito o el comportamiento. "
        "No necesitan ser detallistas — basta con una nota al día. Esa información es muy valiosa en la próxima consulta. 💙"
    ),
    'aprendizaje': (
        "📚 *Tip del mes — Apoyo al Aprendizaje*\n\n"
        "Una estrategia sencilla: cuando {nombre_paciente} tenga que aprender algo nuevo, divídanlo en pasos muy pequeños "
        "y celebren cada uno por separado. El cerebro aprende mejor con logros frecuentes que con metas lejanas. 💙"
    ),
    'conductual': (
        "🌟 *Tip del mes — Intervención Conductual*\n\n"
        "Esta semana, elijan una sola conducta positiva de {nombre_paciente} y nómbrenla en voz alta cuando ocurra: "
        "'¡Qué bien que esperaste tu turno!' La atención positiva específica refuerza mucho más que el elogio general. 💙"
    ),
    'sensorial': (
        "🎨 *Tip del mes — Integración Sensorial*\n\n"
        "Pueden preparar una pequeña 'caja sensorial' en casa: arroz, botones, telas diferentes, esponjas. "
        "Dejen que {nombre_paciente} explore con las manos sin presión. Son 10 minutos que complementan directamente lo que trabaja en terapia. 💙"
    ),
    'comunicacion': (
        "💡 *Tip del mes — Comunicación Aumentativa*\n\n"
        "En casa, acompañen siempre las palabras con gestos o imágenes cuando se dirijan a {nombre_paciente}. "
        "No es dar un paso atrás — es abrir más canales de comunicación al mismo tiempo. Eso acelera el proceso. 💙"
    ),
    'default': (
        "💙 *Tip del mes — Centro Misael*\n\n"
        "Un recordatorio simple: la constancia en casa multiplica los resultados de cada sesión. "
        "No hace falta hacer mucho — con unos minutos diarios de atención enfocada en {nombre_paciente}, "
        "el proceso avanza mucho más rápido. ¡Gracias por su esfuerzo y dedicación! 🙏"
    ),
}

def _detectar_terapia(nombre_servicio: str) -> str:
    nombre = nombre_servicio.lower()
    if 'lenguaje' in nombre or 'fonoaudiología' in nombre or 'fono' in nombre:
        return 'lenguaje'
    if 'ocupacional' in nombre:
        return 'ocupacional'
    if 'física' in nombre or 'fisica' in nombre or 'físico' in nombre:
        return 'fisica'
    if 'psicolog' in nombre:
        return 'psicologia'
    if 'neurolog' in nombre:
        return 'neurologia'
    if 'aprendizaje' in nombre or 'aprender' in nombre:
        return 'aprendizaje'
    if 'conduct' in nombre:
        return 'conductual'
    if 'sensorial' in nombre or 'integración' in nombre:
        return 'sensorial'
    if 'comunicación' in nombre or 'comunicacion' in nombre or 'aumentativ' in nombre:
        return 'comunicacion'
    return 'default'

@api_view(['GET'])
def orientacion_mensual(request):
    """
    Detecta la terapia principal de cada paciente activo y devuelve
    un tip practico personalizado.
    Controla duplicados usando cache en Django para evitar envios dobles.
    Agregar al cron el dia 1 de cada mes.
    GET /recordatorios/orientacion-mensual/?sucursal=3
    """
    from django.db.models import Count
    from django.core.cache import cache
    sucursal_id = request.GET.get('sucursal')

    # Clave de cache para este mes y sucursal
    from django.utils import timezone
    hoy = timezone.localdate()
    cache_key = f"orientacion_mensual_{hoy.year}_{hoy.month}_suc{sucursal_id or 'todas'}"

    if cache.get(cache_key):
        return Response({'total': 0, 'orientaciones': [], 'nota': 'Ya enviado este mes para esta sucursal'})

    # Pacientes activos con al menos una sesion realizada
    from pacientes.models import Paciente
    pacientes = Paciente.objects.filter(estado='activo').prefetch_related('sucursales')

    data = []
    vistos = set()  # evitar duplicados por telefono

    for paciente in pacientes:
        telefono = paciente.telefono_tutor
        if not telefono or telefono in vistos:
            continue

        # Filtrar por sucursal si se pide
        if sucursal_id:
            sucursales_ids = list(paciente.sucursales.values_list('id', flat=True))
            if int(sucursal_id) not in sucursales_ids:
                continue

        # Servicio mas frecuente del paciente
        servicio_top = Sesion.objects.filter(
            paciente=paciente,
            estado__in=['realizada', 'realizada_retraso'],
        ).values('servicio__nombre').annotate(
            total=Count('id')
        ).order_by('-total').first()

        nombre_servicio = servicio_top['servicio__nombre'] if servicio_top else ''
        clave_terapia = _detectar_terapia(nombre_servicio)
        plantilla = TIPS_POR_TERAPIA[clave_terapia]

        nombre_tutor = paciente.nombre_tutor or 'estimado tutor/a'
        nombre_paciente = paciente.nombre_completo

        tip = plantilla.format(nombre_paciente=nombre_paciente)
        mensaje = f"Hola, *{nombre_tutor}*! 😊\n\n{tip}"

        vistos.add(telefono)
        data.append({
            'tutor_nombre': nombre_tutor,
            'tutor_telefono': telefono,
            'paciente_nombre': nombre_paciente,
            'terapia_detectada': clave_terapia,
            'mensaje': mensaje,
            'tipo': 'recordatorio',
        })

    # Marcar como enviado para este mes (expira en 32 dias)
    if data:
        cache.set(cache_key, True, 60 * 60 * 24 * 32)

    return Response({'total': len(data), 'orientaciones': data})

# ─────────────────────────────────────────────────────────────
# RECEPTOR — el bot Node.js llama aquí después de enviar
# un recordatorio generado por los endpoints de esta API.
# POST /recordatorios/api/registrar-enviado/
# Body: { "telefono": "59176543210", "mensaje": "...", "tipo": "recordatorio-cita" }
# ─────────────────────────────────────────────────────────────

from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
import json as _json

@csrf_exempt
def registrar_recordatorio_enviado(request):
    """
    Llamar desde Node.js justo después de enviar cada recordatorio.
    Registra el mensaje en ConversacionAgente para que sea visible
    en el panel de conversaciones del agente.

    Ejemplo en Node.js (agregar después de cada client.sendMessage):
        await fetch('http://localhost:8000/recordatorios/api/registrar-enviado/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                telefono: '59176543210',
                mensaje: mensajeEnviado,
                tipo: 'recordatorio-cita',
                // tipo puede ser: recordatorio-cita | recordatorio-deuda |
                //                 recordatorio-hito | recordatorio-orientacion |
                //                 recordatorio-mensualidades
            })
        });
    """
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Metodo no permitido'}, status=405)

    try:
        data = _json.loads(request.body)
    except Exception:
        return JsonResponse({'ok': False, 'error': 'JSON invalido'}, status=400)

    telefono = data.get('telefono', '').strip()
    mensaje  = data.get('mensaje',  '').strip()
    tipo     = data.get('tipo',     'recordatorio').strip()

    if not telefono or not mensaje:
        return JsonResponse({'ok': False, 'error': 'Faltan campos: telefono y mensaje son requeridos'}, status=400)

    _guardar_recordatorio(telefono, mensaje, tipo)
    return JsonResponse({'ok': True})