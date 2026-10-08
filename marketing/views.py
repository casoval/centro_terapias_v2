"""
marketing/views.py

Interfaz del módulo. TODAS las vistas son solo para superusuario
(`superusuario_requerido`) y toda acción que cambia datos exige POST.
"""

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import (
    ActivoForm, CampanaForm, ConfigForm, FichaForm, GenerarGuionForm, MarcaForm,
)
from .guiones import GuionError, aprobar_guion, crear_guion_manual, generar_guiones
from .models import (
    Activo, AuditoriaMarketing, Campana, ConfigMarketing, FichaContenido, Guion, Marca, RegistroGasto,
)
from .permissions import superusuario_requerido
from .proveedores.base import ProveedorError
from .proveedores.registro import listar_proveedores_texto, obtener_proveedor_texto
from .sincronizacion import sincronizar_fichas_centro


def _siguiente(request, defecto):
    """Redirige a `next` solo si es una ruta interna de este sitio (evita redirects abiertos)."""
    destino = request.POST.get('next', '')
    if destino and url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()},
                                                   require_https=request.is_secure()):
        return redirect(destino)
    return redirect(defecto)


def _auditar(request, accion, objeto, detalle=None):
    AuditoriaMarketing.objects.create(
        usuario=request.user, accion=accion, objeto_tipo=type(objeto).__name__,
        objeto_id=str(objeto.pk), detalle=detalle or {},
    )


# ══════════════════════════════════════════════════════════════════════════
# PANEL
# ══════════════════════════════════════════════════════════════════════════

@superusuario_requerido
def panel(request):
    config = ConfigMarketing.get()
    gasto = RegistroGasto.total_mes()
    presupuesto = config.presupuesto_mensual_usd
    porcentaje = int(min(100, (gasto / presupuesto) * 100)) if presupuesto and presupuesto > 0 else 0

    proveedores = listar_proveedores_texto()
    avisos = []
    if not any(p['disponible'] for p in proveedores):
        avisos.append('No hay ningún modelo de IA con clave configurada (GEMINI_API_KEY o GROQ_API_KEY en el .env).')
    if not getattr(settings, 'MARKETING_R2_CONFIGURADO', False):
        if getattr(settings, 'IS_PRODUCTION', False):
            avisos.append('El almacenamiento (bucket R2 de marketing) no está configurado: no se podrán subir archivos.')
        else:
            avisos.append('Modo desarrollo: los archivos se guardan en una carpeta local, no en R2.')
    if not Marca.objects.exists():
        avisos.append('Aún no hay marcas. Ejecuta: python manage.py cargar_marcas_iniciales')
    if not FichaContenido.objects.filter(aprobada=True, activa=True).exists():
        avisos.append('No hay fichas de contenido aprobadas. Sin ellas la IA no puede escribir guiones.')

    contexto = {
        'seccion': 'panel',
        'marcas': Marca.objects.filter(activa=True),
        'fichas_aprobadas': FichaContenido.objects.filter(aprobada=True, activa=True).count(),
        'fichas_pendientes': FichaContenido.objects.filter(aprobada=False, activa=True).count(),
        'campanas_por_estado': dict(Campana.objects.values_list('estado').annotate(n=Count('id'))),
        'guiones_por_estado': dict(Guion.objects.values_list('estado').annotate(n=Count('id'))),
        'activos_total': Activo.objects.filter(activo=True).count(),
        'gasto': gasto, 'presupuesto': presupuesto, 'porcentaje': porcentaje,
        'proveedores': proveedores, 'avisos': avisos,
        'campanas_recientes': Campana.objects.select_related('marca')[:6],
        'guiones_recientes': Guion.objects.select_related('campana', 'campana__marca')[:6],
    }
    return render(request, 'marketing/panel.html', contexto)


# ══════════════════════════════════════════════════════════════════════════
# CAMPAÑAS Y GUIONES
# ══════════════════════════════════════════════════════════════════════════

@superusuario_requerido
def campana_lista(request):
    qs = Campana.objects.select_related('marca').annotate(n_guiones=Count('guiones'))
    marca = request.GET.get('marca', '')
    estado = request.GET.get('estado', '')
    if marca.isdigit():
        qs = qs.filter(marca_id=int(marca))
    if estado in dict(Campana.ESTADO_CHOICES):
        qs = qs.filter(estado=estado)
    elif not estado:
        qs = qs.exclude(estado='archivada')
    return render(request, 'marketing/campana_lista.html', {
        'seccion': 'campanas', 'campanas': qs, 'marcas': Marca.objects.filter(activa=True),
        'marca_sel': marca, 'estado_sel': estado, 'estados': Campana.ESTADO_CHOICES,
    })


