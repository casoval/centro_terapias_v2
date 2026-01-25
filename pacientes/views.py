from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.db.models import Count, Q
from datetime import date
from .models import Paciente, PacienteServicio
from .forms import PacienteForm

@login_required
def lista_pacientes(request):
    """
    Lista de pacientes activos
    ✅ FILTRADO POR SUCURSAL SEGÚN ROL
    """
    # ✅ FILTRADO SEGÚN ROL DEL USUARIO
    if request.user.is_superuser:
        # Superadmin ve TODOS los pacientes
        pacientes = Paciente.objects.filter(estado='activo')
        sucursales_disponibles = None  # Todas
    elif hasattr(request.user, 'perfil'):
        if request.user.perfil.es_gerente():
            # Gerentes ven TODOS los pacientes
            pacientes = Paciente.objects.filter(estado='activo')
            sucursales_disponibles = None  # Todas
        elif request.user.perfil.es_recepcionista():
            # ✅ RECEPCIONISTAS: Solo pacientes de SUS sucursales
            mis_sucursales = request.user.perfil.sucursales.all()
            
            if mis_sucursales.exists():
                pacientes = Paciente.objects.filter(
                    estado='activo',
                    sucursales__in=mis_sucursales
                ).distinct()
                sucursales_disponibles = mis_sucursales
            else:
                # Sin sucursales asignadas = no ve nada
                pacientes = Paciente.objects.none()
                sucursales_disponibles = Paciente.objects.none()
        else:
            # Otros roles (profesionales, pacientes) no deberían estar aquí
            pacientes = Paciente.objects.none()
            sucursales_disponibles = Paciente.objects.none()
    else:
        pacientes = Paciente.objects.none()
        sucursales_disponibles = Paciente.objects.none()
    
    # Ordenamiento: Primero por nombre, luego apellido
    pacientes = pacientes.order_by('nombre', 'apellido')
    
    # Lógica de Búsqueda
    buscar = request.GET.get('q', '')
    if buscar:
        pacientes = pacientes.filter(
            Q(nombre__icontains=buscar) | 
            Q(apellido__icontains=buscar)
        )
    
    # Lógica de Filtro por Sucursal
    sucursal_id = request.GET.get('sucursal')
    if sucursal_id:
        pacientes = pacientes.filter(sucursales__id=sucursal_id)
    
    # ✅ Obtener sucursales para el filtro SEGÚN PERMISOS
    from servicios.models import Sucursal
    
    if sucursales_disponibles is None:
        # Superadmin/Gerente: Todas las sucursales activas
        sucursales = Sucursal.objects.filter(activa=True).order_by('nombre')
    elif hasattr(sucursales_disponibles, 'exists') and sucursales_disponibles.exists():
        # Recepcionista: Solo sus sucursales
        sucursales = sucursales_disponibles.filter(activa=True).order_by('nombre')
    else:
        # Sin permisos
        sucursales = Sucursal.objects.none()
    
    context = {
        'pacientes': pacientes,
        'buscar': buscar,
        'sucursales': sucursales,
        'sucursal_seleccionada': int(sucursal_id) if sucursal_id else None
    }
    return render(request, 'pacientes/lista.html', context)

