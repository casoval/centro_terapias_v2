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
    proveedor, tipo, estado, período y sucursal.
    """
    from servicios.models import Sucursal

    # ── Filtros ───────────────────────────────────────────────────────────────
    buscar       = request.GET.get('q', '').strip()
    tipo         = request.GET.get('tipo', '')
    categoria_id = request.GET.get('categoria', '')
    proveedor_id = request.GET.get('proveedor', '')
    sucursal_id  = request.GET.get('sucursal', '')
    estado       = request.GET.get('estado', 'activos')
    fecha_desde  = request.GET.get('fecha_desde', '')
    fecha_hasta  = request.GET.get('fecha_hasta', '')
    mes          = request.GET.get('mes', '')
    anio         = request.GET.get('anio', '')

    qs = Egreso.objects.select_related(
        'categoria', 'proveedor', 'metodo_pago', 'registrado_por', 'sucursal'
    )

    if estado == 'activos':
        qs = qs.filter(anulado=False)
    elif estado == 'anulados':
        qs = qs.filter(anulado=True)

    if buscar:
        qs = qs.filter(
            Q(numero_egreso__icontains=buscar) |
            Q(concepto__icontains=buscar) |
            Q(proveedor__nombre__icontains=buscar) |
            Q(numero_documento_proveedor__icontains=buscar) |
            Q(registrado_por__first_name__icontains=buscar) |
            Q(registrado_por__last_name__icontains=buscar)
        )
    if tipo:
        qs = qs.filter(categoria__tipo=tipo)
    if categoria_id:
        qs = qs.filter(categoria_id=categoria_id)
    if proveedor_id:
        qs = qs.filter(proveedor_id=proveedor_id)
    if sucursal_id == 'global':
        qs = qs.filter(sucursal__isnull=True)
    elif sucursal_id:
        qs = qs.filter(sucursal_id=sucursal_id)
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
    total_filtrado = qs.filter(anulado=False).aggregate(
        total=Coalesce(Sum('monto'), Decimal('0'))
    )['total']

    # ── Paginación ────────────────────────────────────────────────────────────
    paginator   = Paginator(qs.order_by('-fecha', '-fecha_registro'), 50)
    page_number = request.GET.get('page', 1)
    page_obj    = paginator.get_page(page_number)

    context = {
        'page_obj':          page_obj,
        'total_filtrado':    total_filtrado,
        'categorias':        CategoriaEgreso.objects.filter(activo=True),
        'proveedores':       Proveedor.objects.filter(activo=True),
        'sucursales':        Sucursal.objects.filter(activa=True).order_by('nombre'),
        'tipos':             CategoriaEgreso.TIPO_CHOICES,
        'anios_disponibles': _get_anios_disponibles(),
        'filtros': {
            'q':          buscar,
            'tipo':       tipo,
            'categoria':  categoria_id,
            'proveedor':  proveedor_id,
            'sucursal':   sucursal_id,
            'estado':     estado,
            'fecha_desde': fecha_desde,
            'fecha_hasta': fecha_hasta,
            'mes':        mes,
            'anio':       anio,
        },
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
    from servicios.models import Sucursal
    context = {
        'categorias':   CategoriaEgreso.objects.filter(activo=True).order_by('tipo', 'nombre'),
        'proveedores':  Proveedor.objects.filter(activo=True).order_by('nombre'),
        'metodos_pago': MetodoPago.objects.filter(activo=True).exclude(nombre__in=['Uso de Crédito', 'Crédito/Saldo a Favor', 'Credito/Saldo a Favor']).exclude(nombre__icontains='crédito').exclude(nombre__icontains='saldo'),
        'sucursales':   Sucursal.objects.filter(activa=True).order_by('nombre'),
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
    Dashboard financiero del centro.
    Soporta filtro por sucursal: global (sucursal=None) o por sede específica.
    """
    from servicios.models import Sucursal

    hoy        = date.today()
    mes        = int(request.GET.get('mes',  hoy.month))
    anio       = int(request.GET.get('anio', hoy.year))
    sucursal_id = request.GET.get('sucursal', '')

    # Resolver sucursal
    sucursal_obj = None
    if sucursal_id:
        try:
            sucursal_obj = Sucursal.objects.get(id=sucursal_id, activa=True)
        except Sucursal.DoesNotExist:
            sucursal_id = ''

    # Recalcular snapshot del mes solicitado (global + sucursal si aplica)
    ResumenFinancieroService.recalcular_mes(mes, anio)
    if sucursal_obj:
        ResumenFinancieroService.recalcular_mes(mes, anio, sucursal=sucursal_obj)

    try:
        resumen = ResumenFinanciero.objects.get(
            mes=mes, anio=anio, sucursal=sucursal_obj
        )
    except ResumenFinanciero.DoesNotExist:
        resumen = None

    # Histórico 12 meses (mismo filtro de sucursal)
    historico = ResumenFinanciero.objects.filter(
        sucursal=sucursal_obj
    ).order_by('-anio', '-mes')[:12]

    # Top 5 proveedores del mes (filtrado por sucursal si aplica)
    top_qs = (
        Egreso.objects
        .filter(periodo_mes=mes, periodo_anio=anio, anulado=False)
        .exclude(proveedor__isnull=True)
    )
    if sucursal_obj:
        top_qs = top_qs.filter(sucursal=sucursal_obj)
    top_proveedores = (
        top_qs.values('proveedor__nombre')
        .annotate(total=Sum('monto'))
        .order_by('-total')[:5]
    )

    # Últimos 10 egresos del mes
    ult_qs = Egreso.objects.filter(
        periodo_mes=mes, periodo_anio=anio, anulado=False
    ).select_related('categoria', 'proveedor')
    if sucursal_obj:
        # Para sucursal: egresos de esa sucursal + honorarios de esa sucursal
        from egresos.models import PagoHonorario
        honorarios_ids = PagoHonorario.objects.filter(
            sesiones__sucursal_id=sucursal_obj.id,
            egreso__periodo_mes=mes,
            egreso__periodo_anio=anio,
            egreso__anulado=False,
        ).values_list('egreso_id', flat=True)
        ult_qs = ult_qs.filter(
            Q(sucursal=sucursal_obj) | Q(id__in=honorarios_ids)
        )
    ultimos_egresos = ult_qs.order_by('-fecha')[:10]

    context = {
        'resumen':           resumen,
        'historico':         list(historico),
        'top_proveedores':   list(top_proveedores),
        'ultimos_egresos':   ultimos_egresos,
        'mes_actual':        mes,
        'anio_actual':       anio,
        'mes_display':       resumen.mes_display if resumen else f'{str(mes).zfill(2)}/{anio}',
        'anios_disponibles': _get_anios_disponibles(),
        'sucursales':        Sucursal.objects.filter(activa=True).order_by('nombre'),
        'sucursal_obj':      sucursal_obj,
        'sucursal_id':       sucursal_id,
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
    from itertools import groupby
    categorias = CategoriaEgreso.objects.all().order_by('tipo', 'nombre')
    # Agrupar por tipo en Python — evita usar {% regroup %} en el template
    grupos = [
        (tipo_display, list(items))
        for tipo_display, items in groupby(categorias, key=lambda c: c.get_tipo_display())
    ]
    return render(request, 'egresos/lista_categorias.html', {
        'categorias': categorias,
        'grupos': grupos,
    })


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


# ─────────────────────────────────────────────────────────────────────────────
# LIQUIDACIÓN DE HONORARIOS
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@staff_member_required
def liquidar_honorarios(request):
    """
    GET:  Muestra todos los profesionales externos con sesiones sin pagar.
    POST: Registra el egreso EGR-XXXX para las sesiones seleccionadas.
    """
    from servicios.models import ComisionSesion
    from profesionales.models import Profesional
    from decimal import Decimal
    from django.db.models import Sum

    if request.method == 'POST':
        profesional_id = request.POST.get('profesional_id')
        proveedor_id   = request.POST.get('proveedor_id')
        sesiones_ids   = request.POST.getlist('sesiones_ids')
        metodo_pago_id = request.POST.get('metodo_pago')
        monto_pago     = request.POST.get('monto_pago', '0').strip()
        concepto       = request.POST.get('concepto', '').strip()
        fecha_pago_str = request.POST.get('fecha_pago', '')
        observaciones  = request.POST.get('observaciones', '').strip()

        # Validaciones
        if not sesiones_ids:
            messages.error(request, '❌ Debes seleccionar al menos una sesión.')
            return redirect('egresos:liquidar_honorarios')
        if not metodo_pago_id:
            messages.error(request, '❌ Debes seleccionar un método de pago.')
            return redirect('egresos:liquidar_honorarios')
        if not proveedor_id:
            messages.error(request, '❌ El profesional no tiene un proveedor vinculado. Créalo primero.')
            return redirect('egresos:liquidar_honorarios')

        try:
            fecha_pago = datetime.strptime(fecha_pago_str, '%Y-%m-%d').date()
            monto      = Decimal(monto_pago)
            if monto <= 0:
                raise ValueError('Monto inválido')
        except (ValueError, Exception):
            messages.error(request, '❌ Fecha o monto inválidos.')
            return redirect('egresos:liquidar_honorarios')

        # Obtener la categoría de honorarios automáticamente
        categoria = CategoriaEgreso.objects.filter(
            es_honorario_profesional=True, activo=True
        ).first()
        if not categoria:
            messages.error(
                request,
                '❌ No existe una categoría activa de honorarios. '
                'Créala en Egresos → Categorías con "Es pago de honorarios" activado.'
            )
            return redirect('egresos:liquidar_honorarios')

        try:
            egreso = EgresoService.registrar_egreso(
                user=request.user,
                categoria_id=categoria.id,
                fecha=fecha_pago,
                concepto=concepto or f'Honorarios profesional externo',
                monto=monto,
                metodo_pago_id=int(metodo_pago_id),
                proveedor_id=int(proveedor_id),
                sesiones_ids=[int(s) for s in sesiones_ids],
                observaciones=observaciones,
            )
            profesional = Profesional.objects.get(id=profesional_id)
            messages.success(
                request,
                f'✅ {egreso.numero_egreso} registrado — '
                f'Bs. {egreso.monto:,.0f} a {profesional.nombre} {profesional.apellido} '
                f'por {len(sesiones_ids)} sesión(es).'
            )
        except Exception as e:
            messages.error(request, f'❌ Error al registrar honorario: {str(e)}')

        return redirect('egresos:liquidar_honorarios')

    # ── GET: construir los bloques por profesional ────────────────────────────

    # Sesiones de servicios externos que tienen ComisionSesion
    # y que NO están en ningún Egreso no anulado
    sesiones_pagadas_ids = (
        Egreso.objects
        .filter(anulado=False)
        .values_list('sesiones_cubiertas__id', flat=True)
    )

    comisiones_pendientes = (
        ComisionSesion.objects
        .filter(
            sesion__estado__in=['realizada', 'realizada_retraso'],
        )
        .exclude(sesion__id__in=sesiones_pagadas_ids)
        .select_related(
            'sesion__profesional',
            'sesion__paciente',
            'sesion__servicio',
        )
        .order_by('sesion__profesional', 'sesion__fecha')
    )

    # Agrupar por profesional en Python
    from itertools import groupby
    bloques = []
    deuda_total = Decimal('0')
    total_sesiones_pendientes = 0

    for profesional, items in groupby(
        comisiones_pendientes,
        key=lambda c: c.sesion.profesional
    ):
        sesiones_bloque = [
            {'sesion': c.sesion, 'comision': c}
            for c in items
        ]
        total_bloque = sum(
            s['comision'].monto_profesional for s in sesiones_bloque
        )

        # Buscar proveedor vinculado
        proveedor = None
        try:
            proveedor = profesional.proveedor_egreso
        except Exception:
            pass

        bloques.append({
            'profesional':     profesional,
            'proveedor':       proveedor,
            'sesiones':        sesiones_bloque,
            'total_pendiente': total_bloque,
        })
        deuda_total += total_bloque
        total_sesiones_pendientes += len(sesiones_bloque)

    # Historial últimos 20 egresos de honorarios
    historial = (
        Egreso.objects
        .filter(
            categoria__es_honorario_profesional=True,
            anulado=False,
        )
        .select_related('proveedor', 'categoria')
        .prefetch_related('sesiones_cubiertas')
        .order_by('-fecha', '-fecha_registro')[:20]
    )

    return render(request, 'egresos/liquidar_honorarios.html', {
        'bloques':                  bloques,
        'deuda_total':              deuda_total,
        'total_sesiones_pendientes': total_sesiones_pendientes,
        'profesionales_con_deuda':  len(bloques),
        'metodos_pago':             MetodoPago.objects.filter(activo=True).exclude(nombre__in=['Uso de Crédito', 'Crédito/Saldo a Favor', 'Credito/Saldo a Favor']).exclude(nombre__icontains='crédito').exclude(nombre__icontains='saldo'),
        'historial':                historial,
        'hoy':                      date.today(),
    })


# ─────────────────────────────────────────────────────────────────────────────
# LIQUIDACIÓN DE HONORARIOS — por sesión con saldo
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@staff_member_required
def liquidar_honorarios(request):
    """
    GET:  Muestra profesionales externos con sesiones pendientes de pago.
          Cada sesión muestra su deuda (monto_profesional de ComisionSesion).
    POST: Registra PagoHonorario + Egreso EGR-XXXX.
          El monto pagado puede ser menor a la deuda.
          Si saldado=True, las sesiones se dan por cerradas aunque quede diferencia.
    """
    from servicios.models import ComisionSesion
    from profesionales.models import Profesional
    from .models import PagoHonorario
    from decimal import Decimal
    from itertools import groupby

    if request.method == 'POST':
        return _procesar_pago_honorario(request)

    # ── GET: construir bloques por profesional + sucursal ────────────────────

    # Sesiones ya cerradas — SOLO si el egreso asociado NO está anulado.
    # Si el egreso fue anulado, las sesiones deben volver a aparecer como pendientes.
    sesiones_saldadas_ids = set(
        PagoHonorario.objects
        .filter(saldado=True, egreso__anulado=False)
        .values_list('sesiones__id', flat=True)
    )
    sesiones_pago_completo_ids = set(
        PagoHonorario.objects
        .filter(saldado=False, diferencia__lte=0, egreso__anulado=False)
        .values_list('sesiones__id', flat=True)
    )
    sesiones_cerradas_ids = sesiones_saldadas_ids | sesiones_pago_completo_ids

    comisiones_pendientes = (
        ComisionSesion.objects
        .filter(sesion__estado__in=['realizada', 'realizada_retraso'])
        .exclude(sesion__id__in=sesiones_cerradas_ids)
        .select_related(
            'sesion__profesional',
            'sesion__paciente',
            'sesion__servicio',
            'sesion__sucursal',
        )
        .order_by(
            'sesion__profesional__apellido',
            'sesion__sucursal__nombre',
            'sesion__fecha',
        )
    )

    # Agrupar por (profesional, sucursal)
    from itertools import groupby
    bloques = []
    deuda_total = Decimal('0')
    total_sesiones_pendientes = 0

    def _key(c):
        prof = c.sesion.profesional
        suc  = c.sesion.sucursal
        return (prof.id if prof else 0, suc.id if suc else 0)

    for (prof_id, suc_id), items in groupby(comisiones_pendientes, key=_key):
        sesiones_bloque = [{'sesion': c.sesion, 'comision': c} for c in items]
        if not sesiones_bloque:
            continue

        profesional = sesiones_bloque[0]['sesion'].profesional
        sucursal    = sesiones_bloque[0]['sesion'].sucursal
        total_bloque = sum(s['comision'].monto_profesional for s in sesiones_bloque)

        proveedor = None
        try:
            proveedor = profesional.proveedor_egreso
        except Exception:
            pass

        bloques.append({
            'profesional':     profesional,
            'sucursal':        sucursal,
            'proveedor':       proveedor,
            'sesiones':        sesiones_bloque,
            'total_pendiente': total_bloque,
            # key única para el form (prof+suc para evitar colisiones en el HTML)
            'form_id':         f'{prof_id}_{suc_id}',
        })
        deuda_total += total_bloque
        total_sesiones_pendientes += len(sesiones_bloque)

    # Historial últimos 15 pagos de honorarios
    historial = (
        PagoHonorario.objects
        .select_related('profesional', 'egreso', 'metodo_pago')
        .prefetch_related('sesiones')
        .order_by('-fecha', '-fecha_registro')[:15]
    )

    return render(request, 'egresos/liquidar_honorarios.html', {
        'bloques':                   bloques,
        'deuda_total':               deuda_total,
        'total_sesiones_pendientes': total_sesiones_pendientes,
        'profesionales_con_deuda':   len(bloques),
        'metodos_pago':              MetodoPago.objects.filter(activo=True).exclude(nombre__in=['Uso de Crédito', 'Crédito/Saldo a Favor', 'Credito/Saldo a Favor']).exclude(nombre__icontains='crédito').exclude(nombre__icontains='saldo'),
        'historial':                 historial,
        'hoy':                       date.today(),
    })


def _procesar_pago_honorario(request):
    """Helper POST: valida y registra el PagoHonorario + Egreso."""
    from servicios.models import ComisionSesion
    from .models import PagoHonorario
    from decimal import Decimal

    profesional_id = request.POST.get('profesional_id')
    proveedor_id   = request.POST.get('proveedor_id')
    sucursal_id    = request.POST.get('sucursal_id', '')
    sesiones_ids   = request.POST.getlist('sesiones_ids')
    metodo_pago_id = request.POST.get('metodo_pago')
    monto_pagado_str = request.POST.get('monto_pagado', '0').strip()
    saldado        = request.POST.get('saldado') == '1'
    concepto       = request.POST.get('concepto', '').strip()
    fecha_str      = request.POST.get('fecha_pago', '')
    observaciones  = request.POST.get('observaciones', '').strip()

    # Validaciones
    if not sesiones_ids:
        messages.error(request, '❌ Selecciona al menos una sesión.')
        return redirect('egresos:liquidar_honorarios')
    if not metodo_pago_id:
        messages.error(request, '❌ Selecciona un método de pago.')
        return redirect('egresos:liquidar_honorarios')
    if not proveedor_id:
        messages.error(request, '❌ El profesional no tiene proveedor vinculado.')
        return redirect('egresos:liquidar_honorarios')

    try:
        fecha       = datetime.strptime(fecha_str, '%Y-%m-%d').date()
        monto_pagado = Decimal(monto_pagado_str)
        if monto_pagado <= 0:
            raise ValueError
    except Exception:
        messages.error(request, '❌ Fecha o monto inválidos.')
        return redirect('egresos:liquidar_honorarios')

    # Calcular deuda real de las sesiones seleccionadas
    from profesionales.models import Profesional
    try:
        profesional = Profesional.objects.get(id=profesional_id)
    except Profesional.DoesNotExist:
        messages.error(request, '❌ Profesional no encontrado.')
        return redirect('egresos:liquidar_honorarios')

    comisiones = ComisionSesion.objects.filter(
        sesion__id__in=sesiones_ids
    )
    monto_deuda = comisiones.aggregate(
        total=Sum('monto_profesional')
    )['total'] or Decimal('0')

    # Obtener categoría de honorarios
    categoria = CategoriaEgreso.objects.filter(
        es_honorario_profesional=True, activo=True
    ).first()
    if not categoria:
        messages.error(
            request,
            '❌ No existe una categoría de honorarios activa. '
            'Créala en Egresos → Categorías con "Es pago de honorarios" activado.'
        )
        return redirect('egresos:liquidar_honorarios')

    nombre_prof = f"{profesional.nombre} {profesional.apellido}"
    concepto_final = concepto or f"Honorarios {nombre_prof}"

    try:
        # Crear Egreso EGR-XXXX
        egreso = EgresoService.registrar_egreso(
            user=request.user,
            categoria_id=categoria.id,
            fecha=fecha,
            concepto=concepto_final,
            monto=monto_pagado,
            metodo_pago_id=int(metodo_pago_id),
            proveedor_id=int(proveedor_id),
            observaciones=observaciones,
        )

        # Crear PagoHonorario
        pago = PagoHonorario.objects.create(
            profesional=profesional,
            monto_deuda=monto_deuda,
            monto_pagado=monto_pagado,
            saldado=saldado,
            fecha=fecha,
            metodo_pago_id=int(metodo_pago_id),
            observaciones=observaciones,
            egreso=egreso,
            registrado_por=request.user,
        )
        pago.sesiones.set([int(s) for s in sesiones_ids])

        # Recalcular resumen de la sucursal si aplica
        if sucursal_id:
            from servicios.models import Sucursal
            try:
                suc_obj = Sucursal.objects.get(id=sucursal_id)
                ResumenFinancieroService.recalcular_mes(
                    fecha.month, fecha.year, sucursal=suc_obj
                )
            except Exception:
                pass

        n_sesiones = len(sesiones_ids)
        diferencia = monto_deuda - monto_pagado
        msg = (
            f'✅ {egreso.numero_egreso} — Bs. {monto_pagado:,.0f} pagado a {nombre_prof} '
            f'por {n_sesiones} sesión(es).'
        )
        if diferencia > 0 and saldado:
            msg += f' Diferencia de Bs. {diferencia:,.0f} marcada como saldada.'
        elif diferencia > 0:
            msg += f' Quedan Bs. {diferencia:,.0f} pendientes.'
        elif diferencia < 0:
            msg += f' Adelanto de Bs. {abs(diferencia):,.0f} incluido.'

        messages.success(request, msg)

    except Exception as e:
        messages.error(request, f'❌ Error: {str(e)}')

    return redirect('egresos:liquidar_honorarios')