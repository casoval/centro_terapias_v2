from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.db.models import Q, Count, Sum
from datetime import datetime, timedelta, date
from decimal import Decimal
from .models import Sesion
from pacientes.models import Paciente, PacienteServicio
from servicios.models import TipoServicio, Sucursal
from profesionales.models import Profesional
from core.utils import (
    get_sucursales_usuario, 
    get_profesional_usuario, 
    filtrar_por_sucursales,
    solo_sus_sucursales
)
import json


@login_required
@solo_sus_sucursales
def calendario(request):
    """Calendario principal con filtros avanzados y permisos por sucursal"""
    
    # Obtener parámetros de filtro
    vista = request.GET.get('vista', 'semanal')
    fecha_str = request.GET.get('fecha', '')
    estado_filtro = request.GET.get('estado', '')
    paciente_id = request.GET.get('paciente', '')
    profesional_id = request.GET.get('profesional', '')
    servicio_id = request.GET.get('servicio', '')
    sucursal_id = request.GET.get('sucursal', '')
    
    # Fecha base
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
        fecha_desde_str = request.GET.get('fecha_desde', '')
        fecha_hasta_str = request.GET.get('fecha_hasta', '')
        
        if fecha_desde_str and fecha_hasta_str:
            try:
                fecha_inicio = datetime.strptime(fecha_desde_str, '%Y-%m-%d').date()
                fecha_fin = datetime.strptime(fecha_hasta_str, '%Y-%m-%d').date()
            except:
                primer_dia = fecha_base.replace(day=1)
                if fecha_base.month == 12:
                    ultimo_dia = fecha_base.replace(day=31)
                else:
                    ultimo_dia = (fecha_base.replace(day=1, month=fecha_base.month + 1) - timedelta(days=1))
                fecha_inicio = primer_dia
                fecha_fin = ultimo_dia
        else:
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
    
    # Query base
    sesiones = Sesion.objects.select_related(
        'paciente', 'profesional', 'servicio', 'sucursal'
    ).filter(
        fecha__gte=fecha_inicio,
        fecha__lte=fecha_fin
    )
    
    # ✅ FILTRAR POR SUCURSALES DEL USUARIO
    sucursales_usuario = request.sucursales_usuario
    
    if sucursales_usuario is not None:
        # Usuario tiene sucursales asignadas
        if sucursales_usuario.exists():
            sesiones = sesiones.filter(sucursal__in=sucursales_usuario)
        else:
            sesiones = sesiones.none()
    
    # Filtro adicional por sucursal específica
    if sucursal_id:
        sesiones = sesiones.filter(sucursal_id=sucursal_id)
    
    # Aplicar otros filtros
    if estado_filtro:
        sesiones = sesiones.filter(estado=estado_filtro)
    if paciente_id:
        sesiones = sesiones.filter(paciente_id=paciente_id)
    if profesional_id:
        sesiones = sesiones.filter(profesional_id=profesional_id)
    if servicio_id:
        sesiones = sesiones.filter(servicio_id=servicio_id)
    
    sesiones = sesiones.order_by('fecha', 'hora_inicio')
    
    # ✅ Datos para filtros (FILTRADOS POR SUCURSALES)
    if sucursales_usuario is not None and sucursales_usuario.exists():
        pacientes = Paciente.objects.filter(
            estado='activo',
            sucursales__in=sucursales_usuario
        ).distinct().order_by('nombre', 'apellido')
        
        profesionales = Profesional.objects.filter(
            activo=True,
            sucursales__in=sucursales_usuario
        ).distinct().order_by('nombre', 'apellido')
        
        sucursales = sucursales_usuario
    else:
        # Superuser: todas las sucursales
        if sucursal_id:
            pacientes = Paciente.objects.filter(
                estado='activo',
                sucursales__id=sucursal_id
            ).distinct().order_by('nombre', 'apellido')
            profesionales = Profesional.objects.filter(
                activo=True,
                sucursales__id=sucursal_id
            ).distinct().order_by('nombre', 'apellido')
        else:
            pacientes = Paciente.objects.filter(estado='activo').order_by('nombre', 'apellido')
            profesionales = Profesional.objects.filter(activo=True).order_by('nombre', 'apellido')
        
        sucursales = Sucursal.objects.filter(activa=True)
    
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
    else:
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
        'sucursales': sucursales,
        'estados': Sesion.ESTADO_CHOICES,
        'fecha_anterior': fecha_anterior,
        'fecha_siguiente': fecha_siguiente,
        'estado_filtro': estado_filtro,
        'paciente_id': paciente_id,
        'profesional_id': profesional_id,
        'servicio_id': servicio_id,
        'sucursal_id': sucursal_id,
        'sucursales_usuario': sucursales_usuario,
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
@solo_sus_sucursales
def agendar_recurrente(request):
    """Vista para agendar sesiones recurrentes CON FILTRO DE SUCURSAL Y DURACIÓN PERSONALIZABLE"""
    
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
            
            # ✅ NUEVO: Obtener sesiones seleccionadas por el usuario
            sesiones_seleccionadas = request.POST.getlist('sesiones_seleccionadas')
            
            if not sesiones_seleccionadas:
                messages.error(request, '⚠️ Debes seleccionar al menos una sesión para agendar.')
                return redirect('agenda:agendar_recurrente')
            
            # Convertir a conjunto de fechas para búsqueda rápida
            fechas_seleccionadas = set([
                datetime.strptime(f, '%Y-%m-%d').date() for f in sesiones_seleccionadas
            ])
            
            # Obtener duración personalizada
            duracion_personalizada = request.POST.get('duracion_personalizada')
            
            paciente = Paciente.objects.get(id=paciente_id)
            servicio = TipoServicio.objects.get(id=servicio_id)
            profesional = Profesional.objects.get(id=profesional_id)
            sucursal = Sucursal.objects.get(id=sucursal_id)
            
            # ✅ VALIDACIÓN: Verificar permisos de sucursal
            sucursales_usuario = request.sucursales_usuario
            if sucursales_usuario is not None:
                if not sucursales_usuario.filter(id=sucursal.id).exists():
                    messages.error(request, '❌ No tienes permiso para agendar en esta sucursal.')
                    return redirect('agenda:agendar_recurrente')
            
            # ✅ VALIDACIÓN: Paciente debe tener la sucursal
            if not paciente.tiene_sucursal(sucursal):
                messages.error(request, f'❌ El paciente no está asignado a la sucursal {sucursal}.')
                return redirect('agenda:agendar_recurrente')
            
            # ✅ VALIDACIÓN: Profesional debe tener sucursal + servicio
            if not profesional.puede_atender_en(sucursal, servicio):
                messages.error(request, f'❌ El profesional no puede atender este servicio en esta sucursal.')
                return redirect('agenda:agendar_recurrente')
            
            paciente_servicio = PacienteServicio.objects.get(
                paciente=paciente,
                servicio=servicio
            )
            monto = paciente_servicio.costo_sesion
            
            # ✅ DETERMINAR DURACIÓN: Personalizada o estándar
            if duracion_personalizada:
                duracion_minutos = int(duracion_personalizada)
            else:
                duracion_minutos = servicio.duracion_minutos
            
            inicio_dt = datetime.combine(fecha_inicio, hora)
            fin_dt = inicio_dt + timedelta(minutes=duracion_minutos)
            hora_fin = fin_dt.time()
            
            sesiones_creadas = 0
            sesiones_error = []
            fecha_actual = fecha_inicio
            
            while fecha_actual <= fecha_fin:
                # ✅ VALIDAR: Solo crear si está en días seleccionados Y en fechas seleccionadas
                if fecha_actual.weekday() in dias_semana and fecha_actual in fechas_seleccionadas:
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
                                duracion_minutos=duracion_minutos,
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
                duracion_msg = f" de {duracion_minutos} minutos" if duracion_personalizada else ""
                messages.success(request, f'✅ Se crearon {sesiones_creadas} sesiones{duracion_msg} correctamente.')
            else:
                messages.warning(request, '⚠️ No se pudo crear ninguna sesión. Verifica los conflictos de horario.')
            
            if sesiones_error:
                error_msg = f'⚠️ {len(sesiones_error)} sesiones no se pudieron crear por conflictos de horario.'
                messages.warning(request, error_msg)
            
            return redirect('agenda:calendario')
            
        except Exception as e:
            messages.error(request, f'Error al crear sesiones: {str(e)}')
            return redirect('agenda:agendar_recurrente')
    
    # ✅ GET - Mostrar formulario
    sucursales_usuario = request.sucursales_usuario
    
    if sucursales_usuario is not None and sucursales_usuario.exists():
        sucursales = sucursales_usuario
        pacientes = Paciente.objects.filter(
            estado='activo',
            sucursales__in=sucursales_usuario
        ).distinct().order_by('nombre', 'apellido')
        profesionales = Profesional.objects.filter(
            activo=True,
            sucursales__in=sucursales_usuario
        ).distinct().order_by('nombre', 'apellido')
    else:
        # Superuser
        pacientes = Paciente.objects.filter(estado='activo').order_by('nombre', 'apellido')
        profesionales = Profesional.objects.filter(activo=True).order_by('nombre', 'apellido')
        sucursales = Sucursal.objects.filter(activa=True)
    
    context = {
        'pacientes': pacientes,
        'profesionales': profesionales,
        'sucursales': sucursales,
        'sucursales_usuario': sucursales_usuario,
    }
    
    return render(request, 'agenda/agendar_recurrente.html', context)

