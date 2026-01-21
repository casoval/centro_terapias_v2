from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from .models import TipoServicio, Sucursal
from .forms import TipoServicioForm, SucursalForm
from datetime import date, timedelta


# ==================== SERVICIOS/TIPOS ====================

@login_required
def lista_servicios(request):
    """Lista de tipos de servicios activos"""
    servicios = TipoServicio.objects.filter(activo=True).order_by('nombre')
    
    # Búsqueda
    buscar = request.GET.get('q', '')
    if buscar:
        servicios = servicios.filter(nombre__icontains=buscar)
    
    # Agregar estadísticas de uso
    hoy = date.today()
    inicio_semana = hoy - timedelta(days=hoy.weekday())
    fin_semana = inicio_semana + timedelta(days=6)
    
    try:
        from pacientes.models import PacienteServicio
        
        for servicio in servicios:
            servicio.sesiones_semana = servicio.sesiones.filter(
                fecha__gte=inicio_semana,
                fecha__lte=fin_semana
            ).count()
            servicio.pacientes_activos = PacienteServicio.objects.filter(
                servicio=servicio,
                activo=True
            ).count()
    except ImportError:
        for servicio in servicios:
            servicio.sesiones_semana = servicio.sesiones.filter(
                fecha__gte=inicio_semana,
                fecha__lte=fin_semana
            ).count()
            servicio.pacientes_activos = 0
    
    context = {
        'servicios': servicios,
        'buscar': buscar,
    }
    return render(request, 'servicios/lista_servicios.html', context)

@login_required
def detalle_servicio(request, pk):
    """Detalle de un tipo de servicio"""
    servicio = get_object_or_404(TipoServicio, pk=pk)
    
    # ✅ Parámetros para mostrar todos
    mostrar_todos_profesionales = request.GET.get('todos_prof', '') == '1'
    mostrar_todos_pacientes = request.GET.get('todos_pac', '') == '1'
    
    # ✅ FILTRAR POR SUCURSALES DEL RECEPCIONISTA
    sesiones = servicio.sesiones.all()
    profesionales_query = servicio.profesionales.filter(activo=True)
    
    # Verificar si el usuario tiene perfil y es recepcionista
    if hasattr(request.user, 'perfil'):
        perfil = request.user.perfil
        
        if perfil.es_recepcionista() or perfil.es_gerente():
            sucursales_usuario = perfil.get_sucursales()
            if sucursales_usuario and sucursales_usuario.exists():
                # Filtrar sesiones por sucursales del recepcionista
                sesiones = sesiones.filter(sucursal__in=sucursales_usuario)
                # Filtrar profesionales por sucursales del recepcionista
                profesionales_query = profesionales_query.filter(sucursales__in=sucursales_usuario).distinct()
    
    # Últimas 10 sesiones
    sesiones = sesiones.order_by('-fecha', '-hora_inicio')[:10]
    
    # ✅ Profesionales que ofrecen este servicio
    profesionales_query = profesionales_query.order_by('apellido', 'nombre')
    total_profesionales = profesionales_query.count()
    
    if mostrar_todos_profesionales:
        profesionales = profesionales_query
    else:
        profesionales = profesionales_query[:6]  # Mostrar solo 6 inicialmente
    
    # ✅ NUEVO: Pacientes que reciben este servicio (filtrados por sucursal si es recepcionista)
    try:
        from pacientes.models import PacienteServicio
        pacientes_query = PacienteServicio.objects.filter(
            servicio=servicio,
            activo=True
        ).select_related('paciente').filter(
            paciente__estado='activo'
        )
        
        # Filtrar pacientes por sucursales del recepcionista
        if hasattr(request.user, 'perfil'):
            perfil = request.user.perfil
            
            if perfil.es_recepcionista() or perfil.es_gerente():
                sucursales_usuario = perfil.get_sucursales()
                if sucursales_usuario and sucursales_usuario.exists():
                    pacientes_query = pacientes_query.filter(
                        paciente__sucursales__in=sucursales_usuario
                    ).distinct()
        
        pacientes_query = pacientes_query.order_by('paciente__apellido', 'paciente__nombre')
        total_pacientes = pacientes_query.count()
        
        if mostrar_todos_pacientes:
            pacientes_servicios = pacientes_query
        else:
            pacientes_servicios = pacientes_query[:6]  # Mostrar solo 6 inicialmente
        
        pacientes_activos = total_pacientes
    except ImportError:
        pacientes_servicios = []
        pacientes_activos = 0
        total_pacientes = 0
    
    context = {
        'servicio': servicio,
        'sesiones': sesiones,
        'profesionales': profesionales,
        'total_profesionales': total_profesionales,
        'mostrar_todos_profesionales': mostrar_todos_profesionales,
        'pacientes_servicios': pacientes_servicios,
        'total_pacientes': total_pacientes,
        'mostrar_todos_pacientes': mostrar_todos_pacientes,
        'pacientes_activos': pacientes_activos,
    }
    return render(request, 'servicios/detalle_servicio.html', context)

