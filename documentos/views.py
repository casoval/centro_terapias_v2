from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Count, Q, Max
from django.http import HttpResponseForbidden

from pacientes.models import Paciente
from agenda.models import Proyecto, Mensualidad, Sesion
from .models import DocumentoPaciente, PlanTrabajo
from .forms import DocumentoPacienteForm, PlanTrabajoForm
from .permissions import (
    puede_ver_documentos, puede_subir_documentos,
    puede_eliminar_documentos, es_profesional,
)
from integracion_misael_kids import misael_kids_client as mk


@login_required
def subir_documento(request, paciente_id):
    """
    Vista genérica de subida. Recibe por querystring/POST opcionalmente
    `proyecto_id` o `mensualidad_id` para pre-seleccionar el destino
    (cuando se abre desde el detalle de un proyecto o mensualidad).
    Si no se envía ninguno, el documento queda como "general".
    """
    paciente = get_object_or_404(Paciente, pk=paciente_id)

    if not puede_subir_documentos(request.user, paciente):
        messages.error(request, '❌ No tienes permiso para subir documentos de este paciente.')
        return HttpResponseForbidden('No autorizado')

    proyecto_id = request.POST.get('proyecto_id') or request.GET.get('proyecto_id')
    mensualidad_id = request.POST.get('mensualidad_id') or request.GET.get('mensualidad_id')

    if request.method == 'POST':
        form = DocumentoPacienteForm(
            request.POST, request.FILES, paciente=paciente,
            instance=DocumentoPaciente(paciente=paciente),
        )
        if form.is_valid():
            documento = form.save(commit=False)
            documento.paciente = paciente
            documento.subido_por = request.user
            documento.save()
            messages.success(request, f'✅ Documento "{documento.titulo}" subido correctamente.')
            return _redirigir_post_subida(request, paciente, documento)
        else:
            messages.error(request, '❌ Revisa los datos del formulario.')
    else:
        initial = {}
        if proyecto_id:
            initial['proyecto'] = proyecto_id
        if mensualidad_id:
            initial['mensualidad'] = mensualidad_id
        form = DocumentoPacienteForm(paciente=paciente, initial=initial)

    context = {
        'form': form,
        'paciente': paciente,
        'proyecto_id': proyecto_id,
        'mensualidad_id': mensualidad_id,
        'next_url': request.GET.get('next') or request.POST.get('next', ''),
    }
    return render(request, 'documentos/subir_documento.html', context)


def _redirigir_post_subida(request, paciente, documento):
    """Vuelve a donde el usuario estaba (proyecto, mensualidad, resumen o ficha)."""
    next_url = request.POST.get('next')
    if next_url:
        return redirect(next_url)
    if documento.proyecto_id:
        return redirect('agenda:detalle_proyecto', proyecto_id=documento.proyecto_id)
    if documento.mensualidad_id:
        return redirect('agenda:detalle_mensualidad', mensualidad_id=documento.mensualidad_id)
    if es_profesional(request.user):
        return redirect('documentos:resumen_paciente_profesional', paciente_id=paciente.id)
    return redirect('pacientes:detalle', pk=paciente.id)


@login_required
def eliminar_documento(request, documento_id):
    """Solo el administrador (superusuario) puede eliminar documentos."""
    documento = get_object_or_404(DocumentoPaciente, pk=documento_id)

    if not puede_eliminar_documentos(request.user):
        messages.error(request, '❌ Solo un administrador puede eliminar documentos.')
        return HttpResponseForbidden('No autorizado')

    if request.method == 'POST':
        paciente_id = documento.paciente_id
        proyecto_id = documento.proyecto_id
        mensualidad_id = documento.mensualidad_id
        titulo = documento.titulo
        documento.archivo.delete(save=False)
        documento.delete()
        messages.success(request, f'🗑️ Documento "{titulo}" eliminado.')

        next_url = request.POST.get('next')
        if next_url:
            return redirect(next_url)
        if proyecto_id:
            return redirect('agenda:detalle_proyecto', proyecto_id=proyecto_id)
        if mensualidad_id:
            return redirect('agenda:detalle_mensualidad', mensualidad_id=mensualidad_id)
        return redirect('pacientes:detalle', pk=paciente_id)

    return render(request, 'documentos/confirmar_eliminar.html', {'documento': documento})