# ============= APIs HTMX =============

@login_required
def cargar_pacientes_sucursal(request):
    """✅ API: Cargar pacientes de una sucursal específica (HTMX)"""
    sucursal_id = request.GET.get('sucursal')
    
    if not sucursal_id:
        return render(request, 'agenda/partials/pacientes_select.html', {'pacientes': []})
    
    try:
        pacientes = Paciente.objects.filter(
            sucursales__id=sucursal_id,
            estado='activo'
        ).distinct().order_by('nombre', 'apellido')
        
        return render(request, 'agenda/partials/pacientes_select.html', {
            'pacientes': pacientes
        })
    except Exception as e:
        return render(request, 'agenda/partials/pacientes_select.html', {
            'pacientes': [],
            'error': str(e)
        })


@login_required
def cargar_servicios_paciente(request):
    """API: Cargar servicios contratados por un paciente (HTMX)"""
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
        return render(request, 'agenda/partials/servicios_select.html', {
            'servicios': [],
            'error': str(e)
        })


@login_required
def cargar_profesionales_por_servicio(request):
    """✅ API: Cargar profesionales que ofrecen un servicio en una sucursal (HTMX)"""
    servicio_id = request.GET.get('servicio')
    sucursal_id = request.GET.get('sucursal')
    
    if not servicio_id or not sucursal_id:
        return render(request, 'agenda/partials/profesionales_select.html', {'profesionales': []})
    
    try:
        # Profesionales que:
        # 1. Están activos
        # 2. Tienen la sucursal asignada
        # 3. Ofrecen el servicio seleccionado
        profesionales = Profesional.objects.filter(
            activo=True,
            sucursales__id=sucursal_id,
            servicios__id=servicio_id
        ).distinct().order_by('nombre', 'apellido')
        
        return render(request, 'agenda/partials/profesionales_select.html', {
            'profesionales': profesionales
        })
    except Exception as e:
        return render(request, 'agenda/partials/profesionales_select.html', {
            'profesionales': [],
            'error': str(e)
        })

