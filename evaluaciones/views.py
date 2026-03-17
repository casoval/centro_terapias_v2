"""
Vistas para las evaluaciones ADOS-2, ADI-R e Informes PDF.
Usa HTMX para autoguardado y navegación por secciones sin recargar.
"""

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST
from django.utils import timezone

from .models import EvaluacionADOS2, EvaluacionADIR, InformeEvaluacion
from .forms import (
    EvaluacionADOS2GeneralForm,
    ADOS2Modulo1ComunicacionForm, ADOS2Modulo1InteraccionForm, ADOS2Modulo1RRBForm,
    ADOS2Modulo2Form, ADOS2Modulo3Form, ADOS2Modulo4Form, ADOS2ModuloTForm,
    ADOS2ObservacionesForm,
    EvaluacionADIRGeneralForm, ADIRHistoriaDesarrolloForm,
    ADIRComunicacionVerbalesForm, ADIRComunicacionNoVerbalesForm,
    ADIRInteraccionSocialForm,
    ADIRComportamientoRRForm, ADIRObservacionesForm,
    InformeEvaluacionForm,
)

# ─────────────────────────────────────────────
# Mapa de formularios ADOS-2 por módulo
# ─────────────────────────────────────────────

ADOS2_FORMS_POR_MODULO = {
    '1': [
        ('comunicacion', ADOS2Modulo1ComunicacionForm,
         'Dominio A — Comunicación', 'evaluaciones/ados2/seccion_modulo1_com.html'),
        ('interaccion', ADOS2Modulo1InteraccionForm,
         'Dominio B — Interacción Social', 'evaluaciones/ados2/seccion_modulo1_soc.html'),
        ('rrb', ADOS2Modulo1RRBForm,
         'Dominio C — Comportamiento Restringido', 'evaluaciones/ados2/seccion_rrb.html'),
        ('observaciones', ADOS2ObservacionesForm,
         'Observaciones finales', 'evaluaciones/ados2/seccion_observaciones.html'),
    ],
    '2': [
        ('items', ADOS2Modulo2Form, 'Ítems Módulo 2', 'evaluaciones/ados2/seccion_modulo2.html'),
        ('observaciones', ADOS2ObservacionesForm,
         'Observaciones finales', 'evaluaciones/ados2/seccion_observaciones.html'),
    ],
    '3': [
        ('items', ADOS2Modulo3Form, 'Ítems Módulo 3', 'evaluaciones/ados2/seccion_modulo3.html'),
        ('observaciones', ADOS2ObservacionesForm,
         'Observaciones finales', 'evaluaciones/ados2/seccion_observaciones.html'),
    ],
    '4': [
        ('items', ADOS2Modulo4Form, 'Ítems Módulo 4', 'evaluaciones/ados2/seccion_modulo4.html'),
        ('observaciones', ADOS2ObservacionesForm,
         'Observaciones finales', 'evaluaciones/ados2/seccion_observaciones.html'),
    ],
    'T': [
        ('items', ADOS2ModuloTForm, 'Ítems Módulo T', 'evaluaciones/ados2/seccion_moduloT.html'),
        ('observaciones', ADOS2ObservacionesForm,
         'Observaciones finales', 'evaluaciones/ados2/seccion_observaciones.html'),
    ],
}


# ═══════════════════════════════════════════════════════════════
# VISTAS GENERALES
# ═══════════════════════════════════════════════════════════════

@login_required
def dashboard_evaluaciones(request):
    """Panel principal de evaluaciones."""
    evaluaciones_ados2 = EvaluacionADOS2.objects.select_related(
        'paciente', 'evaluador').order_by('-fecha_evaluacion')[:10]
    evaluaciones_adir = EvaluacionADIR.objects.select_related(
        'paciente', 'evaluador').order_by('-fecha_evaluacion')[:10]
    informes = InformeEvaluacion.objects.select_related(
        'paciente', 'evaluador').order_by('-fecha_informe')[:10]

    context = {
        'evaluaciones_ados2': evaluaciones_ados2,
        'evaluaciones_adir': evaluaciones_adir,
        'informes': informes,
        'total_ados2': EvaluacionADOS2.objects.count(),
        'total_adir': EvaluacionADIR.objects.count(),
        'total_informes': InformeEvaluacion.objects.count(),
    }
    return render(request, 'evaluaciones/dashboard.html', context)


