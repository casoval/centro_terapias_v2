from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.contrib import messages
from django.db.models import Count, Sum, Q
from datetime import date, timedelta, datetime, time
from decimal import Decimal
from calendar import monthrange
from core.utils import solo_sus_sucursales


@login_required
@solo_sus_sucursales  # ✅ Aplicar filtrado automático
def dashboard(request):
    """Dashboard principal con estadísticas FILTRADAS por sucursal"""
    
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
        inicio_mes = hoy.replace(day=1)
        _, ultimo_dia = monthrange(hoy.year, hoy.month)
        fin_mes = hoy.replace(day=ultimo_dia)
        
        # ✅ OBTENER SUCURSALES DEL USUARIO (ya viene del decorator)
        sucursales_usuario = request.sucursales_usuario
        
        # ===== ESTADÍSTICAS PRINCIPALES (FILTRADAS) =====
        
        # Base query de sesiones según sucursales
        if sucursales_usuario is not None:
            if sucursales_usuario.exists():
                sesiones_base = Sesion.objects.filter(sucursal__in=sucursales_usuario)
                pacientes_base = Paciente.objects.filter(sucursales__in=sucursales_usuario).distinct()
                profesionales_base = Profesional.objects.filter(sucursales__in=sucursales_usuario).distinct()
                servicios_base = TipoServicio.objects.all()  # Los servicios son globales
            else:
                # Sin sucursales asignadas = no ve nada
                sesiones_base = Sesion.objects.none()
                pacientes_base = Paciente.objects.none()
                profesionales_base = Profesional.objects.none()
                servicios_base = TipoServicio.objects.none()
        else:
            # Superadmin = ve todo
            sesiones_base = Sesion.objects.all()
            pacientes_base = Paciente.objects.all()
            profesionales_base = Profesional.objects.all()
            servicios_base = TipoServicio.objects.all()
        
        # Sesiones de hoy
        sesiones_hoy = sesiones_base.filter(fecha=hoy).count()
        
        # Pacientes activos
        pacientes_activos = pacientes_base.filter(estado='activo').count()
        
        # Sesiones de la semana
        sesiones_semana = sesiones_base.filter(
            fecha__gte=inicio_semana,
            fecha__lte=fin_semana
        ).count()
        
        # Sesiones del mes actual
        sesiones_mes = sesiones_base.filter(
            fecha__gte=inicio_mes,
            fecha__lte=fin_mes
        ).count()
        
        # ===== NUEVAS ESTADÍSTICAS (FILTRADAS) =====
        
        # Sucursales (mostrar solo las asignadas)
        if sucursales_usuario is not None and sucursales_usuario.exists():
            sucursales_activas = sucursales_usuario.filter(activa=True).count()
            sucursales_para_top = sucursales_usuario.filter(activa=True)
        else:
            sucursales_activas = Sucursal.objects.filter(activa=True).count()
            sucursales_para_top = Sucursal.objects.filter(activa=True)
        
        # Profesionales activos (solo de sus sucursales)
        profesionales_activos = profesionales_base.filter(activo=True).count()
        
        # Servicios activos (globales, pero se pueden filtrar)
        servicios_activos = servicios_base.filter(activo=True).count()
        
        # ===== TOP 5 POR CATEGORÍA (FILTRADO) =====
        
        # Top 5 Sucursales (solo las asignadas)
        top_sucursales = sucursales_para_top.annotate(
            sesiones_mes=Count('sesiones', filter=Q(
                sesiones__fecha__gte=inicio_mes,
                sesiones__fecha__lte=fin_mes
            ))
        ).order_by('-sesiones_mes')[:5]
        
        # Top 5 Profesionales (solo de sus sucursales)
        # ✅ FIX: cuando sucursales_usuario is None (superadmin) no se filtra por sucursal
        prof_filter = Q(
            sesiones__fecha__gte=inicio_mes,
            sesiones__fecha__lte=fin_mes,
        )
        if sucursales_usuario is not None:
            prof_filter &= Q(sesiones__sucursal__in=sucursales_para_top)

        top_profesionales = profesionales_base.filter(
            activo=True
        ).annotate(
            sesiones_mes=Count('sesiones', filter=prof_filter)
        ).order_by('-sesiones_mes')[:5]
        
        # Top 5 Servicios (filtrado por sesiones de sus sucursales)
        if sucursales_usuario is not None and sucursales_usuario.exists():
            top_servicios = servicios_base.filter(
                activo=True
            ).annotate(
                sesiones_mes=Count('sesiones', filter=Q(
                    sesiones__fecha__gte=inicio_mes,
                    sesiones__fecha__lte=fin_mes,
                    sesiones__sucursal__in=sucursales_usuario
                ))
            ).order_by('-sesiones_mes')[:5]
        else:
            top_servicios = servicios_base.filter(
                activo=True
            ).annotate(
                sesiones_mes=Count('sesiones', filter=Q(
                    sesiones__fecha__gte=inicio_mes,
                    sesiones__fecha__lte=fin_mes
                ))
            ).order_by('-sesiones_mes')[:5]
        
        # ===== PRÓXIMAS SESIONES (FILTRADAS) =====
        
        todas_sesiones = sesiones_base.filter(
            fecha__gte=hoy,
            fecha__lte=hoy + timedelta(days=7),
            estado='programada'
        ).select_related(
            'paciente', 'servicio', 'profesional', 'sucursal'
        ).order_by('fecha', 'hora_inicio')
        
        sesiones_filtradas = []
        
        for sesion in todas_sesiones:
            if sesion.fecha == hoy:
                if sesion.hora_fin > hora_actual:
                    if sesion.hora_inicio <= hora_actual < sesion.hora_fin:
                        sesion.estado_tiempo = 'en_curso'
                    else:
                        sesion.estado_tiempo = 'proxima'
                    sesiones_filtradas.append(sesion)
            else:
                sesion.estado_tiempo = 'proxima'
                sesiones_filtradas.append(sesion)
        
        proximas_sesiones = sesiones_filtradas[:30]
        
        # Sesiones recientes (filtradas)
        sesiones_recientes = sesiones_base.filter(
            fecha__lte=hoy
        ).select_related(
            'paciente', 'servicio', 'profesional', 'sucursal'
        ).order_by('-fecha', '-hora_inicio')[:10]
        
        context = {
            # Estadísticas principales
            'sesiones_hoy': sesiones_hoy,
            'pacientes_activos': pacientes_activos,
            'sesiones_semana': sesiones_semana,
            'sesiones_mes': sesiones_mes,
            
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
            'sucursales_usuario': sucursales_usuario,  # ✅ Pasar al template
        }
        
    except Exception as e:
        import traceback
        print("❌ ERROR EN DASHBOARD:")
        print(traceback.format_exc())
        
        context = {
            'sesiones_hoy': 0,
            'pacientes_activos': 0,
            'sesiones_semana': 0,
            'sesiones_mes': 0,
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
        
        if not user.is_superuser:
            if hasattr(user, 'perfil'):
                if user.perfil.es_profesional():
                    return '/agenda/'
                if user.perfil.es_paciente():
                    return '/facturacion/mi-cuenta/'
        
        return '/'


def logout_view(request):
    from django.contrib.auth import logout as auth_logout
    auth_logout(request)
    return redirect('core:login')

# ==================== GESTIÓN DE USUARIOS ====================

@login_required
def lista_usuarios(request):
    """Lista de usuarios del sistema con sus roles"""
    from django.contrib.auth.models import User
    from .models import PerfilUsuario

    # Solo usuarios no-superuser que tengan perfil creado.
    # perfil__isnull=False excluye Users huerfanos (sin PerfilUsuario)
    usuarios = User.objects.filter(
        is_superuser=False,
        perfil__isnull=False
    ).select_related('perfil').order_by('-is_active', 'username')

    # Busqueda
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
                perfil.refresh_from_db()  # forzar lectura real desde la BD

                # ✅ SINCRONIZACIÓN BIDIRECCIONAL usando perfil ya guardado
                from pacientes.models import Paciente as PacienteModel
                from profesionales.models import Profesional as ProfModel

                if perfil.paciente_id:
                    PacienteModel.objects.filter(
                        id=perfil.paciente_id
                    ).update(user=usuario)
                else:
                    PacienteModel.objects.filter(user=usuario).update(user=None)

                if perfil.profesional_id:
                    ProfModel.objects.filter(
                        id=perfil.profesional_id
                    ).update(user=usuario)
                else:
                    ProfModel.objects.filter(user=usuario).update(user=None)

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
    
    # Solo editar usuarios que tengan perfil (los huerfanos no deben ser editables)
    usuario = get_object_or_404(User, pk=pk, is_superuser=False)

    try:
        perfil = usuario.perfil
    except PerfilUsuario.DoesNotExist:
        messages.error(request, '⚠️ Este usuario no tiene perfil válido. Elimínalo desde el admin de Django.')
        return redirect('core:lista_usuarios')

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

                # ✅ SINCRONIZACIÓN BIDIRECCIONAL usando perfil ya guardado
                from pacientes.models import Paciente as PacienteModel
                from profesionales.models import Profesional as ProfModel
                perfil.refresh_from_db()  # forzar lectura real desde la BD

                # Sync paciente
                if perfil.paciente_id:
                    PacienteModel.objects.filter(
                        id=perfil.paciente_id
                    ).update(user=usuario)
                    PacienteModel.objects.filter(
                        user=usuario
                    ).exclude(id=perfil.paciente_id).update(user=None)
                else:
                    PacienteModel.objects.filter(user=usuario).update(user=None)

                # Sync profesional
                if perfil.profesional_id:
                    ProfModel.objects.filter(
                        id=perfil.profesional_id
                    ).update(user=usuario)
                    ProfModel.objects.filter(
                        user=usuario
                    ).exclude(id=perfil.profesional_id).update(user=None)
                else:
                    ProfModel.objects.filter(user=usuario).update(user=None)

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
                import core.models as core_models
                username = usuario.username

                # Desactivar signals para evitar que se recree el perfil
                core_models._disable_signals = True
                try:
                    # Limpiar vinculaciones bidireccionales ANTES de eliminar
                    if hasattr(usuario, 'perfil'):
                        perfil = usuario.perfil
                        if perfil.paciente:
                            try:
                                from pacientes.models import Paciente as PacienteModel
                                PacienteModel.objects.filter(user=usuario).update(user=None)
                            except Exception:
                                pass
                        if perfil.profesional:
                            try:
                                from profesionales.models import Profesional as ProfModel
                                ProfModel.objects.filter(user=usuario).update(user=None)
                            except Exception:
                                pass
                        perfil.delete()  # Eliminar perfil primero
                    usuario.delete()
                finally:
                    core_models._disable_signals = False

                messages.success(request, f'✅ Usuario "{username}" eliminado exitosamente.')
                return redirect('core:lista_usuarios')

            except ProtectedError:
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

# =====================================================================
# REEMPLAZAR la función crear_usuarios_pacientes_masivo en views.py
# =====================================================================

@login_required
def crear_usuarios_pacientes_masivo(request):
    """
    Crea cuentas masivamente para pacientes sin acceso.

    - Usuario:    NOMBRE + palabra  (editable por fila)
    - Contraseña: APELLIDO + palabra (editable por fila)

    Si el admin edita el campo en la tabla, se usa ese valor.
    Si lo deja como está, se usa el valor auto-generado.
    """
    import unicodedata
    from pacientes.models import Paciente
    from .models import PerfilUsuario
    from django.contrib.auth.models import User
    import core.models as core_models

    # Solo superadmin y gerentes
    if not request.user.is_superuser:
        if not (hasattr(request.user, 'perfil') and request.user.perfil.es_gerente()):
            messages.error(request, '⚠️ No tienes permisos para esta acción.')
            return redirect('core:lista_usuarios')

    # ─── Helpers ───────────────────────────────────────────────────────────
    def quitar_acentos(texto):
        texto = unicodedata.normalize('NFKD', texto)
        return ''.join(c for c in texto if not unicodedata.combining(c))

    def solo_alfanum_mayus(texto):
        """Solo alfanumérico en mayúsculas — para la BASE (nombre/apellido)."""
        return ''.join(c for c in quitar_acentos(texto).upper() if c.isalnum())

    def limpiar_palabra(texto):
        """
        Para la palabra añadida por el usuario:
        permite letras, números y los caracteres válidos en usernames de Django: @ . + - _
        """
        if not texto:
            return ''
        texto = quitar_acentos(texto).upper().replace(' ', '')
        return ''.join(c for c in texto if c.isalnum() or c in '@.+-_')

    def gen_username(paciente, palabra):
        return solo_alfanum_mayus(paciente.nombre or '') + limpiar_palabra(palabra)

    def gen_password(paciente, palabra):
        return solo_alfanum_mayus(paciente.apellido or '') + limpiar_palabra(palabra)

    # ─── Pacientes SIN cuenta vinculada ────────────────────────────────────
    pacientes_sin_cuenta = Paciente.objects.filter(
        estado='activo',
        perfil_usuario__isnull=True
    ).order_by('nombre', 'apellido')

    # ─── POST ───────────────────────────────────────────────────────────────
    if request.method == 'POST':
        ids_seleccionados = request.POST.getlist('pacientes_ids')
        palabra_usuario  = request.POST.get('palabra_usuario', '').strip()
        palabra_password = request.POST.get('palabra_password', '').strip()

        if not ids_seleccionados:
            messages.warning(request, '⚠️ No seleccionaste ningún paciente.')
            return redirect('core:crear_usuarios_pacientes_masivo')

        # Palabras clave son opcionales — si están vacías, la base es solo nombre/apellido
        resultados = {'creados': [], 'errores': []}
        usernames_en_lote = set()

        core_models._disable_signals = True
        try:
            for paciente_id in ids_seleccionados:
                try:
                    paciente = Paciente.objects.get(id=paciente_id, perfil_usuario__isnull=True)
                except Paciente.DoesNotExist:
                    resultados['errores'].append({
                        'nombre': f'Paciente #{paciente_id}',
                        'error': 'Ya tiene cuenta o no existe'
                    })
                    continue

                # ── Leer valores del form (el admin pudo editarlos) ──
                username_raw = request.POST.get(f'username_{paciente_id}', '').strip()
                password_raw = request.POST.get(f'password_{paciente_id}', '').strip()

                # Si fueron editados manualmente usar ese valor; si no, fórmula automática
                username_base = limpiar_palabra(username_raw) if username_raw else gen_username(paciente, palabra_usuario)
                pwd           = password_raw if password_raw else gen_password(paciente, palabra_password)

                if not username_base or not pwd:
                    resultados['errores'].append({
                        'nombre': f'{paciente.nombre} {paciente.apellido}',
                        'error': 'Usuario o contraseña vacíos'
                    })
                    continue

                # Resolver duplicados con sufijo numérico
                username = username_base
                contador = 2
                while (User.objects.filter(username=username).exists() or
                       username in usernames_en_lote):
                    username = f"{username_base}{contador}"
                    contador += 1
                usernames_en_lote.add(username)

                try:
                    user = User.objects.create_user(
                        username=username,
                        first_name=paciente.nombre or '',
                        last_name=paciente.apellido or '',
                        password=pwd,
                        is_active=True,
                    )

                    perfil, _ = PerfilUsuario.objects.get_or_create(
                        user=user,
                        defaults={'activo': True}
                    )
                    perfil.rol      = 'paciente'
                    perfil.paciente = paciente
                    perfil.activo   = True
                    perfil.save()

                    # ✅ SINCRONIZACIÓN BIDIRECCIONAL: paciente.user debe apuntar
                    # al usuario recién creado. Sin esto, cuando el paciente inicie
                    # sesión, request.user.perfil.paciente devuelve None porque
                    # paciente.user quedaba vacío.
                    paciente.user = user
                    paciente.save(update_fields=['user'])

                    resultados['creados'].append({
                        'nombre':   f'{paciente.nombre} {paciente.apellido}',
                        'username': username,
                        'password': pwd,
                    })

                except Exception as e:
                    try:
                        User.objects.filter(username=username).delete()
                    except Exception:
                        pass
                    resultados['errores'].append({
                        'nombre': f'{paciente.nombre} {paciente.apellido}',
                        'error': str(e)
                    })

        finally:
            core_models._disable_signals = False

        total   = len(resultados['creados'])
        errores = len(resultados['errores'])

        if total > 0:
            messages.success(request, f'✅ {total} cuenta(s) creada(s) exitosamente.')
        if errores > 0:
            messages.warning(request, f'⚠️ {errores} paciente(s) no pudieron procesarse.')

        context = {
            'resultados':         resultados,
            'mostrar_resultados': True,
        }
        return render(request, 'core/usuarios/masivo_pacientes.html', context)

    # ─── GET: preview ───────────────────────────────────────────────────────
    preview_pacientes = []
    for p in pacientes_sin_cuenta:
        preview_pacientes.append({
            'paciente':      p,
            'nombre_base':   solo_alfanum_mayus(p.nombre or ''),
            'apellido_base': solo_alfanum_mayus(p.apellido or ''),
        })

    context = {
        'preview_pacientes':  preview_pacientes,
        'total_sin_cuenta':   len(preview_pacientes),
        'mostrar_resultados': False,
    }
    return render(request, 'core/usuarios/masivo_pacientes.html', context)


# =====================================================================
# GUARDAR TEMA DE INTERFAZ POR USUARIO
# =====================================================================

from django.http import JsonResponse
from django.views.decorators.http import require_POST

@login_required
@require_POST
def guardar_tema(request):
    """
    Guarda el tema de interfaz seleccionado por el usuario en su perfil.
    Recibe: JSON { "tema": "atardecer" }  o  POST campo 'tema'
    """
    import json

    # Leer tema desde JSON body o desde POST form
    try:
        data = json.loads(request.body)
        tema = data.get('tema', '').strip()
    except (json.JSONDecodeError, UnicodeDecodeError):
        tema = request.POST.get('tema', '').strip()

    # Validar que sea un tema permitido
    TEMAS_VALIDOS = {'atardecer', 'aurora', 'cyber', 'ocean', 'forest', 'galaxy', 'tropical', 'spring', 'sky'}
    if tema not in TEMAS_VALIDOS:
        return JsonResponse({'ok': False, 'error': 'Tema no válido'}, status=400)

    # Guardar en el perfil del usuario
    try:
        perfil = request.user.perfil
        perfil.tema_ui = tema
        perfil.save(update_fields=['tema_ui'])
        return JsonResponse({'ok': True, 'tema': tema})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)