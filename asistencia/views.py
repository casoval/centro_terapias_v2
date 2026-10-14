import json
from datetime import date, timedelta
from functools import wraps

from django.contrib import messages
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from .forms import (
    BloqueFechaEspecialForm, BloqueHorarioForm, ConfigAsistenciaForm, EditarObservacionForm,
    FechaEspecialForm, MarcarAsistenciaForm, PermisoReenrolamientoForm, PlantillaHorarioForm,
    DIAS_RESTO_SUGERIDO, PermisoAsistenciaForm, ReglasAsistenciaForm, TRAMOS_SUGERIDOS, TramoFormSet,
    ZonaAsistenciaForm, bloque_formset,
)
from .informe_mensual import MESES, construir_informes_mensuales
from .models import (
    BloqueFechaEspecial, BloqueHorario, ConfigAsistencia, DIAS_SEMANA, DIAS_SEMANA_ORDEN, EnrolamientoFacial,
    FechaEspecial, PermisoAsistencia, PermisoReenrolamiento, PlantillaHorario, RegistroAsistencia, ReglasAsistencia,
    TramoDescuento, ZonaAsistencia,
)
from .services import (
    ErrorEnrolamiento, ValidadorAsistencia, calcular_estado_dia, construir_panel, dias_descuento,
    elegir_config_y_horario, fmt_min_seg, procesar_enrolamiento, registrar_manual,
    registros_validos_del_dia, segundos_para_proximo_tramo, texto_tramos,
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


def clonar_plantillas_zona(config, desde):
    """
    Al activar el horario propio desde `desde`, copia como punto de partida los horarios de la zona
    que rigen ese día (para no dejar al profesional sin horario).
    """
    if any(p.vigente_en(desde) for p in PlantillaHorario.objects.filter(zona=config.zona, user=config.user)):
        return 0
    n = 0
    for p in PlantillaHorario.objects.filter(zona=config.zona, user__isnull=True).prefetch_related('bloques'):
        if not p.vigente_en(desde):
            continue
        copia = PlantillaHorario.objects.create(
            zona=config.zona, user=config.user, nombre=p.nombre, dias=list(p.dias or []), vigente_desde=desde)
        for b in p.bloques.all():
            BloqueHorario.objects.create(
                plantilla=copia, orden=b.orden, hora_entrada=b.hora_entrada,
                hora_salida=b.hora_salida, tolerancia_minutos=b.tolerancia_minutos,
                max_retraso_minutos=b.max_retraso_minutos)
        n += 1
    return n


def _cambiar_horario_propio(config, activar, desde):
    """
    Activa o desactiva el horario propio DESDE una fecha, sin tocar lo anterior:
      - activar: abre un periodo propio desde `desde` y copia los horarios de la zona vigentes ese día
      - desactivar: cierra el periodo (y los horarios propios) el día anterior a `desde`
    """
    ayer = desde - timedelta(days=1)
    abiertos = list(config.periodos_propios.filter(hasta__isnull=True))
    if activar:
        if not abiertos:
            config.periodos_propios.create(desde=desde)
        clonar_plantillas_zona(config, desde)
    else:
        for periodo in abiertos:
            if desde <= periodo.desde:
                periodo.delete()                          # nunca llegó a regir
            else:
                periodo.hasta = ayer
                periodo.save(update_fields=['hasta'])
        for p in PlantillaHorario.objects.filter(zona=config.zona, user=config.user):
            if p.vigente_desde >= desde:
                p.delete()
            elif p.vigente_hasta is None or p.vigente_hasta > ayer:
                p.vigente_hasta = ayer
                p.save(update_fields=['vigente_hasta'])
    if config.personalizado != activar:
        config.personalizado = activar
        config.save(update_fields=['personalizado'])
    if hasattr(config, '_periodos_cache'):
        del config._periodos_cache


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

    # Cómo va el mes de cada profesional (estrellas + semáforo), para actuar antes de que haya descuentos fuertes
    from profesionales.models import Profesional
    profs = (Profesional.objects.filter(activo=True, user__isnull=False)
             .select_related('user').prefetch_related('sucursales'))
    evaluaciones = {i.user.pk: i for i in construir_informes_mensuales(profs, fecha.year, fecha.month)}
    for fila in datos:
        inf = evaluaciones.get(fila['user'].pk)
        fila['eval'] = inf.resumen if inf else None
    alertas = [f for f in datos if f['eval'] and f['eval']['alerta']]

    return render(request, 'asistencia/admin/panel.html', {
        'datos': datos, 'alertas': alertas,
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
    """Horarios por zona (varias plantillas por grupo de días), con su vigencia, y horarios propios."""
    hoy = timezone.localdate()
    zonas = list(ZonaAsistencia.objects.filter(activa=True).prefetch_related('plantillas__bloques'))
    nombres = dict(DIAS_SEMANA)
    for z in zonas:
        de_zona = [p for p in z.plantillas.all() if p.user_id is None]
        z.plantillas_zona = [p for p in de_zona if p.estado_vigencia(hoy) != 'finalizado']
        z.historial_zona = sorted((p for p in de_zona if p.estado_vigencia(hoy) == 'finalizado'),
                                  key=lambda p: p.vigente_hasta, reverse=True)
        cubiertos = {d for p in z.plantillas_zona if p.estado_vigencia(hoy) == 'vigente' for d in (p.dias or [])}
        z.dias_sin_horario = [nombres[d] for d in DIAS_SEMANA_ORDEN if d not in cubiertos]

    configs = list(
        ConfigAsistencia.objects.filter(personalizado=True)
        .select_related('user', 'zona', 'modificado_por')
        .prefetch_related('zona__plantillas__bloques', 'periodos_propios')
        .order_by('user__last_name')
    )
    for c in configs:
        c.plantillas_personales = [p for p in c.zona.plantillas.all()
                                   if p.user_id == c.user_id and p.estado_vigencia(hoy) != 'finalizado']

    return render(request, 'asistencia/admin/horarios.html', {
        'zonas': zonas, 'configs_personalizadas': configs, 'hoy': hoy, 'seccion': 'horarios',
    })


def _firma_plantilla(dias, bloques):
    """Contenido comparable de un horario: días y bloques (entrada, salida, tolerancia, límite)."""
    return tuple(dias or ()), tuple(sorted(bloques))


def _bloques_limpios(formset):
    out = []
    for f in formset.forms:
        cd = f.cleaned_data
        if not cd or cd.get('DELETE') or not cd.get('hora_entrada'):
            continue
        out.append((cd['hora_entrada'], cd['hora_salida'], cd['tolerancia_minutos'], cd.get('max_retraso_minutos')))
    return sorted(out)


@solo_admin
def editar_plantilla(request, pk=None, zona_pk=None, config_pk=None):
    """
    Crea o edita un horario (días + bloques) indicando DESDE CUÁNDO rige. Los cambios no son retroactivos:
      - editar con una fecha posterior al inicio del horario crea una versión nueva desde esa fecha y
        cierra la anterior el día previo (los meses pasados conservan lo que regía);
      - editar con una fecha igual o anterior al inicio corrige ese mismo horario.
      pk         -> editar existente
      zona_pk    -> nuevo horario de la zona
      config_pk  -> nuevo horario propio del profesional de esa asignación
    """
    hoy = timezone.localdate()
    if pk:
        plantilla = get_object_or_404(PlantillaHorario.objects.select_related('zona', 'user'), pk=pk)
        if plantilla.estado_vigencia(hoy) == 'finalizado':
            messages.error(request, 'Ese horario ya finalizó y forma parte del historial: no se puede editar. '
                                    'Crea uno nuevo con «Agregar horario».')
            return redirect('asistencia:horarios')
    elif config_pk:
        cfg = get_object_or_404(ConfigAsistencia.objects.select_related('zona', 'user'), pk=config_pk)
        plantilla = PlantillaHorario(zona=cfg.zona, user=cfg.user)
    else:
        plantilla = PlantillaHorario(zona=get_object_or_404(ZonaAsistencia, pk=zona_pk))

    es_nueva = plantilla.pk is None
    zona, usuario = plantilla.zona, plantilla.user
    config_personal = (
        ConfigAsistencia.objects.filter(user=usuario, zona=zona).first() if usuario else None
    )
    volver = ('asistencia:editar_config', config_personal.pk) if config_personal else ('asistencia:horarios',)

    if request.method == 'POST':
        # contenido y vigencia ORIGINALES (el formulario modifica la instancia en memoria al validar)
        original = None if es_nueva else _firma_plantilla(
            plantilla.dias, [(b.hora_entrada, b.hora_salida, b.tolerancia_minutos, b.max_retraso_minutos)
                             for b in plantilla.bloques.all()])
        orig_desde, orig_hasta = plantilla.vigente_desde, plantilla.vigente_hasta
        form = PlantillaHorarioForm(request.POST, instance=plantilla)
        formset = bloque_formset(PlantillaHorario, BloqueHorario, BloqueHorarioForm,
                                 instance=plantilla, data=request.POST)
        if form.is_valid() and formset.is_valid():
            desde = form.cleaned_data['vigente_desde']
            nuevos_dias = form.cleaned_data['dias']
            nuevos_bloques = _bloques_limpios(formset)
            with transaction.atomic():
                if es_nueva or desde <= orig_desde:
                    plantilla = form.save(commit=False)
                    plantilla.vigente_desde = desde
                    plantilla.save()
                    formset.instance = plantilla
                    formset.save()
                    mensaje = f'Horario guardado. Rige desde el {desde:%d/%m/%Y}.'
                elif _firma_plantilla(nuevos_dias, nuevos_bloques) == original:
                    plantilla.nombre = form.cleaned_data['nombre']
                    plantilla.save(update_fields=['nombre'])
                    mensaje = 'No cambiaron los días ni los bloques: no se creó una versión nueva.'
                else:
                    anterior = PlantillaHorario.objects.get(pk=plantilla.pk)
                    anterior.vigente_hasta = desde - timedelta(days=1)
                    anterior.save(update_fields=['vigente_hasta'])
                    nueva = PlantillaHorario.objects.create(
                        zona=zona, user=usuario, nombre=form.cleaned_data['nombre'], dias=nuevos_dias,
                        vigente_desde=desde, vigente_hasta=orig_hasta)
                    for orden, (e, sal, tol, lim) in enumerate(nuevos_bloques, start=1):
                        BloqueHorario.objects.create(
                            plantilla=nueva, orden=orden, hora_entrada=e, hora_salida=sal,
                            tolerancia_minutos=tol, max_retraso_minutos=lim)
                    mensaje = (f'Nueva versión del horario desde el {desde:%d/%m/%Y}. '
                               f'Hasta el {desde - timedelta(days=1):%d/%m/%Y} se conserva el horario anterior.')
                if config_personal:
                    _marcar_modificado(config_personal, request.user)
            messages.success(request, mensaje)
            return redirect(*volver)
    else:
        form = PlantillaHorarioForm(instance=plantilla)
        formset = bloque_formset(PlantillaHorario, BloqueHorario, BloqueHorarioForm, instance=plantilla)

    return render(request, 'asistencia/admin/editar_plantilla.html', {
        'form': form, 'formset': formset, 'plantilla': plantilla, 'es_nueva': es_nueva,
        'zona': zona, 'usuario': usuario, 'volver': volver, 'hoy': hoy,
        'seccion': 'horarios',
    })


@solo_admin
@require_POST
def eliminar_plantilla(request, pk):
    """
    «Finalizar» un horario desde una fecha (por defecto hoy). Lo anterior se conserva: el horario sigue
    rigiendo hasta el día previo. Solo se borra si nunca llegó a regir.
    """
    plantilla = get_object_or_404(PlantillaHorario.objects.select_related('zona', 'user'), pk=pk)
    try:
        desde = date.fromisoformat(request.POST.get('desde', ''))
    except ValueError:
        desde = timezone.localdate()
    config_personal = (
        ConfigAsistencia.objects.filter(user=plantilla.user, zona=plantilla.zona).first()
        if plantilla.user_id else None
    )
    if desde <= plantilla.vigente_desde:
        plantilla.delete()
        messages.success(request, 'Horario eliminado (todavía no había empezado a regir).')
    else:
        if plantilla.vigente_hasta is None or plantilla.vigente_hasta >= desde:
            plantilla.vigente_hasta = desde - timedelta(days=1)
            plantilla.save(update_fields=['vigente_hasta'])
        messages.success(request, f'El horario deja de regir desde el {desde:%d/%m/%Y}. '
                                  'Los días anteriores se conservan.')
    if config_personal:
        return redirect('asistencia:editar_config', pk=config_personal.pk)
    return redirect('asistencia:horarios')


# ── Reglas de retraso ────────────────────────────────────────────────────────

@solo_admin
def reglas_asistencia(request):
    """
    Descuento por retraso acumulado, por TRAMOS («hasta N minutos acumulados -> X días»), en versiones: cada
    cambio rige DESDE el mes elegido y los meses anteriores conservan las reglas que tenían.
    (Tolerancia y límite para marcar: en Horarios.)
    """
    from decimal import Decimal

    hoy = timezone.localdate()
    actual = ReglasAsistencia.para_fecha(hoy)
    tramos_actuales = actual.tramos_lista() if actual else []
    if tramos_actuales:
        filas_base = [(h / 60, d) for h, d in tramos_actuales if h is not None]
        dias_resto = next((d for h, d in tramos_actuales if h is None), 0)
    else:
        filas_base, dias_resto = TRAMOS_SUGERIDOS, DIAS_RESTO_SUGERIDO     # sugerencia inicial editable

    if request.method == 'POST':
        form = ReglasAsistenciaForm(request.POST)
        formset = TramoFormSet(request.POST, prefix='tramos')
        if form.is_valid() and formset.is_valid():
            filas = formset.filas_validas
            resto = form.cleaned_data['dias_resto']
            if filas and resto < filas[-1][1]:
                form.add_error('dias_resto', f'No puede ser menor que el último tramo ({filas[-1][1]} días).')
            else:
                desde = form.cleaned_data['vigente_desde']
                with transaction.atomic():
                    regla = ReglasAsistencia(vigente_desde=desde, modificado_por=request.user)
                    regla.save()                          # misma fecha = actualiza esa versión
                    regla.tramos.all().delete()
                    for hasta, dias in filas:
                        TramoDescuento.objects.create(regla=regla, hasta_minutos=hasta, dias=dias)
                    TramoDescuento.objects.create(regla=regla, hasta_minutos=None, dias=resto)
                primero_mes_actual = hoy.replace(day=1)
                if desde < primero_mes_actual:
                    messages.warning(request, f'Reglas guardadas desde {desde:%m/%Y}. Atención: cambian el cálculo de '
                                              'meses ya transcurridos (los informes de esos meses se recalcularán).')
                elif desde == primero_mes_actual:
                    messages.warning(request, 'Reglas guardadas desde el mes en curso: afectan a todo este mes, '
                                              'también a los días que ya pasaron.')
                else:
                    messages.success(request, f'Reglas guardadas. Rigen desde el 1/{desde:%m/%Y}; los meses anteriores no cambian.')
                return redirect('asistencia:reglas')
    else:
        form = ReglasAsistenciaForm(initial={'dias_resto': dias_resto})
        formset = TramoFormSet(prefix='tramos', initial=[
            {'hasta': Decimal(str(round(h, 2))), 'dias': Decimal(str(d))} for h, d in filas_base])

    versiones = list(ReglasAsistencia.objects.select_related('modificado_por').prefetch_related('tramos'))
    for v in versiones:
        v.estado = v.estado_vigencia(actual.pk if actual else None, hoy)
        v.texto = texto_tramos(v.tramos_lista()) or 'sin descuento'
    ejemplos = [(fmt_min_seg(seg), dias_descuento(seg, tramos_actuales))
                for seg in (900, 1800, 1801, 2700, 2701, 3600, 3601, 5400, 5401, 7200)]
    return render(request, 'asistencia/admin/reglas.html', {
        'form': form, 'formset': formset, 'actual': actual, 'versiones': versiones, 'ejemplos': ejemplos,
        'hay_reglas': bool(actual and actual.hay_descuento), 'seccion': 'reglas',
    })


@solo_admin
@require_POST
def eliminar_reglas(request, pk):
    """Solo se pueden borrar versiones programadas (futuras); las demás forman el historial."""
    version = get_object_or_404(ReglasAsistencia, pk=pk)
    if version.vigente_desde > timezone.localdate():
        version.delete()
        messages.success(request, 'Versión programada eliminada.')
    else:
        messages.error(request, 'Solo se pueden eliminar versiones programadas (futuras): '
                                'las anteriores forman parte del historial.')
    return redirect('asistencia:reglas')


# ── Asignaciones ─────────────────────────────────────────────────────────────

@solo_admin
def asignaciones(request):
    """Asignación de zonas a profesionales (y opcionalmente horario propio)."""
    configs = list(
        ConfigAsistencia.objects.select_related('user__perfil__profesional', 'zona')
        .prefetch_related('zona__plantillas__bloques', 'periodos_propios').order_by('user__last_name')
    )
    hoy = timezone.localdate()
    for c in configs:
        c.plantillas_vigentes = [p for p in c.plantillas_efectivas(hoy)]

    profesionales_sin_config = User.objects.filter(
        perfil__rol='profesional', is_active=True
    ).exclude(configs_asistencia__isnull=False)

    if request.method == 'POST':
        form = ConfigAsistenciaForm(request.POST)
        if form.is_valid():
            config = form.save()
            if config.personalizado:
                desde = form.cleaned_data.get('aplicar_desde') or hoy
                _cambiar_horario_propio(config, True, desde)
                _marcar_modificado(config, request.user)
                messages.success(
                    request,
                    f'Asignación guardada. Horario propio desde el {desde:%d/%m/%Y}, copiado del de la zona '
                    'como punto de partida: ajústalo en «Editar».')
            else:
                messages.success(request, 'Asignación guardada correctamente.')
            return redirect('asistencia:asignaciones')
    else:
        form = ConfigAsistenciaForm()

    return render(request, 'asistencia/admin/asignaciones.html', {
        'configs': configs,
        'profesionales_sin_config': profesionales_sin_config,
        'form': form, 'hoy': hoy,
        'seccion': 'asignaciones',
    })


@solo_admin
def editar_config(request, pk):
    config = get_object_or_404(ConfigAsistencia.objects.select_related('user', 'zona'), pk=pk)
    hoy = timezone.localdate()
    if request.method == 'POST':
        antes = config.personalizado                    # antes de que el formulario modifique la instancia
        form = ConfigAsistenciaForm(request.POST, instance=config)
        if form.is_valid():
            config = form.save()
            if config.personalizado != antes:
                desde = form.cleaned_data.get('aplicar_desde') or hoy
                _cambiar_horario_propio(config, config.personalizado, desde)
                _marcar_modificado(config, request.user)
                if config.personalizado:
                    messages.success(request, f'Horario propio activado desde el {desde:%d/%m/%Y}. '
                                              'Los días anteriores conservan el horario de la zona.')
                else:
                    messages.success(request, f'Horario propio desactivado desde el {desde:%d/%m/%Y}. '
                                              'Los días anteriores conservan el horario propio.')
            else:
                messages.success(request, 'Configuración actualizada.')
            return redirect('asistencia:editar_config', pk=config.pk)
    else:
        form = ConfigAsistenciaForm(instance=config)

    propias = (PlantillaHorario.objects.filter(zona=config.zona, user=config.user)
               .prefetch_related('bloques').order_by('vigente_desde', 'id'))
    de_zona = (PlantillaHorario.objects.filter(zona=config.zona, user__isnull=True)
               .prefetch_related('bloques').order_by('vigente_desde', 'id'))
    return render(request, 'asistencia/admin/editar_config.html', {
        'form': form, 'config': config, 'seccion': 'asignaciones', 'hoy': hoy,
        'plantillas_personales': [p for p in propias if p.estado_vigencia(hoy) != 'finalizado'],
        'plantillas_zona': [p for p in de_zona if p.estado_vigencia(hoy) != 'finalizado'],
        'periodos': list(config.periodos_propios.all()),
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
        .select_related('zona').prefetch_related('zona__plantillas__bloques', 'periodos_propios')
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

    # Evaluación del mes (estrellas de puntualidad y semáforo de asistencia) y descuento, con las reglas de ESE mes
    from profesionales.models import Profesional
    prof = (Profesional.objects.filter(user=user, activo=True)
            .select_related('user').prefetch_related('sucursales').first())
    informe = construir_informes_mensuales([prof], anio, mes)[0] if prof else None
    reglas = ReglasAsistencia.para_mes(anio, mes)
    tramos = reglas.tramos_lista() if reglas else []
    hay_reglas = bool(reglas and reglas.hay_descuento)
    acum_seg = (informe.resumen['retraso_seg'] if informe else
                entradas.filter(estado='TARDANZA').aggregate(total=Sum('segundos_acumulables'))['total'] or 0)

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
        'informe': informe,
        'resumen': informe.resumen if informe else None,
        'acum_seg': acum_seg,
        'hay_reglas': hay_reglas,
        'texto_regla': texto_tramos(tramos) if tramos else '',
        'descuento_dias': dias_descuento(acum_seg, tramos),
        # el "faltan X" solo tiene sentido en el mes en curso
        'faltan_seg': (segundos_para_proximo_tramo(acum_seg, tramos) if (mes, anio) == (hoy.month, hoy.year) else None),
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


# ══════════════════════════════════════════════════════════════════════════════
# INFORME MENSUAL DE ASISTENCIA (PDF por profesional / sucursal / global)
# ══════════════════════════════════════════════════════════════════════════════

def _periodo_informe(request):
    """(anio, mes) de los parámetros; inválido o futuro -> mes actual."""
    hoy = timezone.localdate()
    try:
        mes = int(request.GET.get('mes', hoy.month))
        anio = int(request.GET.get('anio', hoy.year))
        if not (1 <= mes <= 12 and 2000 <= anio <= hoy.year) or (anio, mes) > (hoy.year, hoy.month):
            raise ValueError
    except (TypeError, ValueError):
        mes, anio = hoy.month, hoy.year
    return anio, mes


def _profesionales_informe(request):
    """Profesionales activos con usuario, filtrados por ?sucursal= y ?profesional= (ids)."""
    from profesionales.models import Profesional
    from servicios.models import Sucursal

    qs = (Profesional.objects.filter(activo=True, user__isnull=False)
          .select_related('user').prefetch_related('sucursales').order_by('apellido', 'nombre'))
    sucursal = profesional = None
    sid, pid = request.GET.get('sucursal', ''), request.GET.get('profesional', '')
    if sid.isdigit():
        sucursal = Sucursal.objects.filter(pk=int(sid)).first()
        if sucursal:
            qs = qs.filter(sucursales=sucursal)
    if pid.isdigit():
        qs = qs.filter(pk=int(pid))
        profesional = qs.first()
    return qs, sucursal, profesional


def _alcance_informe(sucursal, profesional):
    if profesional:
        return f"Profesional: {profesional.nombre} {profesional.apellido}", \
               f"{profesional.apellido}-{profesional.nombre}"
    if sucursal:
        return f"Sucursal: {sucursal.nombre}", f"sucursal-{sucursal.nombre}"
    return "Global (todas las sucursales)", "global"


def _respuesta_pdf(pdf_bytes, nombre_archivo):
    resp = HttpResponse(pdf_bytes, content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="{nombre_archivo}"'
    return resp


@solo_admin
def informe_mensual(request):
    """Resumen del mes por profesional y descargas del PDF (global, por sucursal, por profesional)."""
    from profesionales.models import Profesional
    from servicios.models import Sucursal

    anio, mes = _periodo_informe(request)
    qs, sucursal, profesional = _profesionales_informe(request)
    informes = construir_informes_mensuales(qs, anio, mes)
    hoy = timezone.localdate()
    return render(request, 'asistencia/admin/informe_mensual.html', {
        'informes': informes,
        'anio': anio, 'mes': mes, 'periodo': f"{MESES[mes]} {anio}",
        'sucursal': sucursal, 'profesional': profesional,
        'sucursales': Sucursal.objects.filter(activa=True),
        'profesionales': Profesional.objects.filter(activo=True, user__isnull=False).order_by('apellido', 'nombre'),
        'meses': [(m, MESES[m]) for m in range(1, 13)],
        'anios': list(range(max(2024, hoy.year - 3), hoy.year + 1)),
        'sin_usuario': Profesional.objects.filter(activo=True, user__isnull=True).count(),
        'seccion': 'informe',
    })


@solo_admin
def informe_mensual_pdf(request):
    """PDF: una hoja por profesional (más hoja resumen si son varios). Sin montos de pago."""
    from .informe_mensual_pdf import generar_informe_mensual_pdf

    anio, mes = _periodo_informe(request)
    qs, sucursal, profesional = _profesionales_informe(request)
    informes = construir_informes_mensuales(qs, anio, mes)
    alcance, slug = _alcance_informe(sucursal, profesional)
    pdf = generar_informe_mensual_pdf(informes, alcance, sucursal_filtro=sucursal.nombre if sucursal else None)
    return _respuesta_pdf(pdf, f"asistencia_{anio}-{mes:02d}_{slugify(slug)}.pdf")


@solo_profesional
def mi_informe_pdf(request):
    """El profesional descarga su propio informe del mes."""
    from profesionales.models import Profesional
    from .informe_mensual_pdf import generar_informe_mensual_pdf

    prof = (Profesional.objects.filter(user=request.user, activo=True)
            .select_related('user').prefetch_related('sucursales').first())
    if prof is None:
        messages.error(request, 'Tu usuario no está vinculado a un profesional activo.')
        return redirect('asistencia:mi_asistencia')
    anio, mes = _periodo_informe(request)
    informes = construir_informes_mensuales([prof], anio, mes)
    pdf = generar_informe_mensual_pdf(informes, f"Profesional: {prof.nombre} {prof.apellido}")
    return _respuesta_pdf(pdf, f"mi_asistencia_{anio}-{mes:02d}.pdf")


# ══════════════════════════════════════════════════════════════════════════════
# JUSTIFICACIONES (permisos): una falta solo deja de descontar si el administrador la justifica
# ══════════════════════════════════════════════════════════════════════════════

def _ultimo_dia_del_mes(fecha):
    return (fecha.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


@solo_admin
def justificaciones(request):
    """Faltas del mes pendientes de justificar y permisos ya registrados. Plazo: último día del mes de la falta."""
    anio, mes = _periodo_informe(request)
    qs, sucursal, profesional = _profesionales_informe(request)
    informes = construir_informes_mensuales(qs, anio, mes)
    hoy = timezone.localdate()
    plazo = _ultimo_dia_del_mes(date(anio, mes, 1))
    pendientes = [(inf, dia) for inf in informes for dia in inf.dias if dia.bloques_falta]
    nombres = {inf.user.pk: inf.nombre for inf in informes}
    permisos = list(PermisoAsistencia.objects.filter(
        user_id__in=list(nombres), fecha__gte=date(anio, mes, 1), fecha__lte=plazo
    ).select_related('registrado_por').order_by('fecha', 'user_id'))
    for pm in permisos:
        pm.profesional_nombre = nombres.get(pm.user_id, pm.user.get_full_name())
        pm.puede_quitar = hoy <= pm.plazo_hasta
    from profesionales.models import Profesional
    from servicios.models import Sucursal
    return render(request, 'asistencia/admin/justificaciones.html', {
        'pendientes': pendientes, 'permisos': permisos, 'form': PermisoAsistenciaForm(),
        'anio': anio, 'mes': mes, 'periodo': f"{MESES[mes]} {anio}",
        'plazo': plazo, 'en_plazo': hoy <= plazo,
        'sucursal': sucursal, 'profesional': profesional,
        'sucursales': Sucursal.objects.filter(activa=True),
        'profesionales': Profesional.objects.filter(activo=True, user__isnull=False).order_by('apellido', 'nombre'),
        'meses': [(m, MESES[m]) for m in range(1, 13)],
        'anios': list(range(max(2024, hoy.year - 3), hoy.year + 1)),
        'seccion': 'justificaciones',
    })


@solo_admin
@require_POST
def justificar_falta(request):
    """Registra el permiso de una falta (todo el día o un bloque), con el detalle del justificativo escrito."""
    from profesionales.models import Profesional
    try:
        uid = int(request.POST.get('user', ''))
        fecha = date.fromisoformat(request.POST.get('fecha', ''))
    except ValueError:
        messages.error(request, 'Datos inválidos para justificar.')
        return redirect('asistencia:justificaciones')
    volver = redirect(f"{reverse('asistencia:justificaciones')}?mes={fecha.month}&anio={fecha.year}")
    bloque = request.POST.get('bloque', '').strip()

    prof = (Profesional.objects.filter(user_id=uid, activo=True).select_related('user')
            .prefetch_related('sucursales').first())
    if prof is None:
        messages.error(request, 'No se encontró al profesional.')
        return volver
    plazo = _ultimo_dia_del_mes(fecha)
    if timezone.localdate() > plazo:
        messages.error(request, f'El plazo para justificar terminó el {plazo:%d/%m/%Y} (último día del mes de la falta). '
                                'Esa falta queda con descuento.')
        return volver
    informe = construir_informes_mensuales([prof], fecha.year, fecha.month)[0]
    dia = next(d for d in informe.dias if d.fecha == fecha)
    if not dia.bloques_falta:
        messages.error(request, 'Ese día no figura como falta sin justificar.')
        return volver
    if bloque and (not bloque.isdigit() or int(bloque) not in dia.bloques_falta):
        messages.error(request, 'Ese bloque no figura como falta.')
        return volver

    form = PermisoAsistenciaForm(request.POST, request.FILES)
    if not form.is_valid():
        for errores in form.errors.values():
            for e in errores:
                messages.error(request, e)
        return volver
    permiso = PermisoAsistencia.objects.filter(user_id=uid, fecha=fecha, bloque=bloque).first() \
        or PermisoAsistencia(user_id=uid, fecha=fecha, bloque=bloque)
    permiso.tipo = form.cleaned_data['tipo']
    permiso.detalle = form.cleaned_data['detalle']
    if form.cleaned_data.get('comprobante'):
        permiso.comprobante = form.cleaned_data['comprobante']
    permiso.registrado_por = request.user
    permiso.save()
    alcance = 'todo el día' if not bloque else f'el bloque {bloque}'
    messages.success(request, f'Falta justificada: {prof.nombre} {prof.apellido}, {fecha:%d/%m/%Y} ({alcance}). '
                              'Ya no genera descuento.')
    return volver


@solo_admin
@require_POST
def quitar_permiso(request, pk):
    """Quita un permiso (la falta vuelve a tener descuento). Solo dentro del plazo del mes."""
    permiso = get_object_or_404(PermisoAsistencia.objects.select_related('user'), pk=pk)
    volver = redirect(f"{reverse('asistencia:justificaciones')}?mes={permiso.fecha.month}&anio={permiso.fecha.year}")
    if timezone.localdate() > permiso.plazo_hasta:
        messages.error(request, f'Ese mes ya cerró ({permiso.plazo_hasta:%d/%m/%Y}): el permiso no se puede quitar.')
        return volver
    permiso.delete()
    messages.success(request, 'Permiso quitado: la falta vuelve a tener descuento.')
    return volver
