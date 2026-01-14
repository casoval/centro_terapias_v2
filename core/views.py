from django.shortcuts import render, redirect
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.db.models import Count, Sum, Q
from datetime import date, timedelta, datetime, time
from decimal import Decimal


@login_required
def dashboard(request):
    """Dashboard principal con estadísticas"""
    
    # ✅ REDIRECCIONAR SEGÚN ROL
    if not request.user.is_superuser:
        if hasattr(request.user, 'perfil'):
            # Si es profesional, ir a su agenda
            if request.user.perfil.es_profesional():
                return redirect('agenda:calendario')
            
            # ✅ NUEVO: Si es paciente, ir a su cuenta
            if request.user.perfil.es_paciente():
                return redirect('facturacion:mi_cuenta')
    
    try:
        from agenda.models import Sesion
        from pacientes.models import Paciente
        from servicios.models import Sucursal, TipoServicio
        from profesionales.models import Profesional
        
        hoy = date.today()
        ahora = datetime.now()
        hora_actual = ahora.time()
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
        
        # ✅ CORREGIDO: Pendientes de pago
        # Obtener sesiones realizadas con monto > 0
        sesiones_pendientes = Sesion.objects.filter(
            estado__in=['realizada', 'realizada_retraso', 'falta'],
            proyecto__isnull=True,  # Excluir sesiones de proyectos
            monto_cobrado__gt=0
        ).select_related('paciente')
        
        # Calcular total pendiente sumando saldo_pendiente de cada sesión
        total_pendiente = Decimal('0.00')
        for sesion in sesiones_pendientes:
            if sesion.saldo_pendiente > 0:
                total_pendiente += sesion.saldo_pendiente
        
        pendientes_pago = total_pendiente
        
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
        
        # ===== PRÓXIMAS SESIONES CON FILTRADO INTELIGENTE =====
        
        # Obtener todas las sesiones programadas desde hoy hasta 7 días
        todas_sesiones = Sesion.objects.filter(
            fecha__gte=hoy,
            fecha__lte=hoy + timedelta(days=7),
            estado='programada'
        ).select_related(
            'paciente', 'servicio', 'profesional', 'sucursal'
        ).order_by('fecha', 'hora_inicio')
        
        # Filtrar sesiones según la hora actual
        sesiones_filtradas = []
        
        for sesion in todas_sesiones:
            # Si es HOY
            if sesion.fecha == hoy:
                # Solo mostrar si:
                # 1. Está EN CURSO (hora_inicio <= ahora < hora_fin)
                # 2. AÚN NO EMPEZÓ (hora_inicio > ahora)
                # NO mostrar si ya terminó (hora_fin <= ahora)
                
                if sesion.hora_fin > hora_actual:
                    # Determinar si está en curso o es próxima
                    if sesion.hora_inicio <= hora_actual < sesion.hora_fin:
                        sesion.estado_tiempo = 'en_curso'
                    else:
                        sesion.estado_tiempo = 'proxima'
                    
                    sesiones_filtradas.append(sesion)
            else:
                # Si es día futuro, siempre mostrar
                sesion.estado_tiempo = 'proxima'
                sesiones_filtradas.append(sesion)
        
        # Limitar a máximo 30 sesiones
        proximas_sesiones = sesiones_filtradas[:30]
        
        # Sesiones recientes
        sesiones_recientes = Sesion.objects.filter(
            fecha__lte=hoy
        ).select_related(
            'paciente', 'servicio', 'profesional', 'sucursal'
        ).order_by('-fecha', '-hora_inicio')[:10]
        
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
            
            # Para el template
            'hora_actual': hora_actual,
            'fecha_actual': hoy,
        }
        
    except Exception as e:
        # Si hay error, mostrar dashboard básico con el error para debugging
        import traceback
        print("❌ ERROR EN DASHBOARD:")
        print(traceback.format_exc())
        
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
    
    def get_success_url(self):
        """Redirigir según el rol del usuario después del login"""
        user = self.request.user
        
        # ✅ Redireccionar según rol
        if not user.is_superuser:
            if hasattr(user, 'perfil'):
                # Si es profesional, ir directo a agenda
                if user.perfil.es_profesional():
                    return '/agenda/'
                
                # ✅ NUEVO: Si es paciente, ir a su cuenta
                if user.perfil.es_paciente():
                    return '/facturacion/mi-cuenta/'
        
        # Para otros roles, ir al dashboard
        return '/'


def logout_view(request):
    auth_logout(request)
    return redirect('core:login')