@login_required
def agregar_servicio(request):
    """Crear un nuevo tipo de servicio"""
    if request.method == 'POST':
        form = TipoServicioForm(request.POST)
        if form.is_valid():
            servicio = form.save()
            messages.success(request, f'✅ Servicio "{servicio.nombre}" creado exitosamente.')
            return redirect('servicios:lista_servicios')
    else:
        form = TipoServicioForm()
    
    context = {
        'form': form,
    }
    return render(request, 'servicios/agregar_servicio.html', context)


@login_required
def editar_servicio(request, pk):
    """Editar un tipo de servicio existente"""
    servicio = get_object_or_404(TipoServicio, pk=pk)
    
    if request.method == 'POST':
        form = TipoServicioForm(request.POST, instance=servicio)
        if form.is_valid():
            servicio = form.save()
            messages.success(request, f'✅ Servicio "{servicio.nombre}" actualizado exitosamente.')
            return redirect('servicios:detalle_servicio', pk=servicio.id)
    else:
        form = TipoServicioForm(instance=servicio)
    
    context = {
        'form': form,
        'servicio': servicio,
    }
    return render(request, 'servicios/editar_servicio.html', context)


@login_required
def eliminar_servicio(request, pk):
    """Eliminar o desactivar un tipo de servicio"""
    servicio = get_object_or_404(TipoServicio, pk=pk)
    
    # ✅ Verificar si tiene datos relacionados
    sesiones_count = servicio.sesiones.count()
    profesionales_count = servicio.profesionales.filter(activo=True).count()
    
    try:
        from pacientes.models import PacienteServicio
        pacientes_count = PacienteServicio.objects.filter(
            servicio=servicio,
            activo=True
        ).count()
    except ImportError:
        pacientes_count = 0
    
    tiene_datos = sesiones_count > 0 or profesionales_count > 0 or pacientes_count > 0
    
    datos_relacionados = {
        'sesiones': sesiones_count,
        'profesionales': profesionales_count,
        'pacientes': pacientes_count,
    }
    
    if request.method == 'POST':
        accion = request.POST.get('accion')
        
        if accion == 'desactivar':
            # ✅ DESACTIVAR: Cambiar estado a inactivo
            servicio.activo = False
            servicio.save()
            messages.success(
                request, 
                f'🔒 Servicio "{servicio.nombre}" desactivado correctamente. '
                f'Puedes reactivarlo en cualquier momento desde el panel de administración.'
            )
            return redirect('servicios:lista_servicios')
        
        elif accion == 'eliminar' and not tiene_datos:
            # ✅ ELIMINAR: Solo si NO tiene datos asociados
            nombre = servicio.nombre
            servicio.delete()
            messages.success(
                request, 
                f'🗑️ Servicio "{nombre}" eliminado permanentemente del sistema.'
            )
            return redirect('servicios:lista_servicios')
        else:
            # ❌ Intento de eliminar con datos asociados
            messages.error(
                request,
                '❌ No se puede eliminar este servicio porque tiene datos asociados. '
                'Usa la opción DESACTIVAR en su lugar.'
            )
    
    context = {
        'servicio': servicio,
        'tiene_datos': tiene_datos,
        'datos_relacionados': datos_relacionados,
    }
    return render(request, 'servicios/eliminar_servicio.html', context)


