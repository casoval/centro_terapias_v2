from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from .models import TipoServicio, Sucursal
from datetime import date, timedelta

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
    
    for servicio in servicios:
        servicio.sesiones_semana = servicio.sesiones.filter(
            fecha__gte=inicio_semana,
            fecha__lte=fin_semana
        ).count()
        servicio.pacientes_activos = servicio.pacienteservicio_set.filter(activo=True).count()
    
    context = {
        'servicios': servicios,
        'buscar': buscar,
    }
    return render(request, 'servicios/lista_servicios.html', context)


@login_required
def detalle_servicio(request, pk):
    """Detalle de un tipo de servicio"""
    servicio = get_object_or_404(TipoServicio, pk=pk)
    
    # Últimas 10 sesiones
    sesiones = servicio.sesiones.all().order_by('-fecha', '-hora_inicio')[:10]
    
    # Profesionales que ofrecen este servicio
    profesionales = servicio.profesionales.filter(activo=True)
    
    # Pacientes que tienen este servicio contratado
    pacientes_activos = servicio.pacienteservicio_set.filter(activo=True).count()
    
    context = {
        'servicio': servicio,
        'sesiones': sesiones,
        'profesionales': profesionales,
        'pacientes_activos': pacientes_activos,
    }
    return render(request, 'servicios/detalle_servicio.html', context)


@login_required
def lista_sucursales(request):
    """Lista de sucursales activas"""
    sucursales = Sucursal.objects.filter(activa=True).order_by('nombre')
    
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
    
    # Últimas 10 sesiones
    sesiones = sucursal.sesiones.all().order_by('-fecha', '-hora_inicio')[:10]
    
    # Profesionales activos en esta sucursal
    profesionales = sucursal.profesionales.filter(activo=True)
    
    # Pacientes activos en esta sucursal
    pacientes = sucursal.pacientes.filter(estado='activo')
    
    context = {
        'sucursal': sucursal,
        'sesiones': sesiones,
        'profesionales': profesionales,
        'pacientes': pacientes,
    }
    return render(request, 'servicios/detalle_sucursal.html', context)
