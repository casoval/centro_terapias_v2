from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.db.models import Q, Count, Sum, F, OuterRef, Subquery, Case, When, Value, DecimalField
from django.db.models.functions import Coalesce
from django.core.paginator import Paginator
from datetime import datetime, timedelta, date
from calendar import monthrange
from decimal import Decimal

from agenda.models import Sesion, Proyecto, Mensualidad
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

# ============= 💳 MENSUALIDADES =============

@login_required
@solo_sus_sucursales
def crear_mensualidad(request):
    """Crear nueva mensualidad"""
    
    if request.method == 'POST':
        try:
            from django.db import transaction
            
            # Obtener datos del formulario
            paciente_id = request.POST.get('paciente_id')
            servicio_id = request.POST.get('servicio_id')
            profesional_id = request.POST.get('profesional_id')
            sucursal_id = request.POST.get('sucursal_id')
            mes = int(request.POST.get('mes'))
            anio = int(request.POST.get('anio'))
            costo_mensual = Decimal(request.POST.get('costo_mensual'))
            observaciones = request.POST.get('observaciones', '')
            
            # Validaciones básicas
            if not all([paciente_id, servicio_id, profesional_id, sucursal_id, mes, anio, costo_mensual]):
                messages.error(request, '❌ Faltan datos obligatorios')
                return redirect('agenda:crear_mensualidad')
            
            paciente = Paciente.objects.get(id=paciente_id)
            servicio = TipoServicio.objects.get(id=servicio_id)
            profesional = Profesional.objects.get(id=profesional_id)
            sucursal = Sucursal.objects.get(id=sucursal_id)
            
            # Verificar permisos
            sucursales_usuario = request.sucursales_usuario
            if sucursales_usuario is not None:
                if not sucursales_usuario.filter(id=sucursal.id).exists():
                    messages.error(request, '❌ No tienes permiso para crear mensualidades en esta sucursal')
                    return redirect('agenda:crear_mensualidad')
            
            # Verificar si ya existe mensualidad para ese paciente/servicio/período
            mensualidad_existente = Mensualidad.objects.filter(
                paciente=paciente,
                servicio=servicio,
                mes=mes,
                anio=anio
            ).first()
            
            if mensualidad_existente:
                messages.error(
                    request, 
                    f'❌ Ya existe una mensualidad para {paciente} - {servicio} en {mensualidad_existente.periodo_display}'
                )
                return redirect('agenda:crear_mensualidad')
            
            # ✅ Crear mensualidad (sin configuración de sesiones)
            with transaction.atomic():
                mensualidad = Mensualidad.objects.create(
                    paciente=paciente,
                    servicio=servicio,
                    profesional=profesional,
                    sucursal=sucursal,
                    mes=mes,
                    anio=anio,
                    costo_mensual=costo_mensual,
                    observaciones=observaciones,
                    creada_por=request.user
                )
            
            messages.success(request, f'✅ Mensualidad {mensualidad.codigo} creada correctamente')
            messages.info(request, '📌 Ahora puedes agregar las sesiones desde "Agendar Sesión Recurrente"')
            
            return redirect('agenda:detalle_mensualidad', mensualidad_id=mensualidad.id)
            
        except Exception as e:
            messages.error(request, f'❌ Error: {str(e)}')
            import traceback
            print(traceback.format_exc())
            return redirect('agenda:crear_mensualidad')
    
    # GET - Mostrar formulario
    sucursales_usuario = request.sucursales_usuario
    
    if sucursales_usuario is not None and sucursales_usuario.exists():
        sucursales = sucursales_usuario
    else:
        sucursales = Sucursal.objects.filter(activa=True)
    
    context = {
        'sucursales': sucursales,
        'fecha_hoy': date.today(),
    }
    
    return render(request, 'agenda/crear_mensualidad.html', context)

