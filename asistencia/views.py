from datetime import date, timedelta
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Count, Q, Sum
from django.utils import timezone
from django.contrib.auth.models import User

from .models import (
    ZonaAsistencia, HorarioPredeterminado, ConfigAsistencia,
    FechaEspecial, EnrolamientoFacial, PermisoReenrolamiento, RegistroAsistencia
)
from .forms import (
    MarcarAsistenciaForm, EditarObservacionForm, ZonaAsistenciaForm,
    HorarioPredeterminadoForm, ConfigAsistenciaForm, FechaEspecialForm, PermisoReenrolamientoForm
)
from .services import ValidadorAsistencia


# ── Decoradores de permiso ───────────────────────────────────────────────────

def solo_admin(view_func):
    """Solo superadmin o gerente."""
    from functools import wraps
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('core:login')
        if request.user.is_superuser:
            return view_func(request, *args, **kwargs)
        if hasattr(request.user, 'perfil') and request.user.perfil.rol in ['gerente']:
            return view_func(request, *args, **kwargs)
        messages.error(request, 'No tienes permiso para acceder a esta sección.')
        return redirect('core:dashboard')
    return wrapper


def solo_profesional(view_func):
    from functools import wraps
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('core:login')
        if hasattr(request.user, 'perfil') and request.user.perfil.rol == 'profesional':
            return view_func(request, *args, **kwargs)
        messages.error(request, 'Esta sección es solo para profesionales.')
        return redirect('core:dashboard')
    return wrapper


# ══════════════════════════════════════════════════════════════════════════════
# PANEL ADMINISTRADOR
# ══════════════════════════════════════════════════════════════════════════════

@solo_admin
def panel_admin(request):
    """Resumen diario — vista principal del admin."""
    hoy = timezone.now().date()

    profesionales = User.objects.filter(
        perfil__rol='profesional', is_active=True
    ).select_related('perfil__profesional', 'enrolamiento')

    datos = []
    for user in profesionales:
        registros_hoy = user.registros_asistencia.filter(
            fecha_hora__date=hoy,
            estado__in=['PUNTUAL', 'TARDANZA']
        ).order_by('fecha_hora')

        entrada = registros_hoy.filter(tipo='ENTRADA').first()
        salida = registros_hoy.filter(tipo='SALIDA').first()
        intentos_fallidos = user.registros_asistencia.filter(
            fecha_hora__date=hoy,
            estado__in=['DENEGADO_GPS', 'DENEGADO_BIO']
        ).count()

        try:
            enrolamiento = user.enrolamiento
            estado_enrolamiento = enrolamiento.estado
        except EnrolamientoFacial.DoesNotExist:
            estado_enrolamiento = 'pendiente'

        if estado_enrolamiento != 'enrolado':
            estado_dia = 'sin_enrolar'
        elif entrada:
            estado_dia = entrada.estado
        else:
            estado_dia = 'ausente'

        datos.append({
            'user': user,
            'profesional': getattr(getattr(user, 'perfil', None), 'profesional', None),
            'entrada': entrada,
            'salida': salida,
            'estado_dia': estado_dia,
            'estado_enrolamiento': estado_enrolamiento,
            'intentos_fallidos': intentos_fallidos,
        })

    resumen = {
        'presentes': sum(1 for d in datos if d['estado_dia'] in ['PUNTUAL', 'TARDANZA']),
        'tardanzas': sum(1 for d in datos if d['estado_dia'] == 'TARDANZA'),
        'ausentes': sum(1 for d in datos if d['estado_dia'] == 'ausente'),
        'sin_enrolar': sum(1 for d in datos if d['estado_dia'] == 'sin_enrolar'),
    }

    return render(request, 'asistencia/admin/panel.html', {
        'datos': datos,
        'resumen': resumen,
        'hoy': hoy,
        'seccion': 'resumen',
    })


@solo_admin
def zonas_gps(request):
    """Gestión de zonas GPS — listado y creación."""
    zonas = ZonaAsistencia.objects.select_related('sucursal', 'horario_predeterminado').all()

    if request.method == 'POST':
        form = ZonaAsistenciaForm(request.POST)
        if form.is_valid():
            zona = form.save()
            # Crear horario predeterminado automáticamente
            HorarioPredeterminado.objects.get_or_create(zona=zona)
            messages.success(request, f'Zona "{zona.nombre}" creada correctamente.')
            return redirect('asistencia:zonas_gps')
    else:
        form = ZonaAsistenciaForm()

    return render(request, 'asistencia/admin/zonas.html', {
        'zonas': zonas,
        'form': form,
        'seccion': 'zonas',
    })