@login_required
def agregar_paciente(request):
    """
    ✅ Vista para agregar nuevo paciente con formulario personalizado
    ✅ Con sincronización de usuario del sistema
    ✅ LIMITADO A SUCURSALES DEL RECEPCIONISTA
    """
    # ✅ Verificar si viene con user_id (desde crear usuario)
    user_id = request.GET.get('user_id')
    usuario_seleccionado = None
    
    if user_id:
        try:
            from django.contrib.auth.models import User
            usuario_seleccionado = User.objects.get(id=user_id)
        except User.DoesNotExist:
            messages.warning(request, '⚠️ Usuario no encontrado.')
    
    if request.method == 'POST':
        form = PacienteForm(request.POST, request.FILES, user=request.user)
        
        if form.is_valid():
            paciente = form.save()
            
            # ✅ VALIDACIÓN: Verificar que las sucursales sean permitidas
            if not request.user.is_superuser and hasattr(request.user, 'perfil'):
                if request.user.perfil.es_recepcionista():
                    mis_sucursales = request.user.perfil.sucursales.all()
                    sucursales_paciente = paciente.sucursales.all()
                    
                    # Verificar que todas las sucursales del paciente estén en las del recepcionista
                    sucursales_no_permitidas = sucursales_paciente.exclude(id__in=mis_sucursales.values_list('id', flat=True))
                    
                    if sucursales_no_permitidas.exists():
                        messages.error(
                            request,
                            '❌ No tienes permiso para asignar algunas de las sucursales seleccionadas.'
                        )
                        paciente.delete()
                        return redirect('pacientes:agregar')
            
            # ✅ SINCRONIZACIÓN: Si tiene usuario, crear/actualizar perfil
            if paciente.user:
                from core.models import PerfilUsuario
                
                perfil, created = PerfilUsuario.objects.get_or_create(
                    user=paciente.user,
                    defaults={'rol': 'paciente', 'activo': True}
                )
                
                # Vincular el paciente con el perfil
                perfil.paciente = paciente
                perfil.rol = 'paciente'
                perfil.save()
                
                messages.success(
                    request, 
                    f'✅ ¡Paciente {paciente.nombre_completo} registrado y vinculado con usuario "{paciente.user.username}"!'
                )
            else:
                messages.success(
                    request,
                    f'✅ ¡Paciente {paciente.nombre_completo} registrado exitosamente!'
                )
            
            # Redirigir al detalle del paciente
            return redirect('pacientes:detalle', pk=paciente.id)
        else:
            messages.error(
                request,
                '❌ Por favor corrige los errores en el formulario'
            )
    else:
        form = PacienteForm(user=request.user)
        
        # ✅ Pre-seleccionar usuario si viene desde crear usuario
        if usuario_seleccionado:
            form.initial['user'] = usuario_seleccionado.id
    
    # ✅ Obtener servicios disponibles (todos para todos los roles)
    from servicios.models import TipoServicio
    servicios = TipoServicio.objects.filter(activo=True).order_by('nombre')
    
    context = {
        'form': form,
        'servicios': servicios,
        'usuario_seleccionado': usuario_seleccionado,
    }
    return render(request, 'pacientes/agregar.html', context)


@login_required
def editar_paciente(request, pk):
    """
    ✅ Vista para editar paciente existente
    ✅ VALIDAR QUE RECEPCIONISTA SOLO EDITE PACIENTES DE SUS SUCURSALES
    """
    paciente = get_object_or_404(Paciente, pk=pk)
    
    # ✅ VALIDACIÓN DE ACCESO PARA RECEPCIONISTAS
    if not request.user.is_superuser and hasattr(request.user, 'perfil'):
        if request.user.perfil.es_recepcionista():
            mis_sucursales = request.user.perfil.sucursales.all()
            sucursales_paciente = paciente.sucursales.all()
            
            # Verificar que el paciente tenga al menos una sucursal del recepcionista
            if not sucursales_paciente.filter(id__in=mis_sucursales.values_list('id', flat=True)).exists():
                messages.error(
                    request,
                    '⚠️ No tienes permiso para editar este paciente (no pertenece a tus sucursales).'
                )
                return redirect('pacientes:lista')
    
    if request.method == 'POST':
        form = PacienteForm(request.POST, request.FILES, instance=paciente, user=request.user)
        
        if form.is_valid():
            # Guardar paciente
            paciente = form.save()
            
            # ✅ VALIDACIÓN: Verificar que las nuevas sucursales sean permitidas
            if not request.user.is_superuser and hasattr(request.user, 'perfil'):
                if request.user.perfil.es_recepcionista():
                    mis_sucursales = request.user.perfil.sucursales.all()
                    sucursales_paciente = paciente.sucursales.all()
                    
                    sucursales_no_permitidas = sucursales_paciente.exclude(id__in=mis_sucursales.values_list('id', flat=True))
                    
                    if sucursales_no_permitidas.exists():
                        messages.error(
                            request,
                            '❌ No puedes asignar sucursales fuera de tus permisos.'
                        )
                        return redirect('pacientes:editar', pk=pk)
            
            # ✅ SINCRONIZACIÓN: Actualizar perfil si cambió el usuario
            if paciente.user:
                from core.models import PerfilUsuario
                
                perfil, created = PerfilUsuario.objects.get_or_create(
                    user=paciente.user,
                    defaults={'rol': 'paciente', 'activo': True}
                )
                
                perfil.paciente = paciente
                perfil.rol = 'paciente'
                perfil.save()
            
            # ✅ ACTUALIZAR SERVICIOS: Primero marcar todos como inactivos
            PacienteServicio.objects.filter(paciente=paciente).update(activo=False)
            
            # ✅ Luego activar/actualizar los seleccionados
            from servicios.models import TipoServicio
            servicios = TipoServicio.objects.filter(activo=True)
            
            for servicio in servicios:
                servicio_key = f'servicio_{servicio.id}'
                
                if servicio_key in request.POST:
                    # Obtener precio personalizado
                    precio_key = f'precio_{servicio.id}'
                    precio_custom = request.POST.get(precio_key, '').strip()
                    
                    # Si está vacío o es 0, usar precio base
                    if not precio_custom or float(precio_custom or 0) == 0:
                        precio_custom = servicio.costo_base
                    else:
                        precio_custom = float(precio_custom)
                    
                    # Obtener observaciones
                    obs_key = f'obs_{servicio.id}'
                    observaciones = request.POST.get(obs_key, '').strip()
                    
                    # Actualizar o crear
                    paciente_servicio, created = PacienteServicio.objects.update_or_create(
                        paciente=paciente,
                        servicio=servicio,
                        defaults={
                            'costo_sesion': precio_custom,
                            'observaciones': observaciones,
                            'activo': True
                        }
                    )
            
            messages.success(
                request,
                f'✅ ¡Paciente {paciente.nombre_completo} actualizado correctamente!'
            )
            return redirect('pacientes:detalle', pk=paciente.id)
        else:
            messages.error(
                request,
                '❌ Por favor corrige los errores en el formulario'
            )
    else:
        form = PacienteForm(instance=paciente, user=request.user)
    
    # Obtener servicios y servicios del paciente
    from servicios.models import TipoServicio
    servicios = TipoServicio.objects.filter(activo=True).order_by('nombre')
    
    # Crear diccionario de servicios del paciente
    servicios_paciente = {}
    for ps in PacienteServicio.objects.filter(paciente=paciente):
        servicios_paciente[ps.servicio.id] = ps
    
    context = {
        'form': form,
        'paciente': paciente,
        'servicios': servicios,
        'servicios_paciente': servicios_paciente,
    }
    return render(request, 'pacientes/editar.html', context)


