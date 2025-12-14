from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Q, Count, Sum
from datetime import datetime, timedelta, date
from decimal import Decimal
from .models import Sesion
from pacientes.models import Paciente, PacienteServicio
from servicios.models import TipoServicio, Sucursal
from profesionales.models import Profesional
import json


@login_required
def calendario(request):
    """Calendario principal con filtros avanzados"""
    
    # Obtener parámetros de filtro
    vista = request.GET.get('vista', 'semanal')  # 'diaria', 'semanal', 'mensual', 'lista'
    fecha_str = request.GET.get('fecha', '')
    estado_filtro = request.GET.get('estado', '')
    paciente_id = request.GET.get('paciente', '')
    profesional_id = request.GET.get('profesional', '')
    servicio_id = request.GET.get('servicio', '')
    
    # Fecha base (hoy si no se especifica)
    if fecha_str:
        try:
            fecha_base = datetime.strptime(fecha_str, '%Y-%m-%d').date()
        except:
            fecha_base = date.today()
    else:
        fecha_base = date.today()
    
    # Calcular rango según la vista
    if vista == 'diaria':
        fecha_inicio = fecha_base
        fecha_fin = fecha_base
    elif vista == 'mensual':
        primer_dia = fecha_base.replace(day=1)
        if fecha_base.month == 12:
            ultimo_dia = fecha_base.replace(day=31)
        else:
            ultimo_dia = (fecha_base.replace(day=1, month=fecha_base.month + 1) - timedelta(days=1))
        fecha_inicio = primer_dia
        fecha_fin = ultimo_dia
    elif vista == 'lista':
        # Para lista, permitir filtro de fechas personalizado
        fecha_desde_str = request.GET.get('fecha_desde', '')
        fecha_hasta_str = request.GET.get('fecha_hasta', '')
        
        if fecha_desde_str and fecha_hasta_str:
            try:
                fecha_inicio = datetime.strptime(fecha_desde_str, '%Y-%m-%d').date()
                fecha_fin = datetime.strptime(fecha_hasta_str, '%Y-%m-%d').date()
            except:
                # Si hay error, usar el mes actual
                primer_dia = fecha_base.replace(day=1)
                if fecha_base.month == 12:
                    ultimo_dia = fecha_base.replace(day=31)
                else:
                    ultimo_dia = (fecha_base.replace(day=1, month=fecha_base.month + 1) - timedelta(days=1))
                fecha_inicio = primer_dia
                fecha_fin = ultimo_dia
        else:
            # Por defecto, mostrar todo el mes actual
            primer_dia = fecha_base.replace(day=1)
            if fecha_base.month == 12:
                ultimo_dia = fecha_base.replace(day=31)
            else:
                ultimo_dia = (fecha_base.replace(day=1, month=fecha_base.month + 1) - timedelta(days=1))
            fecha_inicio = primer_dia
            fecha_fin = ultimo_dia
    else:  # semanal
        dias_desde_lunes = fecha_base.weekday()
        fecha_inicio = fecha_base - timedelta(days=dias_desde_lunes)
        fecha_fin = fecha_inicio + timedelta(days=6)
    
    # Query base optimizado con select_related
    sesiones = Sesion.objects.select_related(
        'paciente', 'profesional', 'servicio', 'sucursal'
    ).filter(
        fecha__gte=fecha_inicio,
        fecha__lte=fecha_fin
    )
    
    # Aplicar filtros
    if estado_filtro:
        sesiones = sesiones.filter(estado=estado_filtro)
    if paciente_id:
        sesiones = sesiones.filter(paciente_id=paciente_id)
    if profesional_id:
        sesiones = sesiones.filter(profesional_id=profesional_id)
    if servicio_id:
        sesiones = sesiones.filter(servicio_id=servicio_id)
    
    # Ordenar
    sesiones = sesiones.order_by('fecha', 'hora_inicio')
    
    # Datos para filtros
    pacientes = Paciente.objects.filter(estado='activo').order_by('nombre', 'apellido')
    profesionales = Profesional.objects.filter(activo=True).order_by('nombre', 'apellido')
    servicios = TipoServicio.objects.filter(activo=True).order_by('nombre')
    
    # Generar estructura del calendario
    if vista == 'diaria':
        calendario_data = _generar_calendario_diario(fecha_base, sesiones)
    elif vista == 'mensual':
        calendario_data = _generar_calendario_mensual(fecha_base, sesiones)
    elif vista == 'lista':
        calendario_data = None
    else:
        calendario_data = _generar_calendario_semanal(fecha_inicio, sesiones)
    
    # Navegación de fechas
    if vista == 'diaria':
        fecha_anterior = fecha_base - timedelta(days=1)
        fecha_siguiente = fecha_base + timedelta(days=1)
    elif vista == 'mensual':
        fecha_anterior = (fecha_base.replace(day=1) - timedelta(days=1))
        if fecha_base.month == 12:
            fecha_siguiente = fecha_base.replace(year=fecha_base.year + 1, month=1)
        else:
            fecha_siguiente = fecha_base.replace(month=fecha_base.month + 1)
    else:  # semanal o lista
        fecha_anterior = fecha_inicio - timedelta(days=7)
        fecha_siguiente = fecha_inicio + timedelta(days=7)
    
    context = {
        'vista': vista,
        'fecha_base': fecha_base,
        'fecha_inicio': fecha_inicio,
        'fecha_fin': fecha_fin,
        'calendario_data': calendario_data,
        'sesiones': sesiones,
        'pacientes': pacientes,
        'profesionales': profesionales,
        'servicios': servicios,
        'estados': Sesion.ESTADO_CHOICES,
        'fecha_anterior': fecha_anterior,
        'fecha_siguiente': fecha_siguiente,
        # Filtros actuales
        'estado_filtro': estado_filtro,
        'paciente_id': paciente_id,
        'profesional_id': profesional_id,
        'servicio_id': servicio_id,
    }
    
    return render(request, 'agenda/calendario.html', context)