@solo_admin
def editar_zona(request, pk):
    zona = get_object_or_404(ZonaAsistencia, pk=pk)
    if request.method == 'POST':
        form = ZonaAsistenciaForm(request.POST, instance=zona)
        if form.is_valid():
            form.save()
            messages.success(request, f'Zona "{zona.nombre}" actualizada.')
            return redirect('asistencia:zonas_gps')
    else:
        form = ZonaAsistenciaForm(instance=zona)
    return render(request, 'asistencia/admin/editar_zona.html', {
        'form': form, 'zona': zona, 'seccion': 'zonas'
    })


@solo_admin
def horarios(request):
    """Gestión de horarios predeterminados y personalizados."""
    zonas = ZonaAsistencia.objects.prefetch_related(
        'horario_predeterminado', 'configs__user__perfil__profesional'
    ).filter(activa=True)

    configs_personalizadas = ConfigAsistencia.objects.filter(
        personalizado=True
    ).select_related('user__perfil__profesional', 'zona', 'modificado_por')

    return render(request, 'asistencia/admin/horarios.html', {
        'zonas': zonas,
        'configs_personalizadas': configs_personalizadas,
        'seccion': 'horarios',
    })


@solo_admin
def editar_horario_predeterminado(request, zona_pk):
    zona = get_object_or_404(ZonaAsistencia, pk=zona_pk)
    horario, _ = HorarioPredeterminado.objects.get_or_create(zona=zona)

    if request.method == 'POST':
        form = HorarioPredeterminadoForm(request.POST, instance=horario)
        if form.is_valid():
            form.save()
            messages.success(request, f'Horario de "{zona.nombre}" actualizado.')
            return redirect('asistencia:horarios')
    else:
        form = HorarioPredeterminadoForm(instance=horario)

    return render(request, 'asistencia/admin/editar_horario.html', {
        'form': form, 'zona': zona, 'horario': horario, 'seccion': 'horarios'
    })


@solo_admin
def asignaciones(request):
    """Asignación manual de zonas y horarios a profesionales."""
    configs = ConfigAsistencia.objects.select_related(
        'user__perfil__profesional', 'zona'
    ).order_by('user__last_name')

    profesionales_sin_config = User.objects.filter(
        perfil__rol='profesional', is_active=True
    ).exclude(
        configs_asistencia__isnull=False
    )

    if request.method == 'POST':
        form = ConfigAsistenciaForm(request.POST)
        if form.is_valid():
            config = form.save(commit=False)
            if config.personalizado:
                config.modificado_por = request.user
                config.fecha_modificacion = timezone.now()
            config.save()
            messages.success(request, 'Asignación guardada correctamente.')
            return redirect('asistencia:asignaciones')
    else:
        form = ConfigAsistenciaForm()

    return render(request, 'asistencia/admin/asignaciones.html', {
        'configs': configs,
        'profesionales_sin_config': profesionales_sin_config,
        'form': form,
        'seccion': 'asignaciones',
    })


@solo_admin
def editar_config(request, pk):
    config = get_object_or_404(ConfigAsistencia, pk=pk)
    if request.method == 'POST':
        form = ConfigAsistenciaForm(request.POST, instance=config)
        if form.is_valid():
            config = form.save(commit=False)
            if config.personalizado:
                config.modificado_por = request.user
                config.fecha_modificacion = timezone.now()
            config.save()
            messages.success(request, 'Configuración actualizada.')
            return redirect('asistencia:asignaciones')
    else:
        form = ConfigAsistenciaForm(instance=config)
    return render(request, 'asistencia/admin/editar_config.html', {
        'form': form, 'config': config, 'seccion': 'asignaciones'
    })


@solo_admin
def eliminar_config(request, pk):
    config = get_object_or_404(ConfigAsistencia, pk=pk)
    if request.method == 'POST':
        nombre = str(config)
        config.delete()
        messages.success(request, f'Asignación "{nombre}" eliminada.')
    return redirect('asistencia:asignaciones')



