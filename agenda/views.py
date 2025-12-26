from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.db.models import Q, Count, Sum, F  # ✅ F en lugar de Proyecto
from django.core.paginator import Paginator
from datetime import datetime, timedelta, date
from decimal import Decimal

from agenda.models import Sesion, Proyecto  # ✅ AGREGAR ESTA LÍNEA
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

def lista_proyectos(request):
    """Lista de proyectos con filtros"""
    
    # Filtros
    buscar = request.GET.get('q', '').strip()
    estado_filtro = request.GET.get('estado', '')
    tipo_filtro = request.GET.get('tipo', '')
    sucursal_id = request.GET.get('sucursal', '')
    
    # Query base
    proyectos = Proyecto.objects.select_related(
        'paciente', 'servicio_base', 'profesional_responsable', 'sucursal'
    ).all()
    
    # Filtrar por sucursales del usuario
    sucursales_usuario = request.sucursales_usuario
    if sucursales_usuario is not None:
        if sucursales_usuario.exists():
            proyectos = proyectos.filter(sucursal__in=sucursales_usuario)
        else:
            proyectos = proyectos.none()
    
    # Aplicar filtros
    if buscar:
        proyectos = proyectos.filter(
            Q(codigo__icontains=buscar) |
            Q(nombre__icontains=buscar) |
            Q(paciente__nombre__icontains=buscar) |
            Q(paciente__apellido__icontains=buscar)
        )
    
    if estado_filtro:
        proyectos = proyectos.filter(estado=estado_filtro)
    
    if tipo_filtro:
        proyectos = proyectos.filter(tipo=tipo_filtro)
    
    if sucursal_id:
        proyectos = proyectos.filter(sucursal_id=sucursal_id)
    
    proyectos = proyectos.order_by('-fecha_inicio')
    
    # Paginación
    paginator = Paginator(proyectos, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    # Estadísticas
    estadisticas = {
        'total': proyectos.count(),
        'en_progreso': proyectos.filter(estado='en_progreso').count(),
        'planificados': proyectos.filter(estado='planificado').count(),
        'finalizados': proyectos.filter(estado='finalizado').count(),
    }
    
    # Sucursales para filtro
    from servicios.models import Sucursal
    if sucursales_usuario is not None and sucursales_usuario.exists():
        sucursales = sucursales_usuario
    else:
        sucursales = Sucursal.objects.filter(activa=True)
    
    context = {
        'page_obj': page_obj,
        'estadisticas': estadisticas,
        'buscar': buscar,
        'estado_filtro': estado_filtro,
        'tipo_filtro': tipo_filtro,
        'sucursal_id': sucursal_id,
        'sucursales': sucursales,
        'estados': Proyecto.ESTADO_CHOICES,
        'tipos': Proyecto.TIPO_CHOICES,
    }
    
    return render(request, 'agenda/lista_proyectos.html', context)


@login_required
@solo_sus_sucursales
def detalle_proyecto(request, proyecto_id):
    """Detalle completo de un proyecto"""
    
    proyecto = get_object_or_404(
        Proyecto.objects.select_related(
            'paciente', 'servicio_base', 'profesional_responsable', 'sucursal'
        ),
        id=proyecto_id
    )
    
    # Verificar permisos de sucursal
    sucursales_usuario = request.sucursales_usuario
    if sucursales_usuario is not None:
        if not sucursales_usuario.filter(id=proyecto.sucursal.id).exists():
            messages.error(request, '❌ No tienes permiso para ver este proyecto')
            return redirect('agenda:lista_proyectos')
    
    # Sesiones del proyecto
    sesiones = proyecto.sesiones.select_related(
        'profesional', 'servicio'
    ).order_by('-fecha', '-hora_inicio')
    
    # Pagos del proyecto
    from facturacion.models import Pago
    pagos = proyecto.pagos.filter(anulado=False).select_related(
        'metodo_pago', 'registrado_por'
    ).order_by('-fecha_pago')
    
    # Estadísticas
    stats = {
        'total_sesiones': sesiones.count(),
        'sesiones_realizadas': sesiones.filter(estado='realizada').count(),
        'total_horas': sum(s.duracion_minutos for s in sesiones) / 60,
    }
    
    context = {
        'proyecto': proyecto,
        'sesiones': sesiones,
        'pagos': pagos,
        'stats': stats,
    }
    
    return render(request, 'agenda/detalle_proyecto.html', context)


@login_required
@solo_sus_sucursales
def crear_proyecto(request):
    """Crear nuevo proyecto"""
    
    if request.method == 'POST':
        try:
            # Obtener datos del formulario
            nombre = request.POST.get('nombre')
            tipo = request.POST.get('tipo')
            paciente_id = request.POST.get('paciente_id')
            servicio_id = request.POST.get('servicio_id')
            profesional_id = request.POST.get('profesional_id')
            sucursal_id = request.POST.get('sucursal_id')
            fecha_inicio_str = request.POST.get('fecha_inicio')
            fecha_fin_estimada_str = request.POST.get('fecha_fin_estimada')
            costo_total = Decimal(request.POST.get('costo_total'))
            descripcion = request.POST.get('descripcion', '')
            
            # Validaciones
            if not all([nombre, tipo, paciente_id, servicio_id, profesional_id, sucursal_id, fecha_inicio_str, costo_total]):
                messages.error(request, '❌ Faltan datos obligatorios')
                return redirect('agenda:crear_proyecto')
            
            from datetime import datetime
            fecha_inicio = datetime.strptime(fecha_inicio_str, '%Y-%m-%d').date()
            fecha_fin_estimada = None
            if fecha_fin_estimada_str:
                fecha_fin_estimada = datetime.strptime(fecha_fin_estimada_str, '%Y-%m-%d').date()
            
            paciente = Paciente.objects.get(id=paciente_id)
            servicio = TipoServicio.objects.get(id=servicio_id)
            profesional = Profesional.objects.get(id=profesional_id)
            from servicios.models import Sucursal
            sucursal = Sucursal.objects.get(id=sucursal_id)
            
            # Verificar permisos
            sucursales_usuario = request.sucursales_usuario
            if sucursales_usuario is not None:
                if not sucursales_usuario.filter(id=sucursal.id).exists():
                    messages.error(request, '❌ No tienes permiso para crear proyectos en esta sucursal')
                    return redirect('agenda:crear_proyecto')
            
            # Crear proyecto
            proyecto = Proyecto.objects.create(
                nombre=nombre,
                tipo=tipo,
                paciente=paciente,
                servicio_base=servicio,
                profesional_responsable=profesional,
                sucursal=sucursal,
                fecha_inicio=fecha_inicio,
                fecha_fin_estimada=fecha_fin_estimada,
                costo_total=costo_total,
                descripcion=descripcion,
                creado_por=request.user
            )
            
            messages.success(request, f'✅ Proyecto {proyecto.codigo} creado correctamente')
            return redirect('agenda:detalle_proyecto', proyecto_id=proyecto.id)
            
        except Exception as e:
            messages.error(request, f'❌ Error: {str(e)}')
            return redirect('agenda:crear_proyecto')
    
    # GET - Mostrar formulario
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
        pacientes = Paciente.objects.filter(estado='activo').order_by('nombre', 'apellido')
        profesionales = Profesional.objects.filter(activo=True).order_by('nombre', 'apellido')
        from servicios.models import Sucursal
        sucursales = Sucursal.objects.filter(activa=True)
    
    servicios = TipoServicio.objects.filter(activo=True).order_by('nombre')
    
    context = {
        'pacientes': pacientes,
        'servicios': servicios,
        'profesionales': profesionales,
        'sucursales': sucursales,
        'tipos': Proyecto.TIPO_CHOICES,
        'fecha_hoy': date.today(),
    }
    
    return render(request, 'agenda/crear_proyecto.html', context)


@login_required
def actualizar_estado_proyecto(request, proyecto_id):
    """Actualizar estado de un proyecto (AJAX)"""
    
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)
    
    try:
        proyecto = Proyecto.objects.get(id=proyecto_id)
        nuevo_estado = request.POST.get('estado')
        
        if nuevo_estado not in dict(Proyecto.ESTADO_CHOICES):
            return JsonResponse({'error': 'Estado inválido'}, status=400)
        
        proyecto.estado = nuevo_estado
        proyecto.modificado_por = request.user
        
        # Si se finaliza, establecer fecha_fin_real
        if nuevo_estado == 'finalizado' and not proyecto.fecha_fin_real:
            from datetime import date
            proyecto.fecha_fin_real = date.today()
        
        proyecto.save()
        
        return JsonResponse({
            'success': True,
            'mensaje': f'Estado actualizado a: {proyecto.get_estado_display()}'
        })
        
    except Proyecto.DoesNotExist:
        return JsonResponse({'error': 'Proyecto no encontrado'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@solo_sus_sucursales
def calendario(request):
    """Calendario principal con filtros avanzados y permisos por sucursal"""
    
    # Obtener parámetros de filtro
    vista = request.GET.get('vista', 'semanal')
    fecha_str = request.GET.get('fecha', '')
    
    # ✅ CORRECCIÓN: Convertir strings vacíos a None
    estado_filtro = request.GET.get('estado', '').strip() or None
    paciente_id = request.GET.get('paciente', '').strip() or None
    profesional_id = request.GET.get('profesional', '').strip() or None
    servicio_id = request.GET.get('servicio', '').strip() or None
    sucursal_id = request.GET.get('sucursal', '').strip() or None
    tipo_sesion = request.GET.get('tipo_sesion', '').strip() or None
    
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
    
    # ✅ Query base - MOSTRAR TODAS LAS SESIONES
    sesiones = Sesion.objects.select_related(
        'paciente', 'profesional', 'servicio', 'sucursal', 'proyecto'
    ).filter(
        fecha__gte=fecha_inicio,
        fecha__lte=fecha_fin
    )
    
    # ✅ FILTRAR POR SUCURSALES DEL USUARIO
    sucursales_usuario = request.sucursales_usuario
    
    if sucursales_usuario is not None:
        if sucursales_usuario.exists():
            sesiones = sesiones.filter(sucursal__in=sucursales_usuario)
        else:
            sesiones = sesiones.none()
    
    # ✅ CORRECCIÓN: Solo aplicar filtros si tienen valor (no None)
    if sucursal_id:
        sesiones = sesiones.filter(sucursal_id=sucursal_id)
    
    if tipo_sesion == 'normal':
        sesiones = sesiones.filter(proyecto__isnull=True)
    elif tipo_sesion == 'evaluacion':
        sesiones = sesiones.filter(proyecto__isnull=False)
    # Si tipo_sesion es None: mostrar todas
    
    if estado_filtro:
        sesiones = sesiones.filter(estado=estado_filtro)
    
    if paciente_id:
        sesiones = sesiones.filter(paciente_id=paciente_id)
    
    if profesional_id:
        sesiones = sesiones.filter(profesional_id=profesional_id)
    
    if servicio_id:
        sesiones = sesiones.filter(servicio_id=servicio_id)
    
    sesiones = sesiones.order_by('fecha', 'hora_inicio')
    
    # =========================================================================
    # CÁLCULO DE ESTADÍSTICAS
    # =========================================================================
    from decimal import Decimal
    
    estadisticas = sesiones.aggregate(
        total_monto=Sum('monto_cobrado'),
        count_programadas=Count('id', filter=Q(estado='programada')),
        count_realizadas=Count('id', filter=Q(estado='realizada')),
        count_retraso=Count('id', filter=Q(estado='realizada_retraso')),
        count_falta=Count('id', filter=Q(estado='falta')),
        count_permiso=Count('id', filter=Q(estado='permiso')),
        count_cancelada=Count('id', filter=Q(estado='cancelada')),
        count_reprogramada=Count('id', filter=Q(estado='reprogramada')),
    )
    
    # Calcular pagos
    sesiones_con_pagos = sesiones.annotate(
        total_pagado_sesion=Sum('pagos__monto', filter=Q(pagos__anulado=False))
    )
    
    total_pagado = sesiones_con_pagos.aggregate(
        total=Sum('total_pagado_sesion')
    )['total'] or Decimal('0.00')
    
    sesiones_list = list(sesiones_con_pagos)
    total_pendiente = sum(
        max(s.monto_cobrado - (s.total_pagado_sesion or Decimal('0.00')), Decimal('0.00'))
        for s in sesiones_list
    )
    
    count_pagados = sum(
        1 for s in sesiones_list 
        if s.monto_cobrado > 0 and (s.total_pagado_sesion or Decimal('0.00')) >= s.monto_cobrado
    )
    count_pendientes = sum(
        1 for s in sesiones_list 
        if s.monto_cobrado > 0 and (s.total_pagado_sesion or Decimal('0.00')) < s.monto_cobrado
    )
    
    estadisticas['total_pagado'] = total_pagado
    estadisticas['total_pendiente'] = total_pendiente
    estadisticas['count_pagados'] = count_pagados
    estadisticas['count_pendientes'] = count_pendientes
    
    # ✅ CORRECCIÓN: Datos para filtros - DEPENDEN DE LA SUCURSAL SELECCIONADA
    if sucursales_usuario is not None and sucursales_usuario.exists():
        # Si hay sucursales asignadas al usuario
        if sucursal_id:
            # Si hay una sucursal específica seleccionada
            pacientes = Paciente.objects.filter(
                estado='activo',
                sucursales__id=sucursal_id
            ).distinct().order_by('nombre', 'apellido')
            
            profesionales = Profesional.objects.filter(
                activo=True,
                sucursales__id=sucursal_id
            ).distinct().order_by('nombre', 'apellido')
        else:
            # Mostrar todos de las sucursales del usuario
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
        # Superuser sin restricciones
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
    
    # ✅ CORRECCIÓN: Servicios dependen del paciente seleccionado
    if paciente_id:
        servicios = TipoServicio.objects.filter(
            pacienteservicio__paciente_id=paciente_id,
            pacienteservicio__activo=True,
            activo=True
        ).distinct().order_by('nombre')
    else:
        servicios = TipoServicio.objects.filter(activo=True).order_by('nombre')
    
    # Marcar última sesión por paciente+servicio
    from collections import defaultdict
    
    combinaciones_paciente_servicio = set()
    for sesion in sesiones:
        combinaciones_paciente_servicio.add((sesion.paciente_id, sesion.servicio_id))
    
    ultimas_sesiones_ids = set()
    for paciente_id_combo, servicio_id_combo in combinaciones_paciente_servicio:
        ultima_sesion = Sesion.objects.filter(
            paciente_id=paciente_id_combo,
            servicio_id=servicio_id_combo,
            estado__in=['programada', 'realizada', 'realizada_retraso']
        ).order_by('-fecha', '-hora_inicio').first()
        
        if ultima_sesion:
            ultimas_sesiones_ids.add(ultima_sesion.id)
    
    for sesion in sesiones:
        sesion.es_ultima_sesion_paciente_servicio = sesion.id in ultimas_sesiones_ids
    
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
        fecha_anterior = (fecha_base.replace(day=1) - timedelta(days=1)).replace(day=1)
        if fecha_base.month == 12:
            fecha_siguiente = fecha_base.replace(year=fecha_base.year + 1, month=1, day=1)
        else:
            fecha_siguiente = fecha_base.replace(month=fecha_base.month + 1, day=1)
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
        
        # ✅ CORRECCIÓN: Pasar valores originales (pueden ser None)
        'estado_filtro': estado_filtro or '',
        'paciente_id': paciente_id or '',
        'profesional_id': profesional_id or '',
        'servicio_id': servicio_id or '',
        'sucursal_id': sucursal_id or '',
        'tipo_sesion': tipo_sesion or '',
        
        'sucursales_usuario': sucursales_usuario,
        
        # Estadísticas
        'total_monto': estadisticas['total_monto'] or 0,
        'total_pagado': estadisticas['total_pagado'] or 0,
        'total_pendiente': estadisticas['total_pendiente'] or 0,
        'count_programadas': estadisticas['count_programadas'],
        'count_realizadas': estadisticas['count_realizadas'],
        'count_retraso': estadisticas['count_retraso'],
        'count_falta': estadisticas['count_falta'],
        'count_permiso': estadisticas['count_permiso'],
        'count_cancelada': estadisticas['count_cancelada'],
        'count_reprogramada': estadisticas['count_reprogramada'],
        'count_pagados': estadisticas['count_pagados'],
        'count_pendientes': estadisticas['count_pendientes'],
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
    """Generar estructura para vista semanal CON OPTIMIZACIÓN"""
    from datetime import time
    from itertools import groupby
    
    dias = []
    for i in range(7):
        dia = fecha_inicio + timedelta(days=i)
        sesiones_dia = [s for s in sesiones if s.fecha == dia]
        
        # ✅ OPTIMIZACIÓN: Pre-calcular si hay sesiones de mañana Y tarde
        tiene_manana = any(s.hora_inicio.hour < 13 for s in sesiones_dia)
        tiene_tarde = any(s.hora_inicio.hour >= 13 for s in sesiones_dia)
        
        # ✅ NUEVO: Agrupar sesiones y marcar el primer grupo de tarde
        sesiones_agrupadas = []
        if sesiones_dia:
            # Ordenar por hora
            sesiones_ordenadas = sorted(sesiones_dia, key=lambda s: s.hora_inicio)
            
            # Agrupar por hora
            grupos = []
            for hora, grupo_sesiones in groupby(sesiones_ordenadas, key=lambda s: s.hora_inicio.hour):
                grupos.append({
                    'hora': hora,
                    'sesiones': list(grupo_sesiones)
                })
            
            # Marcar el primer grupo >= 13
            primer_tarde_encontrado = False
            for grupo in grupos:
                grupo['mostrar_linea_tarde'] = False
                if grupo['hora'] >= 13 and not primer_tarde_encontrado and tiene_manana:
                    grupo['mostrar_linea_tarde'] = True
                    primer_tarde_encontrado = True
            
            sesiones_agrupadas = grupos
        
        dias.append({
            'fecha': dia,
            'es_hoy': dia == date.today(),
            'sesiones': sesiones_dia,
            'sesiones_agrupadas': sesiones_agrupadas,  # ✅ NUEVO
            'dia_nombre': dia.strftime('%A'),
            'dia_numero': dia.day,
            'tiene_sesiones_manana': tiene_manana,
            'tiene_sesiones_tarde': tiene_tarde,
        })
    return {'dias': dias, 'tipo': 'semanal'}

def _generar_calendario_mensual(fecha_base, sesiones):
    """Generar estructura para vista mensual tipo cuadrícula CON OPTIMIZACIÓN"""
    from itertools import groupby
    
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
                'sesiones_agrupadas': [],
            })
    
    dias_mes_actual = []
    for dia_num in range(1, ultimo_dia.day + 1):
        dia = fecha_base.replace(day=dia_num)
        sesiones_dia = [s for s in sesiones if s.fecha == dia]
        
        # ✅ OPTIMIZACIÓN: Pre-calcular mañana/tarde y agrupar
        tiene_manana = any(s.hora_inicio.hour < 13 for s in sesiones_dia)
        tiene_tarde = any(s.hora_inicio.hour >= 13 for s in sesiones_dia)
        
        sesiones_agrupadas = []
        if sesiones_dia:
            sesiones_ordenadas = sorted(sesiones_dia, key=lambda s: s.hora_inicio)
            grupos = []
            
            for hora, grupo_sesiones in groupby(sesiones_ordenadas, key=lambda s: s.hora_inicio.hour):
                grupos.append({
                    'hora': hora,
                    'sesiones': list(grupo_sesiones)
                })
            
            # Marcar primer grupo >= 13 si hay mañana
            primer_tarde_encontrado = False
            for grupo in grupos:
                grupo['mostrar_linea_tarde'] = False
                if grupo['hora'] >= 13 and not primer_tarde_encontrado and tiene_manana:
                    grupo['mostrar_linea_tarde'] = True
                    primer_tarde_encontrado = True
            
            sesiones_agrupadas = grupos
        
        dias_mes_actual.append({
            'fecha': dia,
            'es_hoy': dia == date.today(),
            'es_otro_mes': False,
            'sesiones': sesiones_dia,
            'sesiones_agrupadas': sesiones_agrupadas,  # ✅ NUEVO
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
                'sesiones_agrupadas': [],
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
            
            # 🆕 NUEVO: Obtener proyecto si fue seleccionado
            asignar_proyecto = request.POST.get('asignar_proyecto') == 'on'
            proyecto_id = request.POST.get('proyecto_id')
            proyecto = None
            
            if asignar_proyecto and proyecto_id:
                try:
                    proyecto = Proyecto.objects.get(id=proyecto_id)
                    print(f"✅ Proyecto seleccionado: {proyecto.codigo}")
                except Proyecto.DoesNotExist:
                    messages.error(request, '❌ El proyecto seleccionado no existe')
                    return redirect('agenda:agendar_recurrente')
            
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
            
            # 🆕 DETERMINAR MONTO: Si es proyecto, monto = 0
            if proyecto:
                monto = Decimal('0.00')
                print(f"💰 Sesiones de proyecto: monto = Bs. 0.00")
            else:
                paciente_servicio = PacienteServicio.objects.get(
                    paciente=paciente,
                    servicio=servicio
                )
                monto = paciente_servicio.costo_sesion
                print(f"💰 Sesiones normales: monto = Bs. {monto}")
            
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
                            # 🆕 CREAR SESIÓN CON PROYECTO
                            Sesion.objects.create(
                                paciente=paciente,
                                servicio=servicio,
                                profesional=profesional,
                                sucursal=sucursal,
                                proyecto=proyecto,  # 🆕 NUEVO
                                fecha=fecha_actual,
                                hora_inicio=hora,
                                hora_fin=hora_fin,
                                duracion_minutos=duracion_minutos,
                                monto_cobrado=monto,  # 0 si es proyecto
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
                proyecto_msg = f" vinculadas al proyecto {proyecto.codigo}" if proyecto else ""
                messages.success(request, f'✅ Se crearon {sesiones_creadas} sesiones{duracion_msg}{proyecto_msg} correctamente.')
            else:
                messages.warning(request, '⚠️ No se pudo crear ninguna sesión. Verifica los conflictos de horario.')
            
            if sesiones_error:
                error_msg = f'⚠️ {len(sesiones_error)} sesiones no se pudieron crear por conflictos de horario.'
                messages.warning(request, error_msg)
            
            return redirect('agenda:calendario')
            
        except Exception as e:
            messages.error(request, f'Error al crear sesiones: {str(e)}')
            import traceback
            print(traceback.format_exc())  # Para debugging
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
    sucursal_id = request.GET.get('sucursal', '').strip()
    
    # ✅ Si no hay sucursal, devolver lista vacía
    if not sucursal_id:
        return render(request, 'agenda/partials/pacientes_select.html', {
            'pacientes': []
        })
    
    try:
        # Filtrar pacientes de la sucursal
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
    """✅ API: Cargar servicios contratados por un paciente (HTMX)"""
    paciente_id = request.GET.get('paciente', '').strip()
    
    # ✅ Si no hay paciente, devolver lista vacía
    if not paciente_id:
        return render(request, 'agenda/partials/servicios_select.html', {
            'servicios': []
        })
    
    try:
        # ✅ CORRECCIÓN CRÍTICA: Filtrar SOLO servicios ACTIVOS del paciente
        servicios = PacienteServicio.objects.filter(
            paciente_id=paciente_id,
            activo=True  # Solo servicios activos
        ).select_related('servicio').filter(
            servicio__activo=True  # Y el servicio debe estar activo
        )
        
        # Verificar si hay servicios
        if not servicios.exists():
            return render(request, 'agenda/partials/servicios_select.html', {
                'servicios': [],
                'error': 'Este paciente no tiene servicios contratados activos'
            })
        
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
    servicio_id = request.GET.get('servicio', '').strip()
    sucursal_id = request.GET.get('sucursal', '').strip()
    
    # ✅ Si falta servicio o sucursal, devolver lista vacía
    if not servicio_id or not sucursal_id:
        return render(request, 'agenda/partials/profesionales_select.html', {
            'profesionales': [],
            'error': 'Faltan datos requeridos' if not servicio_id or not sucursal_id else None
        })
    
    try:
        # ✅ CORRECCIÓN: Profesionales que:
        # 1. Están activos
        # 2. Tienen la sucursal asignada
        # 3. Ofrecen el servicio seleccionado
        profesionales = Profesional.objects.filter(
            activo=True,
            sucursales__id=sucursal_id,
            servicios__id=servicio_id
        ).distinct().order_by('nombre', 'apellido')
        
        # Verificar si hay profesionales
        if not profesionales.exists():
            return render(request, 'agenda/partials/profesionales_select.html', {
                'profesionales': [],
                'error': 'No hay profesionales disponibles para este servicio en esta sucursal'
            })
        
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
    """Editar sesión con validación de pagos"""
    sesion = get_object_or_404(Sesion, id=sesion_id)
    
    if request.method == 'POST':
        try:
            estado_nuevo = request.POST.get('estado')
            
            # 🆕 VALIDACIÓN: Si cambia a estado sin cobro y tiene pagos
            if estado_nuevo in ['permiso', 'cancelada', 'reprogramada']:
                pagos_activos = sesion.pagos.filter(anulado=False)
                
                if pagos_activos.exists():
                    # ✅ AJAX: Devolver JSON indicando que necesita confirmación
                    total_pagado = pagos_activos.aggregate(Sum('monto'))['monto__sum']
                    
                    return JsonResponse({
                        'requiere_confirmacion': True,
                        'sesion_id': sesion.id,
                        'estado_nuevo': estado_nuevo,
                        'total_pagado': float(total_pagado),
                        'cantidad_pagos': pagos_activos.count(),
                        'mensaje': f'Esta sesión tiene {pagos_activos.count()} pago(s) registrado(s) por Bs. {total_pagado}'
                    })
            
            # Si no hay pagos o no es estado sin cobro, continuar normal
            sesion.estado = estado_nuevo
            
            # Aplicar políticas de cobro según estado
            if estado_nuevo in ['permiso', 'cancelada', 'reprogramada']:
                sesion.monto_cobrado = Decimal('0.00')
            
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
                sesion.reprogramacion_realizada = request.POST.get('reprogramacion_realizada') == 'on'
            
            sesion.modificada_por = request.user
            sesion.save()
            
            messages.success(request, '✅ Sesión actualizada correctamente')
            
            return JsonResponse({'success': True})
            
        except Exception as e:
            return JsonResponse({
                'error': True,
                'mensaje': str(e)
            }, status=400)
    
    # GET - Mostrar formulario
    estadisticas = _calcular_estadisticas_mes(sesion)
    
    return render(request, 'agenda/partials/editar_form.html', {
        'sesion': sesion,
        'estadisticas': json.dumps(estadisticas),
    })


@login_required
def modal_confirmar_cambio_estado(request, sesion_id):
    """
    API: Generar contenido del modal de confirmación (HTMX)
    Esta vista devuelve SOLO el HTML del modal, no una página completa
    """
    sesion = get_object_or_404(Sesion, id=sesion_id)
    estado_nuevo = request.GET.get('estado')
    
    pagos_activos = sesion.pagos.filter(anulado=False)
    total_pagado = pagos_activos.aggregate(Sum('monto'))['monto__sum']
    
    return render(request, 'agenda/partials/modal_confirmar_cambio.html', {
        'sesion': sesion,
        'estado_nuevo': estado_nuevo,
        'pagos': pagos_activos,
        'total_pagado': total_pagado
    })

@login_required
def procesar_cambio_estado(request, sesion_id):
    """
    Procesar cambio de estado con manejo de pagos
    🆕 NUEVO: Gestiona conversión a crédito, anulación, o transferencia
    """
    
    if request.method != 'POST':
        return redirect('agenda:calendario')
    
    sesion = get_object_or_404(Sesion, id=sesion_id)
    
    try:
        from django.db import transaction
        
        estado_nuevo = request.POST.get('estado_nuevo')
        accion_pago = request.POST.get('accion_pago')
        observaciones_cambio = request.POST.get('observaciones_cambio', '')
        
        with transaction.atomic():
            # Obtener pagos activos
            pagos_activos = sesion.pagos.filter(anulado=False)
            
            # ACCIÓN 1: CONVERTIR A CRÉDITO (A FAVOR)
            if accion_pago == 'convertir_credito':
                for pago in pagos_activos:
                    # Desvincular de la sesión
                    pago.sesion = None
                    
                    # Actualizar concepto
                    pago.concepto = f"Crédito por sesión {sesion.fecha} ({estado_nuevo})"
                    
                    # Agregar observación
                    if observaciones_cambio:
                        pago.observaciones += f"\n\n[Sistema] {observaciones_cambio}"
                    pago.observaciones += f"\n[Sistema] Convertido a crédito el {date.today()} - Sesión cambió a {estado_nuevo}"
                    
                    pago.save()
                
                messages.success(
                    request, 
                    f'✅ Estado cambiado a "{estado_nuevo}". '
                    f'Bs. {pagos_activos.aggregate(Sum("monto"))["monto__sum"]} convertidos a saldo a favor'
                )
            
            # ACCIÓN 2: ANULAR PAGO
            elif accion_pago == 'anular_pago':
                motivo_anulacion = request.POST.get('motivo_anulacion', '').strip()
                
                if not motivo_anulacion:
                    messages.error(request, '❌ Debe especificar un motivo de anulación')
                    return redirect('agenda:calendario')
                
                for pago in pagos_activos:
                    pago.anular(
                        user=request.user,
                        motivo=f"Sesión cambió a {estado_nuevo}. {motivo_anulacion}"
                    )
                
                messages.warning(
                    request,
                    f'⚠️ Estado cambiado a "{estado_nuevo}". '
                    f'{pagos_activos.count()} pago(s) anulado(s). DEBE devolver el dinero al paciente.'
                )
            
            # ACCIÓN 3: TRANSFERIR (SOLO REPROGRAMADA)
            elif accion_pago == 'transferir_pago':
                # Los pagos quedan vinculados a la sesión
                # Cuando se cree la nueva sesión, se pueden transferir manualmente
                
                # Agregar nota
                sesion.observaciones += f"\n[Sistema] Pagos pendientes de transferir a nueva sesión"
                
                messages.info(
                    request,
                    f'ℹ️ Estado cambiado a "Reprogramada". '
                    f'Los pagos quedarán disponibles para transferir a la nueva sesión.'
                )
            
            # ✅ CRÍTICO: Cambiar estado de la sesión
            sesion.estado = estado_nuevo
            sesion.monto_cobrado = Decimal('0.00')
            
            if observaciones_cambio:
                sesion.observaciones += f"\n\n{observaciones_cambio}"
            
            sesion.modificada_por = request.user
            sesion.save()
                    
        return redirect('agenda:calendario')
        
    except Exception as e:
        messages.error(request, f'❌ Error: {str(e)}')
        return redirect('agenda:calendario')

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
    
@login_required
def obtener_proyectos_paciente(request, paciente_id):
    """
    🆕 API JSON: Obtener proyectos activos de un paciente
    Usado en agendar_recurrente.html para cargar proyectos dinámicamente
    """
    try:
        # Validar que el paciente existe
        paciente = get_object_or_404(Paciente, id=paciente_id)
        
        # Obtener proyectos activos (no finalizados ni cancelados)
        proyectos = Proyecto.objects.filter(
            paciente=paciente,
            estado__in=['planificado', 'en_progreso']
        ).select_related('servicio_base', 'sucursal').order_by('-fecha_inicio')
        
        # Verificar permisos de sucursal del usuario
        sucursales_usuario = request.sucursales_usuario
        if sucursales_usuario is not None and sucursales_usuario.exists():
            proyectos = proyectos.filter(sucursal__in=sucursales_usuario)
        
        # Construir respuesta JSON
        proyectos_data = []
        for proyecto in proyectos:
            proyectos_data.append({
                'id': proyecto.id,
                'codigo': proyecto.codigo,
                'nombre': proyecto.nombre,
                'tipo': proyecto.get_tipo_display(),
                'costo_total': float(proyecto.costo_total),
                'total_pagado': float(proyecto.total_pagado),
                'saldo_pendiente': float(proyecto.saldo_pendiente),
                'sesiones_completadas': proyecto.sesiones.filter(
                    estado__in=['realizada', 'realizada_retraso']
                ).count(),
                'estado': proyecto.get_estado_display(),
            })
        
        return JsonResponse({
            'success': True,
            'proyectos': proyectos_data
        })
        
    except Paciente.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Paciente no encontrado'
        }, status=404)
    
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)