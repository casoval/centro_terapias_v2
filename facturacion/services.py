from decimal import Decimal
from datetime import date
from django.db import transaction
from django.db.models import Sum, F, Q
from django.db.models.functions import Coalesce
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User

from .models import Pago, MetodoPago, CuentaCorriente
from agenda.models import Sesion, Proyecto
from pacientes.models import Paciente


class AccountService:
    @staticmethod
    def update_balance(paciente: Paciente) -> Decimal:
        cuenta, _ = CuentaCorriente.objects.get_or_create(paciente=paciente)
        
        # 1. Pagos adelantados (1 consulta rápida)
        pagos_adelantados = Pago.objects.filter(
            paciente=paciente,
            anulado=False,
            tipo_operacion='pago',  # ✅ ACTUALIZADO: Solo pagos normales
            sesion__isnull=True,
            proyecto__isnull=True,
            mensualidad__isnull=True
        ).exclude(
            metodo_pago__nombre="Uso de Crédito"
        ).aggregate(total=Coalesce(Sum('monto'), Decimal('0.00')))['total']
        
        # 2. Pagos de sesiones no realizadas (1 consulta rápida)
        pagos_sesiones_pendientes = Pago.objects.filter(
            paciente=paciente,
            anulado=False,
            tipo_operacion='pago',  # ✅ ACTUALIZADO
            sesion__estado='programada'
        ).exclude(
            metodo_pago__nombre="Uso de Crédito"
        ).aggregate(total=Coalesce(Sum('monto'), Decimal('0.00')))['total']
        
        # 3. Excedentes (OPTIMIZADO: De N consultas a 1 consulta)
        sesiones_con_excedente = Sesion.objects.filter(
            paciente=paciente,
            proyecto__isnull=True,
            monto_cobrado__gt=0
        ).annotate(
            total_pagado_calc=Coalesce(
                Sum('pagos__monto', filter=Q(pagos__anulado=False) & Q(pagos__tipo_operacion='pago') & ~Q(pagos__metodo_pago__nombre="Uso de Crédito")), 
                Decimal('0.00')
            )
        ).filter(
            total_pagado_calc__gt=F('monto_cobrado')
        )
        
        excedentes_total = sesiones_con_excedente.aggregate(
            total=Coalesce(Sum(F('total_pagado_calc') - F('monto_cobrado')), Decimal('0.00'))
        )['total']
        
        # 4. Uso manual de crédito
        uso_credito = Pago.objects.filter(
            paciente=paciente,
            anulado=False,
            tipo_operacion='pago',  # ✅ ACTUALIZADO
            metodo_pago__nombre="Uso de Crédito"
        ).aggregate(total=Coalesce(Sum('monto'), Decimal('0.00')))['total']
        
        # ✅ 5. NUEVO: Devoluciones (restan del crédito disponible)
        devoluciones_total = Pago.objects.filter(
            paciente=paciente,
            anulado=False,
            tipo_operacion='devolucion'
        ).aggregate(total=Coalesce(Sum('monto'), Decimal('0.00')))['total']
        
        # Calcular saldo final
        credito_disponible = (
            pagos_adelantados +
            pagos_sesiones_pendientes +
            excedentes_total -
            uso_credito -
            devoluciones_total  # ✅ NUEVO: Restar devoluciones
        )
        
        # Actualizar totales informativos
        stats = Pago.objects.filter(
            paciente=paciente, anulado=False, tipo_operacion='pago'  # ✅ ACTUALIZADO
        ).exclude(
            metodo_pago__nombre="Uso de Crédito"
        ).aggregate(pagado=Coalesce(Sum('monto'), Decimal('0.00')))

        consumo = Sesion.objects.filter(
            paciente=paciente,
            estado__in=['realizada', 'realizada_retraso', 'falta'],
            proyecto__isnull=True
        ).aggregate(cobrado=Coalesce(Sum('monto_cobrado'), Decimal('0.00')))
        
        cuenta.total_consumido = consumo['cobrado']
        cuenta.total_pagado = stats['pagado']
        cuenta.saldo = credito_disponible
        cuenta.save()
        
        return cuenta.saldo


