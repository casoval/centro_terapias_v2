# egresos/views.py
# Vistas para la app de egresos: listado, registro, anulación, PDF y dashboard.

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.core.paginator import Paginator
from django.utils import timezone
from django.core.cache import cache

from decimal import Decimal
from datetime import date, datetime

from .models import Egreso, EgresoRecurrente, CategoriaEgreso, Proveedor, ResumenFinanciero
from .services import EgresoService, ResumenFinancieroService
from facturacion.models import MetodoPago


# ─────────────────────────────────────────────────────────────────────────────
# LISTADO DE EGRESOS
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@staff_member_required
def lista_egresos(request):
    """
    Listado paginado de egresos con filtros por fecha, categoría,
    proveedor, tipo, estado y período.
    """
    # ── Filtros ───────────────────────────────────────────────────────────────
    buscar       = request.GET.get('q', '').strip()
    tipo         = request.GET.get('tipo', '')
    categoria_id = request.GET.get('categoria', '')
    proveedor_id = request.GET.get('proveedor', '')
    estado       = request.GET.get('estado', 'activos')   # activos | anulados | todos
    fecha_desde  = request.GET.get('fecha_desde', '')
    fecha_hasta  = request.GET.get('fecha_hasta', '')
    mes          = request.GET.get('mes', '')
    anio         = request.GET.get('anio', '')

    qs = Egreso.objects.select_related(
        'categoria', 'proveedor', 'metodo_pago', 'registrado_por', 'sucursal'
    )

    # Filtro por estado de anulación
    if estado == 'activos':
        qs = qs.filter(anulado=False)
    elif estado == 'anulados':
        qs = qs.filter(anulado=True)
    # 'todos' → no filtrar

    if buscar:
        qs = qs.filter(
            Q(numero_egreso__icontains=buscar) |
            Q(concepto__icontains=buscar) |
            Q(proveedor__nombre__icontains=buscar) |
            Q(numero_documento_proveedor__icontains=buscar)
        )
    if tipo:
        qs = qs.filter(categoria__tipo=tipo)
    if categoria_id:
        qs = qs.filter(categoria_id=categoria_id)
    if proveedor_id:
        qs = qs.filter(proveedor_id=proveedor_id)
    if fecha_desde:
        try:
            qs = qs.filter(fecha__gte=datetime.strptime(fecha_desde, '%Y-%m-%d').date())
        except ValueError:
            pass
    if fecha_hasta:
        try:
            qs = qs.filter(fecha__lte=datetime.strptime(fecha_hasta, '%Y-%m-%d').date())
        except ValueError:
            pass
    if mes:
        qs = qs.filter(periodo_mes=int(mes))
    if anio:
        qs = qs.filter(periodo_anio=int(anio))

    # ── Totales del filtro actual ─────────────────────────────────────────────
    totales = qs.filter(anulado=False).aggregate(
        total=Coalesce(Sum('monto'), Decimal('0'))
    )
    total_filtrado = totales['total']

    # ── Paginación ────────────────────────────────────────────────────────────
    paginator   = Paginator(qs, 50)
    page_number = request.GET.get('page', 1)
    page_obj    = paginator.get_page(page_number)

    # ── Datos para los selectores de filtro ───────────────────────────────────
    categorias = CategoriaEgreso.objects.filter(activo=True)
    proveedores = Proveedor.objects.filter(activo=True)
    tipos       = CategoriaEgreso.TIPO_CHOICES

    context = {
        'page_obj':      page_obj,
        'total_filtrado': total_filtrado,
        'categorias':    categorias,
        'proveedores':   proveedores,
        'tipos':         tipos,
        # Filtros activos (para mantener estado del form)
        'filtros': {
            'q':          buscar,
            'tipo':       tipo,
            'categoria':  categoria_id,
            'proveedor':  proveedor_id,
            'estado':     estado,
            'fecha_desde':fecha_desde,
            'fecha_hasta':fecha_hasta,
            'mes':        mes,
            'anio':       anio,
        },
        'anios_disponibles': _get_anios_disponibles(),
    }
    return render(request, 'egresos/lista_egresos.html', context)