@superusuario_requerido
def campana_crear(request):
    form = CampanaForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        campana = form.save(commit=False)
        campana.creada_por = request.user
        campana.save()
        form.save_m2m()
        _auditar(request, 'campana_creada', campana)
        messages.success(request, 'Campaña creada. Ahora puedes generar su guion.')
        return redirect('marketing:campana_detalle', pk=campana.pk)
    return render(request, 'marketing/campana_form.html', {
        'seccion': 'campanas', 'form': form, 'titulo': 'Nueva campaña', 'campana': None,
    })


@superusuario_requerido
def campana_editar(request, pk):
    campana = get_object_or_404(Campana, pk=pk)
    form = CampanaForm(request.POST or None, instance=campana)
    if request.method == 'POST' and form.is_valid():
        form.save()
        _auditar(request, 'campana_editada', campana)
        messages.success(request, 'Campaña actualizada.')
        return redirect('marketing:campana_detalle', pk=campana.pk)
    return render(request, 'marketing/campana_form.html', {
        'seccion': 'campanas', 'form': form, 'titulo': f'Editar: {campana.titulo}', 'campana': campana,
    })


@superusuario_requerido
def campana_detalle(request, pk):
    campana = get_object_or_404(Campana.objects.select_related('marca'), pk=pk)
    return render(request, 'marketing/campana_detalle.html', {
        'seccion': 'campanas', 'campana': campana,
        'guiones': campana.guiones.all(),
        'fichas': campana.fichas.all(),
        'form_generar': GenerarGuionForm(),
        'fichas_aprobadas': campana.fichas.filter(aprobada=True, activa=True).count(),
        'puede_generar': campana.quien_escribe != 'usuario',
    })


@superusuario_requerido
@require_POST
def campana_archivar(request, pk):
    campana = get_object_or_404(Campana, pk=pk)
    campana.estado = 'archivada' if campana.estado != 'archivada' else 'borrador'
    campana.save(update_fields=['estado', 'actualizada'])
    _auditar(request, 'campana_estado', campana, {'estado': campana.estado})
    messages.success(request, f'Campaña {"archivada" if campana.estado == "archivada" else "restaurada"}.')
    return redirect('marketing:campana_lista')


@superusuario_requerido
@require_POST
def guion_generar(request, pk):
    campana = get_object_or_404(Campana, pk=pk)
    form = GenerarGuionForm(request.POST)
    if not form.is_valid():
        messages.error(request, 'Revisa los datos para generar el guion.')
        return redirect('marketing:campana_detalle', pk=pk)
    try:
        proveedor = obtener_proveedor_texto(form.cleaned_data['proveedor'] or None)
        guiones = generar_guiones(
            campana, cantidad=int(form.cleaned_data['cantidad']), proveedor=proveedor,
            usuario=request.user, instrucciones_extra=form.cleaned_data['instrucciones_extra'],
        )
    except (GuionError, ProveedorError) as e:
        messages.error(request, str(e))
        return redirect('marketing:campana_detalle', pk=pk)
    if campana.estado == 'borrador':
        campana.estado = 'en_curso'
        campana.save(update_fields=['estado', 'actualizada'])
    validos = sum(1 for g in guiones if g.estado == 'validado')
    if validos == len(guiones):
        messages.success(request, f'{len(guiones)} guion(es) generado(s) y válido(s). Revísalos y apruébalos.')
    else:
        messages.warning(request, f'{len(guiones)} generado(s); {len(guiones) - validos} no pasó la validación (ver detalle).')
    return redirect('marketing:campana_detalle', pk=pk)


def _escenas_desde_post(post):
    cols = [post.getlist(k) for k in ('texto_pantalla', 'locucion', 'prompt_visual', 'duracion_seg')]
    escenas = []
    for tp, lo, pv, du in zip(*cols):
        if not (tp.strip() or lo.strip() or pv.strip()):
            continue
        try:
            dur = float(du.replace(',', '.')) if du.strip() else 4.0
        except ValueError:
            dur = 4.0
        escenas.append({'texto_pantalla': tp, 'locucion': lo, 'prompt_visual': pv, 'duracion_seg': dur})
    return escenas


