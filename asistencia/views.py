import json
from datetime import date, timedelta
from functools import wraps

from django.contrib import messages
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import (
    BloqueFechaEspecialForm, BloqueHorarioForm, ConfigAsistenciaForm, EditarObservacionForm,
    FechaEspecialForm, MarcarAsistenciaForm, PermisoReenrolamientoForm, PlantillaHorarioForm,
    ZonaAsistenciaForm, bloque_formset,
)
from .models import (
    BloqueFechaEspecial, BloqueHorario, ConfigAsistencia, DIAS_SEMANA, DIAS_SEMANA_ORDEN, EnrolamientoFacial,
    FechaEspecial, PermisoReenrolamiento, PlantillaHorario, RegistroAsistencia, ZonaAsistencia,
)
from .services import (
    ErrorEnrolamiento, ValidadorAsistencia, calcular_estado_dia, construir_panel,
    elegir_config_y_horario, procesar_enrolamiento, registrar_manual, registros_validos_del_dia,
)


# ── Decoradores de permiso ───────────────────────────────────────────────────

def solo_admin(view_func):
    """Solo superadmin o gerente."""
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
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('core:login')
        if hasattr(request.user, 'perfil') and request.user.perfil.rol == 'profesional':
            return view_func(request, *args, **kwargs)
        messages.error(request, 'Esta sección es solo para profesionales.')
        return redirect('core:dashboard')
    return wrapper


def _marcar_modificado(config, admin):
    config.modificado_por = admin
    config.fecha_modificacion = timezone.now()
    config.save(update_fields=['modificado_por', 'fecha_modificacion'])


def clonar_plantillas_zona(config):
    """
    Al activar 'horario propio' por primera vez se copian las plantillas de la zona
    como punto de partida (para no dejar al profesional sin horario).
    """
    if PlantillaHorario.objects.filter(zona=config.zona, user=config.user).exists():
        return 0
    n = 0
    for p in PlantillaHorario.objects.filter(zona=config.zona, user__isnull=True).prefetch_related('bloques'):
        copia = PlantillaHorario.objects.create(
            zona=config.zona, user=config.user, nombre=p.nombre, dias=list(p.dias or []))
        for b in p.bloques.all():
            BloqueHorario.objects.create(
                plantilla=copia, orden=b.orden, hora_entrada=b.hora_entrada,
                hora_salida=b.hora_salida, tolerancia_minutos=b.tolerancia_minutos)
        n += 1
    return n


# ══════════════════════════════════════════════════════════════════════════════
# PANEL ADMINISTRADOR
# ══════════════════════════════════════════════════════════════════════════════

@solo_admin
@require_POST
def marcar_admin(request, user_pk):
    """El admin marca entrada/salida de un profesional. Sin GPS ni rostro; queda anotado."""
    profesional_user = get_object_or_404(
        User, pk=user_pk, perfil__rol='profesional', is_active=True
    )
    tipo = request.POST.get('tipo')
    if tipo not in ('ENTRADA', 'SALIDA'):
        messages.error(request, 'Tipo inválido.')
        return redirect('asistencia:panel_admin')

    ok, _registro, error = registrar_manual(
        profesional_user, tipo, request.user,
        observacion=request.POST.get('observacion', '').strip(),
    )
    if ok:
        messages.success(
            request,
            f'{tipo.capitalize()} de {profesional_user.get_full_name()} registrada correctamente.')
    else:
        messages.error(request, error)
    return redirect('asistencia:panel_admin')


@solo_admin
def panel_admin(request):
    """Resumen diario — vista principal del admin."""
    hoy = timezone.localdate()
    try:
        fecha = date.fromisoformat(request.GET.get('fecha', ''))
    except ValueError:
        fecha = hoy
    if fecha > hoy:
        fecha = hoy

    datos, resumen = construir_panel(fecha)
    return render(request, 'asistencia/admin/panel.html', {
        'datos': datos,
        'resumen': resumen,
        'hoy': fecha,
        'es_hoy': fecha == hoy,
        'dia_anterior': fecha - timedelta(days=1),
        'dia_siguiente': fecha + timedelta(days=1) if fecha < hoy else None,
        'seccion': 'resumen',
    })