# ─────────────────────────────────────────────────────────────────────────────
# REGISTRO DE EGRESO
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@staff_member_required
def registrar_egreso(request):
    """
    Vista para registrar un nuevo egreso.
    GET:  muestra el formulario.
    POST: procesa y redirige al listado con mensaje de confirmación.
    """
    if request.method == 'POST':
        try:
            # Recoger datos del formulario
            categoria_id  = request.POST.get('categoria')
            proveedor_id  = request.POST.get('proveedor') or None
            fecha_str     = request.POST.get('fecha')
            concepto      = request.POST.get('concepto', '').strip()
            monto         = request.POST.get('monto', '0')
            metodo_pago_id= request.POST.get('metodo_pago')
            periodo_mes   = request.POST.get('periodo_mes') or None
            periodo_anio  = request.POST.get('periodo_anio') or None
            num_transac   = request.POST.get('numero_transaccion', '').strip()
            num_doc_prov  = request.POST.get('numero_documento_proveedor', '').strip()
            observaciones = request.POST.get('observaciones', '').strip()
            sucursal_id   = request.POST.get('sucursal') or None
            sesiones_ids  = request.POST.getlist('sesiones_cubiertas')

            # Validaciones básicas
            if not all([categoria_id, fecha_str, concepto, monto, metodo_pago_id]):
                messages.error(request, '❌ Faltan campos obligatorios.')
                return _render_form_egreso(request)

            fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()

            egreso = EgresoService.registrar_egreso(
                user=request.user,
                categoria_id=int(categoria_id),
                fecha=fecha,
                concepto=concepto,
                monto=Decimal(monto),
                metodo_pago_id=int(metodo_pago_id),
                proveedor_id=int(proveedor_id) if proveedor_id else None,
                periodo_mes=int(periodo_mes) if periodo_mes else None,
                periodo_anio=int(periodo_anio) if periodo_anio else None,
                numero_transaccion=num_transac,
                numero_documento_proveedor=num_doc_prov,
                observaciones=observaciones,
                sucursal_id=int(sucursal_id) if sucursal_id else None,
                sesiones_ids=[int(s) for s in sesiones_ids] if sesiones_ids else None,
            )

            messages.success(
                request,
                f'✅ Egreso {egreso.numero_egreso} registrado correctamente — '
                f'Bs. {egreso.monto:,.0f}'
            )
            return redirect('egresos:lista_egresos')

        except Exception as e:
            messages.error(request, f'❌ Error al registrar egreso: {str(e)}')
            return _render_form_egreso(request)

    return _render_form_egreso(request)


def _render_form_egreso(request):
    """Helper: renderiza el formulario de registro con los datos necesarios."""
    context = {
        'categorias':   CategoriaEgreso.objects.filter(activo=True).order_by('tipo', 'nombre'),
        'proveedores':  Proveedor.objects.filter(activo=True).order_by('nombre'),
        'metodos_pago': MetodoPago.objects.filter(activo=True),
        'hoy':          date.today(),
        'anio_actual':  date.today().year,
        'mes_actual':   date.today().month,
    }
    return render(request, 'egresos/registrar_egreso.html', context)


# ─────────────────────────────────────────────────────────────────────────────
# DETALLE DE EGRESO
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@staff_member_required
def detalle_egreso(request, egreso_id):
    """Vista de detalle de un egreso con todas sus relaciones."""
    egreso = get_object_or_404(
        Egreso.objects.select_related(
            'categoria', 'proveedor', 'metodo_pago',
            'registrado_por', 'anulado_por', 'sucursal'
        ).prefetch_related('sesiones_cubiertas__paciente'),
        id=egreso_id
    )
    return render(request, 'egresos/detalle_egreso.html', {'egreso': egreso})


