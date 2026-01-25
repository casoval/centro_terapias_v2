from django.db import models
from django.core.validators import MinValueValidator
from django.db.models import Sum, F, Q, Case, When, DecimalField
from django.db.models.functions import Coalesce
from django.core.cache import cache
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
    
    mensualidad = models.ForeignKey(
        'agenda.Mensualidad',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pagos',
        help_text="Mensualidad asociada (tratamientos mensuales regulares)"
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
            models.Index(fields=['-numero_recibo']),
            models.Index(fields=['sesion']),
            models.Index(fields=['proyecto']),
            models.Index(fields=['mensualidad']),
            models.Index(
                fields=['paciente', 'anulado'],
                name='pago_paciente_anulado_idx'
            ),
            models.Index(
                fields=['paciente', 'anulado', 'sesion'],
                name='pago_pac_anulado_sesion_idx'
            ),
            models.Index(
                fields=['paciente', 'anulado', 'proyecto'],
                name='pago_pac_anulado_proy_idx'
            ),
            models.Index(
                fields=['metodo_pago', 'anulado'],
                name='pago_metodo_anulado_idx'
            ),
            models.Index(
                fields=['sesion', 'anulado'],
                name='pago_sesion_anulado_idx'
            ),
            models.Index(
                fields=['proyecto', 'anulado'],
                name='pago_proyecto_anulado_idx'
            ),
            models.Index(
                fields=['mensualidad', 'anulado'],
                name='pago_mensualidad_anulado_idx'
            ), 
        ]
        
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(sesion__isnull=False, proyecto__isnull=True, mensualidad__isnull=True) |
                    models.Q(sesion__isnull=True, proyecto__isnull=False, mensualidad__isnull=True) |
                    models.Q(sesion__isnull=True, proyecto__isnull=True, mensualidad__isnull=False) |
                    models.Q(sesion__isnull=True, proyecto__isnull=True, mensualidad__isnull=True)
                ),
                name='pago_sesion_o_proyecto_o_mensualidad_o_ninguno'
            )
        ]
    
    def __str__(self):
        if self.mensualidad:
            return f"Pago {self.numero_recibo} - {self.paciente} - Mensualidad: {self.mensualidad.codigo} - Bs. {self.monto}"
        elif self.proyecto:
            return f"Pago {self.numero_recibo} - {self.paciente} - Proyecto: {self.proyecto.codigo} - Bs. {self.monto}"
        elif self.sesion:
            return f"Pago {self.numero_recibo} - {self.paciente} - Sesión - Bs. {self.monto}"
        else:
            return f"Pago {self.numero_recibo} - {self.paciente} - A cuenta - Bs. {self.monto}"
            
    @property
    def tipo_pago(self):
        """Retorna el tipo de pago como string"""
        if self.mensualidad:
            return 'mensualidad'
        elif self.proyecto:
            return 'proyecto'
        elif self.sesion:
            return 'sesion'
        else:
            return 'adelantado'
    
    def save(self, *args, **kwargs):
        """
        Genera numero_recibo automáticamente SOLO si no existe
        ✅ OPTIMIZADO: No dispara señales innecesarias
        """
        # Detectar si es una actualización sin cambios relevantes
        update_fields = kwargs.get('update_fields')
        if self.pk and update_fields and 'anulado' not in update_fields and 'monto' not in update_fields:
            # Es una actualización de campos no críticos, usar update_fields
            super().save(*args, **kwargs)
            return
        
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
        """Anular un pago - OPTIMIZADO"""
        from django.utils import timezone
        
        self.anulado = True
        self.motivo_anulacion = motivo
        self.anulado_por = user
        self.fecha_anulacion = timezone.now()
        self.save(update_fields=['anulado', 'motivo_anulacion', 'anulado_por', 'fecha_anulacion'])
        
        # Invalidar cache
        self._invalidate_patient_cache()
    
    def _invalidate_patient_cache(self):
        """Invalida el cache del paciente"""
        if self.paciente_id:
            cache_keys = [
                f'cuenta_deuda_{self.paciente_id}',
                f'cuenta_balance_{self.paciente_id}',
                f'cuenta_stats_{self.paciente_id}',
            ]
            cache.delete_many(cache_keys)