@login_required
def popover_documentos(request):
    """
    Devuelve un fragmento HTML (para SweetAlert2 vía HTMX) con la lista de
    documentos de un proyecto o mensualidad puntual. Usado desde la columna
    "Archivos" en lista_proyectos.html / lista_mensualidades.html.
    """
    proyecto_id = request.GET.get('proyecto_id')
    mensualidad_id = request.GET.get('mensualidad_id')

    documentos = DocumentoPaciente.objects.none()
    paciente = None

    if proyecto_id:
        proyecto = get_object_or_404(Proyecto, pk=proyecto_id)
        paciente = proyecto.paciente
        documentos = proyecto.documentos.select_related('subido_por').order_by('-fecha_subida')
    elif mensualidad_id:
        mensualidad = get_object_or_404(Mensualidad, pk=mensualidad_id)
        paciente = mensualidad.paciente
        documentos = mensualidad.documentos.select_related('subido_por').order_by('-fecha_subida')

    if not paciente or not puede_ver_documentos(request.user, paciente):
        return HttpResponseForbidden('No autorizado')

    return render(request, 'documentos/_popover_lista.html', {
        'documentos': documentos,
        'puede_eliminar': puede_eliminar_documentos(request.user),
    })


@login_required
def resumen_paciente_profesional(request, paciente_id):
    """
    Página de resumen para el PROFESIONAL: proyectos, mensualidades (de
    cualquier profesional que atienda al paciente) + resumen de sesiones
    agrupado por servicio + documentos generales. Sin datos de pago.
    """
    paciente = get_object_or_404(Paciente, pk=paciente_id)

    if not puede_ver_documentos(request.user, paciente):
        messages.error(request, '❌ No tienes acceso al resumen de este paciente.')
        return redirect('profesionales:mis_pacientes')

    proyectos = paciente.proyectos.select_related('servicio_base').annotate(
        num_documentos=Count('documentos')
    ).order_by('-fecha_inicio')

    mensualidades = paciente.mensualidades.annotate(
        num_documentos=Count('documentos')
    ).order_by('-anio', '-mes')

    documentos_generales = paciente.documentos.filter(
        proyecto__isnull=True, mensualidad__isnull=True
    ).select_related('subido_por').order_by('-fecha_subida')

    planes_trabajo = paciente.planes_trabajo.select_related('profesional').order_by('-fecha_inicio')

    # El plan de trabajo solo se puede crear si el paciente ya está
    # vinculado con Misael Kids (si no, ¿para quién sería el plan?).
    # Si Misael Kids no está configurado o falla, se bloquea con aviso
    # en vez de permitir crear planes "a ciegas" — ver misael_kids_client.
    vinculado_misael_kids = False
    error_verificando_vinculo = False
    try:
        vinculado_misael_kids = mk.esta_vinculado(paciente.id)
    except (mk.MisaelKidsNoConfigurado, mk.MisaelKidsError):
        error_verificando_vinculo = True

    # Resumen de sesiones agrupado por servicio (todas, de cualquier profesional)
    sesiones_qs = Sesion.objects.filter(paciente=paciente).select_related('servicio')
    # ⚡ OPTIMIZACIÓN: ultima_fecha se anota en la MISMA consulta agrupada
    # (Max('fecha') sobre la misma relación ya agrupada por servicio, sin
    # riesgo de fan-out ya que no combina relaciones distintas). Antes se
    # hacía una query aparte POR CADA servicio para buscar su última fecha.
    resumen_servicios = (
        sesiones_qs.values('servicio__id', 'servicio__nombre')
        .annotate(
            total=Count('id'),
            realizadas=Count('id', filter=Q(estado__in=['realizada', 'realizada_retraso'])),
            programadas=Count('id', filter=Q(estado='programada')),
            faltas_canceladas=Count('id', filter=Q(estado__in=['falta', 'cancelada'])),
            ultima_fecha=Max('fecha'),
        )
        .order_by('servicio__nombre')
    )

    context = {
        'paciente': paciente,
        'proyectos': proyectos,
        'mensualidades': mensualidades,
        'documentos_generales': documentos_generales,
        'planes_trabajo': planes_trabajo,
        'vinculado_misael_kids': vinculado_misael_kids,
        'error_verificando_vinculo': error_verificando_vinculo,
        'resumen_servicios': resumen_servicios,
        'puede_subir': puede_subir_documentos(request.user, paciente),
    }
    return render(request, 'documentos/resumen_paciente_profesional.html', context)


