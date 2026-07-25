from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponseForbidden
from django.db.models import Q, Count, ProtectedError
from django.core.exceptions import ValidationError

from servicios.models import Sucursal, TipoServicio
from .models import (
    TitularInventario, ItemInventario, CategoriaItemInventario,
    StockInventario, MovimientoInventario, TransferenciaInventario,
)
from .forms import (
    ItemInventarioForm, CategoriaItemForm, AgregarStockForm,
    AjustarStockForm, SolicitarTransferenciaForm, ResolverTransferenciaForm,
)
from . import services
from .permissions import (
    es_staff_del_centro, es_admin, ve_todo_el_inventario, sucursales_visibles,
    puede_ver_titular, puede_agregar_a_titular, puede_ajustar_o_eliminar_stock,
    puede_gestionar_catalogo, puede_solicitar_transferencia, puede_resolver_transferencias,
)


def _acceso_denegado(request, mensaje='❌ No tienes acceso a este módulo.'):
    messages.error(request, mensaje)
    return HttpResponseForbidden('No autorizado')


def _titulares_donde_puedo_agregar(user):
    """(titular, etiqueta) que el usuario puede alimentar: el suyo propio + sucursales asignadas."""
    opciones = []
    mi_titular = TitularInventario.de_usuario(user)
    opciones.append((mi_titular, '👤 Mi inventario personal'))

    if ve_todo_el_inventario(user):
        sucursales = Sucursal.objects.filter(activa=True)
    else:
        sucursales = sucursales_visibles(user) or []

    for suc in sucursales:
        titular_suc = TitularInventario.de_sucursal(suc)
        opciones.append((titular_suc, f'🏬 Sucursal: {suc.nombre}'))
    return opciones


@login_required
def mi_inventario(request):
    """Atajo: redirige al detalle del titular personal del usuario actual."""
    if not es_staff_del_centro(request.user):
        return _acceso_denegado(request)
    titular = TitularInventario.de_usuario(request.user)
    return redirect('inventario:detalle_titular', titular_id=titular.id)


@login_required
def inventario_general(request):
    """
    Listado de todos los titulares con inventario (admin/gerente ven todos;
    recepcionista/profesional ven el propio + el de sus sucursales asignadas).
    """
    if not es_staff_del_centro(request.user):
        return _acceso_denegado(request)

    titulares = TitularInventario.objects.select_related('sucursal', 'servicio', 'usuario').annotate(
        num_items=Count('stock', distinct=True)
    )

    if not ve_todo_el_inventario(request.user):
        mis_sucursales = sucursales_visibles(request.user) or []
        titulares = titulares.filter(
            Q(tipo='usuario', usuario=request.user) | Q(tipo='sucursal', sucursal__in=mis_sucursales)
        )

    tipo_filtro = request.GET.get('tipo')
    if tipo_filtro:
        titulares = titulares.filter(tipo=tipo_filtro)

    context = {
        'titulares': titulares.order_by('tipo'),
        'tipo_filtro': tipo_filtro,
        've_todo': ve_todo_el_inventario(request.user),
    }
    return render(request, 'inventario/general.html', context)


@login_required
def detalle_titular(request, titular_id):
    titular = get_object_or_404(TitularInventario, pk=titular_id)
    if not puede_ver_titular(request.user, titular):
        return _acceso_denegado(request, '❌ No tienes acceso a este inventario.')

    stock = StockInventario.objects.select_related('item', 'item__categoria').filter(titular=titular, cantidad__gt=0).order_by('item__nombre')
    q = request.GET.get('q')
    if q:
        stock = stock.filter(item__nombre__icontains=q)

    context = {
        'titular': titular,
        'stock': stock,
        'q': q or '',
        'puede_agregar': puede_agregar_a_titular(request.user, titular),
        'puede_ajustar': puede_ajustar_o_eliminar_stock(request.user),
        'puede_transferir': puede_solicitar_transferencia(request.user, titular),
        'es_mi_inventario': titular.tipo == 'usuario' and titular.usuario_id == request.user.id,
        'movimientos_recientes': MovimientoInventario.objects.select_related('item', 'realizado_por').filter(titular=titular)[:15],
    }
    return render(request, 'inventario/detalle_titular.html', context)