@login_required
def vista_previa_recurrente(request):
    """Vista previa de sesiones recurrentes con validación detallada de disponibilidad"""
    
    # Obtener parámetros
    fecha_inicio_str = request.GET.get('fecha_inicio')
    fecha_fin_str = request.GET.get('fecha_fin')
    hora_str = request.GET.get('hora')
    dias_semana = request.GET.getlist('dias_semana')
    paciente_id = request.GET.get('paciente')
    profesional_id = request.GET.get('profesional')
    servicio_id = request.GET.get('servicio')
    duracion_str = request.GET.get('duracion', '60')
    
    # Validar parámetros básicos
    if not all([fecha_inicio_str, fecha_fin_str, hora_str, dias_semana]):
        return HttpResponse('''
            <div class="bg-gray-50 border border-gray-200 rounded-lg p-6 text-center">
                <div class="text-4xl mb-3">📅</div>
                <p class="text-gray-600">Selecciona las fechas, hora y días para ver la vista previa</p>
            </div>
        ''')
    
    try:
        # Convertir strings a objetos
        fecha_inicio = datetime.strptime(fecha_inicio_str, '%Y-%m-%d').date()
        fecha_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d').date()
        hora = datetime.strptime(hora_str, '%H:%M').time()
        dias_semana = [int(d) for d in dias_semana if d]
        duracion_minutos = int(duracion_str)
        
        # Validaciones básicas
        if not dias_semana:
            return HttpResponse('''
                <div class="bg-yellow-50 border border-yellow-200 rounded-lg p-6 text-center">
                    <div class="text-4xl mb-3">⚠️</div>
                    <p class="text-yellow-700 font-medium">No has seleccionado ningún día de la semana</p>
                </div>
            ''')
        
        if fecha_inicio > fecha_fin:
            return HttpResponse('''
                <div class="bg-red-50 border border-red-200 rounded-lg p-6 text-center">
                    <div class="text-4xl mb-3">❌</div>
                    <p class="text-red-700 font-medium">La fecha de inicio debe ser anterior a la fecha de fin</p>
                </div>
            ''')
        
        # Obtener objetos necesarios para validación
        paciente = None
        profesional = None
        servicio = None
        
        if paciente_id:
            try:
                paciente = Paciente.objects.get(id=paciente_id)
            except:
                pass
        
        if profesional_id:
            try:
                profesional = Profesional.objects.get(id=profesional_id)
            except:
                pass
        
        if servicio_id:
            try:
                servicio = TipoServicio.objects.get(id=servicio_id)
            except:
                pass
        
        # Calcular hora_fin usando duración personalizada
        inicio_dt = datetime.combine(fecha_inicio, hora)
        fin_dt = inicio_dt + timedelta(minutes=duracion_minutos)
        hora_fin = fin_dt.time()
        
        # Generar lista de fechas con validación DETALLADA
        sesiones_data = []
        fecha_actual = fecha_inicio
        
        while fecha_actual <= fecha_fin:
            if fecha_actual.weekday() in dias_semana:
                sesion_info = _validar_disponibilidad_detallada(
                    paciente, profesional, fecha_actual, hora, hora_fin
                )
                
                sesiones_data.append({
                    'fecha': fecha_actual,
                    'disponible': sesion_info['disponible'],
                    'conflictos_paciente': sesion_info['conflictos_paciente'],
                    'conflictos_profesional': sesion_info['conflictos_profesional'],
                })
            
            fecha_actual += timedelta(days=1)
        
        if not sesiones_data:
            return HttpResponse('''
                <div class="bg-yellow-50 border border-yellow-200 rounded-lg p-6 text-center">
                    <div class="text-4xl mb-3">⚠️</div>
                    <p class="text-yellow-700 font-medium">No se generarán sesiones con esta configuración</p>
                </div>
            ''')
        
        # Calcular estadísticas
        total = len(sesiones_data)
        disponibles = sum(1 for s in sesiones_data if s['disponible'])
        conflictos = total - disponibles
        
        # Nombres de días
        dias_nombres = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']
        
        # Generar HTML
        hora_formato = hora.strftime('%H:%M')
        hora_fin_formato = hora_fin.strftime('%H:%M')
        servicio_nombre = servicio.nombre if servicio else "Servicio"
        
        # Color del header
        if disponibles == total:
            header_bg = "bg-green-50 border-green-200"
            header_text = "text-green-900"
            header_icon = "✅"
        elif disponibles > 0:
            header_bg = "bg-yellow-50 border-yellow-200"
            header_text = "text-yellow-900"
            header_icon = "⚠️"
        else:
            header_bg = "bg-red-50 border-red-200"
            header_text = "text-red-900"
            header_icon = "❌"
        
        html = f'''
            <div class="{header_bg} border rounded-lg p-4">
                <!-- Header compacto -->
                <div class="flex items-center justify-between mb-3">
                    <div>
                        <h3 class="text-base font-bold {header_text} flex items-center gap-2">
                            {header_icon} Vista Previa
                        </h3>
                        <p class="text-xs {header_text} mt-0.5">
                            {servicio_nombre} · {hora_formato}-{hora_fin_formato} ({duracion_minutos}min)
                        </p>
                    </div>
                    <div class="flex gap-1.5 text-xs">
                        <span class="bg-gray-700 text-white px-2 py-1 rounded font-medium">{total}</span>
                        <span class="bg-green-600 text-white px-2 py-1 rounded font-medium">✓{disponibles}</span>
                        {f'<span class="bg-red-600 text-white px-2 py-1 rounded font-medium">✗{conflictos}</span>' if conflictos > 0 else ''}
                    </div>
                </div>
                
                <!-- Grid de sesiones -->
                <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2 max-h-96 overflow-y-auto pr-1">
        '''
        
        for i, sesion in enumerate(sesiones_data):
            fecha = sesion['fecha']
            fecha_formato = fecha.strftime('%d/%m')
            dia_nombre = dias_nombres[fecha.weekday()]
            disponible = sesion['disponible']
            conflictos_p = sesion['conflictos_paciente']
            conflictos_prof = sesion['conflictos_profesional']
            
            if disponible:
                card_bg = "bg-white border-green-400"
                icon = "✅"
                checked = "checked"
                disabled = ""
            else:
                card_bg = "bg-red-50 border-red-400"
                icon = "🚫"
                checked = ""
                disabled = "disabled"
            
            # ✅ Agregar checkbox para seleccionar sesión
            fecha_iso = fecha.strftime('%Y-%m-%d')
            
            html += f'''
                    <div class="{card_bg} border-2 rounded-lg p-2 relative">
                        <!-- ✅ Checkbox en la esquina superior derecha -->
                        <div class="absolute top-1 right-1">
                            <input type="checkbox" 
                                   name="sesiones_seleccionadas" 
                                   value="{fecha_iso}"
                                   class="sesion-checkbox w-5 h-5 text-blue-600 rounded focus:ring-2 focus:ring-blue-500 {'cursor-pointer' if disponible else 'cursor-not-allowed opacity-50'}"
                                   {checked}
                                   {disabled}
                                   onchange="actualizarContador()">
                        </div>
                        
                        <div class="text-center mt-4">
                            <div class="text-2xl mb-1">{icon}</div>
                            <p class="text-xs font-bold text-gray-900">{dia_nombre}</p>
                            <p class="text-xs font-semibold text-gray-700">{fecha_formato}</p>
            '''
            
            # Mostrar conflictos de forma desplegable
            if not disponible and (conflictos_p or conflictos_prof):
                html += f'''
                            <button type="button" 
                                    onclick="toggleConflicto('panel-{i}', this)"
                                    class="mt-2 w-full text-xs bg-red-500 hover:bg-red-600 text-white px-2 py-1 rounded transition">
                                ▼ Ver detalle
                            </button>
                        </div>
                        
                        <!-- Panel de conflictos desplegable -->
                        <div id="panel-{i}" style="display: none;" class="mt-2 pt-2 border-t border-red-300 text-left">
                '''
                
                if conflictos_p:
                    html += '<div class="mb-2"><p class="text-xs font-bold text-red-700 mb-1">👤 Paciente ocupado:</p>'
                    for c in conflictos_p:
                        html += f'''
                            <div class="text-xs bg-white rounded p-1.5 mb-1 border border-red-200">
                                <p class="font-semibold">{c["servicio"]}</p>
                                <p class="text-gray-600">{c["hora_inicio"]}-{c["hora_fin"]}</p>
                                <p class="text-gray-500 text-[10px]">Dr/a: {c["profesional"]}</p>
                                <p class="text-gray-500 text-[10px]">📍 {c.get("sucursal", "N/A")}</p>
                            </div>
                        '''
                    html += '</div>'
                
                if conflictos_prof:
                    html += '<div><p class="text-xs font-bold text-orange-700 mb-1">👨‍⚕️ Profesional ocupado:</p>'
                    for c in conflictos_prof:
                        html += f'''
                            <div class="text-xs bg-white rounded p-1.5 mb-1 border border-orange-200">
                                <p class="font-semibold">{c["paciente"]}</p>
                                <p class="text-gray-600 text-[10px]">{c["servicio"]}</p>
                                <p class="text-gray-600">{c["hora_inicio"]}-{c["hora_fin"]}</p>
                                <p class="text-gray-500 text-[10px]">📍 {c.get("sucursal", "N/A")}</p>
                            </div>
                        '''
                    html += '</div>'
                
                html += '</div>'
            else:
                html += '</div>'
            
            html += '</div>'
        
        html += f'''
                </div>
                
                <!-- Resumen final con contador de seleccionadas -->
                <div class="mt-3 pt-3 border-t border-gray-300">
                    <div class="grid grid-cols-3 gap-2 text-center text-sm">
                        <div class="bg-blue-100 rounded p-2">
                            <p class="font-bold text-blue-700" id="contador-seleccionadas">{disponibles}</p>
                            <p class="text-xs text-blue-600">Seleccionadas</p>
                        </div>
                        <div class="bg-green-100 rounded p-2">
                            <p class="font-bold text-green-700">{disponibles}</p>
                            <p class="text-xs text-green-600">Disponibles</p>
                        </div>
                        <div class="bg-red-100 rounded p-2">
                            <p class="font-bold text-red-700">{conflictos}</p>
                            <p class="text-xs text-red-600">Con conflictos</p>
                        </div>
                    </div>
                    <p class="text-xs text-gray-500 text-center mt-2">
                        ℹ️ Solo se crearán las sesiones que selecciones
                    </p>
                </div>
            </div>
        '''
        
        return HttpResponse(html)
        
    except ValueError as e:
        return HttpResponse(f'''
            <div class="bg-red-50 border border-red-200 rounded-lg p-6 text-center">
                <div class="text-4xl mb-3">❌</div>
                <p class="text-red-700 font-medium">Error en el formato de fecha u hora</p>
                <p class="text-sm text-red-600 mt-2">{str(e)}</p>
            </div>
        ''')
    except Exception as e:
        return HttpResponse(f'''
            <div class="bg-red-50 border border-red-200 rounded-lg p-6 text-center">
                <div class="text-4xl mb-3">❌</div>
                <p class="text-red-700 font-medium">Error al generar la vista previa</p>
                <p class="text-sm text-red-600 mt-2">{str(e)}</p>
            </div>
        ''')

