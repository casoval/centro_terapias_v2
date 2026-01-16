from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.db import transaction
from agenda.models import Sesion
from .models import Pago, CuentaCorriente
import logging

logger = logging.getLogger(__name__)

# ✅ THREAD-LOCAL STORAGE para evitar bucles infinitos
import threading
_thread_locals = threading.local()

def _get_update_lock():
    """Obtener el conjunto de pacientes que están siendo actualizados en este hilo"""
    if not hasattr(_thread_locals, 'updating_pacientes'):
        _thread_locals.updating_pacientes = set()
    return _thread_locals.updating_pacientes


@receiver(post_save, sender=Sesion)
def actualizar_cuenta_al_guardar_sesion(sender, instance, **kwargs):
    """
    Actualizar cuenta corriente cuando se guarda una sesión
    ✅ OPTIMIZADO: Con lock para evitar bucles y solo si cambió algo relevante
    """
    # Solo actualizar si la sesión está en un estado que afecta la cuenta
    if instance.estado not in ['realizada', 'realizada_retraso', 'falta', 'programada']:
        return
    
    paciente_id = instance.paciente_id
    update_lock = _get_update_lock()
    
    # Si ya se está actualizando este paciente en este hilo, salir
    if paciente_id in update_lock:
        return
    
    try:
        update_lock.add(paciente_id)
        
        # Usar transaction.on_commit para evitar conflictos
        transaction.on_commit(lambda: _update_balance_safe(instance.paciente_id))
        
    except Exception as e:
        logger.error(f"Error actualizando cuenta al guardar sesión {instance.id}: {str(e)}")
    finally:
        update_lock.discard(paciente_id)


@receiver(post_delete, sender=Sesion)
def actualizar_cuenta_al_eliminar_sesion(sender, instance, **kwargs):
    """
    Actualizar cuenta corriente cuando se elimina una sesión
    ✅ OPTIMIZADO: Con lock para evitar bucles
    """
    paciente_id = instance.paciente_id
    update_lock = _get_update_lock()
    
    if paciente_id in update_lock:
        return
    
    try:
        update_lock.add(paciente_id)
        transaction.on_commit(lambda: _update_balance_safe(paciente_id))
    except Exception as e:
        logger.error(f"Error actualizando cuenta al eliminar sesión {instance.id}: {str(e)}")
    finally:
        update_lock.discard(paciente_id)


@receiver(post_save, sender=Pago)
def actualizar_cuenta_al_guardar_pago(sender, instance, created, **kwargs):
    """
    Actualizar cuenta corriente cuando se guarda un pago
    ✅ OPTIMIZADO: Solo actualizar si es relevante para el balance
    """
    # No actualizar si es un pago anulado que ya existía anulado
    if not created and instance.anulado:
        return
    
    paciente_id = instance.paciente_id
    update_lock = _get_update_lock()
    
    if paciente_id in update_lock:
        return
    
    try:
        update_lock.add(paciente_id)
        transaction.on_commit(lambda: _update_balance_safe(paciente_id))
    except Exception as e:
        logger.error(f"Error actualizando cuenta al guardar pago {instance.id}: {str(e)}")
    finally:
        update_lock.discard(paciente_id)


@receiver(post_delete, sender=Pago)
def actualizar_cuenta_al_eliminar_pago(sender, instance, **kwargs):
    """
    Actualizar cuenta corriente cuando se elimina un pago
    ✅ OPTIMIZADO: Con lock para evitar bucles
    """
    paciente_id = instance.paciente_id
    update_lock = _get_update_lock()
    
    if paciente_id in update_lock:
        return
    
    try:
        update_lock.add(paciente_id)
        transaction.on_commit(lambda: _update_balance_safe(paciente_id))
    except Exception as e:
        logger.error(f"Error actualizando cuenta al eliminar pago {instance.id}: {str(e)}")
    finally:
        update_lock.discard(paciente_id)


def _update_balance_safe(paciente_id):
    """
    Actualiza el balance de forma segura con manejo de errores
    """
    try:
        from pacientes.models import Paciente
        from .services import AccountService
        
        paciente = Paciente.objects.get(id=paciente_id)
        AccountService.update_balance(paciente)
        
    except Paciente.DoesNotExist:
        logger.warning(f"Paciente {paciente_id} no existe, no se puede actualizar balance")
    except Exception as e:
        logger.error(f"Error actualizando balance para paciente {paciente_id}: {str(e)}")