# ═══════════════════════════════════════════════════════════════
# VISTAS ADOS-2
# ═══════════════════════════════════════════════════════════════

@login_required
def ados2_lista(request):
    """Listado de evaluaciones ADOS-2."""
    evaluaciones = EvaluacionADOS2.objects.select_related(
        'paciente', 'evaluador').order_by('-fecha_evaluacion')
    return render(request, 'evaluaciones/ados2/lista.html',
                  {'evaluaciones': evaluaciones})


@login_required
def ados2_crear(request):
    """
    Paso 1: Crear evaluación ADOS-2 con datos generales.
    Al guardar redirige al formulario de ítems del módulo seleccionado.
    """
    if request.method == 'POST':
        form = EvaluacionADOS2GeneralForm(request.POST)
        if form.is_valid():
            eval_obj = form.save(commit=False)
            try:
                eval_obj.evaluador = request.user.profesional
            except Exception:
                pass  # si el usuario no tiene profesional vinculado
            eval_obj.save()
            messages.success(request, f'Evaluación ADOS-2 Módulo {eval_obj.modulo} creada.')
            return redirect('evaluaciones:ados2_items', pk=eval_obj.pk)
    else:
        form = EvaluacionADOS2GeneralForm(user=request.user)

    return render(request, 'evaluaciones/ados2/crear.html', {'form': form})


@login_required
def ados2_items(request, pk):
    """
    Paso 2: Formulario de ítems según el módulo seleccionado.
    Usa secciones HTMX para guardar sección por sección.
    """
    evaluacion = get_object_or_404(EvaluacionADOS2, pk=pk)
    secciones = ADOS2_FORMS_POR_MODULO.get(evaluacion.modulo, [])

    context = {
        'evaluacion': evaluacion,
        'secciones': [
            {
                'key': key,
                'label': label,
                'template': tpl,
                'form': FormClass(instance=evaluacion),
            }
            for key, FormClass, label, tpl in secciones
        ],
    }
    return render(request, 'evaluaciones/ados2/items.html', context)


@login_required
@require_POST
def ados2_guardar_seccion(request, pk, seccion):
    """
    Vista HTMX: guarda una sección de ítems ADOS-2 y devuelve
    el fragmento HTML actualizado con puntuaciones.
    """
    evaluacion = get_object_or_404(EvaluacionADOS2, pk=pk)
    secciones = ADOS2_FORMS_POR_MODULO.get(evaluacion.modulo, [])

    # Buscar el formulario correspondiente a la sección
    form_data = next(
        ((key, FormClass, label, tpl)
         for key, FormClass, label, tpl in secciones if key == seccion),
        None
    )

    if not form_data:
        return HttpResponse('Sección no encontrada', status=404)

    key, FormClass, label, tpl = form_data
    form = FormClass(request.POST, instance=evaluacion)

    if form.is_valid():
        form.save()  # save() dispara calcular_puntuaciones()
        evaluacion.refresh_from_db()

        # Devolver fragmento con resumen de puntuaciones (para HTMX)
        if request.headers.get('HX-Request'):
            html = render_to_string('evaluaciones/ados2/partials/puntuaciones.html',
                                    {'evaluacion': evaluacion})
            return HttpResponse(html)
        messages.success(request, f'Sección "{label}" guardada correctamente.')
    else:
        if request.headers.get('HX-Request'):
            html = render_to_string(tpl, {'form': form, 'evaluacion': evaluacion})
            return HttpResponse(html, status=422)
        messages.error(request, 'Error al guardar. Revise los campos.')

    return redirect('evaluaciones:ados2_items', pk=pk)


@login_required
def ados2_detalle(request, pk):
    """Vista de detalle con puntuaciones y clasificación."""
    evaluacion = get_object_or_404(
        EvaluacionADOS2.objects.select_related('paciente', 'evaluador'), pk=pk)
    return render(request, 'evaluaciones/ados2/detalle.html',
                  {'evaluacion': evaluacion})


@login_required
def ados2_editar(request, pk):
    evaluacion = get_object_or_404(EvaluacionADOS2, pk=pk)
    if request.method == 'POST':
        form = EvaluacionADOS2GeneralForm(request.POST, instance=evaluacion)
        if form.is_valid():
            form.save()
            messages.success(request, 'Evaluación actualizada.')
            return redirect('evaluaciones:ados2_detalle', pk=pk)
    else:
        form = EvaluacionADOS2GeneralForm(instance=evaluacion)
    return render(request, 'evaluaciones/ados2/crear.html',
                  {'form': form, 'editar': True, 'evaluacion': evaluacion})