# ==================== SUCURSALES ====================

@login_required
def lista_sucursales(request):
    """Lista de sucursales activas"""
    sucursales = Sucursal.objects.filter(activa=True).order_by('nombre')
    
    # ✅ FILTRAR POR SUCURSALES DEL RECEPCIONISTA
    if hasattr(request.user, 'perfil'):
        perfil = request.user.perfil
        
        if perfil.es_recepcionista() or perfil.es_gerente():
            sucursales_usuario = perfil.get_sucursales()
            if sucursales_usuario and sucursales_usuario.exists():
                # Mostrar solo las sucursales asignadas al recepcionista
                sucursales = sucursales.filter(id__in=sucursales_usuario)
    
    # Búsqueda
    buscar = request.GET.get('q', '')
    if buscar:
        sucursales = sucursales.filter(
            Q(nombre__icontains=buscar) | Q(direccion__icontains=buscar)
        )
    
    # Agregar estadísticas
    hoy = date.today()
    inicio_semana = hoy - timedelta(days=hoy.weekday())
    fin_semana = inicio_semana + timedelta(days=6)
    
    for sucursal in sucursales:
        sucursal.sesiones_semana = sucursal.sesiones.filter(
            fecha__gte=inicio_semana,
            fecha__lte=fin_semana
        ).count()
        sucursal.profesionales_activos = sucursal.profesionales.filter(activo=True).count()
        sucursal.pacientes_activos = sucursal.pacientes.filter(estado='activo').count()
    
    context = {
        'sucursales': sucursales,
        'buscar': buscar,
    }
    return render(request, 'servicios/lista_sucursales.html', context)

@login_required
def detalle_sucursal(request, pk):
    """Detalle de una sucursal"""
    sucursal = get_object_or_404(Sucursal, pk=pk)
    
    # ✅ VERIFICAR ACCESO DEL RECEPCIONISTA A ESTA SUCURSAL
    if hasattr(request.user, 'perfil'):
        perfil = request.user.perfil
        
        if perfil.es_recepcionista() or perfil.es_gerente():
            sucursales_usuario = perfil.get_sucursales()
            if sucursales_usuario and sucursales_usuario.exists():
                # Verificar que tenga acceso a esta sucursal
                if not sucursales_usuario.filter(id=sucursal.id).exists():
                    messages.error(request, '⚠️ No tienes acceso a esta sucursal.')
                    return redirect('servicios:lista_sucursales')
    
    # ✅ Parámetros para mostrar todos
    mostrar_todos_profesionales = request.GET.get('todos_prof', '') == '1'
    mostrar_todos_pacientes = request.GET.get('todos_pac', '') == '1'
    
    # Últimas 10 sesiones
    sesiones = sucursal.sesiones.all().order_by('-fecha', '-hora_inicio')[:10]
    
    # ✅ Profesionales activos en esta sucursal
    profesionales_query = sucursal.profesionales.filter(activo=True).order_by('apellido', 'nombre')
    total_profesionales = profesionales_query.count()
    
    if mostrar_todos_profesionales:
        profesionales = profesionales_query
    else:
        profesionales = profesionales_query[:6]  # Mostrar solo 6 inicialmente
    
    # ✅ Pacientes activos en esta sucursal
    pacientes_query = sucursal.pacientes.filter(estado='activo').order_by('apellido', 'nombre')
    total_pacientes = pacientes_query.count()
    
    if mostrar_todos_pacientes:
        pacientes = pacientes_query
    else:
        pacientes = pacientes_query[:6]  # Mostrar solo 6 inicialmente
    
    context = {
        'sucursal': sucursal,
        'sesiones': sesiones,
        'profesionales': profesionales,
        'total_profesionales': total_profesionales,
        'mostrar_todos_profesionales': mostrar_todos_profesionales,
        'pacientes': pacientes,
        'total_pacientes': total_pacientes,
        'mostrar_todos_pacientes': mostrar_todos_pacientes,
    }
    return render(request, 'servicios/detalle_sucursal.html', context)

