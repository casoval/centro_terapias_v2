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
        decimal_places=2,
        default=0,
        help_text="Sesiones realizadas + falta (estados con costo ya generado)"
    )
    
    total_sesiones_programadas = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Sesiones programadas (compromiso futuro)"
    )
    
    total_mensualidades = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Mensualidades activas/pausadas/completadas"
    )
    
    total_proyectos_real = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Proyectos en_progreso/finalizados"
    )
    
    total_proyectos_planificados = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Proyectos planificados (compromiso futuro)"
    )
    
    # Total Consumido Real (con programadas y planificadas)
    total_consumido_real = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Total incluyendo todos los compromisos"
    )
    
    # ========================================
    # PERSPECTIVA B: TOTAL ACTUAL (sin programadas)
    # ========================================
    
    # Total Consumido Actual (solo realizadas, sin futuros)
    total_consumido_actual = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Total solo de lo ya ocurrido (sin programadas ni planificadas)"
    )
    
    # ========================================
    # PAGOS (mismo para ambas perspectivas)
    # ========================================
    
    pagos_sesiones = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Pagos aplicados a sesiones normales"
    )
    
    pagos_mensualidades = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Pagos aplicados a mensualidades"
    )
    
    pagos_proyectos = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Pagos aplicados a proyectos"
    )
    
    # ✅ NUEVO: Pagos con crédito (para desglose detallado)
    pagos_sesiones_credito = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Pagos a sesiones usando crédito (método 'Uso de Crédito')"
    )
    
    pagos_mensualidades_credito = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Pagos a mensualidades usando crédito (método 'Uso de Crédito')"
    )
    
    pagos_proyectos_credito = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Pagos a proyectos usando crédito (método 'Uso de Crédito')"
    )
    
    pagos_adelantados = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Crédito disponible total (adelantado - usado)"
    )
    
    # ========================================
    # DESGLOSE DE CRÉDITO DISPONIBLE (para validación)
    # ========================================
    
    pagos_sin_asignar = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Pagos adelantados sin asignar (adelantado puro)"
    )
    
    pagos_sesiones_programadas = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Pagos a sesiones programadas (adelantado)"
    )
    
    pagos_proyectos_planificados = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Pagos a proyectos planificados (adelantado)"
    )
    
    uso_credito = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Monto usado del crédito (método 'Uso de Crédito')"
    )
    
    total_devoluciones = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Devoluciones realizadas (se restan del total pagado)"
    )
    
    # Total Pagado (mismo para ambas perspectivas)
    total_pagado = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Total pagado efectivamente (pagos - devoluciones)"
    )
    
    # ========================================
    # SALDOS (dos perspectivas)
    # ========================================
    
    # Saldo Real (con programadas y planificadas)
    saldo_real = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Saldo incluyendo todos los compromisos futuros"
    )
    
    # Saldo Actual (sin programadas ni planificadas)
    saldo_actual = models.DecimalField(
        max_digits=10,
        decimal_places=2,
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
    monto = models.DecimalField(max_digits=10, decimal_places=2)
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
        """
        if not self.numero_recibo:
            # ✅ Determinar prefijo según método de pago
            if self.metodo_pago.nombre == "Uso de Crédito":
                prefijo = "CRE"
            else:
                prefijo = "REC"
        
            # ✅ Buscar el último número con este prefijo
            ultimo_recibo = Pago.objects.filter(
                numero_recibo__startswith=f'{prefijo}-'
            ).order_by('-numero_recibo').first()
        
            if ultimo_recibo:
                # Extraer el número del formato PREFIJO-NNNN
                ultimo_numero = int(ultimo_recibo.numero_recibo.split('-')[-1])
                nuevo_numero = ultimo_numero + 1
            else:
                nuevo_numero = 1
        
            # ✅ Formato simple: PREFIJO-NNNN (ej: REC-0001, CRE-0023)
            self.numero_recibo = f'{prefijo}-{nuevo_numero:04d}'
    
        self.full_clean()
        super().save(*args, **kwargs)
    
    def anular(self, usuario, motivo):
        """
        Anula el pago registrando auditoría completa
        
        Args:
            usuario: Usuario que anula el pago
            motivo: Motivo de la anulación
        """
        from django.utils import timezone
        
        if self.anulado:
            raise ValidationError("Este pago ya está anulado")
        
        # Marcar como anulado con auditoría
        self.anulado = True
        self.motivo_anulacion = motivo
        self.anulado_por = usuario
        self.fecha_anulacion = timezone.now()
        self.save(update_fields=['anulado', 'motivo_anulacion', 'anulado_por', 'fecha_anulacion'])
        
        # Actualizar la cuenta corriente del paciente
        # (los signals se encargarán de esto automáticamente)


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
        decimal_places=2,
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
    monto = models.DecimalField(max_digits=10, decimal_places=2)
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
    
    def save(self, *args, **kwargs):
        """Genera número de devolución automáticamente"""
        if not self.numero_devolucion:
            # ✅ Formato simple: DEV-NNNN
            ultima_dev = Devolucion.objects.filter(
                numero_devolucion__startswith='DEV-'
            ).order_by('-numero_devolucion').first()
        
            if ultima_dev:
                ultimo_numero = int(ultima_dev.numero_devolucion.split('-')[-1])
                nuevo_numero = ultimo_numero + 1
            else:
                nuevo_numero = 1
        
            self.numero_devolucion = f'DEV-{nuevo_numero:04d}'
    
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
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    descuento = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2)

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