@login_required
def ados2_eliminar(request, pk):
    evaluacion = get_object_or_404(EvaluacionADOS2, pk=pk)
    if request.method == 'POST':
        evaluacion.delete()
        messages.success(request, 'Evaluación ADOS-2 eliminada.')
        return redirect('evaluaciones:ados2_lista')
    return render(request, 'evaluaciones/ados2/confirmar_eliminar.html',
                  {'evaluacion': evaluacion})


# ═══════════════════════════════════════════════════════════════
# VISTAS ADI-R
# ═══════════════════════════════════════════════════════════════

ADIR_SECCIONES = [
    ('general', EvaluacionADIRGeneralForm, 'Datos generales',
     'evaluaciones/adir/seccion_general.html'),
    ('historia', ADIRHistoriaDesarrolloForm, 'Historia del desarrollo',
     'evaluaciones/adir/seccion_historia.html'),
    # El formulario de comunicación se elige dinámicamente según tipo_comunicacion
    # Se usa Verbales por defecto; la vista adir_items lo ajusta según la evaluación
    ('comunicacion_verbal', ADIRComunicacionVerbalesForm, 'A — Lenguaje Verbal (ítems 9-19)',
     'evaluaciones/adir/seccion_comunicacion.html'),
    ('comunicacion_no_verbal', ADIRComunicacionNoVerbalesForm, 'A — Comunicación No Verbal',
     'evaluaciones/adir/seccion_comunicacion.html'),
    ('interaccion', ADIRInteraccionSocialForm, 'B — Interacción Social',
     'evaluaciones/adir/seccion_interaccion.html'),
    ('comportamiento', ADIRComportamientoRRForm, 'C — Comportamientos RR',
     'evaluaciones/adir/seccion_comportamiento.html'),
    ('observaciones', ADIRObservacionesForm, 'Observaciones finales',
     'evaluaciones/adir/seccion_observaciones.html'),
]


@login_required
def adir_lista(request):
    evaluaciones = EvaluacionADIR.objects.select_related(
        'paciente', 'evaluador').order_by('-fecha_evaluacion')
    return render(request, 'evaluaciones/adir/lista.html',
                  {'evaluaciones': evaluaciones})


@login_required
def adir_crear(request):
    """Paso 1: Crear evaluación ADI-R con datos generales."""
    if request.method == 'POST':
        form = EvaluacionADIRGeneralForm(request.POST)
        if form.is_valid():
            eval_obj = form.save(commit=False)
            try:
                eval_obj.evaluador = request.user.profesional
            except Exception:
                pass  # si el usuario no tiene profesional vinculado
            eval_obj.save()
            messages.success(request, 'Evaluación ADI-R creada.')
            return redirect('evaluaciones:adir_items', pk=eval_obj.pk)
    else:
        form = EvaluacionADIRGeneralForm(user=request.user)

    return render(request, 'evaluaciones/adir/crear.html', {'form': form})


@login_required
def adir_items(request, pk):
    """
    Formulario de ítems ADI-R por secciones con HTMX.
    Filtra la sección de comunicación según tipo_comunicacion del evaluado
    (verbal → ADIRComunicacionVerbalesForm; no_verbal → ADIRComunicacionNoVerbalesForm).
    """
    evaluacion = get_object_or_404(EvaluacionADIR, pk=pk)
    es_verbal = evaluacion.tipo_comunicacion == 'verbal'

    secciones_render = []
    for key, FormClass, label, tpl in ADIR_SECCIONES:
        # Saltar la sección de comunicación que NO corresponde al tipo del evaluado
        if key == 'comunicacion_verbal' and not es_verbal:
            continue
        if key == 'comunicacion_no_verbal' and es_verbal:
            continue
        secciones_render.append({
            'key': key,
            'label': label,
            'template': tpl,
            'form': FormClass(instance=evaluacion),
        })

    return render(request, 'evaluaciones/adir/items.html', {
        'evaluacion': evaluacion,
        'secciones': secciones_render,
        'es_verbal': es_verbal,
    })


