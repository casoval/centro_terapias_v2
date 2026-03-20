from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_POST
import json
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
from itertools import groupby

from agenda.models import Sesion, Proyecto, Mensualidad, ServicioProfesionalMensualidad, PermisoEdicionSesion
from django.contrib.auth.decorators import user_passes_test
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
    
    # Query string sin 'page' para preservar filtros en paginación
    params = request.GET.copy()
    params.pop('page', None)
    query_string = params.urlencode()

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
        'query_string': query_string,
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
    
    # Pagos del proyecto - ✅ CORREGIDO: Incluye pagos masivos
    from facturacion.models import Pago, Devolucion, DetallePagoMasivo
    
    # IDs de pagos directos
    pagos_directos_ids = proyecto.pagos.filter(anulado=False).values_list('id', flat=True)
    
    # IDs de pagos masivos que contienen este proyecto
    pagos_masivos_ids = DetallePagoMasivo.objects.filter(
        proyecto=proyecto,
        tipo='proyecto',
        pago__anulado=False
    ).values_list('pago_id', flat=True)
    
    # Combinar ambos conjuntos de IDs y obtener todos los pagos
    todos_ids = set(list(pagos_directos_ids) + list(pagos_masivos_ids))
    
    pagos = Pago.objects.filter(
        id__in=todos_ids,
        anulado=False
    ).select_related(
        'metodo_pago', 'registrado_por'
    ).order_by('-fecha_pago')
    
    # ✅ NUEVO: Devoluciones del proyecto
    devoluciones = Devolucion.objects.filter(
        proyecto=proyecto
    ).select_related(
        'metodo_devolucion', 'registrado_por'
    ).order_by('-fecha_devolucion')
    
    # Estadísticas
    stats = {
        'total_sesiones': sesiones.count(),
        'sesiones_realizadas': sesiones.filter(estado='realizada').count(),
        'sesiones_programadas': sesiones.filter(estado='programada').count(),
        'total_horas': sum(s.duracion_minutos for s in sesiones) / 60,
    }
    
    context = {
        'proyecto': proyecto,
        'sesiones': sesiones,
        'pagos': pagos,
        'devoluciones': devoluciones,  # ✅ NUEVO
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
    """
    Actualizar estado de un proyecto (AJAX)
    ✅ MEJORADO: Incluye opción de ajuste para estado cancelado
    """
    
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)
    
    try:
        from .services import ProyectoMensualidadService
        
        proyecto = Proyecto.objects.get(id=proyecto_id)
        nuevo_estado = request.POST.get('estado')
        
        if nuevo_estado not in dict(Proyecto.ESTADO_CHOICES):
            return JsonResponse({'error': 'Estado inválido'}, status=400)
        
        # ✅ NUEVO: Manejo especial para estados finales
        if nuevo_estado in ['finalizado', 'cancelado']:
            # Validar que no tenga sesiones programadas
            resultado = ProyectoMensualidadService.validar_cambio_estado(
                proyecto, nuevo_estado, tipo='proyecto'
            )
            
            if not resultado['success']:
                return JsonResponse({
                    'error': True,
                    'mensaje': resultado['mensaje'],
                    'tiene_sesiones_programadas': True,
                    'num_sesiones': resultado['num_sesiones_programadas']
                }, status=400)
            
            # Determinar si se debe ajustar el costo
            # ✅ FINALIZADO: Siempre ajusta automáticamente
            # ✅ CANCELADO: Solo si el usuario lo indica
            if nuevo_estado == 'finalizado':
                ajustar_costo = True
            else:  # cancelado
                # El parámetro viene del formulario/modal
                ajustar_costo = request.POST.get('ajustar_costo') == 'true'
            
            # Aplicar cambio de estado con ajuste
            resultado_cambio = ProyectoMensualidadService.cambiar_estado_con_ajuste(
                proyecto, nuevo_estado, ajustar_costo, request.user, tipo='proyecto'
            )
            
            return JsonResponse(resultado_cambio)
        
        # Cambio de estado normal (sin ajuste)
        proyecto.estado = nuevo_estado
        proyecto.modificado_por = request.user
        proyecto.save()
        
        return JsonResponse({
            'success': True,
            'ajuste_realizado': False,
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
    
    # Query string sin 'page' para preservar filtros en paginación
    params = request.GET.copy()
    params.pop('page', None)
    query_string = params.urlencode()

    context = {
        'page_obj': page_obj,
        'estadisticas': estadisticas,
        'buscar': buscar,
        'estado_filtro': estado_filtro,
        'sucursal_id': sucursal_id,
        'sucursales': sucursales,
        'estados': Mensualidad.ESTADO_CHOICES,
        'query_string': query_string,
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
    
    # Pagos de la mensualidad - ✅ CORREGIDO: Incluye pagos masivos
    from facturacion.models import Pago, Devolucion, DetallePagoMasivo
    
    # IDs de pagos directos
    pagos_directos_ids = Pago.objects.filter(
        mensualidad=mensualidad,
        anulado=False
    ).values_list('id', flat=True)
    
    # IDs de pagos masivos que contienen esta mensualidad
    pagos_masivos_ids = DetallePagoMasivo.objects.filter(
        mensualidad=mensualidad,
        tipo='mensualidad',
        pago__anulado=False
    ).values_list('pago_id', flat=True)
    
    # Combinar ambos conjuntos de IDs y obtener todos los pagos
    todos_ids = set(list(pagos_directos_ids) + list(pagos_masivos_ids))
    
    pagos = Pago.objects.filter(
        id__in=todos_ids,
        anulado=False
    ).select_related(
        'metodo_pago', 'registrado_por'
    ).order_by('-fecha_pago')
    
    # ✅ NUEVO: Devoluciones de la mensualidad
    devoluciones = Devolucion.objects.filter(
        mensualidad=mensualidad
    ).select_related(
        'metodo_devolucion', 'registrado_por'
    ).order_by('-fecha_devolucion')
    
    # Estadísticas
    stats = {
        'total_sesiones': sesiones.count(),
        'sesiones_realizadas': sesiones.filter(
            estado__in=['realizada', 'realizada_retraso']
        ).count(),
        'sesiones_programadas': sesiones.filter(estado='programada').count(),
        'total_horas': sum(s.duracion_minutos for s in sesiones) / 60,
    }
    
    context = {
        'mensualidad': mensualidad,
        'sesiones': sesiones,
        'pagos': pagos,
        'devoluciones': devoluciones,  # ✅ NUEVO
        'stats': stats,
    }
    
    return render(request, 'agenda/detalle_mensualidad.html', context)

@login_required
def actualizar_estado_mensualidad(request, mensualidad_id):
    """
    Actualizar estado de una mensualidad (AJAX)
    ✅ MEJORADO: Incluye opción de ajuste para estado cancelada
    """
    
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)
    
    try:
        from .services import ProyectoMensualidadService
        
        mensualidad = Mensualidad.objects.get(id=mensualidad_id)
        nuevo_estado = request.POST.get('estado')
        
        if nuevo_estado not in dict(Mensualidad.ESTADO_CHOICES):
            return JsonResponse({'error': 'Estado inválido'}, status=400)
        
        # ✅ NUEVO: Manejo especial para estados finales
        if nuevo_estado in ['completada', 'cancelada']:
            # Validar que no tenga sesiones programadas
            resultado = ProyectoMensualidadService.validar_cambio_estado(
                mensualidad, nuevo_estado, tipo='mensualidad'
            )
            
            if not resultado['success']:
                return JsonResponse({
                    'error': True,
                    'mensaje': resultado['mensaje'],
                    'tiene_sesiones_programadas': True,
                    'num_sesiones': resultado['num_sesiones_programadas']
                }, status=400)
            
            # Determinar si se debe ajustar el costo
            # ✅ COMPLETADA: Siempre ajusta automáticamente
            # ✅ CANCELADA: Solo si el usuario lo indica
            if nuevo_estado == 'completada':
                ajustar_costo = True
            else:  # cancelada
                # El parámetro viene del formulario/modal
                ajustar_costo = request.POST.get('ajustar_costo') == 'true'
            
            # Aplicar cambio de estado con ajuste
            resultado_cambio = ProyectoMensualidadService.cambiar_estado_con_ajuste(
                mensualidad, nuevo_estado, ajustar_costo, request.user, tipo='mensualidad'
            )
            
            return JsonResponse(resultado_cambio)
        
        # Cambio de estado normal (sin ajuste)
        mensualidad.estado = nuevo_estado
        mensualidad.modificada_por = request.user
        mensualidad.save()
        
        return JsonResponse({
            'success': True,
            'ajuste_realizado': False,
            'mensaje': f'Estado actualizado a: {mensualidad.get_estado_display()}'
        })
        
    except Mensualidad.DoesNotExist:
        return JsonResponse({'error': 'Mensualidad no encontrada'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@login_required
def confirmacion_mensualidad(request):
    """
    Vista de confirmación después de crear mensualidad
    """
    
    # Obtener datos de la sesión
    datos_mensualidad = request.session.get('mensualidad_creada')
    
    if not datos_mensualidad:
        messages.error(request, '❌ No hay datos de mensualidad para mostrar')


# ✅ NUEVO: API para obtener datos de confirmación al cancelar
@login_required
def api_datos_confirmacion_cancelacion(request):
    """
    API para obtener datos necesarios para confirmar cancelación
    Se usa tanto para proyectos como mensualidades
    """
    
    if request.method != 'GET':
        return JsonResponse({'error': 'Método no permitido'}, status=405)
    
    try:
        from .services import ProyectoMensualidadService
        
        tipo = request.GET.get('tipo')  # 'proyecto' o 'mensualidad'
        objeto_id = request.GET.get('id')
        nuevo_estado = request.GET.get('estado')
        
        if not all([tipo, objeto_id, nuevo_estado]):
            return JsonResponse({'error': 'Parámetros incompletos'}, status=400)
        
        # Obtener el objeto
        if tipo == 'proyecto':
            instancia = Proyecto.objects.get(id=objeto_id)
        elif tipo == 'mensualidad':
            instancia = Mensualidad.objects.get(id=objeto_id)
        else:
            return JsonResponse({'error': 'Tipo inválido'}, status=400)
        
        # Obtener datos para confirmación
        datos = ProyectoMensualidadService.obtener_datos_para_confirmacion(
            instancia, nuevo_estado, tipo
        )
        
        return JsonResponse(datos)
        
    except (Proyecto.DoesNotExist, Mensualidad.DoesNotExist):
        return JsonResponse({'error': 'Objeto no encontrado'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
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
    subvista = request.GET.get('subvista', '').strip()  # 'timeline' o ''
    
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
        'subvista': subvista,
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
        'permisos_activos_count': PermisoEdicionSesion.objects.filter(
            valido_desde__lte=date.today(),
            valido_hasta__gte=date.today(),
            usado=False,
        ).count() if (request.user.is_staff or request.user.is_superuser) else 0,
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
            
            # 🐛 DEBUG: Ver qué fechas llegaron
            print(f"🔍 DEBUG fechas_seleccionadas: {sorted(fechas_seleccionadas)}")
            print(f"🔍 DEBUG dias_semana: {dias_semana}")
            print(f"🔍 DEBUG fecha_inicio: {fecha_inicio}, fecha_fin: {fecha_fin}")
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
            
            # ✅ CORREGIDO: Leer sesiones_grupales del POST correctamente
            # El checkbox HTML envía 'on' cuando está marcado, no 'true'
            sesiones_grupales_raw = request.POST.get('sesiones_grupales', '')
            permitir_sesiones_grupales = sesiones_grupales_raw in ('on', 'true', '1', 'True')
            
            # 🐛 DEBUG
            print(f"🔍 DEBUG sesiones_grupales_raw: '{sesiones_grupales_raw}'")
            print(f"🔍 DEBUG permitir_sesiones_grupales: {permitir_sesiones_grupales}")
            print(f"🔍 DEBUG sesiones_seleccionadas count: {len(sesiones_seleccionadas)}")
            
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
                    # 🐛 DEBUG: Fecha procesada
                    print(f"✅ Procesando {fecha_actual.strftime("%Y-%m-%d")} - weekday={fecha_actual.weekday()}, en fechas_selec={fecha_actual in fechas_seleccionadas}")
                    try:
                        # ✅ CORREGIDO: Usar validar_disponibilidad_con_grupales
                        # para respetar el checkbox de sesiones grupales
                        # 🐛 DEBUG
                        disponible, mensaje = Sesion.validar_disponibilidad_con_grupales(
                            paciente, profesional, fecha_actual, hora, hora_fin,
                            permitir_sesiones_grupales=permitir_sesiones_grupales
                        )
                        
                        # 🐛 DEBUG: Resultado de validación
                        print(f"📅 Validando {fecha_actual.strftime("%Y-%m-%d")}: disponible={disponible}, mensaje={mensaje}, permitir_grupales={permitir_sesiones_grupales}")
                        
                        if disponible:
                            # 🆕 CREAR SESIÓN CON PROYECTO Y/O MENSUALIDAD
                            print(f"💾 Intentando crear sesión para {fecha_actual}")
                            
                            # ✅ Crear instancia SIN guardar
                            sesion = Sesion(
                                paciente=paciente,
                                servicio=servicio,
                                profesional=profesional,
                                sucursal=sucursal,
                                proyecto=proyecto,
                                mensualidad=mensualidad,
                                fecha=fecha_actual,
                                hora_inicio=hora,
                                hora_fin=hora_fin,
                                duracion_minutos=duracion_minutos,
                                monto_cobrado=monto,
                                creada_por=request.user,
                                modificada_por=request.user
                            )
                            
                            # ✅ Si se permiten sesiones grupales, agregar flag
                            if permitir_sesiones_grupales:
                                sesion._permitir_sesiones_grupales = True
                                print(f"🔓 Flag sesiones grupales establecido para {fecha_actual}")
                            
                            # ✅ Guardar la sesión (llamará a clean() pero respetará el flag)
                            sesion.save()
                            sesiones_creadas += 1
                            print(f"✅ Sesión creada exitosamente para {fecha_actual}. Total creadas: {sesiones_creadas}")
                        else:
                            sesiones_error.append({
                                'fecha': fecha_actual,
                                'error': mensaje
                            })
                    except Exception as e:
                        print(f"❌ EXCEPCIÓN capturada para {fecha_actual}: {e}")
                        import traceback
                        traceback.print_exc()
                        sesiones_error.append({
                            'fecha': fecha_actual,
                            'error': str(e)
                        })
                
                fecha_actual += timedelta(days=1)
            
            
            # 🐛 DEBUG: Resumen final
            print(f"\n📊 RESUMEN: sesiones_creadas={sesiones_creadas}, sesiones_error={len(sesiones_error)}")
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
@solo_sus_sucursales
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
    
    # ✅ NUEVO: Parámetro para sesiones grupales
    permitir_sesiones_grupales = request.GET.get('sesiones_grupales', 'false').lower() == 'true'
    
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
        
        # ✅ MODIFICADO: Pasar el parámetro permitir_sesiones_grupales
        while fecha_actual <= fecha_fin:
            if fecha_actual.weekday() in dias_semana:
                sesion_info = _validar_disponibilidad_detallada(
                    paciente, profesional, fecha_actual, hora, hora_fin,
                    permitir_sesiones_grupales=permitir_sesiones_grupales  # ✅ NUEVO
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


def _validar_disponibilidad_detallada(paciente, profesional, fecha, hora_inicio, hora_fin, permitir_sesiones_grupales=False):
    """
    Valida disponibilidad y retorna detalles COMPLETOS de los conflictos
    ✅ ACTUALIZADO: Incluye información detallada para tooltips
    ✅ NUEVO: Soporte para sesiones grupales
    
    Args:
        paciente: Paciente
        profesional: Profesional
        fecha: Fecha de la sesión
        hora_inicio: Hora de inicio
        hora_fin: Hora de fin
        permitir_sesiones_grupales: Si True, no valida conflictos del profesional
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
    
    # ✅ Verificar conflictos del PACIENTE (siempre se valida)
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
    
    # ✅ Verificar conflictos del PROFESIONAL (solo si NO se permiten sesiones grupales)
    if not permitir_sesiones_grupales:
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
    
    permitir_sesiones_grupales = request.GET.get('sesiones_grupales', 'false').lower() == 'true'
    
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
                hora_fin,
                permitir_sesiones_grupales=permitir_sesiones_grupales
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
                hora_fin,
                permitir_sesiones_grupales=permitir_sesiones_grupales
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
    sesion = get_object_or_404(Sesion, id=sesion_id)
    
    # ✅ BUG FIX: Llamar al método con paréntesis
    es_profesional = hasattr(request.user, 'perfil') and request.user.perfil.es_profesional()
    es_admin = request.user.is_superuser or (
        hasattr(request.user, 'perfil') and 
        request.user.perfil.rol in ['gerente', 'administrador']
    )
    es_recepcionista = hasattr(request.user, 'perfil') and request.user.perfil.es_recepcionista()

    profesional_actual = None
    if es_profesional:
        try:
            profesional_actual = get_profesional_usuario(request.user)
        except:
            pass

    hoy = date.today()
    puede_editar = True
    puede_editar_pago = True
    mensaje_bloqueo = None
    campos_permitidos = ['estado', 'notas_sesion', 'observaciones', 'hora_inicio', 'hora_fin']

    if not es_admin:
        if es_profesional:
            if sesion.fecha == hoy:
                # ✅ Siempre puede editar sesiones del día actual
                puede_editar = True
            else:
                # ✅ BUG FIX: Consultar permisos antes de bloquear
                if profesional_actual:
                    puede, campos, motivo = profesional_puede_editar_sesion(
                        profesional_actual, sesion
                    )
                else:
                    puede, campos, motivo = False, [], "Sin registro de profesional"
                
                if puede:
                    puede_editar = True
                    puede_editar_pago = False
                    campos_permitidos = campos
                    mensaje_bloqueo = None
                    # ✅ Registrar uso del permiso al guardar (se hace en POST)
                else:
                    puede_editar = False
                    puede_editar_pago = False
                    if sesion.fecha < hoy:
                        mensaje_bloqueo = "Solo lectura - Sesión pasada (sin permiso de edición)"
                    else:
                        mensaje_bloqueo = "Solo lectura - Sesión futura"

        elif es_recepcionista:
            if sesion.editada_por_profesional:
                puede_editar = False
                mensaje_bloqueo = "Solo lectura - Ya editada por profesional"
            puede_editar_pago = True

    if es_recepcionista:
        puede_editar_pago = True

    if request.method == 'POST':
        if not puede_editar and not puede_editar_pago:
            return JsonResponse({
                'error': True,
                'mensaje': f'❌ {mensaje_bloqueo}. No tienes permisos para editar esta sesión.'
            }, status=403)
        
        # ✅ Registrar uso del permiso si el profesional editó con permiso
        if puede_editar and es_profesional and profesional_actual and sesion.fecha != hoy:
            registrar_uso_permiso(profesional_actual, sesion)
        
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
            
            # 🆕 VALIDACIÓN: Si cambia a estado sin cobro y tiene pagos
            if puede_editar and estado_nuevo in ['permiso', 'cancelada', 'reprogramada']:
                pagos_activos = sesion.pagos.filter(anulado=False)
                
                if pagos_activos.exists():
                    # 🔒 PROFESIONALES: No pueden gestionar pagos — derivar a recepción/admin
                    if es_profesional:
                        total_pagado = pagos_activos.aggregate(Sum('monto'))['monto__sum'] or Decimal('0.00')
                        return JsonResponse({
                            'error': True,
                            'mensaje': (
                                f'❌ Esta sesión tiene un pago registrado de Bs. {total_pagado}. '
                                f'Para cambiar el estado a "{estado_nuevo}" debes comunicarte '
                                f'con recepción o administración para que gestionen el pago.'
                            )
                        }, status=403)
                    
                    # ✅ RECEPCIONISTAS / ADMINS: Modal de confirmación con opciones de pago
                    pagos_activos_list = pagos_activos.select_related('metodo_pago')
                    total_pagado = pagos_activos_list.aggregate(Sum('monto'))['monto__sum'] or Decimal('0.00')
                    
                    pagos_data = [
                        {
                            'numero_recibo': p.numero_recibo,
                            'concepto': p.concepto[:40],
                            'fecha': p.fecha_pago.strftime('%d/%m/%Y'),
                            'metodo': p.metodo_pago.nombre,
                            'monto': str(p.monto),
                        }
                        for p in pagos_activos_list
                    ]
                    
                    return JsonResponse({
                        'requiere_confirmacion': True,
                        'sesion_id': sesion.id,
                        'estado_nuevo': estado_nuevo,
                        'pagos': pagos_data,
                        'total_pagado': str(total_pagado),
                        'cantidad_pagos': len(pagos_data),
                        'mensaje': f'Esta sesión tiene {len(pagos_data)} pago(s) registrado(s) por Bs. {total_pagado}'
                    })
            
            # ✅ USAR TRANSACCIÓN para garantizar atomicidad
            with transaction.atomic():
                # ✅ MODIFICADO: Solo actualizar si tiene permiso de edición
                if puede_editar:
                    # Guardar estado anterior para logging
                    estado_anterior = sesion.estado
                    
                    # Actualizar estado
                    sesion.estado = estado_nuevo
                    
                    # Aplicar políticas de cobro según estado (todos los roles)
                    # Si llegó aquí con es_profesional=True, ya se validó que NO hay pagos activos
                    if estado_nuevo in ['permiso', 'cancelada', 'reprogramada']:
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
                        'estado', 'monto_cobrado', 'monto_previo_exencion',
                        'observaciones', 'notas_sesion',
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
    ✅ MODIFICADO: Ahora soporta sesiones grupales
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
        
        # ✅ NUEVO: Leer sesiones_grupales del POST
        sesiones_grupales_raw = request.POST.get('sesiones_grupales', '')
        permitir_sesiones_grupales = sesiones_grupales_raw in ('on', 'true', '1', 'True')
        
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
        # CREAR SESIONES (✅ MODIFICADO CON SESIONES GRUPALES)
        # ========================================
        sesiones_creadas = 0
        sesiones_con_conflicto = 0
        fechas_con_conflicto = []
        
        for fecha in fechas_generadas:
            try:
                # ✅ VALIDAR con sesiones grupales
                disponible, mensaje = Sesion.validar_disponibilidad_con_grupales(
                    mensualidad.paciente,
                    servicio_profesional.profesional,
                    fecha,
                    hora_inicio,
                    hora_fin,
                    permitir_sesiones_grupales=permitir_sesiones_grupales
                )
                
                if disponible:
                    # ✅ Crear instancia SIN guardar
                    sesion = Sesion(
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
                    
                    # ✅ Si se permiten sesiones grupales, agregar flag
                    if permitir_sesiones_grupales:
                        sesion._permitir_sesiones_grupales = True
                    
                    # ✅ Guardar la sesión (llamará a clean() pero respetará el flag)
                    sesion.save()
                    sesiones_creadas += 1
                else:
                    # No disponible según validación
                    sesiones_con_conflicto += 1
                    fechas_con_conflicto.append(fecha.strftime('%d/%m'))
                
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

# ═══════════════════════════════════════════════════════════════════════════════
# CAMBIO DE ESTADO CON PAGOS REGISTRADOS
# ═══════════════════════════════════════════════════════════════════════════════

ESTADOS_SIN_COBRO = ['permiso', 'cancelada', 'reprogramada']


@login_required
def modal_confirmar_cambio_estado(request, sesion_id):
    """
    Consulta AJAX: ¿tiene pagos esta sesión antes de cambiar a un estado sin cobro?
    GET  ?estado_nuevo=permiso              → JSON  { requiere_confirmacion: true/false }
    GET  ?estado_nuevo=permiso&formato=html → HTML  del partial con los datos del modal
    """
    from facturacion.models import Pago

    sesion = get_object_or_404(Sesion, id=sesion_id)
    estado_nuevo = request.GET.get('estado_nuevo', '')

    if estado_nuevo not in ESTADOS_SIN_COBRO:
        return JsonResponse({'requiere_confirmacion': False})

    pagos = Pago.objects.filter(
        sesion=sesion,
        anulado=False
    ).select_related('metodo_pago').exclude(metodo_pago__nombre='Uso de Crédito')

    if not pagos.exists():
        return JsonResponse({'requiere_confirmacion': False})

    total_pagado = sum(p.monto for p in pagos)

    # El JS del editar_form.html necesita los datos como JSON para construir el modal
    pagos_data = [
        {
            'numero_recibo': p.numero_recibo,
            'concepto': p.concepto[:40],
            'fecha': p.fecha_pago.strftime('%d/%m/%Y'),
            'metodo': p.metodo_pago.nombre,
            'monto': str(p.monto),
        }
        for p in pagos
    ]

    return JsonResponse({
        'requiere_confirmacion': True,
        'estado_nuevo': estado_nuevo,
        'pagos': pagos_data,
        'total_pagado': str(total_pagado),
        'cantidad_pagos': len(pagos_data),
    })


@login_required
def procesar_cambio_estado(request, sesion_id):
    """
    POST: Procesa el cambio de estado de una sesión que tiene pagos registrados.

    Campos POST:
        estado_nuevo         → 'permiso' | 'cancelada' | 'reprogramada'
        accion_pago          → 'convertir_credito' | 'anular_pago'
        motivo_anulacion     → texto (requerido si accion_pago == 'anular_pago')
        observaciones_cambio → texto opcional
    """
    from django.db import transaction
    from facturacion.models import Pago
    from facturacion.services import AccountService

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Método no permitido'}, status=405)

    sesion = get_object_or_404(Sesion, id=sesion_id)

    estado_nuevo         = request.POST.get('estado_nuevo', '').strip()
    accion_pago          = request.POST.get('accion_pago', '').strip()
    motivo_anulacion     = request.POST.get('motivo_anulacion', '').strip()
    observaciones_cambio = request.POST.get('observaciones_cambio', '').strip()

    # ── Validaciones ──────────────────────────────────────────────────────────
    if estado_nuevo not in ESTADOS_SIN_COBRO:
        return JsonResponse({'success': False, 'error': f"Estado '{estado_nuevo}' no requiere confirmación de pagos."}, status=400)

    if accion_pago not in ['convertir_credito', 'anular_pago']:
        return JsonResponse({'success': False, 'error': 'Debes elegir qué hacer con el dinero pagado.'}, status=400)

    if accion_pago == 'anular_pago' and not motivo_anulacion:
        return JsonResponse({'success': False, 'error': 'El motivo de anulación es obligatorio.'}, status=400)

    # ── Obtener pagos activos de la sesión ────────────────────────────────────
    pagos_sesion = Pago.objects.filter(
        sesion=sesion,
        anulado=False
    ).select_related('metodo_pago', 'paciente')

    try:
        with transaction.atomic():

            # ── Cambiar estado de la sesión ───────────────────────────────────
            estado_anterior = sesion.estado
            sesion.estado = estado_nuevo
            if observaciones_cambio:
                obs_previas = getattr(sesion, 'observaciones', '') or ''
                sesion.observaciones = (obs_previas + '\n' + observaciones_cambio).strip() if obs_previas else observaciones_cambio
            sesion.save()

            # ── Procesar pagos ────────────────────────────────────────────────
            monto_total = Decimal('0.00')
            for pago in pagos_sesion:
                monto_total += pago.monto

                if accion_pago == 'convertir_credito':
                    # Desvincular de la sesión → queda como pago adelantado (crédito)
                    pago.sesion = None
                    pago.concepto = (
                        f"Crédito por cambio de estado - sesión {sesion.fecha} "
                        f"({estado_anterior} → {estado_nuevo})"
                    )
                    if observaciones_cambio:
                        pago.observaciones = (
                            (pago.observaciones + '\n' if pago.observaciones else '') +
                            f"Cambio de estado: {observaciones_cambio}"
                        )
                    pago.save(update_fields=['sesion', 'concepto', 'observaciones'])

                elif accion_pago == 'anular_pago':
                    pago.anular(
                        usuario=request.user,
                        motivo=(
                            f"Cambio de estado sesión {sesion.fecha} "
                            f"({estado_anterior} → {estado_nuevo}). "
                            f"Motivo: {motivo_anulacion}"
                        )
                    )

            # ── Recalcular cuenta corriente ───────────────────────────────────
            AccountService.update_balance(sesion.paciente)

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

    # ── Respuesta de éxito ────────────────────────────────────────────────────
    if accion_pago == 'convertir_credito':
        mensaje = (
            f"Estado cambiado a '{estado_nuevo}'. "
            f"Bs. {monto_total} convertidos en crédito disponible para el paciente."
        )
    else:
        mensaje = (
            f"Estado cambiado a '{estado_nuevo}'. "
            f"Pago(s) anulados. Recuerda devolver Bs. {monto_total} al paciente."
        )

    return JsonResponse({'success': True, 'message': mensaje})

@login_required
def informe_evolucion(request, paciente_id):
    """
    Vista del formulario de filtros y previsualización del informe de evolución.
    GET  → muestra el formulario con los filtros
    POST → aplica filtros, agrupa por profesional → servicio y muestra en pantalla
    """
    paciente = get_object_or_404(Paciente, pk=paciente_id)

    # Profesionales que han atendido a este paciente
    profesionales = Profesional.objects.filter(
        sesiones__paciente=paciente
    ).distinct().order_by('nombre', 'apellido')

    # Servicios que ha recibido este paciente
    servicios = TipoServicio.objects.filter(
        sesiones__paciente=paciente
    ).distinct().order_by('nombre')

    ESTADOS = [
        ('programada',        'Programada'),
        ('realizada',         'Realizada'),
        ('realizada_retraso', 'Realizada con Retraso'),
        ('falta',             'Falta sin Aviso'),
        ('permiso',           'Permiso (con aviso)'),
        ('cancelada',         'Cancelada'),
        ('reprogramada',      'Reprogramada'),
    ]

    grupos = None
    filtros = {}
    total_sesiones = 0

    if request.method == 'POST':
        profesional_id  = request.POST.get('profesional', '').strip()
        servicio_id     = request.POST.get('servicio', '').strip()
        fecha_desde_str = request.POST.get('fecha_desde', '').strip()
        fecha_hasta_str = request.POST.get('fecha_hasta', '').strip()
        estados_sel     = request.POST.getlist('estados')

        filtros = {
            'profesional_id': profesional_id,
            'servicio_id':    servicio_id,
            'fecha_desde':    fecha_desde_str,
            'fecha_hasta':    fecha_hasta_str,
            'estados':        estados_sel,
        }

        qs = Sesion.objects.filter(paciente=paciente).select_related(
            'profesional', 'servicio', 'sucursal'
        )

        if profesional_id:
            qs = qs.filter(profesional_id=profesional_id)

        if servicio_id:
            qs = qs.filter(servicio_id=servicio_id)

        if fecha_desde_str:
            try:
                fd = datetime.strptime(fecha_desde_str, '%Y-%m-%d').date()
                qs = qs.filter(fecha__gte=fd)
                filtros['fecha_desde_obj'] = fd
            except ValueError:
                pass

        if fecha_hasta_str:
            try:
                fh = datetime.strptime(fecha_hasta_str, '%Y-%m-%d').date()
                qs = qs.filter(fecha__lte=fh)
                filtros['fecha_hasta_obj'] = fh
            except ValueError:
                pass

        if estados_sel:
            qs = qs.filter(estado__in=estados_sel)

        # Ordenar: profesional → servicio → fecha → hora
        qs = qs.order_by(
            'profesional__nombre', 'profesional__apellido',
            'servicio__nombre',
            'fecha', 'hora_inicio'
        )

        # Agrupar en Python: profesional → servicio → sesiones
        grupos = []
        for prof, sesiones_prof in groupby(qs, key=lambda s: s.profesional):
            subgrupos = []
            for serv, sesiones_serv in groupby(sesiones_prof, key=lambda s: s.servicio):
                lista = list(sesiones_serv)
                total_sesiones += len(lista)
                subgrupos.append({
                    'servicio': serv,
                    'sesiones': lista,
                })
            grupos.append({
                'profesional': prof,
                'subgrupos':   subgrupos,
            })

    return render(request, 'agenda/informe_evolucion.html', {
        'paciente':       paciente,
        'profesionales':  profesionales,
        'servicios':      servicios,
        'estados':        ESTADOS,
        'grupos':         grupos,
        'filtros':        filtros,
        'total_sesiones': total_sesiones,
    })


@login_required
def generar_pdf_informe_evolucion(request, paciente_id):
    """
    Genera y descarga el PDF del informe de evolución según los parámetros GET.
    """
    from agenda.informe_evolucion_pdf import generar_informe_evolucion_pdf

    paciente = get_object_or_404(Paciente, pk=paciente_id)

    profesional_id  = request.GET.get('profesional', '').strip()
    servicio_id     = request.GET.get('servicio', '').strip()
    fecha_desde_str = request.GET.get('fecha_desde', '').strip()
    fecha_hasta_str = request.GET.get('fecha_hasta', '').strip()
    estados_sel     = request.GET.getlist('estados')

    qs = Sesion.objects.filter(paciente=paciente).select_related(
        'profesional', 'servicio', 'sucursal'
    )

    profesional_nombre = "Todos los profesionales"
    servicio_nombre    = "Todos los servicios"
    fecha_desde = None
    fecha_hasta = None

    if profesional_id:
        qs = qs.filter(profesional_id=profesional_id)
        try:
            prof = Profesional.objects.get(pk=profesional_id)
            profesional_nombre = f"{prof.nombre} {prof.apellido}"
        except Profesional.DoesNotExist:
            pass

    if servicio_id:
        qs = qs.filter(servicio_id=servicio_id)
        try:
            from servicios.models import TipoServicio
            srv = TipoServicio.objects.get(pk=servicio_id)
            servicio_nombre = srv.nombre
        except TipoServicio.DoesNotExist:
            pass

    if fecha_desde_str:
        try:
            fecha_desde = datetime.strptime(fecha_desde_str, '%Y-%m-%d').date()
            qs = qs.filter(fecha__gte=fecha_desde)
        except ValueError:
            pass

    if fecha_hasta_str:
        try:
            fecha_hasta = datetime.strptime(fecha_hasta_str, '%Y-%m-%d').date()
            qs = qs.filter(fecha__lte=fecha_hasta)
        except ValueError:
            pass

    if estados_sel:
        qs = qs.filter(estado__in=estados_sel)

    qs = qs.order_by(
        'profesional__nombre', 'profesional__apellido',
        'servicio__nombre',
        'fecha', 'hora_inicio'
    )

    buffer = generar_informe_evolucion_pdf(
        paciente=paciente,
        sesiones=qs,
        profesional_nombre=profesional_nombre,
        servicio_nombre=servicio_nombre,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        estados_filtro=estados_sel,
    )

    nombre_archivo = (
        f"informe_evolucion_{paciente.apellido}_{paciente.nombre}_"
        f"{date.today().strftime('%Y%m%d')}.pdf"
    ).replace(' ', '_')

    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="{nombre_archivo}"'
    return response

import collections as _collections




@login_required
@solo_sus_sucursales
def modal_copiar_mensualidad(request, mensualidad_id):
    """
    Modal para copiar mensualidad con lógica de semana tipo.

    Flujo:
    - Selector de mes destino con estado (disponible / ya existe).
    - Formulario: editar SOLO la semana tipo (~5-7 filas).
    - Preview de solo lectura del mes completo para ver conflictos.
    - Al procesar: la semana tipo se replica a cada día del mes destino,
      incluyendo días pasados (mensualidades creadas tarde).
    """
    mensualidad_origen = get_object_or_404(
        Mensualidad.objects.select_related('paciente', 'sucursal')
                           .prefetch_related(
                               'servicios_profesionales__servicio',
                               'servicios_profesionales__profesional',
                           ),
        id=mensualidad_id
    )

    # ── Permisos ───────────────────────────────────────────
    sucursales_usuario = request.sucursales_usuario
    if sucursales_usuario is not None:
        if not sucursales_usuario.filter(id=mensualidad_origen.sucursal.id).exists():
            return HttpResponse(
                '<p class="text-red-600 font-bold p-4">❌ Sin permiso.</p>',
                status=403
            )

    MESES = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
             'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
    DIAS_SEMANA = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']

    mes_origen  = mensualidad_origen.mes
    anio_origen = mensualidad_origen.anio

    # ── Mes/año destino ────────────────────────────────────
    try:
        mes_destino  = int(request.GET.get('mes_destino',  0)) or (mes_origen % 12) + 1
        anio_destino = int(request.GET.get('anio_destino', 0)) or (
            anio_origen + 1 if mes_origen == 12 else anio_origen
        )
    except (ValueError, TypeError):
        mes_destino  = (mes_origen % 12) + 1
        anio_destino = anio_origen + 1 if mes_origen == 12 else anio_origen

    if mes_destino == mes_origen and anio_destino == anio_origen:
        mes_destino  = (mes_origen % 12) + 1
        anio_destino = anio_origen + 1 if mes_origen == 12 else anio_origen

    mes_destino_display = MESES[mes_destino]

    # ── Opciones de mes: 12 siguientes con estado ──────────
    opciones_mes = []
    for delta in range(1, 13):
        m_raw = mes_origen + delta
        m = ((m_raw - 1) % 12) + 1
        a = anio_origen + (m_raw - 1) // 12
        existe = Mensualidad.objects.filter(
            paciente=mensualidad_origen.paciente,
            mes=m, anio=a
        ).first()
        opciones_mes.append({
            'mes':      m,
            'anio':     a,
            'label':    f"{MESES[m]} {a}",
            'selected': (m == mes_destino and a == anio_destino),
            'existe':   existe,           # objeto Mensualidad o None
        })

    # ── ¿Ya existe mensualidad en el destino seleccionado? ─
    mensualidad_destino_existe = Mensualidad.objects.filter(
        paciente=mensualidad_origen.paciente,
        mes=mes_destino,
        anio=anio_destino
    ).first()

    sesiones_destino_count = 0
    if mensualidad_destino_existe:
        sesiones_destino_count = mensualidad_destino_existe.sesiones.filter(
            estado__in=['programada', 'realizada', 'realizada_retraso']
        ).count()

    # ── Servicios-profesionales de la mensualidad origen ──
    servicios_profesionales = list(
        mensualidad_origen.servicios_profesionales
        .select_related('servicio', 'profesional')
        .order_by('servicio__nombre')
    )

    # ── Sesiones del origen para detectar el patrón ───────
    sesiones_origen = list(
        mensualidad_origen.sesiones
        .select_related('servicio', 'profesional')
        .order_by('fecha', 'hora_inicio')
    )

    dias_en_destino = monthrange(anio_destino, mes_destino)[1]
    min_fecha       = date(anio_destino, mes_destino, 1)
    max_fecha       = date(anio_destino, mes_destino, dias_en_destino)

    # ── Extraer patrón semanal (semana tipo) ───────────────
    # patron_wd: { weekday: [ {hora_inicio, duracion, servicio_id, profesional_id} ] }
    #
    # ESTRATEGIA: usamos la UNIÓN de todos los slots únicos de todas las semanas,
    # agrupados por weekday. Así, si se agregaron nuevos servicios/slots a mitad de mes,
    # aparecen igualmente en la semana tipo sin marcar el patrón como irregular.
    #
    # patron_irregular solo se activa si hay CONFLICTOS REALES: mismo (weekday, servicio_id,
    # profesional_id) con distintas horas de inicio en diferentes semanas — no simplemente
    # porque unas semanas tengan más slots que otras.
    patron_wd        = _collections.defaultdict(list)
    patron_irregular = False

    if sesiones_origen:
        semanas_vistas = _collections.defaultdict(lambda: _collections.defaultdict(list))
        for s in sesiones_origen:
            wd       = s.fecha.weekday()
            iso_week = s.fecha.isocalendar()[1]
            semanas_vistas[iso_week][wd].append({
                'hora_inicio':    s.hora_inicio,
                'duracion':       s.duracion_minutos,
                'servicio_id':    s.servicio_id,
                'profesional_id': s.profesional_id,
            })

        # Construir patron_wd como unión de slots únicos de todas las semanas
        # Clave de deduplicación: (hora_inicio, servicio_id, profesional_id)
        for iso_week, sd in semanas_vistas.items():
            for wd, slots in sd.items():
                claves_existentes = {
                    (sl['hora_inicio'], sl['servicio_id'], sl['profesional_id'])
                    for sl in patron_wd[wd]
                }
                for slot in slots:
                    clave = (slot['hora_inicio'], slot['servicio_id'], slot['profesional_id'])
                    if clave not in claves_existentes:
                        patron_wd[wd].append(slot)
                        claves_existentes.add(clave)

        # Detectar irregularidades REALES: mismo (wd, servicio_id, profesional_id)
        # con hora_inicio distinta entre semanas distintas.
        # Agrupamos por (wd, servicio_id, profesional_id) y verificamos consistencia de hora.
        horas_por_clave = _collections.defaultdict(set)
        for iso_week, sd in semanas_vistas.items():
            for wd, slots in sd.items():
                for slot in slots:
                    key = (wd, slot['servicio_id'], slot['profesional_id'])
                    horas_por_clave[key].add(slot['hora_inicio'])

        patron_irregular = any(len(horas) > 1 for horas in horas_por_clave.values())

    # ── Semana tipo para el formulario editable ────────────
    # Lista ordenada por weekday → el usuario edita esto
    semana_tipo = []
    for wd in sorted(patron_wd.keys()):
        for slot in patron_wd[wd]:
            semana_tipo.append({
                'weekday':       wd,
                'dia_nombre':    DIAS_SEMANA[wd],
                'hora_inicio':   slot['hora_inicio'].strftime('%H:%M'),
                'duracion':      slot['duracion'],
                'servicio_id':   slot['servicio_id'],
                'profesional_id':slot['profesional_id'],
            })

    # ── Preview del mes completo (solo lectura) ────────────
    # Expandir el patrón a todos los días del mes destino
    preview_mes  = []   # { fecha_display, fecha_iso, slots: [{hora, servicio, profesional, conflicto, conflicto_paciente, conflicto_profesional}] }
    total_conflictos         = 0
    total_conflictos_paciente    = 0
    total_conflictos_profesional = 0

    # Estados relevantes para detección de solapamientos
    _ESTADOS_ACTIVOS = ['programada', 'realizada', 'realizada_retraso']

    for d in range(1, dias_en_destino + 1):
        fecha_d = date(anio_destino, mes_destino, d)
        wd      = fecha_d.weekday()

        if wd not in patron_wd:
            continue

        slots_dia = []
        for slot in patron_wd[wd]:
            hora_inicio = slot['hora_inicio']
            duracion    = slot['duracion']
            hora_fin    = (datetime.combine(fecha_d, hora_inicio)
                           + timedelta(minutes=duracion)).time()

            # ── Conflicto PACIENTE: solapamiento de rango (no solo hora exacta) ──
            conflicto_paciente = Sesion.objects.filter(
                paciente   = mensualidad_origen.paciente,
                fecha      = fecha_d,
                estado__in = _ESTADOS_ACTIVOS,
                hora_inicio__lt = hora_fin,
                hora_fin__gt    = hora_inicio,
            ).exists()

            # ── Conflicto PROFESIONAL: solapamiento de rango ──
            # Buscamos el objeto profesional desde servicios_profesionales
            sp_match = next(
                (sp for sp in servicios_profesionales
                 if sp.servicio_id   == slot['servicio_id']
                 and sp.profesional_id == slot['profesional_id']),
                None
            )
            conflicto_profesional = False
            if sp_match:
                conflicto_profesional = Sesion.objects.filter(
                    profesional = sp_match.profesional,
                    fecha       = fecha_d,
                    estado__in  = _ESTADOS_ACTIVOS,
                    hora_inicio__lt = hora_fin,
                    hora_fin__gt    = hora_inicio,
                ).exclude(
                    # Excluir la propia sesión del paciente si ya contabilizamos arriba
                    paciente = mensualidad_origen.paciente,
                ).exists()

            conflicto = conflicto_paciente or conflicto_profesional

            if conflicto:
                total_conflictos += 1
            if conflicto_paciente:
                total_conflictos_paciente += 1
            if conflicto_profesional:
                total_conflictos_profesional += 1

            slots_dia.append({
                'hora':                  hora_inicio.strftime('%H:%M'),
                'hora_fin':              hora_fin.strftime('%H:%M'),
                'duracion':              duracion,
                'servicio':              sp_match.servicio.nombre if sp_match else f"#{slot['servicio_id']}",
                'profesional':           (
                    f"{sp_match.profesional.nombre} {sp_match.profesional.apellido}"
                    if sp_match else f"#{slot['profesional_id']}"
                ),
                'conflicto':             conflicto,
                'conflicto_paciente':    conflicto_paciente,
                'conflicto_profesional': conflicto_profesional,
            })

        preview_mes.append({
            'fecha_iso':                   fecha_d.isoformat(),
            'fecha_display':               fecha_d.day,
            'dia_nombre':                  DIAS_SEMANA[wd],
            'dia_semana':                  wd,
            'slots':                       slots_dia,
            'tiene_conflicto':             any(s['conflicto'] for s in slots_dia),
            'tiene_conflicto_paciente':    any(s['conflicto_paciente'] for s in slots_dia),
            'tiene_conflicto_profesional': any(s['conflicto_profesional'] for s in slots_dia),
        })

    context = {
        'mensualidad_origen':         mensualidad_origen,
        'costo_mensual_valor':        str(mensualidad_origen.costo_mensual or '0'),
        'servicios_profesionales':    servicios_profesionales,
        'semana_tipo':                semana_tipo,
        'preview_mes':                preview_mes,
        'total_conflictos':                  total_conflictos,
        'total_conflictos_paciente':         total_conflictos_paciente,
        'total_conflictos_profesional':      total_conflictos_profesional,
        'patron_irregular':           patron_irregular,
        'mes_destino':                mes_destino,
        'anio_destino':               anio_destino,
        'mes_destino_display':        mes_destino_display,
        'mensualidad_destino_existe': mensualidad_destino_existe,
        'sesiones_destino_count':     sesiones_destino_count,
        'min_fecha_iso':              min_fecha.isoformat(),
        'max_fecha_iso':              max_fecha.isoformat(),
        'opciones_mes':               opciones_mes,
        'DIAS_SEMANA_JSON':           json.dumps(
            ['Lunes','Martes','Miércoles','Jueves','Viernes','Sábado','Domingo']
        ),
    }

    return render(request, 'agenda/modal_copiar_mensualidad.html', context)


@login_required
@solo_sus_sucursales
def procesar_copiar_mensualidad(request, mensualidad_id):
    """
    Recibe la semana tipo editada por el usuario y:
    1. Crea la nueva mensualidad.
    2. Copia los ServicioProfesionalMensualidad.
    3. Expande la semana tipo a TODOS los días del mes destino
       (incluye días pasados si se crea tarde en el mes).
    4. Omite sesiones con conflicto si grupales=OFF, las crea si grupales=ON.

    POST arrays (semana tipo, filas paralelas):
        weekday[]        int  0-6
        hora_inicio[]    HH:MM
        duracion[]       int  minutos
        servicio_id[]    int
        profesional_id[] int

    POST escalares:
        mes_destino, anio_destino, costo_mensual
        sesiones_grupales  '1' | ''
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    mensualidad_origen = get_object_or_404(
        Mensualidad.objects.select_related('paciente', 'sucursal')
                           .prefetch_related(
                               'servicios_profesionales__servicio',
                               'servicios_profesionales__profesional',
                           ),
        id=mensualidad_id
    )

    sucursales_usuario = request.sucursales_usuario
    if sucursales_usuario is not None:
        if not sucursales_usuario.filter(id=mensualidad_origen.sucursal.id).exists():
            messages.error(request, '❌ No tienes permiso.')
            return redirect('agenda:lista_mensualidades')

    MESES = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
             'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']

    try:
        mes_destino   = int(request.POST['mes_destino'])
        anio_destino  = int(request.POST['anio_destino'])
        costo_mensual = Decimal(request.POST.get('costo_mensual',
                                                  str(mensualidad_origen.costo_mensual)))
    except (KeyError, ValueError, TypeError):
        messages.error(request, '❌ Datos inválidos.')
        return redirect('agenda:detalle_mensualidad', mensualidad_id=mensualidad_id)

    permitir_grupales = request.POST.get('sesiones_grupales', '') in ('on', '1', 'true', 'True')

    # ── Verificar mensualidad destino ────────────────────────
    mensualidad_destino_existente = Mensualidad.objects.filter(
        paciente=mensualidad_origen.paciente,
        mes=mes_destino, anio=anio_destino
    ).first()
    if mensualidad_destino_existente:
        sesiones_count = mensualidad_destino_existente.sesiones.filter(
            estado__in=['programada', 'realizada', 'realizada_retraso']
        ).count()
        if sesiones_count > 0:
            messages.error(
                request,
                f'❌ La mensualidad {MESES[mes_destino]} {anio_destino} ya tiene '
                f'{sesiones_count} sesión(es). Eliminá todas las sesiones antes '
                f'de copiar, o usá el patrón semanal para agregar sesiones.'
            )
            return redirect('agenda:detalle_mensualidad', mensualidad_id=mensualidad_id)

    # ── Leer la semana tipo del POST ───────────────────────
    weekdays       = request.POST.getlist('weekday[]')
    horas_inicio   = request.POST.getlist('hora_inicio[]')
    duraciones     = request.POST.getlist('duracion[]')
    servicios_ids  = request.POST.getlist('servicio_id[]')
    profesionales_ids = request.POST.getlist('profesional_id[]')

    if not weekdays:
        messages.warning(request, '⚠️ La semana tipo está vacía.')
        return redirect('agenda:detalle_mensualidad', mensualidad_id=mensualidad_id)

    # Construir patron_wd: { weekday: [ {hora_inicio, duracion, servicio_id, profesional_id} ] }
    patron_wd = _collections.defaultdict(list)
    for idx in range(len(weekdays)):
        try:
            wd             = int(weekdays[idx])
            hora_inicio    = datetime.strptime(horas_inicio[idx], '%H:%M').time()
            duracion       = int(duraciones[idx]) if duraciones[idx] else 45
            servicio_id    = int(servicios_ids[idx])
            profesional_id = int(profesionales_ids[idx])
        except (ValueError, IndexError):
            continue
        patron_wd[wd].append({
            'hora_inicio':    hora_inicio,
            'duracion':       duracion,
            'servicio_id':    servicio_id,
            'profesional_id': profesional_id,
        })

    if not patron_wd:
        messages.warning(request, '⚠️ No hay slots válidos en la semana tipo.')
        return redirect('agenda:detalle_mensualidad', mensualidad_id=mensualidad_id)

    # Precargar servicios y profesionales
    from servicios.models import TipoServicio as _TipoServicio
    from profesionales.models import Profesional as _Profesional
    servicios_map     = {s.id: s for s in _TipoServicio.objects.all()}
    profesionales_map = {p.id: p for p in _Profesional.objects.all()}

    dias_en_mes = monthrange(anio_destino, mes_destino)[1]

    from django.db import transaction as _tx
    try:
        with _tx.atomic():

            # 1. Crear o reutilizar mensualidad destino
            if mensualidad_destino_existente:
                # Ya existe con 0 sesiones: actualizar costo y reutilizar
                nueva = mensualidad_destino_existente
                nueva.costo_mensual = costo_mensual
                nueva.observaciones = (
                    f"Copiada desde {mensualidad_origen.codigo} "
                    f"({mensualidad_origen.periodo_display})"
                )
                nueva.save()
            else:
                nueva = Mensualidad(
                    paciente      = mensualidad_origen.paciente,
                    sucursal      = mensualidad_origen.sucursal,
                    mes           = mes_destino,
                    anio          = anio_destino,
                    costo_mensual = costo_mensual,
                    estado        = 'activa',
                    observaciones = (
                        f"Copiada desde {mensualidad_origen.codigo} "
                        f"({mensualidad_origen.periodo_display})"
                    ),
                    creada_por    = request.user,
                )
                nueva.save()

            # 2. Copiar ServicioProfesionalMensualidad (solo si es nueva)
            if not mensualidad_destino_existente:
                for sp in mensualidad_origen.servicios_profesionales.all():
                    ServicioProfesionalMensualidad.objects.create(
                        mensualidad = nueva,
                        servicio    = sp.servicio,
                        profesional = sp.profesional,
                    )

            # 3. Expandir semana tipo a todos los días del mes
            creadas  = 0
            omitidas = 0
            conflictos_detalle = []

            for d in range(1, dias_en_mes + 1):
                fecha = date(anio_destino, mes_destino, d)
                wd    = fecha.weekday()

                if wd not in patron_wd:
                    continue

                for slot in patron_wd[wd]:
                    servicio    = servicios_map.get(slot['servicio_id'])
                    profesional = profesionales_map.get(slot['profesional_id'])

                    if not servicio or not profesional:
                        omitidas += 1
                        continue

                    hora_inicio = slot['hora_inicio']
                    duracion    = slot['duracion']
                    hora_fin    = (datetime.combine(fecha, hora_inicio)
                                   + timedelta(minutes=duracion)).time()

                    disponible, msg_disp = Sesion.validar_disponibilidad_con_grupales(
                        mensualidad_origen.paciente,
                        profesional,
                        fecha,
                        hora_inicio,
                        hora_fin,
                        permitir_sesiones_grupales=permitir_grupales
                    )

                    if not disponible:
                        omitidas += 1
                        conflictos_detalle.append(
                            f"{fecha.strftime('%d/%m')} {hora_inicio.strftime('%H:%M')} – {msg_disp}"
                        )
                        continue

                    try:
                        sesion = Sesion(
                            paciente         = mensualidad_origen.paciente,
                            servicio         = servicio,
                            profesional      = profesional,
                            sucursal         = mensualidad_origen.sucursal,
                            mensualidad      = nueva,
                            fecha            = fecha,
                            hora_inicio      = hora_inicio,
                            hora_fin         = hora_fin,
                            duracion_minutos = duracion,
                            estado           = 'programada',
                            monto_cobrado    = Decimal('0.00'),
                            creada_por       = request.user,
                            modificada_por   = request.user,
                        )
                        if permitir_grupales:
                            sesion._permitir_sesiones_grupales = True
                        sesion.save()
                        creadas += 1
                    except ValidationError:
                        omitidas += 1
                        conflictos_detalle.append(
                            f"{fecha.strftime('%d/%m')} {hora_inicio.strftime('%H:%M')}"
                        )

            # 4. Mensaje de resultado
            if creadas > 0:
                msg = (
                    f'✅ Mensualidad {nueva.codigo} creada para '
                    f'{MESES[mes_destino]} {anio_destino} '
                    f'con {creadas} sesión(es).'
                )
                if omitidas:
                    msg += f' ({omitidas} omitida(s) por conflicto de horario)'
                messages.success(request, msg)
            else:
                messages.warning(
                    request,
                    f'⚠️ Se creó la mensualidad {nueva.codigo} pero no se pudo '
                    f'crear ninguna sesión (todas tenían conflicto de horario).'
                )

            return redirect('agenda:detalle_mensualidad', mensualidad_id=nueva.id)

    except Exception as e:
        import traceback
        traceback.print_exc()
        messages.error(request, f'❌ Error al copiar mensualidad: {e}')
        return redirect('agenda:detalle_mensualidad', mensualidad_id=mensualidad_id)

# ════════════════════════════════════════════════════════════════
#  AGENDAR POR PATRÓN SEMANAL  (sesiones normales, sin mensualidad)
# ════════════════════════════════════════════════════════════════

def _semana_iso_a_rango(iso_year, iso_week):
    """Devuelve (lunes, domingo) de la semana ISO dada."""
    lunes  = date.fromisocalendar(iso_year, iso_week, 1)
    domingo = lunes + timedelta(days=6)
    return lunes, domingo


def _construir_semanas_de_mes(anio, mes):
    """
    Devuelve lista de dicts con todas las semanas que tienen
    al menos un día en ese mes/año, con info de compartición.

    Cada dict:
        iso_year, iso_week       → identificadores únicos
        lunes, domingo           → date
        dias_mes   [date, ...]   → días que pertenecen a este mes
        dias_otro  [date, ...]   → días que pertenecen al otro mes
        compartida               → bool
        mes_anterior             → bool (los días extra son del mes anterior)
        mes_siguiente            → bool (los días extra son del mes siguiente)
        label                    → "lun 2 – dom 8 mar"
    """
    DIAS_CORTO = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']
    dias_en_mes = monthrange(anio, mes)[1]
    semanas_vistas = {}  # (iso_year, iso_week) → set de fechas del mes

    for d in range(1, dias_en_mes + 1):
        fecha = date(anio, mes, d)
        key   = (fecha.isocalendar()[0], fecha.isocalendar()[1])
        semanas_vistas.setdefault(key, []).append(fecha)

    resultado = []
    for (iy, iw), dias_del_mes in sorted(semanas_vistas.items()):
        lunes, domingo = _semana_iso_a_rango(iy, iw)
        dias_otro = [
            lunes + timedelta(days=i)
            for i in range(7)
            if (lunes + timedelta(days=i)) not in dias_del_mes
        ]
        compartida     = len(dias_otro) > 0
        mes_anterior   = compartida and dias_otro[0] < dias_del_mes[0]
        mes_siguiente  = compartida and dias_otro[-1] > dias_del_mes[-1]

        # Label legible: "Lun 2 – Dom 8"
        fmt_ini = f"{DIAS_CORTO[lunes.weekday()]} {lunes.day}"
        fmt_fin = f"{DIAS_CORTO[domingo.weekday()]} {domingo.day}"
        label   = f"{fmt_ini} – {fmt_fin}"

        resultado.append({
            'iso_year':      iy,
            'iso_week':      iw,
            'lunes':         lunes,
            'domingo':       domingo,
            'dias_mes':      dias_del_mes,
            'dias_otro':     dias_otro,
            'compartida':    compartida,
            'mes_anterior':  mes_anterior,
            'mes_siguiente': mes_siguiente,
            'label':         label,
            'key':           f"{iy}-{iw}",   # para usar en el template
        })
    return resultado


@login_required
@solo_sus_sucursales
def agendar_patron_semanal(request):
    """
    Página principal: buscador de paciente + formulario de 4 pasos.
    Paso 1 — elegir paciente
    Paso 2 — elegir/definir semana tipo
    Paso 3 — elegir semanas a aplicar (navegación por mes)
    Paso 4 — preview y confirmar
    """
    sucursales_usuario = request.sucursales_usuario

    # Sucursales para filtros
    if sucursales_usuario is not None and sucursales_usuario.exists():
        sucursales = sucursales_usuario
    else:
        sucursales = Sucursal.objects.filter(activa=True)

    # Servicios y profesionales para el formulario de semana tipo
    from servicios.models import TipoServicio as _TS
    from profesionales.models import Profesional as _Prof
    servicios     = _TS.objects.filter(activo=True).order_by('nombre')
    profesionales = _Prof.objects.filter(activo=True).order_by('nombre')

    # Mes actual para el selector inicial de semanas
    hoy = date.today()

    context = {
        'sucursales':     sucursales,
        'servicios':      servicios,
        'profesionales':  profesionales,
        'mes_actual':     hoy.month,
        'anio_actual':    hoy.year,
        'DIAS_SEMANA':    json.dumps(['Lunes','Martes','Miércoles','Jueves','Viernes','Sábado','Domingo']),
    }
    return render(request, 'agenda/agendar_patron_semanal.html', context)


@login_required
def api_semanas_paciente(request, paciente_id):
    """
    Devuelve las últimas 4 semanas con sesiones del paciente
    para mostrar como sugerencias de semana base.
    """
    paciente = get_object_or_404(Paciente, id=paciente_id)

    # Últimas 12 semanas ISO que tengan sesiones (no canceladas)
    sesiones = (
        Sesion.objects
        .filter(
            paciente=paciente,
            estado__in=['programada', 'realizada', 'realizada_retraso']
        )
        .select_related('servicio', 'profesional')
        .order_by('-fecha')
    )

    # Agrupar por semana ISO
    semanas = {}
    for s in sesiones:
        iy, iw, _ = s.fecha.isocalendar()
        key = (iy, iw)
        semanas.setdefault(key, []).append(s)
        if len(semanas) >= 12 and key in semanas:
            pass  # seguimos para no cortar sesiones de la misma semana
        if len(semanas) > 12:
            break

    DIAS_SEMANA = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
    resultado = []
    for (iy, iw), sesiones_semana in sorted(semanas.items(), reverse=True)[:12]:
        lunes, domingo = _semana_iso_a_rango(iy, iw)
        slots = []
        for s in sorted(sesiones_semana, key=lambda x: (x.fecha.weekday(), x.hora_inicio)):
            slots.append({
                'weekday':       s.fecha.weekday(),
                'dia_nombre':    DIAS_SEMANA[s.fecha.weekday()],
                'hora_inicio':   s.hora_inicio.strftime('%H:%M'),
                'duracion':      s.duracion_minutos,
                'servicio_id':   s.servicio_id,
                'servicio_nombre': s.servicio.nombre,
                'profesional_id':  s.profesional_id,
                'profesional_nombre': f"{s.profesional.nombre} {s.profesional.apellido}",
            })
        resultado.append({
            'key':    f"{iy}-{iw}",
            'label':  f"{lunes.strftime('%d/%m')} – {domingo.strftime('%d/%m/%Y')}",
            'lunes':  lunes.isoformat(),
            'domingo': domingo.isoformat(),
            'slots':  slots,
        })

    return JsonResponse({'semanas': resultado, 'paciente_nombre': str(paciente)})


@login_required
def api_semanas_mes(request):
    """
    Devuelve las semanas de un mes con info de:
    - Si son compartidas con mes anterior/siguiente
    - Si el paciente ya tiene sesiones en esos días
    GET params: mes, anio, paciente_id
    """
    try:
        mes        = int(request.GET['mes'])
        anio       = int(request.GET['anio'])
        paciente_id = int(request.GET['paciente_id'])
    except (KeyError, ValueError):
        return JsonResponse({'error': 'Parámetros inválidos'}, status=400)

    paciente = get_object_or_404(Paciente, id=paciente_id)
    semanas  = _construir_semanas_de_mes(anio, mes)

    # ✅ mes_fijo: cuando viene de mensualidad, solo mostramos ese mes
    # GET param opcional: mes_fijo=1 bloquea la navegación y filtra días en semanas compartidas
    mes_fijo = request.GET.get('mes_fijo', '0') == '1'

    # Fechas con sesiones del paciente en el rango del mes + semanas adyacentes
    fecha_ini = semanas[0]['lunes']
    fecha_fin = semanas[-1]['domingo']
    fechas_con_sesion = set(
        Sesion.objects.filter(
            paciente=paciente,
            fecha__range=(fecha_ini, fecha_fin),
            estado__in=['programada', 'realizada', 'realizada_retraso']
        ).values_list('fecha', flat=True)
    )

    MESES = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
             'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']

    semanas_json = []
    for s in semanas:
        dias_mes_con_sesion  = [d.isoformat() for d in s['dias_mes']  if d in fechas_con_sesion]
        dias_otro_con_sesion = [d.isoformat() for d in s['dias_otro'] if d in fechas_con_sesion]

        # Nombres del otro mes para mostrar en las opciones de semana compartida
        if s['mes_anterior']:
            otro_mes = s['dias_otro'][0].month
            otro_anio = s['dias_otro'][0].year
        elif s['mes_siguiente']:
            otro_mes = s['dias_otro'][0].month
            otro_anio = s['dias_otro'][0].year
        else:
            otro_mes = None
            otro_anio = None

        semanas_json.append({
            'key':               s['key'],
            'label':             s['label'],
            'lunes':             s['lunes'].isoformat(),
            'domingo':           s['domingo'].isoformat(),
            'compartida':        s['compartida'],
            # ✅ Con mes_fijo, semanas compartidas se tratan como "solo_mes" automáticamente
            'mes_fijo':          mes_fijo,
            'mes_anterior':      s['mes_anterior'],
            'mes_siguiente':     s['mes_siguiente'],
            'otro_mes_nombre':   MESES[otro_mes] if otro_mes else None,
            'mes_nombre':        MESES[mes],
            'dias_mes':          [d.isoformat() for d in s['dias_mes']],
            'dias_otro':         [d.isoformat() for d in s['dias_otro']],
            'dias_mes_con_sesion':  dias_mes_con_sesion,
            'dias_otro_con_sesion': dias_otro_con_sesion,
        })

    MESES_PREV = mes - 1 if mes > 1 else 12
    ANIO_PREV  = anio if mes > 1 else anio - 1
    MESES_NEXT = mes + 1 if mes < 12 else 1
    ANIO_NEXT  = anio if mes < 12 else anio + 1

    return JsonResponse({
        'semanas':       semanas_json,
        'mes_display':   f"{MESES[mes]} {anio}",
        'mes':           mes,
        'anio':          anio,
        'mes_fijo':      mes_fijo,
        'prev_mes':      MESES_PREV,
        'prev_anio':     ANIO_PREV,
        'next_mes':      MESES_NEXT,
        'next_anio':     ANIO_NEXT,
    })


@login_required
def api_preview_patron(request):
    """
    Recibe la semana tipo + la selección de semanas + decisiones sobre semanas
    compartidas y devuelve el preview expandido de todos los días a crear.

    POST JSON:
    {
        paciente_id: int,
        semana_tipo: [ {weekday, hora_inicio, duracion, servicio_id, profesional_id} ],
        semanas_seleccionadas: [
            {
                key: "2026-10",
                decision: "todo" | "solo_mes" | "solo_otro" | "omitir",
                dias_incluir: ["2026-03-02", ...]   // fechas concretas a incluir
            }
        ],
        permitir_grupales: bool
    }
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST requerido'}, status=405)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON inválido'}, status=400)

    paciente_id  = data.get('paciente_id')
    semana_tipo  = data.get('semana_tipo', [])
    semanas_sel  = data.get('semanas_seleccionadas', [])
    perm_grupales = data.get('permitir_grupales', False)

    if not paciente_id or not semana_tipo or not semanas_sel:
        return JsonResponse({'error': 'Datos incompletos'}, status=400)

    paciente = get_object_or_404(Paciente, id=paciente_id)

    # Construir patron_wd
    patron_wd = _collections.defaultdict(list)
    for slot in semana_tipo:
        try:
            wd  = int(slot['weekday'])
            h   = datetime.strptime(slot['hora_inicio'], '%H:%M').time()
            dur = int(slot.get('duracion', 45))
            sid = int(slot['servicio_id'])
            pid = int(slot['profesional_id'])
        except (KeyError, ValueError):
            continue
        patron_wd[wd].append({'hora_inicio': h, 'duracion': dur,
                               'servicio_id': sid, 'profesional_id': pid})

    # Resolver nombres
    from servicios.models import TipoServicio as _TS
    from profesionales.models import Profesional as _Prof
    servicios_map     = {s.id: s for s in _TS.objects.all()}
    profesionales_map = {p.id: p for p in _Prof.objects.all()}

    DIAS_SEMANA = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']

    # Expandir fechas a crear
    fechas_a_crear = set()
    for sem in semanas_sel:
        decision    = sem.get('decision', 'todo')
        dias_incluir = sem.get('dias_incluir', [])
        if decision == 'omitir':
            continue
        for d_iso in dias_incluir:
            fechas_a_crear.add(date.fromisoformat(d_iso))

    # Para cada fecha, generar slots y verificar conflictos
    dias_preview = []
    total_conflictos = 0
    total_con_sesiones_previas = 0

    for fecha in sorted(fechas_a_crear):
        wd = fecha.weekday()
        if wd not in patron_wd:
            continue

        slots_dia = []
        for slot in patron_wd[wd]:
            hora_inicio = slot['hora_inicio']
            duracion    = slot['duracion']
            hora_fin    = (datetime.combine(fecha, hora_inicio)
                           + timedelta(minutes=duracion)).time()

            serv = servicios_map.get(slot['servicio_id'])
            prof = profesionales_map.get(slot['profesional_id'])

            # Verificar conflicto igual que al crear (paciente + profesional)
            if prof:
                disponible, msg_conflicto = Sesion.validar_disponibilidad_con_grupales(
                    paciente, prof, fecha, hora_inicio, hora_fin,
                    permitir_sesiones_grupales=perm_grupales
                )
                conflicto = not disponible
            else:
                conflicto, msg_conflicto = False, ''

            if conflicto:
                total_conflictos += 1

            # Sesiones previas ese día (cualquier hora)
            sesiones_previas_dia = Sesion.objects.filter(
                paciente   = paciente,
                fecha      = fecha,
                estado__in = ['programada', 'realizada', 'realizada_retraso']
            ).exists()

            slots_dia.append({
                'hora':        hora_inicio.strftime('%H:%M'),
                'hora_fin':    hora_fin.strftime('%H:%M'),
                'duracion':    duracion,
                'servicio':    serv.nombre if serv else f"#{slot['servicio_id']}",
                'profesional': f"{prof.nombre} {prof.apellido}" if prof else f"#{slot['profesional_id']}",
                'servicio_id':    slot['servicio_id'],
                'profesional_id': slot['profesional_id'],
                'conflicto':      conflicto,
                'conflicto_msg':  msg_conflicto if conflicto else '',
            })

        tiene_sesiones_previas = Sesion.objects.filter(
            paciente=paciente, fecha=fecha,
            estado__in=['programada','realizada','realizada_retraso']
        ).exists()

        if tiene_sesiones_previas:
            total_con_sesiones_previas += 1

        dias_preview.append({
            'fecha_iso':            fecha.isoformat(),
            'fecha_display':        fecha.strftime('%d/%m/%Y'),
            'dia_nombre':           DIAS_SEMANA[wd],
            'tiene_conflicto':      any(s['conflicto'] for s in slots_dia),
            'tiene_sesiones_previas': tiene_sesiones_previas,
            'slots':                slots_dia,
        })

    return JsonResponse({
        'dias':                    dias_preview,
        'total_conflictos':        total_conflictos,
        'total_con_sesiones_previas': total_con_sesiones_previas,
        'total_sesiones':          sum(len(d['slots']) for d in dias_preview),
    })


@login_required
@solo_sus_sucursales
def procesar_patron_semanal(request):
    """
    Crea todas las sesiones a partir del patrón semanal confirmado.
    POST JSON: { paciente_id, sucursal_id, semana_tipo, fechas, permitir_grupales,
                 tipo_agenda, vinculo_id }
    Siempre devuelve JSON, nunca HTML de error.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST requerido'}, status=405)

    # ── Parsear body ────────────────────────────────────────────────
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, Exception):
        return JsonResponse({'error': 'JSON inválido'}, status=400)

    # ── Todo el procesamiento dentro de un try global → siempre JSON ─
    try:
        paciente_id   = data.get('paciente_id')
        sucursal_id   = data.get('sucursal_id')
        semana_tipo   = data.get('semana_tipo', [])
        fechas_iso    = data.get('fechas', [])
        perm_grupales = data.get('permitir_grupales', False)
        tipo_agenda   = data.get('tipo_agenda', 'normal')   # 'normal'|'mensualidad'|'proyecto'
        vinculo_id    = data.get('vinculo_id')

        if not all([paciente_id, sucursal_id, semana_tipo, fechas_iso]):
            return JsonResponse({'error': 'Datos incompletos'}, status=400)

        paciente = get_object_or_404(Paciente, id=paciente_id)
        sucursal = get_object_or_404(Sucursal, id=sucursal_id)

        # Verificar permisos de sucursal (el decorator inyecta sucursales_usuario)
        sucursales_usuario = request.sucursales_usuario
        if sucursales_usuario is not None:
            if not sucursales_usuario.filter(id=sucursal.id).exists():
                return JsonResponse({'error': 'Sin permiso para esta sucursal'}, status=403)

        # ── Construir patron_wd ────────────────────────────────────
        import collections as _col
        patron_wd = _col.defaultdict(list)
        for slot in semana_tipo:
            try:
                wd  = int(slot['weekday'])
                h   = datetime.strptime(slot['hora_inicio'], '%H:%M').time()
                dur = int(slot.get('duracion', 45))
                sid = int(slot['servicio_id'])
                pid = int(slot['profesional_id'])
            except (KeyError, ValueError):
                continue
            patron_wd[wd].append({'hora_inicio': h, 'duracion': dur,
                                   'servicio_id': sid, 'profesional_id': pid})

        from servicios.models import TipoServicio as _TS
        from profesionales.models import Profesional as _Prof
        servicios_map     = {s.id: s for s in _TS.objects.all()}
        profesionales_map = {p.id: p for p in _Prof.objects.all()}

        from django.db import transaction as _tx
        creadas  = 0
        omitidas = 0
        errores  = []

        with _tx.atomic():
            for fecha_iso in fechas_iso:
                try:
                    fecha = date.fromisoformat(fecha_iso)
                except ValueError:
                    continue

                wd = fecha.weekday()
                if wd not in patron_wd:
                    continue

                for slot in patron_wd[wd]:
                    servicio    = servicios_map.get(slot['servicio_id'])
                    profesional = profesionales_map.get(slot['profesional_id'])

                    if not servicio or not profesional:
                        omitidas += 1
                        continue

                    hora_inicio = slot['hora_inicio']
                    duracion    = slot['duracion']
                    hora_fin    = (datetime.combine(fecha, hora_inicio)
                                   + timedelta(minutes=duracion)).time()

                    try:
                        disponible, msg = Sesion.validar_disponibilidad_con_grupales(
                            paciente, profesional, fecha, hora_inicio, hora_fin,
                            permitir_sesiones_grupales=perm_grupales
                        )
                    except Exception:
                        disponible, msg = True, ''

                    if not disponible:
                        omitidas += 1
                        errores.append(
                            f"{fecha.strftime('%d/%m/%Y')} {hora_inicio.strftime('%H:%M')} — {msg}"
                        )
                        continue

                    # ── Resolver vínculo ───────────────────────────
                    mensualidad_obj = None
                    proyecto_obj    = None
                    if tipo_agenda == 'mensualidad' and vinculo_id:
                        mensualidad_obj = Mensualidad.objects.filter(id=vinculo_id).first()
                    elif tipo_agenda == 'proyecto' and vinculo_id:
                        proyecto_obj = Proyecto.objects.filter(id=vinculo_id).first()

                    # ── Determinar monto ───────────────────────────
                    # Mensualidad / Proyecto → 0 (el pago es del vínculo)
                    # Normal → costo_sesion del PacienteServicio del paciente
                    if tipo_agenda in ('mensualidad', 'proyecto'):
                        monto_sesion = Decimal('0.00')
                    else:
                        try:
                            ps = PacienteServicio.objects.get(
                                paciente=paciente,
                                servicio=servicio,
                            )
                            monto_sesion = ps.costo_sesion or Decimal('0.00')
                        except PacienteServicio.DoesNotExist:
                            monto_sesion = Decimal('0.00')

                    try:
                        sesion = Sesion(
                            paciente         = paciente,
                            servicio         = servicio,
                            profesional      = profesional,
                            sucursal         = sucursal,
                            mensualidad      = mensualidad_obj,
                            proyecto         = proyecto_obj if hasattr(Sesion, 'proyecto') else None,
                            fecha            = fecha,
                            hora_inicio      = hora_inicio,
                            hora_fin         = hora_fin,
                            duracion_minutos = duracion,
                            estado           = 'programada',
                            monto_cobrado    = monto_sesion,
                            creada_por       = request.user,
                            modificada_por   = request.user,
                        )
                        if perm_grupales:
                            sesion._permitir_sesiones_grupales = True
                        sesion.save()
                        creadas += 1
                    except (ValidationError, Exception) as e:
                        omitidas += 1
                        errores.append(
                            f"{fecha.strftime('%d/%m/%Y')} {hora_inicio.strftime('%H:%M')} "
                            f"— Error al guardar: {str(e)[:80]}"
                        )

        return JsonResponse({
            'success':  True,
            'creadas':  creadas,
            'omitidas': omitidas,
            'errores':  errores[:10],
            'redirect': f"/agenda/?paciente={paciente_id}",
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
@login_required
def api_pacientes_sucursal_json(request):
    """
    API JSON: devuelve pacientes activos de una sucursal.
    Usado por el formulario de patrón semanal.
    GET param: sucursal (id)
    """
    sucursal_id = request.GET.get('sucursal', '').strip()
    if not sucursal_id:
        return JsonResponse({'pacientes': []})
    try:
        pacientes = (
            Paciente.objects
            .filter(sucursales__id=sucursal_id, estado='activo')
            .distinct()
            .order_by('nombre', 'apellido')
            .values('id', 'nombre', 'apellido')
        )
        data = [{'id': p['id'], 'nombre': f"{p['nombre']} {p['apellido']}".strip()}
                for p in pacientes]
        return JsonResponse({'pacientes': data})
    except Exception as e:
        return JsonResponse({'pacientes': [], 'error': str(e)})


@login_required
def api_vinculos_paciente(request):
    """
    API JSON: devuelve mensualidades o proyectos activos del paciente.
    GET params: paciente (id), tipo ('mensualidad' | 'proyecto')
    """
    paciente_id = request.GET.get('paciente','').strip()
    tipo        = request.GET.get('tipo','').strip()
    if not paciente_id or tipo not in ('mensualidad','proyecto'):
        return JsonResponse({'items':[]})
    try:
        paciente = get_object_or_404(Paciente, id=paciente_id)
        if tipo == 'mensualidad':
            qs = Mensualidad.objects.filter(
                paciente=paciente, estado='activa'
            ).order_by('-anio','-mes')
            MESES = ['','Enero','Febrero','Marzo','Abril','Mayo','Junio',
                     'Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre']
            items = [{'id':m.id, 'label':f"{MESES[m.mes]} {m.anio} — {m.codigo}", 'mes':m.mes, 'anio':m.anio} for m in qs]
        else:
            qs = Proyecto.objects.filter(
                paciente=paciente, estado__in=['planificado','en_progreso']
            ).order_by('-fecha_inicio')
            items = [{'id':p.id, 'label':f"{p.codigo} — {p.nombre}"} for p in qs]
        return JsonResponse({'items': items})
    except Exception as e:
        return JsonResponse({'items':[], 'error':str(e)})

# ============================================================
# AGREGAR AL FINAL DE agenda/views.py
# ============================================================


@login_required
@solo_sus_sucursales
def agregar_servicio_mensualidad(request, mensualidad_id):
    """
    Agrega un nuevo ServicioProfesionalMensualidad a una mensualidad existente.

    Servicios disponibles  → PacienteServicio activos del paciente
    Profesionales disp.    → Profesional activo + tiene el servicio + está en la sucursal
    """
    mensualidad = get_object_or_404(
        Mensualidad.objects.select_related('paciente', 'sucursal'),
        id=mensualidad_id
    )

    # Verificar permisos de sucursal
    sucursales_usuario = request.sucursales_usuario
    if sucursales_usuario is not None:
        if not sucursales_usuario.filter(id=mensualidad.sucursal.id).exists():
            messages.error(request, '❌ No tienes permiso para modificar esta mensualidad')
            return redirect('agenda:detalle_mensualidad', mensualidad_id=mensualidad_id)

    # Solo mensualidades activas o pausadas pueden modificarse
    if mensualidad.estado in ('completada', 'cancelada'):
        messages.error(request, '❌ No se puede modificar una mensualidad completada o cancelada')
        return redirect('agenda:detalle_mensualidad', mensualidad_id=mensualidad_id)

    if request.method != 'POST':
        return redirect('agenda:detalle_mensualidad', mensualidad_id=mensualidad_id)

    servicio_id    = request.POST.get('servicio_id', '').strip()
    profesional_id = request.POST.get('profesional_id', '').strip()

    if not servicio_id or not profesional_id:
        messages.error(request, '❌ Debes seleccionar un servicio y un profesional')
        return redirect('agenda:detalle_mensualidad', mensualidad_id=mensualidad_id)

    try:
        # 1. Validar que el servicio pertenece al paciente (está en PacienteServicio activo)
        paciente_servicio = PacienteServicio.objects.filter(
            paciente=mensualidad.paciente,
            servicio_id=servicio_id,
            activo=True
        ).select_related('servicio').first()

        if not paciente_servicio:
            messages.error(request, '❌ El servicio seleccionado no está asignado a este paciente')
            return redirect('agenda:detalle_mensualidad', mensualidad_id=mensualidad_id)

        # 2. Validar que el profesional atiende ese servicio en esa sucursal
        profesional_valido = Profesional.objects.filter(
            id=profesional_id,
            activo=True,
            sucursales=mensualidad.sucursal,
            servicios__id=servicio_id
        ).exists()

        if not profesional_valido:
            messages.error(request, '❌ El profesional seleccionado no está disponible para este servicio en esta sucursal')
            return redirect('agenda:detalle_mensualidad', mensualidad_id=mensualidad_id)

        # 3. Verificar que no existe ya ese servicio en la mensualidad
        ya_existe = ServicioProfesionalMensualidad.objects.filter(
            mensualidad=mensualidad,
            servicio_id=servicio_id
        ).exists()

        if ya_existe:
            messages.warning(request, '⚠️ Ese servicio ya está incluido en esta mensualidad')
            return redirect('agenda:detalle_mensualidad', mensualidad_id=mensualidad_id)

        # 4. Crear
        ServicioProfesionalMensualidad.objects.create(
            mensualidad=mensualidad,
            servicio_id=servicio_id,
            profesional_id=profesional_id,
        )

        profesional_obj    = Profesional.objects.get(id=profesional_id)
        profesional_nombre = f"{profesional_obj.nombre} {profesional_obj.apellido}".strip()
        servicio_nombre    = paciente_servicio.servicio.nombre

        messages.success(
            request,
            f'✅ Servicio "{servicio_nombre}" con {profesional_nombre} agregado correctamente'
        )

    except Exception as e:
        messages.error(request, f'❌ Error al agregar el servicio: {str(e)}')

    return redirect('agenda:detalle_mensualidad', mensualidad_id=mensualidad_id)


@login_required
def api_servicios_disponibles_mensualidad(request):
    """
    API JSON: Retorna los servicios que el paciente tiene en PacienteServicio (activos)
    que todavía NO están en la mensualidad, junto con los profesionales disponibles
    para cada uno en la sucursal de la mensualidad.

    GET params:
        paciente_id    : ID del paciente
        mensualidad_id : ID de la mensualidad

    Respuesta:
        {
          "servicios": [
            {
              "id": 3,
              "nombre": "Terapia Ocupacional",
              "profesionales": [
                { "id": 7, "nombre": "Ana López" }
              ]
            }
          ]
        }
    """
    paciente_id    = request.GET.get('paciente_id', '').strip()
    mensualidad_id = request.GET.get('mensualidad_id', '').strip()

    sucursal_id = request.GET.get('sucursal_id', '').strip()

    # Necesita paciente Y (mensualidad_id O sucursal_id)
    if not paciente_id or (not mensualidad_id and not sucursal_id):
        return JsonResponse({'servicios': [], 'error': 'Faltan parámetros requeridos (paciente_id + mensualidad_id o sucursal_id)'}, status=400)

    try:
        # Resolver sucursal
        if mensualidad_id:
            mensualidad = get_object_or_404(Mensualidad, id=mensualidad_id)
            sucursal    = mensualidad.sucursal
        else:
            from servicios.models import Sucursal as _Sucursal
            sucursal    = get_object_or_404(_Sucursal, id=sucursal_id)
            mensualidad = None

        # IDs de servicios que ya están en la mensualidad (excluirlos)
        # Solo excluir servicios ya en mensualidad si se pasó mensualidad_id
        servicios_ya_agregados = set()
        if mensualidad_id and mensualidad:
            servicios_ya_agregados = set(
                ServicioProfesionalMensualidad.objects.filter(
                    mensualidad=mensualidad
                ).values_list('servicio_id', flat=True)
            )

        # Servicios activos del paciente que NO están ya en la mensualidad
        paciente_servicios = PacienteServicio.objects.filter(
            paciente_id=paciente_id,
            activo=True,
        ).select_related('servicio').filter(
            servicio__activo=True
        ).exclude(
            servicio_id__in=servicios_ya_agregados
        ).order_by('servicio__nombre')

        servicios_lista = []
        for ps in paciente_servicios:
            # Profesionales que atienden este servicio en la sucursal de la mensualidad
            profesionales = Profesional.objects.filter(
                activo=True,
                sucursales=sucursal,
                servicios=ps.servicio
            ).distinct().order_by('nombre', 'apellido')

            # Solo incluir el servicio si tiene al menos un profesional disponible
            if profesionales.exists():
                servicios_lista.append({
                    'id': ps.servicio.id,
                    'nombre': ps.servicio.nombre,
                    'profesionales': [
                        {
                            'id': p.id,
                            'nombre': f"{p.nombre} {p.apellido}".strip()
                        }
                        for p in profesionales
                    ]
                })

        return JsonResponse({'servicios': servicios_lista})

    except Exception as e:
        return JsonResponse({'servicios': [], 'error': str(e)}, status=500)

# ══════════════════════════════════════════════════════════════
# PERMISOS DE EDICIÓN — Vistas y funciones de servicio
# ══════════════════════════════════════════════════════════════

_staff_required = user_passes_test(lambda u: u.is_staff or u.is_superuser)


@login_required
@_staff_required
def lista_permisos_edicion(request):
    """Lista todos los permisos con filtros y estadísticas."""
    from django.utils import timezone

    qs = PermisoEdicionSesion.objects.select_related('profesional', 'otorgado_por').all()

    filtro_profesional = request.GET.get('profesional', '')
    filtro_estado      = request.GET.get('estado', '')
    filtro_mes         = request.GET.get('mes', '')

    if filtro_profesional:
        qs = qs.filter(profesional_id=filtro_profesional)

    if filtro_estado == 'activo':
        ahora = timezone.now()
        qs = qs.filter(valido_desde__lte=ahora, valido_hasta__gte=ahora, usado=False)
    elif filtro_estado == 'pendiente':
        qs = qs.filter(valido_desde__gt=timezone.now())
    elif filtro_estado == 'expirado':
        qs = qs.filter(valido_hasta__lt=timezone.now(), usado=False)
    elif filtro_estado == 'usado':
        qs = qs.filter(usado=True)

    if filtro_mes:
        try:
            anio, mes = filtro_mes.split('-')
            qs = qs.filter(fecha_creacion__year=anio, fecha_creacion__month=mes)
        except ValueError:
            pass

    # Estadísticas globales (sin filtros)
    ahora = timezone.now()
    todos = PermisoEdicionSesion.objects.all()
    stats = {
        'activos':    todos.filter(valido_desde__lte=ahora, valido_hasta__gte=ahora, usado=False).count(),
        'pendientes': todos.filter(valido_desde__gt=ahora).count(),
        'usados':     todos.filter(usado=True).count(),
        'expirados':  todos.filter(valido_hasta__lt=ahora, usado=False).count(),
    }

    paginator = Paginator(qs, 20)
    page      = request.GET.get('page', 1)
    permisos  = paginator.get_page(page)

    profesionales = Profesional.objects.filter(activo=True).order_by('nombre')

    return render(request, 'agenda/permisos_edicion.html', {
        'permisos':           permisos,
        'stats':              stats,
        'profesionales':      profesionales,
        'filtro_profesional': filtro_profesional,
        'filtro_estado':      filtro_estado,
        'filtro_mes':         filtro_mes,
    })


@login_required
@_staff_required
def crear_permiso_edicion(request):
    """Crea un nuevo permiso de edición."""
    from .forms import PermisoEdicionForm

    if request.method == 'POST':
        form = PermisoEdicionForm(request.POST)
        if form.is_valid():
            permiso = form.save(commit=False)
            permiso.otorgado_por = request.user
            permiso.save()
            messages.success(
                request,
                f"✅ Permiso creado para {permiso.profesional.nombre} "
                f"{permiso.profesional.apellido} — válido hasta "
                f"{permiso.valido_hasta.strftime('%d/%m/%Y %H:%M')}."
            )
            return redirect('agenda:lista_permisos_edicion')
    else:
        form = PermisoEdicionForm()

    profesionales = Profesional.objects.filter(activo=True).order_by('nombre')
    return render(request, 'agenda/form_permiso_edicion.html', {
        'form':           form,
        'profesionales':  profesionales,
        'permiso':        None,
    })


@login_required
@_staff_required
def editar_permiso_edicion(request, permiso_id):
    """Edita un permiso existente (solo si no fue usado todavía)."""
    from .forms import PermisoEdicionForm

    permiso = get_object_or_404(PermisoEdicionSesion, id=permiso_id)

    if permiso.usado:
        messages.error(request, "❌ No se puede editar un permiso que ya fue utilizado.")
        return redirect('agenda:lista_permisos_edicion')

    if request.method == 'POST':
        form = PermisoEdicionForm(request.POST, instance=permiso)
        if form.is_valid():
            form.save()
            messages.success(request, "✅ Permiso actualizado correctamente.")
            return redirect('agenda:lista_permisos_edicion')
    else:
        form = PermisoEdicionForm(instance=permiso)

    profesionales = Profesional.objects.filter(activo=True).order_by('nombre')
    return render(request, 'agenda/form_permiso_edicion.html', {
        'form':          form,
        'profesionales': profesionales,
        'permiso':       permiso,
    })


@login_required
@_staff_required
def revocar_permiso_edicion(request, permiso_id):
    """Elimina (revoca) un permiso."""
    if request.method == 'POST':
        permiso = get_object_or_404(PermisoEdicionSesion, id=permiso_id)
        nombre = f"{permiso.profesional.nombre} {permiso.profesional.apellido}"
        permiso.delete()
        messages.success(request, f"🗑️ Permiso de {nombre} revocado correctamente.")
    return redirect('agenda:lista_permisos_edicion')


# ── Funciones de servicio reutilizables ──

def profesional_puede_editar_sesion(profesional, sesion):
    """
    Verifica si un profesional puede editar una sesión específica.
    Retorna: (puede: bool, campos_permitidos: list, motivo: str)
    """
    from django.utils import timezone as tz

    hoy = date.today()

    # Siempre puede editar sesiones del día actual
    if sesion.fecha == hoy:
        return True, ['estado', 'notas_sesion', 'observaciones', 'hora_inicio', 'hora_fin'], "Sesión del día actual"

    permiso = PermisoEdicionSesion.objects.filter(
        profesional=profesional,
        fecha_sesion_desde__lte=sesion.fecha,
        fecha_sesion_hasta__gte=sesion.fecha,
        valido_desde__lte=tz.now(),
        valido_hasta__gte=tz.now(),
        usado=False,
    ).first()

    if not permiso:
        return False, [], "Sin permiso para editar sesiones de otra fecha"

    campos = []
    if permiso.puede_editar_estado: campos.append('estado')
    if permiso.puede_editar_notas:  campos.append('notas_sesion')
    if permiso.puede_editar_otros_campos:
        campos += ['observaciones', 'hora_inicio', 'hora_fin']

    return True, campos, f"Permiso otorgado por {permiso.otorgado_por}"


def registrar_uso_permiso(profesional, sesion):
    """Marca el permiso como usado una vez que el profesional edita la sesión."""
    from django.utils import timezone as tz

    permiso = PermisoEdicionSesion.objects.filter(
        profesional=profesional,
        fecha_sesion_desde__lte=sesion.fecha,
        fecha_sesion_hasta__gte=sesion.fecha,
        valido_desde__lte=tz.now(),
        valido_hasta__gte=tz.now(),
        usado=False,
    ).first()

    if permiso:
        permiso.usado     = True
        permiso.fecha_uso = tz.now()
        permiso.save(update_fields=['usado', 'fecha_uso'])

def calcular_racha_semanas(paciente):
    """Cuenta semanas consecutivas hacia atrás con al menos 1 sesión realizada."""
    from datetime import date, timedelta
    hoy = date.today()
    semana_actual = hoy - timedelta(days=hoy.weekday())  # lunes de esta semana
    racha = 0
    for i in range(52):
        inicio = semana_actual - timedelta(weeks=i)
        fin = inicio + timedelta(days=6)
        tiene = Sesion.objects.filter(
            paciente=paciente,
            fecha__range=(inicio, fin),
            estado='realizada'
        ).exists()
        if tiene:
            racha += 1
        else:
            break
    return racha

def mi_calendario_magico(request, paciente_id):
    paciente = get_object_or_404(Paciente, id=paciente_id)
    todas_sesiones = Sesion.objects.filter(
        paciente=paciente
    ).select_related('servicio', 'profesional', 'sucursal', 'mensualidad', 'proyecto'
    ).order_by('fecha', 'hora_inicio')

    today = date.today()
    mes_actual = todas_sesiones.filter(fecha__year=today.year, fecha__month=today.month)

    # Conteos por estado
    realizadas_count      = todas_sesiones.filter(estado='realizada').count()
    retraso_count         = todas_sesiones.filter(estado='realizada_retraso').count()
    falta_count           = todas_sesiones.filter(estado='falta').count()
    permiso_count         = todas_sesiones.filter(estado='permiso').count()
    cancelada_count       = todas_sesiones.filter(estado='cancelada').count()
    reprogramada_count    = todas_sesiones.filter(estado='reprogramada').count()
    proximas_count        = todas_sesiones.filter(fecha__gte=today, estado__in=['programada', 'agendada', 'pendiente']).count()

    # Progreso del mes (realizada + realizada_retraso cuentan como completadas)
    mes_realizadas = mes_actual.filter(estado__in=['realizada', 'realizada_retraso']).count()
    mes_total      = mes_actual.count()
    pct            = int((mes_realizadas / mes_total * 100) if mes_total > 0 else 0)

    # Próxima sesión
    proxima = todas_sesiones.filter(
        fecha__gte=today,
        estado__in=['programada', 'agendada', 'pendiente']
    ).first()

    return render(request, 'agenda/mi_calendario_magico.html', {
        'paciente':                  paciente,
        'user_id':                   request.user.id,
        'tema_calendario':           getattr(getattr(request.user, 'perfil', None), 'tema_calendario', ''),
        'todas_sesiones':            todas_sesiones,
        'total_sesiones':            todas_sesiones.count(),
        # Stats individuales
        'sesiones_realizadas_count': realizadas_count,
        'sesiones_retraso_count':    retraso_count,
        'sesiones_falta_count':      falta_count,
        'sesiones_permiso_count':    permiso_count,
        'sesiones_canceladas_count': cancelada_count,
        'sesiones_reprog_count':     reprogramada_count,
        'sesiones_proximas_count':   proximas_count,
        # Progreso mes
        'sesiones_mes_realizadas':   mes_realizadas,
        'sesiones_mes_total':        mes_total,
        'pct_mes':                   pct,
        'proxima_sesion':            proxima,
        'racha_semanas':             calcular_racha_semanas(paciente),
    })

@login_required
@require_POST
def guardar_tema_calendario(request):
    """Guarda el tema del calendario mágico en el perfil del usuario."""
    try:
        data = json.loads(request.body)
        tema = data.get('tema', '').strip()
        temas_validos = [
            'dino', 'space', 'ocean', 'hero', 'fantasy',
            'magic', 'sunny', 'nature', 'candy', 'sky'
        ]
        if tema not in temas_validos:
            return JsonResponse({'ok': False, 'error': 'Tema no válido'}, status=400)

        if hasattr(request.user, 'perfil'):
            request.user.perfil.tema_calendario = tema
            request.user.perfil.save(update_fields=['tema_calendario'])

        return JsonResponse({'ok': True})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)

@login_required
def mis_informes_evolucion(request):
    """
    Vista del ROL PROFESIONAL: lista los pacientes propios
    para que el profesional elija a cuál ver el informe de evolución.

    Solo accesible para usuarios con perfil profesional.
    Redirige a la agenda si no se encuentra el profesional.
    """
    profesional = get_profesional_usuario(request.user)
    if not profesional:
        messages.error(request, '❌ No se encontró tu perfil de profesional.')
        return redirect('agenda:calendario')

    # Pacientes que han tenido al menos 1 sesión con este profesional
    from django.db.models import Count as _Count
    pacientes = (
        Paciente.objects
        .filter(sesiones__profesional=profesional)
        .distinct()
        .order_by('nombre', 'apellido')
        .annotate(
            sesiones_count=_Count(
                'sesiones',
                filter=Q(sesiones__profesional=profesional)
            )
        )
    )

    return render(request, 'agenda/mis_informes_evolucion.html', {
        'profesional': profesional,
        'pacientes':   pacientes,
    })


@login_required
def informe_evolucion_profesional(request, paciente_id):
    """
    Vista del ROL PROFESIONAL: informe de evolución de UN paciente,
    filtrando automáticamente solo las sesiones del profesional logueado.

    GET  → muestra el formulario (sin filtro de profesional, ya está fijo)
    POST → aplica filtros de servicio/fechas/estados y muestra resultados
    """
    profesional = get_profesional_usuario(request.user)
    if not profesional:
        messages.error(request, '❌ No se encontró tu perfil de profesional.')
        return redirect('agenda:calendario')

    paciente = get_object_or_404(Paciente, pk=paciente_id)

    # Verificar que este profesional tenga al menos 1 sesión con el paciente
    tiene_sesiones = Sesion.objects.filter(
        paciente=paciente,
        profesional=profesional
    ).exists()
    if not tiene_sesiones:
        messages.error(
            request,
            f'❌ No tenés sesiones registradas con {paciente.nombre_completo}.'
        )
        return redirect('agenda:mis_informes_evolucion')

    # Servicios que este profesional brindó a este paciente
    servicios = TipoServicio.objects.filter(
        sesiones__paciente=paciente,
        sesiones__profesional=profesional
    ).distinct().order_by('nombre')

    ESTADOS = [
        ('programada',        'Programada'),
        ('realizada',         'Realizada'),
        ('realizada_retraso', 'Realizada con Retraso'),
        ('falta',             'Falta sin Aviso'),
        ('permiso',           'Permiso (con aviso)'),
        ('cancelada',         'Cancelada'),
        ('reprogramada',      'Reprogramada'),
    ]

    grupos = None
    filtros = {}
    total_sesiones = 0

    if request.method == 'POST':
        servicio_id     = request.POST.get('servicio', '').strip()
        fecha_desde_str = request.POST.get('fecha_desde', '').strip()
        fecha_hasta_str = request.POST.get('fecha_hasta', '').strip()
        estados_sel     = request.POST.getlist('estados')

        filtros = {
            'servicio_id':  servicio_id,
            'fecha_desde':  fecha_desde_str,
            'fecha_hasta':  fecha_hasta_str,
            'estados':      estados_sel,
        }

        # Base: solo sesiones de este profesional con este paciente
        qs = Sesion.objects.filter(
            paciente=paciente,
            profesional=profesional
        ).select_related('profesional', 'servicio', 'sucursal')

        if servicio_id:
            qs = qs.filter(servicio_id=servicio_id)

        if fecha_desde_str:
            try:
                fd = datetime.strptime(fecha_desde_str, '%Y-%m-%d').date()
                qs = qs.filter(fecha__gte=fd)
                filtros['fecha_desde_obj'] = fd
            except ValueError:
                pass

        if fecha_hasta_str:
            try:
                fh = datetime.strptime(fecha_hasta_str, '%Y-%m-%d').date()
                qs = qs.filter(fecha__lte=fh)
                filtros['fecha_hasta_obj'] = fh
            except ValueError:
                pass

        if estados_sel:
            qs = qs.filter(estado__in=estados_sel)

        # Ordenar por servicio → fecha → hora
        qs = qs.order_by('servicio__nombre', 'fecha', 'hora_inicio')

        # Agrupar solo por servicio (el profesional ya está fijo)
        grupos = []
        for serv, sesiones_serv in groupby(qs, key=lambda s: s.servicio):
            lista = list(sesiones_serv)
            total_sesiones += len(lista)
            grupos.append({
                'servicio': serv,
                'sesiones': lista,
            })

    return render(request, 'agenda/informe_evolucion_profesional.html', {
        'paciente':       paciente,
        'profesional':    profesional,
        'servicios':      servicios,
        'estados':        ESTADOS,
        'grupos':         grupos,
        'filtros':        filtros,
        'total_sesiones': total_sesiones,
    })


@login_required
def generar_pdf_informe_evolucion_profesional(request, paciente_id):
    """
    Genera el PDF del informe de evolución para el rol profesional.
    Usa la firma real de generar_informe_evolucion_pdf:
        (paciente, sesiones, profesional_nombre, servicio_nombre,
         fecha_desde, fecha_hasta, estados_filtro)
    """
    from agenda.informe_evolucion_pdf import generar_informe_evolucion_pdf

    profesional = get_profesional_usuario(request.user)
    if not profesional:
        messages.error(request, '❌ No se encontró tu perfil de profesional.')
        return redirect('agenda:calendario')

    paciente = get_object_or_404(Paciente, pk=paciente_id)

    # ── Leer filtros desde GET ────────────────────────────────
    servicio_id     = request.GET.get('servicio', '').strip()
    fecha_desde_str = request.GET.get('fecha_desde', '').strip()
    fecha_hasta_str = request.GET.get('fecha_hasta', '').strip()
    estados_sel     = request.GET.getlist('estados')

    # ── Construir queryset ────────────────────────────────────
    qs = Sesion.objects.filter(
        paciente=paciente,
        profesional=profesional
    ).select_related('profesional', 'servicio', 'sucursal')

    if servicio_id:
        qs = qs.filter(servicio_id=servicio_id)

    fecha_desde = None
    if fecha_desde_str:
        try:
            fecha_desde = datetime.strptime(fecha_desde_str, '%Y-%m-%d').date()
            qs = qs.filter(fecha__gte=fecha_desde)
        except ValueError:
            pass

    fecha_hasta = None
    if fecha_hasta_str:
        try:
            fecha_hasta = datetime.strptime(fecha_hasta_str, '%Y-%m-%d').date()
            qs = qs.filter(fecha__lte=fecha_hasta)
        except ValueError:
            pass

    if estados_sel:
        qs = qs.filter(estado__in=estados_sel)

    # El planificador interno ordena por profesional→servicio→fecha
    qs = qs.order_by(
        'profesional__nombre', 'profesional__apellido',
        'servicio__nombre',
        'fecha', 'hora_inicio'
    )

    # ── Nombres para el encabezado del PDF ───────────────────
    profesional_nombre = f"{profesional.nombre} {profesional.apellido}".strip()

    # Si se filtró por un servicio específico, mostrarlo; si no, vacío
    servicio_nombre = ""
    if servicio_id:
        try:
            servicio_nombre = TipoServicio.objects.get(pk=servicio_id).nombre
        except TipoServicio.DoesNotExist:
            pass

    # ── Generar PDF ───────────────────────────────────────────
    buffer = generar_informe_evolucion_pdf(
        paciente=paciente,
        sesiones=qs,
        profesional_nombre=profesional_nombre,
        servicio_nombre=servicio_nombre,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        estados_filtro=estados_sel,
    )

    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = (
        f'inline; filename="informe_evolucion_'
        f'{paciente.apellido}_{paciente.nombre}_'
        f'{profesional.apellido}.pdf"'
    )
    return response

@login_required
def sesiones_sucursal_profesional(request):
    """
    Vista para el rol profesional.
    Muestra las sesiones del día en su(s) sucursal(es).
    Permite navegar entre días con flechas.
    Solo muestra: paciente, servicio, profesional, hora inicio/fin y duración.
    """
    from datetime import date, timedelta

    # ── 1. Verificar que el usuario sea profesional ──
    if not hasattr(request.user, 'perfil') or not request.user.perfil.es_profesional():
        messages.error(request, '⚠️ Esta sección es solo para profesionales.')
        return redirect('agenda:calendario')

    # ── 2. Obtener el profesional vinculado al usuario ──
    try:
        profesional = Profesional.objects.get(user=request.user)
    except Profesional.DoesNotExist:
        messages.error(request, '❌ No hay un profesional vinculado a tu cuenta. Contacta al administrador.')
        return redirect('agenda:calendario')

    # ── 3. Obtener sucursales del profesional ──
    sucursales = profesional.sucursales.all()
    if not sucursales.exists():
        messages.warning(request, '⚠️ No tienes sucursales asignadas. Contacta al administrador.')
        return redirect('agenda:calendario')

    sucursal_nombre = (
        sucursales.first().nombre
        if sucursales.count() == 1
        else ", ".join(s.nombre for s in sucursales)
    )

    # ── 4. Fecha del día a visualizar ──
    fecha_str = request.GET.get('fecha', '')
    if fecha_str:
        try:
            fecha_actual = date.fromisoformat(fecha_str)
        except ValueError:
            fecha_actual = date.today()
    else:
        fecha_actual = date.today()

    fecha_anterior = fecha_actual - timedelta(days=1)
    fecha_siguiente = fecha_actual + timedelta(days=1)
    es_hoy = (fecha_actual == date.today())

    # ── 5. Sesiones del día en las sucursales del profesional ──
    sesiones = (
        Sesion.objects
        .filter(fecha=fecha_actual, sucursal__in=sucursales)
        .select_related('paciente', 'servicio', 'profesional', 'sucursal')
        .order_by('hora_inicio')
    )

    # ── 6. Estadísticas ──
    total_sesiones = sesiones.count()
    total_minutos = sum(s.duracion_minutos for s in sesiones)
    total_profesionales = sesiones.values('profesional_id').distinct().count()

    # ── 7. Fecha en español ──
    DIAS_ES = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
    MESES_ES = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
                'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']

    fecha_display = f"{DIAS_ES[fecha_actual.weekday()]} {fecha_actual.day} de {MESES_ES[fecha_actual.month]} de {fecha_actual.year}"

    context = {
        'sesiones': sesiones,
        'profesional': profesional,
        'fecha_actual': fecha_actual,
        'fecha_anterior': fecha_anterior.isoformat(),
        'fecha_siguiente': fecha_siguiente.isoformat(),
        'fecha_display': fecha_display,
        'es_hoy': es_hoy,
        'sucursal_nombre': sucursal_nombre,
        'total_sesiones': total_sesiones,
        'total_minutos': total_minutos,
        'total_profesionales': total_profesionales,
    }
    return render(request, 'agenda/sesiones_sucursal_profesional.html', context)