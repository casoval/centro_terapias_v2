from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
import hashlib

from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .alertas import alertas_para
from .forms import AnuncioForm
from .models import Anuncio, AnuncioLectura
from .visibilidad import (ROL_ADMIN, anuncio_visible_para, anuncios_historial, anuncios_vigentes,
                          rol_de, usuarios_destino)

SESSION_FIRMA = 'avisos_popup_firma'


def solo_admin(view):
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_superuser:
            messages.error(request, 'Solo el administrador puede gestionar anuncios.')
            return redirect('avisos:lista')
        return view(request, *args, **kwargs)
    wrapper.__name__ = view.__name__
    wrapper.__doc__ = view.__doc__
    return wrapper


def _serializar_anuncio(a, leidos):
    return {
        'id': a.id, 'titulo': a.titulo, 'mensaje': a.mensaje,
        'urgente': a.es_urgente(),
        'adjunto_url': a.adjunto.url if a.adjunto else '',
        'adjunto_tipo': a.adjunto_tipo(),
        'hasta': a.fecha_fin.strftime('%d/%m/%Y'),
        'destinatarios': a.destinatarios_texto(),
        'pedir_confirmacion': a.pedir_confirmacion,
        'leido': a.id in leidos,
    }


@login_required
@require_GET
@ensure_csrf_cookie
def popup_data(request):
    """Datos del pop-up de inicio (solo se consulta desde la página de inicio del rol)."""
    hoy = timezone.localdate()
    alertas = alertas_para(request.user, hoy)
    anuncios = []
    if rol_de(request.user) != ROL_ADMIN:      # el admin gestiona desde la pestaña Avisos
        anuncios = list(anuncios_vigentes(request.user, hoy))
    leidos = set(AnuncioLectura.objects.filter(user=request.user, anuncio__in=anuncios)
                 .values_list('anuncio_id', flat=True)) if anuncios else set()
    total = len(alertas) + len(anuncios)

    # Admin/gerente/recepción: se muestra cada vez que entran al panel principal.
    # Profesional y paciente: una vez por inicio de sesión y una vez por día (sus páginas de inicio
    # tienen filtros y vistas que recargan la página); vuelve a salir si aparece algo nuevo.
    mostrar = total > 0
    if mostrar and rol_de(request.user) in ('profesional', 'paciente'):
        firma = hashlib.sha1((hoy.isoformat() + '#' + '|'.join(sorted(a['clave'] for a in alertas)) + '#' +
                              ','.join(str(a.id) for a in anuncios)).encode()).hexdigest()
        if request.session.get(SESSION_FIRMA) == firma:
            mostrar = False
        else:
            request.session[SESSION_FIRMA] = firma
    return JsonResponse({
        'total': total, 'mostrar': mostrar,
        'alertas': alertas,
        'anuncios': [_serializar_anuncio(a, leidos) for a in anuncios],
        'url_avisos': reverse('avisos:lista'),
    })


@login_required
@ensure_csrf_cookie
def lista(request):
    hoy = timezone.localdate()
    vigentes = list(anuncios_vigentes(request.user, hoy))
    historial = list(anuncios_historial(request.user, hoy))
    leidos = set(AnuncioLectura.objects.filter(user=request.user).values_list('anuncio_id', flat=True))
    es_admin = request.user.is_superuser
    conteo = {}
    if es_admin:
        from django.db.models import Count
        conteo = dict(AnuncioLectura.objects.values_list('anuncio_id').annotate(n=Count('id')))
    for a in vigentes + historial:
        a.leido = a.id in leidos
        a.n_lecturas = conteo.get(a.id, 0)
    return render(request, 'avisos/lista.html', {
        'vigentes': vigentes, 'historial': historial, 'es_admin': es_admin,
        'vigentes_count': len(vigentes),
    })


@login_required
@require_POST
def marcar_leido(request, pk):
    anuncio = get_object_or_404(Anuncio, pk=pk)
    if not anuncio.pedir_confirmacion or not anuncio_visible_para(request.user, anuncio):
        return JsonResponse({'ok': False}, status=403)
    AnuncioLectura.objects.get_or_create(anuncio=anuncio, user=request.user)
    return JsonResponse({'ok': True})


@solo_admin
def crear(request):
    hoy = timezone.localdate()
    form = AnuncioForm(request.POST or None, request.FILES or None,
                       initial={'fecha_inicio': hoy, 'fecha_fin': hoy, 'guardar_en_historial': True})
    if request.method == 'POST' and form.is_valid():
        obj = form.save(commit=False)
        obj.creado_por = request.user
        obj.save()
        form.save_m2m()
        messages.success(request, 'Anuncio publicado.')
        return redirect('avisos:lista')
    return render(request, 'avisos/form.html', {'form': form, 'titulo_pagina': 'Nuevo anuncio'})


@solo_admin
def editar(request, pk):
    anuncio = get_object_or_404(Anuncio, pk=pk)
    form = AnuncioForm(request.POST or None, request.FILES or None, instance=anuncio)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Anuncio actualizado.')
        return redirect('avisos:lista')
    return render(request, 'avisos/form.html', {'form': form, 'anuncio': anuncio, 'titulo_pagina': 'Editar anuncio'})


@solo_admin
def eliminar(request, pk):
    anuncio = get_object_or_404(Anuncio, pk=pk)
    if request.method == 'POST':
        anuncio.delete()
        messages.success(request, 'Anuncio eliminado.')
        return redirect('avisos:lista')
    return render(request, 'avisos/confirmar_eliminar.html', {'anuncio': anuncio})


@solo_admin
def lecturas(request, pk):
    anuncio = get_object_or_404(Anuncio, pk=pk)
    confirmaron = {l.user_id: l.fecha for l in anuncio.lecturas.all()}
    destino = list(usuarios_destino(anuncio))
    filas = [{'user': u, 'fecha': confirmaron.get(u.id)} for u in destino]
    filas.sort(key=lambda f: (f['fecha'] is not None, (f['user'].get_full_name() or f['user'].username).lower()))
    return render(request, 'avisos/lecturas.html', {
        'anuncio': anuncio, 'filas': filas,
        'n_confirmaron': sum(1 for f in filas if f['fecha']), 'n_total': len(filas),
    })
