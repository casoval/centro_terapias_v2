# egresos/signals.py
# Señales para recalcular automáticamente el ResumenFinanciero
# cuando hay cambios en Egreso (app egresos) o en Pago/Devolucion (app facturacion).

import threading
import logging

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

logger = logging.getLogger(__name__)

# ── Threading local para evitar recálculos en cascada ────────────────────────
# Mismo patrón que usa facturacion/signals.py para evitar loops infinitos.
_recalculando = threading.local()


def _is_recalculando():
    return getattr(_recalculando, 'activo', False)


def _set_recalculando(valor):
    _recalculando.activo = valor


# ─────────────────────────────────────────────────────────────────────────────
# SEÑALES DE EGRESO
# ─────────────────────────────────────────────────────────────────────────────

@receiver(post_save, sender='egresos.Egreso')
def recalcular_al_guardar_egreso(sender, instance, **kwargs):
    """
    Recalcula el ResumenFinanciero del período afectado
    cada vez que se guarda (crea o modifica) un Egreso.
    """
    if _is_recalculando():
        return

    try:
        _set_recalculando(True)
        from egresos.services import ResumenFinancieroService
        ResumenFinancieroService.recalcular_mes(
            instance.periodo_mes,
            instance.periodo_anio,
        )
    except Exception as e:
        logger.error(
            f'Error en signal post_save Egreso {instance.numero_egreso}: {e}',
            exc_info=True
        )
    finally:
        _set_recalculando(False)


@receiver(post_delete, sender='egresos.Egreso')
def recalcular_al_eliminar_egreso(sender, instance, **kwargs):
    """
    Recalcula el ResumenFinanciero si se elimina un Egreso.
    (En condiciones normales los egresos se anulan, no se eliminan.
     Esta señal cubre el caso de eliminación directa desde admin.)
    """
    if _is_recalculando():
        return

    try:
        _set_recalculando(True)
        from egresos.services import ResumenFinancieroService
        ResumenFinancieroService.recalcular_mes(
            instance.periodo_mes,
            instance.periodo_anio,
        )
    except Exception as e:
        logger.error(
            f'Error en signal post_delete Egreso {instance.numero_egreso}: {e}',
            exc_info=True
        )
    finally:
        _set_recalculando(False)


# ─────────────────────────────────────────────────────────────────────────────
# SEÑALES DE PAGO Y DEVOLUCIÓN (de la app facturacion)
# Cuando entra dinero o se devuelve, el ingreso del mes cambia
# → hay que recalcular el ResumenFinanciero de ese mes.
# ─────────────────────────────────────────────────────────────────────────────

@receiver(post_save, sender='facturacion.Pago')
def recalcular_al_guardar_pago(sender, instance, **kwargs):
    """
    Recalcula el ResumenFinanciero del mes del pago.
    Se dispara al registrar un nuevo pago o al anularlo.
    """
    if _is_recalculando():
        return

    try:
        _set_recalculando(True)
        from egresos.services import ResumenFinancieroService
        ResumenFinancieroService.recalcular_mes(
            instance.fecha_pago.month,
            instance.fecha_pago.year,
        )
    except Exception as e:
        logger.error(
            f'Error en signal post_save Pago {getattr(instance, "numero_recibo", instance.pk)}: {e}',
            exc_info=True
        )
    finally:
        _set_recalculando(False)


@receiver(post_save, sender='facturacion.Devolucion')
def recalcular_al_guardar_devolucion(sender, instance, **kwargs):
    """
    Recalcula el ResumenFinanciero del mes de la devolución.
    """
    if _is_recalculando():
        return

    try:
        _set_recalculando(True)
        from egresos.services import ResumenFinancieroService
        ResumenFinancieroService.recalcular_mes(
            instance.fecha_devolucion.month,
            instance.fecha_devolucion.year,
        )
    except Exception as e:
        logger.error(
            f'Error en signal post_save Devolucion '
            f'{getattr(instance, "numero_devolucion", instance.pk)}: {e}',
            exc_info=True
        )
    finally:
        _set_recalculando(False)