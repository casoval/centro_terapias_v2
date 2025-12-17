from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from .models import Profesional
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
