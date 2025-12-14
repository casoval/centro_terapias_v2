from django.db import models
from django.core.validators import MinValueValidator
from decimal import Decimal
from agenda.models import Sesion
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
    """Registro detallado de pagos"""
    
    # Relaciones
    paciente = models.ForeignKey(
        Paciente, 
        on_delete=models.PROTECT,
        related_name='pagos'
    )
    sesion = models.ForeignKey(
        Sesion,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pagos',
        help_text="Sesión específica (opcional si es pago adelantado)"
    )
    
    # Datos del pago
    fecha_pago = models.DateField()
    monto = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
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
        unique=True,
        help_text="Número de recibo generado automáticamente"
    )
    
    # Control
    registrado_por = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='pagos_registrados'
    )
    fecha_registro = models.DateTimeField(auto_now_add=True)
    
    # Índices para optimizar búsquedas
    class Meta:
        verbose_name = "Pago"
        verbose_name_plural = "Pagos"
        ordering = ['-fecha_pago', '-fecha_registro']
        indexes = [
            models.Index(fields=['paciente', '-fecha_pago']),
            models.Index(fields=['fecha_pago']),
            models.Index(fields=['numero_recibo']),
        ]
    
    def __str__(self):
        return f"Pago {self.numero_recibo} - {self.paciente} - Bs. {self.monto}"
    
    def save(self, *args, **kwargs):
        if not self.numero_recibo:
            # Generar número de recibo automático
            ultimo = Pago.objects.order_by('-id').first()
            numero = 1 if not ultimo else ultimo.id + 1
            self.numero_recibo = f"REC-{numero:06d}"
        super().save(*args, **kwargs)


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
        help_text="Total de sesiones realizadas"
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
        """Recalcular saldo basado en sesiones y pagos"""
        from django.db.models import Sum, Q
        
        # Total consumido (sesiones realizadas)
        consumido = Sesion.objects.filter(
            paciente=self.paciente,
            estado__in=['realizada', 'realizada_retraso']
        ).aggregate(
            total=Sum('monto_cobrado')
        )['total'] or Decimal('0.00')
        
        # Total pagado
        pagado = Pago.objects.filter(
            paciente=self.paciente
        ).aggregate(
            total=Sum('monto')
        )['total'] or Decimal('0.00')
        
        self.total_consumido = consumido
        self.total_pagado = pagado
        self.saldo = pagado - consumido  # Positivo = a favor, Negativo = debe
        self.save()


class Factura(models.Model):
    """Facturas agrupando múltiples pagos/sesiones"""
    
    ESTADO_CHOICES = [
        ('borrador', 'Borrador'),
        ('emitida', 'Emitida'),
        ('anulada', 'Anulada'),
    ]
    
    # Identificación
    numero_factura = models.CharField(
        max_length=20,
        unique=True
    )
    fecha_emision = models.DateField()
    
    # Cliente
    paciente = models.ForeignKey(
        Paciente,
        on_delete=models.PROTECT,
        related_name='facturas'
    )
    
    # Datos fiscales (del tutor)
    nombre_fiscal = models.CharField(max_length=200)
    nit_ci = models.CharField(max_length=20)
    
    # Detalle
    concepto = models.TextField()
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    descuento = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00')
    )
    total = models.DecimalField(max_digits=10, decimal_places=2)
    
    # Estado
    estado = models.CharField(
        max_length=20,
        choices=ESTADO_CHOICES,
        default='borrador'
    )
    
    # Relación con pagos
    pagos = models.ManyToManyField(
        Pago,
        related_name='facturas',
        blank=True
    )
    
    # Control
    emitida_por = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='facturas_emitidas'
    )
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
            # Generar número automático
            ultimo = Factura.objects.order_by('-id').first()
            numero = 1 if not ultimo else ultimo.id + 1
            self.numero_factura = f"FACT-{numero:06d}"
        super().save(*args, **kwargs)