@login_required
@solo_sus_sucursales
def lista_mensualidades(request):
    """Lista de mensualidades con filtros"""
    
    # Filtros
    buscar = request.GET.get('q', '').strip()
    estado_filtro = request.GET.get('estado', '')
    sucursal_id = request.GET.get('sucursal', '')
    
    # Query base - ✅ SIN ANOTACIONES
    mensualidades = Mensualidad.objects.select_related(
        'paciente', 'servicio', 'profesional', 'sucursal'
    ).prefetch_related('sesiones')  # ✅ Optimiza las queries de las propiedades
    
    # Filtrar por sucursales del usuario
    sucursales_usuario = request.sucursales_usuario
    if sucursales_usuario is not None:
        if sucursales_usuario.exists():
            mensualidades = mensualidades.filter(sucursal__in=sucursales_usuario)
        else:
            mensualidades = mensualidades.none()
    
    # Aplicar filtros
    if buscar:
        mensualidades = mensualidades.filter(
            Q(codigo__icontains=buscar) |
            Q(paciente__nombre__icontains=buscar) |
            Q(paciente__apellido__icontains=buscar)
        )
    
    if estado_filtro:
        mensualidades = mensualidades.filter(estado=estado_filtro)
    
    if sucursal_id:
        mensualidades = mensualidades.filter(sucursal_id=sucursal_id)
    
    mensualidades = mensualidades.order_by('-anio', '-mes', '-fecha_creacion')
    
    # Paginación
    paginator = Paginator(mensualidades, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    # Estadísticas
    estadisticas = {
        'total': mensualidades.count(),
        'activas': mensualidades.filter(estado='activa').count(),
        'pausadas': mensualidades.filter(estado='pausada').count(),
        'completadas': mensualidades.filter(estado='completada').count(),
    }
    
    # Sucursales para filtro
    if sucursales_usuario is not None and sucursales_usuario.exists():
        sucursales = sucursales_usuario
    else:
        sucursales = Sucursal.objects.filter(activa=True)
    
    context = {
        'page_obj': page_obj,
        'estadisticas': estadisticas,
        'buscar': buscar,
        'estado_filtro': estado_filtro,
        'sucursal_id': sucursal_id,
        'sucursales': sucursales,
        'estados': Mensualidad.ESTADO_CHOICES,
    }
    
    return render(request, 'agenda/lista_mensualidades.html', context)

@login_required
@solo_sus_sucursales
def detalle_mensualidad(request, mensualidad_id):
    """Detalle completo de una mensualidad"""
    
    mensualidad = get_object_or_404(
        Mensualidad.objects.select_related(
            'paciente', 'servicio', 'profesional', 'sucursal'
        ),
        id=mensualidad_id
    )
    
    # Verificar permisos de sucursal
    sucursales_usuario = request.sucursales_usuario
    if sucursales_usuario is not None:
        if not sucursales_usuario.filter(id=mensualidad.sucursal.id).exists():
            messages.error(request, '❌ No tienes permiso para ver esta mensualidad')
            return redirect('agenda:lista_mensualidades')
    
    # Sesiones de la mensualidad
    sesiones = mensualidad.sesiones.select_related(
        'profesional', 'servicio'
    ).order_by('fecha', 'hora_inicio')
    
    # Pagos de la mensualidad
    from facturacion.models import Pago
    pagos = Pago.objects.filter(
        mensualidad=mensualidad,
        anulado=False
    ).select_related(
        'metodo_pago', 'registrado_por'
    ).order_by('-fecha_pago')
    
    # Estadísticas
    stats = {
        'total_sesiones': sesiones.count(),
        'sesiones_realizadas': sesiones.filter(
            estado__in=['realizada', 'realizada_retraso']
        ).count(),
        'total_horas': sum(s.duracion_minutos for s in sesiones) / 60,
    }
    
    context = {
        'mensualidad': mensualidad,
        'sesiones': sesiones,
        'pagos': pagos,
        'stats': stats,
    }
    
    return render(request, 'agenda/detalle_mensualidad.html', context)


@login_required
def actualizar_estado_mensualidad(request, mensualidad_id):
    """Actualizar estado de una mensualidad (AJAX)"""
    
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)
    
    try:
        mensualidad = Mensualidad.objects.get(id=mensualidad_id)
        nuevo_estado = request.POST.get('estado')
        
        if nuevo_estado not in dict(Mensualidad.ESTADO_CHOICES):
            return JsonResponse({'error': 'Estado inválido'}, status=400)
        
        mensualidad.estado = nuevo_estado
        mensualidad.modificada_por = request.user
        mensualidad.save()
        
        return JsonResponse({
            'success': True,
            'mensaje': f'Estado actualizado a: {mensualidad.get_estado_display()}'
        })
        
    except Mensualidad.DoesNotExist:
        return JsonResponse({'error': 'Mensualidad no encontrada'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def confirmacion_mensualidad(request):
    """
    Vista de confirmación después de crear mensualidad
    """
    
    # Obtener datos de la sesión
    datos_mensualidad = request.session.get('mensualidad_creada')
    
    if not datos_mensualidad:
        messages.error(request, '❌ No hay datos de mensualidad para mostrar')
        return redirect('agenda:lista_mensualidades')
    
    # Limpiar sesión después de obtener datos
    del request.session['mensualidad_creada']
    
    context = {
        'datos_mensualidad': datos_mensualidad,
    }
    
    return render(request, 'agenda/confirmacion_mensualidad.html', context)

@login_required
@solo_sus_sucursales
def calendario(request):
    """Calendario principal con filtros avanzados y permisos por sucursal"""
    from .services import CalendarService
    
    # Obtener parámetros de filtro
    vista = request.GET.get('vista', 'semanal')
    fecha_str = request.GET.get('fecha', '')
    
    # Filtros
    estado_filtro = request.GET.get('estado', '').strip() or None
    paciente_id = request.GET.get('paciente', '').strip() or None
    profesional_id = request.GET.get('profesional', '').strip() or None
    servicio_id = request.GET.get('servicio', '').strip() or None
    sucursal_id = request.GET.get('sucursal', '').strip() or None
    tipo_sesion = request.GET.get('tipo_sesion', '').strip() or None
    
    # ✅ CORREGIDO: Verificar si es profesional Y tiene registro
    es_profesional = False
    profesional_actual = None
    
    if hasattr(request.user, 'perfil') and request.user.perfil.es_profesional() and not request.user.is_superuser:
        # ✅ Verificar que tenga profesional asignado
        if request.user.perfil.profesional:
            profesional_actual = request.user.perfil.profesional
            profesional_id = str(profesional_actual.id)
            es_profesional = True
        else:
            # ❌ Es profesional pero no tiene registro
            messages.error(request, '❌ Tu usuario de profesional no tiene un registro asignado')
            return redirect('/')
    
    # Fecha base
    if fecha_str:
        try:
            fecha_base = datetime.strptime(fecha_str, '%Y-%m-%d').date()
        except:
            fecha_base = date.today()
    else:
        fecha_base = date.today()
        
    # ✅ CORREGIDO: Calcular rango según la vista
    if vista == 'lista':
        # Para vista lista, usar filtros de fecha del usuario o None (sin límite)
        fecha_desde_str = request.GET.get('fecha_desde', '').strip()
        fecha_hasta_str = request.GET.get('fecha_hasta', '').strip()
        
        if fecha_desde_str:
            try:
                fecha_inicio = datetime.strptime(fecha_desde_str, '%Y-%m-%d').date()
            except:
                fecha_inicio = None
        else:
            fecha_inicio = None
        
        if fecha_hasta_str:
            try:
                fecha_fin = datetime.strptime(fecha_hasta_str, '%Y-%m-%d').date()
            except:
                fecha_fin = None
        else:
            fecha_fin = None
    elif vista == 'diaria':
        fecha_inicio = fecha_base
        fecha_fin = fecha_base
    elif vista == 'mensual':
        primer_dia = fecha_base.replace(day=1)
        # ✅ CORREGIDO: Usar monthrange para obtener el último día válido del mes
        ultimo_dia_del_mes = monthrange(fecha_base.year, fecha_base.month)[1]
        ultimo_dia = fecha_base.replace(day=ultimo_dia_del_mes)
        fecha_inicio = primer_dia
        fecha_fin = ultimo_dia
    else: # semanal por defecto
        dias_desde_lunes = fecha_base.weekday()
        fecha_inicio = fecha_base - timedelta(days=dias_desde_lunes)
        fecha_fin = fecha_inicio + timedelta(days=6)

    # 1. Obtener sesiones filtradas usando el servicio
    sesiones = CalendarService.get_filtered_sessions(
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        sucursales_usuario=request.sucursales_usuario,
        sucursal_id=sucursal_id,
        tipo_sesion=tipo_sesion,
        estado=estado_filtro,
        paciente_id=paciente_id,
        profesional_id=profesional_id,
        servicio_id=servicio_id
    )
    
    # 2. Anotaciones extra (Business Logic específica de la vista)
    # Marcar última sesión por paciente+servicio
    latest_sesion_sq = Sesion.objects.filter(
        paciente=OuterRef('paciente'),
        servicio=OuterRef('servicio'),
        estado__in=['programada', 'realizada', 'realizada_retraso']
    ).order_by('-fecha', '-hora_inicio').values('id')[:1]
    
    sesiones = sesiones.annotate(
        latest_sesion_id=Subquery(latest_sesion_sq)
    )
    
    # ✅ ORDENAR: Las fechas más recientes primero (descendente)
    sesiones = sesiones.order_by('-fecha', '-hora_inicio')
    
    sesiones_lista = []
    for sesion in sesiones:
        sesion.es_ultima_sesion_paciente_servicio = (sesion.id == sesion.latest_sesion_id)
        sesiones_lista.append(sesion)
    
    # ✅ NUEVO: Paginación para vista lista
    if vista == 'lista':
        # Obtener cantidad de items por página (default: 50)
        por_pagina = request.GET.get('por_pagina', '50')
        try:
            por_pagina = int(por_pagina)
            # Validar que esté en rango permitido
            if por_pagina not in [25, 50, 100, 200]:
                por_pagina = 50
        except:
            por_pagina = 50
        
        # Aplicar paginación
        from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
        
        paginator = Paginator(sesiones_lista, por_pagina)
        page_number = request.GET.get('page', 1)
        
        try:
            sesiones_paginadas = paginator.get_page(page_number)
        except PageNotAnInteger:
            sesiones_paginadas = paginator.get_page(1)
        except EmptyPage:
            sesiones_paginadas = paginator.get_page(paginator.num_pages)
        
        # Para vista lista, usar sesiones paginadas
        sesiones_lista = list(sesiones_paginadas)
        page_obj = sesiones_paginadas
    else:
        page_obj = None

    # 3. Generar estructura del calendario
    calendario_data = CalendarService.get_calendar_data(vista, fecha_base, sesiones_lista)
    
    # 4. Estadísticas
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
        total_pagado_sesion=Coalesce(Sum('pagos__monto', filter=Q(pagos__anulado=False)), Decimal('0.00'))
    )
    
    stats_pagos = sesiones_con_pagos.aggregate(
        total_pagado=Sum('total_pagado_sesion'),
        total_pendiente=Sum(
             Case(
                 When(monto_cobrado__gt=F('total_pagado_sesion'), then=F('monto_cobrado') - F('total_pagado_sesion')),
                 default=Decimal('0.00'),
                 output_field=DecimalField()
             )
        ),
        count_pagados=Count(
            Case(
                When(monto_cobrado__gt=0, total_pagado_sesion__gte=F('monto_cobrado'), then=1),
                output_field=DecimalField()
            )
        ),
        count_pendientes=Count(
            Case(
                When(monto_cobrado__gt=0, total_pagado_sesion__lt=F('monto_cobrado'), then=1),
                output_field=DecimalField()
            )
        )
    )

    estadisticas['total_pagado'] = stats_pagos['total_pagado'] or Decimal('0.00')
    estadisticas['total_pendiente'] = stats_pagos['total_pendiente'] or Decimal('0.00')
    estadisticas['count_pagados'] = stats_pagos['count_pagados']
    estadisticas['count_pendientes'] = stats_pagos['count_pendientes']
    
    # 5. Datos para Selectores (Filtros)
    sucursales_usuario = request.sucursales_usuario

    # ✅ OPTIMIZACIÓN: Si es profesional, SOLO cargar SU registro (sin importar sucursales)
    if es_profesional:
        profesionales = Profesional.objects.filter(id=profesional_id)
        
        # Para pacientes y servicios, filtrar según sucursales si existen
        if sucursales_usuario is not None and sucursales_usuario.exists():
            if sucursal_id:
                pacientes = Paciente.objects.filter(
                    estado='activo', 
                    sucursales__id=sucursal_id
                ).distinct().order_by('nombre', 'apellido')
            else:
                pacientes = Paciente.objects.filter(
                    estado='activo', 
                    sucursales__in=sucursales_usuario
                ).distinct().order_by('nombre', 'apellido')
            sucursales = sucursales_usuario
        else:
            # Profesional sin sucursales asignadas (superuser)
            if sucursal_id:
                pacientes = Paciente.objects.filter(
                    estado='activo', 
                    sucursales__id=sucursal_id
                ).distinct().order_by('nombre', 'apellido')
            else:
                pacientes = Paciente.objects.filter(estado='activo').order_by('nombre', 'apellido')
            sucursales = Sucursal.objects.filter(activa=True)

    else:
        # ✅ NO ES PROFESIONAL: Cargar según sucursales
        if sucursales_usuario is not None and sucursales_usuario.exists():
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
            # Superuser o usuario sin sucursales
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

    # ✅ SERVICIOS: Filtrar según paciente seleccionado (aplica para TODOS los roles)
    if paciente_id:
        servicios = TipoServicio.objects.filter(
            pacientes__id=paciente_id,
            activo=True
        ).distinct().order_by('nombre')
    else:
        servicios = TipoServicio.objects.filter(activo=True).order_by('nombre')
    
    # Navegación
    if vista == 'lista':
        # ✅ Para vista lista, la navegación no aplica (no hay anterior/siguiente)
        fecha_anterior = None
        fecha_siguiente = None
    elif vista == 'diaria':
        fecha_anterior = fecha_base - timedelta(days=1)
        fecha_siguiente = fecha_base + timedelta(days=1)
    elif vista == 'mensual':
        fecha_anterior = (fecha_base.replace(day=1) - timedelta(days=1)).replace(day=1)
        if fecha_base.month == 12:
            fecha_siguiente = fecha_base.replace(year=fecha_base.year + 1, month=1, day=1)
        else:
            fecha_siguiente = fecha_base.replace(month=fecha_base.month + 1, day=1)
    elif vista == 'semanal':
        fecha_anterior = fecha_inicio - timedelta(days=7)
        fecha_siguiente = fecha_inicio + timedelta(days=7)
    else:
        # Fallback para cualquier otra vista
        fecha_anterior = None
        fecha_siguiente = None

    context = {
        'vista': vista,
        'fecha_base': fecha_base,
        'fecha_inicio': fecha_inicio,
        'fecha_fin': fecha_fin,
        'calendario_data': calendario_data,
        'sesiones': sesiones_lista,
        'pacientes': pacientes,
        'profesionales': profesionales,
        'servicios': servicios,
        'sucursales': sucursales,
        'estados': Sesion.ESTADO_CHOICES,
        'fecha_anterior': fecha_anterior,
        'fecha_siguiente': fecha_siguiente,
        'estado_filtro': estado_filtro or '',
        'paciente_id': paciente_id or '',
        'profesional_id': profesional_id or '',
        'servicio_id': servicio_id or '',
        'sucursal_id': sucursal_id or '',
        'tipo_sesion': tipo_sesion or '',
        'sucursales_usuario': sucursales_usuario,
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
        'page_obj': page_obj,
        'por_pagina': request.GET.get('por_pagina', '50'),
        'es_profesional': es_profesional,
    }
    
    return render(request, 'agenda/calendario.html', context)

@login_required
@solo_sus_sucursales
def agendar_recurrente(request):
    """Vista para agendar sesiones recurrentes CON FILTRO DE SUCURSAL Y DURACIÓN PERSONALIZABLE"""
    
    if request.method == 'POST':
        try:
            paciente_id = request.POST.get('paciente_id')  # Cambiado de 'paciente' a 'paciente_id'
            servicio_id = request.POST.get('servicio_id')  # Cambiado de 'servicio' a 'servicio_id'
            profesional_id = request.POST.get('profesional_id')  # Cambiado de 'profesional' a 'profesional_id'
            sucursal_id = request.POST.get('sucursal')  # Este está correcto
            
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
            
            # 💳 NUEVO: Obtener mensualidad si fue seleccionada
            asignar_mensualidad = request.POST.get('asignar_mensualidad') == 'on'
            mensualidad_id = request.POST.get('mensualidad_id')
            mensualidad = None
            
            if asignar_mensualidad and mensualidad_id:
                try:
                    mensualidad = Mensualidad.objects.get(id=mensualidad_id)
                    print(f"✅ Mensualidad seleccionada: {mensualidad.codigo} - {mensualidad.periodo_display}")
                except Mensualidad.DoesNotExist:
                    messages.error(request, '❌ La mensualidad seleccionada no existe')
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
            
            # 🆕 DETERMINAR MONTO: Si es proyecto o mensualidad, monto = 0
            if proyecto:
                monto = Decimal('0.00')
                print(f"💰 Sesiones de proyecto: monto = Bs. 0.00")
            elif mensualidad:
                monto = Decimal('0.00')
                print(f"💳 Sesiones de mensualidad: monto = Bs. 0.00")
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
                            # 🆕 CREAR SESIÓN CON PROYECTO Y/O MENSUALIDAD
                            Sesion.objects.create(
                                paciente=paciente,
                                servicio=servicio,
                                profesional=profesional,
                                sucursal=sucursal,
                                proyecto=proyecto,  # 🆕 NUEVO
                                mensualidad=mensualidad,  # 💳 NUEVO
                                fecha=fecha_actual,
                                hora_inicio=hora,
                                hora_fin=hora_fin,
                                duracion_minutos=duracion_minutos,
                                monto_cobrado=monto,  # 0 si es proyecto o mensualidad
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
                # 🆕 Preparar datos para confirmación
                dias_nombres = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
                dias_seleccionados_nombres = [dias_nombres[int(d)] for d in dias_semana]
                
                duracion_msg = f" de {duracion_minutos} minutos" if duracion_personalizada else ""
                proyecto_msg = f" - Proyecto {proyecto.codigo}" if proyecto else ""
                mensualidad_msg = f" - Mensualidad {mensualidad.codigo} ({mensualidad.periodo_display})" if mensualidad else ""
                
                # Construir período
                periodo = f"{fecha_inicio.strftime('%d/%m/%Y')} al {fecha_fin.strftime('%d/%m/%Y')}"
                
                # Construir horario
                horario = f"{hora.strftime('%H:%M')} - {hora_fin.strftime('%H:%M')}{duracion_msg}"
                
                # 🆕 Almacenar en session
                request.session['sesiones_creadas'] = {
                    'mensaje': f'Se crearon exitosamente {sesiones_creadas} sesión(es)',
                    'total_creadas': sesiones_creadas,
                    'paciente': paciente.nombre_completo,
                    'profesional': f"{profesional.nombre} {profesional.apellido}",
                    'servicio': servicio.nombre,
                    'periodo': periodo,
                    'horario': horario,
                    'dias': ', '.join(dias_seleccionados_nombres),
                    'proyecto': f"{proyecto.codigo} - {proyecto.nombre}" if proyecto else None,
                    'mensualidad': f"{mensualidad.codigo} - {mensualidad.periodo_display}" if mensualidad else None,
                    'errores': len(sesiones_error),
                }
                
                return redirect('agenda:confirmacion_sesiones')
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

@login_required
def confirmacion_sesiones(request):
    """
    🆕 Vista de confirmación después de crear sesiones recurrentes
    """
    
    # Obtener datos de la sesión
    datos_sesiones = request.session.get('sesiones_creadas')
    
    if not datos_sesiones:
        messages.error(request, '❌ No hay datos de sesiones para mostrar')
        return redirect('agenda:calendario')
    
    # Limpiar sesión después de obtener datos
    del request.session['sesiones_creadas']
    
    context = {
        'datos_sesiones': datos_sesiones,
    }
    
    return render(request, 'agenda/confirmacion_sesiones.html', context)

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
    
    # 🆕 DETECTAR TIPO DE PRECIO según el contexto
    tipo_precio = request.GET.get('tipo_precio', '')  # Primero intentar desde parámetro GET
    
    if not tipo_precio:
        # Si no viene el parámetro, detectar desde el referer
        referer = request.META.get('HTTP_REFERER', '').lower()
        
        if 'mensualidad' in referer or 'crear-mensualidad' in referer:
            tipo_precio = 'mensualidad'
        elif 'proyecto' in referer or 'crear-proyecto' in referer:
            tipo_precio = 'proyecto'
        elif 'recurrente' in referer or 'agendar-recurrente' in referer:
            tipo_precio = 'recurrente'
        else:
            tipo_precio = 'default'  # Mostrar costo_base por defecto
    
    # ✅ Si no hay paciente, devolver lista vacía
    if not paciente_id:
        return render(request, 'agenda/partials/servicios_select.html', {
            'servicios': [],
            'tipo_precio': tipo_precio,  # 🆕 AGREGAR tipo_precio
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
                'error': 'Este paciente no tiene servicios contratados activos',
                'tipo_precio': tipo_precio,  # 🆕 AGREGAR tipo_precio
            })
        
        return render(request, 'agenda/partials/servicios_select.html', {
            'servicios': servicios,
            'tipo_precio': tipo_precio,  # 🆕 AGREGAR tipo_precio
        })
    except Exception as e:
        return render(request, 'agenda/partials/servicios_select.html', {
            'servicios': [],
            'error': str(e),
            'tipo_precio': tipo_precio,  # 🆕 AGREGAR tipo_precio
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
    """Vista previa de sesiones recurrentes ULTRA COMPACTA"""
    
    # Obtener parámetros
    fecha_inicio_str = request.GET.get('fecha_inicio')
    fecha_fin_str = request.GET.get('fecha_fin')
    hora_str = request.GET.get('hora')
    dias_semana = request.GET.getlist('dias_semana')
    paciente_id = request.GET.get('paciente')
    profesional_id = request.GET.get('profesional')
    servicio_id = request.GET.get('servicio')
    duracion_str = request.GET.get('duracion', '60')
    
    # ✨ NUEVO: Parámetro para incluir sesiones pasadas
    incluir_pasadas = request.GET.get('incluir_pasadas', 'false').lower() == 'true'
    
    # Validar parámetros básicos
    if not all([fecha_inicio_str, fecha_fin_str, hora_str, dias_semana]):
        return HttpResponse('''
            <div class="bg-gray-50 border border-gray-200 rounded p-4 text-center">
                <div class="text-2xl mb-2">📅</div>
                <p class="text-xs text-gray-600">Selecciona fechas, hora y días</p>
            </div>
        ''')
    
    try:
        # Convertir strings a objetos
        fecha_inicio = datetime.strptime(fecha_inicio_str, '%Y-%m-%d').date()
        fecha_fin = datetime.strptime(fecha_fin_str, '%Y-%m-%d').date()
        hora = datetime.strptime(hora_str, '%H:%M').time()
        dias_semana = [int(d) for d in dias_semana if d]
        duracion_minutos = int(duracion_str)
        
        # ✨ NUEVO: Si no se incluyen sesiones pasadas, ajustar fecha_inicio
        hoy = date.today()
        fecha_inicio_efectiva = fecha_inicio
        
        if not incluir_pasadas and fecha_inicio < hoy:
            # Calcular fecha mínima (mañana)
            fecha_minima = hoy + timedelta(days=1)
            
            # Si toda la mensualidad es pasada, no mostrar sesiones
            if fecha_fin < fecha_minima:
                return HttpResponse('''
                    <div class="bg-yellow-50 border border-yellow-200 rounded p-3 text-center">
                        <div class="text-2xl mb-2">⚠️</div>
                        <p class="text-xs text-yellow-700 font-semibold mb-1">Todas las fechas son pasadas</p>
                        <p class="text-xs text-yellow-600">Marca "Programar sesiones pasadas" para incluirlas</p>
                    </div>
                ''')
            
            # Ajustar fecha_inicio para mostrar solo desde mañana
            fecha_inicio_efectiva = max(fecha_inicio, fecha_minima)
        
        # Validaciones básicas
        if not dias_semana:
            return HttpResponse('''
                <div class="bg-yellow-50 border border-yellow-200 rounded p-3 text-center">
                    <p class="text-xs text-yellow-700">⚠️ Selecciona al menos un día</p>
                </div>
            ''')
        
        if fecha_inicio_efectiva > fecha_fin:
            return HttpResponse('''
                <div class="bg-red-50 border border-red-200 rounded p-3 text-center">
                    <p class="text-xs text-red-700">❌ Fecha inicio debe ser antes de fecha fin</p>
                </div>
            ''')
        
        # Obtener objetos
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
        
        # Calcular hora_fin
        inicio_dt = datetime.combine(fecha_inicio, hora)
        fin_dt = inicio_dt + timedelta(minutes=duracion_minutos)
        hora_fin = fin_dt.time()
        
        # ✨ MODIFICADO: Generar lista de fechas desde fecha_inicio_efectiva
        sesiones_data = []
        fecha_actual = fecha_inicio_efectiva
        
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
                <div class="bg-yellow-50 border border-yellow-200 rounded p-3 text-center">
                    <p class="text-xs text-yellow-700">⚠️ No se generarán sesiones</p>
                </div>
            ''')
        
        # Estadísticas
        total = len(sesiones_data)
        disponibles = sum(1 for s in sesiones_data if s['disponible'])
        conflictos = total - disponibles
        
        # Nombres de días
        dias_nombres = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']
        
        # Info del header
        hora_formato = hora.strftime('%H:%M')
        servicio_nombre = servicio.nombre if servicio else "Servicio"
        
        # Color del header
        if disponibles == total:
            header_icon = "✅"
        elif disponibles > 0:
            header_icon = "⚠️"
        else:
            header_icon = "❌"
        
        # ✨ NUEVO: Mostrar aviso si se están filtrando sesiones pasadas
        aviso_filtrado = ''
        if not incluir_pasadas and fecha_inicio < hoy:
            sesiones_omitidas = 0
            fecha_temp = fecha_inicio
            while fecha_temp < fecha_inicio_efectiva:
                if fecha_temp.weekday() in dias_semana:
                    sesiones_omitidas += 1
                fecha_temp += timedelta(days=1)
            
            if sesiones_omitidas > 0:
                aviso_filtrado = f'''
                    <div class="bg-blue-50 border border-blue-300 rounded-lg p-2 mb-2">
                        <div class="flex items-center gap-2 text-xs">
                            <span class="text-blue-600">ℹ️</span>
                            <span class="text-blue-800"><strong>{sesiones_omitidas}</strong> sesión(es) pasada(s) omitida(s). Marca "Programar sesiones pasadas" para incluirlas.</span>
                        </div>
                    </div>
                '''
        
        # 🆕 HTML ULTRA COMPACTO EN GRID
        html = f'''
            <div class="bg-green-50 border border-green-200 rounded-lg p-2 mb-2">
                <div class="flex items-center justify-between text-xs">
                    <div class="flex items-center gap-2">
                        <span class="font-bold text-green-800 uppercase">{header_icon} Vista Previa</span>
                        <span class="text-green-600">{servicio_nombre} · {hora_formato} ({duracion_minutos}min)</span>
                    </div>
                    <div class="flex gap-2">
                        <div class="bg-white rounded px-2 py-0.5 border border-green-300">
                            <span class="text-green-700 font-bold">{disponibles}</span>
                            <span class="text-gray-500 text-[10px]"> OK</span>
                        </div>
                        {f'<div class="bg-white rounded px-2 py-0.5 border border-red-300"><span class="text-red-700 font-bold">{conflictos}</span><span class="text-gray-500 text-[10px]"> ⚠️</span></div>' if conflictos > 0 else ''}
                    </div>
                </div>
            </div>
            
            {aviso_filtrado}
            
            <div class="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 gap-1.5 mb-2">
        '''
        
        for i, sesion in enumerate(sesiones_data):
            fecha = sesion['fecha']
            fecha_formato = fecha.strftime('%d/%m')
            dia_nombre = dias_nombres[fecha.weekday()]
            disponible = sesion['disponible']
            conflictos_p = sesion['conflictos_paciente']
            conflictos_prof = sesion['conflictos_profesional']
            
            fecha_iso = fecha.strftime('%Y-%m-%d')
            
            if disponible:
                card_bg = "border-green-400 bg-green-50"
                icon_color = "text-green-600"
                icon = "✅"
                checked = "checked"
                disabled = ""
            else:
                card_bg = "border-red-400 bg-red-50 opacity-70"
                icon_color = "text-red-600"
                icon = "🚫"
                checked = ""
                disabled = "disabled"
            
            html += f'''
                <label class="relative cursor-pointer group">
                    <input type="checkbox" 
                           name="sesiones_seleccionadas" 
                           value="{fecha_iso}"
                           class="sesion-checkbox peer absolute top-1 right-1 w-4 h-4 rounded border-2 border-green-400 checked:bg-blue-500"
                           {checked}
                           {disabled}
                           onchange="actualizarContador()">
                    
                    <div class="border-2 {card_bg} rounded-lg p-1.5 transition-all peer-checked:border-blue-500 peer-checked:bg-blue-50 hover:shadow-sm">
                        <div class="{icon_color} text-xs text-center mb-0.5">{icon}</div>
                        <div class="text-[10px] font-bold text-gray-700 text-center mb-0.5">{dia_nombre}</div>
                        <div class="text-center">
                            <div class="text-sm font-black text-gray-800">{fecha_formato}</div>
                        </div>
            '''
            
            # Mostrar conflictos de forma desplegable COMPACTA
            if not disponible and (conflictos_p or conflictos_prof):
                html += f'''
                        <button type="button" 
                                onclick="toggleConflicto('panel-{i}', this)"
                                class="mt-1 w-full text-[9px] bg-red-500 hover:bg-red-600 text-white px-1 py-0.5 rounded">
                            ▼ Ver detalle
                        </button>
                    </div>
                    
                    <div id="panel-{i}" style="display: none;" class="absolute z-10 mt-1 w-48 bg-white border-2 border-red-400 rounded-lg p-2 shadow-lg text-left">
                '''
                
                if conflictos_p:
                    html += '<div class="mb-1"><p class="text-[9px] font-bold text-red-700 mb-0.5">👤 Paciente ocupado:</p>'
                    for c in conflictos_p[:2]:  # Solo mostrar 2
                        html += f'''
                            <div class="text-[9px] bg-red-50 rounded p-1 mb-0.5 border border-red-200">
                                <p class="font-semibold">{c["servicio"][:15]}</p>
                                <p class="text-gray-600">{c["hora_inicio"]}-{c["hora_fin"]}</p>
                            </div>
                        '''
                    if len(conflictos_p) > 2:
                        html += f'<p class="text-[8px] text-gray-500">+{len(conflictos_p)-2} más</p>'
                    html += '</div>'
                
                if conflictos_prof:
                    html += '<div><p class="text-[9px] font-bold text-orange-700 mb-0.5">👨‍⚕️ Prof. ocupado:</p>'
                    for c in conflictos_prof[:2]:
                        html += f'''
                            <div class="text-[9px] bg-orange-50 rounded p-1 mb-0.5 border border-orange-200">
                                <p class="font-semibold">{c["paciente"][:15]}</p>
                                <p class="text-gray-600">{c["hora_inicio"]}-{c["hora_fin"]}</p>
                            </div>
                        '''
                    if len(conflictos_prof) > 2:
                        html += f'<p class="text-[8px] text-gray-500">+{len(conflictos_prof)-2} más</p>'
                    html += '</div>'
                
                html += '</div>'
            else:
                html += '</div>'
            
            html += '</label>'
        
        html += f'''
            </div>
            
            {f'<div class="bg-orange-50 border border-orange-200 rounded p-2 mb-2"><div class="flex items-start gap-1.5 text-xs"><span class="text-orange-600 flex-shrink-0">⚠️</span><p class="text-orange-800"><strong>{conflictos}</strong> sesión(es) con conflicto no se crearán. Solo se crearán las <strong>{disponibles}</strong> disponibles.</p></div></div>' if conflictos > 0 else ''}
            
            <div class="bg-blue-50 border border-blue-200 rounded p-2 text-[10px] text-blue-700 flex items-center gap-1">
                <span>ℹ️</span>
                <span>Solo se crearán las sesiones que selecciones</span>
            </div>
        '''
        
        return HttpResponse(html)
        
    except ValueError as e:
        return HttpResponse(f'''
            <div class="bg-red-50 border border-red-200 rounded p-3 text-center">
                <p class="text-xs text-red-700">❌ Error en formato: {str(e)}</p>
            </div>
        ''')
    except Exception as e:
        return HttpResponse(f'''
            <div class="bg-red-50 border border-red-200 rounded p-3 text-center">
                <p class="text-xs text-red-700">❌ Error: {str(e)}</p>
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
    """
    Editar sesión con validación de pagos y permisos por rol
    ✅ CORREGIDO: Manejo robusto de errores y validaciones
    """
    sesion = get_object_or_404(Sesion, id=sesion_id)
    
    # 🆕 Verificar permisos según rol
    es_profesional = hasattr(request.user, 'perfil') and request.user.perfil.es_profesional
    es_admin = request.user.is_superuser or (hasattr(request.user, 'perfil') and request.user.perfil.rol in ['gerente', 'administrador'])
    
    # Obtener el objeto Profesional si es profesional
    profesional_actual = None
    if es_profesional:
        try:
            from core.utils import get_profesional_usuario
            profesional_actual = get_profesional_usuario(request.user)
        except:
            pass
    
    # Validaciones de permisos
    hoy = date.today()
    puede_editar = True
    puede_editar_pago = True
    mensaje_bloqueo = None
    
    # 🆕 Identificar si es recepcionista
    es_recepcionista = hasattr(request.user, 'perfil') and request.user.perfil.es_recepcionista()
    
    if not es_admin:
        if es_profesional:
            # 🔒 RESTRICCIÓN 1: Profesionales solo editan sesiones de HOY
            if sesion.fecha != hoy:
                puede_editar = False
                puede_editar_pago = False
                if sesion.fecha < hoy:
                    mensaje_bloqueo = "Solo lectura - Sesión pasada (Profesionales solo editan hoy)"
                else:
                    mensaje_bloqueo = "Solo lectura - Sesión futura (Profesionales solo editan hoy)"
            
            # 🔒 RESTRICCIÓN 2: Profesionales solo editan una vez
            elif sesion.editada_por_profesional:
                puede_editar = False
                puede_editar_pago = False
                mensaje_bloqueo = "Solo lectura - Ya fue editada por ti"
        
        elif es_recepcionista:
            # 🔒 RESTRICCIÓN: No editar si profesional ya editó
            if sesion.editada_por_profesional:
                puede_editar = False
                mensaje_bloqueo = "Solo lectura - Ya editada por profesional"
            
            # ✅ CLAVE: Recepcionistas SIEMPRE pueden editar pago hasta que esté pagado
            puede_editar_pago = not sesion.pagado
    
    if request.method == 'POST':
        # ✅ CRÍTICO: Verificar permisos antes de procesar
        if not puede_editar and not puede_editar_pago:
            return JsonResponse({
                'error': True,
                'mensaje': f'❌ {mensaje_bloqueo}. No tienes permisos para editar esta sesión.'
            }, status=403)
        
        try:
            # ✅ NUEVO: Importar aquí para evitar errores de importación circular
            from django.db import transaction
            from django.core.exceptions import ValidationError
            
            estado_nuevo = request.POST.get('estado', '').strip()
            
            # ✅ VALIDACIÓN: Estado debe ser válido
            if not estado_nuevo:
                return JsonResponse({
                    'error': True,
                    'mensaje': '❌ Debes seleccionar un estado'
                }, status=400)
            
            estados_validos = dict(Sesion.ESTADO_CHOICES).keys()
            if estado_nuevo not in estados_validos:
                return JsonResponse({
                    'error': True,
                    'mensaje': f'❌ Estado inválido: {estado_nuevo}'
                }, status=400)
            
            # 🆕 VALIDACIÓN: Si cambia a estado sin cobro y tiene pagos (SOLO para NO profesionales)
            if not es_profesional and estado_nuevo in ['permiso', 'cancelada', 'reprogramada']:
                pagos_activos = sesion.pagos.filter(anulado=False)
                
                if pagos_activos.exists():
                    # ✅ AJAX: Devolver JSON indicando que necesita confirmación
                    total_pagado = pagos_activos.aggregate(Sum('monto'))['monto__sum'] or Decimal('0.00')
                    
                    return JsonResponse({
                        'requiere_confirmacion': True,
                        'sesion_id': sesion.id,
                        'estado_nuevo': estado_nuevo,
                        'total_pagado': float(total_pagado),
                        'cantidad_pagos': pagos_activos.count(),
                        'mensaje': f'Esta sesión tiene {pagos_activos.count()} pago(s) registrado(s) por Bs. {total_pagado}'
                    })
            
            # ✅ USAR TRANSACCIÓN para garantizar atomicidad
            with transaction.atomic():
                # ✅ MODIFICADO: Solo actualizar si tiene permiso de edición
                if puede_editar:
                    # Guardar estado anterior para logging
                    estado_anterior = sesion.estado
                    
                    # Actualizar estado
                    sesion.estado = estado_nuevo
                    
                    # Aplicar políticas de cobro según estado (SOLO para NO profesionales)
                    if not es_profesional and estado_nuevo in ['permiso', 'cancelada', 'reprogramada']:
                        sesion.monto_cobrado = Decimal('0.00')
                    
                    # Observaciones y notas
                    if not es_profesional:
                        observaciones_nuevas = request.POST.get('observaciones', '').strip()
                        sesion.observaciones = observaciones_nuevas
                    
                    # Notas de sesión (profesionales y admins)
                    if es_profesional or es_admin:
                        notas_nuevas = request.POST.get('notas_sesion', '').strip()
                        sesion.notas_sesion = notas_nuevas
                    
                    # ✅ CAMPOS ESPECÍFICOS SEGÚN ESTADO
                    if estado_nuevo == 'realizada_retraso':
                        hora_real = request.POST.get('hora_real_inicio', '').strip()
                        if hora_real:
                            try:
                                sesion.hora_real_inicio = datetime.strptime(hora_real, '%H:%M').time()
                                inicio = datetime.combine(sesion.fecha, sesion.hora_inicio)
                                real = datetime.combine(sesion.fecha, sesion.hora_real_inicio)
                                sesion.minutos_retraso = int((real - inicio).total_seconds() / 60)
                            except ValueError:
                                return JsonResponse({
                                    'error': True,
                                    'mensaje': '❌ Formato de hora inválido'
                                }, status=400)
                    
                    if estado_nuevo == 'reprogramada':
                        fecha_nueva = request.POST.get('fecha_reprogramada', '').strip()
                        hora_nueva = request.POST.get('hora_reprogramada', '').strip()
                        
                        if fecha_nueva:
                            try:
                                sesion.fecha_reprogramada = datetime.strptime(fecha_nueva, '%Y-%m-%d').date()
                            except ValueError:
                                return JsonResponse({
                                    'error': True,
                                    'mensaje': '❌ Formato de fecha inválido'
                                }, status=400)
                        
                        if hora_nueva:
                            try:
                                sesion.hora_reprogramada = datetime.strptime(hora_nueva, '%H:%M').time()
                            except ValueError:
                                return JsonResponse({
                                    'error': True,
                                    'mensaje': '❌ Formato de hora inválido'
                                }, status=400)
                        
                        sesion.motivo_reprogramacion = request.POST.get('motivo_reprogramacion', '').strip()
                        sesion.reprogramacion_realizada = request.POST.get('reprogramacion_realizada') == 'on'
                    
                    # 🆕 Marcar como editada por profesional si aplica
                    if es_profesional:
                        sesion.editada_por_profesional = True
                        sesion.fecha_edicion_profesional = datetime.now()
                        if profesional_actual:
                            sesion.profesional_editor = profesional_actual
                    
                    sesion.modificada_por = request.user
                    
                    # ✅ CRÍTICO: Guardar SIN validación de choques (solo cambio de estado)
                    # Usamos update_fields para evitar full_clean()
                    campos_actualizar = [
                        'estado', 'monto_cobrado', 'observaciones', 'notas_sesion',
                        'modificada_por', 'fecha_modificacion'
                    ]
                    
                    if estado_nuevo == 'realizada_retraso' and sesion.hora_real_inicio:
                        campos_actualizar.extend(['hora_real_inicio', 'minutos_retraso'])
                    
                    if estado_nuevo == 'reprogramada':
                        campos_actualizar.extend([
                            'fecha_reprogramada', 'hora_reprogramada',
                            'motivo_reprogramacion', 'reprogramacion_realizada'
                        ])
                    
                    if es_profesional:
                        campos_actualizar.extend([
                            'editada_por_profesional', 'fecha_edicion_profesional',
                            'profesional_editor'
                        ])
                    
                    # ✅ GUARDAR con update_fields (evita full_clean)
                    sesion.save(update_fields=campos_actualizar)
                
                # ✅ NUEVO: Si solo tiene permiso de pago (recepcionista con sesión bloqueada)
                elif puede_editar_pago and es_recepcionista:
                    # Solo actualizar observaciones
                    observaciones_nuevas = request.POST.get('observaciones', '').strip()
                    sesion.observaciones = observaciones_nuevas
                    sesion.modificada_por = request.user
                    
                    sesion.save(update_fields=['observaciones', 'modificada_por', 'fecha_modificacion'])
            
            # ✅ ÉXITO
            return JsonResponse({
                'success': True,
                'mensaje': 'Sesión actualizada correctamente'
            })
            
        except ValidationError as ve:
            # ✅ Capturar errores de validación del modelo
            errores = []
            if hasattr(ve, 'message_dict'):
                for campo, mensajes in ve.message_dict.items():
                    errores.extend(mensajes)
            else:
                errores = [str(ve)]
            
            return JsonResponse({
                'error': True,
                'mensaje': '❌ Error de validación: ' + ', '.join(errores)
            }, status=400)
        
        except Exception as e:
            # ✅ Log del error para debugging
            import traceback
            print("ERROR en editar_sesion:")
            print(traceback.format_exc())
            
            return JsonResponse({
                'error': True,
                'mensaje': f'❌ Error inesperado: {str(e)}'
            }, status=500)
    
    # GET - Mostrar formulario
    estadisticas = _calcular_estadisticas_mes(sesion)
    
    return render(request, 'agenda/partials/editar_form.html', {
        'sesion': sesion,
        'estadisticas': json.dumps(estadisticas),
        'puede_editar': puede_editar,
        'puede_editar_pago': puede_editar_pago,
        'mensaje_bloqueo': mensaje_bloqueo,
        'es_profesional': es_profesional,
        'es_recepcionista': es_recepcionista,
        'es_admin': es_admin,
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
    from calendar import monthrange
    
    primer_dia = sesion.fecha.replace(day=1)
    ultimo_dia_del_mes = monthrange(sesion.fecha.year, sesion.fecha.month)[1]
    ultimo_dia = sesion.fecha.replace(day=ultimo_dia_del_mes)
    
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
        'canceladas': sesiones_mes.filter(estado='cancelada').count(),
        'reprogramadas': sesiones_mes.filter(estado='reprogramada').count(),
        'programadas': sesiones_mes.filter(estado='programada').count(),
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


@login_required
def obtener_mensualidades_paciente(request):
    """
    🆕 API JSON: Obtener mensualidades del paciente según sucursal, servicio y profesional
    Usado en agendar_recurrente.html para cargar mensualidades dinámicamente
    """
    try:
        # Obtener parámetros
        paciente_id = request.GET.get('paciente')
        servicio_id = request.GET.get('servicio')
        profesional_id = request.GET.get('profesional')
        sucursal_id = request.GET.get('sucursal')
        
        # Validar parámetros requeridos
        if not all([paciente_id, servicio_id, profesional_id, sucursal_id]):
            return JsonResponse({
                'success': False,
                'error': 'Faltan parámetros requeridos'
            }, status=400)
        
        # Validar que existan los objetos
        paciente = get_object_or_404(Paciente, id=paciente_id)
        servicio = get_object_or_404(TipoServicio, id=servicio_id)
        profesional = get_object_or_404(Profesional, id=profesional_id)
        sucursal = get_object_or_404(Sucursal, id=sucursal_id)
        
        # Buscar mensualidades con los 4 parámetros
        mensualidades = Mensualidad.objects.filter(
            paciente=paciente,
            servicio=servicio,
            profesional=profesional,
            sucursal=sucursal,
            estado__in=['activa', 'pausada']  # Solo activas y pausadas
        ).order_by('-anio', '-mes')
        
        # Construir respuesta JSON
        mensualidades_data = []
        for mensualidad in mensualidades:
            mensualidades_data.append({
                'id': mensualidad.id,
                'codigo': mensualidad.codigo,
                'periodo': mensualidad.periodo_display,  # "Enero 2024"
                'mes': mensualidad.mes,
                'anio': mensualidad.anio,
                'costo_mensual': float(mensualidad.costo_mensual),
                'total_pagado': float(mensualidad.total_pagado),
                'saldo_pendiente': float(mensualidad.saldo_pendiente),
                'num_sesiones': mensualidad.num_sesiones,
                'num_sesiones_realizadas': mensualidad.num_sesiones_realizadas,
                'estado': mensualidad.get_estado_display(),
            })
        
        return JsonResponse({
            'success': True,
            'mensualidades': mensualidades_data
        })
        
    except Paciente.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Paciente no encontrado'
        }, status=404)
    except TipoServicio.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Servicio no encontrado'
        }, status=404)
    except Profesional.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Profesional no encontrado'
        }, status=404)
    except Sucursal.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Sucursal no encontrada'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required