@superusuario_requerido
def guion_manual(request, pk):
    """Escribir un guion a mano. Con ?base=<id> parte de otro guion (nueva versión editada)."""
    campana = get_object_or_404(Campana, pk=pk)
    inicial = {'gancho': '', 'caption': '', 'hashtags': '', 'escenas': [{}]}
    base_id = request.GET.get('base', '')
    if base_id.isdigit():
        base = Guion.objects.filter(pk=int(base_id), campana=campana).first()
        if base:
            inicial = {'gancho': base.gancho, 'caption': base.caption, 'hashtags': base.hashtags,
                       'escenas': base.escenas or [{}]}
    if request.method == 'POST':
        gancho = request.POST.get('gancho', '')
        caption = request.POST.get('caption', '')
        hashtags = request.POST.get('hashtags', '')
        escenas = _escenas_desde_post(request.POST)
        try:
            g = crear_guion_manual(campana, gancho, escenas, caption, hashtags, usuario=request.user)
        except GuionError as e:
            messages.error(request, str(e))
        else:
            if g.estado == 'validado':
                messages.success(request, f'Guion v{g.version} guardado y válido.')
            else:
                messages.warning(request, f'Guion v{g.version} guardado, pero no pasó la validación.')
            return redirect('marketing:campana_detalle', pk=pk)
        inicial = {'gancho': gancho, 'caption': caption, 'hashtags': hashtags, 'escenas': escenas or [{}]}
    return render(request, 'marketing/guion_manual.html', {
        'seccion': 'campanas', 'campana': campana, 'inicial': inicial,
    })


@superusuario_requerido
@require_POST
def guion_aprobar(request, pk):
    guion = get_object_or_404(Guion, pk=pk)
    try:
        aprobar_guion(guion, request.user)
        messages.success(request, f'Guion v{guion.version} aprobado.')
    except GuionError as e:
        messages.error(request, str(e))
    return redirect('marketing:campana_detalle', pk=guion.campana_id)


@superusuario_requerido
@require_POST
def guion_eliminar(request, pk):
    guion = get_object_or_404(Guion, pk=pk)
    campana_id = guion.campana_id
    if guion.piezas.exists():
        messages.error(request, 'Este guion ya tiene piezas creadas y no se puede eliminar.')
    elif guion.estado == 'aprobado':
        messages.error(request, 'Un guion aprobado no se elimina.')
    else:
        _auditar(request, 'guion_eliminado', guion, {'version': guion.version})
        guion.delete()
        messages.success(request, 'Guion eliminado.')
    return redirect('marketing:campana_detalle', pk=campana_id)


# ══════════════════════════════════════════════════════════════════════════
# FICHAS DE CONTENIDO
# ══════════════════════════════════════════════════════════════════════════

@superusuario_requerido
def ficha_lista(request):
    qs = FichaContenido.objects.select_related('marca')
    marca = request.GET.get('marca', '')
    estado = request.GET.get('estado', '')
    if marca.isdigit():
        qs = qs.filter(marca_id=int(marca))
    if estado == 'aprobadas':
        qs = qs.filter(aprobada=True)
    elif estado == 'pendientes':
        qs = qs.filter(aprobada=False)
    return render(request, 'marketing/ficha_lista.html', {
        'seccion': 'fichas', 'fichas': qs, 'marcas': Marca.objects.filter(activa=True),
        'marca_sel': marca, 'estado_sel': estado,
    })


@superusuario_requerido
def ficha_crear(request):
    form = FichaForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        ficha = form.save()
        _auditar(request, 'ficha_creada', ficha)
        messages.success(request, 'Ficha creada. Recuerda aprobarla para que la IA pueda usarla.')
        return redirect('marketing:ficha_lista')
    return render(request, 'marketing/form_generico.html', {
        'seccion': 'fichas', 'form': form, 'titulo': 'Nueva ficha de contenido',
        'volver': 'marketing:ficha_lista',
        'ayuda': 'Escribe solo hechos verificados del servicio, producto o programa. La IA no podrá afirmar nada fuera de las fichas aprobadas.',
    })


@superusuario_requerido
def ficha_editar(request, pk):
    ficha = get_object_or_404(FichaContenido, pk=pk)
    form = FichaForm(request.POST or None, instance=ficha)
    if request.method == 'POST' and form.is_valid():
        texto_cambio = 'texto' in form.changed_data
        ficha = form.save(commit=False)
        if texto_cambio and ficha.aprobada:
            ficha.aprobada, ficha.aprobada_por, ficha.aprobada_en = False, None, None
            messages.warning(request, 'Cambiaste el texto: la ficha volvió a quedar SIN aprobar.')
        ficha.save()
        _auditar(request, 'ficha_editada', ficha)
        messages.success(request, 'Ficha guardada.')
        return redirect('marketing:ficha_lista')
    return render(request, 'marketing/form_generico.html', {
        'seccion': 'fichas', 'form': form, 'titulo': f'Editar ficha: {ficha.titulo}',
        'volver': 'marketing:ficha_lista',
        'ayuda': 'Si cambias el texto, la ficha tendrá que aprobarse de nuevo.',
    })


@superusuario_requerido
@require_POST
def ficha_aprobar(request, pk):
    ficha = get_object_or_404(FichaContenido, pk=pk)
    if ficha.aprobada:
        ficha.aprobada, ficha.aprobada_por, ficha.aprobada_en = False, None, None
        accion, msg = 'ficha_desaprobada', 'Ficha marcada como sin aprobar.'
    else:
        ficha.aprobada, ficha.aprobada_por, ficha.aprobada_en = True, request.user, timezone.now()
        accion, msg = 'ficha_aprobada', 'Ficha aprobada.'
    ficha.save()
    _auditar(request, accion, ficha)
    messages.success(request, msg)
    return _siguiente(request, 'marketing:ficha_lista')


