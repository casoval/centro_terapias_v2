from django.db import models
from django.core.validators import MinValueValidator
from django.db.models import Sum, F, Q, Case, When, DecimalField
from django.db.models.functions import Coalesce
from decimal import Decimal
from pacientes.models import Paciente
from django.contrib.auth.models import User


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


class Pago(models.Model):
    """
    Registro detallado de pagos
    
    🆕 NUEVO: Soporta 3 tipos de pago:
    1. Pago de sesión específica (sesion != None, proyecto = None)
    2. Pago de proyecto (proyecto != None, sesion = None)
    3. Pago adelantado/a cuenta (sesion = None, proyecto = None)
    """
    
    # Relaciones
    paciente = models.ForeignKey(
        Paciente, 
        on_delete=models.PROTECT,
        related_name='pagos'
    )
    
    sesion = models.ForeignKey(
        'agenda.Sesion',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pagos',
        help_text="Sesión específica (opcional si es pago adelantado o de proyecto)"
    )
    
    proyecto = models.ForeignKey(
        'agenda.Proyecto',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pagos',
        help_text="Proyecto asociado (evaluaciones, tratamientos especiales)"
    )
    
    # Datos del pago
    fecha_pago = models.DateField()
    monto = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    metodo_pago = models.ForeignKey(
        MetodoPago,
        on_delete=models.PROTECT
    )
    
    # Detalles adicionales
    numero_transaccion = models.CharField(
        max_length=100,
        blank=True,
        help_text="Número de referencia, transacción o recibo"
    )
    concepto = models.CharField(
        max_length=200,
        help_text="Concepto del pago"
    )
    observaciones = models.TextField(blank=True)
    
    # Recibo
    numero_recibo = models.CharField(
        max_length=20,
        help_text="Número de recibo generado automáticamente"
    )
    
    # Control
    registrado_por = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='pagos_registrados'
    )
    fecha_registro = models.DateTimeField(auto_now_add=True)
    
    # Anulación
    anulado = models.BooleanField(default=False)
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
        indexes = [
            models.Index(fields=['paciente', '-fecha_pago']),
            models.Index(fields=['fecha_pago']),
            models.Index(fields=['numero_recibo']),
            models.Index(fields=['-numero_recibo']),  # ✅ NUEVO: Para búsquedas descendentes
            models.Index(fields=['sesion']),
            models.Index(fields=['proyecto']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(sesion__isnull=False, proyecto__isnull=True) |
                    models.Q(sesion__isnull=True, proyecto__isnull=False) |
                    models.Q(sesion__isnull=True, proyecto__isnull=True)
                ),
                name='pago_sesion_o_proyecto_o_ninguno'
            )
        ]
    
    def __str__(self):
        if self.proyecto:
            return f"Pago {self.numero_recibo} - {self.paciente} - Proyecto: {self.proyecto.codigo} - Bs. {self.monto}"
        elif self.sesion:
            return f"Pago {self.numero_recibo} - {self.paciente} - Sesión - Bs. {self.monto}"
        else:
            return f"Pago {self.numero_recibo} - {self.paciente} - A cuenta - Bs. {self.monto}"
    
    @property
    def tipo_pago(self):
        """Retorna el tipo de pago como string"""
        if self.proyecto:
            return 'proyecto'
        elif self.sesion:
            return 'sesion'
        else:
            return 'adelantado'
    
    def save(self, *args, **kwargs):
        """
        Genera numero_recibo automáticamente SOLO si no existe
        """
        if not self.numero_recibo or self.numero_recibo == '':
            ultimo_pago = Pago.objects.filter(
                numero_recibo__startswith='REC-'
            ).order_by('-numero_recibo').first()
            
            if ultimo_pago:
                try:
                    ultimo_numero = int(ultimo_pago.numero_recibo.split('-')[1])
                    nuevo_numero = ultimo_numero + 1
                except (ValueError, IndexError):
                    nuevo_numero = Pago.objects.filter(
                        numero_recibo__startswith='REC-'
                    ).count() + 1
            else:
                nuevo_numero = 1
            
            self.numero_recibo = f"REC-{nuevo_numero:04d}"
        
        super().save(*args, **kwargs)

    
    def anular(self, user, motivo):
        """Anular un pago"""
        from django.utils import timezone
        
        self.anulado = True
        self.motivo_anulacion = motivo
        self.anulado_por = user
        self.fecha_anulacion = timezone.now()
        self.save()


