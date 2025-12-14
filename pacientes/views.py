from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from .models import Paciente

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
    
    # Servicios contratados
    servicios = paciente.pacienteservicio_set.filter(activo=True)
    
    context = {
        'paciente': paciente,
        'sesiones': sesiones,
        'servicios': servicios,
    }
    return render(request, 'pacientes/detalle.html', context)