@login_required
@require_POST
def adir_guardar_seccion(request, pk, seccion):
    """Vista HTMX: guarda sección ADI-R y devuelve puntuaciones parciales."""
    evaluacion = get_object_or_404(EvaluacionADIR, pk=pk)

    form_data = next(
        ((key, FormClass, label, tpl)
         for key, FormClass, label, tpl in ADIR_SECCIONES if key == seccion),
        None
    )

    if not form_data:
        return HttpResponse('Sección no encontrada', status=404)

    key, FormClass, label, tpl = form_data
    form = FormClass(request.POST, instance=evaluacion)

    if form.is_valid():
        form.save()
        evaluacion.refresh_from_db()

        if request.headers.get('HX-Request'):
            html = render_to_string(
                'evaluaciones/adir/partials/algoritmo.html',
                {'evaluacion': evaluacion}
            )
            return HttpResponse(html)
        messages.success(request, f'Sección "{label}" guardada.')
    else:
        if request.headers.get('HX-Request'):
            html = render_to_string(tpl, {'form': form, 'evaluacion': evaluacion})
            return HttpResponse(html, status=422)
        messages.error(request, 'Error al guardar.')

    return redirect('evaluaciones:adir_items', pk=pk)


@login_required
def adir_detalle(request, pk):
    evaluacion = get_object_or_404(
        EvaluacionADIR.objects.select_related('paciente', 'evaluador'), pk=pk)
    return render(request, 'evaluaciones/adir/detalle.html',
                  {'evaluacion': evaluacion})


@login_required
def adir_eliminar(request, pk):
    evaluacion = get_object_or_404(EvaluacionADIR, pk=pk)
    if request.method == 'POST':
        evaluacion.delete()
        messages.success(request, 'Evaluación ADI-R eliminada.')
        return redirect('evaluaciones:adir_lista')
    return render(request, 'evaluaciones/adir/confirmar_eliminar.html',
                  {'evaluacion': evaluacion})


# ═══════════════════════════════════════════════════════════════
# VISTAS INFORMES
# ═══════════════════════════════════════════════════════════════

@login_required
def informe_lista(request):
    informes = InformeEvaluacion.objects.select_related(
        'paciente', 'evaluador').order_by('-fecha_informe')
    return render(request, 'evaluaciones/reports/lista.html',
                  {'informes': informes})


@login_required
def informe_crear(request):
    """Crear informe combinado ADOS-2 + ADI-R."""
    if request.method == 'POST':
        form = InformeEvaluacionForm(request.POST)
        if form.is_valid():
            informe = form.save(commit=False)
            try:
                informe.evaluador = request.user.profesional
            except Exception:
                pass
            informe.save()
            messages.success(request, 'Informe creado correctamente.')
            return redirect('evaluaciones:informe_detalle', pk=informe.pk)
    else:
        form = InformeEvaluacionForm(user=request.user)

    return render(request, 'evaluaciones/reports/crear.html', {'form': form})


@login_required
def informe_detalle(request, pk):
    informe = get_object_or_404(
        InformeEvaluacion.objects.select_related(
            'paciente', 'evaluador', 'evaluacion_ados2', 'evaluacion_adir'),
        pk=pk
    )
    return render(request, 'evaluaciones/reports/detalle.html',
                  {'informe': informe})


@login_required
def informe_editar(request, pk):
    informe = get_object_or_404(InformeEvaluacion, pk=pk)
    if request.method == 'POST':
        form = InformeEvaluacionForm(request.POST, instance=informe)
        if form.is_valid():
            form.save()
            messages.success(request, 'Informe actualizado.')
            return redirect('evaluaciones:informe_detalle', pk=pk)
    else:
        form = InformeEvaluacionForm(instance=informe)
    return render(request, 'evaluaciones/reports/crear.html',
                  {'form': form, 'editar': True, 'informe': informe})