@login_required
def eliminar_paciente(request, pk):
    """
    ✅ Vista para eliminar o desactivar paciente
    ✅ VALIDAR PERMISOS DE RECEPCIONISTA
    """
    paciente = get_object_or_404(Paciente, pk=pk)
    
    # ✅ VALIDACIÓN DE ACCESO PARA RECEPCIONISTAS
    if not request.user.is_superuser and hasattr(request.user, 'perfil'):
        if request.user.perfil.es_recepcionista():
            mis_sucursales = request.user.perfil.sucursales.all()
            sucursales_paciente = paciente.sucursales.all()
            
            if not sucursales_paciente.filter(id__in=mis_sucursales.values_list('id', flat=True)).exists():
                messages.error(
                    request,
                    '⚠️ No tienes permiso para eliminar este paciente.'
                )
                return redirect('pacientes:lista')
    
    # ✅ Verificar si tiene datos asociados
    from agenda.models import Sesion
    
    sesiones_count = Sesion.objects.filter(paciente=paciente).count()
    servicios_count = PacienteServicio.objects.filter(paciente=paciente).count()
    
    # Verificar proyectos (si existen en tu sistema)
    proyectos_count = 0
    try:
        proyectos_count = paciente.proyectos.count()
    except:
        pass
    
    tiene_datos = (sesiones_count > 0 or servicios_count > 0 or proyectos_count > 0)
    
    datos_relacionados = {
        'sesiones': sesiones_count,
        'servicios': servicios_count,
        'proyectos': proyectos_count,
    }
    
    if request.method == 'POST':
        accion = request.POST.get('accion')
        
        if accion == 'desactivar':
            # ✅ DESACTIVAR: Cambiar estado a inactivo
            paciente.estado = 'inactivo'
            paciente.save()
            
            messages.success(
                request,
                f'🔒 Paciente {paciente.nombre_completo} desactivado correctamente. '
                f'Los datos se mantienen intactos y puede reactivarse cuando sea necesario.'
            )
            return redirect('pacientes:lista')
            
        elif accion == 'eliminar' and not tiene_datos:
            # ✅ ELIMINAR: Solo si NO tiene datos asociados
            nombre_completo = paciente.nombre_completo
            
            # Desvincular usuario si existe
            if paciente.user:
                from core.models import PerfilUsuario
                try:
                    perfil = paciente.user.perfil
                    perfil.paciente = None
                    perfil.save()
                except:
                    pass
            
            # Eliminar paciente
            paciente.delete()
            
            messages.success(
                request,
                f'🗑️ Paciente {nombre_completo} eliminado permanentemente del sistema.'
            )
            return redirect('pacientes:lista')
        else:
            messages.error(
                request,
                '❌ No se puede eliminar este paciente porque tiene datos asociados. '
                'Usa la opción de DESACTIVAR.'
            )
    
    context = {
        'paciente': paciente,
        'tiene_datos': tiene_datos,
        'datos_relacionados': datos_relacionados,
    }
    return render(request, 'pacientes/eliminar.html', context)

