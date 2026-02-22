# facturacion/models.py
# ✅ ACTUALIZADO: Con campos calculados para optimización

from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db.models import Q, Sum
from pacientes.models import Paciente
from servicios.models import TipoServicio, Sucursal
from profesionales.models import Profesional
from datetime import datetime
from decimal import Decimal


class MetodoPago(models.Model):
    """Métodos de pago disponibles"""
    nombre = models.CharField(max_length=50, unique=True)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)
    
    class Meta:
        verbose_name = "Método de Pago"
        verbose_name_plural = "Métodos de Pago"
        ordering = ['nombre']
    
    def __str__(self):
        return self.nombre


class CuentaCorriente(models.Model):
    """
    Cuenta corriente del paciente con campos calculados y almacenados
    ✅ OPTIMIZADO: Todos los totales pre-calculados para acceso rápido
    """
    paciente = models.OneToOneField(
        Paciente,
        on_delete=models.CASCADE,
        related_name='cuenta_corriente'
    )
    
    # ========================================
    # PERSPECTIVA A: TOTAL REAL (con programadas)
    # ========================================
    
    # Consumido Real (incluye programadas y planificadas)
    total_sesiones_normales_real = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        default=0,
        help_text="Sesiones realizadas + falta (estados con costo ya generado)"
    )
    
    total_sesiones_programadas = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        default=0,
        help_text="Sesiones programadas (compromiso futuro)"
    )
    
    total_mensualidades = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        default=0,
        help_text="Mensualidades activas/pausadas/completadas"
    )
    
    total_proyectos_real = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        default=0,
        help_text="Proyectos en_progreso/finalizados"
    )
    
    total_proyectos_planificados = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        default=0,
        help_text="Proyectos planificados (compromiso futuro)"
    )
    
    # Total Consumido Real (con programadas y planificadas)
    total_consumido_real = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        default=0,
        help_text="Total incluyendo todos los compromisos"
    )
    
    # ========================================
    # PERSPECTIVA B: TOTAL ACTUAL (sin programadas)
    # ========================================
    
    # Total Consumido Actual (solo realizadas, sin futuros)
    total_consumido_actual = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        default=0,
        help_text="Total solo de lo ya ocurrido (sin programadas ni planificadas)"
    )
    
    # ========================================
    # PAGOS (mismo para ambas perspectivas)
    # ========================================
    
    pagos_sesiones = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        default=0,
        help_text="Pagos aplicados a sesiones normales"
    )
    
    pagos_mensualidades = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        default=0,
        help_text="Pagos aplicados a mensualidades"
    )
    
    pagos_proyectos = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        default=0,
        help_text="Pagos aplicados a proyectos"
    )
    
    # ✅ NUEVO: Pagos con crédito (para desglose detallado)
    pagos_sesiones_credito = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        default=0,
        help_text="Pagos a sesiones usando crédito (método 'Uso de Crédito')"
    )
    
    pagos_mensualidades_credito = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        default=0,
        help_text="Pagos a mensualidades usando crédito (método 'Uso de Crédito')"
    )
    
    pagos_proyectos_credito = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        default=0,
        help_text="Pagos a proyectos usando crédito (método 'Uso de Crédito')"
    )
    
    pagos_adelantados = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        default=0,
        help_text="Crédito disponible total (adelantado - usado)"
    )
    
    # ========================================
    # DESGLOSE DE CRÉDITO DISPONIBLE (para validación)
    # ========================================
    
    pagos_sin_asignar = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        default=0,
        help_text="Pagos adelantados sin asignar (adelantado puro)"
    )
    
    pagos_sesiones_programadas = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        default=0,
        help_text="Pagos a sesiones programadas (adelantado)"
    )
    
    pagos_proyectos_planificados = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        default=0,
        help_text="Pagos a proyectos planificados (adelantado)"
    )
    
    uso_credito = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        default=0,
        help_text="Monto usado del crédito (método 'Uso de Crédito')"
    )
    
    total_devoluciones = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        default=0,
        help_text="Devoluciones realizadas (se restan del total pagado)"
    )
    
    # Total Pagado (mismo para ambas perspectivas)
    total_pagado = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        default=0,
        help_text="Total pagado efectivamente (pagos - devoluciones)"
    )
    
    # ========================================
    # SALDOS (dos perspectivas)
    # ========================================
    
    # Saldo Real (con programadas y planificadas)
    saldo_real = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        default=0,
        help_text="Saldo incluyendo todos los compromisos futuros"
    )
    
    # Saldo Actual (sin programadas ni planificadas)
    saldo_actual = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        default=0,
        help_text="Saldo solo de lo ya ocurrido"
    )
    
    # ========================================
    # CONTADORES
    # ========================================
    
    num_sesiones_realizadas_pendientes = models.IntegerField(
        default=0,
        help_text="Sesiones realizadas/falta sin pagar completamente"
    )
    
    num_sesiones_programadas_pendientes = models.IntegerField(
        default=0,
        help_text="Sesiones programadas sin pagar"
    )
    
    num_mensualidades_activas = models.IntegerField(
        default=0,
        help_text="Mensualidades en estado activa"
    )
    
    num_proyectos_activos = models.IntegerField(
        default=0,
        help_text="Proyectos en progreso o planificados"
    )
    
    # ========================================
    # CAMPOS DE CONTROL
    # ========================================
    
    ultima_actualizacion = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Cuenta Corriente"
        verbose_name_plural = "Cuentas Corrientes"
        ordering = ['paciente__nombre', 'paciente__apellido']
    
        # ✅ NUEVO: Índices para mejor performance
        indexes = [
            # Índices simples en campos más consultados
            models.Index(fields=['saldo_actual'], name='idx_cc_saldo_act'),
            models.Index(fields=['saldo_real'], name='idx_cc_saldo_real'),
            models.Index(fields=['ultima_actualizacion'], name='idx_cc_upd'),
            
            # Índices compuestos para queries complejas
            models.Index(
                fields=['saldo_actual', 'ultima_actualizacion'], 
                name='idx_cc_saldo_fecha'
            ),
            
            # Índice condicional para deudores (solo PostgreSQL)
            models.Index(
                fields=['paciente', 'saldo_actual'],
                name='idx_cc_deudores',
                condition=models.Q(saldo_actual__lt=0)
            ),
        ]

    def __str__(self):
        return f"Cuenta de {self.paciente}"
    
    # ============================================================
    # PROPIEDADES COMPUTADAS (AGREGAR ESTAS)
    # ============================================================
    
    @property
    def consumo_sesiones(self):
        """Retorna el número total de sesiones consumidas (realizadas)"""
        from agenda.models import Sesion
        return Sesion.objects.filter(
            paciente=self.paciente,
            estado__in=['realizada', 'realizada_retraso']
        ).count()
    
    @property
    def consumo_sesiones_detalle(self):
        """Retorna un diccionario con detalles del consumo de sesiones"""
        from agenda.models import Sesion
        sesiones = Sesion.objects.filter(paciente=self.paciente)
        return {
            'total_programadas': sesiones.count(),
            'realizadas': sesiones.filter(estado='realizada').count(),
            'con_retraso': sesiones.filter(estado='realizada_retraso').count(),
            'faltas': sesiones.filter(estado='falta').count(),
            'pendientes': sesiones.filter(estado='pendiente').count(),
            'canceladas': sesiones.filter(estado='cancelada').count(),
            'total_consumidas': sesiones.filter(estado__in=['realizada', 'realizada_retraso']).count(),
        }
    
    @property
    def consumo_mensualidades(self):
        """Retorna el número total de mensualidades activas/pausadas/completadas"""
        from agenda.models import Mensualidad
        return Mensualidad.objects.filter(
            paciente=self.paciente,
            estado__in=['activa', 'pausada', 'completada']
        ).count()
    
    @property
    def consumo_proyectos(self):
        """Retorna el número total de proyectos en progreso/planificados/finalizados"""
        from agenda.models import Proyecto
        return Proyecto.objects.filter(
            paciente=self.paciente,
            estado__in=['en_progreso', 'planificado', 'finalizado']
        ).count()
    
    @property
    def pagado_sesiones(self):
        """Alias para pagos_sesiones"""
        return self.pagos_sesiones
    
    @property
    def pagado_mensualidades(self):
        """Alias para pagos_mensualidades"""
        return self.pagos_mensualidades
    
    @property
    def pagado_proyectos(self):
        """Alias para pagos_proyectos"""
        return self.pagos_proyectos
    
    @property
    def pendiente_sesiones(self):
        """Calcula el saldo pendiente de sesiones normales"""
        return self.total_sesiones_normales_real - self.pagos_sesiones
    
    @property
    def pendiente_mensualidades(self):
        """Calcula el saldo pendiente de mensualidades"""
        return self.total_mensualidades - self.pagos_mensualidades
    
    @property
    def pendiente_proyectos(self):
        """Calcula el saldo pendiente de proyectos"""
        return self.total_proyectos_real - self.pagos_proyectos
    
    @property
    def deuda_sesiones(self):
        """Alias para pendiente_sesiones"""
        return self.pendiente_sesiones
    
    @property
    def deuda_mensualidades(self):
        """Alias para pendiente_mensualidades"""
        return self.pendiente_mensualidades
    
    @property
    def deuda_proyectos(self):
        """Alias para pendiente_proyectos"""
        return self.pendiente_proyectos
    
    @property
    def deuda_total(self):
        """Calcula la deuda total (suma de todas las categorías)"""
        return self.deuda_sesiones + self.deuda_mensualidades + self.deuda_proyectos
    
    @property
    def total_consumo_general(self):
        """Alias para total_consumido_real"""
        return self.total_consumido_real
    
    @property
    def total_pagos(self):
        """Alias para total_pagado"""
        return self.total_pagado
    
    @property
    def saldo_general(self):
        """Alias para saldo_real"""
        return self.saldo_real
    
    @property
    def total_deuda_general(self):
        """Alias para deuda_total"""
        return self.deuda_total
    
    @property
    def balance_final(self):
        """Alias para saldo_actual - Balance final de la cuenta"""
        return self.saldo_actual
    
    @property
    def balance_general(self):
        """Alias alternativo para saldo_real"""
        return self.saldo_real
    
    @property
    def balance_actual(self):
        """Alias alternativo para saldo_actual"""
        return self.saldo_actual
    
    @property
    def credito_disponible(self):
        """Alias para pagos_adelantados"""
        return self.pagos_adelantados
    
    @property
    def saldo_favor(self):
        """Alias para pagos_adelantados - Saldo a favor del paciente"""
        return self.pagos_adelantados
    
    @property
    def total_consumido(self):
        """Alias para total_consumido_actual"""
        return self.total_consumido_actual
    
    @property
    def total_adeudado(self):
        """Retorna el monto adeudado (saldo_actual cuando es negativo)"""
        return abs(self.saldo_actual) if self.saldo_actual < 0 else 0
    
    @property
    def monto_pendiente(self):
        """Alias para deuda_total"""
        return self.deuda_total
    
    def actualizar_saldo(self):
        """
        Actualiza todos los campos calculados
        ⚠️ DEPRECATED: Usar AccountService.update_balance() en su lugar
        """
        from facturacion.services import AccountService
        AccountService.update_balance(self.paciente)


