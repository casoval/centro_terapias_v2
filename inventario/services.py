"""
Operaciones de stock centralizadas — para que TODO cambio de cantidad
pase por acá y quede su MovimientoInventario correspondiente. Las views
nunca deben tocar StockInventario.cantidad directamente.
"""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import StockInventario, MovimientoInventario


@transaction.atomic
def agregar_stock(user, titular, item, cantidad, motivo=''):
    """Suma cantidad al stock de un titular. Cualquier staff autorizado puede llamar esto (nunca resta)."""
    if cantidad <= 0:
        raise ValidationError('La cantidad a agregar debe ser mayor a cero.')

    stock, _ = StockInventario.objects.select_for_update().get_or_create(titular=titular, item=item)
    stock.cantidad += cantidad
    stock.save(update_fields=['cantidad', 'fecha_actualizacion'])

    MovimientoInventario.objects.create(
        titular=titular, item=item, tipo='entrada', cantidad=cantidad,
        motivo=motivo, realizado_por=user,
    )
    return stock


@transaction.atomic
def ajustar_stock(admin_user, titular, item, nueva_cantidad, motivo=''):
    """Fija el stock a un valor exacto (admin). Genera un movimiento 'ajuste' con el delta real."""
    if nueva_cantidad < 0:
        raise ValidationError('La cantidad no puede ser negativa.')

    stock, _ = StockInventario.objects.select_for_update().get_or_create(titular=titular, item=item)
    delta = nueva_cantidad - stock.cantidad
    stock.cantidad = nueva_cantidad
    stock.save(update_fields=['cantidad', 'fecha_actualizacion'])

    if delta != 0:
        MovimientoInventario.objects.create(
            titular=titular, item=item, tipo='ajuste', cantidad=delta,
            motivo=motivo or 'Ajuste manual', realizado_por=admin_user,
        )
    return stock


@transaction.atomic
def dar_de_baja(admin_user, titular, item, cantidad, motivo=''):
    """Resta cantidad del stock de un titular (admin). Ej: se rompió, se perdió, etc."""
    if cantidad <= 0:
        raise ValidationError('La cantidad a dar de baja debe ser mayor a cero.')

    stock, _ = StockInventario.objects.select_for_update().get_or_create(titular=titular, item=item)
    if stock.cantidad < cantidad:
        raise ValidationError(f'No hay suficiente stock ({stock.cantidad} disponibles).')

    stock.cantidad -= cantidad
    stock.save(update_fields=['cantidad', 'fecha_actualizacion'])

    MovimientoInventario.objects.create(
        titular=titular, item=item, tipo='baja', cantidad=-cantidad,
        motivo=motivo or 'Baja manual', realizado_por=admin_user,
    )
    return stock