@login_required
def detalle_paciente(request, pk):
    """
    Detalle de un paciente con profesionales y sucursales
    ✅ VALIDAR ACCESO PARA RECEPCIONISTAS
    """
    paciente = get_object_or_404(Paciente, pk=pk)
    
    # ✅ VALIDACIÓN DE ACCESO PARA RECEPCIONISTAS
    if not request.user.is_superuser and hasattr(request.user, 'perfil'):
        if request.user.perfil.es_recepcionista():
            mis_sucursales = request.user.perfil.sucursales.all()
            sucursales_paciente = paciente.sucursales.all()
            
            if not sucursales_paciente.filter(id__in=mis_sucursales.values_list('id', flat=True)).exists():
                messages.error(
                    request,
                    '⚠️ No tienes permiso para ver este paciente.'
                )
                return redirect('pacientes:lista')
    
    # Últimas 10 sesiones
    sesiones = paciente.sesiones.all().order_by('-fecha', '-hora_inicio')[:10]
    
    # ✅ Servicios contratados
    servicios = PacienteServicio.objects.filter(
        paciente=paciente,
        activo=True
    ).select_related('servicio')
    
    # ✅ Obtener sucursales donde ha sido atendido
    from agenda.models import Sesion
    sucursales_ids = Sesion.objects.filter(
        paciente=paciente
    ).values_list('sucursal_id', flat=True).distinct()
    
    from servicios.models import Sucursal
    sucursales = Sucursal.objects.filter(
        id__in=sucursales_ids
    ).order_by('nombre')
    
    # ✅ Obtener profesionales que le han atendido
    profesionales_ids = Sesion.objects.filter(
        paciente=paciente
    ).values_list('profesional_id', flat=True).distinct()
    
    from profesionales.models import Profesional
    profesionales = Profesional.objects.filter(
        id__in=profesionales_ids
    ).prefetch_related('servicios', 'sucursales')
    
    # ✅ Agregar estadísticas por profesional
    profesionales_data = []
    for profesional in profesionales:
        # Contar sesiones totales con este profesional
        total_sesiones = Sesion.objects.filter(
            paciente=paciente,
            profesional=profesional
        ).count()
        
        # Contar sesiones realizadas
        sesiones_realizadas = Sesion.objects.filter(
            paciente=paciente,
            profesional=profesional,
            estado__in=['realizada', 'realizada_retraso']
        ).count()
        
        # Próxima sesión con este profesional
        proxima_sesion = Sesion.objects.filter(
            paciente=paciente,
            profesional=profesional,
            estado__in=['programada', 'retraso', 'con_retraso'],
            fecha__gte=date.today()
        ).order_by('fecha', 'hora_inicio').first()
        
        # Servicios únicos que este profesional da a este paciente
        servicios_ids = Sesion.objects.filter(
            paciente=paciente,
            profesional=profesional
        ).values_list('servicio_id', flat=True).distinct()
        
        from servicios.models import TipoServicio
        servicios_profesional = TipoServicio.objects.filter(
            id__in=servicios_ids
        ).values_list('nombre', flat=True)
        
        profesionales_data.append({
            'profesional': profesional,
            'total_sesiones': total_sesiones,
            'sesiones_realizadas': sesiones_realizadas,
            'proxima_sesion': proxima_sesion,
            'servicios': list(servicios_profesional),
        })
    
    context = {
        'paciente': paciente,
        'sesiones': sesiones,
        'servicios': servicios,
        'sucursales': sucursales,
        'profesionales_data': profesionales_data,
    }
    return render(request, 'pacientes/detalle.html', context)

