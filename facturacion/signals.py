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


# ==================== SUPRESIÓN DE RECÁLCULOS REDUNDANTES EN LOTE ====================
# ⚡ OPTIMIZACIÓN: al agendar sesiones recurrentes / patrón semanal, el código
# guarda hasta decenas de objetos Sesion en un mismo request, uno por uno
# (no se puede usar bulk_create: cada fecha se valida individualmente y
# algunas pueden fallar sin afectar a las demás — es un comportamiento
# intencional que hay que preservar). Sin este mecanismo, cada .save()
# individual dispara una recalculación COMPLETA de la cuenta corriente
# (~30 queries), multiplicando el costo por N sesiones del lote — confirmado
# en producción: dos recálculos para el mismo paciente a 37ms de diferencia
# en los logs. Con SuprimirRecalculoBalance, todo el lote se agenda con la
# recalculación real desactivada, y se ejecuta UNA sola vez al salir del
# bloque, reflejando el resultado final del lote completo (incluso si
# algunas fechas individuales fallaron). No cambia CÓMO se calcula el
# balance (AccountService.update_balance no se toca), solo CUÁNDO corre.
#
# Es un mecanismo independiente del _get_update_lock() de arriba (que sigue
# funcionando exactamente igual que antes, sin cambios) — para no arriesgar
# modificar la protección anti-bucles-infinitos que ya existe.
_recalculo_suprimido = threading.local()


def _paciente_con_recalculo_suprimido(paciente_id):
    ids = getattr(_recalculo_suprimido, 'ids', None)
    return ids is not None and paciente_id in ids


class SuprimirRecalculoBalance:
    """
    Context manager: agrupa múltiples guardados de Sesion del MISMO paciente
    en una sola recalculación de cuenta corriente al salir del bloque, en
    vez de una por cada .save() individual dentro de él.

    Uso:
        with SuprimirRecalculoBalance(paciente.id):
            for fecha in fechas:
                sesion = Sesion(...)
                sesion.save()   # no dispara recálculo individual aquí
        # Al salir del bloque: se recalcula UNA sola vez.

    Seguro de anidar o de usar más de una vez para el mismo paciente_id en
    el mismo hilo: solo se recalcula al salir del bloque MÁS EXTERNO.
    También recalcula si el bloque termina por una excepción, para reflejar
    lo que sí se alcanzó a guardar antes del error.
    """

    def __init__(self, *paciente_ids):
        self.paciente_ids = {pid for pid in paciente_ids if pid}

    def __enter__(self):
        ids = getattr(_recalculo_suprimido, 'ids', None)
        if ids is None:
            ids = set()
            _recalculo_suprimido.ids = ids
        # Solo nos hacemos responsables de recalcular los que ESTE bloque
        # agrega — si un bloque externo ya los tenía suprimidos, que sea
        # ese el que recalcule al salir.
        self._agregados_por_mi = self.paciente_ids - ids
        ids.update(self.paciente_ids)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        ids = getattr(_recalculo_suprimido, 'ids', set())
        for pid in self._agregados_por_mi:
            ids.discard(pid)

        if self._agregados_por_mi:
            from pacientes.models import Paciente
            from .services import AccountService
            for pid in self._agregados_por_mi:
                try:
                    paciente = Paciente.objects.get(id=pid)
                    AccountService.update_balance(paciente)
                except Exception as e:
                    logger.warning(
                        f"No se pudo recalcular balance tras lote para paciente {pid}: {e}"
                    )
        return False  # nunca suprime la excepción original del bloque


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

    # ⚡ Si estamos dentro de un bloque SuprimirRecalculoBalance para este
    # paciente (agendamiento en lote), no recalculamos aquí — se hace UNA
    # sola vez al salir del bloque. Ver SuprimirRecalculoBalance más arriba.
    if _paciente_con_recalculo_suprimido(paciente_id):
        return

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

    if _paciente_con_recalculo_suprimido(paciente_id):
        return

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