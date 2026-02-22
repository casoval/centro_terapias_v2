# facturacion/services.py
# ✅ CORREGIDO: Cálculo de total_pagado sin duplicar pagos adelantados

from decimal import Decimal
from django.db.models import Sum, Count, Q, F
from django.db.models.functions import Coalesce
from django.db import transaction
from django.core.exceptions import ValidationError
import logging

logger = logging.getLogger(__name__)


class AccountService:
    """
    Servicio para gestionar cuentas corrientes de pacientes
    ✅ OPTIMIZADO: Calcula todos los campos en un solo proceso
    """
    
    @staticmethod
    @transaction.atomic
    def update_balance(paciente):
        """
        Actualiza TODOS los campos calculados de la cuenta corriente del paciente
        
        Args:
            paciente: Instancia del modelo Paciente
        
        Returns:
            CuentaCorriente: Instancia actualizada
        """
        from facturacion.models import CuentaCorriente, Pago, Devolucion
        from agenda.models import Sesion, Proyecto, Mensualidad
        
        # Obtener o crear cuenta
        cuenta, created = CuentaCorriente.objects.get_or_create(
            paciente=paciente
        )
        # BUG 2 FIX: lock a nivel de BD para que Workers simultáneos de
        # Gunicorn/uWSGI no pisen el cálculo del otro. select_for_update()
        # bloquea la fila en PostgreSQL hasta que esta transacción termine.
        # threading.local() en signals.py solo protege dentro del mismo proceso,
        # no entre procesos. Este lock sí funciona entre todos los workers.
        cuenta = CuentaCorriente.objects.select_for_update().get(id=cuenta.id)
        
        # ========================================
        # 1. CALCULAR CONSUMIDO
        # ========================================
        
        # 1.1 Sesiones Normales Realizadas (estados con costo ya generado)
        sesiones_realizadas_stats = Sesion.objects.filter(
            paciente=paciente,
            proyecto__isnull=True,  # Solo sesiones normales
            mensualidad__isnull=True,  # Solo sesiones normales
            estado__in=['realizada', 'realizada_retraso', 'falta']
        ).aggregate(
            total=Coalesce(Sum('monto_cobrado'), Decimal('0')),
            count_pendientes=Count(
                'id',
                filter=Q(
                    # Sesiones que tienen saldo pendiente
                    monto_cobrado__gt=0
                ) & ~Q(
                    # Excluir las que están completamente pagadas
                    id__in=Sesion.objects.filter(
                        paciente=paciente,
                        proyecto__isnull=True,
                        mensualidad__isnull=True,
                        estado__in=['realizada', 'realizada_retraso', 'falta']
                    ).annotate(
                        pagado=Coalesce(
                            Sum('pagos__monto', filter=Q(pagos__anulado=False)),
                            Decimal('0')
                        )
                    ).filter(
                        pagado__gte=F('monto_cobrado')
                    ).values_list('id', flat=True)
                )
            )
        )
        
        cuenta.total_sesiones_normales_real = sesiones_realizadas_stats['total']
        cuenta.num_sesiones_realizadas_pendientes = sesiones_realizadas_stats['count_pendientes']
        
        # 1.2 Sesiones Programadas (compromiso futuro)
        sesiones_programadas_stats = Sesion.objects.filter(
            paciente=paciente,
            proyecto__isnull=True,
            mensualidad__isnull=True,
            estado='programada'
        ).aggregate(
            total=Coalesce(Sum('monto_cobrado'), Decimal('0')),
            count_pendientes=Count(
                'id',
                filter=Q(monto_cobrado__gt=0)
            )
        )
        
        cuenta.total_sesiones_programadas = sesiones_programadas_stats['total']
        cuenta.num_sesiones_programadas_pendientes = sesiones_programadas_stats['count_pendientes']
        
        # 1.3 Mensualidades (activas/pausadas/completadas/canceladas)
        # ✅ MODIFICADO: Ahora incluye canceladas
        mensualidades_stats = Mensualidad.objects.filter(
            paciente=paciente,
            estado__in=['activa', 'pausada', 'completada', 'cancelada']
        ).aggregate(
            total=Coalesce(Sum('costo_mensual'), Decimal('0')),
            count_activas=Count('id', filter=Q(estado='activa'))
        )
        
        cuenta.total_mensualidades = mensualidades_stats['total']
        cuenta.num_mensualidades_activas = mensualidades_stats['count_activas']
        
        # 1.4 Proyectos en Progreso/Finalizados/Cancelados
        # ✅ MODIFICADO: Ahora incluye cancelados
        proyectos_reales_stats = Proyecto.objects.filter(
            paciente=paciente,
            estado__in=['en_progreso', 'finalizado', 'cancelado']
        ).aggregate(
            total=Coalesce(Sum('costo_total'), Decimal('0'))
        )
        
        cuenta.total_proyectos_real = proyectos_reales_stats['total']
        
        # 1.5 Proyectos Planificados (compromiso futuro)
        proyectos_planificados_stats = Proyecto.objects.filter(
            paciente=paciente,
            estado='planificado'
        ).aggregate(
            total=Coalesce(Sum('costo_total'), Decimal('0'))
        )
        
        cuenta.total_proyectos_planificados = proyectos_planificados_stats['total']
        
        # 1.6 Contador de Proyectos Activos
        cuenta.num_proyectos_activos = Proyecto.objects.filter(
            paciente=paciente,
            estado__in=['planificado', 'en_progreso']
        ).count()
        
        # ========================================
        # 2. CALCULAR TOTALES CONSUMIDOS
        # ========================================
        
        # 2.1 Total Consumido Real (incluye todo)
        cuenta.total_consumido_real = (
            cuenta.total_sesiones_normales_real +
            cuenta.total_sesiones_programadas +
            cuenta.total_mensualidades +
            cuenta.total_proyectos_real +
            cuenta.total_proyectos_planificados
        )
        
        # 2.2 Total Consumido Actual (sin programadas ni planificadas)
        cuenta.total_consumido_actual = (
            cuenta.total_sesiones_normales_real +
            cuenta.total_mensualidades +
            cuenta.total_proyectos_real
        )
        
        # ========================================
        # 3. CALCULAR PAGOS
        # ========================================
        # ✅ NOTA SOBRE PAGOS MASIVOS:
        # Un pago masivo crea un único registro Pago con sesion=None, proyecto=None,
        # mensualidad=None. Los ítems reales viven en DetallePagoMasivo.
        # Por eso cada categoría suma DOS fuentes:
        #   a) Pagos directos (FK en Pago apunta a la entidad)
        #   b) Detalles masivos (FK en DetallePagoMasivo apunta a la entidad,
        #      tomando el monto proporcional desde DetallePagoMasivo.monto
        #      del Pago padre no anulado)
        from .models import DetallePagoMasivo
        
        # 3.1 Pagos a Sesiones (incluye programadas y realizadas)
        # a) Pagos directos a sesiones
        pagos_sesiones_directos = Pago.objects.filter(
            paciente=paciente,
            sesion__isnull=False,
            anulado=False
        ).exclude(
            metodo_pago__nombre="Uso de Crédito"
        ).aggregate(total=Coalesce(Sum('monto'), Decimal('0')))['total']

        # b) Detalles masivos de tipo sesión (cuyo pago padre no está anulado)
        pagos_sesiones_masivos = DetallePagoMasivo.objects.filter(
            pago__paciente=paciente,
            pago__anulado=False,
            tipo='sesion',
        ).exclude(
            pago__metodo_pago__nombre="Uso de Crédito"
        ).aggregate(total=Coalesce(Sum('monto'), Decimal('0')))['total']

        pagos_sesiones = pagos_sesiones_directos + pagos_sesiones_masivos
        cuenta.pagos_sesiones = pagos_sesiones

        # ✅ Cálculo de Pagos a Sesiones con CRÉDITO
        pagos_sesiones_credito_directos = Pago.objects.filter(
            paciente=paciente,
            sesion__isnull=False,
            anulado=False,
            metodo_pago__nombre="Uso de Crédito"
        ).aggregate(total=Coalesce(Sum('monto'), Decimal('0')))['total']

        pagos_sesiones_credito_masivos = DetallePagoMasivo.objects.filter(
            pago__paciente=paciente,
            pago__anulado=False,
            pago__metodo_pago__nombre="Uso de Crédito",
            tipo='sesion',
        ).aggregate(total=Coalesce(Sum('monto'), Decimal('0')))['total']

        pagos_sesiones_credito = pagos_sesiones_credito_directos + pagos_sesiones_credito_masivos
        cuenta.pagos_sesiones_credito = pagos_sesiones_credito
        
        # 3.2 Pagos a Mensualidades
        # a) Pagos directos a mensualidades
        pagos_mensualidades_directos = Pago.objects.filter(
            paciente=paciente,
            mensualidad__isnull=False,
            anulado=False
        ).exclude(
            metodo_pago__nombre="Uso de Crédito"
        ).aggregate(total=Coalesce(Sum('monto'), Decimal('0')))['total']

        # b) Detalles masivos de tipo mensualidad
        pagos_mensualidades_masivos = DetallePagoMasivo.objects.filter(
            pago__paciente=paciente,
            pago__anulado=False,
            tipo='mensualidad',
        ).exclude(
            pago__metodo_pago__nombre="Uso de Crédito"
        ).aggregate(total=Coalesce(Sum('monto'), Decimal('0')))['total']

        pagos_mensualidades = pagos_mensualidades_directos + pagos_mensualidades_masivos
        cuenta.pagos_mensualidades = pagos_mensualidades

        # ✅ Cálculo de Pagos a Mensualidades con CRÉDITO
        pagos_mensualidades_credito_directos = Pago.objects.filter(
            paciente=paciente,
            mensualidad__isnull=False,
            anulado=False,
            metodo_pago__nombre="Uso de Crédito"
        ).aggregate(total=Coalesce(Sum('monto'), Decimal('0')))['total']

        pagos_mensualidades_credito_masivos = DetallePagoMasivo.objects.filter(
            pago__paciente=paciente,
            pago__anulado=False,
            pago__metodo_pago__nombre="Uso de Crédito",
            tipo='mensualidad',
        ).aggregate(total=Coalesce(Sum('monto'), Decimal('0')))['total']

        pagos_mensualidades_credito = pagos_mensualidades_credito_directos + pagos_mensualidades_credito_masivos
        cuenta.pagos_mensualidades_credito = pagos_mensualidades_credito
        
        # 3.3 Pagos a Proyectos
        # a) Pagos directos a proyectos
        pagos_proyectos_directos = Pago.objects.filter(
            paciente=paciente,
            proyecto__isnull=False,
            anulado=False
        ).exclude(
            metodo_pago__nombre="Uso de Crédito"
        ).aggregate(total=Coalesce(Sum('monto'), Decimal('0')))['total']

        # b) Detalles masivos de tipo proyecto
        pagos_proyectos_masivos = DetallePagoMasivo.objects.filter(
            pago__paciente=paciente,
            pago__anulado=False,
            tipo='proyecto',
        ).exclude(
            pago__metodo_pago__nombre="Uso de Crédito"
        ).aggregate(total=Coalesce(Sum('monto'), Decimal('0')))['total']

        pagos_proyectos = pagos_proyectos_directos + pagos_proyectos_masivos
        cuenta.pagos_proyectos = pagos_proyectos

        # ✅ Cálculo de Pagos a Proyectos con CRÉDITO
        pagos_proyectos_credito_directos = Pago.objects.filter(
            paciente=paciente,
            proyecto__isnull=False,
            anulado=False,
            metodo_pago__nombre="Uso de Crédito"
        ).aggregate(total=Coalesce(Sum('monto'), Decimal('0')))['total']

        pagos_proyectos_credito_masivos = DetallePagoMasivo.objects.filter(
            pago__paciente=paciente,
            pago__anulado=False,
            pago__metodo_pago__nombre="Uso de Crédito",
            tipo='proyecto',
        ).aggregate(total=Coalesce(Sum('monto'), Decimal('0')))['total']

        pagos_proyectos_credito = pagos_proyectos_credito_directos + pagos_proyectos_credito_masivos
        cuenta.pagos_proyectos_credito = pagos_proyectos_credito

        # 3.4 Pagos Adelantados (CRÉDITO DISPONIBLE)
        # ========================================
        # ⚠️ IMPORTANTE: El crédito disponible es SOLO el dinero que NO está comprometido
        # NO incluye pagos a sesiones programadas ni proyectos planificados
        # porque esos pagos ya están asignados a servicios específicos
        # ========================================
        
        # ✅ 3.4.0 PRIMERO calcular las devoluciones
        total_devoluciones = Devolucion.objects.filter(
            paciente=paciente
        ).aggregate(total=Coalesce(Sum('monto'), Decimal('0')))['total']
        
        cuenta.total_devoluciones = total_devoluciones
        
        # 3.4.1 Pagos sin asignar (VERDADERO crédito disponible)
        # Son pagos que NO están vinculados a ninguna sesión, proyecto o mensualidad
        # ✅ CORREGIDO: Los pagos masivos (sesion/proyecto/mensualidad=None) tienen sus
        # ítems en DetallePagoMasivo, por lo que NO deben contarse aquí como crédito libre.
        # Se excluyen usando detalles_masivos__isnull=False.
        pagos_sin_asignar = Pago.objects.filter(
            paciente=paciente,
            sesion__isnull=True,
            mensualidad__isnull=True,
            proyecto__isnull=True,
            anulado=False
        ).exclude(
            metodo_pago__nombre="Uso de Crédito"  # ❌ No contar "Uso de Crédito" como pago
        ).exclude(
            detalles_masivos__isnull=False  # ❌ No contar pagos masivos (sus ítems ya clasificados arriba)
        ).aggregate(total=Coalesce(Sum('monto'), Decimal('0')))['total']
        
        cuenta.pagos_sin_asignar = pagos_sin_asignar  # ✅ Guardar en BD
        
        # 3.4.2 Pagos a sesiones programadas (SOLO para referencia, NO son crédito libre)
        # ⚠️ Estos pagos están COMPROMETIDOS a sesiones específicas
        # a) Pagos directos a sesiones programadas
        pagos_sesiones_prog_directos = Pago.objects.filter(
            paciente=paciente,
            sesion__estado='programada',
            anulado=False
        ).exclude(
            metodo_pago__nombre="Uso de Crédito"
        ).aggregate(total=Coalesce(Sum('monto'), Decimal('0')))['total']

        # b) Detalles masivos que apuntan a sesiones programadas
        pagos_sesiones_prog_masivos = DetallePagoMasivo.objects.filter(
            pago__paciente=paciente,
            pago__anulado=False,
            tipo='sesion',
            sesion__estado='programada',
        ).exclude(
            pago__metodo_pago__nombre="Uso de Crédito"
        ).aggregate(total=Coalesce(Sum('monto'), Decimal('0')))['total']

        pagos_sesiones_programadas = pagos_sesiones_prog_directos + pagos_sesiones_prog_masivos
        cuenta.pagos_sesiones_programadas = pagos_sesiones_programadas  # ✅ Guardar en BD
        
        # 3.4.3 Pagos a proyectos planificados (SOLO para referencia, NO son crédito libre)
        # ⚠️ Estos pagos están COMPROMETIDOS a proyectos específicos
        # a) Pagos directos a proyectos planificados
        pagos_proy_plan_directos = Pago.objects.filter(
            paciente=paciente,
            proyecto__estado='planificado',
            anulado=False
        ).exclude(
            metodo_pago__nombre="Uso de Crédito"
        ).aggregate(total=Coalesce(Sum('monto'), Decimal('0')))['total']

        # b) Detalles masivos que apuntan a proyectos planificados
        pagos_proy_plan_masivos = DetallePagoMasivo.objects.filter(
            pago__paciente=paciente,
            pago__anulado=False,
            tipo='proyecto',
            proyecto__estado='planificado',
        ).exclude(
            pago__metodo_pago__nombre="Uso de Crédito"
        ).aggregate(total=Coalesce(Sum('monto'), Decimal('0')))['total']

        pagos_proyectos_planificados = pagos_proy_plan_directos + pagos_proy_plan_masivos
        cuenta.pagos_proyectos_planificados = pagos_proyectos_planificados  # ✅ Guardar en BD
        
        # 3.4.4 Uso de Crédito (pagos con método "Uso de Crédito")
        uso_credito = Pago.objects.filter(
            paciente=paciente,
            metodo_pago__nombre="Uso de Crédito",
            anulado=False
        ).aggregate(total=Coalesce(Sum('monto'), Decimal('0')))['total']
        
        cuenta.uso_credito = uso_credito  # ✅ Guardar en BD
        
        # ✅ 3.4.5 CORREGIDO: Calcular devoluciones
        # Solo las devoluciones de crédito general (no de sesiones/proyectos específicos)
        devoluciones_credito = Devolucion.objects.filter(
            paciente=paciente,
            proyecto__isnull=True,
            mensualidad__isnull=True
        ).aggregate(total=Coalesce(Sum('monto'), Decimal('0')))['total']
        
        # ✅ 3.4.6 CORREGIDO: Crédito disponible = SOLO pagos sin asignar - Uso - Devoluciones
        # ⚠️ NO incluimos pagos a sesiones programadas ni proyectos planificados
        # porque esos pagos están comprometidos a servicios específicos
        credito_disponible_calculado = (
            pagos_sin_asignar -      # Solo pagos adelantados puros (sin asignar)
            uso_credito -            # Menos lo que ya se usó de crédito
            devoluciones_credito     # Menos devoluciones de crédito general
        )
        
        # Guardar en el campo pagos_adelantados (representa crédito disponible REAL)
        cuenta.pagos_adelantados = credito_disponible_calculado
        
        # ========================================
        # ✅ 3.5 CORREGIDO: Total Pagado (SIN DUPLICAR ADELANTADOS)
        # ========================================
        # ANTES (INCORRECTO):
        #   total_pagado = pagos_sesiones + pagos_mensualidades + pagos_proyectos + total_pagos_adelantados - devoluciones
        #   Esto sumaba 2 veces los pagos adelantados porque:
        #   - pagos_sesiones YA incluye pagos a sesiones programadas
        #   - pagos_proyectos YA incluye pagos a proyectos planificados
        #   - Y luego se sumaba total_pagos_adelantados de nuevo
        #
        # AHORA (CORRECTO):
        #   total_pagado = TODOS los pagos con recibo (sin importar a qué están asignados) - devoluciones
        cuenta.total_pagado = (
            pagos_sesiones +        # Incluye pagos a sesiones (programadas y realizadas)
            pagos_mensualidades +   # Incluye pagos a mensualidades
            pagos_proyectos +       # Incluye pagos a proyectos (planificados y en progreso)
            pagos_sin_asignar -     # Solo pagos adelantados puros (sin asignar)
            total_devoluciones      # Restar TODAS las devoluciones del total pagado
        )
        # ⚠️ NOTA: No sumamos total_pagos_adelantados porque ya está incluido en:
        #    - pagos_sesiones (incluye sesiones programadas)
        #    - pagos_proyectos (incluye proyectos planificados)
        #    Solo sumamos pagos_sin_asignar (lo que NO está en las anteriores)
        
        # ========================================
        # 4. CALCULAR SALDOS
        # ========================================
        
        # 4.1 Saldo Real (con todos los compromisos)
        # Saldo positivo = a favor del paciente (pagó más de lo que consumió)
        # Saldo negativo = debe el paciente (consumió más de lo que pagó)
        cuenta.saldo_real = cuenta.total_pagado - cuenta.total_consumido_real
        
        # 4.2 Saldo Actual (solo lo ya ocurrido)
        # Este incluye pagos a sesiones programadas que aún no se realizaron
        cuenta.saldo_actual = cuenta.total_pagado - cuenta.total_consumido_actual
        
        # ========================================
        # 4.3 NOTA IMPORTANTE: Saldo Actual vs Crédito Disponible
        # ========================================
        # ANTES: saldo_actual == pagos_adelantados (eran equivalentes)
        # AHORA: Son conceptos DIFERENTES:
        #
        # - SALDO ACTUAL: Incluye todos los pagos (incluso los comprometidos a sesiones/proyectos futuros)
        #   Ejemplo: Si pagaste 100 Bs a una sesión programada, el saldo_actual refleja ese pago
        #
        # - CRÉDITO DISPONIBLE: SOLO dinero libre que puede usarse en cualquier servicio
        #   Ejemplo: El pago de 100 Bs a sesión programada NO está disponible como crédito libre
        #
        # Esto está CORRECTO porque:
        # - El saldo_actual muestra la situación financiera general
        # - El crédito_disponible muestra solo el dinero NO comprometido
        
        # ========================================
        # 5. GUARDAR CAMBIOS
        # ========================================
        
        cuenta.save()
        
        logger.info(
            f"💰 Cuenta actualizada para {paciente}:\n"
            f"   Consumido Actual: Bs.{cuenta.total_consumido_actual}\n"
            f"   Total Pagado: Bs.{cuenta.total_pagado}\n"
            f"   Saldo Actual: Bs.{cuenta.saldo_actual}\n"
            f"   Crédito Disponible: Bs.{cuenta.pagos_adelantados}"
        )
        
        return cuenta

    @staticmethod
    def recalcular_todas_las_cuentas():
        """
        Recalcula las cuentas de TODOS los pacientes del sistema.
        Utilizado por el comando manage.py recalcular_cuentas --all
        """
        from pacientes.models import Paciente
        
        pacientes = Paciente.objects.all()
        total = pacientes.count()
        exitosos = 0
        errores = []
        
        logger.info(f"🔄 Iniciando recálculo masivo de {total} cuentas...")
        
        for paciente in pacientes:
            try:
                # Llamamos a update_balance para cada paciente
                AccountService.update_balance(paciente)
                exitosos += 1
            except Exception as e:
                # Capturamos errores para el reporte final
                error_msg = str(e)
                logger.error(f"❌ Error recalculando paciente {paciente.id}: {error_msg}")
                errores.append({
                    'paciente_id': paciente.id,
                    'paciente_nombre': str(paciente),
                    'error': error_msg
                })
        
        # Retornamos el diccionario que espera el comando recalcular_cuentas.py
        return {
            'total': total,
            'exitosos': exitosos,
            'errores': errores
        }
    
    @staticmethod
    @transaction.atomic
    def process_payment(user, paciente, monto_total, metodo_pago_id, fecha_pago,
                       tipo_pago, referencia_id=None, usar_credito=False,
                       monto_credito=0, es_pago_completo=False, observaciones='', numero_transaccion=''):
        """
        Procesa un pago (efectivo + opcional crédito) para sesión/proyecto/mensualidad/adelantado
        
        Args:
            user: Usuario que registra el pago
            paciente: Instancia del Paciente
            monto_total: Monto total a pagar
            metodo_pago_id: ID del método de pago principal
            fecha_pago: Fecha del pago
            tipo_pago: 'sesion', 'proyecto', 'mensualidad', 'adelantado'
            referencia_id: ID de la sesión/proyecto/mensualidad (None si es adelantado)
            usar_credito: Boolean - si se usa crédito disponible
            monto_credito: Monto a pagar con crédito
            es_pago_completo: Si es True, ajusta el monto_cobrado al total pagado
            observaciones: Texto opcional
            numero_transaccion: Número de transacción opcional
            
        Returns:
            dict con 'success', 'mensaje', 'recibos', 'monto_total', 'pago_efectivo', 'pago_credito'
        """
        from facturacion.models import Pago, MetodoPago, CuentaCorriente
        from agenda.models import Sesion, Proyecto, Mensualidad
        
        # Validaciones básicas
        # ✅ PERMITIR monto 0 para casos especiales (becas, cortesías, razones sociales)
        if monto_total < 0:
            raise ValidationError('El monto total no puede ser negativo')
        
        if usar_credito and monto_credito <= 0:
            raise ValidationError('Si usa crédito, debe especificar un monto válido')
        
        if usar_credito and monto_credito > monto_total:
            raise ValidationError('El monto de crédito no puede ser mayor al monto total')
        
        # Calcular monto en efectivo
        # DEFENSA Bug 4: si usar_credito=False, no restar credito aunque monto_credito tenga valor.
        # Esto protege el servicio ante llamadas directas con datos inconsistentes.
        monto_efectivo = monto_total - (monto_credito if usar_credito else 0)
        
        if monto_efectivo < 0:
            raise ValidationError('El monto en efectivo no puede ser negativo')
        
        # Verificar crédito disponible
        if usar_credito:
            cuenta, _ = CuentaCorriente.objects.get_or_create(paciente=paciente)
            if monto_credito > cuenta.pagos_adelantados:
                raise ValidationError(
                    f'Crédito insuficiente. Disponible: Bs.{cuenta.pagos_adelantados}, '
                    f'Solicitado: Bs.{monto_credito}'
                )
        
        # Obtener referencia según tipo
        sesion = None
        proyecto = None
        mensualidad = None
        
        if tipo_pago == 'sesion':
            if not referencia_id:
                raise ValidationError('Debe especificar la sesión')
            sesion = Sesion.objects.get(id=referencia_id)
            
        elif tipo_pago == 'proyecto':
            if not referencia_id:
                raise ValidationError('Debe especificar el proyecto')
            proyecto = Proyecto.objects.get(id=referencia_id)
            
        elif tipo_pago == 'mensualidad':
            if not referencia_id:
                raise ValidationError('Debe especificar la mensualidad')
            mensualidad = Mensualidad.objects.get(id=referencia_id)
            
        elif tipo_pago == 'adelantado':
            pass  # No requiere referencia
            
        else:
            raise ValidationError('Tipo de pago no válido')
        
        # ✅ CORREGIDO: Obtener método de pago solo si se va a usar
        # (cuando hay monto en efectivo O cuando es pago completo de 0)
        metodo_pago = None
        if monto_efectivo > 0 or (monto_efectivo == 0 and es_pago_completo and monto_total == 0):
            if not metodo_pago_id:
                raise ValidationError('Debe seleccionar un método de pago')
            metodo_pago = MetodoPago.objects.get(id=metodo_pago_id)
        
        # Lista de recibos generados
        recibos = []
        pago_efectivo = None
        pago_credito = None
        
        # ✅ MODIFICADO: Permitir crear pago de 0 si es_pago_completo=True (becas, condonaciones)
        # 1. Crear pago en efectivo (si hay monto O si es pago completo de 0)
        if monto_efectivo > 0 or (monto_efectivo == 0 and es_pago_completo and monto_total == 0):
            concepto = f"Pago {tipo_pago}"
            if sesion:
                concepto = f"Pago sesión {sesion.fecha}" if monto_efectivo > 0 else f"Sesión sin cobro - {sesion.fecha}"
            elif proyecto:
                concepto = f"Pago proyecto {proyecto.nombre}" if monto_efectivo > 0 else f"Proyecto sin cobro - {proyecto.nombre}"
            elif mensualidad:
                # ✅ CORREGIDO: Mensualidad tiene servicios many-to-many
                servicios = mensualidad.servicios_profesionales.select_related('servicio').all()
                if servicios.exists():
                    primer_servicio = servicios.first().servicio.nombre
                    if servicios.count() > 1:
                        if monto_efectivo > 0:
                            concepto = f"Pago mensualidad {primer_servicio} (+{servicios.count()-1} más)"
                        else:
                            concepto = f"Mensualidad sin cobro - {primer_servicio} (+{servicios.count()-1} más)"
                    else:
                        if monto_efectivo > 0:
                            concepto = f"Pago mensualidad {primer_servicio}"
                        else:
                            concepto = f"Mensualidad sin cobro - {primer_servicio}"
                else:
                    if monto_efectivo > 0:
                        concepto = f"Pago mensualidad {mensualidad.periodo_display}"
                    else:
                        concepto = f"Mensualidad sin cobro - {mensualidad.periodo_display}"
            elif tipo_pago == 'adelantado':
                concepto = "Pago adelantado"
            
            pago_efectivo = Pago.objects.create(
                paciente=paciente,
                sesion=sesion,
                proyecto=proyecto,
                mensualidad=mensualidad,
                fecha_pago=fecha_pago,
                monto=monto_efectivo,
                metodo_pago=metodo_pago,
                concepto=concepto,
                observaciones=observaciones if observaciones else ("Beca/Condonación" if monto_efectivo == 0 else ""),
                numero_transaccion=numero_transaccion,
                registrado_por=user
            )
            recibos.append(pago_efectivo.numero_recibo)
        
        # 2. Crear pago con crédito (si se usa)
        if usar_credito and monto_credito > 0:
            metodo_credito = MetodoPago.objects.get(nombre="Uso de Crédito")
            
            concepto_credito = f"Uso de crédito - {tipo_pago}"
            if sesion:
                concepto_credito = f"Uso de crédito - sesión {sesion.fecha}"
            elif proyecto:
                concepto_credito = f"Uso de crédito - proyecto {proyecto.nombre}"
            elif mensualidad:
                # ✅ CORREGIDO: Mensualidad tiene servicios many-to-many
                servicios = mensualidad.servicios_profesionales.select_related('servicio').all()
                if servicios.exists():
                    primer_servicio = servicios.first().servicio.nombre
                    if servicios.count() > 1:
                        concepto_credito = f"Uso de crédito - mensualidad {primer_servicio} (+{servicios.count()-1} más)"
                    else:
                        concepto_credito = f"Uso de crédito - mensualidad {primer_servicio}"
                else:
                    concepto_credito = f"Uso de crédito - mensualidad {mensualidad.periodo_display}"
            
            pago_credito = Pago.objects.create(
                paciente=paciente,
                sesion=sesion,
                proyecto=proyecto,
                mensualidad=mensualidad,
                fecha_pago=fecha_pago,
                monto=monto_credito,
                metodo_pago=metodo_credito,
                concepto=concepto_credito,
                observaciones=f"Uso de crédito. {observaciones}".strip(),
                registrado_por=user
            )
            recibos.append(pago_credito.numero_recibo)
        
        # 3. Ajustar monto_cobrado si es pago completo
        if es_pago_completo:
            if sesion:
                # Calcular total pagado para esta sesión
                total_pagado = Pago.objects.filter(
                    sesion=sesion,
                    anulado=False
                ).aggregate(total=Sum('monto'))['total'] or Decimal('0')
                
                
                # ✅ CORREGIDO: Ajustar monto_cobrado al total pagado
                # Si es pago de 0 (Sin Cobro), condona la deuda restante
                if monto_total == 0:
                    # Pago sin cobro: ajustar el monto_cobrado al total pagado hasta ahora
                    # Ejemplos:
                    # - Si costo era 50 y se pagó 25, ahora monto_cobrado = 25 (condona 25)
                    # - Si costo era 50 y no se pagó nada, ahora monto_cobrado = 0 (todo gratis)
                    # ✅ Guardar monto original solo la primera vez que se ajusta
                    if sesion.monto_original is None:
                        sesion.monto_original = sesion.monto_cobrado
                    sesion.monto_cobrado = total_pagado
                    sesion.save()
                else:
                    # Pago normal: solo ajustar monto_cobrado
                    if sesion.monto_cobrado != total_pagado:
                        # ✅ Guardar monto original solo la primera vez que se ajusta
                        if sesion.monto_original is None:
                            sesion.monto_original = sesion.monto_cobrado
                        sesion.monto_cobrado = total_pagado
                        sesion.save()
            
            elif proyecto:
                total_pagado = Pago.objects.filter(
                    proyecto=proyecto,
                    anulado=False
                ).aggregate(total=Sum('monto'))['total'] or Decimal('0')
                
                if proyecto.costo_total != total_pagado:
                    # ✅ Guardar precio original solo la primera vez que se ajusta (solo informativo)
                    if proyecto.costo_original is None:
                        proyecto.costo_original = proyecto.costo_total
                    proyecto.costo_total = total_pagado
                    proyecto.save()
            
            elif mensualidad:
                total_pagado = Pago.objects.filter(
                    mensualidad=mensualidad,
                    anulado=False
                ).aggregate(total=Sum('monto'))['total'] or Decimal('0')
                
                if mensualidad.costo_mensual != total_pagado:
                    # ✅ Guardar precio original solo la primera vez que se ajusta (solo informativo)
                    if mensualidad.costo_original is None:
                        mensualidad.costo_original = mensualidad.costo_mensual
                    mensualidad.costo_mensual = total_pagado
                    mensualidad.save()
        
        # 4. Actualizar cuenta corriente
        AccountService.update_balance(paciente)
        
        # ✅ Mensaje personalizado según el monto
        if monto_total == 0:
            mensaje = "Sesión registrada sin cobro (beca/cortesía/razón social)"
        else:
            mensaje = f"Pago registrado exitosamente. Total: Bs.{monto_total}"
            if monto_efectivo > 0 and monto_credito > 0:
                mensaje += f" (Efectivo: Bs.{monto_efectivo} + Crédito: Bs.{monto_credito})"
        
        return {
            'success': True,
            'mensaje': mensaje,
            'recibos': recibos,
            'monto_total': monto_total,
            'pago_efectivo': pago_efectivo,
            'pago_credito': pago_credito
        }
    
    @staticmethod
    @transaction.atomic
    def process_refund(user, paciente, monto_devolucion, metodo_pago_id, fecha_devolucion,
                      tipo_devolucion, referencia_id=None, motivo='', observaciones=''):
        """
        Procesa una devolución de dinero al paciente
        
        Args:
            user: Usuario que registra la devolución
            paciente: Instancia del Paciente
            monto_devolucion: Monto a devolver
            metodo_pago_id: ID del método de pago para la devolución
            fecha_devolucion: Fecha de la devolución
            tipo_devolucion: 'credito', 'proyecto', 'mensualidad'
            referencia_id: ID del proyecto/mensualidad (None si es crédito general)
            motivo: Motivo de la devolución
            observaciones: Observaciones adicionales
            
        Returns:
            dict con 'success', 'mensaje', 'devolucion', 'numero_recibo'
        """
        from facturacion.models import Devolucion, MetodoPago, Pago
        from agenda.models import Proyecto, Mensualidad
        
        # Validaciones
        if monto_devolucion <= 0:
            raise ValidationError('El monto de devolución debe ser mayor a cero')
        
        if not motivo:
            raise ValidationError('Debe especificar el motivo de la devolución')
        
        # Obtener referencia según tipo
        proyecto = None
        mensualidad = None
        
        if tipo_devolucion == 'proyecto':
            if not referencia_id:
                raise ValidationError('Debe especificar el proyecto')
            proyecto = Proyecto.objects.get(id=referencia_id)
            
            # Verificar que no se devuelva más de lo pagado
            total_pagado = Pago.objects.filter(
                proyecto=proyecto,
                anulado=False
            ).aggregate(total=Sum('monto'))['total'] or Decimal('0')
            
            devoluciones_previas = Devolucion.objects.filter(
                proyecto=proyecto
            ).aggregate(total=Sum('monto'))['total'] or Decimal('0')
            
            disponible = total_pagado - devoluciones_previas
            
            if monto_devolucion > disponible:
                raise ValidationError(
                    f'No se puede devolver más de lo disponible. Disponible: Bs.{disponible}'
                )
        
        elif tipo_devolucion == 'mensualidad':
            if not referencia_id:
                raise ValidationError('Debe especificar la mensualidad')
            mensualidad = Mensualidad.objects.get(id=referencia_id)
            
            total_pagado = Pago.objects.filter(
                mensualidad=mensualidad,
                anulado=False
            ).aggregate(total=Sum('monto'))['total'] or Decimal('0')
            
            devoluciones_previas = Devolucion.objects.filter(
                mensualidad=mensualidad
            ).aggregate(total=Sum('monto'))['total'] or Decimal('0')
            
            disponible = total_pagado - devoluciones_previas
            
            if monto_devolucion > disponible:
                raise ValidationError(
                    f'No se puede devolver más de lo disponible. Disponible: Bs.{disponible}'
                )
        
        elif tipo_devolucion == 'credito':
            # BUG 1 ESCENARIO B FIX: en lugar de leer cuenta.pagos_adelantados
            # (campo calculado que puede estar stale por el gap entre commit y
            # transaction.on_commit), recalculamos el crédito disponible en
            # tiempo real desde las fuentes dentro de esta misma transacción.
            #
            # Además bloqueamos la fila de CuentaCorriente con select_for_update()
            # para que ningún otro worker pueda crear una segunda devolución de
            # crédito concurrente contra el mismo saldo antes de que ésta termine.
            from facturacion.models import CuentaCorriente, DetallePagoMasivo
            cuenta, _ = CuentaCorriente.objects.get_or_create(paciente=paciente)
            # Lock a nivel de BD — protege contra concurrencia entre workers
            cuenta = CuentaCorriente.objects.select_for_update().get(id=cuenta.id)

            # Recalcular crédito real en tiempo real (no el campo cacheado)
            pagos_sin_asignar = Pago.objects.filter(
                paciente=paciente,
                sesion__isnull=True,
                mensualidad__isnull=True,
                proyecto__isnull=True,
                anulado=False,
            ).exclude(
                metodo_pago__nombre="Uso de Crédito"
            ).exclude(
                detalles_masivos__isnull=False
            ).aggregate(total=Coalesce(Sum('monto'), Decimal('0')))['total']

            uso_credito = Pago.objects.filter(
                paciente=paciente,
                metodo_pago__nombre="Uso de Crédito",
                anulado=False,
            ).aggregate(total=Coalesce(Sum('monto'), Decimal('0')))['total']

            devoluciones_credito_previas = Devolucion.objects.filter(
                paciente=paciente,
                proyecto__isnull=True,
                mensualidad__isnull=True,
            ).aggregate(total=Coalesce(Sum('monto'), Decimal('0')))['total']

            credito_real = pagos_sin_asignar - uso_credito - devoluciones_credito_previas

            if monto_devolucion > credito_real:
                raise ValidationError(
                    f'Crédito insuficiente. '
                    f'Crédito real disponible: Bs.{credito_real} '
                    f'(Adelantado: Bs.{pagos_sin_asignar} '
                    f'- Usado: Bs.{uso_credito} '
                    f'- Devuelto previamente: Bs.{devoluciones_credito_previas}).'
                )
        else:
            raise ValidationError('Tipo de devolución no válido')

        # Crear devolución
        # Devolucion.clean() re-valida las mismas reglas antes de guardar
        # (cubre el caso de creación directa desde Django Admin - Escenario A Fix)
        metodo_pago = MetodoPago.objects.get(id=metodo_pago_id)

        devolucion = Devolucion.objects.create(
            paciente=paciente,
            proyecto=proyecto,
            mensualidad=mensualidad,
            fecha_devolucion=fecha_devolucion,
            monto=monto_devolucion,
            motivo=motivo,
            metodo_devolucion=metodo_pago,
            observaciones=observaciones,
            registrado_por=user
        )

        # Actualizar cuenta corriente
        AccountService.update_balance(paciente)
        
        return {
            'success': True,
            'mensaje': f'Devolución registrada exitosamente',
            'devolucion': devolucion,
            'numero_recibo': devolucion.numero_devolucion
        }


