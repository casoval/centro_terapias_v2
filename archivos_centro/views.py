from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponseForbidden
from django.db.models import Q, Count
from django.core.paginator import Paginator

from .models import ArchivoCentro, CategoriaArchivo, ArchivoRolPermitido, ArchivoUsuarioPermitido
from .forms import ArchivoCentroForm, CategoriaArchivoForm, PermisosArchivoForm
from .permissions import (
    es_staff_del_centro, puede_ver_archivo, puede_subir_archivos,
    puede_eliminar_archivos, puede_editar_visibilidad_simple,
    puede_gestionar_permisos_avanzados, puede_gestionar_categorias,
)


def _acceso_denegado(request, mensaje='❌ No tienes acceso a este módulo.'):
    messages.error(request, mensaje)
    return HttpResponseForbidden('No autorizado')


@login_required
def lista_archivos(request):
    """
    Listado principal. El admin ve todo. Los demás ven: lo suyo + lo que
    tenga visibilidad 'todos' + lo que tenga 'roles'/'usuarios' que los
    incluya.
    """
    if not es_staff_del_centro(request.user):
        return _acceso_denegado(request)

    qs = ArchivoCentro.objects.select_related('categoria', 'subido_por').all()

    if not request.user.is_superuser:
        perfil = getattr(request.user, 'perfil', None)
        rol = perfil.rol if perfil else None
        filtro_visible = (
            Q(subido_por=request.user)
            | Q(visibilidad='todos')
            | Q(visibilidad='roles', roles_permitidos__rol=rol)
            | Q(visibilidad='usuarios', usuarios_permitidos__usuario=request.user)
        )
        qs = qs.filter(filtro_visible).distinct()

    categoria_id = request.GET.get('categoria')
    if categoria_id:
        qs = qs.filter(categoria_id=categoria_id)

    q = request.GET.get('q')
    if q:
        qs = qs.filter(Q(titulo__icontains=q) | Q(descripcion__icontains=q))

    solo_mios = request.GET.get('mios')
    if solo_mios:
        qs = qs.filter(subido_por=request.user)

    paginator = Paginator(qs, 24)
    page = paginator.get_page(request.GET.get('page'))

    context = {
        'archivos': page,
        'categorias': CategoriaArchivo.objects.all(),
        'categoria_actual': categoria_id,
        'q': q or '',
        'solo_mios': bool(solo_mios),
        'puede_subir': puede_subir_archivos(request.user),
        'puede_eliminar': puede_eliminar_archivos(request.user),
        'puede_gestionar_permisos': puede_gestionar_permisos_avanzados(request.user),
        'puede_gestionar_categorias': puede_gestionar_categorias(request.user),
    }
    return render(request, 'archivos_centro/lista.html', context)


@login_required
def subir_archivo(request):
    if not puede_subir_archivos(request.user):
        return _acceso_denegado(request, '❌ No tienes permiso para subir archivos.')

    if request.method == 'POST':
        form = ArchivoCentroForm(
            request.POST, request.FILES,
            es_admin=request.user.is_superuser,
            instance=ArchivoCentro(subido_por=request.user),
        )
        if form.is_valid():
            archivo = form.save(commit=False)
            archivo.subido_por = request.user
            archivo.save()
            form.guardar_permisos_avanzados(archivo)
            messages.success(request, f'✅ Archivo "{archivo.titulo}" subido correctamente.')
            return redirect('archivos_centro:lista')
        messages.error(request, '❌ Revisa los datos del formulario.')
    else:
        form = ArchivoCentroForm(es_admin=request.user.is_superuser)

    return render(request, 'archivos_centro/subir.html', {'form': form, 'es_admin': request.user.is_superuser})


@login_required
def editar_archivo(request, archivo_id):
    """
    Edición básica (título, descripción, categoría) + visibilidad simple.
    Permitido al dueño del archivo o al admin. Para permisos avanzados
    (roles/usuarios específicos) ver `gestionar_permisos`, exclusivo admin.
    """
    archivo = get_object_or_404(ArchivoCentro, pk=archivo_id)

    if not puede_editar_visibilidad_simple(request.user, archivo):
        return _acceso_denegado(request, '❌ Solo quien subió este archivo (o un administrador) puede editarlo.')

    if request.method == 'POST':
        form = ArchivoCentroForm(
            request.POST, request.FILES,
            es_admin=request.user.is_superuser,
            instance=archivo,
        )
        # Un usuario común no puede tocar el binario al editar, solo metadatos + visibilidad simple.
        form.fields['archivo'].required = False
        if form.is_valid():
            archivo_guardado = form.save()
            form.guardar_permisos_avanzados(archivo_guardado)
            messages.success(request, f'✅ "{archivo.titulo}" actualizado.')
            return redirect('archivos_centro:lista')
        messages.error(request, '❌ Revisa los datos del formulario.')
    else:
        form = ArchivoCentroForm(es_admin=request.user.is_superuser, instance=archivo)
        form.fields['archivo'].required = False

    return render(request, 'archivos_centro/editar.html', {'form': form, 'archivo': archivo, 'es_admin': request.user.is_superuser})


