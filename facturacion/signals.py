# facturacion/signals.py
# ✅ ACTUALIZADO: Signals para TODOS los modelos que afectan las cuentas corrientes

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.db import transaction
from django.apps import apps
from agenda.models import Sesion
from .models import Pago, CuentaCorriente, Devolucion
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


# ==================== SIGNALS PARA SESIONES ====================

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


# ==================== SIGNALS PARA PAGOS ====================

@receiver(post_save, sender=Pago)
def actualizar_cuenta_al_guardar_pago(sender, instance, created, **kwargs):
    """
    Actualizar cuenta corriente cuando se guarda un pago
    ✅ OPTIMIZADO: Solo actualizar si es relevante para el balance
    """
    # ✅ CAMBIO IMPORTANTE: Ya NO evitamos actualizar cuando se anula un pago
    # La razón: cuando anulas un pago, el total_pagado debe disminuir,
    # pero si no recalculamos, el total_pagado seguirá mostrando el pago anulado.
    # Como el cálculo en AccountService.update_balance() ya filtra por anulado=False,
    # al recalcular automáticamente excluirá los pagos anulados.
    
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


# ==================== SIGNALS PARA DEVOLUCIONES ====================

@receiver(post_save, sender=Devolucion)
def actualizar_cuenta_al_guardar_devolucion(sender, instance, created, **kwargs):
    """
    Actualizar cuenta corriente cuando se guarda una devolución
    """
    paciente_id = instance.paciente_id
    update_lock = _get_update_lock()
    
    if paciente_id in update_lock:
        return
    
    try:
        update_lock.add(paciente_id)
        transaction.on_commit(lambda: _update_balance_safe(paciente_id))
    except Exception as e:
        logger.error(f"Error actualizando cuenta al guardar devolución {instance.id}: {str(e)}")
    finally:
        update_lock.discard(paciente_id)


@receiver(post_delete, sender=Devolucion)
def actualizar_cuenta_al_eliminar_devolucion(sender, instance, **kwargs):
    """
    Actualizar cuenta corriente cuando se elimina una devolución
    """
    paciente_id = instance.paciente_id
    update_lock = _get_update_lock()
    
    if paciente_id in update_lock:
        return
    
    try:
        update_lock.add(paciente_id)
        transaction.on_commit(lambda: _update_balance_safe(paciente_id))
    except Exception as e:
        logger.error(f"Error actualizando cuenta al eliminar devolución {instance.id}: {str(e)}")
    finally:
        update_lock.discard(paciente_id)


# ==================== SIGNALS PARA PROYECTOS ====================
# ✅ CORREGIDO: Solo conectar si la app 'agenda' está instalada

if apps.is_installed('agenda'):
    # Importar Proyecto solo si la app está instalada
    try:
        from agenda.models import Proyecto
        
        @receiver(post_save, sender=Proyecto)
        def actualizar_cuenta_al_guardar_proyecto(sender, instance, **kwargs):
            """
            Actualizar cuenta corriente cuando se guarda un proyecto
            ✅ NUEVO: Asegura que los cambios en proyectos actualicen la cuenta
            """
            paciente_id = instance.paciente_id
            update_lock = _get_update_lock()
            
            if paciente_id in update_lock:
                return
            
            try:
                update_lock.add(paciente_id)
                transaction.on_commit(lambda: _update_balance_safe(paciente_id))
            except Exception as e:
                logger.error(f"Error actualizando cuenta al guardar proyecto {instance.id}: {str(e)}")
            finally:
                update_lock.discard(paciente_id)


        @receiver(post_delete, sender=Proyecto)
        def actualizar_cuenta_al_eliminar_proyecto(sender, instance, **kwargs):
            """
            Actualizar cuenta corriente cuando se elimina un proyecto
            ✅ NUEVO: Asegura que la eliminación de proyectos actualice la cuenta
            """
            paciente_id = instance.paciente_id
            update_lock = _get_update_lock()
            
            if paciente_id in update_lock:
                return
            
            try:
                update_lock.add(paciente_id)
                transaction.on_commit(lambda: _update_balance_safe(paciente_id))
            except Exception as e:
                logger.error(f"Error actualizando cuenta al eliminar proyecto {instance.id}: {str(e)}")
            finally:
                update_lock.discard(paciente_id)
    
    except ImportError:
        logger.warning("No se pudo importar Proyecto desde agenda.models")


# ==================== SIGNALS PARA MENSUALIDADES ====================
# ✅ CORREGIDO: Solo conectar si la app 'agenda' está instalada

if apps.is_installed('agenda'):
    # Importar Mensualidad solo si la app está instalada
    try:
        from agenda.models import Mensualidad
        
        @receiver(post_save, sender=Mensualidad)
        def actualizar_cuenta_al_guardar_mensualidad(sender, instance, **kwargs):
            """
            Actualizar cuenta corriente cuando se guarda una mensualidad
            ✅ NUEVO: Asegura que los cambios en mensualidades actualicen la cuenta
            """
            paciente_id = instance.paciente_id
            update_lock = _get_update_lock()
            
            if paciente_id in update_lock:
                return
            
            try:
                update_lock.add(paciente_id)
                transaction.on_commit(lambda: _update_balance_safe(paciente_id))
            except Exception as e:
                logger.error(f"Error actualizando cuenta al guardar mensualidad {instance.id}: {str(e)}")
            finally:
                update_lock.discard(paciente_id)


        @receiver(post_delete, sender=Mensualidad)
        def actualizar_cuenta_al_eliminar_mensualidad(sender, instance, **kwargs):
            """
            Actualizar cuenta corriente cuando se elimina una mensualidad
            ✅ NUEVO: Asegura que la eliminación de mensualidades actualice la cuenta
            """
            paciente_id = instance.paciente_id
            update_lock = _get_update_lock()
            
            if paciente_id in update_lock:
                return
            
            try:
                update_lock.add(paciente_id)
                transaction.on_commit(lambda: _update_balance_safe(paciente_id))
            except Exception as e:
                logger.error(f"Error actualizando cuenta al eliminar mensualidad {instance.id}: {str(e)}")
            finally:
                update_lock.discard(paciente_id)
    
    except ImportError:
        logger.warning("No se pudo importar Mensualidad desde agenda.models")


# ==================== FUNCIÓN DE ACTUALIZACIÓN SEGURA ====================

def _update_balance_safe(paciente_id):
    """
    Actualiza el balance de forma segura con manejo de errores
    ✅ USA AccountService para el cálculo optimizado
    """
    try:
        from pacientes.models import Paciente
        from .services import AccountService
        
        paciente = Paciente.objects.get(id=paciente_id)
        AccountService.update_balance(paciente)
        
        logger.info(f"✅ Cuenta actualizada para paciente {paciente_id}")
        
    except Paciente.DoesNotExist:
        logger.warning(f"Paciente {paciente_id} no existe, no se puede actualizar balance")
    except Exception as e:
        logger.error(f"Error actualizando balance para paciente {paciente_id}: {str(e)}")