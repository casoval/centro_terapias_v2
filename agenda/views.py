from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.core.exceptions import ValidationError
from django.db.models import Q, Count, Sum, F, OuterRef, Subquery, Case, When, Value, DecimalField
from django.db.models.functions import Coalesce
from django.core.paginator import Paginator
from datetime import datetime, timedelta, date
from calendar import monthrange, Calendar
from decimal import Decimal

from agenda.models import Sesion, Proyecto, Mensualidad, ServicioProfesionalMensualidad
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
    """
    Crear nueva mensualidad
    ✅ MODIFICADO: Cada servicio tiene su propio profesional asignado
    """
    
    if request.method == 'POST':
        try:
            from django.db import transaction
            
            # Obtener datos del formulario
            paciente_id = request.POST.get('paciente_id')
            servicio_ids = request.POST.getlist('servicio_ids[]')  # ✅ Array de servicios
            profesional_ids = request.POST.getlist('profesional_ids[]')  # ✅ Array de profesionales
            sucursal_id = request.POST.get('sucursal_id')
            mes = int(request.POST.get('mes'))
            anio = int(request.POST.get('anio'))
            costo_mensual = Decimal(request.POST.get('costo_mensual'))
            observaciones = request.POST.get('observaciones', '')
            
            # Validaciones básicas
            if not all([paciente_id, servicio_ids, profesional_ids, sucursal_id, mes, anio, costo_mensual]):
                messages.error(request, '❌ Faltan datos obligatorios')
                return redirect('agenda:crear_mensualidad')
            
            # ✅ VALIDAR que hay la misma cantidad de servicios y profesionales
            if len(servicio_ids) != len(profesional_ids):
                messages.error(request, '❌ Error: No coinciden servicios con profesionales')
                return redirect('agenda:crear_mensualidad')
            
            # ✅ VALIDAR que se seleccionó al menos un servicio
            if not servicio_ids:
                messages.error(request, '❌ Debes agregar al menos un servicio')
                return redirect('agenda:crear_mensualidad')
            
            paciente = Paciente.objects.get(id=paciente_id)
            sucursal = Sucursal.objects.get(id=sucursal_id)
            
            # Verificar permisos
            sucursales_usuario = request.sucursales_usuario
            if sucursales_usuario is not None:
                if not sucursales_usuario.filter(id=sucursal.id).exists():
                    messages.error(request, '❌ No tienes permiso para crear mensualidades en esta sucursal')
                    return redirect('agenda:crear_mensualidad')
            
            # ✅ Verificar si ya existe mensualidad para ese paciente/período
            mensualidad_existente = Mensualidad.objects.filter(
                paciente=paciente,
                mes=mes,
                anio=anio
            ).first()
            
            if mensualidad_existente:
                messages.error(
                    request, 
                    f'❌ Ya existe una mensualidad para {paciente} en {mensualidad_existente.periodo_display}'
                )
                return redirect('agenda:crear_mensualidad')
            
            # ✅ Crear mensualidad con transacción
            with transaction.atomic():
                # 1. Crear mensualidad
                mensualidad = Mensualidad(
                    paciente=paciente,
                    sucursal=sucursal,
                    mes=mes,
                    anio=anio,
                    costo_mensual=costo_mensual,
                    observaciones=observaciones,
                    creada_por=request.user
                )
                mensualidad.save()
                
                # 2. Crear relaciones servicio-profesional
                from agenda.models import ServicioProfesionalMensualidad
                
                servicios_nombres = []
                for servicio_id, profesional_id in zip(servicio_ids, profesional_ids):
                    servicio = TipoServicio.objects.get(id=servicio_id)
                    profesional = Profesional.objects.get(id=profesional_id)
                    
                    # Crear relación intermedia
                    ServicioProfesionalMensualidad.objects.create(
                        mensualidad=mensualidad,
                        servicio=servicio,
                        profesional=profesional
                    )
                    
                    servicios_nombres.append(f"{servicio.nombre} ({profesional.nombre})")
            
            messages.success(request, f'✅ Mensualidad {mensualidad.codigo} creada correctamente')
            messages.info(request, f'📋 Servicios: {", ".join(servicios_nombres)}')
            messages.info(request, '📌 Ahora puedes agregar las sesiones desde "Agendar Sesión Recurrente"')
            
            return redirect('agenda:detalle_mensualidad', mensualidad_id=mensualidad.id)
            
        except (TipoServicio.DoesNotExist, Profesional.DoesNotExist):
            messages.error(request, '❌ Uno o más servicios/profesionales no existen')
            return redirect('agenda:crear_mensualidad')
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
    """Lista de mensualidades con filtros - ✅ CORREGIDO: ManyToMany"""
    
    # Filtros
    buscar = request.GET.get('q', '').strip()
    estado_filtro = request.GET.get('estado', '')
    sucursal_id = request.GET.get('sucursal', '')
    
    # Query base - ✅ CORREGIDO: prefetch_related para ManyToMany
    mensualidades = Mensualidad.objects.select_related(
        'paciente', 'sucursal'
    ).prefetch_related(
        'servicios_profesionales__servicio',  # ✅ Prefetch servicios a través del modelo intermedio
        'servicios_profesionales__profesional',  # ✅ Prefetch profesionales
        'sesiones'
    )
    
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
    """Detalle completo de una mensualidad - ✅ CORREGIDO"""
    
    mensualidad = get_object_or_404(
        Mensualidad.objects.select_related(
            'paciente', 'sucursal'
        ).prefetch_related(
            'servicios_profesionales__servicio',
            'servicios_profesionales__profesional'
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
    vista = request.GET.get('vista', 'diaria')
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
        
        # ✅ DETECTAR SESIONES EN CURSO (EN VIVO)
        from django.utils import timezone
        
        # CORRECCIÓN: Convertir a hora local (reloj real) antes de comparar
        ahora = timezone.localtime(timezone.now()) 
        
        # Verificar si la sesión está ocurriendo AHORA
        sesion.es_sesion_en_curso = (
            sesion.estado == 'programada' and
            sesion.fecha == ahora.date() and
            # Comparamos hora local con hora de la sesión
            sesion.hora_inicio <= ahora.time() <= sesion.hora_fin
        )
        
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
                # ✅ VALIDAR: Verificar que el servicio+profesional existan en la mensualidad
                sp_existe = mensualidad.servicios_profesionales.filter(
                    servicio=servicio,
                    profesional=profesional
                ).exists()
                
                if not sp_existe:
                    messages.error(
                        request, 
                        f'❌ La combinación de {servicio.nombre} con {profesional.nombre} '
                        f'no existe en la mensualidad {mensualidad.codigo}'
                    )
                    return redirect('agenda:agendar_recurrente')
                
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
    
    # ✅ NUEVO: Obtener parámetros GET para pre-seleccionar campos
    sucursal_preseleccionada_id = request.GET.get('sucursal')
    paciente_preseleccionado_id = request.GET.get('paciente')
    proyecto_preseleccionado_id = request.GET.get('proyecto')
    
    sucursal_preseleccionada = None
    paciente_preseleccionado = None
    proyecto_preseleccionado = None
    
    # Validar y obtener objetos si fueron proporcionados
    if sucursal_preseleccionada_id:
        try:
            sucursal_preseleccionada = Sucursal.objects.get(id=sucursal_preseleccionada_id)
        except Sucursal.DoesNotExist:
            pass
    
    if paciente_preseleccionado_id:
        try:
            paciente_preseleccionado = Paciente.objects.get(id=paciente_preseleccionado_id)
        except Paciente.DoesNotExist:
            pass
    
    if proyecto_preseleccionado_id:
        try:
            proyecto_preseleccionado = Proyecto.objects.select_related(
                'paciente', 'sucursal', 'servicio_base', 'profesional_responsable'
            ).get(id=proyecto_preseleccionado_id)
        except Proyecto.DoesNotExist:
            pass
    
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
        # ✅ NUEVO: Pasar objetos pre-seleccionados al template
        'sucursal_preseleccionada': sucursal_preseleccionada,
        'paciente_preseleccionado': paciente_preseleccionado,
        'proyecto_preseleccionado': proyecto_preseleccionado,
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
    ✅ ACTUALIZADO: Incluye información detallada para tooltips
    """
    resultado = {
        'disponible': True,
        'conflictos_paciente': [],
        'conflictos_profesional': [],
        'tiene_conflicto_paciente': False,
        'tiene_conflicto_profesional': False,
        'num_conflictos': 0
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
            resultado['tiene_conflicto_paciente'] = True
            resultado['conflictos_paciente'].append({
                'servicio': sesion.servicio.nombre,
                'hora_inicio': sesion.hora_inicio.strftime('%H:%M'),
                'hora_fin': sesion.hora_fin.strftime('%H:%M'),
                'profesional': f"{sesion.profesional.nombre} {sesion.profesional.apellido}",
                'sucursal': sesion.sucursal.nombre,
                'duracion': sesion.duracion_minutos
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
            resultado['tiene_conflicto_profesional'] = True
            resultado['conflictos_profesional'].append({
                'paciente': f"{sesion.paciente.nombre} {sesion.paciente.apellido}",
                'servicio': sesion.servicio.nombre,
                'hora_inicio': sesion.hora_inicio.strftime('%H:%M'),
                'hora_fin': sesion.hora_fin.strftime('%H:%M'),
                'sucursal': sesion.sucursal.nombre,
                'duracion': sesion.duracion_minutos
            })
    
    # Contar total de conflictos
    resultado['num_conflictos'] = len(resultado['conflictos_paciente']) + len(resultado['conflictos_profesional'])
    
    return resultado



@login_required
@solo_sus_sucursales
def vista_previa_mensualidad(request):
    """
    Vista previa para modal de agendamiento de mensualidad
    Valida choques de horarios similar a vista_previa_recurrente
    """
    
    # Obtener parámetros
    servicio_profesional_id = request.GET.get('servicio_profesional_id')
    hora_str = request.GET.get('hora')
    duracion_str = request.GET.get('duracion', '45')
    modo_seleccion = request.GET.get('modo_seleccion', 'recurrente')
    
    # Detectar si es una petición para validar UN solo día (casilla)
    solo_dia = request.GET.get('solo_dia') == 'true'

    # Validar parámetros básicos
    if not all([servicio_profesional_id, hora_str]):
        return HttpResponse('''
            <div class="bg-gray-50 border border-gray-200 rounded p-4 text-center">
                <div class="text-2xl mb-2">📅</div>
                <p class="text-xs text-gray-600">Selecciona hora y días</p>
            </div>
        ''')
    
    try:
        # Obtener servicio-profesional
        servicio_profesional = get_object_or_404(
            ServicioProfesionalMensualidad.objects.select_related(
                'mensualidad__paciente',
                'mensualidad__sucursal',
                'servicio',
                'profesional'
            ),
            id=servicio_profesional_id
        )
        
        mensualidad = servicio_profesional.mensualidad
        
        # Verificar permisos
        sucursales_usuario = request.sucursales_usuario
        if sucursales_usuario is not None:
            if not sucursales_usuario.filter(id=mensualidad.sucursal.id).exists():
                return HttpResponse('''
                    <div class="bg-red-50 border border-red-200 rounded p-3 text-center">
                        <p class="text-xs text-red-700">❌ Sin permisos</p>
                    </div>
                ''')
        
        # Convertir hora y duración
        hora = datetime.strptime(hora_str, '%H:%M').time()
        duracion_minutos = int(duracion_str)
        
        # Calcular hora_fin
        inicio_dt = datetime.combine(date.today(), hora)
        fin_dt = inicio_dt + timedelta(minutes=duracion_minutos)
        hora_fin = fin_dt.time()

        # Lógica para devolver JSON cuando se consulta una casilla individual
        if solo_dia:
            fecha_str = request.GET.get('dias_especificos') # En este modo, llega una sola fecha
            if not fecha_str:
                return JsonResponse({'error': 'Falta fecha'}, status=400)
            
            try:
                fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
            except ValueError:
                return JsonResponse({'error': 'Fecha inválida'}, status=400)

            # Usar tu función auxiliar existente para validar
            sesion_info = _validar_disponibilidad_detallada(
                mensualidad.paciente,
                servicio_profesional.profesional,
                fecha,
                hora,
                hora_fin
            )

            # Retornar JSON completo con detalles de conflictos
            return JsonResponse({
                'disponible': sesion_info['disponible'],
                'tiene_conflicto': not sesion_info['disponible'],
                'tiene_conflicto_paciente': sesion_info['tiene_conflicto_paciente'],
                'tiene_conflicto_profesional': sesion_info['tiene_conflicto_profesional'],
                'conflictos_paciente': sesion_info['conflictos_paciente'],
                'conflictos_profesional': sesion_info['conflictos_profesional'],
                'num_conflictos': sesion_info['num_conflictos'],
                'mensaje': 'Libre' if sesion_info['disponible'] else 'Conflicto'
            })
        
        # Obtener fechas según modo de selección
        fechas_generadas = []
        
        if modo_seleccion == 'recurrente':
            # Modo patrón recurrente
            dias_semana = request.GET.getlist('dias_semana')
            
            if not dias_semana:
                return HttpResponse('''
                    <div class="bg-yellow-50 border border-yellow-200 rounded p-3 text-center">
                        <p class="text-xs text-yellow-700">⚠️ Selecciona al menos un día de la semana</p>
                    </div>
                ''')
            
            dias_semana = [int(d) for d in dias_semana]
            
            # ✨ NUEVO: Parámetro para incluir sesiones pasadas
            incluir_pasadas = request.GET.get('incluir_pasadas', 'false').lower() == 'true'
            
            # Generar fechas
            fecha_inicio = date(mensualidad.anio, mensualidad.mes, 1)
            ultimo_dia_num = monthrange(mensualidad.anio, mensualidad.mes)[1]
            fecha_fin = date(mensualidad.anio, mensualidad.mes, ultimo_dia_num)
            
            # ✨ NUEVO: Si no se incluyen sesiones pasadas, ajustar fecha_inicio
            hoy = date.today()
            fecha_inicio_efectiva = fecha_inicio
            
            if not incluir_pasadas and fecha_inicio < hoy:
                # Calcular fecha mínima (mañana)
                fecha_minima = hoy + timedelta(days=1)
                
                # Si toda la mensualidad es pasada, no mostrar sesiones
                if fecha_fin < fecha_minima:
                    return HttpResponse('''
                        <div class="bg-yellow-50 border-2 border-yellow-300 rounded-xl p-4 text-center">
                            <div class="text-3xl mb-2">⚠️</div>
                            <p class="text-sm text-yellow-800 font-bold mb-1">Todas las fechas son pasadas</p>
                            <p class="text-xs text-yellow-700">Marca "📅 Programar sesiones pasadas" para incluirlas</p>
                        </div>
                    ''')
                
                # Ajustar fecha_inicio para mostrar solo desde mañana
                fecha_inicio_efectiva = max(fecha_inicio, fecha_minima)
            
            fecha_actual = fecha_inicio_efectiva
            while fecha_actual <= fecha_fin:
                dia_semana = fecha_actual.weekday()
                dia_js = (dia_semana + 1) % 7  # Convertir Python → JS
                
                if dia_js in dias_semana:
                    fechas_generadas.append(fecha_actual)
                
                fecha_actual += timedelta(days=1)
        
        else:
            # Modo días específicos
            dias_especificos = request.GET.getlist('dias_especificos')
            
            if not dias_especificos:
                return HttpResponse('''
                    <div class="bg-yellow-50 border border-yellow-200 rounded p-3 text-center">
                        <p class="text-xs text-yellow-700">⚠️ Selecciona al menos un día del mes</p>
                    </div>
                ''')
            
            for fecha_str in dias_especificos:
                try:
                    fecha_obj = datetime.strptime(fecha_str, '%Y-%m-%d').date()
                    fechas_generadas.append(fecha_obj)
                except ValueError:
                    continue
            
            fechas_generadas.sort()
        
        if not fechas_generadas:
            return HttpResponse('''
                <div class="bg-yellow-50 border border-yellow-200 rounded p-3 text-center">
                    <p class="text-xs text-yellow-700">⚠️ No se generarán sesiones</p>
                </div>
            ''')
        
        # Validar disponibilidad para cada fecha
        sesiones_data = []
        for fecha in fechas_generadas:
            sesion_info = _validar_disponibilidad_detallada(
                mensualidad.paciente,
                servicio_profesional.profesional,
                fecha,
                hora,
                hora_fin
            )
            
            sesiones_data.append({
                'fecha': fecha,
                'disponible': sesion_info['disponible'],
                'conflictos_paciente': sesion_info['conflictos_paciente'],
                'conflictos_profesional': sesion_info['conflictos_profesional'],
            })
        
        # Estadísticas
        total = len(sesiones_data)
        disponibles = sum(1 for s in sesiones_data if s['disponible'])
        conflictos = total - disponibles
        
        # Nombres de días
        dias_nombres = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']
        
        # Info del header
        hora_formato = hora.strftime('%H:%M')
        servicio_nombre = servicio_profesional.servicio.nombre
        
        # Color del header
        if disponibles == total:
            header_icon = "✅"
        elif disponibles > 0:
            header_icon = "⚠️"
        else:
            header_icon = "❌"
        
        # HTML compacto en grid
        html = f'''
            <div class="bg-gradient-to-r from-purple-50 to-indigo-50 border-2 border-purple-300 rounded-xl p-3 mb-3">
                <div class="flex items-center justify-between text-xs mb-2">
                    <div class="flex items-center gap-2">
                        <span class="text-xl">{header_icon}</span>
                        <span class="font-black text-purple-900 uppercase">Vista Previa</span>
                        <span class="text-purple-600">{servicio_nombre} · {hora_formato} ({duracion_minutos}min)</span>
                    </div>
                    <div class="flex gap-2">
                        <div class="bg-white rounded-lg px-2.5 py-1 border-2 border-green-400 shadow-sm">
                            <span class="text-green-700 font-black text-sm">{disponibles}</span>
                            <span class="text-gray-500 text-[10px]"> OK</span>
                        </div>
                        {f'<div class="bg-white rounded-lg px-2.5 py-1 border-2 border-red-400 shadow-sm"><span class="text-red-700 font-black text-sm">{conflictos}</span><span class="text-gray-500 text-[10px]"> ⚠️</span></div>' if conflictos > 0 else ''}
                    </div>
                </div>
                
                <div class="grid grid-cols-4 sm:grid-cols-5 md:grid-cols-6 lg:grid-cols-7 gap-2">
        '''
        
        for i, sesion in enumerate(sesiones_data):
            fecha = sesion['fecha']
            fecha_formato = fecha.strftime('%d/%m')
            fecha_iso = fecha.strftime('%Y-%m-%d')
            dia_nombre = dias_nombres[fecha.weekday()]
            disponible = sesion['disponible']
            conflictos_p = sesion['conflictos_paciente']
            conflictos_prof = sesion['conflictos_profesional']
            
            if disponible:
                card_bg = "border-green-400 bg-green-50"
                icon_color = "text-green-600"
                icon = "✅"
                checked = "checked"
                disabled = ""
            else:
                card_bg = "border-red-400 bg-red-50 opacity-75"
                icon_color = "text-red-600"
                icon = "🚫"
                checked = ""
                disabled = "disabled"
            
            html += f'''
                <label class="relative cursor-pointer group">
                    <input type="checkbox" 
                           name="sesiones_seleccionadas" 
                           value="{fecha_iso}"
                           class="sesion-checkbox-mensualidad peer absolute top-1 right-1 w-4 h-4 rounded border-2 border-green-400 checked:bg-blue-500"
                           {checked}
                           {disabled}
                           onchange="actualizarContadorMensualidad()">
                    
                    <div class="border-2 {card_bg} rounded-lg p-2 transition-all peer-checked:border-blue-500 peer-checked:bg-blue-50 hover:shadow-md">
                        <div class="{icon_color} text-lg text-center mb-1">{icon}</div>
                        <div class="text-[10px] font-bold text-gray-700 text-center mb-1">{dia_nombre}</div>
                        <div class="text-center">
                            <div class="text-sm font-black text-gray-800">{fecha_formato}</div>
                        </div>
            '''
            
            # Mostrar conflictos de forma desplegable
            if not disponible and (conflictos_p or conflictos_prof):
                html += f'''
                        <button type="button" 
                                onclick="toggleConflictoModal('panel-mensualidad-{i}', this)"
                                class="mt-2 w-full text-[9px] bg-red-500 hover:bg-red-600 text-white px-1 py-1 rounded font-bold">
                            ▼ Detalle
                        </button>
                    </div>
                    
                    <div id="panel-mensualidad-{i}" style="display: none;" class="absolute z-20 mt-1 w-56 bg-white border-2 border-red-400 rounded-lg p-2 shadow-xl text-left">
                '''
                
                if conflictos_p:
                    html += '<div class="mb-2"><p class="text-[10px] font-black text-red-700 mb-1 flex items-center gap-1">👤 Paciente ocupado:</p>'
                    for c in conflictos_p[:2]:
                        html += f'''
                            <div class="text-[9px] bg-red-50 rounded p-1.5 mb-1 border border-red-200">
                                <p class="font-bold text-red-900">{c["servicio"][:20]}</p>
                                <p class="text-gray-600">{c["hora_inicio"]}-{c["hora_fin"]}</p>
                            </div>
                        '''
                    if len(conflictos_p) > 2:
                        html += f'<p class="text-[8px] text-gray-500 italic">+{len(conflictos_p)-2} más</p>'
                    html += '</div>'
                
                if conflictos_prof:
                    html += '<div><p class="text-[10px] font-black text-orange-700 mb-1 flex items-center gap-1">👨‍⚕️ Prof. ocupado:</p>'
                    for c in conflictos_prof[:2]:
                        html += f'''
                            <div class="text-[9px] bg-orange-50 rounded p-1.5 mb-1 border border-orange-200">
                                <p class="font-bold text-orange-900">{c["paciente"][:20]}</p>
                                <p class="text-gray-600">{c["hora_inicio"]}-{c["hora_fin"]}</p>
                            </div>
                        '''
                    if len(conflictos_prof) > 2:
                        html += f'<p class="text-[8px] text-gray-500 italic">+{len(conflictos_prof)-2} más</p>'
                    html += '</div>'
                
                html += '</div>'
            else:
                html += '</div>'
            
            html += '</label>'
        
        html += f'''
                </div>
            </div>
            
            {f'<div class="bg-orange-50 border-2 border-orange-300 rounded-lg p-3 mb-3"><div class="flex items-start gap-2 text-xs"><span class="text-orange-600 text-lg flex-shrink-0">⚠️</span><p class="text-orange-900"><strong>{conflictos}</strong> sesión(es) con conflicto de horario. Solo se crearán las <strong class="text-green-700">{disponibles}</strong> disponibles.</p></div></div>' if conflictos > 0 else ''}
            
            <div class="bg-blue-50 border border-blue-300 rounded-lg p-2 text-[11px] text-blue-800 flex items-center justify-between">
                <div class="flex items-center gap-2">
                    <span class="text-lg">ℹ️</span>
                    <span>Solo se crearán las sesiones que selecciones</span>
                </div>
                <div class="bg-white px-3 py-1 rounded-lg border border-blue-300 shadow-sm">
                    <span class="text-blue-900 font-bold">Seleccionadas: <span id="contador-seleccionadas-mensualidad" class="text-purple-600">0</span> / {total}</span>
                </div>
            </div>
        '''
        
        return HttpResponse(html)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return HttpResponse(f'''
            <div class="bg-red-50 border border-red-200 rounded p-3 text-center">
                <p class="text-xs text-red-700">❌ Error: {str(e)}</p>
            </div>
        ''')

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
    🆕 API JSON: Obtener proyectos de un paciente
    ✅ MODIFICADO: Incluye finalizados y muestra código
    """
    try:
        # Validar que el paciente existe
        paciente = get_object_or_404(Paciente, id=paciente_id)
        
        # ✅ CORRECCIÓN: Incluir 'finalizado' por si se quiere agendar algo extra
        # Excluir solo los 'cancelado'
        proyectos = Proyecto.objects.filter(
            paciente=paciente
        ).exclude(
            estado='cancelado'
        ).select_related('servicio_base', 'sucursal').order_by('-fecha_inicio')
        
        # Verificar permisos de sucursal del usuario
        # (Usamos getattr por si el decorador no inyectó la variable)
        sucursales_usuario = getattr(request, 'sucursales_usuario', None)
        
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
                'estado_raw': proyecto.estado, # Para lógica frontend si se necesita
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
    ✅ MODIFICADO: Soporta mensualidades multi-servicio
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
        
        # ✅ CORREGIDO v2: Buscar mensualidades que contengan el servicio+profesional
        # Una mensualidad puede tener MÚLTIPLES servicios, solo necesitamos verificar
        # que EXISTA AL MENOS UNO que coincida con servicio+profesional seleccionados
        
        # Primero obtener IDs de mensualidades que tienen esta combinación
        mensualidades_ids = ServicioProfesionalMensualidad.objects.filter(
            servicio=servicio,
            profesional=profesional
        ).values_list('mensualidad_id', flat=True)
        
        # Luego filtrar mensualidades por esos IDs
        mensualidades = Mensualidad.objects.filter(
            id__in=mensualidades_ids,
            paciente=paciente,
            sucursal=sucursal,
            estado__in=['activa', 'pausada']
        ).prefetch_related(
            'servicios_profesionales__servicio',
            'servicios_profesionales__profesional'
        ).order_by('-anio', '-mes')
        
        # Construir respuesta JSON
        mensualidades_data = []
        for mensualidad in mensualidades:
            # ✅ Incluir todos los servicios con sus profesionales
            servicios_list = []
            for sp in mensualidad.servicios_profesionales.all():
                servicios_list.append({
                    'id': sp.servicio.id,
                    'nombre': sp.servicio.nombre,
                    'profesional_id': sp.profesional.id,
                    'profesional_nombre': f"{sp.profesional.nombre} {sp.profesional.apellido}"
                })
            
            mensualidades_data.append({
                'id': mensualidad.id,
                'codigo': mensualidad.codigo,
                'periodo': mensualidad.periodo_display,  # "Enero 2024"
                'mes': mensualidad.mes,
                'anio': mensualidad.anio,
                'servicios': servicios_list,  # ✅ Array de servicios
                'servicios_display': mensualidad.servicios_display,  # ✅ String legible
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

@login_required
@solo_sus_sucursales
def modal_agendar_mensualidad(request, servicio_profesional_id):
    """
    Retorna el HTML del modal para agendar sesiones desde mensualidad
    OPCIÓN C: Días específicos + Patrón recurrente
    """
    
    # Obtener el servicio-profesional
    servicio_profesional = get_object_or_404(
        ServicioProfesionalMensualidad.objects.select_related(
            'mensualidad__paciente',
            'mensualidad__sucursal',
            'servicio',
            'profesional'
        ),
        id=servicio_profesional_id
    )
    
    mensualidad = servicio_profesional.mensualidad
    
    # Verificar permisos de sucursal
    sucursales_usuario = request.sucursales_usuario
    if sucursales_usuario is not None:
        if not sucursales_usuario.filter(id=mensualidad.sucursal.id).exists():
            return JsonResponse({
                'error': 'No tienes permiso para agendar en esta sucursal'
            }, status=403)
    
    # Calcular fechas del período
    anio = mensualidad.anio
    mes = mensualidad.mes
    
    # Primer y último día del mes
    fecha_inicio = date(anio, mes, 1)
    ultimo_dia = monthrange(anio, mes)[1]
    fecha_fin = date(anio, mes, ultimo_dia)
    
    # ========================================
    # OPCIÓN 1: Días de la semana para patrón recurrente
    # ========================================
    dias_semana = [
        (1, 'Lun'),
        (2, 'Mar'),
        (3, 'Mié'),
        (4, 'Jue'),
        (5, 'Vie'),
        (6, 'Sáb'),
        (0, 'Dom'),
    ]
    
    # ========================================
    # OPCIÓN 2: Generar calendario de días del mes
    # ========================================
    dias_mes = generar_calendario_mes(anio, mes)
    
    context = {
        'servicio_profesional': servicio_profesional,
        'mensualidad': mensualidad,
        'fecha_inicio': fecha_inicio.strftime('%Y-%m-%d'),
        'fecha_fin': fecha_fin.strftime('%Y-%m-%d'),
        'dias_semana': dias_semana,
        'dias_mes': dias_mes,  # Calendario completo con días del mes
    }
    
    return render(request, 'agenda/modal_agendar_mensualidad.html', context)


def generar_calendario_mes(anio, mes):
    """
    Genera un calendario del mes con días del mes anterior/siguiente
    para completar semanas completas (como un calendario real)
    
    Retorna lista de diccionarios:
    [
        {
            'fecha': '2026-03-01',
            'numero': 1,
            'es_otro_mes': False
        },
        ...
    ]
    """
    # Primer día del mes
    primer_dia = date(anio, mes, 1)
    
    # Último día del mes
    ultimo_dia_num = monthrange(anio, mes)[1]
    ultimo_dia = date(anio, mes, ultimo_dia_num)
    
    # Calendario Python (0=Lunes, 6=Domingo)
    cal = Calendar(firstweekday=0)  # Empieza en Lunes
    
    dias = []
    
    # Obtener todas las semanas del mes (pueden incluir días del mes anterior/siguiente)
    for semana in cal.monthdatescalendar(anio, mes):
        for dia_fecha in semana:
            es_otro_mes = dia_fecha.month != mes
            
            dias.append({
                'fecha': dia_fecha.strftime('%Y-%m-%d'),
                'numero': dia_fecha.day,
                'es_otro_mes': es_otro_mes,
                'dia_semana': dia_fecha.weekday(),  # 0=Lunes, 6=Domingo
            })
    
    return dias


@login_required
@solo_sus_sucursales
def procesar_agendar_mensualidad(request, servicio_profesional_id):
    """
    Procesa el formulario de agendamiento desde mensualidad
    OPCIÓN C: Soporta días específicos Y patrón recurrente
    """
    
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)
    
    try:
        # Obtener servicio-profesional
        servicio_profesional = get_object_or_404(
            ServicioProfesionalMensualidad.objects.select_related(
                'mensualidad__paciente',
                'mensualidad__sucursal',
                'servicio',
                'profesional'
            ),
            id=servicio_profesional_id
        )
        
        mensualidad = servicio_profesional.mensualidad
        
        # Verificar permisos
        sucursales_usuario = request.sucursales_usuario
        if sucursales_usuario is not None:
            if not sucursales_usuario.filter(id=mensualidad.sucursal.id).exists():
                messages.error(request, '❌ No tienes permiso para agendar en esta sucursal')
                return redirect('agenda:detalle_mensualidad', mensualidad_id=mensualidad.id)
        
        # ========================================
        # OBTENER DATOS DEL FORMULARIO
        # ========================================
        hora_inicio_str = request.POST.get('hora_inicio')
        duracion_minutos = int(request.POST.get('duracion_minutos'))
        modo_seleccion = request.POST.get('modo_seleccion', 'recurrente')
        observaciones = request.POST.get('observaciones', '')
        
        # Validaciones básicas
        if not all([hora_inicio_str, duracion_minutos]):
            messages.error(request, '❌ Faltan datos obligatorios (hora y duración)')
            return redirect('agenda:detalle_mensualidad', mensualidad_id=mensualidad.id)
        
        # Convertir hora
        hora_inicio = datetime.strptime(hora_inicio_str, '%H:%M').time()
        
        # Calcular hora fin
        hora_inicio_dt = datetime.combine(date.today(), hora_inicio)
        hora_fin_dt = hora_inicio_dt + timedelta(minutes=duracion_minutos)
        hora_fin = hora_fin_dt.time()
        
        # ========================================
        # GENERAR FECHAS SEGÚN MODO
        # ========================================
        fechas_generadas = []
        
        if modo_seleccion == 'recurrente':
            # MODO 1: Patrón recurrente (días de la semana)
            dias_semana = request.POST.getlist('dias_semana_recurrente')
            
            if not dias_semana:
                messages.error(request, '❌ Selecciona al menos un día de la semana')
                return redirect('agenda:detalle_mensualidad', mensualidad_id=mensualidad.id)
            
            # Convertir a enteros
            dias_semana = [int(d) for d in dias_semana]
            
            # ✅ OBTENER SESIONES SELECCIONADAS POR EL USUARIO
            sesiones_seleccionadas = request.POST.getlist('sesiones_seleccionadas')
            
            if not sesiones_seleccionadas:
                messages.error(request, '⚠️ Debes seleccionar al menos una sesión para agendar.')
                return redirect('agenda:detalle_mensualidad', mensualidad_id=mensualidad.id)
            
            # Convertir a conjunto de fechas seleccionadas
            fechas_seleccionadas = set([
                datetime.strptime(f, '%Y-%m-%d').date() for f in sesiones_seleccionadas
            ])
            
            # Generar fechas según patrón
            fecha_inicio = date(mensualidad.anio, mensualidad.mes, 1)
            ultimo_dia_num = monthrange(mensualidad.anio, mensualidad.mes)[1]
            fecha_fin = date(mensualidad.anio, mensualidad.mes, ultimo_dia_num)
            
            fecha_actual = fecha_inicio
            while fecha_actual <= fecha_fin:
                dia_semana = fecha_actual.weekday()  # 0=Lunes, 6=Domingo
                
                # Convertir: Python (0=Lunes) → JS (0=Domingo)
                dia_js = (dia_semana + 1) % 7
                
                # ✅ SOLO AGREGAR SI ESTÁ EN EL PATRÓN Y FUE SELECCIONADA
                if dia_js in dias_semana and fecha_actual in fechas_seleccionadas:
                    fechas_generadas.append(fecha_actual)
                
                fecha_actual += timedelta(days=1)
        
        else:
            # MODO 2: Días específicos del mes
            dias_especificos = request.POST.getlist('dias_especificos')
            
            if not dias_especificos:
                messages.error(request, '❌ Selecciona al menos un día del mes')
                return redirect('agenda:detalle_mensualidad', mensualidad_id=mensualidad.id)
            
            # Convertir strings de fecha a objetos date
            for fecha_str in dias_especificos:
                try:
                    fecha_obj = datetime.strptime(fecha_str, '%Y-%m-%d').date()
                    fechas_generadas.append(fecha_obj)
                except ValueError:
                    continue
            
            # Ordenar fechas
            fechas_generadas.sort()
        
        # ========================================
        # VALIDAR QUE SE GENERARON FECHAS
        # ========================================
        if not fechas_generadas:
            messages.warning(request, '⚠️ No se generaron fechas con la configuración seleccionada')
            return redirect('agenda:detalle_mensualidad', mensualidad_id=mensualidad.id)
        
        # ========================================
        # CREAR SESIONES
        # ========================================
        sesiones_creadas = 0
        sesiones_con_conflicto = 0
        fechas_con_conflicto = []
        
        for fecha in fechas_generadas:
            try:
                # Crear sesión (el modelo Sesion.clean() validará conflictos automáticamente)
                Sesion.objects.create(
                    paciente=mensualidad.paciente,
                    servicio=servicio_profesional.servicio,
                    profesional=servicio_profesional.profesional,
                    sucursal=mensualidad.sucursal,
                    mensualidad=mensualidad,
                    fecha=fecha,
                    hora_inicio=hora_inicio,
                    hora_fin=hora_fin,
                    duracion_minutos=duracion_minutos,
                    estado='programada',
                    observaciones=observaciones,
                    creada_por=request.user,
                    modificada_por=request.user
                )
                sesiones_creadas += 1
                
            except ValidationError as e:
                # El modelo detectó un conflicto en clean()
                sesiones_con_conflicto += 1
                fechas_con_conflicto.append(fecha.strftime('%d/%m'))
                
                # Log del error para debugging
                import traceback
                print(f"ValidationError en fecha {fecha}: {e}")
                continue
                
            except Exception as e:
                # Otros errores inesperados
                sesiones_con_conflicto += 1
                fechas_con_conflicto.append(fecha.strftime('%d/%m'))
                print(f"Error inesperado en fecha {fecha}: {e}")
                import traceback
                traceback.print_exc()
                continue
        
        # ========================================
        # PREPARAR DATOS PARA CONFIRMACIÓN
        # ========================================
        if sesiones_creadas > 0:
            # Obtener nombres de días seleccionados
            dias_nombres = {
                0: 'Domingo', 1: 'Lunes', 2: 'Martes', 3: 'Miércoles',
                4: 'Jueves', 5: 'Viernes', 6: 'Sábado'
            }
            
            # Construir lista de días basada en el modo de selección
            if modo_seleccion == 'recurrente':
                dias_semana_valores = request.POST.getlist('dias_semana_recurrente')
                dias_seleccionados_nombres = [dias_nombres[int(d)] for d in dias_semana_valores]
            else:
                # Para días específicos, mostrar las fechas
                dias_seleccionados_nombres = [f.strftime('%d/%m') for f in fechas_generadas[:5]]
                if len(fechas_generadas) > 5:
                    dias_seleccionados_nombres.append(f'+{len(fechas_generadas)-5} más')
            
            # Construir período
            fecha_min = min(fechas_generadas)
            fecha_max = max(fechas_generadas)
            periodo = f"{fecha_min.strftime('%d/%m/%Y')} al {fecha_max.strftime('%d/%m/%Y')}"
            
            # Construir horario
            horario = f"{hora_inicio.strftime('%H:%M')} - {hora_fin.strftime('%H:%M')} ({duracion_minutos} min)"
            
            # 🆕 Almacenar en session
            request.session['sesiones_creadas'] = {
                'mensaje': f'Se crearon exitosamente {sesiones_creadas} sesión(es) para {mensualidad.periodo_display}',
                'total_creadas': sesiones_creadas,
                'paciente': mensualidad.paciente.nombre_completo,
                'profesional': f"{servicio_profesional.profesional.nombre} {servicio_profesional.profesional.apellido}",
                'servicio': servicio_profesional.servicio.nombre,
                'periodo': periodo,
                'horario': horario,
                'dias': ', '.join(dias_seleccionados_nombres),
                'proyecto': None,  # Las mensualidades no usan proyectos
                'mensualidad': f"{mensualidad.codigo} - {mensualidad.periodo_display}",
                'errores': sesiones_con_conflicto,
            }
            
            return redirect('agenda:confirmacion_sesiones')
        
        # Si no se creó ninguna sesión, mostrar mensaje de error
        if sesiones_con_conflicto > 0:
            conflictos_str = ', '.join(fechas_con_conflicto[:5])
            if len(fechas_con_conflicto) > 5:
                conflictos_str += f' (+{len(fechas_con_conflicto) - 5} más)'
            
            messages.warning(
                request,
                f'⚠️ {sesiones_con_conflicto} sesión(es) omitida(s) por conflictos de horario en: {conflictos_str}'
            )
        else:
            messages.error(request, '❌ No se pudo crear ninguna sesión')
        
        return redirect('agenda:detalle_mensualidad', mensualidad_id=mensualidad.id)
        
    except Exception as e:
        import traceback
        print(traceback.format_exc())  # Para debugging
        messages.error(request, f'❌ Error al crear sesiones: {str(e)}')
        return redirect('agenda:detalle_mensualidad', mensualidad_id=mensualidad.id)