@login_required
def agregar_stock(request, titular_id=None):
    """
    Sumar cantidad al stock. Si viene `titular_id` en la URL, se preselecciona
    (debe ser uno de los titulares autorizados); si no, se elige en el form.
    """
    if not es_staff_del_centro(request.user):
        return _acceso_denegado(request)

    opciones = _titulares_donde_puedo_agregar(request.user)
    choices = [(str(t.id), label) for t, label in opciones]
    titulares_por_id = {t.id: t for t, _ in opciones}

    if not choices:
        messages.error(request, '❌ No tienes ningún inventario disponible para agregar stock.')
        return redirect('inventario:general')

    if request.method == 'POST':
        form = AgregarStockForm(request.POST, titulares_choices=choices)
        if form.is_valid():
            titular = titulares_por_id.get(int(form.cleaned_data['titular']))
            if not titular or not puede_agregar_a_titular(request.user, titular):
                return _acceso_denegado(request, '❌ No puedes agregar stock a ese inventario.')
            services.agregar_stock(
                request.user, titular, form.cleaned_data['item'],
                form.cleaned_data['cantidad'], form.cleaned_data['motivo'],
            )
            messages.success(request, f'✅ Se agregaron {form.cleaned_data["cantidad"]} × {form.cleaned_data["item"].nombre} a {titular}.')
            return redirect('inventario:detalle_titular', titular_id=titular.id)
        messages.error(request, '❌ Revisa los datos del formulario.')
    else:
        inicial = {}
        if titular_id and int(titular_id) in titulares_por_id:
            inicial['titular'] = str(titular_id)
        form = AgregarStockForm(titulares_choices=choices, initial=inicial)

    if not ItemInventario.objects.filter(activo=True).exists():
        messages.warning(request, '⚠️ Aún no hay ítems en el catálogo. Pide a un administrador o gerente que cree algunos.')

    return render(request, 'inventario/agregar_stock.html', {'form': form})


@login_required
def ajustar_stock(request, titular_id, item_id):
    """Exclusivo admin: fija manualmente el stock exacto de un ítem para un titular."""
    if not puede_ajustar_o_eliminar_stock(request.user):
        return _acceso_denegado(request, '❌ Solo un administrador puede ajustar el stock.')

    titular = get_object_or_404(TitularInventario, pk=titular_id)
    item = get_object_or_404(ItemInventario, pk=item_id)
    stock = StockInventario.objects.filter(titular=titular, item=item).first()
    cantidad_actual = stock.cantidad if stock else 0

    if request.method == 'POST':
        form = AjustarStockForm(request.POST)
        if form.is_valid():
            try:
                services.ajustar_stock(
                    request.user, titular, item,
                    form.cleaned_data['nueva_cantidad'], form.cleaned_data['motivo'],
                )
            except ValidationError as e:
                messages.error(request, f'❌ {e.message if hasattr(e, "message") else e}')
                return redirect('inventario:ajustar_stock', titular_id=titular.id, item_id=item.id)
            messages.success(request, f'✅ Stock de "{item.nombre}" en {titular} actualizado a {form.cleaned_data["nueva_cantidad"]}.')
            return redirect('inventario:detalle_titular', titular_id=titular.id)
        messages.error(request, '❌ Revisa los datos del formulario.')
    else:
        form = AjustarStockForm(initial={'nueva_cantidad': cantidad_actual})

    return render(request, 'inventario/ajustar_stock.html', {
        'form': form, 'titular': titular, 'item': item, 'cantidad_actual': cantidad_actual,
    })


# ==================== CATÁLOGO (admin/gerente) ====================

@login_required
def catalogo(request):
    if not puede_gestionar_catalogo(request.user):
        return _acceso_denegado(request, '❌ Solo admin o gerente gestionan el catálogo.')

    if request.method == 'POST':
        form = ItemInventarioForm(request.POST)
        if form.is_valid():
            item = form.save(commit=False)
            item.creado_por = request.user
            item.save()
            messages.success(request, f'✅ Ítem "{item.nombre}" creado.')
            return redirect('inventario:catalogo')
        messages.error(request, '❌ Revisa los datos del formulario.')
    else:
        form = ItemInventarioForm()

    items = ItemInventario.objects.select_related('categoria').order_by('-activo', 'nombre')
    return render(request, 'inventario/catalogo.html', {
        'form': form, 'items': items, 'form_categoria': CategoriaItemForm(),
        'categorias': CategoriaItemInventario.objects.all(),
    })


@login_required
def crear_categoria_item(request):
    if not puede_gestionar_catalogo(request.user):
        return _acceso_denegado(request)
    if request.method == 'POST':
        form = CategoriaItemForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, '✅ Categoría creada.')
        else:
            messages.error(request, '❌ Revisa los datos del formulario.')
    return redirect('inventario:catalogo')


@login_required
def editar_item(request, item_id):
    if not puede_gestionar_catalogo(request.user):
        return _acceso_denegado(request)
    item = get_object_or_404(ItemInventario, pk=item_id)
    if request.method == 'POST':
        form = ItemInventarioForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            messages.success(request, f'✅ "{item.nombre}" actualizado.')
            return redirect('inventario:catalogo')
        messages.error(request, '❌ Revisa los datos del formulario.')
    else:
        form = ItemInventarioForm(instance=item)
    return render(request, 'inventario/editar_item.html', {'form': form, 'item': item})