# ─────────────────────────────────────────────────────────────────────────────
# ANULACIÓN DE EGRESO
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@staff_member_required
def anular_egreso(request, egreso_id):
    """
    Anula un egreso.
    GET:  muestra confirmación.
    POST: ejecuta la anulación.
    """
    egreso = get_object_or_404(Egreso, id=egreso_id)

    if egreso.anulado:
        messages.warning(
            request,
            f'⚠️ El egreso {egreso.numero_egreso} ya está anulado.'
        )
        return redirect('egresos:detalle_egreso', egreso_id=egreso.id)

    if request.method == 'POST':
        motivo = request.POST.get('motivo', '').strip()
        if not motivo:
            messages.error(request, '❌ Debe especificar el motivo de anulación.')
            return render(request, 'egresos/confirmar_anulacion.html', {'egreso': egreso})

        try:
            EgresoService.anular_egreso(
                user=request.user,
                egreso_id=egreso_id,
                motivo=motivo,
            )
            messages.success(
                request,
                f'✅ Egreso {egreso.numero_egreso} anulado correctamente.'
            )
            return redirect('egresos:lista_egresos')

        except Exception as e:
            messages.error(request, f'❌ Error al anular: {str(e)}')

    return render(request, 'egresos/confirmar_anulacion.html', {'egreso': egreso})


# ─────────────────────────────────────────────────────────────────────────────
# PDF DEL RECIBO DE EGRESO
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@staff_member_required
def generar_egreso_pdf(request, egreso_id):
    """
    Genera el comprobante PDF del egreso (recibo EGR-XXXX).
    Usa cache para no regenerar si no ha cambiado.
    """
    egreso = get_object_or_404(
        Egreso.objects.select_related(
            'categoria', 'proveedor', 'metodo_pago',
            'registrado_por', 'sucursal'
        ),
        id=egreso_id
    )

    try:
        cache_key = f'pdf_egreso_{egreso.numero_egreso}'
        pdf_cached = cache.get(cache_key)

        if pdf_cached and not egreso.anulado:
            response = HttpResponse(pdf_cached, content_type='application/pdf')
            response['Content-Disposition'] = (
                f'inline; filename="egreso_{egreso.numero_egreso}.pdf"'
            )
            return response

        from . import pdf_generator
        pdf_data = pdf_generator.generar_egreso_pdf(egreso)

        if not egreso.anulado:
            cache.set(cache_key, pdf_data, 3600)

        response = HttpResponse(pdf_data, content_type='application/pdf')
        response['Content-Disposition'] = (
            f'inline; filename="egreso_{egreso.numero_egreso}.pdf"'
        )
        return response

    except Exception as e:
        import logging
        logging.getLogger(__name__).error(
            f'Error generando PDF egreso {egreso_id}: {e}', exc_info=True
        )
        messages.error(request, f'❌ Error al generar PDF: {str(e)}')
        return redirect('egresos:detalle_egreso', egreso_id=egreso_id)


