from django.shortcuts import render, redirect
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.db.models import Count, Sum, Q
from datetime import date, timedelta
from decimal import Decimal


@login_required
def dashboard(request):
    """Dashboard principal con estadísticas"""
    
    try:
        from agenda.models import Sesion
        from pacientes.models import Paciente
        from servicios.models import Sucursal, TipoServicio
        from profesionales.models import Profesional
        
        hoy = date.today()
        inicio_semana = hoy - timedelta(days=hoy.weekday())
        fin_semana = inicio_semana + timedelta(days=6)
        
        # ===== ESTADÍSTICAS PRINCIPALES =====
        
        # Sesiones de hoy
        sesiones_hoy = Sesion.objects.filter(fecha=hoy).count()
        
        # Pacientes activos
        pacientes_activos = Paciente.objects.filter(estado='activo').count()
        
        # Sesiones de la semana
        sesiones_semana = Sesion.objects.filter(
            fecha__gte=inicio_semana,
            fecha__lte=fin_semana
        ).count()
        
        # Pendientes de pago
        pendientes_pago = Sesion.objects.filter(
            estado__in=['realizada', 'realizada_retraso', 'falta'],
            pagado=False
        ).aggregate(
            total=Sum('monto_cobrado')
        )['total'] or Decimal('0.00')
        
        # ===== NUEVAS ESTADÍSTICAS =====
        
        # Sucursales activas
        sucursales_activas = Sucursal.objects.filter(activa=True).count()
        
        # Profesionales activos
        profesionales_activos = Profesional.objects.filter(activo=True).count()
        
        # Servicios activos
        servicios_activos = TipoServicio.objects.filter(activo=True).count()
        
        # ===== TOP 5 POR CATEGORÍA =====
        
        # Top 5 Sucursales (por cantidad de sesiones esta semana)
        top_sucursales = Sucursal.objects.filter(
            activa=True
        ).annotate(
            sesiones_semana=Count('sesiones', filter=Q(
                sesiones__fecha__gte=inicio_semana,
                sesiones__fecha__lte=fin_semana
            ))
        ).order_by('-sesiones_semana')[:5]
        
        # Top 5 Profesionales (por cantidad de sesiones esta semana)
        top_profesionales = Profesional.objects.filter(
            activo=True
        ).annotate(
            sesiones_semana=Count('sesiones', filter=Q(
                sesiones__fecha__gte=inicio_semana,
                sesiones__fecha__lte=fin_semana
            ))
        ).order_by('-sesiones_semana')[:5]
        
        # Top 5 Servicios (por cantidad de sesiones esta semana)
        top_servicios = TipoServicio.objects.filter(
            activo=True
        ).annotate(
            sesiones_semana=Count('sesiones', filter=Q(
                sesiones__fecha__gte=inicio_semana,
                sesiones__fecha__lte=fin_semana
            ))
        ).order_by('-sesiones_semana')[:5]
        
        # ===== SESIONES =====
        
        # Próximas sesiones (próximos 7 días)
        proximas_sesiones = Sesion.objects.filter(
            fecha__gte=hoy,
            fecha__lte=hoy + timedelta(days=7),
            estado='programada'
        ).select_related('paciente', 'servicio', 'profesional', 'sucursal').order_by('fecha', 'hora_inicio')[:10]
        
        # Sesiones recientes
        sesiones_recientes = Sesion.objects.filter(
            fecha__lte=hoy
        ).select_related('paciente', 'servicio', 'profesional', 'sucursal').order_by('-fecha', '-hora_inicio')[:10]
        
        context = {
            # Estadísticas principales
            'sesiones_hoy': sesiones_hoy,
            'pacientes_activos': pacientes_activos,
            'sesiones_semana': sesiones_semana,
            'pendientes_pago': pendientes_pago,
            
            # Nuevas estadísticas
            'sucursales_activas': sucursales_activas,
            'profesionales_activos': profesionales_activos,
            'servicios_activos': servicios_activos,
            
            # Top 5
            'top_sucursales': top_sucursales,
            'top_profesionales': top_profesionales,
            'top_servicios': top_servicios,
            
            # Sesiones
            'proximas_sesiones': proximas_sesiones,
            'sesiones_recientes': sesiones_recientes,
        }
        
    except Exception as e:
        # Si hay error, mostrar dashboard básico
        context = {
            'sesiones_hoy': 0,
            'pacientes_activos': 0,
            'sesiones_semana': 0,
            'pendientes_pago': Decimal('0.00'),
            'sucursales_activas': 0,
            'profesionales_activos': 0,
            'servicios_activos': 0,
            'top_sucursales': [],
            'top_profesionales': [],
            'top_servicios': [],
            'proximas_sesiones': [],
            'sesiones_recientes': [],
            'error': str(e),
        }
    
    return render(request, 'core/dashboard.html', context)


class CustomLoginView(LoginView):
    template_name = 'core/login.html'
    redirect_authenticated_user = True


def logout_view(request):
    auth_logout(request)
    return redirect('core:login')