@login_required
def mis_sesiones(request):
    """
    Vista EXCLUSIVA para que los pacientes vean sus propias sesiones
    ✅ Nadie más puede acceder aquí
    """
    # ✅ Verificar que el usuario sea paciente
    if not hasattr(request.user, 'perfil') or not request.user.perfil.es_paciente:
        messages.error(request, '⚠️ Esta sección es solo para pacientes.')
        return redirect('core:dashboard')
    
    # ✅ Obtener el paciente vinculado
    paciente = request.user.perfil.paciente
    
    if not paciente:
        messages.error(request, '❌ No hay un paciente vinculado a tu cuenta.')
        return redirect('core:dashboard')
    
    # Importar modelo Sesion
    from agenda.models import Sesion
    
    # ✅ IMPORTANTE: Solo mostrar sesiones del paciente actual
    sesiones = Sesion.objects.filter(
        paciente=paciente  # ← Solo SUS sesiones
    ).select_related(
        'servicio', 'profesional', 'sucursal', 'proyecto'
    ).order_by('-fecha', '-hora_inicio')
    
    # Separar sesiones por estado
    # ✅ Sesiones próximas (futuras programadas)
    sesiones_proximas = sesiones.filter(
        estado__in=['programada', 'retraso', 'con_retraso'],
        fecha__gte=date.today()
    ).order_by('fecha', 'hora_inicio')
    
    # ✅ Sesiones realizadas (con y sin retraso)
    sesiones_realizadas = sesiones.filter(
        estado__in=['realizada', 'realizada_retraso']
    )
    
    # ✅ Sesiones canceladas y faltas
    sesiones_canceladas = sesiones.filter(
        estado__in=['cancelada', 'falta']
    )
    
    # ✅ NUEVA: Sesiones con permiso
    sesiones_permisos = sesiones.filter(
        estado='permiso'
    ).order_by('fecha', 'hora_inicio')
    
    context = {
        'paciente': paciente,
        'sesiones_proximas': sesiones_proximas,
        'sesiones_realizadas': sesiones_realizadas,
        'sesiones_canceladas': sesiones_canceladas,
        'sesiones_permisos': sesiones_permisos,
        'total_sesiones': sesiones.count(),
    }
    
    return render(request, 'pacientes/mis_sesiones.html', context)


@login_required
def mis_profesionales(request):
    """
    Vista EXCLUSIVA para que los pacientes vean sus profesionales
    ✅ Muestra todos los profesionales que han atendido al paciente
    """
    # ✅ Verificar que el usuario sea paciente
    if not hasattr(request.user, 'perfil') or not request.user.perfil.es_paciente:
        messages.error(request, '⚠️ Esta sección es solo para pacientes.')
        return redirect('core:dashboard')
    
    # ✅ Obtener el paciente vinculado
    paciente = request.user.perfil.paciente
    
    if not paciente:
        messages.error(request, '❌ No hay un paciente vinculado a tu cuenta.')
        return redirect('core:dashboard')
    
    # Importar modelos necesarios
    from agenda.models import Sesion
    from profesionales.models import Profesional
    
    # ✅ Obtener todos los profesionales que han atendido al paciente
    profesionales_ids = Sesion.objects.filter(
        paciente=paciente
    ).values_list('profesional_id', flat=True).distinct()
    
    profesionales = Profesional.objects.filter(
        id__in=profesionales_ids
    ).prefetch_related('servicios', 'sucursales')
    
    # ✅ Agregar estadísticas de sesiones por profesional
    profesionales_data = []
    for profesional in profesionales:
        # Contar sesiones totales
        total_sesiones = Sesion.objects.filter(
            paciente=paciente,
            profesional=profesional
        ).count()
        
        # Contar sesiones realizadas
        sesiones_realizadas = Sesion.objects.filter(
            paciente=paciente,
            profesional=profesional,
            estado__in=['realizada', 'realizada_retraso']
        ).count()
        
        # Próxima sesión
        proxima_sesion = Sesion.objects.filter(
            paciente=paciente,
            profesional=profesional,
            estado__in=['programada', 'retraso', 'con_retraso'],
            fecha__gte=date.today()
        ).order_by('fecha', 'hora_inicio').first()
        
        # ✅ Obtener servicios únicos que este profesional da a este paciente
        servicios_ids = Sesion.objects.filter(
            paciente=paciente,
            profesional=profesional
        ).values_list('servicio_id', flat=True).distinct()
        
        # Obtener nombres de servicios únicos
        from servicios.models import TipoServicio
        servicios_paciente = TipoServicio.objects.filter(
            id__in=servicios_ids
        ).values_list('nombre', flat=True)
        
        profesionales_data.append({
            'profesional': profesional,
            'total_sesiones': total_sesiones,
            'sesiones_realizadas': sesiones_realizadas,
            'proxima_sesion': proxima_sesion,
            'servicios_paciente': list(servicios_paciente),
        })
    
    context = {
        'paciente': paciente,
        'profesionales_data': profesionales_data,
        'total_profesionales': len(profesionales_data),
    }
    
    return render(request, 'pacientes/mis_profesionales.html', context)

# pacientes/views.py