def _generar_calendario_diario(fecha, sesiones):
    """Generar estructura para vista diaria"""
    sesiones_dia = [s for s in sesiones if s.fecha == fecha]
    return {
        'fecha': fecha,
        'es_hoy': fecha == date.today(),
        'sesiones': sesiones_dia,
        'dia_nombre': fecha.strftime('%A'),
        'tipo': 'diaria'
    }


def _generar_calendario_semanal(fecha_inicio, sesiones):
    """Generar estructura para vista semanal"""
    dias = []
    for i in range(7):
        dia = fecha_inicio + timedelta(days=i)
        sesiones_dia = [s for s in sesiones if s.fecha == dia]
        dias.append({
            'fecha': dia,
            'es_hoy': dia == date.today(),
            'sesiones': sesiones_dia,
            'dia_nombre': dia.strftime('%A'),
            'dia_numero': dia.day,
        })
    return {'dias': dias, 'tipo': 'semanal'}


def _generar_calendario_mensual(fecha_base, sesiones):
    """Generar estructura para vista mensual tipo cuadrícula"""
    primer_dia = fecha_base.replace(day=1)
    
    if fecha_base.month == 12:
        ultimo_dia = fecha_base.replace(day=31)
    else:
        ultimo_dia = (fecha_base.replace(month=fecha_base.month + 1) - timedelta(days=1))
    
    primer_dia_semana = primer_dia.weekday()
    dias_mes_anterior = []
    if primer_dia_semana > 0:
        for i in range(primer_dia_semana):
            dia = primer_dia - timedelta(days=primer_dia_semana - i)
            dias_mes_anterior.append({
                'fecha': dia,
                'es_otro_mes': True,
                'sesiones': [],
            })
    
    dias_mes_actual = []
    for dia_num in range(1, ultimo_dia.day + 1):
        dia = fecha_base.replace(day=dia_num)
        sesiones_dia = [s for s in sesiones if s.fecha == dia]
        dias_mes_actual.append({
            'fecha': dia,
            'es_hoy': dia == date.today(),
            'es_otro_mes': False,
            'sesiones': sesiones_dia,
            'dia_numero': dia_num,
        })
    
    todos_dias = dias_mes_anterior + dias_mes_actual
    semanas = []
    semana_actual = []
    
    for dia in todos_dias:
        semana_actual.append(dia)
        if len(semana_actual) == 7:
            semanas.append(semana_actual)
            semana_actual = []
    
    if semana_actual:
        while len(semana_actual) < 7:
            semana_actual.append({
                'fecha': None,
                'es_otro_mes': True,
                'sesiones': [],
            })
        semanas.append(semana_actual)
    
    return {
        'semanas': semanas,
        'tipo': 'mensual',
        'mes_nombre': fecha_base.strftime('%B %Y'),
    }