@superusuario_requerido
@require_POST
def ficha_sincronizar(request):
    try:
        r = sincronizar_fichas_centro()
    except ValueError as e:
        messages.error(request, str(e))
    else:
        messages.success(
            request,
            f'Sincronizado: {r["creadas"]} creada(s), {r["actualizadas"]} actualizada(s), '
            f'{r["sin_cambios"]} sin cambios, {r["conservadas_editadas"]} conservada(s) por estar editadas a mano. '
            'Las nuevas o actualizadas quedan sin aprobar.',
        )
    return redirect('marketing:ficha_lista')


# ══════════════════════════════════════════════════════════════════════════
# MARCAS
# ══════════════════════════════════════════════════════════════════════════

@superusuario_requerido
def marca_lista(request):
    return render(request, 'marketing/marca_lista.html', {
        'seccion': 'marcas',
        'marcas': Marca.objects.annotate(n_fichas=Count('fichas', distinct=True), n_campanas=Count('campanas', distinct=True)),
    })


@superusuario_requerido
def marca_editar(request, pk):
    marca = get_object_or_404(Marca, pk=pk)
    form = MarcaForm(request.POST or None, instance=marca)
    if request.method == 'POST' and form.is_valid():
        form.save()
        _auditar(request, 'marca_editada', marca)
        messages.success(request, f'Marca «{marca.nombre}» actualizada.')
        return redirect('marketing:marca_lista')
    return render(request, 'marketing/form_generico.html', {
        'seccion': 'marcas', 'form': form, 'titulo': f'Editar marca: {marca.nombre}',
        'volver': 'marketing:marca_lista',
        'ayuda': 'Las palabras prohibidas y las reglas de contenido se aplican a todos los guiones de esta marca.',
    })


# ══════════════════════════════════════════════════════════════════════════
# ACTIVOS
# ══════════════════════════════════════════════════════════════════════════

@superusuario_requerido
def activo_lista(request):
    qs = Activo.objects.select_related('marca')
    marca = request.GET.get('marca', '')
    if marca.isdigit():
        qs = qs.filter(marca_id=int(marca))
    return render(request, 'marketing/activo_lista.html', {
        'seccion': 'activos', 'activos': qs, 'marcas': Marca.objects.filter(activa=True), 'marca_sel': marca,
    })


@superusuario_requerido
def activo_subir(request):
    form = ActivoForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        try:
            activo = form.save(commit=False)
            activo.subido_por = request.user
            # El atomic propio aísla el fallo del almacenamiento: si falla, solo se
            # revierte este guardado y la página puede seguir consultando la base.
            with transaction.atomic():
                activo.save()
        except ImproperlyConfigured as e:
            messages.error(request, str(e))
        else:
            _auditar(request, 'activo_subido', activo)
            messages.success(request, 'Archivo subido.')
            return redirect('marketing:activo_lista')
    return render(request, 'marketing/form_generico.html', {
        'seccion': 'activos', 'form': form, 'titulo': 'Subir foto, video o audio', 'multipart': True,
        'volver': 'marketing:activo_lista',
        'ayuda': 'Si en el archivo aparecen personas —y más aún niños— necesitas autorización escrita. '
                 'Sin ella, el archivo queda bloqueado y no se podrá usar en campañas.',
    })


@superusuario_requerido
@require_POST
def activo_toggle(request, pk):
    activo = get_object_or_404(Activo, pk=pk)
    activo.activo = not activo.activo
    activo.save(update_fields=['activo'])
    _auditar(request, 'activo_activado' if activo.activo else 'activo_desactivado', activo)
    messages.success(request, 'Activo ' + ('activado.' if activo.activo else 'desactivado.'))
    return _siguiente(request, 'marketing:activo_lista')


# ══════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ══════════════════════════════════════════════════════════════════════════

@superusuario_requerido
def config_editar(request):
    config = ConfigMarketing.get()
    form = ConfigForm(request.POST or None, instance=config)
    if request.method == 'POST' and form.is_valid():
        form.save()
        _auditar(request, 'config_editada', config)
        messages.success(request, 'Configuración guardada.')
        return redirect('marketing:config')
    return render(request, 'marketing/form_generico.html', {
        'seccion': 'config', 'form': form, 'titulo': 'Configuración de Marketing',
        'volver': 'marketing:panel',
        'ayuda': 'Las claves de los modelos de IA se definen en el archivo .env del servidor, nunca aquí.',
    })
