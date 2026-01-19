from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.db.models import Count, Q
from datetime import date
from .models import Paciente, PacienteServicio
from .forms import PacienteForm

@login_required
def lista_pacientes(request):
    """Lista de pacientes activos"""
    # 1. Ordenamiento: Primero por nombre, luego apellido
    pacientes = Paciente.objects.filter(estado='activo').order_by('nombre', 'apellido')
    
    # 2. Lógica de Búsqueda
    buscar = request.GET.get('q', '')
    if buscar:
        pacientes = pacientes.filter(
            Q(nombre__icontains=buscar) | 
            Q(apellido__icontains=buscar)
        )
    
    # 3. Lógica de Filtro por Sucursal
    sucursal_id = request.GET.get('sucursal')
    if sucursal_id:
        pacientes = pacientes.filter(sucursales__id=sucursal_id)
    
    # Obtener sucursales para el filtro
    from servicios.models import Sucursal
    # ✅ CORRECCIÓN: Usar 'activa=True' en lugar de 'activo=True'
    sucursales = Sucursal.objects.filter(activa=True).order_by('nombre')
    
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
        form = PacienteForm(request.POST, request.FILES)
        
        if form.is_valid():
            paciente = form.save()
            
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
        form = PacienteForm()
        
        # ✅ Pre-seleccionar usuario si viene desde crear usuario
        if usuario_seleccionado:
            form.initial['user'] = usuario_seleccionado.id
    
    # Obtener servicios disponibles
    from servicios.models import TipoServicio
    servicios = TipoServicio.objects.filter(activo=True).order_by('nombre')
    
    context = {
        'form': form,
        'servicios': servicios,
        'usuario_seleccionado': usuario_seleccionado,  # ✅ Para mostrar en template
    }
    return render(request, 'pacientes/agregar.html', context)


@login_required
def editar_paciente(request, pk):
    """
    ✅ Vista para editar paciente existente
    """
    paciente = get_object_or_404(Paciente, pk=pk)
    
    if request.method == 'POST':
        form = PacienteForm(request.POST, request.FILES, instance=paciente)
        
        if form.is_valid():
            # Guardar paciente
            paciente = form.save()
            
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
        form = PacienteForm(instance=paciente)
    
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
    Similar a la de usuarios
    """
    paciente = get_object_or_404(Paciente, pk=pk)
    
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
    """Detalle de un paciente con profesionales y sucursales"""
    paciente = get_object_or_404(Paciente, pk=pk)
    
    # Últimas 10 sesiones
    sesiones = paciente.sesiones.all().order_by('-fecha', '-hora_inicio')[:10]
    
    # ✅ CORRECCIÓN: Servicios contratados usando consulta directa
    servicios = PacienteServicio.objects.filter(
        paciente=paciente,
        activo=True
    ).select_related('servicio')
    
    # ✅ NUEVO: Obtener sucursales donde ha sido atendido
    from agenda.models import Sesion
    sucursales_ids = Sesion.objects.filter(
        paciente=paciente
    ).values_list('sucursal_id', flat=True).distinct()
    
    from servicios.models import Sucursal
    sucursales = Sucursal.objects.filter(
        id__in=sucursales_ids
    ).order_by('nombre')
    
    # ✅ NUEVO: Obtener profesionales que le han atendido
    profesionales_ids = Sesion.objects.filter(
        paciente=paciente
    ).values_list('profesional_id', flat=True).distinct()
    
    from profesionales.models import Profesional
    profesionales = Profesional.objects.filter(
        id__in=profesionales_ids
    ).prefetch_related('servicios', 'sucursales')
    
    # ✅ NUEVO: Agregar estadísticas por profesional
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