@login_required
def agendar_recurrente(request):
    """Vista para agendar sesiones recurrentes"""
    if request.method == 'POST':
        try:
            paciente_id = request.POST.get('paciente')
            servicio_id = request.POST.get('servicio')
            profesional_id = request.POST.get('profesional')
            sucursal_id = request.POST.get('sucursal')
            
            fecha_inicio = datetime.strptime(request.POST.get('fecha_inicio'), '%Y-%m-%d').date()
            fecha_fin = datetime.strptime(request.POST.get('fecha_fin'), '%Y-%m-%d').date()
            hora = datetime.strptime(request.POST.get('hora'), '%H:%M').time()
            
            dias_semana = request.POST.getlist('dias_semana')
            dias_semana = [int(d) for d in dias_semana]
            
            paciente = Paciente.objects.get(id=paciente_id)
            servicio = TipoServicio.objects.get(id=servicio_id)
            profesional = Profesional.objects.get(id=profesional_id)
            sucursal = Sucursal.objects.get(id=sucursal_id)
            
            paciente_servicio = PacienteServicio.objects.get(
                paciente=paciente,
                servicio=servicio
            )
            monto = paciente_servicio.costo_sesion
            
            inicio_dt = datetime.combine(fecha_inicio, hora)
            fin_dt = inicio_dt + timedelta(minutes=servicio.duracion_minutos)
            hora_fin = fin_dt.time()
            
            sesiones_creadas = 0
            sesiones_error = []
            fecha_actual = fecha_inicio
            
            while fecha_actual <= fecha_fin:
                if fecha_actual.weekday() in dias_semana:
                    try:
                        disponible, mensaje = Sesion.validar_disponibilidad(
                            paciente, profesional, fecha_actual, hora, hora_fin
                        )
                        
                        if disponible:
                            Sesion.objects.create(
                                paciente=paciente,
                                servicio=servicio,
                                profesional=profesional,
                                sucursal=sucursal,
                                fecha=fecha_actual,
                                hora_inicio=hora,
                                hora_fin=hora_fin,
                                duracion_minutos=servicio.duracion_minutos,
                                monto_cobrado=monto,
                                creada_por=request.user
                            )
                            sesiones_creadas += 1
                        else:
                            sesiones_error.append({
                                'fecha': fecha_actual,
                                'error': mensaje
                            })
                    except Exception as e:
                        sesiones_error.append({
                            'fecha': fecha_actual,
                            'error': str(e)
                        })
                
                fecha_actual += timedelta(days=1)
            
            if sesiones_creadas > 0:
                messages.success(request, f'✅ Se crearon {sesiones_creadas} sesiones correctamente.')
            
            if sesiones_error:
                error_msg = f'⚠️ {len(sesiones_error)} sesiones no se pudieron crear por conflictos de horario.'
                messages.warning(request, error_msg)
            
            return redirect('agenda:calendario')
            
        except Exception as e:
            messages.error(request, f'Error al crear sesiones: {str(e)}')
            return redirect('agenda:agendar_recurrente')
    
    pacientes = Paciente.objects.filter(estado='activo').order_by('nombre', 'apellido')
    profesionales = Profesional.objects.filter(activo=True).order_by('nombre', 'apellido')
    sucursales = Sucursal.objects.filter(activa=True)
    
    context = {
        'pacientes': pacientes,
        'profesionales': profesionales,
        'sucursales': sucursales,
    }
    
    return render(request, 'agenda/agendar_recurrente.html', context)


# ============= APIs HTMX =============