@login_required
def informe_pdf(request, pk):
    """
    Genera y descarga el informe en formato PDF.
    Intenta en orden: xhtml2pdf (más fácil en Windows), ReportLab, fallback HTML.
    Instalar con: pip install xhtml2pdf
    """
    informe = get_object_or_404(
        InformeEvaluacion.objects.select_related(
            'paciente', 'evaluador',
            'evaluacion_ados2', 'evaluacion_ados2__paciente',
            'evaluacion_adir', 'evaluacion_adir__paciente',
        ),
        pk=pk
    )

    context = {
        'informe': informe,
        'paciente': informe.paciente,
        'ados2': informe.evaluacion_ados2,
        'adir': informe.evaluacion_adir,
        'fecha_generacion': timezone.now(),
        'request': request,
    }

    html_string = render_to_string('evaluaciones/reports/pdf_template.html', context)
    nombre_paciente = informe.paciente.nombre_completo.replace(' ', '_')
    filename = f'Informe_ADOS2_ADIR_{nombre_paciente}_{informe.fecha_informe}.pdf'

    # ── Opción 1: xhtml2pdf (funciona en Windows sin dependencias del sistema) ──
    try:
        from xhtml2pdf import pisa
        import io

        pdf_buffer = io.BytesIO()
        pisa_status = pisa.CreatePDF(
            src=html_string,
            dest=pdf_buffer,
            encoding='utf-8',
        )

        if not pisa_status.err:
            response = HttpResponse(pdf_buffer.getvalue(), content_type='application/pdf')
            response['Content-Disposition'] = f'inline; filename="{filename}"'
            return response
        else:
            raise Exception(f'xhtml2pdf error: {pisa_status.err}')

    except ImportError:
        pass  # xhtml2pdf no instalado, intentar siguiente opción

    # ── Opción 2: WeasyPrint (mejor calidad, requiere librerías del sistema) ──
    try:
        from weasyprint import HTML

        pdf_file = HTML(
            string=html_string,
            base_url=request.build_absolute_uri('/')
        ).write_pdf()

        response = HttpResponse(pdf_file, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="{filename}"'
        return response

    except ImportError:
        pass  # WeasyPrint no instalado

    # ── Opción 3: Fallback — devolver HTML para imprimir desde el navegador ──
    html_response = render_to_string('evaluaciones/reports/pdf_print.html', context)
    return HttpResponse(
        html_response,
        content_type='text/html; charset=utf-8',
        headers={
            # ✅ CORRECCIÓN: comillas añadidas alrededor de ".pdf" y ".html"
            'Content-Disposition': f'inline; filename="{filename.replace(".pdf", ".html")}"'
        }
    )


@login_required
def informe_eliminar(request, pk):
    informe = get_object_or_404(InformeEvaluacion, pk=pk)
    if request.method == 'POST':
        informe.delete()
        messages.success(request, 'Informe eliminado.')
        return redirect('evaluaciones:informe_lista')
    return render(request, 'evaluaciones/reports/confirmar_eliminar.html',
                  {'informe': informe})


# ═══════════════════════════════════════════════════════════════
# HTMX — Autocomplete / búsqueda de paciente
# ═══════════════════════════════════════════════════════════════

@login_required
def htmx_buscar_paciente(request):
    """Búsqueda dinámica de paciente para los formularios."""
    q = request.GET.get('q', '')
    from pacientes.models import Paciente
    pacientes = Paciente.objects.filter(
        nombre__icontains=q
    )[:10] if q else []

    return render(request, 'evaluaciones/partials/paciente_options.html',
                  {'pacientes': pacientes})


@login_required
def htmx_edad_paciente(request):
    """
    HTMX: Devuelve la edad cronológica del paciente seleccionado
    en relación a la fecha de evaluación para pre-rellenar los campos de edad.
    """
    from pacientes.models import Paciente
    from datetime import date

    paciente_id = request.GET.get('paciente')
    fecha_eval_str = request.GET.get('fecha_evaluacion', '')

    if not paciente_id:
        return HttpResponse('')

    try:
        pac = Paciente.objects.get(pk=paciente_id)
        try:
            fecha_eval = date.fromisoformat(fecha_eval_str)
        except (ValueError, TypeError):
            fecha_eval = date.today()

        delta = fecha_eval - pac.fecha_nacimiento
        anos = delta.days // 365
        meses_extra = (delta.days % 365) // 30

        diagnostico_resumen = ''
        if pac.diagnostico:
            diagnostico_resumen = f' · Dx previo: {pac.diagnostico[:60]}'

        html = (
            f'<div class="alert alert-info py-2 mb-0 small">'
            f'<i class="bi bi-person-check me-1"></i>'
            f'<strong>{pac.nombre_completo}</strong> — '
            f'Edad al evaluar: <strong>{anos} años {meses_extra} meses</strong>'
            f'<br><small class="text-muted">'
            f'Nacimiento: {pac.fecha_nacimiento.strftime("%d/%m/%Y")} · '
            f'Género: {pac.get_genero_display()}'
            f'{diagnostico_resumen}'
            f'</small></div>'
            f'<script>'
            f'document.querySelector("[name=edad_cronologica_anos]").value={anos};'
            f'document.querySelector("[name=edad_cronologica_meses]").value={meses_extra};'
            f'</script>'
        )
        return HttpResponse(html)
    except (Paciente.DoesNotExist, Exception):
        return HttpResponse('')


@login_required
def htmx_evaluaciones_paciente(request):
    """
    HTMX: Devuelve los selects de evaluaciones del paciente elegido
    para inyectarlos en #evaluaciones-asociadas del formulario de Informe.
    """
    paciente_id = request.GET.get('paciente', '')

    def _select_ados2(opts, selected=''):
        items = '<option value="">— Sin ADOS-2 —</option>'
        for ev in opts:
            sel = 'selected' if str(ev.pk) == str(selected) else ''
            items += (
                f'<option value="{ev.pk}" {sel}>' 
                f'Módulo {ev.modulo} — {ev.fecha_evaluacion:%d/%m/%Y} ' 
                f'[{ev.get_clasificacion_display()}]</option>'
            )
        return items

    def _select_adir(opts, selected=''):
        items = '<option value="">— Sin ADI-R —</option>'
        for ev in opts:
            sel = 'selected' if str(ev.pk) == str(selected) else ''
            items += (
                f'<option value="{ev.pk}" {sel}>' 
                f'{ev.fecha_evaluacion:%d/%m/%Y} ' 
                f'[{ev.get_clasificacion_display()}]</option>'
            )
        return items

    tw = (
        "w-full px-3 py-2.5 border-2 border-slate-200 rounded-xl "
        "text-sm font-medium focus:outline-none bg-white"
    )

    if not paciente_id:
        html = (
            '<div class="flex flex-col items-center justify-center py-6 text-center text-slate-400 gap-2">' 
            '<div class="text-3xl">👆</div>' 
            '<p class="text-sm font-medium">Selecciona un paciente para ver sus evaluaciones disponibles</p>' 
            '<input type="hidden" name="evaluacion_ados2" value="">' 
            '<input type="hidden" name="evaluacion_adir" value="">' 
            '</div>'
        )
        return HttpResponse(html)

    ados2_list = EvaluacionADOS2.objects.filter(
        paciente_id=paciente_id).order_by('-fecha_evaluacion')
    adir_list = EvaluacionADIR.objects.filter(
        paciente_id=paciente_id).order_by('-fecha_evaluacion')

    sin_ados2 = not ados2_list.exists()
    sin_adir  = not adir_list.exists()

    aviso = ''
    if sin_ados2 and sin_adir:
        aviso = (
            '<div class="col-span-2 text-center text-xs text-amber-600 bg-amber-50 ' 
            'rounded-lg py-2 px-3 border border-amber-100 mt-1">' 
            '⚠️ Este paciente no tiene evaluaciones ADOS-2 ni ADI-R registradas todavía.' 
            '</div>'
        )

    html = (
        f'<div class="grid grid-cols-1 sm:grid-cols-2 gap-4">' 
        f'<div>' 
        f'<label class="block text-xs font-semibold text-slate-500 mb-1.5">📋 Evaluación ADOS-2</label>' 
        f'<select name="evaluacion_ados2" class="{tw} focus:border-blue-400">' 
        f'{_select_ados2(ados2_list)}</select>' 
        f'</div>' 
        f'<div>' 
        f'<label class="block text-xs font-semibold text-slate-500 mb-1.5">🗒️ Evaluación ADI-R</label>' 
        f'<select name="evaluacion_adir" class="{tw} focus:border-green-400">' 
        f'{_select_adir(adir_list)}</select>' 
        f'</div>' 
        f'{aviso}' 
        f'</div>'
    )
    return HttpResponse(html)

# ═══════════════════════════════════════════════════════════════
# REFERENCIA DE PUNTUACIONES
# ═══════════════════════════════════════════════════════════════

@login_required
def referencia_puntuaciones(request):
    """Vista de referencia rápida: puntos de corte ADOS-2 y ADI-R con simulador."""
    return render(request, 'evaluaciones/referencia.html')