def _es_profesional_autor(user):
    perfil = getattr(user, 'perfil', None)
    return bool(perfil and perfil.rol == 'profesional')


@login_required
def crear_plan_trabajo(request, paciente_id):
    """
    Crea un plan de trabajo para un paciente YA vinculado con Misael
    Kids. El paciente viene fijo por la URL (nunca se elige en el
    formulario) y, si el vínculo no existe, se bloquea antes de mostrar
    el formulario.
    """
    paciente = get_object_or_404(Paciente, pk=paciente_id)

    if not puede_subir_documentos(request.user, paciente):
        messages.error(request, '❌ No tienes permiso para crear planes de trabajo de este paciente.')
        return HttpResponseForbidden('No autorizado')

    try:
        vinculado = mk.esta_vinculado(paciente.id)
    except (mk.MisaelKidsNoConfigurado, mk.MisaelKidsError) as exc:
        messages.error(
            request,
            f'❌ No se pudo verificar el vínculo con Misael Kids ({exc}). '
            'Intenta de nuevo en unos minutos.',
        )
        return redirect('documentos:resumen_paciente_profesional', paciente_id=paciente.id)

    if not vinculado:
        messages.error(
            request,
            '❌ Este paciente todavía no está vinculado con Misael Kids. '
            'Vincúlalo primero desde la página de vinculación.',
        )
        return redirect('documentos:resumen_paciente_profesional', paciente_id=paciente.id)

    es_autor = _es_profesional_autor(request.user)

    if request.method == 'POST':
        form = PlanTrabajoForm(
            request.POST, request.FILES,
            es_profesional_autor=es_autor,
            instance=PlanTrabajo(paciente=paciente),
        )
        if form.is_valid():
            plan = form.save(commit=False)
            plan.paciente = paciente
            plan.profesional = request.user
            plan.save()
            messages.success(request, '✅ Plan de trabajo creado correctamente.')
            return redirect('documentos:resumen_paciente_profesional', paciente_id=paciente.id)
        messages.error(request, '❌ Revisa los datos del formulario.')
    else:
        form = PlanTrabajoForm(es_profesional_autor=es_autor)

    return render(request, 'documentos/plan_trabajo_form.html', {
        'form': form, 'paciente': paciente, 'es_autor': es_autor, 'editando': False,
    })


@login_required
def editar_plan_trabajo(request, plan_id):
    plan = get_object_or_404(PlanTrabajo, pk=plan_id)
    paciente = plan.paciente

    if not puede_subir_documentos(request.user, paciente):
        messages.error(request, '❌ No tienes permiso para editar este plan de trabajo.')
        return HttpResponseForbidden('No autorizado')

    es_autor = _es_profesional_autor(request.user)

    if request.method == 'POST':
        form = PlanTrabajoForm(request.POST, request.FILES, es_profesional_autor=es_autor, instance=plan)
        if form.is_valid():
            form.save()
            messages.success(request, '✅ Plan de trabajo actualizado.')
            return redirect('documentos:resumen_paciente_profesional', paciente_id=paciente.id)
        messages.error(request, '❌ Revisa los datos del formulario.')
    else:
        form = PlanTrabajoForm(es_profesional_autor=es_autor, instance=plan)

    return render(request, 'documentos/plan_trabajo_form.html', {
        'form': form, 'paciente': paciente, 'plan': plan, 'es_autor': es_autor, 'editando': True,
    })


@login_required
def eliminar_plan_trabajo(request, plan_id):
    """Solo el administrador (superusuario) puede eliminar planes de trabajo."""
    plan = get_object_or_404(PlanTrabajo, pk=plan_id)

    if not puede_eliminar_documentos(request.user):
        messages.error(request, '❌ Solo un administrador puede eliminar planes de trabajo.')
        return HttpResponseForbidden('No autorizado')

    if request.method == 'POST':
        paciente_id = plan.paciente_id
        if plan.archivo:
            plan.archivo.delete(save=False)
        plan.delete()
        messages.success(request, '🗑️ Plan de trabajo eliminado.')
        return redirect('documentos:resumen_paciente_profesional', paciente_id=paciente_id)

    return render(request, 'documentos/confirmar_eliminar_plan.html', {'plan': plan})