@solo_admin
def fechas_especiales(request):
    """Gestión de fechas especiales de horario."""
    fechas = FechaEspecial.objects.select_related(
        'zona', 'creado_por'
    ).prefetch_related('profesionales').order_by('-fecha')

    if request.method == 'POST':
        form = FechaEspecialForm(request.POST)
        if form.is_valid():
            fecha_esp = form.save(commit=False)
            fecha_esp.creado_por = request.user
            fecha_esp.save()
            form.save_m2m()
            messages.success(request, f'Fecha especial del {fecha_esp.fecha} guardada.')
            return redirect('asistencia:fechas_especiales')
    else:
        form = FechaEspecialForm()

    return render(request, 'asistencia/admin/fechas_especiales.html', {
        'fechas': fechas,
        'form': form,
        'seccion': 'horarios',
    })


@solo_admin
def eliminar_fecha_especial(request, pk):
    fecha_esp = get_object_or_404(FechaEspecial, pk=pk)
    if request.method == 'POST':
        fecha_esp.delete()
        messages.success(request, 'Fecha especial eliminada.')
    return redirect('asistencia:fechas_especiales')


@solo_admin
def enrolamiento(request):
    """Estado del enrolamiento facial de cada profesional."""
    profesionales = User.objects.filter(
        perfil__rol='profesional', is_active=True
    ).select_related('perfil__profesional').prefetch_related('enrolamiento__permisos')

    datos = []
    for user in profesionales:
        try:
            enrol = user.enrolamiento
        except EnrolamientoFacial.DoesNotExist:
            enrol = None
        datos.append({'user': user, 'enrolamiento': enrol})

    return render(request, 'asistencia/admin/enrolamiento.html', {
        'datos': datos,
        'seccion': 'enrolamiento',
    })


@solo_admin
def desbloquear_enrolamiento(request, enrolamiento_pk):
    """Desbloquear enrolamiento y otorgar permiso de re-enrolamiento."""
    enrol = get_object_or_404(EnrolamientoFacial, pk=enrolamiento_pk)

    if request.method == 'POST':
        form = PermisoReenrolamientoForm(request.POST)
        if form.is_valid():
            PermisoReenrolamiento.objects.create(
                enrolamiento=enrol,
                otorgado_por=request.user,
                motivo=form.cleaned_data['motivo'],
            )
            enrol.estado = 'pendiente'
            enrol.intentos_fallidos = 0
            enrol.save()
            messages.success(
                request,
                f'Permiso otorgado a {enrol.user.get_full_name()}. '
                f'Puede intentar el enrolamiento nuevamente.'
            )
        return redirect('asistencia:enrolamiento')

    return redirect('asistencia:enrolamiento')


@solo_admin
def permisos(request):
    """Historial de permisos de re-enrolamiento y formulario para otorgar."""
    historial = PermisoReenrolamiento.objects.select_related(
        'enrolamiento__user', 'otorgado_por'
    ).order_by('-fecha_otorgado')

    enrolamientos_bloqueados = EnrolamientoFacial.objects.filter(
        estado='bloqueado'
    ).select_related('user__perfil__profesional')

    if request.method == 'POST':
        form = PermisoReenrolamientoForm(request.POST)
        if form.is_valid():
            enrol = get_object_or_404(
                EnrolamientoFacial, pk=form.cleaned_data['enrolamiento_id']
            )
            PermisoReenrolamiento.objects.create(
                enrolamiento=enrol,
                otorgado_por=request.user,
                motivo=form.cleaned_data['motivo'],
            )
            enrol.estado = 'pendiente'
            enrol.intentos_fallidos = 0
            enrol.save()
            messages.success(request, 'Permiso otorgado correctamente.')
            return redirect('asistencia:permisos')
    else:
        form = PermisoReenrolamientoForm()

    return render(request, 'asistencia/admin/permisos.html', {
        'historial': historial,
        'enrolamientos_bloqueados': enrolamientos_bloqueados,
        'form': form,
        'seccion': 'permisos',
    })


# ══════════════════════════════════════════════════════════════════════════════
# PANEL PROFESIONAL
# ══════════════════════════════════════════════════════════════════════════════