@login_required
def eliminar_item(request, item_id):
    if not puede_gestionar_catalogo(request.user):
        return _acceso_denegado(request)
    item = get_object_or_404(ItemInventario, pk=item_id)
    if request.method == 'POST':
        try:
            item.delete()
            messages.success(request, f'🗑️ "{item.nombre}" eliminado.')
        except ProtectedError:
            item.activo = False
            item.save(update_fields=['activo'])
            messages.warning(request, f'⚠️ "{item.nombre}" tiene stock/movimientos asociados: se desactivó en vez de eliminarlo.')
    return redirect('inventario:catalogo')


# ==================== TRANSFERENCIAS ====================

@login_required
def solicitar_transferencia(request, titular_id=None):
    if not es_staff_del_centro(request.user):
        return _acceso_denegado(request)

    opciones = [(t, label) for t, label in _titulares_donde_puedo_agregar(request.user)]
    choices = [(str(t.id), label) for t, label in opciones]
    titulares_por_id = {t.id: t for t, _ in opciones}

    if not choices:
        messages.error(request, '❌ No tienes ningún inventario disponible para transferir.')
        return redirect('inventario:general')

    if request.method == 'POST':
        form = SolicitarTransferenciaForm(request.POST, origen_choices=choices, usuario_actual=request.user)
        if form.is_valid():
            origen = titulares_por_id.get(int(form.cleaned_data['origen']))
            if not origen or not puede_solicitar_transferencia(request.user, origen):
                return _acceso_denegado(request, '❌ No puedes transferir desde ese inventario.')

            stock_actual = StockInventario.objects.filter(titular=origen, item=form.cleaned_data['item']).first()
            disponible = stock_actual.cantidad if stock_actual else 0
            if form.cleaned_data['cantidad'] > disponible:
                form.add_error('cantidad', f'Solo hay {disponible} disponibles en ese inventario.')
            else:
                destino = None
                if form.cleaned_data['destino_tipo'] == 'usuario':
                    destino = TitularInventario.de_usuario(form.cleaned_data['destino_usuario'])

                TransferenciaInventario.objects.create(
                    origen=origen, destino=destino, item=form.cleaned_data['item'],
                    cantidad=form.cleaned_data['cantidad'], motivo=form.cleaned_data['motivo'],
                    notas_solicitante=form.cleaned_data['notas_solicitante'], solicitado_por=request.user,
                )
                messages.success(request, '✅ Solicitud de transferencia enviada. Un administrador debe aprobarla.')
                return redirect('inventario:transferencias')
        messages.error(request, '❌ Revisa los datos del formulario.')
    else:
        inicial = {}
        if titular_id and int(titular_id) in titulares_por_id:
            inicial['origen'] = str(titular_id)
        form = SolicitarTransferenciaForm(origen_choices=choices, usuario_actual=request.user, initial=inicial)

    return render(request, 'inventario/solicitar_transferencia.html', {'form': form})


@login_required
def lista_transferencias(request):
    if not es_staff_del_centro(request.user):
        return _acceso_denegado(request)

    qs = TransferenciaInventario.objects.select_related('origen', 'destino', 'item', 'solicitado_por', 'resuelto_por')
    if not es_admin(request.user):
        qs = qs.filter(solicitado_por=request.user)

    estado = request.GET.get('estado')
    if estado:
        qs = qs.filter(estado=estado)

    return render(request, 'inventario/transferencias.html', {
        'transferencias': qs,
        'estado_filtro': estado,
        'puede_resolver': puede_resolver_transferencias(request.user),
    })


@login_required
def resolver_transferencia(request, transferencia_id):
    if not puede_resolver_transferencias(request.user):
        return _acceso_denegado(request, '❌ Solo un administrador puede aprobar o rechazar transferencias.')

    transferencia = get_object_or_404(TransferenciaInventario, pk=transferencia_id)
    if transferencia.estado != 'pendiente':
        messages.info(request, 'Esta transferencia ya fue resuelta.')
        return redirect('inventario:transferencias')

    if request.method == 'POST':
        form = ResolverTransferenciaForm(request.POST)
        if form.is_valid():
            try:
                if form.cleaned_data['accion'] == 'aprobar':
                    transferencia.aprobar(request.user, form.cleaned_data['notas_admin'])
                    messages.success(request, '✅ Transferencia aprobada y stock actualizado.')
                else:
                    transferencia.rechazar(request.user, form.cleaned_data['notas_admin'])
                    messages.success(request, '🚫 Transferencia rechazada.')
            except ValidationError as e:
                messages.error(request, f'❌ {e.message if hasattr(e, "message") else e}')
            return redirect('inventario:transferencias')
        messages.error(request, '❌ Revisa los datos del formulario.')
    else:
        form = ResolverTransferenciaForm()

    return render(request, 'inventario/resolver_transferencia.html', {'form': form, 'transferencia': transferencia})