# ─────────────────────────────────────────────────────────────────────────────
# DASHBOARD FINANCIERO
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@staff_member_required
def dashboard_financiero(request):
    """
    Dashboard del estado financiero del centro.
    Muestra el ResumenFinanciero del mes actual y permite consultar histórico.
    """
    hoy      = date.today()
    mes      = int(request.GET.get('mes',  hoy.month))
    anio     = int(request.GET.get('anio', hoy.year))

    # Asegurar que existe el resumen del mes solicitado
    ResumenFinancieroService.recalcular_mes(mes, anio)

    try:
        resumen = ResumenFinanciero.objects.get(mes=mes, anio=anio, sucursal=None)
    except ResumenFinanciero.DoesNotExist:
        resumen = None

    # Últimos 12 meses para el gráfico histórico
    historico = ResumenFinanciero.objects.filter(
        sucursal=None
    ).order_by('-anio', '-mes')[:12]

    # Top 5 proveedores del mes (por monto)
    top_proveedores = (
        Egreso.objects
        .filter(periodo_mes=mes, periodo_anio=anio, anulado=False)
        .exclude(proveedor__isnull=True)
        .values('proveedor__nombre')
        .annotate(total=Sum('monto'))
        .order_by('-total')[:5]
    )

    # Egresos del mes por tipo (para la torta)
    egresos_por_tipo = (
        Egreso.objects
        .filter(periodo_mes=mes, periodo_anio=anio, anulado=False)
        .values('categoria__tipo', 'categoria__nombre')
        .annotate(total=Sum('monto'))
        .order_by('-total')
    )

    # Últimos 10 egresos del mes
    ultimos_egresos = Egreso.objects.filter(
        periodo_mes=mes,
        periodo_anio=anio,
        anulado=False
    ).select_related('categoria', 'proveedor').order_by('-fecha')[:10]

    context = {
        'resumen':          resumen,
        'historico':        list(historico),
        'top_proveedores':  list(top_proveedores),
        'egresos_por_tipo': list(egresos_por_tipo),
        'ultimos_egresos':  ultimos_egresos,
        'mes_actual':       mes,
        'anio_actual':      anio,
        'mes_display':      resumen.mes_display if resumen else f'{str(mes).zfill(2)}/{anio}',
        'anios_disponibles': _get_anios_disponibles(),
    }
    return render(request, 'egresos/dashboard_financiero.html', context)


# ─────────────────────────────────────────────────────────────────────────────
# API JSON — para AJAX del dashboard
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@staff_member_required
def api_resumen_mes(request):
    """
    Retorna el ResumenFinanciero de un mes/año en JSON.
    Usado por el dashboard para actualizar sin recargar la página.
    """
    mes  = int(request.GET.get('mes',  date.today().month))
    anio = int(request.GET.get('anio', date.today().year))

    ResumenFinancieroService.recalcular_mes(mes, anio)

    try:
        r = ResumenFinanciero.objects.get(mes=mes, anio=anio, sucursal=None)
        data = {
            'mes':                       r.mes,
            'anio':                      r.anio,
            'periodo':                   r.mes_display,
            'ingresos_brutos':           float(r.ingresos_brutos),
            'total_devoluciones':        float(r.total_devoluciones),
            'ingresos_netos':            float(r.ingresos_netos),
            'egresos_arriendo':          float(r.egresos_arriendo),
            'egresos_servicios_basicos': float(r.egresos_servicios_basicos),
            'egresos_personal':          float(r.egresos_personal),
            'egresos_honorarios':        float(r.egresos_honorarios),
            'egresos_equipamiento':      float(r.egresos_equipamiento),
            'egresos_mantenimiento':     float(r.egresos_mantenimiento),
            'egresos_marketing':         float(r.egresos_marketing),
            'egresos_impuestos':         float(r.egresos_impuestos),
            'egresos_seguros':           float(r.egresos_seguros),
            'egresos_capacitacion':      float(r.egresos_capacitacion),
            'egresos_otros':             float(r.egresos_otros),
            'total_egresos':             float(r.total_egresos),
            'resultado_neto':            float(r.resultado_neto),
            'margen_porcentaje':         float(r.margen_porcentaje),
            'es_rentable':               r.es_rentable,
        }
    except ResumenFinanciero.DoesNotExist:
        data = {'error': 'Sin datos para este período'}

    return JsonResponse(data)


