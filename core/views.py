from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.contrib import messages
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
            
            # ✅ Si es paciente, ir a su cuenta
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
                
                # ✅ Si es paciente, ir a su cuenta
                if user.perfil.es_paciente():
                    return '/facturacion/mi-cuenta/'
        
        # Para otros roles, ir al dashboard
        return '/'


def logout_view(request):
    auth_logout(request)
    return redirect('core:login')


# ==================== GESTIÓN DE USUARIOS ====================

@login_required
def lista_usuarios(request):
    """Lista de usuarios del sistema con sus roles"""
    from django.contrib.auth.models import User
    from .models import PerfilUsuario
    
    # Obtener todos los usuarios excepto superusuarios
    usuarios = User.objects.filter(is_superuser=False).select_related('perfil').order_by('-is_active', 'username')
    
    # Búsqueda
    buscar = request.GET.get('q', '')
    if buscar:
        usuarios = usuarios.filter(
            Q(username__icontains=buscar) |
            Q(first_name__icontains=buscar) |
            Q(last_name__icontains=buscar) |
            Q(email__icontains=buscar)
        )
    
    # Filtro por rol
    rol_filtro = request.GET.get('rol', '')
    if rol_filtro:
        usuarios = usuarios.filter(perfil__rol=rol_filtro)
    
    # Agregar información adicional
    for usuario in usuarios:
        # Asegurar que tiene perfil
        if not hasattr(usuario, 'perfil'):
            PerfilUsuario.objects.get_or_create(
                user=usuario,
                defaults={'activo': True}
            )
    
    context = {
        'usuarios': usuarios,
        'buscar': buscar,
        'rol_filtro': rol_filtro,
        'roles': PerfilUsuario.ROL_CHOICES,
    }
    return render(request, 'core/usuarios/lista.html', context)


@login_required
def agregar_usuario(request):
    """Crear un nuevo usuario con su perfil"""
    from .forms import UsuarioForm, PerfilUsuarioForm
    from django.contrib.auth.models import User
    from .models import PerfilUsuario
    import core.models as core_models
    
    # ✅ Detectar si viene desde profesionales o pacientes
    desde_profesional = request.GET.get('from') == 'profesional'
    desde_paciente = request.GET.get('from') == 'paciente'
    
    if request.method == 'POST':
        usuario_form = UsuarioForm(request.POST)
        perfil_form = PerfilUsuarioForm(request.POST)
        
        if usuario_form.is_valid() and perfil_form.is_valid():
            # Desactivar signals temporalmente
            core_models._disable_signals = True
            
            try:
                # Crear usuario
                usuario = usuario_form.save()
                
                # Crear perfil
                perfil = perfil_form.save(commit=False)
                perfil.user = usuario
                
                # ✅ Forzar rol según origen
                if desde_profesional:
                    perfil.rol = 'profesional'
                elif desde_paciente:
                    perfil.rol = 'paciente'
                
                perfil.save()
                
                # Guardar relaciones many-to-many
                perfil_form.save_m2m()
                
                messages.success(request, f'✅ Usuario "{usuario.username}" creado exitosamente.')
                
                # ✅ Redirigir según origen
                if desde_profesional:
                    return redirect(f'/profesionales/nuevo/?user_id={usuario.id}')
                elif desde_paciente:
                    return redirect(f'/pacientes/nuevo/?user_id={usuario.id}')
                else:
                    return redirect('core:lista_usuarios')
            
            except Exception as e:
                messages.error(request, f'❌ Error al crear usuario: {str(e)}')
            
            finally:
                core_models._disable_signals = False
    else:
        usuario_form = UsuarioForm()
        perfil_form = PerfilUsuarioForm()
        
        # ✅ Pre-seleccionar rol según origen
        if desde_profesional:
            perfil_form.initial['rol'] = 'profesional'
        elif desde_paciente:
            perfil_form.initial['rol'] = 'paciente'
    
    context = {
        'usuario_form': usuario_form,
        'perfil_form': perfil_form,
        'es_nuevo': True,
        'desde_profesional': desde_profesional,
        'desde_paciente': desde_paciente,  # ✅ Pasar al template
    }
    return render(request, 'core/usuarios/agregar.html', context)


