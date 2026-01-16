from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Count, Q
from .models import Profesional
from .forms import ProfesionalForm
from datetime import date, timedelta

@login_required
def lista_profesionales(request):
    """Lista de profesionales activos"""
    profesionales = Profesional.objects.filter(activo=True).order_by('apellido', 'nombre')
    
    # Búsqueda
    buscar = request.GET.get('q', '')
    if buscar:
        profesionales = profesionales.filter(
            Q(nombre__icontains=buscar) |
            Q(apellido__icontains=buscar) |
            Q(especialidad__icontains=buscar)
        )
    
    # Agregar estadísticas
    hoy = date.today()
    inicio_semana = hoy - timedelta(days=hoy.weekday())
    fin_semana = inicio_semana + timedelta(days=6)
    
    for profesional in profesionales:
        profesional.sesiones_semana = profesional.sesiones.filter(
            fecha__gte=inicio_semana,
            fecha__lte=fin_semana
        ).count()
        profesional.total_pacientes = profesional.get_pacientes().count()
    
    context = {
        'profesionales': profesionales,
        'buscar': buscar,
    }
    return render(request, 'profesionales/lista.html', context)


@login_required
def detalle_profesional(request, pk):
    """Detalle de un profesional"""
    profesional = get_object_or_404(Profesional, pk=pk)
    
    # Últimas 10 sesiones
    sesiones = profesional.sesiones.all().order_by('-fecha', '-hora_inicio')[:10]
    
    # Servicios que ofrece
    servicios = profesional.servicios.filter(activo=True)
    
    # Sucursales donde trabaja
    sucursales = profesional.sucursales.filter(activa=True)
    
    # Pacientes que atiende
    pacientes = profesional.get_pacientes()[:10]
    
    context = {
        'profesional': profesional,
        'sesiones': sesiones,
        'servicios': servicios,
        'sucursales': sucursales,
        'pacientes': pacientes,
    }
    return render(request, 'profesionales/detalle.html', context)


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