@login_required
@staff_member_required
def api_egresos_mes(request):
    """
    Retorna los egresos de un mes en JSON para tablas dinámicas.
    """
    mes  = int(request.GET.get('mes',  date.today().month))
    anio = int(request.GET.get('anio', date.today().year))
    tipo = request.GET.get('tipo', '')

    qs = Egreso.objects.filter(
        periodo_mes=mes,
        periodo_anio=anio,
        anulado=False,
    ).select_related('categoria', 'proveedor', 'metodo_pago')

    if tipo:
        qs = qs.filter(categoria__tipo=tipo)

    data = [
        {
            'id':                          e.id,
            'numero_egreso':               e.numero_egreso,
            'fecha':                       e.fecha.isoformat(),
            'categoria':                   e.categoria.nombre,
            'tipo':                        e.categoria.tipo,
            'proveedor':                   str(e.proveedor) if e.proveedor else '—',
            'concepto':                    e.concepto,
            'monto':                       float(e.monto),
            'metodo_pago':                 str(e.metodo_pago),
            'numero_documento_proveedor':  e.numero_documento_proveedor,
        }
        for e in qs
    ]

    return JsonResponse({'egresos': data, 'total': sum(e['monto'] for e in data)})


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS INTERNOS
# ─────────────────────────────────────────────────────────────────────────────

def _get_anios_disponibles():
    """
    Retorna los años disponibles en egresos y pagos para los selectores de filtro.
    """
    anios_egresos = (
        Egreso.objects
        .values_list('periodo_anio', flat=True)
        .distinct()
        .order_by('-periodo_anio')
    )
    anio_actual = date.today().year
    anios = sorted(set(list(anios_egresos) + [anio_actual]), reverse=True)
    return anios


# ─────────────────────────────────────────────────────────────────────────────
# CATEGORÍAS DE EGRESO
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@staff_member_required
def lista_categorias(request):
    categorias = CategoriaEgreso.objects.all()
    return render(request, 'egresos/lista_categorias.html', {'categorias': categorias})


@login_required
@staff_member_required
def crear_categoria(request):
    if request.method == 'POST':
        nombre     = request.POST.get('nombre', '').strip()
        tipo       = request.POST.get('tipo', '').strip()
        descripcion = request.POST.get('descripcion', '').strip()
        es_honorario = request.POST.get('es_honorario_profesional') == '1'
        activo       = request.POST.get('activo') == '1'

        if not nombre or not tipo:
            messages.error(request, 'El nombre y el tipo son obligatorios.')
        elif CategoriaEgreso.objects.filter(nombre=nombre).exists():
            messages.error(request, f'Ya existe una categoría con el nombre "{nombre}".')
        else:
            CategoriaEgreso.objects.create(
                nombre=nombre,
                tipo=tipo,
                descripcion=descripcion,
                es_honorario_profesional=es_honorario,
                activo=activo,
            )
            messages.success(request, f'✅ Categoría "{nombre}" creada correctamente.')
            return redirect('egresos:lista_categorias')

    return render(request, 'egresos/categoria_form.html')


@login_required
@staff_member_required
def editar_categoria(request, categoria_id):
    categoria = get_object_or_404(CategoriaEgreso, id=categoria_id)

    if request.method == 'POST':
        nombre      = request.POST.get('nombre', '').strip()
        tipo        = request.POST.get('tipo', '').strip()
        descripcion = request.POST.get('descripcion', '').strip()
        es_honorario = request.POST.get('es_honorario_profesional') == '1'
        activo       = request.POST.get('activo') == '1'

        if not nombre or not tipo:
            messages.error(request, 'El nombre y el tipo son obligatorios.')
        elif CategoriaEgreso.objects.filter(nombre=nombre).exclude(id=categoria_id).exists():
            messages.error(request, f'Ya existe otra categoría con el nombre "{nombre}".')
        else:
            categoria.nombre     = nombre
            categoria.tipo       = tipo
            categoria.descripcion = descripcion
            categoria.es_honorario_profesional = es_honorario
            categoria.activo     = activo
            categoria.save()
            messages.success(request, f'✅ Categoría "{nombre}" actualizada.')
            return redirect('egresos:lista_categorias')

    return render(request, 'egresos/categoria_form.html', {'categoria': categoria})


