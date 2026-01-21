from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Count, Q
from .models import Profesional
from .forms import ProfesionalForm
from datetime import date, timedelta
# Importar modelo de Sucursal
from servicios.models import Sucursal 

@login_required
def lista_profesionales(request):
    """Lista de profesionales activos con filtros"""
    # 1. Ordenar por apellido y nombre
    profesionales = Profesional.objects.filter(activo=True).order_by('nombre', 'apellido')
    
    # ✅ FILTRO POR SUCURSALES DEL RECEPCIONISTA
    sucursales_usuario = None
    
    # Verificar si el usuario tiene perfil
    if hasattr(request.user, 'perfil'):
        perfil = request.user.perfil
        
        if perfil.es_recepcionista() or perfil.es_gerente():
            # Obtener solo sucursales asignadas al recepcionista/gerente
            sucursales_usuario = perfil.get_sucursales()
            if sucursales_usuario and sucursales_usuario.exists():
                # Filtrar profesionales que trabajen en esas sucursales
                profesionales = profesionales.filter(sucursales__in=sucursales_usuario).distinct()
    
    # 2. Búsqueda por texto
    buscar = request.GET.get('q', '')
    if buscar:
        profesionales = profesionales.filter(
            Q(nombre__icontains=buscar) |
            Q(apellido__icontains=buscar) |
            Q(especialidad__icontains=buscar)
        )
    
    # 3. Nuevo Filtro por Sucursal
    sucursal_id = request.GET.get('sucursal')
    if sucursal_id:
        try:
            sucursal_id = int(sucursal_id)
            profesionales = profesionales.filter(sucursales__id=sucursal_id)
        except ValueError:
            pass

    # Agregar estadísticas (se mantiene igual)
    hoy = date.today()
    inicio_semana = hoy - timedelta(days=hoy.weekday())
    fin_semana = inicio_semana + timedelta(days=6)
    
    for profesional in profesionales:
        profesional.sesiones_semana = profesional.sesiones.filter(
            fecha__gte=inicio_semana,
            fecha__lte=fin_semana
        ).count()
        profesional.total_pacientes = profesional.get_pacientes().count()
    
    # ✅ Obtener sucursales para el select (solo las del usuario si es recepcionista)
    if sucursales_usuario and sucursales_usuario.exists():
        sucursales = sucursales_usuario.filter(activa=True).order_by('nombre')
    else:
        sucursales = Sucursal.objects.filter(activa=True).order_by('nombre')

    context = {
        'profesionales': profesionales,
        'buscar': buscar,
        'sucursales': sucursales,
        'sucursal_id': sucursal_id,
    }
    return render(request, 'profesionales/lista.html', context)

@login_required
def detalle_profesional(request, pk):
    """Detalle de un profesional"""
    profesional = get_object_or_404(Profesional, pk=pk)
    
    # ✅ FILTRAR SESIONES POR SUCURSALES DEL RECEPCIONISTA
    sesiones = profesional.sesiones.all()
    
    # Verificar si el usuario tiene perfil
    if hasattr(request.user, 'perfil'):
        perfil = request.user.perfil
        
        if perfil.es_recepcionista() or perfil.es_gerente():
            sucursales_usuario = perfil.get_sucursales()
            if sucursales_usuario and sucursales_usuario.exists():
                # Solo mostrar sesiones de sucursales asignadas
                sesiones = sesiones.filter(sucursal__in=sucursales_usuario)
    
    # Últimas 10 sesiones
    sesiones = sesiones.order_by('-fecha', '-hora_inicio')[:10]
    
    # Servicios que ofrece
    servicios = profesional.servicios.filter(activo=True)
    
    # ✅ FILTRAR SUCURSALES SEGÚN ROL
    sucursales = profesional.sucursales.filter(activa=True)
    
    if hasattr(request.user, 'perfil'):
        perfil = request.user.perfil
        
        if perfil.es_recepcionista() or perfil.es_gerente():
            sucursales_usuario = perfil.get_sucursales()
            if sucursales_usuario and sucursales_usuario.exists():
                # Solo mostrar sucursales asignadas al recepcionista
                sucursales = sucursales.filter(id__in=sucursales_usuario)
    
    # ✅ FILTRAR PACIENTES POR SUCURSALES DEL RECEPCIONISTA
    pacientes = profesional.get_pacientes()
    
    if hasattr(request.user, 'perfil'):
        perfil = request.user.perfil
        
        if perfil.es_recepcionista() or perfil.es_gerente():
            sucursales_usuario = perfil.get_sucursales()
            if sucursales_usuario and sucursales_usuario.exists():
                # Solo mostrar pacientes atendidos en sucursales asignadas
                from agenda.models import Sesion
                pacientes_ids = Sesion.objects.filter(
                    profesional=profesional,
                    sucursal__in=sucursales_usuario
                ).values_list('paciente_id', flat=True).distinct()
                pacientes = pacientes.filter(id__in=pacientes_ids)
    
    pacientes = pacientes[:10]
    
    context = {
        'profesional': profesional,
        'sesiones': sesiones,
        'servicios': servicios,
        'sucursales': sucursales,
        'pacientes': pacientes,
    }
    return render(request, 'profesionales/detalle.html', context)