class Pago(models.Model):
    """Registro de pagos realizados por pacientes"""
    
    # Identificación
    numero_recibo = models.CharField(
        max_length=20,
        unique=True,
        help_text="Número único de recibo (autogenerado)"
    )
    
    # Relaciones
    paciente = models.ForeignKey(
        Paciente,
        on_delete=models.PROTECT,
        related_name='pagos'
    )
    
    # Relaciones opcionales (solo una debe estar presente)
    sesion = models.ForeignKey(
        'agenda.Sesion',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='pagos',
        help_text="Sesión a la que se aplica este pago"
    )
    
    proyecto = models.ForeignKey(
        'agenda.Proyecto',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='pagos',
        help_text="Proyecto al que se aplica este pago"
    )
    
    mensualidad = models.ForeignKey(
        'agenda.Mensualidad',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='pagos',
        help_text="Mensualidad a la que se aplica este pago"
    )
    
    # Datos del pago
    fecha_pago = models.DateField(help_text="Fecha en que se realizó el pago")
    monto = models.DecimalField(max_digits=10, decimal_places=0)
    metodo_pago = models.ForeignKey(MetodoPago, on_delete=models.PROTECT)
    concepto = models.CharField(max_length=200)
    numero_transaccion = models.CharField(
        max_length=100,
        blank=True,
        help_text="Número de transacción bancaria (opcional)"
    )
    observaciones = models.TextField(blank=True)
    
    # Control
    registrado_por = models.ForeignKey(User, on_delete=models.PROTECT)
    fecha_registro = models.DateTimeField(auto_now_add=True)
    
    # Anulación
    anulado = models.BooleanField(
        default=False,
        help_text="Marca el pago como anulado (no se considera en cálculos)"
    )
    motivo_anulacion = models.TextField(blank=True)
    anulado_por = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='pagos_anulados'
    )
    fecha_anulacion = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        verbose_name = "Pago"
        verbose_name_plural = "Pagos"
        ordering = ['-fecha_pago', '-fecha_registro']

        # ✅ NUEVO: Índices críticos para performance
        indexes = [
            # Índices simples
            models.Index(fields=['numero_recibo'], name='idx_pago_numero'),
            models.Index(fields=['paciente'], name='idx_pago_paciente'),
            models.Index(fields=['fecha_pago'], name='idx_pago_fecha'),
            models.Index(fields=['metodo_pago'], name='idx_pago_metodo'),
            models.Index(fields=['anulado'], name='idx_pago_anulado'),
            
            # Índices compuestos para queries frecuentes
            models.Index(
                fields=['paciente', 'anulado', 'fecha_pago'], 
                name='idx_pago_pac_anul_fec'
            ),
            models.Index(
                fields=['sesion', 'anulado'], 
                name='idx_pago_sesion_anul'
            ),
            models.Index(
                fields=['proyecto', 'anulado'], 
                name='idx_pago_proy_anul'
            ),
            models.Index(
                fields=['mensualidad', 'anulado'], 
                name='idx_pago_mens_anul'
            ),
            
            # Índice para búsqueda por método de pago específico
            models.Index(
                fields=['metodo_pago', 'anulado', 'fecha_pago'],
                name='idx_pago_metodo_valid'
            ),
            
            # Índice parcial solo para pagos válidos (PostgreSQL)
            models.Index(
                fields=['paciente', 'fecha_pago', 'monto'],
                name='idx_pago_valido',
                condition=models.Q(anulado=False)
            ),
        ]
    
    def __str__(self):
        return f"{self.numero_recibo} - {self.paciente} - Bs. {self.monto}"
    
    @property
    def es_pago_adelantado(self):
        """Verifica si es un pago adelantado (sin asignación específica)"""
        return (
            self.sesion is None and
            self.proyecto is None and
            self.mensualidad is None
        )
    
    @property
    def tipo_pago(self):
        """Retorna el tipo de pago"""
        if self.mensualidad:
            return 'mensualidad'
        elif self.proyecto:
            return 'proyecto'
        elif self.sesion:
            return 'sesion'
        else:
            return 'adelantado'
    
    @property
    def es_pago_masivo(self):
        """Verifica si es un pago masivo (tiene múltiples detalles)"""
        return self.detalles_masivos.exists()
    
    @property
    def cantidad_detalles(self):
        """Retorna la cantidad de ítems en el pago masivo"""
        return self.detalles_masivos.count()
    
    def clean(self):
        """Validaciones antes de guardar"""
        super().clean()
        
        # Solo una relación debe estar presente
        relaciones = sum([
            self.sesion is not None,
            self.proyecto is not None,
            self.mensualidad is not None
        ])
        
        if relaciones > 1:
            raise ValidationError(
                "El pago solo puede estar asociado a una sesión, proyecto o mensualidad"
            )
    
    def save(self, *args, **kwargs):
        """
        Genera número de recibo automáticamente con prefijo según tipo
        - REC-0001: Pagos en efectivo, QR, transferencia
        - CRE-0001: Uso de crédito

        BUG 7 FIX: Si se pasan update_fields (ej: anulaciones parciales),
        se omite full_clean() para evitar validaciones innecesarias sobre
        campos que no se están modificando.

        BUG 4 FIX: El ordenamiento usa Cast numérico en lugar de
        orden alfabético sobre el CharField, lo que evita que
        'REC-9999' > 'REC-10000' rompa la secuencia al superar 9.999 registros.
        """
        from django.db import transaction
        from django.db.models.functions import Cast, Substr
        from django.db.models import IntegerField

        # BUG 7 FIX: solo validar cuando NO es una actualización parcial
        update_fields = kwargs.get('update_fields')

        if not self.numero_recibo:
            # Determinar prefijo según método de pago
            if self.metodo_pago.nombre == "Uso de Crédito":
                prefijo = "CRE"
            else:
                prefijo = "REC"

            with transaction.atomic():
                # BUG 4 FIX: ordenar por el número entero extraído del sufijo,
                # no alfabéticamente por el CharField completo.
                ultimo_recibo = (
                    Pago.objects
                    .filter(numero_recibo__startswith=f'{prefijo}-')
                    .select_for_update()
                    .annotate(
                        num=Cast(
                            Substr('numero_recibo', len(prefijo) + 2),  # +2 por el guion
                            output_field=IntegerField()
                        )
                    )
                    .order_by('-num')
                    .first()
                )

                if ultimo_recibo:
                    nuevo_numero = ultimo_recibo.num + 1
                else:
                    nuevo_numero = 1

                self.numero_recibo = f'{prefijo}-{nuevo_numero:04d}'

                # full_clean solo al crear (numero_recibo nuevo)
                self.full_clean()
                super().save(*args, **kwargs)
            return  # ya se guardó dentro del bloque atomic

        # Actualización de registro existente
        if not update_fields:
            # Guardado completo: validar normalmente
            self.full_clean()
        # Si hay update_fields: es actualización parcial (ej: anulación),
        # se omite full_clean() intencionalmente (Bug 7 Fix)
        super().save(*args, **kwargs)
    
    def anular(self, usuario, motivo):
        """
        Anula el pago registrando auditoría completa.

        ESCENARIO C FIX: Se bloquea la anulación si existen devoluciones que
        dependen financieramente de este pago. Permitirlo generaría un estado
        imposible: la clínica habría entregado dinero basado en un pago que
        "no existió", creando dinero de la nada en los registros.

        Flujo correcto si se necesita anular:
            1. Ir al historial de devoluciones del proyecto/mensualidad
            2. Anular o revertir las devoluciones que dependen de este pago
            3. Recién entonces anular este pago
        """
        from django.utils import timezone
        from django.db.models import Sum as _Sum

        if self.anulado:
            raise ValidationError("Este pago ya está anulado.")

        # ── Bloqueo por devoluciones de proyecto ─────────────────────────────
        if self.proyecto_id:
            from facturacion.models import Devolucion
            total_dev = (
                Devolucion.objects
                .filter(proyecto_id=self.proyecto_id)
                .aggregate(total=_Sum('monto'))['total']
            ) or Decimal('0')

            if total_dev > 0:
                raise ValidationError(
                    f"No se puede anular este pago porque el proyecto asociado "
                    f"ya tiene Bs.{total_dev} en devoluciones registradas. "
                    f"Anular este pago dejaría esas devoluciones sin respaldo financiero. "
                    f"Para proceder: primero anule las devoluciones del proyecto "
                    f"'{self.proyecto}' y luego intente anular este pago."
                )

        # ── Bloqueo por devoluciones de mensualidad ───────────────────────────
        if self.mensualidad_id:
            from facturacion.models import Devolucion
            total_dev = (
                Devolucion.objects
                .filter(mensualidad_id=self.mensualidad_id)
                .aggregate(total=_Sum('monto'))['total']
            ) or Decimal('0')

            if total_dev > 0:
                raise ValidationError(
                    f"No se puede anular este pago porque la mensualidad asociada "
                    f"ya tiene Bs.{total_dev} en devoluciones registradas. "
                    f"Anular este pago dejaría esas devoluciones sin respaldo financiero. "
                    f"Para proceder: primero anule las devoluciones de la mensualidad "
                    f"'{self.mensualidad}' y luego intente anular este pago."
                )

        # ── Bloqueo por crédito usado vinculado a la misma sesión ────────────
        # Si se anula el pago en efectivo pero existe un CRE- vinculado a la
        # misma sesión, el crédito descontado queda huérfano (se usó crédito
        # para una sesión cuyo pago "no existió").
        if self.sesion_id and self.metodo_pago.nombre != "Uso de Crédito":
            pagos_credito = Pago.objects.filter(
                sesion_id=self.sesion_id,
                metodo_pago__nombre="Uso de Crédito",
                anulado=False
            ).exclude(id=self.id)

            if pagos_credito.exists():
                total_credito = (
                    pagos_credito.aggregate(total=_Sum('monto'))['total']
                ) or Decimal('0')
                raise ValidationError(
                    f"No se puede anular este pago porque la sesión tiene "
                    f"Bs.{total_credito} adicionales pagados con crédito. "
                    f"Anular solo el pago en efectivo dejaría ese crédito usado sin respaldo. "
                    f"Para proceder: anule primero los recibos de 'Uso de Crédito' "
                    f"de esta sesión y luego intente anular este pago."
                )

        # ── Proceder con la anulación ─────────────────────────────────────────
        self.anulado = True
        self.motivo_anulacion = motivo
        self.anulado_por = usuario
        self.fecha_anulacion = timezone.now()
        self.save(update_fields=['anulado', 'motivo_anulacion', 'anulado_por', 'fecha_anulacion'])

        # La cuenta corriente se actualiza automáticamente vía signal post_save