@solo_profesional
def marcar_asistencia(request):
    """Vista donde el profesional marca entrada o salida."""
    user = request.user
    hoy = timezone.now().date()

    registros_hoy = user.registros_asistencia.filter(
        fecha_hora__date=hoy,
        estado__in=['PUNTUAL', 'TARDANZA']
    ).order_by('fecha_hora')

    entrada_hoy = registros_hoy.filter(tipo='ENTRADA').first()
    salida_hoy = registros_hoy.filter(tipo='SALIDA').first()

    puede_entrar = not entrada_hoy
    puede_salir = bool(entrada_hoy) and not salida_hoy

    # Obtener zonas asignadas para mostrar en el mapa
    configs = ConfigAsistencia.objects.filter(
        user=user, zona__activa=True
    ).select_related('zona')

    if request.method == 'POST':
        form = MarcarAsistenciaForm(request.POST)
        if form.is_valid():
            d = form.cleaned_data
            validador = ValidadorAsistencia(
                user=user,
                tipo=d['tipo'],
                latitud=d.get('latitud'),
                longitud=d.get('longitud'),
                vector_facial_recibido=d.get('vector_facial'),
                foto_base64=d.get('foto_base64'),
                device_id=d.get('device_id', ''),
                observacion=d.get('observacion', ''),
            )
            exito, registro, errores = validador.ejecutar()

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                if exito:
                    return JsonResponse({
                        'aprobado': True,
                        'estado': registro.estado,
                        'tipo': registro.tipo,
                        'hora': registro.fecha_hora.strftime('%H:%M:%S'),
                        'minutos_tardanza': registro.minutos_tardanza,
                    })
                return JsonResponse({'aprobado': False, 'errores': errores}, status=403)

            if exito:
                messages.success(
                    request,
                    f'{registro.tipo.capitalize()} registrada a las '
                    f'{registro.fecha_hora.strftime("%H:%M")} — {registro.estado}.'
                )
            else:
                for err in errores:
                    messages.error(request, err)
        return redirect('asistencia:marcar')

    return render(request, 'asistencia/profesional/marcar.html', {
        'entrada_hoy': entrada_hoy,
        'salida_hoy': salida_hoy,
        'puede_entrar': puede_entrar,
        'puede_salir': puede_salir,
        'configs': configs,
        'hoy': hoy,
    })


@solo_profesional
def mi_asistencia(request):
    """Panel del profesional — historial, métricas y gráfico semanal."""
    user = request.user
    hoy = timezone.now().date()

    # Mes seleccionado (por defecto el actual)
    mes = int(request.GET.get('mes', hoy.month))
    anio = int(request.GET.get('anio', hoy.year))
    inicio_mes = date(anio, mes, 1)
    if mes == 12:
        fin_mes = date(anio + 1, 1, 1) - timedelta(days=1)
    else:
        fin_mes = date(anio, mes + 1, 1) - timedelta(days=1)

    registros = user.registros_asistencia.filter(
        fecha_hora__date__gte=inicio_mes,
        fecha_hora__date__lte=fin_mes,
        tipo='ENTRADA',
        estado__in=['PUNTUAL', 'TARDANZA', 'AUSENTE'],
    ).order_by('-fecha_hora')

    # Métricas del mes
    presentes = registros.filter(estado__in=['PUNTUAL', 'TARDANZA']).count()
    tardanzas = registros.filter(estado='TARDANZA').count()
    ausentes = registros.filter(estado='AUSENTE').count()
    minutos_acum = registros.aggregate(
        total=Sum('minutos_tardanza')
    )['total'] or 0

    # Todos los registros del mes (entrada + salida) para el listado
    registros_listado = user.registros_asistencia.filter(
        fecha_hora__date__gte=inicio_mes,
        fecha_hora__date__lte=fin_mes,
        estado__in=['PUNTUAL', 'TARDANZA', 'AUSENTE'],
    ).order_by('-fecha_hora').select_related('zona')

    # Datos para gráfico semanal (últimas 4 semanas)
    semanas = []
    for i in range(3, -1, -1):
        inicio_sem = hoy - timedelta(days=hoy.weekday() + 7 * i)
        fin_sem = inicio_sem + timedelta(days=6)
        regs_sem = user.registros_asistencia.filter(
            fecha_hora__date__gte=inicio_sem,
            fecha_hora__date__lte=fin_sem,
            tipo='ENTRADA',
        )
        semanas.append({
            'label': f'{inicio_sem.strftime("%d/%m")}',
            'puntuales': regs_sem.filter(estado='PUNTUAL').count(),
            'tardanzas': regs_sem.filter(estado='TARDANZA').count(),
            'ausentes': regs_sem.filter(estado='AUSENTE').count(),
        })

    # Meses disponibles para el selector
    meses_disponibles = []
    for m in range(1, 13):
        meses_disponibles.append({
            'numero': m,
            'nombre': ['Ene','Feb','Mar','Abr','May','Jun',
                       'Jul','Ago','Sep','Oct','Nov','Dic'][m-1],
            'activo': m == mes,
        })

    return render(request, 'asistencia/profesional/mi_asistencia.html', {
        'registros_listado': registros_listado,
        'presentes': presentes,
        'tardanzas': tardanzas,
        'ausentes': ausentes,
        'minutos_acum': minutos_acum,
        'semanas': semanas,
        'mes': mes,
        'anio': anio,
        'meses_disponibles': meses_disponibles,
        'hoy': hoy,
    })