@login_required
def agregar_profesional(request):
    """Crear un nuevo profesional"""
    if request.method == 'POST':
        form = ProfesionalForm(request.POST, request.FILES)
        if form.is_valid():
            profesional = form.save()
            messages.success(request, f'✅ Profesional "{profesional.nombre_completo}" creado exitosamente.')
            return redirect('profesionales:lista')
    else:
        form = ProfesionalForm()
    
    context = {
        'form': form,
    }
    return render(request, 'profesionales/agregar.html', context)


@login_required
def editar_profesional(request, pk):
    """Editar un profesional existente"""
    profesional = get_object_or_404(Profesional, pk=pk)
    
    if request.method == 'POST':
        form = ProfesionalForm(request.POST, request.FILES, instance=profesional)
        if form.is_valid():
            profesional = form.save()
            messages.success(request, f'✅ Profesional "{profesional.nombre_completo}" actualizado exitosamente.')
            return redirect('profesionales:detalle', pk=profesional.id)
    else:
        form = ProfesionalForm(instance=profesional)
    
    context = {
        'form': form,
        'profesional': profesional,
    }
    return render(request, 'profesionales/editar.html', context)


@login_required
def eliminar_profesional(request, pk):
    """Eliminar o desactivar un profesional"""
    profesional = get_object_or_404(Profesional, pk=pk)
    
    # ✅ Verificar si tiene datos relacionados
    from agenda.models import Sesion
    
    sesiones_count = Sesion.objects.filter(profesional=profesional).count()
    pacientes_count = profesional.get_pacientes().count()
    
    tiene_datos = sesiones_count > 0 or pacientes_count > 0
    
    datos_relacionados = {
        'sesiones': sesiones_count,
        'pacientes': pacientes_count,
    }
    
    if request.method == 'POST':
        accion = request.POST.get('accion')
        
        if accion == 'desactivar':
            # ✅ DESACTIVAR: Cambiar estado a inactivo
            profesional.activo = False
            profesional.save()
            messages.success(
                request, 
                f'🔒 Profesional "{profesional.nombre_completo}" desactivado correctamente. '
                f'Puedes reactivarlo en cualquier momento desde el panel de administración.'
            )
            return redirect('profesionales:lista')
        
        elif accion == 'eliminar' and not tiene_datos:
            # ✅ ELIMINAR: Solo si NO tiene datos asociados
            nombre_completo = profesional.nombre_completo
            profesional.delete()
            messages.success(
                request, 
                f'🗑️ Profesional "{nombre_completo}" eliminado permanentemente del sistema.'
            )
            return redirect('profesionales:lista')
        else:
            # ❌ Intento de eliminar con datos asociados
            messages.error(
                request,
                '❌ No se puede eliminar este profesional porque tiene datos asociados. '
                'Usa la opción DESACTIVAR en su lugar.'
            )
    
    context = {
        'profesional': profesional,
        'tiene_datos': tiene_datos,
        'datos_relacionados': datos_relacionados,
    }
    return render(request, 'profesionales/eliminar.html', context)


@login_required
def mis_pacientes(request):
    """
    Vista EXCLUSIVA para que los profesionales vean sus pacientes
    ✅ Muestra todos los pacientes que ha atendido el profesional
    """
    # ✅ Verificar que el usuario sea profesional
    if not hasattr(request.user, 'perfil') or not request.user.perfil.es_profesional:
        messages.error(request, '⚠️ Esta sección es solo para profesionales.')
        return redirect('core:dashboard')
    
    # ✅ Obtener el profesional vinculado
    try:
        profesional = Profesional.objects.get(user=request.user)
    except Profesional.DoesNotExist:
        messages.error(request, '❌ No hay un profesional vinculado a tu cuenta.')
        return redirect('core:dashboard')
    
    # Importar modelos necesarios
    from agenda.models import Sesion
    from pacientes.models import Paciente
    
    # ✅ Obtener todos los pacientes que ha atendido
    pacientes_ids = Sesion.objects.filter(
        profesional=profesional
    ).values_list('paciente_id', flat=True).distinct()
    
    pacientes = Paciente.objects.filter(
        id__in=pacientes_ids,
        estado='activo'
    ).prefetch_related('sucursales')
    
    # ✅ Agregar estadísticas por paciente
    pacientes_data = []
    for paciente in pacientes:
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
        
        # Última sesión realizada
        ultima_sesion = Sesion.objects.filter(
            paciente=paciente,
            profesional=profesional,
            estado__in=['realizada', 'realizada_retraso']
        ).order_by('-fecha', '-hora_inicio').first()
        
        pacientes_data.append({
            'paciente': paciente,
            'total_sesiones': total_sesiones,
            'sesiones_realizadas': sesiones_realizadas,
            'proxima_sesion': proxima_sesion,
            'ultima_sesion': ultima_sesion,
        })
    
    # Ordenar por próxima sesión (los que tienen próxima sesión primero)
    pacientes_data.sort(key=lambda x: (
        x['proxima_sesion'] is None,
        x['proxima_sesion'].fecha if x['proxima_sesion'] else date.max
    ))
    
    context = {
        'profesional': profesional,
        'pacientes_data': pacientes_data,
        'total_pacientes': len(pacientes_data),
    }
    
    return render(request, 'profesionales/mis_pacientes.html', context)