@login_required
def cargar_servicios_paciente(request):
    """Cargar servicios contratados por un paciente (HTMX)"""
    paciente_id = request.GET.get('paciente')
    
    if not paciente_id:
        return render(request, 'agenda/partials/servicios_select.html', {'servicios': []})
    
    try:
        servicios = PacienteServicio.objects.filter(
            paciente_id=paciente_id,
            activo=True
        ).select_related('servicio')
        
        return render(request, 'agenda/partials/servicios_select.html', {
            'servicios': servicios
        })
    except Exception as e:
        print(f"Error cargando servicios: {e}")
        return render(request, 'agenda/partials/servicios_select.html', {
            'servicios': [],
            'error': str(e)
        })


@login_required
def vista_previa_recurrente(request):
    """Vista previa de sesiones recurrentes (HTMX)"""
    try:
        fecha_inicio = datetime.strptime(request.GET.get('fecha_inicio'), '%Y-%m-%d').date()
        fecha_fin = datetime.strptime(request.GET.get('fecha_fin'), '%Y-%m-%d').date()
        hora = request.GET.get('hora')
        dias_semana = request.GET.getlist('dias_semana')
        dias_semana = [int(d) for d in dias_semana if d]
        
        if not dias_semana:
            return render(request, 'agenda/partials/vista_previa.html', {
                'sesiones': [],
                'total': 0
            })
        
        fechas = []
        fecha_actual = fecha_inicio
        while fecha_actual <= fecha_fin:
            if fecha_actual.weekday() in dias_semana:
                fechas.append(fecha_actual)
            fecha_actual += timedelta(days=1)
        
        context = {
            'fechas': fechas,
            'total': len(fechas),
            'hora': hora
        }
        
        return render(request, 'agenda/partials/vista_previa.html', context)
        
    except Exception as e:
        return render(request, 'agenda/partials/vista_previa.html', {
            'sesiones': [],
            'total': 0,
            'error': str(e)
        })


@login_required
def editar_sesion(request, sesion_id):
    """Editar sesión (HTMX modal)"""
    sesion = get_object_or_404(Sesion, id=sesion_id)
    
    if request.method == 'POST':
        try:
            # Actualizar estado
            estado_nuevo = request.POST.get('estado')
            sesion.estado = estado_nuevo
            
            # Aplicar políticas de cobro según estado
            if estado_nuevo == 'permiso':
                # PERMISO: No se cobra
                sesion.monto_cobrado = Decimal('0.00')
                sesion.pagado = False
            elif estado_nuevo == 'reprogramada':
                # REPROGRAMADA: Siempre gratis
                sesion.monto_cobrado = Decimal('0.00')
                sesion.pagado = False
            elif estado_nuevo == 'cancelada':
                # CANCELADA: Por defecto 0, pero se puede modificar
                monto_input = request.POST.get('monto_cobrado', '0')
                sesion.monto_cobrado = Decimal(monto_input) if monto_input else Decimal('0.00')
            else:
                # OTROS ESTADOS: Se puede modificar el monto
                monto_input = request.POST.get('monto_cobrado')
                if monto_input:
                    sesion.monto_cobrado = Decimal(monto_input)
            
            # Observaciones y notas
            sesion.observaciones = request.POST.get('observaciones', '')
            sesion.notas_sesion = request.POST.get('notas_sesion', '')
            
            # Campos específicos según estado
            if estado_nuevo == 'realizada_retraso':
                hora_real = request.POST.get('hora_real_inicio')
                if hora_real:
                    sesion.hora_real_inicio = datetime.strptime(hora_real, '%H:%M').time()
                    inicio = datetime.combine(sesion.fecha, sesion.hora_inicio)
                    real = datetime.combine(sesion.fecha, sesion.hora_real_inicio)
                    sesion.minutos_retraso = int((real - inicio).total_seconds() / 60)
            
            if estado_nuevo == 'reprogramada':
                fecha_nueva = request.POST.get('fecha_reprogramada')
                hora_nueva = request.POST.get('hora_reprogramada')
                if fecha_nueva:
                    sesion.fecha_reprogramada = datetime.strptime(fecha_nueva, '%Y-%m-%d').date()
                if hora_nueva:
                    sesion.hora_reprogramada = datetime.strptime(hora_nueva, '%H:%M').time()
                sesion.motivo_reprogramacion = request.POST.get('motivo_reprogramacion', '')
                # Checkbox de reprogramación realizada
                sesion.reprogramacion_realizada = request.POST.get('reprogramacion_realizada') == 'on'
            
            # Pago
            if estado_nuevo not in ['permiso', 'reprogramada']:
                if request.POST.get('pagado') == 'on':
                    sesion.pagado = True
                    fecha_pago_input = request.POST.get('fecha_pago')
                    if fecha_pago_input:
                        sesion.fecha_pago = datetime.strptime(fecha_pago_input, '%Y-%m-%d').date()
                    elif not sesion.fecha_pago:
                        sesion.fecha_pago = date.today()
                else:
                    sesion.pagado = False
                    sesion.fecha_pago = None
            
            sesion.modificada_por = request.user
            sesion.save()
            
            messages.success(request, '✅ Sesión actualizada correctamente')
            
            # Retornar respuesta exitosa para AJAX
            from django.http import JsonResponse
            return JsonResponse({'success': True})
            
        except Exception as e:
            messages.error(request, f'Error: {str(e)}')
            # Calcular estadísticas
            estadisticas = _calcular_estadisticas_mes(sesion)
            return render(request, 'agenda/partials/editar_form.html', {
                'sesion': sesion,
                'error': str(e),
                'estadisticas': json.dumps(estadisticas),
            })
    
    # GET - Mostrar formulario
    # Calcular estadísticas del mes
    estadisticas = _calcular_estadisticas_mes(sesion)
    
    return render(request, 'agenda/partials/editar_form.html', {
        'sesion': sesion,
        'estadisticas': json.dumps(estadisticas),
    })


