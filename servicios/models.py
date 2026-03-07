from django.db import models
from decimal import Decimal


class TipoServicio(models.Model):
    """Tipos de terapia/servicio que ofrece el centro"""
    
    nombre = models.CharField(max_length=100, unique=True)
    descripcion = models.TextField(blank=True)
    duracion_minutos = models.IntegerField(
        default=60,
        help_text="Duración estándar en minutos"
    )
    costo_base = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Costo base por sesión en Bs."
    )
    precio_mensual = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Precio mensual sugerido en Bs. (opcional)"
    )
    precio_proyecto = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Precio para proyecto/evaluación en Bs. (opcional)"
    )
    color = models.CharField(
        max_length=7,
        default='#3B82F6',
        help_text="Color para el calendario (formato: #RRGGBB)"
    )
    activo = models.BooleanField(default=True)

    # 🆕 NUEVOS CAMPOS: Servicio externo (profesional independiente)
    es_servicio_externo = models.BooleanField(
        default=False,
        help_text="Marcar si el profesional cobra su propio precio y el centro retiene un porcentaje"
    )
    porcentaje_centro = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="% que retiene el centro por sesión. Solo para servicios externos. (ej: 10.00 = 10%)"
    )

    class Meta:
        verbose_name = 'Tipo de Servicio'
        verbose_name_plural = 'Tipos de Servicios'
        ordering = ['nombre']
    
    def __str__(self):
        return f"{self.nombre} - Bs. {self.costo_base}"

    def clean(self):
        from django.core.exceptions import ValidationError
        # Si es servicio externo, el porcentaje es obligatorio
        if self.es_servicio_externo and not self.porcentaje_centro:
            raise ValidationError({
                'porcentaje_centro': 'Debe especificar el porcentaje del centro para servicios externos.'
            })
        # Si no es externo, limpiar el porcentaje
        if not self.es_servicio_externo:
            self.porcentaje_centro = None


class Sucursal(models.Model):
    """Sucursales del centro"""
    
    nombre = models.CharField(max_length=100)
    direccion = models.TextField()
    telefono = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    activa = models.BooleanField(default=True)
    
    class Meta:
        verbose_name = 'Sucursal'
        verbose_name_plural = 'Sucursales'
        ordering = ['nombre']
    
    def __str__(self):
        return self.nombre


# 🆕 NUEVO MODELO
class ComisionSesion(models.Model):
    """
    Registro informativo de la distribución de ingresos para sesiones de servicios externos.
    
    Solo existe para sesiones donde tipo_servicio.es_servicio_externo = True.
    
    ⚠️ IMPORTANTE: Este modelo NO afecta en absoluto:
        - El flujo de pagos
        - Los pagos con crédito
        - La cuenta corriente del paciente
        - Las anulaciones y devoluciones
    
    Su único propósito es registrar cuánto del dinero cobrado corresponde
    al centro y cuánto al profesional, para reportes internos.
    
    Los valores se guardan como snapshot al momento del pago, por lo que
    si el precio o porcentaje cambia después, el historial queda intacto.
    """
    sesion = models.OneToOneField(
        'agenda.Sesion',
        on_delete=models.CASCADE,
        related_name='comision'
    )
    # Snapshot de valores al momento del pago
    precio_cobrado = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        help_text="Precio real cobrado al paciente en esta sesión"
    )
    porcentaje_centro = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="% que retuvo el centro en esta sesión"
    )
    # Guardados en BD para poder usarlos en aggregates y reportes sin @property
    monto_centro = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        default=0,
        help_text="Monto que quedó en el centro (calculado automáticamente)"
    )
    monto_profesional = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        default=0,
        help_text="Monto que corresponde al profesional (calculado automáticamente)"
    )

    def save(self, *args, **kwargs):
        """Calcular monto_centro y monto_profesional automáticamente al guardar"""
        self.monto_centro = (self.precio_cobrado * self.porcentaje_centro / 100).quantize(Decimal('1'))
        self.monto_profesional = self.precio_cobrado - self.monto_centro
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = 'Comisión de Sesión'
        verbose_name_plural = 'Comisiones de Sesiones'

    def __str__(self):
        return (
            f"{self.sesion} | "
            f"Total: Bs.{self.precio_cobrado} | "
            f"Centro ({self.porcentaje_centro}%): Bs.{self.ingreso_centro} | "
            f"Profesional: Bs.{self.monto_profesional}"
        )