"""
integracion_misael_kids/views_panel.py

Pantalla del lado de Centro Misael para:
  1. Buscar niños de Misael Kids que todavía no están vinculados.
  2. Vincularlos a un paciente YA EXISTENTE en Centro Misael, o crear
     el paciente automáticamente copiando los datos del niño.
  3. Ver la lista de vínculos existentes, con sus derivaciones.

Espejo de la pestaña "Vincular con Centro Misael" de Misael Kids, pero
en sentido inverso. El vínculo (VinculoCentroMisael) sigue viviendo
únicamente en Misael Kids — acá no se guarda ninguna copia, todo se
consulta/crea en vivo vía misael_kids_client.

Estas vistas son para el staff logueado del centro (no para Misael
Kids), por eso NO usan la autenticación por API key ni viven bajo
/api/ — se registran aparte, en urls_panel.py.
"""
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from pacientes.models import Paciente
from pacientes.forms import PacienteForm

from . import misael_kids_client as mk


def _puede_gestionar(user):
    if user.is_superuser:
        return True
    perfil = getattr(user, 'perfil', None)
    return bool(perfil and (perfil.es_gerente() or perfil.es_recepcionista()))


@login_required
def panel_vinculacion(request):
    """
    Pantalla principal con dos pestañas: "Vincular niño nuevo" y
    "Niños vinculados". Ambas se llenan por AJAX (ver vistas de abajo)
    para no bloquear la carga de la página si Misael Kids está lento
    o caído.
    """
    if not _puede_gestionar(request.user):
        messages.error(request, '❌ No tienes permiso para acceder a esta pantalla.')
        return redirect('core:dashboard')

    return render(request, 'integracion_misael_kids/panel_vinculacion.html')


@login_required
@require_GET
def api_buscar_ninos(request):
    """GET ?q=<texto> — niños de Misael Kids sin vincular todavía."""
    if not _puede_gestionar(request.user):
        return JsonResponse({'detail': 'Sin permiso.'}, status=403)

    q = request.GET.get('q', '').strip()
    try:
        ninos = mk.buscar_ninos_sin_vincular(q)
    except mk.MisaelKidsNoConfigurado as exc:
        return JsonResponse({'detail': str(exc)}, status=503)
    except mk.MisaelKidsError as exc:
        return JsonResponse({'detail': str(exc)}, status=502)
    return JsonResponse({'ninos': ninos})


@login_required
@require_GET
def api_buscar_pacientes(request):
    """GET ?q=<texto> — pacientes YA existentes en Centro Misael, para vincular a un niño."""
    if not _puede_gestionar(request.user):
        return JsonResponse({'detail': 'Sin permiso.'}, status=403)

    q = request.GET.get('q', '').strip()
    qs = Paciente.objects.all().order_by('apellido', 'nombre')
    if q:
        qs = qs.filter(
            Q(nombre__icontains=q) | Q(apellido__icontains=q) | Q(nombre_tutor__icontains=q)
        )
    qs = qs[:15]
    pacientes = [{
        'id': p.id,
        'nombre_completo': p.nombre_completo,
        'edad': p.edad,
        'estado': p.estado,
    } for p in qs]
    return JsonResponse({'pacientes': pacientes})


@login_required
@require_GET
def api_vinculados(request):
    """GET — lista de vínculos existentes con resumen de derivaciones."""
    if not _puede_gestionar(request.user):
        return JsonResponse({'detail': 'Sin permiso.'}, status=403)

    try:
        vinculos = mk.listar_vinculados()
    except mk.MisaelKidsNoConfigurado as exc:
        return JsonResponse({'detail': str(exc)}, status=503)
    except mk.MisaelKidsError as exc:
        return JsonResponse({'detail': str(exc)}, status=502)
    return JsonResponse({'vinculos': vinculos})


@login_required
@require_POST
def vincular_paciente_existente(request):
    """
    POST { nino_id, paciente_id } — vincula un niño de Misael Kids con
    un paciente que ya existe en Centro Misael.
    """
    if not _puede_gestionar(request.user):
        return JsonResponse({'detail': 'Sin permiso.'}, status=403)

    try:
        body = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'detail': 'Cuerpo inválido.'}, status=400)

    nino_id = body.get('nino_id')
    paciente_id = body.get('paciente_id')
    if not nino_id or not paciente_id:
        return JsonResponse({'detail': 'nino_id y paciente_id son requeridos.'}, status=400)

    paciente = get_object_or_404(Paciente, pk=paciente_id)

    try:
        resultado = mk.crear_vinculo(nino_id, paciente.id, paciente.nombre_completo)
    except mk.MisaelKidsNoConfigurado as exc:
        return JsonResponse({'detail': str(exc)}, status=503)
    except mk.MisaelKidsError as exc:
        return JsonResponse({'detail': str(exc)}, status=409)

    return JsonResponse({'ok': True, 'vinculo': resultado})