# ─────────────────────────────────────────────────────────────────────────────
# PROVEEDORES
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@staff_member_required
def lista_proveedores(request):
    from profesionales.models import Profesional
    filtro_tipo   = request.GET.get('tipo', '')
    filtro_activo = request.GET.get('activo', '1')

    qs = Proveedor.objects.select_related('profesional')

    if filtro_tipo:
        qs = qs.filter(tipo=filtro_tipo)
    if filtro_activo == '0':
        qs = qs.filter(activo=False)
    else:
        qs = qs.filter(activo=True)

    return render(request, 'egresos/lista_proveedores.html', {
        'proveedores':   qs,
        'total':         qs.count(),
        'filtro_tipo':   filtro_tipo,
        'filtro_activo': filtro_activo,
    })


@login_required
@staff_member_required
def crear_proveedor(request):
    from profesionales.models import Profesional
    profesionales = Profesional.objects.filter(activo=True).order_by('nombre')

    if request.method == 'POST':
        nombre         = request.POST.get('nombre', '').strip()
        tipo           = request.POST.get('tipo', '').strip()
        nit_ci         = request.POST.get('nit_ci', '').strip()
        telefono       = request.POST.get('telefono', '').strip()
        email          = request.POST.get('email', '').strip()
        banco          = request.POST.get('banco', '').strip()
        numero_cuenta  = request.POST.get('numero_cuenta', '').strip()
        profesional_id = request.POST.get('profesional', '')
        observaciones  = request.POST.get('observaciones', '').strip()
        activo         = request.POST.get('activo') == '1'

        if not nombre or not tipo:
            messages.error(request, 'El nombre y el tipo son obligatorios.')
        else:
            profesional = None
            if profesional_id:
                try:
                    profesional = Profesional.objects.get(id=profesional_id)
                except Profesional.DoesNotExist:
                    pass

            Proveedor.objects.create(
                nombre=nombre, tipo=tipo, nit_ci=nit_ci,
                telefono=telefono, email=email, banco=banco,
                numero_cuenta=numero_cuenta, profesional=profesional,
                observaciones=observaciones, activo=activo,
            )
            messages.success(request, f'✅ Proveedor "{nombre}" creado correctamente.')
            return redirect('egresos:lista_proveedores')

    return render(request, 'egresos/proveedor_form.html', {'profesionales': profesionales})


@login_required
@staff_member_required
def editar_proveedor(request, proveedor_id):
    from profesionales.models import Profesional
    proveedor     = get_object_or_404(Proveedor, id=proveedor_id)
    profesionales = Profesional.objects.filter(activo=True).order_by('nombre')

    if request.method == 'POST':
        nombre         = request.POST.get('nombre', '').strip()
        tipo           = request.POST.get('tipo', '').strip()
        nit_ci         = request.POST.get('nit_ci', '').strip()
        telefono       = request.POST.get('telefono', '').strip()
        email          = request.POST.get('email', '').strip()
        banco          = request.POST.get('banco', '').strip()
        numero_cuenta  = request.POST.get('numero_cuenta', '').strip()
        profesional_id = request.POST.get('profesional', '')
        observaciones  = request.POST.get('observaciones', '').strip()
        activo         = request.POST.get('activo') == '1'

        if not nombre or not tipo:
            messages.error(request, 'El nombre y el tipo son obligatorios.')
        else:
            profesional = None
            if profesional_id:
                try:
                    profesional = Profesional.objects.get(id=profesional_id)
                except Profesional.DoesNotExist:
                    pass

            proveedor.nombre        = nombre
            proveedor.tipo          = tipo
            proveedor.nit_ci        = nit_ci
            proveedor.telefono      = telefono
            proveedor.email         = email
            proveedor.banco         = banco
            proveedor.numero_cuenta = numero_cuenta
            proveedor.profesional   = profesional
            proveedor.observaciones = observaciones
            proveedor.activo        = activo
            proveedor.save()
            messages.success(request, f'✅ Proveedor "{nombre}" actualizado.')
            return redirect('egresos:lista_proveedores')

    return render(request, 'egresos/proveedor_form.html', {
        'proveedor':     proveedor,
        'profesionales': profesionales,
    })