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
    Retorna tutores con saldo pendiente (saldo_actual < -1).
    Agrupa por teléfono del tutor — un mensaje por tutor aunque tenga varios hijos con deuda.
    Filtra por sucursal si se pasa ?sucursal=3 o ?sucursal=4.
    Construye el mensaje completo listo para enviar por WhatsApp.
    """
    sucursal_id = request.GET.get('sucursal')

    cuentas = CuentaCorriente.objects.filter(
        paciente__estado='activo',
        saldo_actual__lt=-1,  # deuda real de al menos Bs. 1
    ).select_related('paciente').prefetch_related('paciente__sucursales').order_by('saldo_actual')

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

        deuda = abs(cuenta.saldo_actual)

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
        })

    return Response({'total': len(data), 'deudas': data})