def _validar_disponibilidad_detallada(paciente, profesional, fecha, hora_inicio, hora_fin):
    """
    Valida disponibilidad y retorna detalles COMPLETOS de los conflictos
    """
    resultado = {
        'disponible': True,
        'conflictos_paciente': [],
        'conflictos_profesional': []
    }
    
    if not paciente or not profesional:
        return resultado
    
    inicio = datetime.combine(fecha, hora_inicio)
    fin = datetime.combine(fecha, hora_fin)
    
    # Verificar conflictos del PACIENTE
    sesiones_paciente = Sesion.objects.filter(
        paciente=paciente,
        fecha=fecha,
        estado__in=['programada', 'realizada', 'realizada_retraso']
    ).select_related('servicio', 'profesional', 'sucursal')
    
    for sesion in sesiones_paciente:
        s_inicio = datetime.combine(fecha, sesion.hora_inicio)
        s_fin = datetime.combine(fecha, sesion.hora_fin)
        
        if (inicio < s_fin and fin > s_inicio):
            resultado['disponible'] = False
            resultado['conflictos_paciente'].append({
                'servicio': sesion.servicio.nombre,
                'hora_inicio': sesion.hora_inicio.strftime('%H:%M'),
                'hora_fin': sesion.hora_fin.strftime('%H:%M'),
                'profesional': f"{sesion.profesional.nombre} {sesion.profesional.apellido}",
                'sucursal': sesion.sucursal.nombre
            })
    
    # Verificar conflictos del PROFESIONAL
    sesiones_profesional = Sesion.objects.filter(
        profesional=profesional,
        fecha=fecha,
        estado__in=['programada', 'realizada', 'realizada_retraso']
    ).select_related('paciente', 'servicio', 'sucursal')
    
    for sesion in sesiones_profesional:
        s_inicio = datetime.combine(fecha, sesion.hora_inicio)
        s_fin = datetime.combine(fecha, sesion.hora_fin)
        
        if (inicio < s_fin and fin > s_inicio):
            resultado['disponible'] = False
            resultado['conflictos_profesional'].append({
                'paciente': f"{sesion.paciente.nombre} {sesion.paciente.apellido}",
                'servicio': sesion.servicio.nombre,
                'hora_inicio': sesion.hora_inicio.strftime('%H:%M'),
                'hora_fin': sesion.hora_fin.strftime('%H:%M'),
                'sucursal': sesion.sucursal.nombre
            })
    
    return resultado

