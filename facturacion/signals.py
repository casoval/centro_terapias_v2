from django.db.models.signals import post_save, post_delete, pre_delete
from django.dispatch import receiver
from agenda.models import Sesion
from .models import Pago, CuentaCorriente


@receiver(post_save, sender=Sesion)
def actualizar_cuenta_al_guardar_sesion(sender, instance, **kwargs):
    """
    Actualizar cuenta corriente cuando se guarda una sesión
    (crear, modificar estado, cambiar monto)
    """
    try:
        cuenta, created = CuentaCorriente.objects.get_or_create(
            paciente=instance.paciente
        )
        cuenta.actualizar_saldo()
    except Exception as e:
        # Log del error pero no fallar
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error actualizando cuenta al guardar sesión {instance.id}: {str(e)}")


@receiver(post_delete, sender=Sesion)
def actualizar_cuenta_al_eliminar_sesion(sender, instance, **kwargs):
    """
    Actualizar cuenta corriente cuando se elimina una sesión
    """
    try:
        cuenta, created = CuentaCorriente.objects.get_or_create(
            paciente=instance.paciente
        )
        cuenta.actualizar_saldo()
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error actualizando cuenta al eliminar sesión {instance.id}: {str(e)}")


@receiver(post_save, sender=Pago)
def actualizar_cuenta_al_guardar_pago(sender, instance, created, **kwargs):
    """
    Actualizar cuenta corriente cuando se guarda un pago
    (crear, modificar, anular)
    """
    try:
        cuenta, created_cuenta = CuentaCorriente.objects.get_or_create(
            paciente=instance.paciente
        )
        cuenta.actualizar_saldo()
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error actualizando cuenta al guardar pago {instance.id}: {str(e)}")


@receiver(post_delete, sender=Pago)
def actualizar_cuenta_al_eliminar_pago(sender, instance, **kwargs):
    """
    Actualizar cuenta corriente cuando se elimina un pago
    """
    try:
        cuenta, created = CuentaCorriente.objects.get_or_create(
            paciente=instance.paciente
        )
        cuenta.actualizar_saldo()
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error actualizando cuenta al eliminar pago {instance.id}: {str(e)}")