def _calcular_estadisticas_mes(sesion):
    """Calcular estadísticas del mes para el paciente"""
    primer_dia = sesion.fecha.replace(day=1)
    if sesion.fecha.month == 12:
        ultimo_dia = sesion.fecha.replace(day=31)
    else:
        ultimo_dia = (sesion.fecha.replace(month=sesion.fecha.month + 1) - timedelta(days=1))
    
    sesiones_mes = Sesion.objects.filter(
        paciente=sesion.paciente,
        fecha__gte=primer_dia,
        fecha__lte=ultimo_dia
    )
    
    return {
        'asistencias': sesiones_mes.filter(estado='realizada').count(),
        'retrasos': sesiones_mes.filter(estado='realizada_retraso').count(),
        'faltas': sesiones_mes.filter(estado='falta').count(),
        'permisos': sesiones_mes.filter(estado='permiso').count(),
        'cancelaciones': sesiones_mes.filter(estado='cancelada').count(),
        'reprogramaciones': sesiones_mes.filter(estado='reprogramada').count(),
    }


@login_required
def validar_horario(request):
    """Validar disponibilidad de horario (AJAX)"""
    try:
        paciente_id = request.GET.get('paciente_id')
        profesional_id = request.GET.get('profesional_id')
        fecha_str = request.GET.get('fecha')
        hora_inicio_str = request.GET.get('hora_inicio')
        duracion = int(request.GET.get('duracion', 60))
        sesion_id = request.GET.get('sesion_id')
        
        fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
        hora_inicio = datetime.strptime(hora_inicio_str, '%H:%M').time()
        
        inicio_dt = datetime.combine(fecha, hora_inicio)
        fin_dt = inicio_dt + timedelta(minutes=duracion)
        hora_fin = fin_dt.time()
        
        paciente = Paciente.objects.get(id=paciente_id)
        profesional = Profesional.objects.get(id=profesional_id)
        
        sesion_actual = None
        if sesion_id:
            sesion_actual = Sesion.objects.get(id=sesion_id)
        
        disponible, mensaje = Sesion.validar_disponibilidad(
            paciente, profesional, fecha, hora_inicio, hora_fin, sesion_actual
        )
        
        return JsonResponse({
            'disponible': disponible,
            'mensaje': mensaje
        })
        
    except Exception as e:
        return JsonResponse({
            'disponible': False,
            'mensaje': f'Error: {str(e)}'
        }, status=400)