@solo_admin
def zonas_gps(request):
    """Gestión de zonas GPS — listado y creación."""
    zonas = ZonaAsistencia.objects.select_related('sucursal').prefetch_related('plantillas').all()

    if request.method == 'POST':
        form = ZonaAsistenciaForm(request.POST)
        if form.is_valid():
            zona = form.save()
            messages.success(
                request,
                f'Zona "{zona.nombre}" creada. Ahora define sus horarios en la sección Horarios.')
            return redirect('asistencia:zonas_gps')
    else:
        form = ZonaAsistenciaForm()

    return render(request, 'asistencia/admin/zonas.html', {
        'zonas': zonas, 'form': form, 'seccion': 'zonas',
        'zonas_mapa': [
            {'nombre': z.nombre, 'lat': float(z.latitud), 'lon': float(z.longitud),
             'radio': z.radio_metros, 'activa': z.activa}
            for z in zonas
        ],
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


# ── Horarios ─────────────────────────────────────────────────────────────────

@solo_admin
def horarios(request):
    """Horarios por zona (varias plantillas: Lun-Vie partido, Sábado continuo...) y personales."""
    zonas = list(ZonaAsistencia.objects.filter(activa=True).prefetch_related('plantillas__bloques'))
    for z in zonas:
        z.plantillas_zona = [p for p in z.plantillas.all() if p.user_id is None]
        cubiertos = {d for p in z.plantillas_zona for d in (p.dias or [])}
        nombres = dict(DIAS_SEMANA)
        z.dias_sin_horario = [nombres[d] for d in DIAS_SEMANA_ORDEN if d not in cubiertos]

    configs = list(
        ConfigAsistencia.objects.filter(personalizado=True)
        .select_related('user', 'zona', 'modificado_por')
        .prefetch_related('zona__plantillas__bloques')
        .order_by('user__last_name')
    )
    for c in configs:
        c.plantillas_personales = c.plantillas_efectivas()

    return render(request, 'asistencia/admin/horarios.html', {
        'zonas': zonas, 'configs_personalizadas': configs, 'seccion': 'horarios',
    })


@solo_admin
def editar_plantilla(request, pk=None, zona_pk=None, config_pk=None):
    """
    Crea o edita una plantilla de horario (días + bloques).
      pk         -> editar existente
      zona_pk    -> nueva plantilla predeterminada de la zona
      config_pk  -> nueva plantilla personal del profesional de esa asignación
    """
    if pk:
        plantilla = get_object_or_404(PlantillaHorario.objects.select_related('zona', 'user'), pk=pk)
    elif config_pk:
        cfg = get_object_or_404(ConfigAsistencia.objects.select_related('zona', 'user'), pk=config_pk)
        plantilla = PlantillaHorario(zona=cfg.zona, user=cfg.user)
    else:
        plantilla = PlantillaHorario(zona=get_object_or_404(ZonaAsistencia, pk=zona_pk))

    zona, usuario = plantilla.zona, plantilla.user
    config_personal = (
        ConfigAsistencia.objects.filter(user=usuario, zona=zona).first() if usuario else None
    )
    volver = ('asistencia:editar_config', config_personal.pk) if config_personal else ('asistencia:horarios',)

    if request.method == 'POST':
        form = PlantillaHorarioForm(request.POST, instance=plantilla)
        formset = bloque_formset(PlantillaHorario, BloqueHorario, BloqueHorarioForm,
                                 instance=plantilla, data=request.POST)
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                plantilla = form.save()
                formset.instance = plantilla
                formset.save()
                if config_personal:
                    _marcar_modificado(config_personal, request.user)
            messages.success(request, 'Horario guardado.')
            return redirect(*volver)
    else:
        form = PlantillaHorarioForm(instance=plantilla)
        formset = bloque_formset(PlantillaHorario, BloqueHorario, BloqueHorarioForm, instance=plantilla)

    return render(request, 'asistencia/admin/editar_plantilla.html', {
        'form': form, 'formset': formset, 'plantilla': plantilla,
        'zona': zona, 'usuario': usuario, 'volver': volver,
        'seccion': 'horarios',
    })


@solo_admin
@require_POST
def eliminar_plantilla(request, pk):
    plantilla = get_object_or_404(PlantillaHorario.objects.select_related('zona', 'user'), pk=pk)
    config_personal = (
        ConfigAsistencia.objects.filter(user=plantilla.user, zona=plantilla.zona).first()
        if plantilla.user_id else None
    )
    plantilla.delete()
    messages.success(request, 'Horario eliminado.')
    if config_personal:
        return redirect('asistencia:editar_config', pk=config_personal.pk)
    return redirect('asistencia:horarios')


# ── Asignaciones ─────────────────────────────────────────────────────────────

@solo_admin
def asignaciones(request):
    """Asignación de zonas a profesionales (y opcionalmente horario propio)."""
    configs = list(
        ConfigAsistencia.objects.select_related('user__perfil__profesional', 'zona')
        .prefetch_related('zona__plantillas__bloques').order_by('user__last_name')
    )
    for c in configs:
        c.plantillas_vigentes = c.plantillas_efectivas()

    profesionales_sin_config = User.objects.filter(
        perfil__rol='profesional', is_active=True
    ).exclude(configs_asistencia__isnull=False)

    if request.method == 'POST':
        form = ConfigAsistenciaForm(request.POST)
        if form.is_valid():
            config = form.save()
            if config.personalizado:
                clonar_plantillas_zona(config)
                _marcar_modificado(config, request.user)
                messages.success(
                    request,
                    'Asignación guardada. Se copió el horario de la zona como punto de partida: '
                    'ajústalo en «Editar».')
            else:
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
    config = get_object_or_404(ConfigAsistencia.objects.select_related('user', 'zona'), pk=pk)
    if request.method == 'POST':
        form = ConfigAsistenciaForm(request.POST, instance=config)
        if form.is_valid():
            config = form.save()
            if config.personalizado:
                clonar_plantillas_zona(config)
                _marcar_modificado(config, request.user)
            messages.success(request, 'Configuración actualizada.')
            return redirect('asistencia:editar_config', pk=config.pk)
    else:
        form = ConfigAsistenciaForm(instance=config)

    plantillas_personales = list(
        PlantillaHorario.objects.filter(zona=config.zona, user=config.user).prefetch_related('bloques')
    )
    plantillas_zona = list(
        PlantillaHorario.objects.filter(zona=config.zona, user__isnull=True).prefetch_related('bloques')
    )
    return render(request, 'asistencia/admin/editar_config.html', {
        'form': form, 'config': config, 'seccion': 'asignaciones',
        'plantillas_personales': plantillas_personales,
        'plantillas_zona': plantillas_zona,
    })


@solo_admin
@require_POST
def eliminar_config(request, pk):
    config = get_object_or_404(ConfigAsistencia, pk=pk)
    nombre = str(config)
    # las plantillas personales de esa zona dejan de tener sentido
    PlantillaHorario.objects.filter(zona=config.zona, user=config.user).delete()
    config.delete()
    messages.success(request, f'Asignación "{nombre}" eliminada.')
    return redirect('asistencia:asignaciones')


# ── Fechas especiales ────────────────────────────────────────────────────────

@solo_admin
def fechas_especiales(request):
    """Fechas con horario propio (varios bloques) o día libre."""
    fechas = FechaEspecial.objects.select_related('zona', 'creado_por').prefetch_related(
        'profesionales', 'bloques').order_by('-fecha')

    if request.method == 'POST':
        form = FechaEspecialForm(request.POST)
        es_libre = request.POST.get('tipo_horario') == 'libre'
        formset = bloque_formset(
            FechaEspecial, BloqueFechaEspecial, BloqueFechaEspecialForm,
            instance=None, data=request.POST, requiere_bloques=not es_libre)
        if form.is_valid() and (es_libre or formset.is_valid()):
            with transaction.atomic():
                fecha_esp = form.save(commit=False)
                fecha_esp.creado_por = request.user
                fecha_esp.save()
                form.save_m2m()
                if not es_libre:
                    formset.instance = fecha_esp
                    formset.save()
            messages.success(request, f'Fecha especial del {fecha_esp.fecha:%d/%m/%Y} guardada.')
            return redirect('asistencia:fechas_especiales')
    else:
        form = FechaEspecialForm()
        formset = bloque_formset(FechaEspecial, BloqueFechaEspecial, BloqueFechaEspecialForm, instance=None)

    return render(request, 'asistencia/admin/fechas_especiales.html', {
        'fechas': fechas, 'form': form, 'formset': formset, 'seccion': 'fechas',
    })


@solo_admin
@require_POST
def eliminar_fecha_especial(request, pk):
    get_object_or_404(FechaEspecial, pk=pk).delete()
    messages.success(request, 'Fecha especial eliminada.')
    return redirect('asistencia:fechas_especiales')


# ── Enrolamiento ─────────────────────────────────────────────────────────────

@solo_admin
def enrolamiento(request):
    """Estado del enrolamiento facial de cada profesional."""
    profesionales = User.objects.filter(
        perfil__rol='profesional', is_active=True
    ).select_related('perfil__profesional', 'enrolamiento').prefetch_related('enrolamiento__permisos')

    datos = [{'user': u, 'enrolamiento': getattr(u, 'enrolamiento', None)} for u in profesionales]
    return render(request, 'asistencia/admin/enrolamiento.html', {
        'datos': datos, 'seccion': 'enrolamiento',
    })


def _otorgar_permiso(enrol, admin, motivo):
    """
    Permite al profesional volver a registrar su rostro.
      bloqueado -> pasa a 'pendiente' (y se reinician los intentos)
      enrolado  -> sigue enrolado y puede marcar hasta que complete el nuevo registro
    """
    PermisoReenrolamiento.objects.create(enrolamiento=enrol, otorgado_por=admin, motivo=motivo)
    if enrol.estado == 'bloqueado':
        enrol.estado = 'pendiente'
    enrol.intentos_fallidos = 0
    enrol.save(update_fields=['estado', 'intentos_fallidos'])


@solo_admin
@require_POST
def desbloquear_enrolamiento(request, enrolamiento_pk):
    """Desbloquea (o habilita re-enrolar) y otorga permiso."""
    enrol = get_object_or_404(EnrolamientoFacial, pk=enrolamiento_pk)
    form = PermisoReenrolamientoForm(request.POST)
    if form.is_valid():
        _otorgar_permiso(enrol, request.user, form.cleaned_data['motivo'])
        messages.success(
            request,
            f'Permiso otorgado a {enrol.user.get_full_name()}. Puede registrar su rostro nuevamente.')
    else:
        messages.error(request, 'Indica el motivo del permiso.')
    return redirect('asistencia:enrolamiento')


@solo_admin
def permisos(request):
    """Historial de permisos de re-enrolamiento y formulario para otorgar."""
    historial = PermisoReenrolamiento.objects.select_related(
        'enrolamiento__user', 'otorgado_por').order_by('-fecha_otorgado')
    enrolamientos_bloqueados = EnrolamientoFacial.objects.filter(
        estado='bloqueado').select_related('user__perfil__profesional')

    if request.method == 'POST':
        form = PermisoReenrolamientoForm(request.POST)
        if form.is_valid():
            enrol = get_object_or_404(EnrolamientoFacial, pk=form.cleaned_data['enrolamiento_id'])
            _otorgar_permiso(enrol, request.user, form.cleaned_data['motivo'])
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

def _json_errores(request):
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


@solo_profesional
def marcar_asistencia(request):
    """Vista donde el profesional marca entrada o salida (varios bloques por día)."""
    user = request.user
    hoy = timezone.localdate()

    if request.method == 'POST':
        form = MarcarAsistenciaForm(request.POST)
        if not form.is_valid():
            errores = [f'{campo}: {" ".join(errs)}' if campo != '__all__' else " ".join(errs)
                       for campo, errs in form.errors.items()]
            if _json_errores(request):
                return JsonResponse({'aprobado': False, 'errores': errores}, status=400)
            for e in errores:
                messages.error(request, e)
            return redirect('asistencia:marcar')

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
            precision_gps=d.get('precision'),
        )
        exito, registro, errores = validador.ejecutar()

        if _json_errores(request):
            if exito:
                return JsonResponse({
                    'aprobado': True,
                    'estado': registro.estado,
                    'tipo': registro.tipo,
                    'hora': timezone.localtime(registro.fecha_hora).strftime('%H:%M:%S'),
                    'minutos_tardanza': registro.minutos_tardanza,
                })
            return JsonResponse({'aprobado': False, 'errores': errores}, status=403)

        if exito:
            messages.success(
                request,
                f'{registro.get_tipo_display()} registrada a las '
                f'{timezone.localtime(registro.fecha_hora):%H:%M} — {registro.get_estado_display()}.')
        else:
            for err in errores:
                messages.error(request, err)
        return redirect('asistencia:marcar')

    configs = list(
        ConfigAsistencia.objects.filter(user=user, zona__activa=True)
        .select_related('zona').prefetch_related('zona__plantillas__bloques')
    )
    _config, horario = elegir_config_y_horario(user, hoy, configs)
    estado_dia = calcular_estado_dia(registros_validos_del_dia(user, hoy), horario)

    try:
        enrol = user.enrolamiento
    except EnrolamientoFacial.DoesNotExist:
        enrol, _ = EnrolamientoFacial.objects.get_or_create(user=user)

    return render(request, 'asistencia/profesional/marcar.html', {
        'horario': horario,
        'pares': estado_dia.pares,
        'siguiente': estado_dia.siguiente,
        'puede_entrar': estado_dia.siguiente == 'ENTRADA',
        'puede_salir': estado_dia.siguiente == 'SALIDA',
        'configs': configs,
        'zonas_mapa': [
            {'nombre': c.zona.nombre, 'lat': float(c.zona.latitud),
             'lon': float(c.zona.longitud), 'radio': c.zona.radio_metros}
            for c in configs
        ],
        'enrolamiento': enrol,
        'listo_para_marcar': enrol.estado == 'enrolado',
        'hoy': hoy,
    })


MESES_CORTOS = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']


@solo_profesional
def mi_asistencia(request):
    """Panel del profesional — historial, métricas y gráfico semanal."""
    user = request.user
    hoy = timezone.localdate()

    # Mes/año seleccionados: valores inválidos o fuera de rango → mes actual
    try:
        mes = int(request.GET.get('mes', hoy.month))
        anio = int(request.GET.get('anio', hoy.year))
        if not (1 <= mes <= 12 and 2000 <= anio <= hoy.year + 1):
            raise ValueError
    except (TypeError, ValueError):
        mes, anio = hoy.month, hoy.year

    inicio_mes = date(anio, mes, 1)
    fin_mes = (date(anio + 1, 1, 1) if mes == 12 else date(anio, mes + 1, 1)) - timedelta(days=1)

    base = user.registros_asistencia.filter(
        fecha_hora__date__gte=inicio_mes, fecha_hora__date__lte=fin_mes)

    entradas = base.filter(tipo='ENTRADA', estado__in=['PUNTUAL', 'TARDANZA', 'AUSENTE'])
    dias_presentes = {
        timezone.localtime(r.fecha_hora).date()
        for r in entradas.filter(estado__in=['PUNTUAL', 'TARDANZA']).only('fecha_hora')
    }
    presentes = len(dias_presentes)
    tardanzas = entradas.filter(estado='TARDANZA').count()
    ausentes = entradas.filter(estado='AUSENTE').count()
    minutos_acum = entradas.aggregate(total=Sum('minutos_tardanza'))['total'] or 0

    registros_listado = base.filter(
        estado__in=['PUNTUAL', 'TARDANZA', 'AUSENTE']).order_by('-fecha_hora').select_related('zona')

    semanas = []
    for i in range(3, -1, -1):
        inicio_sem = hoy - timedelta(days=hoy.weekday() + 7 * i)
        regs_sem = user.registros_asistencia.filter(
            fecha_hora__date__gte=inicio_sem,
            fecha_hora__date__lte=inicio_sem + timedelta(days=6),
            tipo='ENTRADA',
        )
        semanas.append({
            'label': inicio_sem.strftime('%d/%m'),
            'puntuales': regs_sem.filter(estado='PUNTUAL').count(),
            'tardanzas': regs_sem.filter(estado='TARDANZA').count(),
            'ausentes': regs_sem.filter(estado='AUSENTE').count(),
        })

    primer = user.registros_asistencia.order_by('fecha_hora').values_list('fecha_hora', flat=True).first()
    anio_ini = timezone.localtime(primer).year if primer else hoy.year
    anios_disponibles = list(range(min(anio_ini, hoy.year), hoy.year + 1))

    return render(request, 'asistencia/profesional/mi_asistencia.html', {
        'registros_listado': registros_listado,
        'presentes': presentes,
        'tardanzas': tardanzas,
        'ausentes': ausentes,
        'minutos_acum': minutos_acum,
        'semanas': semanas,
        'mes': mes,
        'anio': anio,
        'anios_disponibles': anios_disponibles,
        'meses_disponibles': [
            {'numero': m, 'nombre': MESES_CORTOS[m - 1], 'activo': m == mes} for m in range(1, 13)
        ],
        'hoy': hoy,
    })


@solo_profesional
def enrolamiento_facial(request):
    """
    Enrolamiento facial del profesional. El primer registro es libre; actualizar un
    rostro ya registrado (o salir de un bloqueo) requiere permiso del administrador.
    """
    user = request.user
    enrol, _ = EnrolamientoFacial.objects.get_or_create(user=user)
    puede_enrolar = enrol.puede_enrolar()

    if request.method == 'POST':
        if not puede_enrolar:
            messages.error(request, 'Necesitas el permiso del administrador para registrar tu rostro de nuevo.')
            return redirect('asistencia:enrolamiento_facial')
        try:
            descriptores = json.loads(request.POST.get('vector_facial') or 'null')
            procesar_enrolamiento(enrol, descriptores, request.POST.get('foto_base64'))
        except (ValueError, ErrorEnrolamiento) as exc:
            msg = str(exc) if isinstance(exc, ErrorEnrolamiento) else 'No se pudieron leer los datos faciales.'
            messages.error(request, msg)
            return redirect('asistencia:enrolamiento_facial')
        messages.success(request, '¡Rostro registrado correctamente! Ya puedes marcar asistencia.')
        return redirect('asistencia:mi_asistencia')

    return render(request, 'asistencia/profesional/enrolamiento_facial.html', {
        'enrolamiento': enrol,
        'puede_enrolar': puede_enrolar,
        'permiso_activo': enrol.tiene_permiso_activo(),
    })


@solo_profesional
def editar_observacion(request, pk):
    """El profesional edita solo su observación — únicamente el mismo día."""
    registro = get_object_or_404(RegistroAsistencia, pk=pk, user=request.user)

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