class CuentaCorriente(models.Model):
    """
    Cuenta corriente del paciente - resumen de deuda/saldo
    ✅ OPTIMIZADO: Con cache y propiedades lazy
    """
    
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
            models.Index(fields=['paciente', 'saldo']),
        ]
    
    def __str__(self):
        return f"CC {self.paciente} - Saldo: Bs. {self.saldo}"
    
    def actualizar_saldo(self):
        """
        Recalcular saldo (delegado al servicio)
        ✅ OPTIMIZADO: Con invalidación de cache
        """
        from .services import AccountService
        AccountService.update_balance(self.paciente)
        self.refresh_from_db()
        self._invalidate_cache()
    
    def _invalidate_cache(self):
        """Invalida el cache de esta cuenta"""
        cache_keys = [
            f'cuenta_deuda_{self.paciente_id}',
            f'cuenta_balance_{self.paciente_id}',
            f'cuenta_stats_{self.paciente_id}',
        ]
        cache.delete_many(cache_keys)
    
    def get_deuda_pendiente_cached(self, timeout=300):
        """
        ✅ Versión con cache de deuda_pendiente
        timeout: segundos de duración del cache (default 5 min)
        """
        cache_key = f'cuenta_deuda_{self.paciente_id}'
        deuda = cache.get(cache_key)
        
        if deuda is None:
            deuda = self._calcular_deuda_pendiente()
            cache.set(cache_key, deuda, timeout)
        
        return deuda
    
    def _calcular_deuda_pendiente(self):
        """
        Calcula cuánto debe el paciente de forma OPTIMIZADA (1 consulta).
        PRIVADO: Usar get_deuda_pendiente_cached() en su lugar
        """
        from agenda.models import Sesion
        
        resultado = Sesion.objects.filter(
            paciente=self.paciente,
            estado__in=['realizada', 'realizada_retraso', 'falta'],
            proyecto__isnull=True,
            monto_cobrado__gt=0
        ).annotate(
            pagado=Coalesce(
                Sum('pagos__monto', filter=Q(pagos__anulado=False)), 
                Decimal('0.00')
            )
        ).aggregate(
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
    def deuda_pendiente(self):
        """
        ⚠️ DEPRECADO: Usar get_deuda_pendiente_cached() para mejor performance
        Mantenido para compatibilidad pero genera queries sin cache
        """
        return self._calcular_deuda_pendiente()
    
    @property
    def balance_neto(self):
        """Balance neto: Crédito - Deuda"""
        return self.saldo - self.get_deuda_pendiente_cached()
    
    @property
    def balance_general(self):
        """Balance general: Total Pagado - Total Consumido"""
        return self.total_pagado - self.total_consumido
    
    # ✅ NUEVAS PROPIEDADES OPTIMIZADAS CON CACHE
    def get_stats_cached(self, timeout=300):
        """
        Obtiene todas las estadísticas de una vez con cache
        Retorna dict con: consumo_sesiones, pagado_sesiones, deuda_sesiones,
                         consumo_proyectos, pagado_proyectos, deuda_proyectos
        """
        cache_key = f'cuenta_stats_{self.paciente_id}'
        stats = cache.get(cache_key)
        
        if stats is None:
            stats = self._calcular_stats_completas()
            cache.set(cache_key, stats, timeout)
        
        return stats
    
    def _calcular_stats_completas(self):
        """Calcula todas las stats de una vez"""
        from agenda.models import Sesion, Proyecto
        
        # Sesiones
        consumo_sesiones = Sesion.objects.filter(
            paciente=self.paciente,
            estado__in=['realizada', 'realizada_retraso', 'falta'],
            proyecto__isnull=True,
            monto_cobrado__gt=0
        ).aggregate(total=Sum('monto_cobrado'))['total'] or Decimal('0.00')
        
        # Pagado en sesiones (con agregación)
        sesiones_con_pagos = Sesion.objects.filter(
            paciente=self.paciente,
            estado__in=['realizada', 'realizada_retraso', 'falta'],
            proyecto__isnull=True,
            monto_cobrado__gt=0
        ).annotate(
            pagado_calc=Coalesce(
                Sum('pagos__monto', filter=Q(pagos__anulado=False)),
                Decimal('0.00')
            )
        ).aggregate(
            total=Coalesce(Sum('pagado_calc'), Decimal('0.00'))
        )
        pagado_sesiones = sesiones_con_pagos['total']
        
        # Proyectos
        consumo_proyectos = Proyecto.objects.filter(
            paciente=self.paciente
        ).aggregate(
            total=Coalesce(Sum('costo_total'), Decimal('0.00'))
        )['total']
        
        pagado_proyectos = Proyecto.objects.filter(
            paciente=self.paciente
        ).annotate(
            total_pagado_calc=Coalesce(
                Sum('pagos__monto', filter=Q(pagos__anulado=False)), 
                Decimal('0.00')
            )
        ).aggregate(
            total=Coalesce(Sum('total_pagado_calc'), Decimal('0.00'))
        )['total']
        
        return {
            'consumo_sesiones': consumo_sesiones,
            'pagado_sesiones': pagado_sesiones,
            'deuda_sesiones': max(consumo_sesiones - pagado_sesiones, Decimal('0.00')),
            'consumo_proyectos': consumo_proyectos,
            'pagado_proyectos': pagado_proyectos,
            'deuda_proyectos': max(consumo_proyectos - pagado_proyectos, Decimal('0.00')),
        }
    
    # Propiedades que usan el cache
    @property
    def consumo_sesiones(self):
        return self.get_stats_cached()['consumo_sesiones']
    
    @property
    def pagado_sesiones(self):
        return self.get_stats_cached()['pagado_sesiones']
    
    @property
    def deuda_sesiones(self):
        return self.get_stats_cached()['deuda_sesiones']
    
    @property
    def consumo_proyectos(self):
        return self.get_stats_cached()['consumo_proyectos']
    
    @property
    def pagado_proyectos(self):
        return self.get_stats_cached()['pagado_proyectos']
    
    @property
    def deuda_proyectos(self):
        return self.get_stats_cached()['deuda_proyectos']
    
    @property
    def total_consumo_general(self):
        stats = self.get_stats_cached()
        return stats['consumo_sesiones'] + stats['consumo_proyectos']
    
    @property
    def total_pagado_general(self):
        stats = self.get_stats_cached()
        return stats['pagado_sesiones'] + stats['pagado_proyectos']
    
    @property
    def total_deuda_general(self):
        stats = self.get_stats_cached()
        return stats['deuda_sesiones'] + stats['deuda_proyectos']
    
    @property
    def balance_final(self):
        """Balance final: Crédito - Deuda Total - OPTIMIZADO"""
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