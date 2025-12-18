from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Sum, Count, F
from django.core.paginator import Paginator
from django.http import JsonResponse, HttpResponse
from django.conf import settings
from django.utils import timezone
from io import BytesIO
import base64
import os
from decimal import Decimal
from datetime import date, datetime

from .models import CuentaCorriente, Pago, MetodoPago
from pacientes.models import Paciente
from agenda.models import Sesion


@login_required
def lista_cuentas_corrientes(request):
    """
    Lista de cuentas corrientes con paginación y filtros
    OPTIMIZADO: Query única con agregaciones
    """
    
    # Filtros
    buscar = request.GET.get('q', '').strip()
    estado = request.GET.get('estado', '')  # 'deudor', 'al_dia', 'a_favor'
    sucursal_id = request.GET.get('sucursal', '')
    
    # Query base: Pacientes activos con prefetch de sucursales
    pacientes = Paciente.objects.filter(
        estado='activo'
    ).select_related(
        'cuenta_corriente'
    ).prefetch_related(
        'sucursales'
    )
    
    # Filtro de búsqueda
    if buscar:
        pacientes = pacientes.filter(
            Q(nombre__icontains=buscar) | 
            Q(apellido__icontains=buscar) |
            Q(nombre_tutor__icontains=buscar)
        )
    
    # Filtro por sucursal
    if sucursal_id:
        pacientes = pacientes.filter(sucursales__id=sucursal_id)
    
    # Crear cuentas corrientes faltantes (lazy)
    for paciente in pacientes:
        if not hasattr(paciente, 'cuenta_corriente'):
            CuentaCorriente.objects.create(paciente=paciente)
    
    # Filtro por estado de cuenta
    if estado == 'deudor':
        pacientes = [p for p in pacientes if p.cuenta_corriente.saldo < 0]
    elif estado == 'al_dia':
        pacientes = [p for p in pacientes if p.cuenta_corriente.saldo == 0]
    elif estado == 'a_favor':
        pacientes = [p for p in pacientes if p.cuenta_corriente.saldo > 0]
    
    # Ordenar por saldo (deudores primero)
    pacientes = sorted(
        pacientes, 
        key=lambda p: p.cuenta_corriente.saldo
    )
    
    # Paginación (20 por página)
    paginator = Paginator(pacientes, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    # Estadísticas generales (una sola query)
    estadisticas = CuentaCorriente.objects.aggregate(
        total_debe=Sum('saldo', filter=Q(saldo__lt=0)),
        total_favor=Sum('saldo', filter=Q(saldo__gt=0)),
        deudores=Count('id', filter=Q(saldo__lt=0)),
        al_dia=Count('id', filter=Q(saldo=0)),
    )
    
    # Convertir None a 0
    estadisticas['total_debe'] = abs(estadisticas['total_debe'] or Decimal('0.00'))
    estadisticas['total_favor'] = estadisticas['total_favor'] or Decimal('0.00')
    
    # Sucursales para filtro
    from servicios.models import Sucursal
    sucursales = Sucursal.objects.filter(activa=True)
    
    context = {
        'page_obj': page_obj,
        'estadisticas': estadisticas,
        'buscar': buscar,
        'estado': estado,
        'sucursal_id': sucursal_id,
        'sucursales': sucursales,
    }
    
    return render(request, 'facturacion/cuentas_corrientes.html', context)


@login_required
def detalle_cuenta_corriente(request, paciente_id):
    """
    Detalle completo de cuenta corriente de un paciente
    OPTIMIZADO: Queries con select_related
    """
    
    paciente = get_object_or_404(
        Paciente.objects.select_related('cuenta_corriente'),
        id=paciente_id
    )
    
    # Crear cuenta corriente si no existe
    cuenta, created = CuentaCorriente.objects.get_or_create(paciente=paciente)
    if created:
        cuenta.actualizar_saldo()
    
    # Sesiones (paginadas) - OPTIMIZADO
    sesiones = Sesion.objects.filter(
        paciente=paciente,
        estado__in=['realizada', 'realizada_retraso', 'falta']
    ).select_related(
        'servicio', 'profesional', 'sucursal'
    ).order_by('-fecha', '-hora_inicio')
    
    # Paginar sesiones (15 por página)
    paginator_sesiones = Paginator(sesiones, 15)
    page_sesiones = request.GET.get('page_sesiones', 1)
    sesiones_page = paginator_sesiones.get_page(page_sesiones)
    
    # Pagos (paginados) - OPTIMIZADO
    pagos = Pago.objects.filter(
        paciente=paciente,
        anulado=False
    ).select_related(
        'metodo_pago', 'sesion', 'registrado_por'
    ).order_by('-fecha_pago')
    
    # Paginar pagos (15 por página)
    paginator_pagos = Paginator(pagos, 15)
    page_pagos = request.GET.get('page_pagos', 1)
    pagos_page = paginator_pagos.get_page(page_pagos)
    
    # Estadísticas del paciente (una query)
    stats = Sesion.objects.filter(paciente=paciente).aggregate(
        total_sesiones=Count('id'),
        realizadas=Count('id', filter=Q(estado='realizada')),
        faltas=Count('id', filter=Q(estado='falta')),
        pendientes_pago=Count('id', filter=Q(pagado=False, estado__in=['realizada', 'realizada_retraso'])),
    )
    
    context = {
        'paciente': paciente,
        'cuenta': cuenta,
        'sesiones': sesiones_page,
        'pagos': pagos_page,
        'stats': stats,
    }
    
    return render(request, 'facturacion/detalle_cuenta.html', context)


@login_required
def registrar_pago(request):
    """
    Registrar pago simple a una sesión específica
    OPTIMIZADO: Formulario simple, sin JS pesado
    """
    
    if request.method == 'POST':
        try:
            sesion_id = request.POST.get('sesion_id')
            paciente_id = request.POST.get('paciente_id')
            monto = Decimal(request.POST.get('monto'))
            metodo_pago_id = request.POST.get('metodo_pago')
            fecha_pago_str = request.POST.get('fecha_pago')
            observaciones = request.POST.get('observaciones', '')
            
            # Validaciones básicas
            if not all([paciente_id, monto, metodo_pago_id, fecha_pago_str]):
                messages.error(request, '❌ Faltan datos obligatorios')
                return redirect('facturacion:registrar_pago')
            
            from datetime import datetime
            fecha_pago = datetime.strptime(fecha_pago_str, '%Y-%m-%d').date()
            
            paciente = Paciente.objects.get(id=paciente_id)
            metodo_pago = MetodoPago.objects.get(id=metodo_pago_id)
            
            # Sesión opcional
            sesion = None
            if sesion_id:
                sesion = Sesion.objects.get(id=sesion_id)
                concepto = f"Pago de sesión {sesion.fecha} - {sesion.servicio.nombre}"
            else:
                concepto = f"Pago general - {paciente.nombre_completo}"
            
            # Crear pago
            pago = Pago.objects.create(
                paciente=paciente,
                sesion=sesion,
                fecha_pago=fecha_pago,
                monto=monto,
                metodo_pago=metodo_pago,
                concepto=concepto,
                observaciones=observaciones,
                registrado_por=request.user
            )
            
            # Si hay sesión, marcarla como pagada
            if sesion:
                sesion.pagado = True
                sesion.fecha_pago = fecha_pago
                sesion.save()
            
            # Actualizar cuenta corriente
            cuenta, created = CuentaCorriente.objects.get_or_create(paciente=paciente)
            cuenta.actualizar_saldo()
            
            messages.success(request, f'✅ Pago registrado correctamente. Recibo: {pago.numero_recibo}')
            return redirect('facturacion:detalle_cuenta', paciente_id=paciente.id)
            
        except Exception as e:
            messages.error(request, f'❌ Error: {str(e)}')
            return redirect('facturacion:registrar_pago')
    
    # GET - Mostrar formulario
    metodos_pago = MetodoPago.objects.filter(activo=True)
    
    # Si viene sesion_id pre-seleccionada
    sesion_id = request.GET.get('sesion')
    sesion = None
    if sesion_id:
        sesion = get_object_or_404(
            Sesion.objects.select_related('paciente', 'servicio'),
            id=sesion_id
        )
    
    context = {
        'metodos_pago': metodos_pago,
        'sesion': sesion,
        'fecha_hoy': date.today(),
    }
    
    return render(request, 'facturacion/registrar_pago.html', context)


@login_required
def marcar_sesion_pagada(request, sesion_id):
    """
    Marcar sesión como pagada (rápido desde lista)
    OPTIMIZADO: HTMX response
    """
    
    if request.method == 'POST':
        try:
            sesion = get_object_or_404(Sesion, id=sesion_id)
            
            # Marcar como pagada
            sesion.pagado = True
            sesion.fecha_pago = date.today()
            sesion.save()
            
            # Actualizar cuenta corriente
            cuenta, created = CuentaCorriente.objects.get_or_create(paciente=sesion.paciente)
            cuenta.actualizar_saldo()
            
            messages.success(request, f'✅ Sesión marcada como pagada')
            
            # Retornar fragmento actualizado (HTMX)
            return render(request, 'facturacion/partials/sesion_row.html', {
                'sesion': sesion
            })
            
        except Exception as e:
            messages.error(request, f'❌ Error: {str(e)}')
            return redirect('facturacion:detalle_cuenta', paciente_id=sesion.paciente.id)
    
    return redirect('facturacion:cuentas_corrientes')


# ============= APIs AJAX/HTMX =============

@login_required
def buscar_pacientes_ajax(request):
    """
    API: Buscar pacientes para autocomplete
    OPTIMIZADO: Solo campos necesarios
    """
    
    q = request.GET.get('q', '').strip()
    
    if len(q) < 2:
        return JsonResponse({'pacientes': []})
    
    pacientes = Paciente.objects.filter(
        Q(nombre__icontains=q) | 
        Q(apellido__icontains=q) |
        Q(nombre_tutor__icontains=q),
        estado='activo'
    ).values('id', 'nombre', 'apellido')[:10]
    
    return JsonResponse({
        'pacientes': list(pacientes)
    })


@login_required
def sesiones_pendientes_ajax(request, paciente_id):
    """
    API: Obtener sesiones pendientes de pago de un paciente
    OPTIMIZADO: HTMX partial
    """
    
    paciente = get_object_or_404(Paciente, id=paciente_id)
    
    sesiones = Sesion.objects.filter(
        paciente=paciente,
        pagado=False,
        estado__in=['realizada', 'realizada_retraso', 'falta']
    ).select_related('servicio').order_by('-fecha')[:20]
    
    return render(request, 'facturacion/partials/sesiones_pendientes.html', {
        'sesiones': sesiones,
        'paciente': paciente,
    })


# ==================== FASE 2: PAGOS MASIVOS ====================

@login_required
def pagos_masivos(request):
    """
    Vista para pagar múltiples sesiones a la vez
    OPTIMIZADO: Proceso en 3 pasos
    """
    
    # Paso 1: Seleccionar paciente
    paciente_id = request.GET.get('paciente')
    paciente = None
    sesiones_pendientes = []
    
    if paciente_id:
        paciente = get_object_or_404(
            Paciente.objects.select_related('cuenta_corriente'),
            id=paciente_id
        )
        
        # Obtener sesiones pendientes
        sesiones_pendientes = Sesion.objects.filter(
            paciente=paciente,
            pagado=False,
            estado__in=['realizada', 'realizada_retraso', 'falta']
        ).select_related(
            'servicio', 'profesional', 'sucursal'
        ).order_by('-fecha', '-hora_inicio')
    
    # Pacientes con deuda para el selector
    pacientes_con_deuda = Paciente.objects.filter(
        estado='activo',
        cuenta_corriente__saldo__lt=0
    ).select_related('cuenta_corriente').order_by('apellido', 'nombre')[:50]
    
    # Métodos de pago
    metodos_pago = MetodoPago.objects.filter(activo=True)
    
    context = {
        'paciente': paciente,
        'sesiones_pendientes': sesiones_pendientes,
        'pacientes_con_deuda': pacientes_con_deuda,
        'metodos_pago': metodos_pago,
        'fecha_hoy': date.today(),
    }
    
    return render(request, 'facturacion/pagos_masivos.html', context)


@login_required
def procesar_pagos_masivos(request):
    """
    Procesar pago masivo de múltiples sesiones
    OPTIMIZADO: Transacción atómica
    """
    
    if request.method != 'POST':
        return redirect('facturacion:pagos_masivos')
    
    try:
        from django.db import transaction
        
        # Datos del formulario
        paciente_id = request.POST.get('paciente_id')
        sesiones_ids = request.POST.getlist('sesiones_ids')
        metodo_pago_id = request.POST.get('metodo_pago')
        fecha_pago_str = request.POST.get('fecha_pago')
        observaciones = request.POST.get('observaciones', '')
        
        # Validaciones
        if not all([paciente_id, sesiones_ids, metodo_pago_id, fecha_pago_str]):
            messages.error(request, '❌ Faltan datos obligatorios')
            return redirect('facturacion:pagos_masivos')
        
        fecha_pago = datetime.strptime(fecha_pago_str, '%Y-%m-%d').date()
        paciente = Paciente.objects.get(id=paciente_id)
        metodo_pago = MetodoPago.objects.get(id=metodo_pago_id)
        
        # Obtener sesiones seleccionadas
        sesiones = Sesion.objects.filter(
            id__in=sesiones_ids,
            paciente=paciente,
            pagado=False
        ).select_related('servicio')
        
        if not sesiones.exists():
            messages.error(request, '❌ No se encontraron sesiones válidas')
            return redirect('facturacion:pagos_masivos')
        
        # Calcular total
        total = sum(s.monto_cobrado for s in sesiones)
        
        # 🔒 TRANSACCIÓN ATÓMICA
        with transaction.atomic():
            # Opción 1: UN SOLO PAGO para todas las sesiones
            concepto = f"Pago masivo de {len(sesiones)} sesiones"
            
            pago = Pago.objects.create(
                paciente=paciente,
                sesion=None,  # No asociado a sesión específica
                fecha_pago=fecha_pago,
                monto=total,
                metodo_pago=metodo_pago,
                concepto=concepto,
                observaciones=observaciones,
                registrado_por=request.user
            )
            
            # Marcar todas las sesiones como pagadas
            contador = 0
            for sesion in sesiones:
                sesion.pagado = True
                sesion.fecha_pago = fecha_pago
                sesion.save()
                contador += 1
            
            # Actualizar cuenta corriente
            cuenta, created = CuentaCorriente.objects.get_or_create(paciente=paciente)
            cuenta.actualizar_saldo()
        
        messages.success(
            request, 
            f'✅ Pago masivo registrado correctamente. {contador} sesiones marcadas como pagadas. Recibo: {pago.numero_recibo}'
        )
        return redirect('facturacion:detalle_cuenta', paciente_id=paciente.id)
        
    except Exception as e:
        messages.error(request, f'❌ Error al procesar pago masivo: {str(e)}')
        return redirect('facturacion:pagos_masivos')


# ==================== HISTORIAL DE PAGOS ====================

@login_required
def historial_pagos(request):
    """
    Historial completo de pagos con filtros
    OPTIMIZADO: Queries y paginación
    """
    
    # Filtros
    buscar = request.GET.get('q', '').strip()
    metodo_id = request.GET.get('metodo', '')
    fecha_desde = request.GET.get('fecha_desde', '')
    fecha_hasta = request.GET.get('fecha_hasta', '')
    
    # Query base - OPTIMIZADO
    pagos = Pago.objects.select_related(
        'paciente', 'metodo_pago', 'registrado_por', 'sesion__servicio'
    ).filter(
        anulado=False
    ).order_by('-fecha_pago', '-fecha_registro')
    
    # Filtro de búsqueda por paciente
    if buscar:
        pagos = pagos.filter(
            Q(paciente__nombre__icontains=buscar) |
            Q(paciente__apellido__icontains=buscar) |
            Q(numero_recibo__icontains=buscar)
        )
    
    # Filtro por método de pago
    if metodo_id:
        pagos = pagos.filter(metodo_pago_id=metodo_id)
    
    # Filtro por rango de fechas
    if fecha_desde:
        try:
            fecha_desde_obj = datetime.strptime(fecha_desde, '%Y-%m-%d').date()
            pagos = pagos.filter(fecha_pago__gte=fecha_desde_obj)
        except:
            pass
    
    if fecha_hasta:
        try:
            fecha_hasta_obj = datetime.strptime(fecha_hasta, '%Y-%m-%d').date()
            pagos = pagos.filter(fecha_pago__lte=fecha_hasta_obj)
        except:
            pass
    
    # Estadísticas (una query)
    stats = pagos.aggregate(
        total_pagos=Count('id'),
        monto_total=Sum('monto')
    )
    
    # Paginación (25 por página)
    paginator = Paginator(pagos, 25)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    # Métodos de pago para filtro
    metodos_pago = MetodoPago.objects.filter(activo=True)
    
    context = {
        'page_obj': page_obj,
        'stats': stats,
        'buscar': buscar,
        'metodo_id': metodo_id,
        'fecha_desde': fecha_desde,
        'fecha_hasta': fecha_hasta,
        'metodos_pago': metodos_pago,
    }
    
    return render(request, 'facturacion/historial_pagos.html', context)


# ==================== RECIBOS PDF ====================

def encontrar_logo():
    """
    Buscar logo en múltiples ubicaciones posibles
    Funciona tanto en desarrollo como en producción (Render)
    """
    posibles_rutas = [
        # Desarrollo
        os.path.join(settings.BASE_DIR, 'static', 'img', 'logo_misael.png'),
        # Producción (después de collectstatic)
        os.path.join(settings.BASE_DIR, 'staticfiles', 'img', 'logo_misael.png'),
    ]
    
    # Agregar STATIC_ROOT si existe (Render.com)
    if hasattr(settings, 'STATIC_ROOT') and settings.STATIC_ROOT:
        posibles_rutas.append(
            os.path.join(settings.STATIC_ROOT, 'img', 'logo_misael.png')
        )
    
    # Agregar STATICFILES_DIRS si existe
    if hasattr(settings, 'STATICFILES_DIRS'):
        for static_dir in settings.STATICFILES_DIRS:
            posibles_rutas.append(
                os.path.join(static_dir, 'img', 'logo_misael.png')
            )
    
    # Devolver la primera ruta que existe
    for ruta in posibles_rutas:
        if os.path.exists(ruta):
            return ruta
    
    return None


@login_required
def generar_recibo_pdf(request, pago_id):
    """
    Generar recibo en PDF usando xhtml2pdf con logo en Base64
    OPTIMIZADO para Render.com (plan gratuito)
    Logo embebido directamente en el HTML
    """
    
    pago = get_object_or_404(
        Pago.objects.select_related(
            'paciente', 'metodo_pago', 'registrado_por', 'sesion__servicio'
        ),
        id=pago_id
    )
    
    try:
        from xhtml2pdf import pisa
        
        # Cargar logo como Base64
        logo_base64 = None
        logo_path = encontrar_logo()
        
        if logo_path:
            try:
                with open(logo_path, 'rb') as logo_file:
                    logo_base64 = base64.b64encode(logo_file.read()).decode('utf-8')
            except Exception as e:
                # Si falla la carga del logo, continuar sin él
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f'No se pudo cargar el logo: {str(e)}')
        
        # Renderizar template HTML con logo embebido
        html_string = render(request, 'facturacion/recibo_pdf.html', {
            'pago': pago,
            'para_pdf': True,
            'logo_base64': logo_base64,
        }).content.decode('utf-8')
        
        # Crear buffer para el PDF
        result = BytesIO()
        
        # Convertir HTML a PDF
        pdf = pisa.pisaDocument(
            BytesIO(html_string.encode("UTF-8")), 
            result,
            encoding='UTF-8'
        )
        
        # Verificar si hubo errores
        if pdf.err:
            raise Exception(f"Error en la generación del PDF: código {pdf.err}")
        
        # Preparar respuesta
        result.seek(0)
        response = HttpResponse(result.read(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="recibo_{pago.numero_recibo}.pdf"'
        
        return response
        
    except ImportError:
        # Fallback: mostrar HTML si xhtml2pdf no está instalado
        messages.warning(
            request, 
            '⚠️ PDF no disponible temporalmente. Mostrando versión para imprimir.'
        )
        return render(request, 'facturacion/recibo_pdf.html', {
            'pago': pago,
            'para_impresion': True
        })
        
    except Exception as e:
        # Log del error para debugging
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f'Error generando PDF para pago {pago_id}: {str(e)}')
        
        messages.error(request, f'❌ Error al generar PDF. Intenta nuevamente.')
        return redirect('facturacion:historial_pagos')

# ==================== ANULAR PAGOS ====================

@login_required
def anular_pago(request, pago_id):
    """
    Anular un pago (con auditoría)
    OPTIMIZADO: Modal HTMX
    """
    
    pago = get_object_or_404(Pago, id=pago_id)
    
    if request.method == 'POST':
        try:
            from django.db import transaction
            
            motivo = request.POST.get('motivo', '').strip()
            
            if not motivo:
                messages.error(request, '❌ Debes especificar un motivo')
                return redirect('facturacion:historial_pagos')
            
            # 🔒 TRANSACCIÓN ATÓMICA
            with transaction.atomic():
                # Anular pago
                pago.anular(request.user, motivo)
            
            messages.success(request, f'✅ Pago {pago.numero_recibo} anulado correctamente')
            return redirect('facturacion:historial_pagos')
            
        except Exception as e:
            messages.error(request, f'❌ Error al anular pago: {str(e)}')
            return redirect('facturacion:historial_pagos')
    
    # GET - Modal de confirmación
    return render(request, 'facturacion/partials/anular_pago_modal.html', {
        'pago': pago
    })


# ==================== FASE 3: REPORTES ====================

@login_required
def dashboard_reportes(request):
    """
    Dashboard de reportes - punto de entrada
    OPTIMIZADO: Vista simple con enlaces
    """
    return render(request, 'facturacion/reportes/dashboard.html')


@login_required
def reporte_paciente(request):
    """
    Reporte detallado por paciente
    OPTIMIZADO: Agregaciones en una query
    """
    
    paciente_id = request.GET.get('paciente')
    fecha_desde = request.GET.get('fecha_desde', '')
    fecha_hasta = request.GET.get('fecha_hasta', '')
    
    paciente = None
    datos = None
    grafico_data = None
    
    if paciente_id:
        from datetime import datetime, timedelta
        
        paciente = get_object_or_404(
            Paciente.objects.select_related('cuenta_corriente'),
            id=paciente_id
        )
        
        # Rango de fechas (por defecto: últimos 3 meses)
        if fecha_desde and fecha_hasta:
            fecha_desde_obj = datetime.strptime(fecha_desde, '%Y-%m-%d').date()
            fecha_hasta_obj = datetime.strptime(fecha_hasta, '%Y-%m-%d').date()
        else:
            fecha_hasta_obj = date.today()
            fecha_desde_obj = fecha_hasta_obj - timedelta(days=90)
            fecha_desde = fecha_desde_obj.strftime('%Y-%m-%d')
            fecha_hasta = fecha_hasta_obj.strftime('%Y-%m-%d')
        
        # Query base
        sesiones = Sesion.objects.filter(
            paciente=paciente,
            fecha__gte=fecha_desde_obj,
            fecha__lte=fecha_hasta_obj
        ).select_related('servicio', 'profesional', 'sucursal')
        
        # Estadísticas generales (una query)
        stats = sesiones.aggregate(
            total_sesiones=Count('id'),
            realizadas=Count('id', filter=Q(estado='realizada')),
            retrasos=Count('id', filter=Q(estado='realizada_retraso')),
            faltas=Count('id', filter=Q(estado='falta')),
            permisos=Count('id', filter=Q(estado='permiso')),
            canceladas=Count('id', filter=Q(estado='cancelada')),
            total_cobrado=Sum('monto_cobrado'),
            total_pagado=Sum('monto_cobrado', filter=Q(pagado=True)),
        )
        
        # Calcular tasa de asistencia
        sesiones_efectivas = stats['realizadas'] + stats['retrasos']
        sesiones_programadas = stats['total_sesiones'] - stats['canceladas'] - stats['permisos']
        tasa_asistencia = (sesiones_efectivas / sesiones_programadas * 100) if sesiones_programadas > 0 else 0
        
        # Por servicio (una query con group by)
        por_servicio = sesiones.values(
            'servicio__nombre', 'servicio__color'
        ).annotate(
            cantidad=Count('id'),
            monto_total=Sum('monto_cobrado')
        ).order_by('-cantidad')
        
        # Por mes (para gráfico)
        from django.db.models.functions import TruncMonth
        por_mes = sesiones.annotate(
            mes=TruncMonth('fecha')
        ).values('mes').annotate(
            cantidad=Count('id'),
            realizadas=Count('id', filter=Q(estado='realizada')),
            faltas=Count('id', filter=Q(estado='falta'))
        ).order_by('mes')
        
        # Preparar datos para gráfico
        grafico_data = {
            'labels': [m['mes'].strftime('%b %Y') for m in por_mes],
            'realizadas': [m['realizadas'] for m in por_mes],
            'faltas': [m['faltas'] for m in por_mes],
        }
        
        datos = {
            'stats': stats,
            'tasa_asistencia': round(tasa_asistencia, 1),
            'por_servicio': por_servicio,
            'sesiones_recientes': sesiones.order_by('-fecha', '-hora_inicio')[:10],
        }
    
    # Lista de pacientes para selector
    pacientes = Paciente.objects.filter(estado='activo').order_by('apellido', 'nombre')
    
    context = {
        'paciente': paciente,
        'datos': datos,
        'grafico_data': grafico_data,
        'pacientes': pacientes,
        'fecha_desde': fecha_desde,
        'fecha_hasta': fecha_hasta,
    }
    
    return render(request, 'facturacion/reportes/paciente.html', context)


@login_required
def reporte_profesional(request):
    """
    Reporte detallado por profesional
    OPTIMIZADO: Agregaciones eficientes
    """
    
    from profesionales.models import Profesional
    
    profesional_id = request.GET.get('profesional')
    sucursal_id = request.GET.get('sucursal', '')
    fecha_desde = request.GET.get('fecha_desde', '')
    fecha_hasta = request.GET.get('fecha_hasta', '')
    
    profesional = None
    datos = None
    
    if profesional_id:
        from datetime import datetime, timedelta
        
        profesional = get_object_or_404(Profesional, id=profesional_id)
        
        # Rango de fechas
        if fecha_desde and fecha_hasta:
            fecha_desde_obj = datetime.strptime(fecha_desde, '%Y-%m-%d').date()
            fecha_hasta_obj = datetime.strptime(fecha_hasta, '%Y-%m-%d').date()
        else:
            fecha_hasta_obj = date.today()
            fecha_desde_obj = fecha_hasta_obj - timedelta(days=90)
            fecha_desde = fecha_desde_obj.strftime('%Y-%m-%d')
            fecha_hasta = fecha_hasta_obj.strftime('%Y-%m-%d')
        
        # Query base
        sesiones = Sesion.objects.filter(
            profesional=profesional,
            fecha__gte=fecha_desde_obj,
            fecha__lte=fecha_hasta_obj
        )
        
        # Filtro por sucursal
        if sucursal_id:
            sesiones = sesiones.filter(sucursal_id=sucursal_id)
        
        sesiones = sesiones.select_related('paciente', 'servicio', 'sucursal')
        
        # Estadísticas
        stats = sesiones.aggregate(
            total_sesiones=Count('id'),
            realizadas=Count('id', filter=Q(estado='realizada')),
            retrasos=Count('id', filter=Q(estado='realizada_retraso')),
            faltas=Count('id', filter=Q(estado='falta')),
            total_generado=Sum('monto_cobrado', filter=Q(estado__in=['realizada', 'realizada_retraso'])),
            pacientes_unicos=Count('paciente', distinct=True),
        )
        
        # Por servicio
        por_servicio = sesiones.values(
            'servicio__nombre', 'servicio__color'
        ).annotate(
            cantidad=Count('id'),
            ingresos=Sum('monto_cobrado', filter=Q(estado__in=['realizada', 'realizada_retraso']))
        ).order_by('-cantidad')
        
        # Por sucursal
        por_sucursal = sesiones.values(
            'sucursal__nombre'
        ).annotate(
            cantidad=Count('id')
        ).order_by('-cantidad')
        
        # Top pacientes atendidos
        top_pacientes = sesiones.values(
            'paciente__nombre', 'paciente__apellido'
        ).annotate(
            sesiones=Count('id')
        ).order_by('-sesiones')[:5]
        
        datos = {
            'stats': stats,
            'por_servicio': por_servicio,
            'por_sucursal': por_sucursal,
            'top_pacientes': top_pacientes,
        }
    
    # Listas para filtros
    profesionales = Profesional.objects.filter(activo=True).order_by('apellido', 'nombre')
    
    from servicios.models import Sucursal
    sucursales = Sucursal.objects.filter(activa=True)
    
    context = {
        'profesional': profesional,
        'datos': datos,
        'profesionales': profesionales,
        'sucursales': sucursales,
        'sucursal_id': sucursal_id,
        'fecha_desde': fecha_desde,
        'fecha_hasta': fecha_hasta,
    }
    
    return render(request, 'facturacion/reportes/profesional.html', context)

@login_required
def reporte_sucursal(request):
    """
    Reporte detallado por sucursal
    OPTIMIZADO: Comparativas entre sucursales
    """
    
    from servicios.models import Sucursal
    
    sucursal_id = request.GET.get('sucursal')
    fecha_desde = request.GET.get('fecha_desde', '')
    fecha_hasta = request.GET.get('fecha_hasta', '')
    
    sucursal = None
    datos = None
    comparativa = []
    
    if sucursal_id:
        from datetime import datetime, timedelta
        
        sucursal = get_object_or_404(Sucursal, id=sucursal_id)
        
        # Rango de fechas
        if fecha_desde and fecha_hasta:
            fecha_desde_obj = datetime.strptime(fecha_desde, '%Y-%m-%d').date()
            fecha_hasta_obj = datetime.strptime(fecha_hasta, '%Y-%m-%d').date()
        else:
            fecha_hasta_obj = date.today()
            fecha_desde_obj = fecha_hasta_obj - timedelta(days=90)
            fecha_desde = fecha_desde_obj.strftime('%Y-%m-%d')
            fecha_hasta = fecha_hasta_obj.strftime('%Y-%m-%d')
        
        # Query base
        sesiones = Sesion.objects.filter(
            sucursal=sucursal,
            fecha__gte=fecha_desde_obj,
            fecha__lte=fecha_hasta_obj
        ).select_related('paciente', 'servicio', 'profesional')
        
        # Estadísticas
        stats = sesiones.aggregate(
            total_sesiones=Count('id'),
            realizadas=Count('id', filter=Q(estado='realizada')),
            ingresos_total=Sum('monto_cobrado', filter=Q(estado__in=['realizada', 'realizada_retraso'])),
            profesionales_activos=Count('profesional', distinct=True),
            pacientes_activos=Count('paciente', distinct=True),
        )
        
        # Por servicio
        por_servicio = sesiones.values(
            'servicio__nombre'
        ).annotate(
            cantidad=Count('id'),
            ingresos=Sum('monto_cobrado', filter=Q(estado__in=['realizada', 'realizada_retraso']))
        ).order_by('-cantidad')
        
        # Top profesionales
        top_profesionales = sesiones.values(
            'profesional__nombre', 'profesional__apellido'
        ).annotate(
            sesiones=Count('id')
        ).order_by('-sesiones')[:5]
        
        datos = {
            'stats': stats,
            'por_servicio': por_servicio,
            'top_profesionales': top_profesionales,
        }
        
        # Comparativa con otras sucursales (CORREGIDO)
        todas_sucursales = Sucursal.objects.filter(activa=True).annotate(
            total_sesiones=Count('sesiones', filter=Q(
                sesiones__fecha__gte=fecha_desde_obj,
                sesiones__fecha__lte=fecha_hasta_obj
            )),
            total_ingresos=Sum('sesiones__monto_cobrado', filter=Q(
                sesiones__fecha__gte=fecha_desde_obj,
                sesiones__fecha__lte=fecha_hasta_obj,
                sesiones__estado__in=['realizada', 'realizada_retraso']
            ))
        ).order_by('-total_sesiones')
        
        comparativa = list(todas_sucursales)
    
    # Lista de sucursales
    sucursales = Sucursal.objects.filter(activa=True)
    
    context = {
        'sucursal': sucursal,
        'datos': datos,
        'comparativa': comparativa,
        'sucursales': sucursales,
        'fecha_desde': fecha_desde,
        'fecha_hasta': fecha_hasta,
    }
    
    return render(request, 'facturacion/reportes/sucursal.html', context)

@login_required
def reporte_financiero(request):
    """
    Reporte financiero general
    OPTIMIZADO: Dashboard financiero completo
    """
    
    from datetime import datetime, timedelta
    from servicios.models import Sucursal
    
    sucursal_id = request.GET.get('sucursal', '')
    fecha_desde = request.GET.get('fecha_desde', '')
    fecha_hasta = request.GET.get('fecha_hasta', '')
    
    # Rango de fechas (por defecto: mes actual)
    if fecha_desde and fecha_hasta:
        fecha_desde_obj = datetime.strptime(fecha_desde, '%Y-%m-%d').date()
        fecha_hasta_obj = datetime.strptime(fecha_hasta, '%Y-%m-%d').date()
    else:
        fecha_hasta_obj = date.today()
        fecha_desde_obj = fecha_hasta_obj.replace(day=1)
        fecha_desde = fecha_desde_obj.strftime('%Y-%m-%d')
        fecha_hasta = fecha_hasta_obj.strftime('%Y-%m-%d')
    
    # Query base
    sesiones = Sesion.objects.filter(
        fecha__gte=fecha_desde_obj,
        fecha__lte=fecha_hasta_obj
    )
    
    pagos = Pago.objects.filter(
        fecha_pago__gte=fecha_desde_obj,
        fecha_pago__lte=fecha_hasta_obj,
        anulado=False
    )
    
    # Filtro por sucursal
    if sucursal_id:
        sesiones = sesiones.filter(sucursal_id=sucursal_id)
        pagos = pagos.filter(sesion__sucursal_id=sucursal_id)
    
    # Ingresos (UNA QUERY)
    ingresos = sesiones.filter(
        estado__in=['realizada', 'realizada_retraso']
    ).aggregate(
        total_generado=Sum('monto_cobrado'),
        total_cobrado=Sum('monto_cobrado', filter=Q(pagado=True)),
        total_pendiente=Sum('monto_cobrado', filter=Q(pagado=False)),
    )
    
    # Por método de pago (UNA QUERY)
    por_metodo = pagos.values(
        'metodo_pago__nombre'
    ).annotate(
        cantidad=Count('id'),
        monto=Sum('monto')
    ).order_by('-monto')
    
    # Por servicio (UNA QUERY)
    por_servicio = sesiones.filter(
        estado__in=['realizada', 'realizada_retraso']
    ).values(
        'servicio__nombre'
    ).annotate(
        sesiones=Count('id'),
        ingresos=Sum('monto_cobrado')
    ).order_by('-ingresos')[:5]
    
    # Evolución mensual (últimos 6 meses)
    seis_meses_atras = fecha_hasta_obj - timedelta(days=180)
    from django.db.models.functions import TruncMonth
    
    evolucion = Sesion.objects.filter(
        fecha__gte=seis_meses_atras,
        fecha__lte=fecha_hasta_obj,
        estado__in=['realizada', 'realizada_retraso']
    ).annotate(
        mes=TruncMonth('fecha')
    ).values('mes').annotate(
        ingresos=Sum('monto_cobrado'),
        cobrado=Sum('monto_cobrado', filter=Q(pagado=True))
    ).order_by('mes')
    
    # Preparar datos para gráfico
    grafico_data = {
        'labels': [e['mes'].strftime('%b %Y') for e in evolucion],
        'ingresos': [float(e['ingresos'] or 0) for e in evolucion],
        'cobrado': [float(e['cobrado'] or 0) for e in evolucion],
    }
    
    # Sucursales para filtro
    sucursales = Sucursal.objects.filter(activa=True)
    
    context = {
        'ingresos': ingresos,
        'por_metodo': por_metodo,
        'por_servicio': por_servicio,
        'grafico_data': grafico_data,
        'sucursales': sucursales,
        'sucursal_id': sucursal_id,
        'fecha_desde': fecha_desde,
        'fecha_hasta': fecha_hasta,
    }
    
    return render(request, 'facturacion/reportes/financiero.html', context)


@login_required
def reporte_asistencia(request):
    """
    Reporte de asistencia y cumplimiento
    OPTIMIZADO: Análisis de comportamiento
    """
    
    from datetime import datetime, timedelta
    
    tipo = request.GET.get('tipo', 'general')  # general, paciente, profesional
    entidad_id = request.GET.get('entidad_id', '')
    fecha_desde = request.GET.get('fecha_desde', '')
    fecha_hasta = request.GET.get('fecha_hasta', '')
    
    # Rango de fechas
    if fecha_desde and fecha_hasta:
        fecha_desde_obj = datetime.strptime(fecha_desde, '%Y-%m-%d').date()
        fecha_hasta_obj = datetime.strptime(fecha_hasta, '%Y-%m-%d').date()
    else:
        fecha_hasta_obj = date.today()
        fecha_desde_obj = fecha_hasta_obj - timedelta(days=90)
        fecha_desde = fecha_desde_obj.strftime('%Y-%m-%d')
        fecha_hasta = fecha_hasta_obj.strftime('%Y-%m-%d')
    
    # Query base
    sesiones = Sesion.objects.filter(
        fecha__gte=fecha_desde_obj,
        fecha__lte=fecha_hasta_obj
    )
    
    # Filtros según tipo
    entidad = None
    if tipo == 'paciente' and entidad_id:
        entidad = Paciente.objects.get(id=entidad_id)
        sesiones = sesiones.filter(paciente=entidad)
    elif tipo == 'profesional' and entidad_id:
        from profesionales.models import Profesional
        entidad = Profesional.objects.get(id=entidad_id)
        sesiones = sesiones.filter(profesional=entidad)
    
    # Estadísticas de asistencia (UNA QUERY)
    stats = sesiones.aggregate(
        total=Count('id'),
        programadas=Count('id', filter=Q(estado='programada')),
        realizadas=Count('id', filter=Q(estado='realizada')),
        retrasos=Count('id', filter=Q(estado='realizada_retraso')),
        faltas=Count('id', filter=Q(estado='falta')),
        permisos=Count('id', filter=Q(estado='permiso')),
        canceladas=Count('id', filter=Q(estado='cancelada')),
    )
    
    # Calcular tasas
    sesiones_efectivas = stats['realizadas'] + stats['retrasos']
    sesiones_programadas = stats['total'] - stats['canceladas'] - stats['permisos']
    
    tasas = {
        'asistencia': (sesiones_efectivas / sesiones_programadas * 100) if sesiones_programadas > 0 else 0,
        'faltas': (stats['faltas'] / sesiones_programadas * 100) if sesiones_programadas > 0 else 0,
        'puntualidad': (stats['realizadas'] / sesiones_efectivas * 100) if sesiones_efectivas > 0 else 0,
    }
    
    # Ranking de asistencia (si es reporte general)
    ranking = []
    if tipo == 'general':
        # Top 10 pacientes con mejor asistencia
        ranking = Paciente.objects.filter(
            estado='activo',
            sesiones__fecha__gte=fecha_desde_obj,
            sesiones__fecha__lte=fecha_hasta_obj
        ).annotate(
            total=Count('sesiones'),
            realizadas=Count('sesiones', filter=Q(sesiones__estado__in=['realizada', 'realizada_retraso'])),
            faltas=Count('sesiones', filter=Q(sesiones__estado='falta'))
        ).filter(total__gte=3).annotate(
            tasa=F('realizadas') * 100.0 / F('total')
        ).order_by('-tasa')[:10]
    
    # Listas para filtros
    pacientes = Paciente.objects.filter(estado='activo').order_by('apellido', 'nombre')
    
    from profesionales.models import Profesional
    profesionales = Profesional.objects.filter(activo=True).order_by('apellido', 'nombre')
    
    context = {
        'tipo': tipo,
        'entidad': entidad,
        'stats': stats,
        'tasas': tasas,
        'ranking': ranking,
        'pacientes': pacientes,
        'profesionales': profesionales,
        'fecha_desde': fecha_desde,
        'fecha_hasta': fecha_hasta,
    }
    
    return render(request, 'facturacion/reportes/asistencia.html', context)


@login_required
def exportar_excel(request):
    """
    Exportar datos a Excel
    OPTIMIZADO: Usa openpyxl
    """
    
    tipo = request.GET.get('tipo', 'cuentas')  # cuentas, pagos, sesiones
    
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
        from io import BytesIO
        
        wb = Workbook()
        ws = wb.active
        
        # Header style
        header_fill = PatternFill(start_color="2563EB", end_color="2563EB", fill_type="solid")
        header_font = Font(color="FFFFFF", bold=True)
        
        if tipo == 'cuentas':
            ws.title = "Cuentas Corrientes"
            
            # Headers
            headers = ['Paciente', 'Tutor', 'Teléfono', 'Consumido', 'Pagado', 'Saldo', 'Estado']
            ws.append(headers)
            
            for cell in ws[1]:
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal='center')
            
            # Data
            pacientes = Paciente.objects.filter(
                estado='activo'
            ).select_related('cuenta_corriente').order_by('apellido', 'nombre')
            
            for p in pacientes:
                cuenta = p.cuenta_corriente if hasattr(p, 'cuenta_corriente') else None
                saldo = cuenta.saldo if cuenta else 0
                
                estado = 'DEBE' if saldo < 0 else ('A FAVOR' if saldo > 0 else 'AL DÍA')
                
                ws.append([
                    p.nombre_completo,
                    p.nombre_tutor,
                    p.telefono_tutor,
                    float(cuenta.total_consumido if cuenta else 0),
                    float(cuenta.total_pagado if cuenta else 0),
                    float(saldo),
                    estado
                ])
        
        elif tipo == 'pagos':
            ws.title = "Historial Pagos"
            
            headers = ['Recibo', 'Fecha', 'Paciente', 'Concepto', 'Método', 'Monto']
            ws.append(headers)
            
            for cell in ws[1]:
                cell.fill = header_fill
                cell.font = header_font
            
            pagos = Pago.objects.filter(
                anulado=False
            ).select_related('paciente', 'metodo_pago').order_by('-fecha_pago')[:500]
            
            for pago in pagos:
                ws.append([
                    pago.numero_recibo,
                    pago.fecha_pago.strftime('%d/%m/%Y'),
                    pago.paciente.nombre_completo,
                    pago.concepto[:50],
                    pago.metodo_pago.nombre,
                    float(pago.monto)
                ])
        
        # Ajustar anchos
        for column in ws.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(cell.value)
                except:
                    pass
            adjusted_width = min(max_length + 2, 50)
            ws.column_dimensions[column_letter].width = adjusted_width
        
        # Generar archivo
        output = BytesIO()
        wb.save(output)
        output.seek(0)
        
        response = HttpResponse(
            output.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="reporte_{tipo}_{date.today()}.xlsx"'
        
        return response
        
    except ImportError:
        messages.error(request, '❌ openpyxl no está instalado')
        return redirect('facturacion:dashboard_reportes')
    except Exception as e:
        messages.error(request, f'❌ Error al exportar: {str(e)}')
        return redirect('facturacion:dashboard_reportes')