@login_required
def agregar_sucursal(request):
    """Crear una nueva sucursal"""
    if request.method == 'POST':
        form = SucursalForm(request.POST)
        if form.is_valid():
            sucursal = form.save()
            messages.success(request, f'✅ Sucursal "{sucursal.nombre}" creada exitosamente.')
            return redirect('servicios:lista_sucursales')
    else:
        form = SucursalForm()
    
    context = {
        'form': form,
    }
    return render(request, 'servicios/agregar_sucursal.html', context)


@login_required
def editar_sucursal(request, pk):
    """Editar una sucursal existente"""
    sucursal = get_object_or_404(Sucursal, pk=pk)
    
    if request.method == 'POST':
        form = SucursalForm(request.POST, instance=sucursal)
        if form.is_valid():
            sucursal = form.save()
            messages.success(request, f'✅ Sucursal "{sucursal.nombre}" actualizada exitosamente.')
            return redirect('servicios:detalle_sucursal', pk=sucursal.id)
    else:
        form = SucursalForm(instance=sucursal)
    
    context = {
        'form': form,
        'sucursal': sucursal,
    }
    return render(request, 'servicios/editar_sucursal.html', context)


@login_required
def eliminar_sucursal(request, pk):
    """Eliminar o desactivar una sucursal"""
    sucursal = get_object_or_404(Sucursal, pk=pk)
    
    # ✅ Verificar si tiene datos relacionados
    sesiones_count = sucursal.sesiones.count()
    profesionales_count = sucursal.profesionales.filter(activo=True).count()
    pacientes_count = sucursal.pacientes.filter(estado='activo').count()
    
    tiene_datos = sesiones_count > 0 or profesionales_count > 0 or pacientes_count > 0
    
    datos_relacionados = {
        'sesiones': sesiones_count,
        'profesionales': profesionales_count,
        'pacientes': pacientes_count,
    }
    
    if request.method == 'POST':
        accion = request.POST.get('accion')
        
        if accion == 'desactivar':
            # ✅ DESACTIVAR: Cambiar estado a inactivo
            sucursal.activa = False
            sucursal.save()
            messages.success(
                request, 
                f'🔒 Sucursal "{sucursal.nombre}" desactivada correctamente. '
                f'Puedes reactivarla en cualquier momento desde el panel de administración.'
            )
            return redirect('servicios:lista_sucursales')
        
        elif accion == 'eliminar' and not tiene_datos:
            # ✅ ELIMINAR: Solo si NO tiene datos asociados
            nombre = sucursal.nombre
            sucursal.delete()
            messages.success(
                request, 
                f'🗑️ Sucursal "{nombre}" eliminada permanentemente del sistema.'
            )
            return redirect('servicios:lista_sucursales')
        else:
            # ❌ Intento de eliminar con datos asociados
            messages.error(
                request,
                '❌ No se puede eliminar esta sucursal porque tiene datos asociados. '
                'Usa la opción DESACTIVAR en su lugar.'
            )
    
    context = {
        'sucursal': sucursal,
        'tiene_datos': tiene_datos,
        'datos_relacionados': datos_relacionados,
    }
    return render(request, 'servicios/eliminar_sucursal.html', context)