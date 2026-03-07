"""
facturacion/views_migracion.py

Vista de administración para migrar sesiones históricas a servicio externo.
Accesible desde el navegador — no requiere shell.

AGREGAR EN urls.py de facturacion:
    from . import views_migracion
    path('admin/migrar-comisiones/', views_migracion.panel_migracion_comisiones, name='panel_migracion_comisiones'),
"""

import logging
from decimal import Decimal

from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

logger = logging.getLogger(__name__)


@staff_member_required
@require_http_methods(["GET", "POST"])
def panel_migracion_comisiones(request):
    """
    Panel para migrar sesiones históricas de servicios externos.
    GET  → muestra el diagnóstico (cuántas sesiones necesitan migración)
    POST → ejecuta la migración con el % indicado
    """
    from agenda.models import Sesion
    from servicios.models import ComisionSesion, TipoServicio
    from facturacion.services import AccountService
    from pacientes.models import Paciente

    # ── Servicios que ya están marcados como externos ──────────────────────
    servicios_externos = TipoServicio.objects.filter(
        es_servicio_externo=True,
        porcentaje_centro__isnull=False,
    ).order_by('nombre')

    # ── Diagnóstico por servicio ───────────────────────────────────────────
    diagnostico = []
    for srv in servicios_externos:
        sesiones_todas = Sesion.objects.filter(
            servicio=srv,
            estado__in=['realizada', 'realizada_retraso'],
        )
        con_comision    = sesiones_todas.filter(comision__isnull=False).count()
        sin_comision    = sesiones_todas.filter(comision__isnull=True).count()
        con_pago        = sesiones_todas.filter(
            comision__isnull=True,
            pagos__anulado=False,
        ).exclude(pagos__metodo_pago__nombre='Uso de Crédito').distinct().count()

        diagnostico.append({
            'servicio':      srv,
            'total':         sesiones_todas.count(),
            'con_comision':  con_comision,
            'sin_comision':  sin_comision,
            'con_pago':      con_pago,
            'sin_pago':      sin_comision - con_pago,
        })

    resultado = None

    # ── POST: ejecutar migración ───────────────────────────────────────────
    if request.method == 'POST':
        servicio_id  = request.POST.get('servicio_id')
        porcentaje   = request.POST.get('porcentaje', '').strip()
        usar_pago    = request.POST.get('usar_pago', 'si') == 'si'
        recalcular   = request.POST.get('recalcular', 'si') == 'si'

        errores = []
        if not servicio_id:
            errores.append('Debes seleccionar un servicio.')
        if not porcentaje:
            errores.append('Debes indicar el porcentaje del centro.')
        else:
            try:
                pct = Decimal(porcentaje)
                if not (0 < pct <= 100):
                    errores.append('El porcentaje debe estar entre 1 y 100.')
            except Exception:
                errores.append('El porcentaje debe ser un número válido.')

        if not errores:
            try:
                srv = TipoServicio.objects.get(id=servicio_id, es_servicio_externo=True)
            except TipoServicio.DoesNotExist:
                errores.append('Servicio no encontrado o no marcado como externo.')

        if errores:
            resultado = {'ok': False, 'errores': errores}
        else:
            # Sesiones sin comisión de ese servicio
            sesiones_pendientes = Sesion.objects.filter(
                servicio=srv,
                estado__in=['realizada', 'realizada_retraso'],
                comision__isnull=True,
            )

            creadas      = 0
            sin_pago_ids = []
            detalles     = []

            for s in sesiones_pendientes:
                if usar_pago:
                    pago = s.pagos.filter(anulado=False).exclude(
                        metodo_pago__nombre='Uso de Crédito'
                    ).first()
                    precio = pago.monto if pago else s.monto_cobrado
                    if not pago:
                        sin_pago_ids.append(s.id)
                else:
                    precio = s.monto_cobrado

                try:
                    comision = ComisionSesion.objects.create(
                        sesion=s,
                        precio_cobrado=precio,
                        porcentaje_centro=pct,
                    )
                    creadas += 1
                    detalles.append({
                        'sesion_id':    s.id,
                        'paciente':     str(s.paciente),
                        'fecha':        s.fecha,
                        'precio':       precio,
                        'monto_centro': comision.monto_centro,
                        'monto_prof':   comision.monto_profesional,
                        'ok':           True,
                    })
                except Exception as e:
                    logger.error(f"Error creando ComisionSesion para sesión {s.id}: {e}")
                    detalles.append({
                        'sesion_id': s.id,
                        'paciente':  str(s.paciente),
                        'fecha':     s.fecha,
                        'ok':        False,
                        'error':     str(e),
                    })

            # Recalcular cuentas corrientes afectadas
            recalculados = 0
            if recalcular and creadas > 0:
                paciente_ids = sesiones_pendientes.values_list(
                    'paciente_id', flat=True
                ).distinct()
                for p in Paciente.objects.filter(id__in=paciente_ids):
                    try:
                        AccountService.update_balance(p)
                        recalculados += 1
                    except Exception as e:
                        logger.error(f"Error recalculando cuenta de {p}: {e}")

            resultado = {
                'ok':           True,
                'servicio':     srv.nombre,
                'porcentaje':   pct,
                'creadas':      creadas,
                'sin_pago_ids': sin_pago_ids,
                'recalculados': recalculados,
                'detalles':     detalles,
            }

    return render(request, 'facturacion/admin/panel_migracion_comisiones.html', {
        'servicios_externos': servicios_externos,
        'diagnostico':        diagnostico,
        'resultado':          resultado,
    })