@login_required
def detalle_sesiones_completo(request, pk):
    """
    Vista completa de todas las sesiones del paciente
    ✅ Solo Admin/Recepcionista
    ✅ Con gráficos estadísticos
    ✅ Diseño combinado adaptativo
    """
    paciente = get_object_or_404(Paciente, pk=pk)
    
    # ✅ VALIDACIÓN DE ACCESO
    if not request.user.is_superuser and hasattr(request.user, 'perfil'):
        if request.user.perfil.es_recepcionista():
            mis_sucursales = request.user.perfil.sucursales.all()
            sucursales_paciente = paciente.sucursales.all()
            
            if not sucursales_paciente.filter(id__in=mis_sucursales.values_list('id', flat=True)).exists():
                messages.error(
                    request,
                    '⚠️ No tienes permiso para ver las sesiones de este paciente.'
                )
                return redirect('pacientes:lista')
        elif not request.user.perfil.es_gerente() and not request.user.perfil.es_administrador():
            messages.error(request, '⚠️ No tienes permiso para acceder a esta sección.')
            return redirect('core:dashboard')
    
    # ==================== OBTENER FILTROS ====================
    tab_activo = request.GET.get('tab', 'normales')  # normales, mensualidades, proyectos
    estado_sesion = request.GET.get('estado', '')
    estado_pago = request.GET.get('pago', '')
    fecha_desde = request.GET.get('desde', '')
    fecha_hasta = request.GET.get('hasta', '')
    profesional_id = request.GET.get('profesional', '')
    servicio_id = request.GET.get('servicio', '')
    sucursal_id = request.GET.get('sucursal', '')
    buscar = request.GET.get('q', '')
    
    # ==================== QUERY BASE ====================
    from agenda.models import Sesion
    
    sesiones = Sesion.objects.filter(
        paciente=paciente
    ).select_related(
        'servicio', 'profesional', 'sucursal', 'proyecto', 'mensualidad'
    ).prefetch_related(
        'pagos', 'pagos__metodo_pago'
    )
    
    # ==================== SEPARAR POR TIPO ====================
    sesiones_normales = sesiones.filter(proyecto__isnull=True, mensualidad__isnull=True)
    sesiones_mensualidades = sesiones.filter(mensualidad__isnull=False)
    sesiones_proyectos = sesiones.filter(proyecto__isnull=False)
    
    # ==================== APLICAR FILTROS ====================
    def aplicar_filtros(query):
        q = query
        
        # Filtro por estado de sesión
        if estado_sesion:
            q = q.filter(estado=estado_sesion)
        
        # Filtro por estado de pago
        if estado_pago:
            if estado_pago == 'pagado':
                # Sesiones completamente pagadas
                sesiones_ids = [
                    s.id for s in q 
                    if s.monto_cobrado > 0 and s.pagado
                ]
                q = q.filter(id__in=sesiones_ids)
            elif estado_pago == 'parcial':
                # Pagos parciales
                sesiones_ids = [
                    s.id for s in q 
                    if s.monto_cobrado > 0 and s.total_pagado > 0 and not s.pagado
                ]
                q = q.filter(id__in=sesiones_ids)
            elif estado_pago == 'pendiente':
                # Sin pagar
                sesiones_ids = [
                    s.id for s in q 
                    if s.monto_cobrado > 0 and s.total_pagado == 0
                ]
                q = q.filter(id__in=sesiones_ids)
            elif estado_pago == 'no_aplica':
                # Gratuitas o de proyecto/mensualidad
                q = q.filter(monto_cobrado=0)
        
        # Filtro por rango de fechas
        if fecha_desde:
            try:
                q = q.filter(fecha__gte=fecha_desde)
            except:
                pass
        
        if fecha_hasta:
            try:
                q = q.filter(fecha__lte=fecha_hasta)
            except:
                pass
        
        # Filtro por profesional
        if profesional_id:
            q = q.filter(profesional_id=profesional_id)
        
        # Filtro por servicio
        if servicio_id:
            q = q.filter(servicio_id=servicio_id)
        
        # Filtro por sucursal
        if sucursal_id:
            q = q.filter(sucursal_id=sucursal_id)
        
        # Búsqueda
        if buscar:
            q = q.filter(
                Q(observaciones__icontains=buscar) |
                Q(notas_sesion__icontains=buscar) |
                Q(servicio__nombre__icontains=buscar) |
                Q(profesional__nombre__icontains=buscar) |
                Q(profesional__apellido__icontains=buscar)
            )
        
        return q
    
    # Aplicar filtros según tab activo
    if tab_activo == 'normales':
        sesiones_filtradas = aplicar_filtros(sesiones_normales).order_by('-fecha', '-hora_inicio')
    elif tab_activo == 'mensualidades':
        sesiones_filtradas = aplicar_filtros(sesiones_mensualidades).order_by('-fecha', '-hora_inicio')
    elif tab_activo == 'proyectos':
        sesiones_filtradas = aplicar_filtros(sesiones_proyectos).order_by('-fecha', '-hora_inicio')
    else:
        sesiones_filtradas = aplicar_filtros(sesiones).order_by('-fecha', '-hora_inicio')
    
    # ==================== AGRUPAR MENSUALIDADES ====================
    mensualidades_agrupadas = []
    if tab_activo == 'mensualidades':
        from agenda.models import Mensualidad
        mensualidades = Mensualidad.objects.filter(
            paciente=paciente
        ).select_related('servicio', 'profesional', 'sucursal').order_by('-anio', '-mes')
        
        for mensualidad in mensualidades:
            sesiones_mens = sesiones_mensualidades.filter(mensualidad=mensualidad)
            
            # Aplicar filtros a las sesiones de esta mensualidad
            sesiones_mens = aplicar_filtros(sesiones_mens)
            
            if sesiones_mens.exists() or not any([estado_sesion, estado_pago, profesional_id, servicio_id, fecha_desde, fecha_hasta]):
                mensualidades_agrupadas.append({
                    'mensualidad': mensualidad,
                    'sesiones': sesiones_mens.order_by('fecha', 'hora_inicio'),
                    'total_sesiones': sesiones_mens.count(),
                    'sesiones_realizadas': sesiones_mens.filter(estado__in=['realizada', 'realizada_retraso']).count(),
                })
    
    # ==================== AGRUPAR PROYECTOS ====================
    proyectos_agrupados = []
    if tab_activo == 'proyectos':
        from agenda.models import Proyecto
        proyectos = Proyecto.objects.filter(
            paciente=paciente
        ).select_related('servicio_base', 'profesional_responsable', 'sucursal').order_by('-fecha_inicio')
        
        for proyecto in proyectos:
            sesiones_proy = sesiones_proyectos.filter(proyecto=proyecto)
            
            # Aplicar filtros
            sesiones_proy = aplicar_filtros(sesiones_proy)
            
            if sesiones_proy.exists() or not any([estado_sesion, estado_pago, profesional_id, servicio_id, fecha_desde, fecha_hasta]):
                proyectos_agrupados.append({
                    'proyecto': proyecto,
                    'sesiones': sesiones_proy.order_by('fecha', 'hora_inicio'),
                    'total_sesiones': sesiones_proy.count(),
                    'sesiones_realizadas': sesiones_proy.filter(estado__in=['realizada', 'realizada_retraso']).count(),
                })
    
    # ==================== ESTADÍSTICAS GENERALES ====================
    stats = {
        'total_sesiones': sesiones.count(),
        'total_normales': sesiones_normales.count(),
        'total_mensualidades': sesiones_mensualidades.count(),
        'total_proyectos': sesiones_proyectos.count(),
        
        # Por estado
        'realizadas': sesiones.filter(estado='realizada').count(),
        'con_retraso': sesiones.filter(estado='realizada_retraso').count(),
        'programadas': sesiones.filter(estado='programada').count(),
        'faltas': sesiones.filter(estado='falta').count(),
        'permisos': sesiones.filter(estado='permiso').count(),
        'canceladas': sesiones.filter(estado='cancelada').count(),
        'reprogramadas': sesiones.filter(estado='reprogramada').count(),
    }
    
    # Tasa de asistencia
    sesiones_efectivas = stats['realizadas'] + stats['con_retraso']
    sesiones_programadas_total = stats['total_sesiones'] - stats['canceladas'] - stats['permisos']
    stats['tasa_asistencia'] = (sesiones_efectivas / sesiones_programadas_total * 100) if sesiones_programadas_total > 0 else 0
    
    # Estadísticas de pago
    sesiones_con_cobro = [s for s in sesiones if s.monto_cobrado > 0]
    
    stats['total_cobrado'] = sum(s.monto_cobrado for s in sesiones_con_cobro)
    stats['total_pagado'] = sum(s.total_pagado for s in sesiones_con_cobro)
    stats['total_pendiente'] = stats['total_cobrado'] - stats['total_pagado']
    
    sesiones_pagadas = [s for s in sesiones_con_cobro if s.pagado]
    sesiones_pendientes = [s for s in sesiones_con_cobro if not s.pagado and s.total_pagado == 0]
    sesiones_parciales = [s for s in sesiones_con_cobro if s.total_pagado > 0 and not s.pagado]
    
    stats['count_pagadas'] = len(sesiones_pagadas)
    stats['count_pendientes'] = len(sesiones_pendientes)
    stats['count_parciales'] = len(sesiones_parciales)
    
    # Tasa de pago
    stats['tasa_pago'] = (stats['count_pagadas'] / len(sesiones_con_cobro) * 100) if sesiones_con_cobro else 0
    
    # ==================== DATOS PARA GRÁFICOS ====================
    import json
    from datetime import timedelta
    from collections import defaultdict
    
    # Gráfico 1: Asistencia por mes (últimos 6 meses)
    hoy = date.today()
    hace_6_meses = hoy - timedelta(days=180)
    
    sesiones_ultimos_6m = sesiones.filter(fecha__gte=hace_6_meses)
    
    # Agrupar por mes
    from django.db.models.functions import TruncMonth
    por_mes = sesiones_ultimos_6m.annotate(
        mes=TruncMonth('fecha')
    ).values('mes').annotate(
        total=Count('id'),
        realizadas=Count('id', filter=Q(estado='realizada')),
        con_retraso=Count('id', filter=Q(estado='realizada_retraso')),
        faltas=Count('id', filter=Q(estado='falta')),
        permisos=Count('id', filter=Q(estado='permiso')),
        canceladas=Count('id', filter=Q(estado='cancelada'))
    ).order_by('mes')
    
    grafico_asistencia = {
        'labels': [m['mes'].strftime('%b %Y') for m in por_mes],
        'realizadas': [m['realizadas'] for m in por_mes],
        'con_retraso': [m['con_retraso'] for m in por_mes],
        'faltas': [m['faltas'] for m in por_mes],
        'permisos': [m['permisos'] for m in por_mes],
        'canceladas': [m['canceladas'] for m in por_mes],
    }
    
    # Gráfico 2: Pagos vs Deuda
    grafico_pagos = {
        'pagado': float(stats['total_pagado']),
        'pendiente': float(stats['total_pendiente']),
    }
    
    # Gráfico 3: Distribución por servicio
    por_servicio = sesiones.values(
        'servicio__nombre', 'servicio__color'
    ).annotate(
        cantidad=Count('id')
    ).order_by('-cantidad')[:5]
    
    grafico_servicios = {
        'labels': [s['servicio__nombre'] for s in por_servicio],
        'data': [s['cantidad'] for s in por_servicio],
        'colors': [s['servicio__color'] for s in por_servicio],
    }
    
    # ==================== DATOS PARA FILTROS ====================
    # Profesionales que han atendido
    profesionales_ids = sesiones.values_list('profesional_id', flat=True).distinct()
    from profesionales.models import Profesional
    profesionales = Profesional.objects.filter(id__in=profesionales_ids).order_by('apellido', 'nombre')
    
    # Servicios contratados
    servicios_ids = sesiones.values_list('servicio_id', flat=True).distinct()
    from servicios.models import TipoServicio
    servicios = TipoServicio.objects.filter(id__in=servicios_ids).order_by('nombre')
    
    # Sucursales donde ha sido atendido
    sucursales_ids = sesiones.values_list('sucursal_id', flat=True).distinct()
    from servicios.models import Sucursal
    sucursales = Sucursal.objects.filter(id__in=sucursales_ids).order_by('nombre')
    
    # ==================== PAGINACIÓN (Solo para sesiones normales) ====================
    from django.core.paginator import Paginator
    
    if tab_activo == 'normales':
        paginator = Paginator(sesiones_filtradas, 20)
        page_number = request.GET.get('page', 1)
        sesiones_page = paginator.get_page(page_number)
    else:
        sesiones_page = None
    
    # ==================== CONTEXT ====================
    context = {
        'paciente': paciente,
        'tab_activo': tab_activo,
        
        # Sesiones
        'sesiones_filtradas': sesiones_filtradas if tab_activo == 'normales' else None,
        'sesiones_page': sesiones_page,
        'mensualidades_agrupadas': mensualidades_agrupadas,
        'proyectos_agrupados': proyectos_agrupados,
        
        # Estadísticas
        'stats': stats,
        
        # Gráficos
        'grafico_asistencia': json.dumps(grafico_asistencia),
        'grafico_pagos': json.dumps(grafico_pagos),
        'grafico_servicios': json.dumps(grafico_servicios),
        
        # Filtros
        'profesionales': profesionales,
        'servicios': servicios,
        'sucursales': sucursales,
        'estados_sesion': Sesion.ESTADO_CHOICES,
        
        # Valores actuales de filtros
        'filtros': {
            'estado': estado_sesion,
            'pago': estado_pago,
            'desde': fecha_desde,
            'hasta': fecha_hasta,
            'profesional': profesional_id,
            'servicio': servicio_id,
            'sucursal': sucursal_id,
            'buscar': buscar,
        },
    }
    
    return render(request, 'pacientes/detalle_sesiones.html', context)