@solo_profesional
def enrolamiento_facial(request):
    """
    Página de enrolamiento facial del profesional.
    Accesible desde su panel. Requiere permiso del admin si ya está enrolado o bloqueado.
    """
    user = request.user
    try:
        enrolamiento = user.enrolamiento
    except Exception:
        from .models import EnrolamientoFacial
        enrolamiento, _ = EnrolamientoFacial.objects.get_or_create(user=user)

    puede_enrolar = enrolamiento.puede_enrolar()
    permiso_activo = enrolamiento.tiene_permiso_activo()

    if request.method == 'POST' and puede_enrolar:
        import json
        vector = request.POST.get('vector_facial')
        foto_base64 = request.POST.get('foto_base64')

        if not vector:
            messages.error(request, 'No se recibió el vector facial. Intentá nuevamente.')
            return redirect('asistencia:enrolamiento_facial')

        try:
            vector_data = json.loads(vector)
        except Exception:
            messages.error(request, 'Error al procesar el vector facial.')
            return redirect('asistencia:enrolamiento_facial')

        # Guardar vector y marcar como enrolado
        enrolamiento.vector_facial = vector_data
        enrolamiento.estado = 'enrolado'
        enrolamiento.intentos_fallidos = 0
        enrolamiento.fecha_enrolamiento = timezone.now()

        # Calcular score promedio (similitud consigo mismo = 1.0 en enrolamiento)
        enrolamiento.score_promedio = 1.0

        # Marcar permiso como usado si existía
        permiso = enrolamiento.permisos.filter(usado=False).first()
        if permiso:
            permiso.usado = True
            permiso.fecha_usado = timezone.now()
            permiso.save()

        # Guardar foto si viene
        if foto_base64:
            import base64
            from django.core.files.base import ContentFile
            try:
                formato, datos = foto_base64.split(';base64,')
                ext = formato.split('/')[-1]
                from .models import RegistroAsistencia
                enrolamiento.save()
            except Exception:
                pass

        enrolamiento.save()
        messages.success(request, '¡Rostro registrado correctamente! Ya podés marcar asistencia.')
        return redirect('asistencia:mi_asistencia')

    return render(request, 'asistencia/profesional/enrolamiento_facial.html', {
        'enrolamiento': enrolamiento,
        'puede_enrolar': puede_enrolar,
        'permiso_activo': permiso_activo,
    })


@solo_profesional
def editar_observacion(request, pk):
    """El profesional edita solo su observación — únicamente el mismo día."""
    registro = get_object_or_404(
        RegistroAsistencia, pk=pk, user=request.user
    )

    if not registro.es_editable_hoy():
        messages.error(request, 'Solo puedes editar la observación durante el día del registro.')
        return redirect('asistencia:mi_asistencia')

    if request.method == 'POST':
        form = EditarObservacionForm(request.POST, instance=registro)
        if form.is_valid():
            form.save()
            messages.success(request, 'Observación actualizada.')
            return redirect('asistencia:mi_asistencia')
    else:
        form = EditarObservacionForm(instance=registro)

    return render(request, 'asistencia/profesional/editar_observacion.html', {
        'form': form, 'registro': registro
    })
