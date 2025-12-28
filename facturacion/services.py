from decimal import Decimal
from datetime import date
from django.db import transaction
from django.db.models import Sum
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User

from .models import Pago, MetodoPago, CuentaCorriente
from agenda.models import Sesion, Proyecto
from pacientes.models import Paciente

class AccountService:
    @staticmethod
    def update_balance(paciente: Paciente) -> Decimal:
        """
        Recalculate and update the balance (credit available) for a patient.
        Refactored from CuentaCorriente.actualizar_saldo to be more explicit and testable.
        """
        cuenta, _ = CuentaCorriente.objects.get_or_create(paciente=paciente)
        
        # 1. Pagos adelantados (sin sesión ni proyecto)
        pagos_adelantados = Pago.objects.filter(
            paciente=paciente,
            anulado=False,
            sesion__isnull=True,
            proyecto__isnull=True
        ).exclude(
            metodo_pago__nombre="Uso de Crédito"
        ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
        
        # 2. Pagos de sesiones no realizadas (programada)
        pagos_sesiones_pendientes = Pago.objects.filter(
            paciente=paciente,
            anulado=False,
            sesion__estado='programada'
        ).exclude(
            metodo_pago__nombre="Uso de Crédito"
        ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
        
        # 3. Excedentes (Overpayments on sessions)
        # This part requires iterating unless we do a complex query. 
        # Keeping iteration for now but optimized query filters.
        excedentes_total = Decimal('0.00')
        
        sesiones_con_cobro = Sesion.objects.filter(
            paciente=paciente,
            estado__in=['realizada', 'realizada_retraso', 'falta'],
            proyecto__isnull=True,
            monto_cobrado__gt=0
        )
        
        # Optimize: fetch all related payments in one go if possible, but per-session calculation is tricky in pure SQL without subqueries.
        # For now, we trust the database is fast enough or we can optimize later with annotations.
        for sesion in sesiones_con_cobro:
            total_pagado = sesion.pagos.filter(anulado=False).exclude(
                metodo_pago__nombre="Uso de Crédito"
            ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
            
            if total_pagado > sesion.monto_cobrado:
                excedentes_total += (total_pagado - sesion.monto_cobrado)
                
        # 4. Uso manual de crédito
        uso_credito = Pago.objects.filter(
            paciente=paciente,
            anulado=False,
            metodo_pago__nombre="Uso de Crédito"
        ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
        
        # Calculate available credit
        credito_disponible = (
            pagos_adelantados +
            pagos_sesiones_pendientes +
            excedentes_total -
            uso_credito
        )
        
        # Update totals for record keeping
        total_consumido = Sesion.objects.filter(
            paciente=paciente,
            estado__in=['realizada', 'realizada_retraso', 'falta'],
            proyecto__isnull=True,
            monto_cobrado__gt=0
        ).aggregate(total=Sum('monto_cobrado'))['total'] or Decimal('0.00')
        
        total_pagado = Pago.objects.filter(
            paciente=paciente,
            anulado=False
        ).exclude(
            metodo_pago__nombre="Uso de Crédito"
        ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
        
        cuenta.total_consumido = total_consumido
        cuenta.total_pagado = total_pagado
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
        referencia_id: int = None,  # sesion_id, proyecto_id, or None for adelantado
        es_pago_completo: bool = False,
        observaciones: str = "",
        numero_transaccion: str = ""
    ) -> dict:
        """
        Process a payment transaction including validation, credit application, and receipt generation.
        Returns a dictionary with result details.
        """
        
        # 1. Validation
        if monto_efectivo < 0 or monto_credito < 0:
            raise ValidationError("Los montos no pueden ser negativos.")

        usar_credito = monto_credito > 0
        cuenta, _ = CuentaCorriente.objects.get_or_create(paciente=paciente)
        
        if usar_credito:
            current_balance = cuenta.saldo
            # If logic allows calling update_balance before check, do it. But assumes caller likely updated it.
            # We will force update to be safe.
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
            recibos_generados = []
            monto_total_aportado = monto_efectivo + monto_credito
            
            # --- Logic for Payment Types ---
            
            if tipo_pago == 'sesion':
                if not referencia_id:
                    raise ValidationError("ID de sesión requerido.")
                sesion = Sesion.objects.get(id=referencia_id)
                
                # Logic: Adjust price if "Pago Completo"
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
                if sesion: concepto += f" - Sesión {sesion.fecha}"
                elif proyecto: concepto += f" - Proyecto {proyecto.codigo}"
                
                pago_credito = Pago.objects.create(
                    paciente=paciente,
                    sesion=sesion,
                    proyecto=proyecto,
                    fecha_pago=fecha_pago,
                    monto=monto_credito,
                    metodo_pago=metodo_credito,
                    concepto=concepto,
                    observaciones=f"Aplicación de saldo a favor\n{observaciones}",
                    registrado_por=user
                )
                # Override receipt number format for credit
                # Note: The model's save method auto-generates REC-XXXX. We might want to customize it.
                # The original view code did this: 
                pago_credito.numero_recibo = f"CREDITO-{fecha_pago.strftime('%Y%m%d')}-{pago_credito.id}"
                pago_credito.save()
                
            # B. Cash/Other Payment
            pago_efectivo = None
            if monto_efectivo > 0:
                concepto = "Pago"
                if sesion: concepto += f" sesión {sesion.fecha} - {sesion.servicio.nombre}"
                elif proyecto: concepto += f" proyecto {proyecto.codigo}"
                else: concepto += " adelantado"
                
                pago_efectivo = Pago.objects.create(
                    paciente=paciente,
                    sesion=sesion,
                    proyecto=proyecto,
                    fecha_pago=fecha_pago,
                    monto=monto_efectivo,
                    metodo_pago=metodo_pago,
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
