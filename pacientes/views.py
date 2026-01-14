from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.db.models import Count, Q
from datetime import date
from .models import Paciente, PacienteServicio

@login_required
def lista_pacientes(request):
    """Lista de pacientes activos"""
    pacientes = Paciente.objects.filter(estado='activo').order_by('apellido', 'nombre')
    
    # Búsqueda
    buscar = request.GET.get('q', '')
    if buscar:
        pacientes = pacientes.filter(
            nombre__icontains=buscar
        ) | pacientes.filter(
            apellido__icontains=buscar
        )
    
    context = {
        'pacientes': pacientes,
        'buscar': buscar,
    }
    return render(request, 'pacientes/lista.html', context)

@login_required
def detalle_paciente(request, pk):
    """Detalle de un paciente"""
    paciente = get_object_or_404(Paciente, pk=pk)
    
    # Últimas 10 sesiones
    sesiones = paciente.sesiones.all().order_by('-fecha', '-hora_inicio')[:10]
    
    # ✅ CORRECCIÓN: Servicios contratados usando consulta directa
    servicios = PacienteServicio.objects.filter(
        paciente=paciente,
        activo=True
    ).select_related('servicio')
    
    context = {
        'paciente': paciente,
        'sesiones': sesiones,
        'servicios': servicios,
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