@login_required
def crear_paciente_y_vincular(request):
    """
    GET ?nino_id=<uuid> — muestra el formulario de paciente (el mismo
    de "Agregar paciente") pre-llenado con los datos del niño.
    POST — crea el Paciente y, si sale bien, vincula ese niño con el
    paciente recién creado en Misael Kids.

    Si el Paciente se crea pero el vínculo falla (ej. Misael Kids
    caído en ese instante), el Paciente queda creado igual — se avisa
    con un mensaje claro y se puede vincular después desde la pestaña
    "Vincular niño nuevo" > "usar paciente existente".
    """
    if not _puede_gestionar(request.user):
        messages.error(request, '❌ No tienes permiso para acceder a esta pantalla.')
        return redirect('core:dashboard')

    nino_id = request.GET.get('nino_id') or request.POST.get('nino_id')
    if not nino_id:
        messages.error(request, '❌ Falta indicar qué niño de Misael Kids vincular.')
        return redirect('integracion_misael_kids_panel:panel_vinculacion')

    try:
        nino = mk.obtener_nino(nino_id)
    except mk.MisaelKidsNoConfigurado as exc:
        messages.error(request, f'❌ {exc}')
        return redirect('integracion_misael_kids_panel:panel_vinculacion')
    except mk.MisaelKidsError as exc:
        messages.error(request, f'❌ No se pudo consultar a Misael Kids: {exc}')
        return redirect('integracion_misael_kids_panel:panel_vinculacion')

    if nino is None:
        messages.error(request, '❌ No se encontró ese niño en Misael Kids.')
        return redirect('integracion_misael_kids_panel:panel_vinculacion')

    if request.method == 'POST':
        form = PacienteForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            paciente = form.save()
            try:
                mk.crear_vinculo(nino_id, paciente.id, paciente.nombre_completo)
            except mk.MisaelKidsNoConfigurado as exc:
                messages.warning(
                    request,
                    f'⚠️ Se creó el paciente, pero no se pudo vincular automáticamente: {exc} '
                    'Podés vincularlo luego desde "Vincular niño nuevo" > paciente existente.'
                )
                return redirect('pacientes:detalle', pk=paciente.pk)
            except mk.MisaelKidsError as exc:
                messages.warning(
                    request,
                    f'⚠️ Se creó el paciente, pero el vínculo con Misael Kids falló: {exc} '
                    'Podés vincularlo luego desde "Vincular niño nuevo" > paciente existente.'
                )
                return redirect('pacientes:detalle', pk=paciente.pk)

            messages.success(
                request,
                f'✅ {paciente.nombre_completo} fue creado y vinculado con '
                f'{nino.get("nombre_completo", "el niño")} de Misael Kids.'
            )
            return redirect('pacientes:detalle', pk=paciente.pk)
    else:
        tutor_principal = (nino.get('tutores') or [None])[0] or {}
        # Misael Kids usa 'tutor_legal', Centro Misael usa 'tutor'.
        parentesco = tutor_principal.get('parentesco', 'otro')
        if parentesco == 'tutor_legal':
            parentesco = 'tutor'
        elif parentesco not in dict(Paciente.PARENTESCO_CHOICES):
            parentesco = 'otro'

        tutores = nino.get('tutores') or []
        segundo = tutores[1] if len(tutores) > 1 else None
        parentesco_2 = None
        if segundo:
            parentesco_2 = segundo.get('parentesco', 'otro')
            if parentesco_2 == 'tutor_legal':
                parentesco_2 = 'tutor'
            elif parentesco_2 not in dict(Paciente.PARENTESCO_CHOICES):
                parentesco_2 = 'otro'

        initial = {
            'nombre': nino.get('nombres', ''),
            'apellido': nino.get('apellidos', ''),
            'fecha_nacimiento': nino.get('fecha_nacimiento'),
            'genero': nino.get('genero') or 'O',
            'alergias': nino.get('alergias', ''),
            'observaciones_medicas': nino.get('condiciones_medicas', ''),
            'nombre_tutor': tutor_principal.get('nombre_completo', ''),
            'parentesco': parentesco,
            'telefono_tutor': tutor_principal.get('telefono', ''),
            'email_tutor': tutor_principal.get('email', ''),
        }
        if segundo:
            initial.update({
                'nombre_tutor_2': segundo.get('nombre_completo', ''),
                'parentesco_2': parentesco_2,
                'telefono_tutor_2': segundo.get('telefono', ''),
                'email_tutor_2': segundo.get('email', ''),
            })
        form = PacienteForm(initial=initial, user=request.user)

    return render(request, 'integracion_misael_kids/crear_paciente_vinculo.html', {
        'form': form,
        'nino': nino,
        'nino_id': nino_id,
    })