def eliminar_sesion(request, sesion_id):
    """
    Eliminar una sesión SOLO si está programada y no tiene pagos
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)
    
    try:
        sesion = get_object_or_404(Sesion, id=sesion_id)
        
        # ✅ VALIDACIÓN 1: Solo sesiones programadas
        if sesion.estado != 'programada':
            return JsonResponse({
                'error': True,
                'mensaje': f'❌ No se puede eliminar. La sesión está en estado: {sesion.get_estado_display()}'
            }, status=400)
        
        # ✅ VALIDACIÓN 2: No debe tener pagos
        pagos_activos = sesion.pagos.filter(anulado=False)
        if pagos_activos.exists():
            total_pagado = pagos_activos.aggregate(Sum('monto'))['monto__sum']
            return JsonResponse({
                'error': True,
                'mensaje': f'❌ No se puede eliminar. La sesión tiene {pagos_activos.count()} pago(s) por Bs. {total_pagado}'
            }, status=400)
        
        # ✅ GUARDAR INFO PARA MENSAJE
        info_sesion = {
            'fecha': sesion.fecha.strftime('%d/%m/%Y'),
            'hora': sesion.hora_inicio.strftime('%H:%M'),
            'paciente': f"{sesion.paciente.nombre} {sesion.paciente.apellido}",
            'servicio': sesion.servicio.nombre
        }
        
        # ✅ ELIMINAR
        sesion.delete()
        
        messages.success(
            request, 
            f'✅ Sesión eliminada: {info_sesion["paciente"]} - {info_sesion["servicio"]} - {info_sesion["fecha"]} {info_sesion["hora"]}'
        )
        
        return JsonResponse({
            'success': True,
            'mensaje': 'Sesión eliminada correctamente',
            'redirect': request.META.get('HTTP_REFERER', '/agenda/')
        })
        
    except Sesion.DoesNotExist:
        return JsonResponse({'error': 'Sesión no encontrada'}, status=404)
    except Exception as e:
        return JsonResponse({
            'error': True,
            'mensaje': f'Error: {str(e)}'
        }, status=500)