class DetallePagoMasivo(models.Model):
    """
    Detalle de cada ítem pagado en un pago masivo
    Permite que UN recibo agrupe múltiples sesiones/proyectos/mensualidades
    """
    pago = models.ForeignKey(
        'Pago',
        on_delete=models.CASCADE,
        related_name='detalles_masivos',
        help_text="Pago principal al que pertenece este detalle"
    )
    
    # Tipo de ítem pagado
    TIPO_CHOICES = [
        ('sesion', 'Sesión'),
        ('proyecto', 'Proyecto'),
        ('mensualidad', 'Mensualidad'),
    ]
    tipo = models.CharField(
        max_length=20,
        choices=TIPO_CHOICES,
        help_text="Tipo de servicio pagado"
    )
    
    # Referencias opcionales (solo una debe estar presente)
    sesion = models.ForeignKey(
        'agenda.Sesion',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='detalles_pago_masivo'
    )
    proyecto = models.ForeignKey(
        'agenda.Proyecto',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='detalles_pago_masivo'
    )
    mensualidad = models.ForeignKey(
        'agenda.Mensualidad',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='detalles_pago_masivo'
    )
    
    # Datos del detalle
    monto = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        help_text="Monto pagado para este ítem específico"
    )
    concepto = models.CharField(
        max_length=200,
        help_text="Descripción del ítem pagado"
    )
    
    class Meta:
        verbose_name = "Detalle de Pago Masivo"
        verbose_name_plural = "Detalles de Pagos Masivos"
        ordering = ['id']

        # ✅ NUEVO: Índices para joins eficientes
        indexes = [
            # Índices simples
            models.Index(fields=['pago'], name='idx_detmas_pago'),
            models.Index(fields=['tipo'], name='idx_detmas_tipo'),
            models.Index(fields=['sesion'], name='idx_detmas_sesion'),
            models.Index(fields=['proyecto'], name='idx_detmas_proy'),
            models.Index(fields=['mensualidad'], name='idx_detmas_mens'),
            
            # Índices compuestos para queries complejas
            models.Index(
                fields=['tipo', 'sesion'], 
                name='idx_detmas_tipo_ses'
            ),
            models.Index(
                fields=['tipo', 'proyecto'], 
                name='idx_detmas_tipo_proy'
            ),
            models.Index(
                fields=['tipo', 'mensualidad'], 
                name='idx_detmas_tipo_mens'
            ),
            
            # Índice para cálculos de totales
            models.Index(
                fields=['pago', 'tipo', 'monto'],
                name='idx_detmas_calc'
            ),
        ]

    
    def __str__(self):
        return f"{self.pago.numero_recibo} - {self.tipo} - Bs. {self.monto}"