class CuentaCorriente(models.Model):
    """Cuenta corriente del paciente - resumen de deuda/saldo"""
    
    paciente = models.OneToOneField(
        Paciente,
        on_delete=models.CASCADE,
        related_name='cuenta_corriente'
    )
    
    # Montos (calculados automáticamente)
    total_consumido = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Total de sesiones realizadas (NO incluye proyectos)"
    )
    total_pagado = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Total pagado"
    )
    saldo = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Saldo pendiente (negativo = debe, positivo = a favor)"
    )
    
    # Control
    ultima_actualizacion = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Cuenta Corriente"
        verbose_name_plural = "Cuentas Corrientes"
        indexes = [
            models.Index(fields=['saldo']),
        ]
    
    def __str__(self):
        return f"CC {self.paciente} - Saldo: Bs. {self.saldo}"
    
    def actualizar_saldo(self):
        """Recalcular saldo (delegado al servicio)"""
        from .services import AccountService
        AccountService.update_balance(self.paciente)
        # Recargar desde DB para tener datos frescos en esta instancia
        self.refresh_from_db()

    @property
    def deuda_pendiente(self):
        """
        Calcula cuánto debe el paciente de forma OPTIMIZADA (1 consulta).
        """
        from agenda.models import Sesion
        
        # Obtenemos sesiones que podrían tener deuda
        resultado = Sesion.objects.filter(
            paciente=self.paciente,
            estado__in=['realizada', 'realizada_retraso', 'falta'],
            proyecto__isnull=True,
            monto_cobrado__gt=0
        ).annotate(
            # Sumar pagos válidos para esta sesión
            pagado=Coalesce(
                Sum('pagos__monto', filter=Q(pagos__anulado=False)), 
                Decimal('0.00')
            )
        ).aggregate(
            # Sumar (Costo - Pagado) solo donde Costo > Pagado
            deuda_total=Coalesce(
                Sum(
                    Case(
                        When(monto_cobrado__gt=F('pagado'), then=F('monto_cobrado') - F('pagado')),
                        default=Decimal('0.00'),
                        output_field=DecimalField()
                    )
                ),
                Decimal('0.00')
            )
        )
        
        return resultado['deuda_total']

    @property
    def balance_neto(self):
        """Balance neto: Crédito - Deuda"""
        return self.saldo - self.deuda_pendiente

    @property
    def balance_general(self):
        """Balance general: Total Pagado - Total Consumido"""
        return self.total_pagado - self.total_consumido

    @property
    def consumo_sesiones(self):
        """Total consumido en sesiones normales (sin proyecto)"""
        from django.db.models import Sum
        from agenda.models import Sesion
        return Sesion.objects.filter(
            paciente=self.paciente,
            estado__in=['realizada', 'realizada_retraso', 'falta'],
            proyecto__isnull=True,
            monto_cobrado__gt=0
        ).aggregate(total=Sum('monto_cobrado'))['total'] or Decimal('0.00')

    @property
    def pagado_sesiones(self):
        """Total pagado en sesiones normales (sin proyecto)"""
        from agenda.models import Sesion
        sesiones_normales = Sesion.objects.filter(
            paciente=self.paciente,
            estado__in=['realizada', 'realizada_retraso', 'falta'],
            proyecto__isnull=True,
            monto_cobrado__gt=0
        )
        
        total = Decimal('0.00')
        for sesion in sesiones_normales:
            total += sesion.total_pagado
        
        return total

    @property
    def deuda_sesiones(self):
        """Deuda pendiente de sesiones normales"""
        return max(self.consumo_sesiones - self.pagado_sesiones, Decimal('0.00'))

    @property
    def consumo_proyectos(self):
        """Total consumido en proyectos"""
        from django.db.models import Sum
        from agenda.models import Proyecto
        return Proyecto.objects.filter(
            paciente=self.paciente
        ).aggregate(total=Sum('costo_total'))['total'] or Decimal('0.00')

    @property
    def pagado_proyectos(self):
        """Total pagado en proyectos"""
        from agenda.models import Proyecto
        proyectos = Proyecto.objects.filter(paciente=self.paciente)
        return sum(p.total_pagado for p in proyectos)

    @property
    def deuda_proyectos(self):
        """Deuda pendiente de proyectos"""
        return max(self.consumo_proyectos - self.pagado_proyectos, Decimal('0.00'))

    @property
    def total_consumo_general(self):
        """Total consumido (sesiones + proyectos)"""
        return self.consumo_sesiones + self.consumo_proyectos

    @property
    def total_pagado_general(self):
        """Total pagado (sesiones + proyectos)"""
        return self.pagado_sesiones + self.pagado_proyectos

    @property
    def total_deuda_general(self):
        """Total deuda pendiente (sesiones + proyectos)"""
        return self.deuda_sesiones + self.deuda_proyectos

    @property
    def balance_final(self):
        """Balance final: Crédito - Deuda Total"""
        return self.saldo - self.total_deuda_general

class Factura(models.Model):
    """Facturas agrupando múltiples pagos/sesiones"""
    
    ESTADO_CHOICES = [
        ('borrador', 'Borrador'),
        ('emitida', 'Emitida'),
        ('anulada', 'Anulada'),
    ]
    
    numero_factura = models.CharField(max_length=20, unique=True)
    fecha_emision = models.DateField()
    paciente = models.ForeignKey(Paciente, on_delete=models.PROTECT, related_name='facturas')
    nombre_fiscal = models.CharField(max_length=200)
    nit_ci = models.CharField(max_length=20)
    concepto = models.TextField()
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    descuento = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    total = models.DecimalField(max_digits=10, decimal_places=2)
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='borrador')
    pagos = models.ManyToManyField(Pago, related_name='facturas', blank=True)
    emitida_por = models.ForeignKey(User, on_delete=models.PROTECT, related_name='facturas_emitidas')
    fecha_registro = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Factura"
        verbose_name_plural = "Facturas"
        ordering = ['-fecha_emision']
        indexes = [
            models.Index(fields=['numero_factura']),
            models.Index(fields=['paciente', '-fecha_emision']),
        ]
    
    def __str__(self):
        return f"Factura {self.numero_factura} - {self.paciente}"
    
    def save(self, *args, **kwargs):
        if not self.numero_factura:
            ultimo = Factura.objects.order_by('-id').first()
            numero = 1 if not ultimo else ultimo.id + 1
            self.numero_factura = f"FACT-{numero:06d}"
        super().save(*args, **kwargs)