class PaymentService:
    @staticmethod
    def process_payment(
        user: User,
        paciente: Paciente,
        monto_efectivo: Decimal,
        monto_credito: Decimal,
        metodo_pago_id: int,
        fecha_pago: date,
        tipo_pago: str,
        referencia_id: int = None,
        es_pago_completo: bool = False,
        observaciones: str = "",
        numero_transaccion: str = ""
    ) -> dict:
        """
        Process a payment transaction including validation, credit application, and receipt generation.
        Soporta: sesion, proyecto, mensualidad, adelantado
        Returns a dictionary with result details.
        """
        
        # 1. Validation
        if monto_efectivo < 0 or monto_credito < 0:
            raise ValidationError("Los montos no pueden ser negativos.")

        usar_credito = monto_credito > 0
        cuenta, _ = CuentaCorriente.objects.get_or_create(paciente=paciente)
        
        if usar_credito:
            current_balance = AccountService.update_balance(paciente)
            if current_balance < monto_credito:
                raise ValidationError(f"Crédito insuficiente. Disponible: Bs. {current_balance}")

        if monto_efectivo > 0 and not metodo_pago_id:
            raise ValidationError("Debe seleccionar un método de pago para el monto en efectivo.")
            
        metodo_pago = None
        if metodo_pago_id:
            metodo_pago = MetodoPago.objects.get(id=metodo_pago_id)

        # 2. Transaction Processing
        with transaction.atomic():
            sesion = None
            proyecto = None
            mensualidad = None  # ✅ NUEVO
            recibos_generados = []
            monto_total_aportado = monto_efectivo + monto_credito
            
            # --- Logic for Payment Types ---
            
            if tipo_pago == 'sesion':
                if not referencia_id:
                    raise ValidationError("ID de sesión requerido.")
                sesion = Sesion.objects.get(id=referencia_id)
                
                if es_pago_completo:
                    pagado_previo = sesion.pagos.filter(anulado=False).exclude(
                        metodo_pago__nombre="Uso de Crédito"
                    ).aggregate(Sum('monto'))['monto__sum'] or Decimal('0.00')
                    
                    nuevo_costo = pagado_previo + monto_total_aportado
                    if sesion.monto_cobrado != nuevo_costo:
                        nota = f"\n[{date.today()}] Ajuste 'Pago Completo': {sesion.monto_cobrado} -> {nuevo_costo}"
                        sesion.monto_cobrado = nuevo_costo
                        sesion.observaciones = (sesion.observaciones or "") + nota
                        sesion.save()
            
            elif tipo_pago == 'proyecto':
                if not referencia_id:
                    raise ValidationError("ID de proyecto requerido.")
                proyecto = Proyecto.objects.get(id=referencia_id)
                
                if es_pago_completo:
                    pagado_previo = proyecto.pagos.filter(anulado=False).exclude(
                        metodo_pago__nombre="Uso de Crédito"
                    ).aggregate(Sum('monto'))['monto__sum'] or Decimal('0.00')
                    
                    nuevo_costo = pagado_previo + monto_total_aportado
                    if proyecto.costo_total != nuevo_costo:
                        proyecto.costo_total = nuevo_costo
                        proyecto.save()
            
            # ✅ NUEVO: Soporte para mensualidades
            elif tipo_pago == 'mensualidad':
                if not referencia_id:
                    raise ValidationError("ID de mensualidad requerido.")
                from agenda.models import Mensualidad
                mensualidad = Mensualidad.objects.get(id=referencia_id)
                
                if es_pago_completo:
                    pagado_previo = mensualidad.pagos.filter(anulado=False).exclude(
                        metodo_pago__nombre="Uso de Crédito"
                    ).aggregate(Sum('monto'))['monto__sum'] or Decimal('0.00')
                    
                    nuevo_costo = pagado_previo + monto_total_aportado
                    if mensualidad.costo_mensual != nuevo_costo:
                        mensualidad.costo_mensual = nuevo_costo
                        mensualidad.save()
                        
            elif tipo_pago == 'adelantado':
                if monto_efectivo <= 0:
                    raise ValidationError("El pago adelantado requiere un monto en efectivo mayor a 0.")
                    
            # --- Recording Payments ---
            
            # A. Credit Payment
            if usar_credito:
                metodo_credito, _ = MetodoPago.objects.get_or_create(
                    nombre="Uso de Crédito",
                    defaults={'descripcion': 'Aplicación de saldo a favor', 'activo': True}
                )
                
                concepto = f"Uso de crédito"
                if sesion: 
                    concepto += f" - Sesión {sesion.fecha}"
                elif proyecto: 
                    concepto += f" - Proyecto {proyecto.codigo}"
                elif mensualidad:  # ✅ NUEVO
                    concepto += f" - Mensualidad {mensualidad.codigo}"
                
                pago_credito = Pago.objects.create(
                    paciente=paciente,
                    sesion=sesion,
                    proyecto=proyecto,
                    mensualidad=mensualidad,  # ✅ NUEVO
                    fecha_pago=fecha_pago,
                    monto=monto_credito,
                    metodo_pago=metodo_credito,
                    tipo_operacion='pago',  # ✅ NUEVO
                    concepto=concepto,
                    observaciones=f"Aplicación de saldo a favor\n{observaciones}",
                    registrado_por=user
                )
                pago_credito.numero_recibo = f"CREDITO-{fecha_pago.strftime('%Y%m%d')}-{pago_credito.id}"
                pago_credito.save()
                
            # B. Cash/Other Payment
            pago_efectivo = None
            if monto_efectivo > 0:
                concepto = "Pago"
                if sesion: 
                    concepto += f" sesión {sesion.fecha} - {sesion.servicio.nombre}"
                elif proyecto: 
                    concepto += f" proyecto {proyecto.codigo}"
                elif mensualidad:  # ✅ CORREGIDO
                    concepto += f" mensualidad {mensualidad.codigo} - {mensualidad.periodo_display}"
                else: 
                    concepto += " adelantado"
                
                pago_efectivo = Pago.objects.create(
                    paciente=paciente,
                    sesion=sesion,
                    proyecto=proyecto,
                    mensualidad=mensualidad,  # ✅ NUEVO
                    fecha_pago=fecha_pago,
                    monto=monto_efectivo,
                    metodo_pago=metodo_pago,
                    tipo_operacion='pago',  # ✅ NUEVO
                    concepto=concepto,
                    observaciones=observaciones,
                    numero_transaccion=numero_transaccion,
                    registrado_por=user
                )
                recibos_generados.append(pago_efectivo.numero_recibo)
                
            # Update Balance after transaction
            AccountService.update_balance(paciente)
            
            # Prepare Result
            return {
                'success': True,
                'pago_efectivo': pago_efectivo,
                'recibos': recibos_generados,
                'monto_total': float(monto_total_aportado),
                'mensaje': 'Pago registrado exitosamente'
            }

    @staticmethod
    def process_refund(
        user: User,
        paciente: Paciente,
        monto_devolucion: Decimal,
        metodo_pago_id: int,
        fecha_devolucion: date,
        tipo_devolucion: str,
        referencia_id: int = None,
        motivo: str = "",
        observaciones: str = ""
    ) -> dict:
        """
        Procesar una devolución de dinero al paciente.
        
        Soporta 3 casos:
        1. tipo_devolucion='credito': Devuelve dinero del crédito disponible del paciente
        2. tipo_devolucion='proyecto': Devolución parcial de un proyecto específico
        3. tipo_devolucion='mensualidad': Devolución parcial de una mensualidad específica
        
        Args:
            user: Usuario que registra la devolución
            paciente: Paciente al que se le devuelve dinero
            monto_devolucion: Monto a devolver (siempre positivo)
            metodo_pago_id: Método usado para la devolución (efectivo, transferencia, etc.)
            fecha_devolucion: Fecha de la devolución
            tipo_devolucion: 'credito', 'proyecto', o 'mensualidad'
            referencia_id: ID del proyecto o mensualidad (solo si tipo != 'credito')
            motivo: Razón de la devolución
            observaciones: Observaciones adicionales
            
        Returns:
            dict con resultado de la operación
        """
        
        # 1. Validaciones básicas
        if monto_devolucion <= 0:
            raise ValidationError("El monto de devolución debe ser mayor a 0.")
        
        if not metodo_pago_id:
            raise ValidationError("Debe seleccionar un método de pago para la devolución.")
        
        metodo_pago = MetodoPago.objects.get(id=metodo_pago_id)
        
        # 2. Validaciones según tipo de devolución
        proyecto = None
        mensualidad = None
        
        if tipo_devolucion == 'credito':
            # CASO 2: Devolución de crédito disponible
            current_balance = AccountService.update_balance(paciente)
            
            if current_balance < monto_devolucion:
                raise ValidationError(
                    f"Crédito insuficiente. Disponible: Bs. {current_balance:.2f}, "
                    f"Solicitado: Bs. {monto_devolucion:.2f}"
                )
            
            concepto = f"Devolución de crédito disponible"
            
        elif tipo_devolucion == 'proyecto':
            # CASO 3a: Devolución parcial de proyecto
            if not referencia_id:
                raise ValidationError("ID de proyecto requerido para devolución de proyecto.")
            
            proyecto = Proyecto.objects.get(id=referencia_id)
            
            # Validar que no se devuelva más de lo pagado
            total_pagado = proyecto.pagos.filter(
                anulado=False,
                tipo_operacion='pago'
            ).exclude(
                metodo_pago__nombre="Uso de Crédito"
            ).aggregate(Sum('monto'))['monto__sum'] or Decimal('0.00')
            
            devoluciones_previas = proyecto.pagos.filter(
                anulado=False,
                tipo_operacion='devolucion'
            ).aggregate(Sum('monto'))['monto__sum'] or Decimal('0.00')
            
            disponible_devolver = total_pagado - devoluciones_previas
            
            if monto_devolucion > disponible_devolver:
                raise ValidationError(
                    f"No se puede devolver más de lo pagado. "
                    f"Disponible para devolver: Bs. {disponible_devolver:.2f}"
                )
            
            concepto = f"Devolución parcial - Proyecto {proyecto.codigo}"
            
        elif tipo_devolucion == 'mensualidad':
            # CASO 3b: Devolución parcial de mensualidad
            if not referencia_id:
                raise ValidationError("ID de mensualidad requerido para devolución de mensualidad.")
            
            from agenda.models import Mensualidad
            mensualidad = Mensualidad.objects.get(id=referencia_id)
            
            # Validar que no se devuelva más de lo pagado
            total_pagado = mensualidad.pagos.filter(
                anulado=False,
                tipo_operacion='pago'
            ).exclude(
                metodo_pago__nombre="Uso de Crédito"
            ).aggregate(Sum('monto'))['monto__sum'] or Decimal('0.00')
            
            devoluciones_previas = mensualidad.pagos.filter(
                anulado=False,
                tipo_operacion='devolucion'
            ).aggregate(Sum('monto'))['monto__sum'] or Decimal('0.00')
            
            disponible_devolver = total_pagado - devoluciones_previas
            
            if monto_devolucion > disponible_devolver:
                raise ValidationError(
                    f"No se puede devolver más de lo pagado. "
                    f"Disponible para devolver: Bs. {disponible_devolver:.2f}"
                )
            
            concepto = f"Devolución parcial - Mensualidad {mensualidad.codigo}"
            
        else:
            raise ValidationError(f"Tipo de devolución inválido: {tipo_devolucion}")
        
        # 3. Registrar la devolución
        with transaction.atomic():
            # Crear el registro de devolución
            devolucion = Pago.objects.create(
                paciente=paciente,
                proyecto=proyecto,
                mensualidad=mensualidad,
                fecha_pago=fecha_devolucion,
                monto=monto_devolucion,
                metodo_pago=metodo_pago,
                tipo_operacion='devolucion',  # ✅ CLAVE
                concepto=concepto,
                observaciones=f"{motivo}\n{observaciones}" if motivo else observaciones,
                registrado_por=user
            )
            
            # Generar número de recibo
            devolucion.numero_recibo = f"DEV-{fecha_devolucion.strftime('%Y%m%d')}-{devolucion.id}"
            devolucion.save()
            
            # 4. Ajustar costos si es devolución de proyecto/mensualidad (OPCIÓN A)
            if proyecto:
                nuevo_costo = proyecto.costo_total - monto_devolucion
                if nuevo_costo < 0:
                    nuevo_costo = Decimal('0.00')
                
                proyecto.costo_total = nuevo_costo
                proyecto.observaciones = (proyecto.observaciones or "") + \
                    f"\n[{fecha_devolucion}] Devolución: Bs. {monto_devolucion} - {motivo}"
                proyecto.save()
                
            elif mensualidad:
                nuevo_monto = mensualidad.costo_mensual - monto_devolucion
                if nuevo_monto < 0:
                    nuevo_monto = Decimal('0.00')
                
                mensualidad.costo_mensual = nuevo_monto
                mensualidad.observaciones = (mensualidad.observaciones or "") + \
                    f"\n[{fecha_devolucion}] Devolución: Bs. {monto_devolucion} - {motivo}"
                mensualidad.save()
            
            # 5. Actualizar balance de cuenta corriente
            AccountService.update_balance(paciente)
            
            # 6. Retornar resultado
            return {
                'success': True,
                'devolucion': devolucion,
                'numero_recibo': devolucion.numero_recibo,
                'monto': float(monto_devolucion),
                'tipo': tipo_devolucion,
                'mensaje': f'Devolución de Bs. {monto_devolucion:.2f} registrada exitosamente'
            }