@login_required
def eliminar_archivo(request, archivo_id):
    """Solo el administrador (superusuario) puede eliminar archivos del centro."""
    archivo = get_object_or_404(ArchivoCentro, pk=archivo_id)

    if not puede_eliminar_archivos(request.user):
        return _acceso_denegado(request, '❌ Solo un administrador puede eliminar archivos.')

    if request.method == 'POST':
        titulo = archivo.titulo
        archivo.archivo.delete(save=False)
        archivo.delete()
        messages.success(request, f'🗑️ "{titulo}" eliminado.')
        return redirect('archivos_centro:lista')

    return render(request, 'archivos_centro/confirmar_eliminar.html', {'archivo': archivo})


@login_required
def descargar_archivo(request, archivo_id):
    """Redirige al archivo (URL firmada de R2 o local) validando permisos primero."""
    archivo = get_object_or_404(ArchivoCentro, pk=archivo_id)
    if not puede_ver_archivo(request.user, archivo):
        return _acceso_denegado(request)
    return redirect(archivo.archivo.url)


@login_required
def gestionar_permisos(request, archivo_id):
    """
    Pantalla exclusiva de admin: cambia la visibilidad de CUALQUIER
    archivo a privado/todos/roles específicos/usuarios específicos.
    """
    archivo = get_object_or_404(ArchivoCentro, pk=archivo_id)

    if not puede_gestionar_permisos_avanzados(request.user):
        return _acceso_denegado(request, '❌ Solo un administrador puede gestionar permisos.')

    if request.method == 'POST':
        form = PermisosArchivoForm(request.POST)
        if form.is_valid():
            archivo.visibilidad = form.cleaned_data['visibilidad']
            archivo.save(update_fields=['visibilidad'])

            ArchivoRolPermitido.objects.filter(archivo=archivo).delete()
            if archivo.visibilidad == 'roles':
                ArchivoRolPermitido.objects.bulk_create([
                    ArchivoRolPermitido(archivo=archivo, rol=rol)
                    for rol in form.cleaned_data['roles']
                ])

            ArchivoUsuarioPermitido.objects.filter(archivo=archivo).delete()
            if archivo.visibilidad == 'usuarios':
                ArchivoUsuarioPermitido.objects.bulk_create([
                    ArchivoUsuarioPermitido(archivo=archivo, usuario=usuario)
                    for usuario in form.cleaned_data['usuarios']
                ])

            messages.success(request, f'🔐 Permisos de "{archivo.titulo}" actualizados.')
            return redirect('archivos_centro:lista')
        messages.error(request, '❌ Revisa los datos del formulario.')
    else:
        form = PermisosArchivoForm(initial={
            'visibilidad': archivo.visibilidad,
            'roles': list(archivo.roles_permitidos.values_list('rol', flat=True)),
            'usuarios': list(archivo.usuarios_permitidos.values_list('usuario_id', flat=True)),
        })

    return render(request, 'archivos_centro/permisos.html', {'form': form, 'archivo': archivo})


@login_required
def lista_categorias(request):
    if not puede_gestionar_categorias(request.user):
        return _acceso_denegado(request, '❌ Solo admin o gerente pueden gestionar categorías.')

    if request.method == 'POST':
        form = CategoriaArchivoForm(request.POST)
        if form.is_valid():
            categoria = form.save(commit=False)
            categoria.creada_por = request.user
            categoria.save()
            messages.success(request, f'✅ Categoría "{categoria.nombre}" creada.')
            return redirect('archivos_centro:categorias')
        messages.error(request, '❌ Revisa los datos del formulario.')
    else:
        form = CategoriaArchivoForm()

    categorias = CategoriaArchivo.objects.annotate(num_archivos=Count('archivos')).order_by('nombre')

    return render(request, 'archivos_centro/categorias.html', {'form': form, 'categorias': categorias})


@login_required
def eliminar_categoria(request, categoria_id):
    if not puede_gestionar_categorias(request.user):
        return _acceso_denegado(request, '❌ Solo admin o gerente pueden gestionar categorías.')

    categoria = get_object_or_404(CategoriaArchivo, pk=categoria_id)
    if request.method == 'POST':
        nombre = categoria.nombre
        categoria.delete()  # los archivos quedan con categoria=None (SET_NULL)
        messages.success(request, f'🗑️ Categoría "{nombre}" eliminada. Sus archivos pasaron a "Sin categoría".')
    return redirect('archivos_centro:categorias')