class Devolucion(models.Model):
    """Registro de devoluciones de dinero a pacientes"""
    
    # Identificación
    numero_devolucion = models.CharField(
        max_length=20,
        unique=True,
        help_text="Número único de devolución (autogenerado)"
    )
    
    # Relaciones
    paciente = models.ForeignKey(
        Paciente,
        on_delete=models.PROTECT,
        related_name='devoluciones'
    )
    
    # Relaciones opcionales (qué se devuelve)
    proyecto = models.ForeignKey(
        'agenda.Proyecto',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Proyecto del cual se devuelve dinero"
    )
    
    mensualidad = models.ForeignKey(
        'agenda.Mensualidad',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Mensualidad de la cual se devuelve dinero"
    )
    
    # Datos de la devolución
    fecha_devolucion = models.DateField()
    monto = models.DecimalField(max_digits=10, decimal_places=0)
    motivo = models.TextField(help_text="Motivo de la devolución")
    metodo_devolucion = models.ForeignKey(
        MetodoPago,
        on_delete=models.PROTECT,
        help_text="Método por el cual se devuelve el dinero"
    )
    numero_transaccion = models.CharField(max_length=100, blank=True)
    observaciones = models.TextField(blank=True)
    
    # Control
    registrado_por = models.ForeignKey(User, on_delete=models.PROTECT)
    fecha_registro = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Devolución"
        verbose_name_plural = "Devoluciones"
        ordering = ['-fecha_devolucion', '-fecha_registro']

        # ✅ NUEVO: Índices para consultas
        indexes = [
            # Índices simples
            models.Index(fields=['numero_devolucion'], name='idx_dev_numero'),
            models.Index(fields=['paciente'], name='idx_dev_paciente'),
            models.Index(fields=['fecha_devolucion'], name='idx_dev_fecha'),
            models.Index(fields=['proyecto'], name='idx_dev_proyecto'),
            models.Index(fields=['mensualidad'], name='idx_dev_mens'),
            
            # Índices compuestos
            models.Index(
                fields=['paciente', 'fecha_devolucion'], 
                name='idx_dev_pac_fecha'
            ),
            models.Index(
                fields=['proyecto', 'monto'],
                name='idx_dev_proy_monto'
            ),
            models.Index(
                fields=['mensualidad', 'monto'],
                name='idx_dev_mens_monto'
            ),
        ]
    
    def __str__(self):
        return f"{self.numero_devolucion} - {self.paciente} - Bs. {self.monto}"

    def clean(self):
        """
        Validaciones financieras que se ejecutan SIEMPRE, incluyendo desde el
        Django Admin (que llama full_clean() → clean() automáticamente).

        BUG 1 ESCENARIO A FIX: Antes, la validación de crédito disponible solo
        existía en process_refund (en services.py). El Django Admin no pasa por
        ese servicio: crea el objeto directo en BD, bypaseando la validación.
        Al poner la lógica aquí en clean(), cualquier intento de crear una
        Devolucion inválida — sea desde el Admin, desde una API, o desde una
        vista — es bloqueado antes de llegar a la BD.

        IMPORTANTE: No usamos select_for_update() aquí porque clean() puede
        ejecutarse fuera de una transacción. La protección contra race conditions
        entre procesos la hace process_refund (Escenario B Fix en services.py).
        Este clean() protege contra el error humano en Admin.
        """
        from django.core.exceptions import ValidationError
        from django.db.models import Sum

        # Solo validar si el objeto es nuevo (creación, no edición).
        # Al editar una devolución existente no tiene sentido re-validar el
        # crédito disponible (ya se consumió cuando se creó).
        if self.pk:
            return

        if self.monto is None or self.monto <= 0:
            raise ValidationError({'monto': 'El monto de devolución debe ser mayor a cero.'})

        # ── Devolución de crédito general (sin proyecto ni mensualidad) ────────
        if not self.proyecto_id and not self.mensualidad_id:
            # Calcular crédito disponible en tiempo real desde las fuentes
            # (no desde el campo calculado pagos_adelantados que puede estar stale)
            from facturacion.models import Pago, Devolucion as Dev, DetallePagoMasivo

            pagos_sin_asignar = (
                Pago.objects
                .filter(
                    paciente=self.paciente,
                    sesion__isnull=True,
                    mensualidad__isnull=True,
                    proyecto__isnull=True,
                    anulado=False,
                )
                .exclude(metodo_pago__nombre="Uso de Crédito")
                .exclude(detalles_masivos__isnull=False)
                .aggregate(total=Sum('monto'))['total']
            ) or Decimal('0')

            uso_credito = (
                Pago.objects
                .filter(
                    paciente=self.paciente,
                    metodo_pago__nombre="Uso de Crédito",
                    anulado=False,
                )
                .aggregate(total=Sum('monto'))['total']
            ) or Decimal('0')

            # Devoluciones de crédito ya existentes (excluye la actual que aún no existe)
            devoluciones_credito_previas = (
                Dev.objects
                .filter(
                    paciente=self.paciente,
                    proyecto__isnull=True,
                    mensualidad__isnull=True,
                )
                .aggregate(total=Sum('monto'))['total']
            ) or Decimal('0')

            credito_real = pagos_sin_asignar - uso_credito - devoluciones_credito_previas

            if self.monto > credito_real:
                raise ValidationError({
                    'monto': (
                        f'Crédito insuficiente. '
                        f'Crédito real disponible: Bs.{credito_real} '
                        f'(Adelantado: Bs.{pagos_sin_asignar} '
                        f'- Usado: Bs.{uso_credito} '
                        f'- Devuelto previamente: Bs.{devoluciones_credito_previas}). '
                        f'No se puede devolver Bs.{self.monto}.'
                    )
                })

        # ── Devolución de proyecto ─────────────────────────────────────────────
        elif self.proyecto_id:
            from facturacion.models import Pago, Devolucion as Dev

            total_pagado_proyecto = (
                Pago.objects
                .filter(proyecto_id=self.proyecto_id, anulado=False)
                .aggregate(total=Sum('monto'))['total']
            ) or Decimal('0')

            devoluciones_previas_proyecto = (
                Dev.objects
                .filter(proyecto_id=self.proyecto_id)
                .aggregate(total=Sum('monto'))['total']
            ) or Decimal('0')

            disponible = total_pagado_proyecto - devoluciones_previas_proyecto

            if self.monto > disponible:
                raise ValidationError({
                    'monto': (
                        f'No se puede devolver Bs.{self.monto} del proyecto. '
                        f'Disponible: Bs.{disponible} '
                        f'(Pagado: Bs.{total_pagado_proyecto} '
                        f'- Ya devuelto: Bs.{devoluciones_previas_proyecto}).'
                    )
                })

        # ── Devolución de mensualidad ──────────────────────────────────────────
        elif self.mensualidad_id:
            from facturacion.models import Pago, Devolucion as Dev

            total_pagado_mensualidad = (
                Pago.objects
                .filter(mensualidad_id=self.mensualidad_id, anulado=False)
                .aggregate(total=Sum('monto'))['total']
            ) or Decimal('0')

            devoluciones_previas_mensualidad = (
                Dev.objects
                .filter(mensualidad_id=self.mensualidad_id)
                .aggregate(total=Sum('monto'))['total']
            ) or Decimal('0')

            disponible = total_pagado_mensualidad - devoluciones_previas_mensualidad

            if self.monto > disponible:
                raise ValidationError({
                    'monto': (
                        f'No se puede devolver Bs.{self.monto} de la mensualidad. '
                        f'Disponible: Bs.{disponible} '
                        f'(Pagado: Bs.{total_pagado_mensualidad} '
                        f'- Ya devuelto: Bs.{devoluciones_previas_mensualidad}).'
                    )
                })

    def save(self, *args, **kwargs):
        """
        Genera número de devolución automáticamente.

        BUG 4 FIX: El ordenamiento usa Cast numérico en lugar de
        orden alfabético sobre el CharField, lo que evita que
        'DEV-9999' > 'DEV-10000' rompa la secuencia al superar 9.999 registros.
        """
        if not self.numero_devolucion:
            from django.db import transaction
            from django.db.models.functions import Cast, Substr
            from django.db.models import IntegerField

            prefijo = 'DEV'

            with transaction.atomic():
                # BUG 4 FIX: ordenar por el número entero extraído del sufijo,
                # no alfabéticamente por el CharField completo.
                ultima_dev = (
                    Devolucion.objects
                    .filter(numero_devolucion__startswith=f'{prefijo}-')
                    .select_for_update()
                    .annotate(
                        num=Cast(
                            Substr('numero_devolucion', len(prefijo) + 2),  # +2 por el guion
                            output_field=IntegerField()
                        )
                    )
                    .order_by('-num')
                    .first()
                )

                if ultima_dev:
                    nuevo_numero = ultima_dev.num + 1
                else:
                    nuevo_numero = 1

                self.numero_devolucion = f'{prefijo}-{nuevo_numero:04d}'
                super().save(*args, **kwargs)
            return  # ya se guardó dentro del bloque atomic

        super().save(*args, **kwargs)

class Factura(models.Model):
    """Facturas generadas para pacientes"""

    ESTADO_CHOICES = [
        ('borrador', 'Borrador'),
        ('emitida', 'Emitida'),
        ('anulada', 'Anulada'),
    ]

    # Identificación
    numero_factura = models.CharField(max_length=20, unique=True)

    # Relaciones
    paciente = models.ForeignKey(
        Paciente,
        on_delete=models.PROTECT,
        related_name='facturas'
    )

    # Datos de facturación
    fecha_emision = models.DateField()
    razon_social = models.CharField(max_length=200)
    nit_ci = models.CharField(max_length=20)

    # Totales
    subtotal = models.DecimalField(max_digits=10, decimal_places=0)
    descuento = models.DecimalField(max_digits=10, decimal_places=0, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=0)

    # Estado
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='borrador')

    # Control
    registrado_por = models.ForeignKey(User, on_delete=models.PROTECT)
    fecha_registro = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Factura"
        verbose_name_plural = "Facturas"
        ordering = ['-fecha_emision']

    def __str__(self):
        return f"{self.numero_factura} - {self.paciente}"