class PaymentService:
    """
    Servicio para procesar pagos y devoluciones.
    Mantiene compatibilidad con views.py delegando a AccountService.
    BUG 6 FIX: process_refund ya no es una copia de AccountService.process_refund;
    delega completamente para garantizar un único punto de verdad.
    """
    
    @staticmethod
    @transaction.atomic
    def process_payment(user, paciente, monto_total, metodo_pago_id, fecha_pago,
                       tipo_pago, referencia_id=None, usar_credito=False,
                       monto_credito=0, es_pago_completo=False, observaciones='', numero_transaccion=''):
        """
        Procesa un pago - delega a AccountService para evitar duplicación
        """
        return AccountService.process_payment(
            user=user,
            paciente=paciente,
            monto_total=monto_total,
            metodo_pago_id=metodo_pago_id,
            fecha_pago=fecha_pago,
            tipo_pago=tipo_pago,
            referencia_id=referencia_id,
            usar_credito=usar_credito,
            monto_credito=monto_credito,
            es_pago_completo=es_pago_completo,
            observaciones=observaciones,
            numero_transaccion=numero_transaccion
        )
    
    @staticmethod
    @transaction.atomic
    def process_refund(user, paciente, monto_devolucion, metodo_pago_id, fecha_devolucion,
                      tipo_devolucion, referencia_id=None, motivo='', observaciones=''):
        """
        Procesa una devolución de dinero al paciente.

        BUG 6 FIX: Antes era una copia exacta de AccountService.process_refund,
        lo que significaba que correcciones en uno no se propagaban al otro.
        Ahora delega completamente: un único punto de verdad.
        """
        return AccountService.process_refund(
            user=user,
            paciente=paciente,
            monto_devolucion=monto_devolucion,
            metodo_pago_id=metodo_pago_id,
            fecha_devolucion=fecha_devolucion,
            tipo_devolucion=tipo_devolucion,
            referencia_id=referencia_id,
            motivo=motivo,
            observaciones=observaciones,
        )