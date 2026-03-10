# facturacion/admin_views.py
# ✅ Vistas administrativas para recálculo de cuentas

from django.shortcuts import render, redirect
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.db import transaction
from django.utils import timezone

from .services import AccountService
from .models import CuentaCorriente
from pacientes.models import Paciente

import logging

logger = logging.getLogger(__name__)


@staff_member_required
def panel_recalcular_cuentas(request):
    """
    Panel administrativo para recalcular cuentas corrientes.
    Pasa cuentas_json al template para que la tabla se renderice
    sin necesitar ningún AJAX extra (evita problemas de auth en Render).
    """
    total_cuentas     = CuentaCorriente.objects.count()
    total_pacientes   = Paciente.objects.count()
    cuentas_negativas = CuentaCorriente.objects.filter(saldo_actual__lt=0).count()

    # ── Serializar lista de cuentas para el template ──────────
    # Consultamos CuentaCorriente directamente (select_related al paciente)
    # para evitar problemas con el related_name inverso.
    cuentas_qs = (
        CuentaCorriente.objects
        .select_related('paciente')
        .order_by('paciente__apellido', 'paciente__nombre')
    )

    cuentas_list = []
    for c in cuentas_qs:
        cuentas_list.append({
            'id':                   c.paciente.id,
            'nombre':               str(c.paciente),
            'saldo_actual':         float(c.saldo_actual),
            'saldo_real':           float(c.saldo_real),
            'ultima_actualizacion': (
                c.ultima_actualizacion.isoformat()
                if c.ultima_actualizacion else None
            ),
        })

    # Pacientes sin cuenta corriente aún
    ids_con_cuenta = {c['id'] for c in cuentas_list}
    for p in Paciente.objects.exclude(id__in=ids_con_cuenta).order_by('apellido', 'nombre'):
        cuentas_list.append({
            'id':                   p.id,
            'nombre':               str(p),
            'saldo_actual':         0.0,
            'saldo_real':           0.0,
            'ultima_actualizacion': None,
        })

    context = {
        'total_cuentas':     total_cuentas,
        'total_pacientes':   total_pacientes,
        'cuentas_negativas': cuentas_negativas,
        'cuentas_json':      cuentas_list,   # consumido por |json_script en el template
    }

    return render(request, 'facturacion/admin/panel_recalcular_cuentas.html', context)


@staff_member_required
@require_http_methods(["POST"])
def recalcular_todas_cuentas(request):
    """
    Ejecuta el recálculo de todas las cuentas corrientes.
    ✅ Solo POST y solo para staff.
    """
    try:
        logger.info(f"🔄 Iniciando recálculo de todas las cuentas por usuario {request.user.username}")

        resultado = AccountService.recalcular_todas_las_cuentas()

        messages.success(
            request,
            f'✅ Recálculo completado: {resultado["exitosos"]} cuentas actualizadas. '
            f'Errores: {len(resultado["errores"])}'
        )

        if resultado['errores']:
            errores_msg = '<br>'.join([
                f'- {e["paciente_nombre"]}: {e["error"]}'
                for e in resultado['errores'][:5]
            ])
            messages.warning(request, f'⚠️ Errores encontrados:<br>{errores_msg}')

        logger.info(f"✅ Recálculo completado: {resultado['exitosos']}/{resultado['total']}")

    except Exception as e:
        logger.error(f"❌ Error en recálculo masivo: {str(e)}")
        messages.error(request, f'❌ Error al recalcular cuentas: {str(e)}')

    return redirect('facturacion:panel_recalcular_cuentas')


@staff_member_required
def recalcular_cuenta_individual(request, paciente_id):
    """
    Recalcula una cuenta individual.
    ✅ GET muestra confirmación, POST ejecuta.
    """
    paciente = Paciente.objects.get(id=paciente_id)

    if request.method == 'POST':
        try:
            cuenta = AccountService.update_balance(paciente)

            messages.success(
                request,
                f'✅ Cuenta de {paciente.nombre_completo} recalculada correctamente'
            )

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'mensaje': 'Cuenta recalculada',
                    'data': {
                        'consumido_real':       float(cuenta.total_consumido_real),
                        'consumido_actual':     float(cuenta.total_consumido_actual),
                        'total_pagado':         float(cuenta.total_pagado),
                        'saldo_real':           float(cuenta.saldo_real),
                        'saldo_actual':         float(cuenta.saldo_actual),
                        'ultima_actualizacion': cuenta.ultima_actualizacion.isoformat(),
                    }
                })

        except Exception as e:
            logger.error(f"Error recalculando cuenta de paciente {paciente_id}: {str(e)}")
            messages.error(request, f'❌ Error: {str(e)}')

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': str(e)}, status=400)

        return redirect('facturacion:detalle_cuenta', paciente_id=paciente_id)

    # GET: mostrar confirmación
    try:
        cuenta = CuentaCorriente.objects.get(paciente=paciente)
    except CuentaCorriente.DoesNotExist:
        cuenta = None

    return render(request, 'facturacion/admin/confirmar_recalculo_cuenta.html', {
        'paciente': paciente,
        'cuenta':   cuenta,
    })


@staff_member_required
def api_recalcular_cuenta(request, paciente_id):
    """
    API AJAX para recalcular una cuenta individual.
    ✅ Solo POST, devuelve JSON.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    try:
        paciente = Paciente.objects.get(id=paciente_id)
        cuenta   = AccountService.update_balance(paciente)

        return JsonResponse({
            'success': True,
            'mensaje': f'Cuenta de {paciente.nombre_completo} recalculada',
            'data': {
                'paciente_id':          paciente.id,
                'paciente_nombre':      paciente.nombre_completo,
                'consumido_real':       float(cuenta.total_consumido_real),
                'consumido_actual':     float(cuenta.total_consumido_actual),
                'total_pagado':         float(cuenta.total_pagado),
                'saldo_real':           float(cuenta.saldo_real),
                'saldo_actual':         float(cuenta.saldo_actual),
                'ultima_actualizacion': cuenta.ultima_actualizacion.isoformat(),
            }
        })

    except Paciente.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': f'Paciente {paciente_id} no existe'
        }, status=404)

    except Exception as e:
        logger.error(f"Error en API recalcular cuenta {paciente_id}: {str(e)}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@staff_member_required
def api_estado_recalculo(request):
    """
    API para obtener estadísticas del sistema en tiempo real.
    """
    try:
        stats = {
            'total_cuentas':            CuentaCorriente.objects.count(),
            'total_pacientes':          Paciente.objects.count(),
            'cuentas_con_saldo_negativo': CuentaCorriente.objects.filter(saldo_actual__lt=0).count(),
            'cuentas_sin_actualizar_hoy': CuentaCorriente.objects.filter(
                ultima_actualizacion__date__lt=timezone.now().date()
            ).count(),
        }
        return JsonResponse({'success': True, 'data': stats})

    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)