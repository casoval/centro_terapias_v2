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
def citas_manana(request):
    """LEGACY - mantener por compatibilidad"""
    manana = timezone.localdate() + timedelta(days=1)
    sesiones = Sesion.objects.filter(
        fecha=manana,
        estado='programada'
    ).select_related('paciente', 'profesional', 'servicio', 'sucursal').order_by('hora_inicio')

    data = []
    for sesion in sesiones:
        paciente = sesion.paciente
        data.append({
            'paciente_nombre': paciente.nombre_completo,
            'tutor_nombre': paciente.nombre_tutor,
            'tutor_telefono': paciente.telefono_tutor,
            'fecha': f"{DIAS[sesion.fecha.weekday()]}, {sesion.fecha.day} de {MESES[sesion.fecha.month - 1]} de {sesion.fecha.year}",
            'hora_inicio': str(sesion.hora_inicio),
            'servicio': sesion.servicio.nombre,
            'profesional': f"{sesion.profesional.nombre} {sesion.profesional.apellido}",
            'sucursal': sesion.sucursal.nombre,
        })

    return Response({'total_sesiones': len(data), 'sesiones': data})

@api_view(['GET'])
def sesiones_proximas(request):
    sucursal_id = request.GET.get('sucursal')
    ahora = timezone.localtime()
    objetivo = ahora + timedelta(hours=2)

    # Ventana de ±1 minuto para evitar duplicados
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
        sesiones = tutor['sesiones']
        if len(sesiones) == 1:
            s = sesiones[0]
            cuerpo = f"{s['paciente_nombre']} tiene su sesión de {s['servicio']} hoy a las {s['hora_inicio']}"
        else:
            cuerpo = "sus pacientes tienen sesiones hoy:\n" + "\n".join([f"• {s['paciente_nombre']} - {s['servicio']} a las {s['hora_inicio']}" for s in sesiones])

        mensaje = f"👋 Hola! Le recordamos que {cuerpo} en {tutor['sucursal']}. ¡Hasta pronto! 😊 neuromisael.com"

        data.append({
            'tutor_nombre': tutor['tutor_nombre'],
            'tutor_telefono': telefono,
            'sucursal': tutor['sucursal'],
            'mensaje': mensaje,
        })

    return Response({'total': len(data), 'sesiones': data})

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

    return Response({
        'semana_desde': str(lunes),
        'semana_hasta': str(domingo),
        'total_tutores': len(tutores),
        'tutores': list(tutores.values())
    })


@api_view(['GET'])
def deudas_pendientes(request):
    cuentas = CuentaCorriente.objects.filter(
        paciente__estado='activo',
        saldo_real__lt=0
    ).select_related('paciente').order_by('saldo_real')

    data = []
    for cuenta in cuentas:
        paciente = cuenta.paciente
        deuda = abs(cuenta.saldo_real)
        data.append({
            'paciente_nombre': paciente.nombre_completo,
            'tutor_nombre': paciente.nombre_tutor,
            'tutor_telefono': paciente.telefono_tutor,
            'tutor_email': paciente.email_tutor or '',
            'saldo_pendiente': str(deuda),
        })

    return Response({'total_pacientes_con_deuda': len(data), 'deudas': data})