@login_required
def editar_usuario(request, pk):
    """Editar un usuario existente y su perfil"""
    from .forms import UsuarioForm, PerfilUsuarioForm
    from django.contrib.auth.models import User
    from .models import PerfilUsuario
    import core.models as core_models
    
    usuario = get_object_or_404(User, pk=pk)
    
    # Asegurar que tiene perfil
    perfil, created = PerfilUsuario.objects.get_or_create(
        user=usuario,
        defaults={'activo': True}
    )
    
    if request.method == 'POST':
        usuario_form = UsuarioForm(request.POST, instance=usuario)
        perfil_form = PerfilUsuarioForm(request.POST, instance=perfil)
        
        if usuario_form.is_valid() and perfil_form.is_valid():
            # Desactivar signals temporalmente
            core_models._disable_signals = True
            
            try:
                # Guardar usuario
                usuario = usuario_form.save()
                
                # Guardar perfil
                perfil = perfil_form.save()
                
                messages.success(request, f'✅ Usuario "{usuario.username}" actualizado exitosamente.')
                return redirect('core:lista_usuarios')
            
            except Exception as e:
                messages.error(request, f'❌ Error al actualizar usuario: {str(e)}')
            
            finally:
                core_models._disable_signals = False
    else:
        usuario_form = UsuarioForm(instance=usuario)
        perfil_form = PerfilUsuarioForm(instance=perfil)
    
    context = {
        'usuario_form': usuario_form,
        'perfil_form': perfil_form,
        'usuario': usuario,
        'es_nuevo': False,
    }
    return render(request, 'core/usuarios/editar.html', context)

@login_required
def eliminar_usuario(request, pk):
    """
    Eliminar un usuario (solo superadmin)
    ✅ MEJORADO: Maneja correctamente usuarios vinculados con profesionales/pacientes
    """
    from django.contrib.auth.models import User
    from django.db.models.deletion import ProtectedError
    
    if not request.user.is_superuser:
        messages.error(request, '⚠️ Solo los superadministradores pueden eliminar usuarios.')
        return redirect('core:lista_usuarios')
    
    usuario = get_object_or_404(User, pk=pk)
    
    # No permitir eliminar al propio usuario
    if usuario == request.user:
        messages.error(request, '⚠️ No puedes eliminar tu propio usuario.')
        return redirect('core:lista_usuarios')
    
    # ✅ Verificar vinculaciones y datos asociados
    tiene_profesional = hasattr(usuario, 'perfil') and usuario.perfil.profesional
    tiene_paciente = hasattr(usuario, 'perfil') and usuario.perfil.paciente
    
    # Contar datos relacionados
    datos_relacionados = {
        'sesiones': 0,
        'proyectos': 0,
    }
    
    if tiene_profesional:
        profesional = usuario.perfil.profesional
        # Contar sesiones del profesional
        if hasattr(profesional, 'sesiones'):
            datos_relacionados['sesiones'] = profesional.sesiones.count()
    
    if tiene_paciente:
        paciente = usuario.perfil.paciente
        # Contar sesiones del paciente
        if hasattr(paciente, 'sesiones'):
            datos_relacionados['sesiones'] += paciente.sesiones.count()
        # Contar proyectos del paciente
        if hasattr(paciente, 'proyectos'):
            datos_relacionados['proyectos'] = paciente.proyectos.count()
    
    # Si tiene datos relacionados, advertir y ofrecer alternativa
    tiene_datos = any(datos_relacionados.values())
    
    if request.method == 'POST':
        accion = request.POST.get('accion', 'eliminar')
        
        if accion == 'desactivar':
            # ✅ OPCIÓN SEGURA: Desactivar en lugar de eliminar
            usuario.is_active = False
            usuario.save()
            
            if hasattr(usuario, 'perfil'):
                usuario.perfil.activo = False
                usuario.perfil.save()
            
            messages.success(
                request, 
                f'✅ Usuario "{usuario.username}" desactivado exitosamente. '
                f'Ya no podrá iniciar sesión, pero sus datos se conservan.'
            )
            return redirect('core:lista_usuarios')
        
        else:  # eliminar
            if tiene_datos:
                # ❌ NO PERMITIR eliminación si tiene datos
                messages.error(
                    request,
                    f'❌ No se puede eliminar el usuario "{usuario.username}" porque tiene datos asociados. '
                    f'Usa la opción de DESACTIVAR en su lugar.'
                )
                return redirect('core:eliminar_usuario', pk=pk)
            
            try:
                username = usuario.username
                usuario.delete()
                messages.success(request, f'✅ Usuario "{username}" eliminado exitosamente.')
                return redirect('core:lista_usuarios')
            
            except ProtectedError as e:
                # Por si acaso alguna protección que no detectamos
                messages.error(
                    request,
                    f'❌ No se puede eliminar el usuario porque tiene datos protegidos. '
                    f'Usa la opción de DESACTIVAR en su lugar.'
                )
                return redirect('core:eliminar_usuario', pk=pk)
            
            except Exception as e:
                messages.error(request, f'❌ Error al eliminar usuario: {str(e)}')
                return redirect('core:eliminar_usuario', pk=pk)
    
    context = {
        'usuario': usuario,
        'tiene_datos': tiene_datos,
        'datos_relacionados': datos_relacionados,
        'tiene_profesional': tiene_profesional,
        'tiene_paciente': tiene_paciente,
    }
    return render(request, 'core/usuarios/eliminar.html', context)