@login_required
def editar_sesion(request, sesion_id):
    """Editar sesiÃ³n (HTMX modal)"""
    sesion = get_object_or_404(Sesion, id=sesion_id)
    
    if request.method == 'POST':
        try:
            # Actualizar estado
            estado_nuevo = request.POST.get('estado')
            sesion.estado = estado_nuevo
            
            # Aplicar polÃ­ticas de cobro segÃºn estado
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
            
            # Campos especÃ­ficos segÃºn estado
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
                # Checkbox de reprogramaciÃ³n realizada
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
            
            messages.success(request, 'âœ… SesiÃ³n actualizada correctamente')
            
            # Retornar respuesta exitosa para AJAX
            from django.http import JsonResponse
            return JsonResponse({'success': True})
            
        except Exception as e:
            messages.error(request, f'Error: {str(e)}')
            # Calcular estadÃ­sticas
            estadisticas = _calcular_estadisticas_mes(sesion)
            return render(request, 'agenda/partials/editar_form.html', {
                'sesion': sesion,
                'error': str(e),
                'estadisticas': json.dumps(estadisticas),
            })
    
    # GET - Mostrar formulario
    # Calcular estadÃ­sticas del mes
    estadisticas = _calcular_estadisticas_mes(sesion)
    
    return render(request, 'agenda/partials/editar_form.html', {
        'sesion': sesion,
        'estadisticas': json.dumps(estadisticas),
    })


def _calcular_estadisticas_mes(sesion):
    """Calcular estadÃ­sticas del mes para el paciente"""
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