# egresos/models.py
# App de egresos del centro: arriendos, servicios básicos, honorarios, personal, etc.

from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db.models import Q
from decimal import Decimal


class CategoriaEgreso(models.Model):
    """
    Categorías configurables para clasificar los egresos del centro.
    El campo 'tipo' agrupa categorías para los reportes del ResumenFinanciero.
    """
    TIPO_CHOICES = [
        ('arriendo',          'Arriendo / Alquiler'),
        ('servicios_basicos', 'Servicios Básicos'),   # luz, agua, gas, internet, teléfono
        ('personal',          'Personal Interno'),     # sueldos del staff fijo
        ('honorarios',        'Honorarios Profesionales'),  # profesionales externos
        ('equipamiento',      'Equipamiento y Materiales'),
        ('mantenimiento',     'Mantenimiento'),
        ('marketing',         'Marketing y Publicidad'),
        ('impuesto',          'Impuestos y Tasas'),
        ('seguro',            'Seguros'),
        ('capacitacion',      'Capacitación'),
        ('otro',              'Otro'),
    ]

    nombre      = models.CharField(max_length=100, unique=True, verbose_name="Nombre")
    tipo        = models.CharField(
        max_length=30,
        choices=TIPO_CHOICES,
        verbose_name="Tipo",
        help_text="Agrupa la categoría para los reportes financieros"
    )
    descripcion = models.TextField(blank=True, verbose_name="Descripción")
    activo      = models.BooleanField(default=True, verbose_name="Activo")
    es_honorario_profesional = models.BooleanField(
        default=False,
        verbose_name="Es pago de honorarios",
        help_text="Marcar si esta categoría corresponde a pago de honorarios a profesionales externos"
    )

    class Meta:
        verbose_name = "Categoría de Egreso"
        verbose_name_plural = "Categorías de Egreso"
        ordering = ['tipo', 'nombre']

    def __str__(self):
        return f"{self.nombre} ({self.get_tipo_display()})"


class Proveedor(models.Model):
    """
    Proveedores y beneficiarios de egresos.
    Puede ser una empresa (EPSAS, CRE) o un profesional externo.
    Si es profesional externo, se vincula con el modelo Profesional existente.
    """
    TIPO_CHOICES = [
        ('empresa',     'Empresa / Institución'),
        ('profesional', 'Profesional Externo'),
        ('persona',     'Persona Natural'),
    ]

    nombre          = models.CharField(max_length=200, verbose_name="Nombre / Razón Social")
    tipo            = models.CharField(max_length=20, choices=TIPO_CHOICES, verbose_name="Tipo")
    nit_ci          = models.CharField(max_length=20, blank=True, verbose_name="NIT / CI")
    telefono        = models.CharField(max_length=20, blank=True, verbose_name="Teléfono")
    email           = models.EmailField(blank=True, verbose_name="Email")
    banco           = models.CharField(max_length=100, blank=True, verbose_name="Banco")
    numero_cuenta   = models.CharField(max_length=50, blank=True, verbose_name="N° de Cuenta")

    # Si es profesional externo, vincular con el modelo ya existente en el sistema
    profesional     = models.OneToOneField(
        'profesionales.Profesional',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='proveedor_egreso',
        verbose_name="Profesional del sistema",
        help_text="Vincular si este proveedor es un profesional registrado en el sistema"
    )

    activo          = models.BooleanField(default=True, verbose_name="Activo")
    observaciones   = models.TextField(blank=True, verbose_name="Observaciones")

    class Meta:
        verbose_name = "Proveedor"
        verbose_name_plural = "Proveedores"
        ordering = ['nombre']

    def __str__(self):
        return f"{self.nombre} ({self.get_tipo_display()})"


class Egreso(models.Model):
    """
    Registro de cada egreso del centro con recibo propio (EGR-XXXX).
    Cubre: arriendos, servicios básicos, honorarios profesionales,
    sueldos de personal, equipamiento, impuestos, etc.

    Principio: TODO lo que sale del centro genera un EGR-XXXX como respaldo.
    """

    # ── Identificación ────────────────────────────────────────────────────────
    numero_egreso   = models.CharField(
        max_length=20,
        unique=True,
        verbose_name="N° Egreso",
        help_text="Autogenerado: EGR-0001, EGR-0002, ..."
    )

    # ── Clasificación ─────────────────────────────────────────────────────────
    categoria       = models.ForeignKey(
        CategoriaEgreso,
        on_delete=models.PROTECT,
        related_name='egresos',
        verbose_name="Categoría"
    )
    proveedor       = models.ForeignKey(
        Proveedor,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='egresos',
        verbose_name="Proveedor / Beneficiario"
    )

    # ── Datos del egreso ──────────────────────────────────────────────────────
    fecha           = models.DateField(verbose_name="Fecha de pago")
    concepto        = models.CharField(max_length=300, verbose_name="Concepto")
    monto           = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        verbose_name="Monto (Bs.)"
    )

    # Período al que corresponde el gasto (puede diferir de la fecha de pago)
    # Ejemplo: factura de luz de enero que se paga en febrero
    periodo_mes     = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        choices=[(i, str(i).zfill(2)) for i in range(1, 13)],
        verbose_name="Período - Mes",
        help_text="Mes al que corresponde el gasto (puede diferir del mes de pago)"
    )
    periodo_anio    = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        verbose_name="Período - Año"
    )

    # ── Método de pago ────────────────────────────────────────────────────────
    metodo_pago     = models.ForeignKey(
        'facturacion.MetodoPago',
        on_delete=models.PROTECT,
        verbose_name="Método de Pago"
    )
    numero_transaccion = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="N° Transacción / Cheque"
    )

    # ── Documento del proveedor ───────────────────────────────────────────────
    numero_documento_proveedor = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="N° Doc. Proveedor",
        help_text="Número de factura o recibo que el proveedor nos entregó"
    )
    comprobante     = models.FileField(
        upload_to='egresos/comprobantes/%Y/%m/',
        blank=True,
        verbose_name="Comprobante",
        help_text="Foto o PDF del comprobante del proveedor"
    )

    # ── Vínculo con sucursal ──────────────────────────────────────────────────
    sucursal        = models.ForeignKey(
        'servicios.Sucursal',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name="Sucursal",
        help_text="Sucursal a la que corresponde este egreso (vacío = global)"
    )

    # ── Vínculo con sesiones (para honorarios) ────────────────────────────────
    # Permite trazar exactamente qué sesiones cubre un pago de honorarios
    sesiones_cubiertas = models.ManyToManyField(
        'agenda.Sesion',
        blank=True,
        related_name='egreso_honorario',
        verbose_name="Sesiones cubiertas",
        help_text="Solo para honorarios: sesiones que cubre este pago"
    )

    # ── Control ───────────────────────────────────────────────────────────────
    observaciones   = models.TextField(blank=True, verbose_name="Observaciones")
    registrado_por  = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='egresos_registrados',
        verbose_name="Registrado por"
    )
    fecha_registro  = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de registro")

    # ── Anulación (mismo patrón que Pago en facturacion) ─────────────────────
    anulado         = models.BooleanField(default=False, verbose_name="Anulado")
    motivo_anulacion = models.TextField(blank=True, verbose_name="Motivo de anulación")
    anulado_por     = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='egresos_anulados',
        verbose_name="Anulado por"
    )
    fecha_anulacion = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fecha de anulación"
    )

    class Meta:
        verbose_name = "Egreso"
        verbose_name_plural = "Egresos"
        ordering = ['-fecha', '-fecha_registro']
        indexes = [
            models.Index(fields=['fecha'], name='idx_egreso_fecha'),
            models.Index(fields=['periodo_mes', 'periodo_anio'], name='idx_egreso_periodo'),
            models.Index(fields=['anulado'], name='idx_egreso_anulado'),
            models.Index(fields=['categoria'], name='idx_egreso_categoria'),
        ]

    def __str__(self):
        return f"{self.numero_egreso} - {self.concepto} (Bs. {self.monto})"

    def clean(self):
        """Validaciones de negocio antes de guardar."""
        if self.monto is not None and self.monto <= 0:
            raise ValidationError({'monto': 'El monto del egreso debe ser mayor a cero.'})

        if self.anulado and not self.motivo_anulacion:
            raise ValidationError({'motivo_anulacion': 'Debe especificar el motivo de anulación.'})

    def save(self, *args, **kwargs):
        """
        Genera número EGR-XXXX automáticamente.
        Mismo patrón que Pago (REC-XXXX) y Devolucion (DEV-XXXX) en facturacion.
        Usa Cast numérico para evitar orden alfabético incorrecto al superar 9.999.
        """
        # Auto-completar período con la fecha de pago si no se especificó
        if not self.periodo_mes:
            self.periodo_mes = self.fecha.month
        if not self.periodo_anio:
            self.periodo_anio = self.fecha.year

        if not self.numero_egreso:
            from django.db import transaction
            from django.db.models.functions import Cast, Substr
            from django.db.models import IntegerField

            prefijo = 'EGR'

            with transaction.atomic():
                ultimo = (
                    Egreso.objects
                    .filter(numero_egreso__startswith=f'{prefijo}-')
                    .select_for_update()
                    .annotate(
                        num=Cast(
                            Substr('numero_egreso', len(prefijo) + 2),
                            output_field=IntegerField()
                        )
                    )
                    .order_by('-num')
                    .first()
                )
                nuevo_numero = (ultimo.num + 1) if ultimo else 1
                self.numero_egreso = f'{prefijo}-{nuevo_numero:04d}'
                super().save(*args, **kwargs)
            return

        super().save(*args, **kwargs)

    @property
    def es_honorario(self):
        """True si este egreso corresponde a un pago de honorarios."""
        return self.categoria.es_honorario_profesional

    @property
    def periodo_display(self):
        """Retorna el período formateado como 'Enero 2025'."""
        if self.periodo_mes and self.periodo_anio:
            meses = [
                '', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
                'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'
            ]
            return f"{meses[self.periodo_mes]} {self.periodo_anio}"
        return '—'


class EgresoRecurrente(models.Model):
    """
    Plantilla para egresos que se repiten periódicamente.
    Un management command (generar_egresos_recurrentes) crea el Egreso real
    cada período automáticamente.

    Casos de uso: alquiler del local, factura de internet, seguro anual, etc.
    """
    FRECUENCIA_CHOICES = [
        ('mensual',    'Mensual'),
        ('bimestral',  'Bimestral'),
        ('trimestral', 'Trimestral'),
        ('semestral',  'Semestral'),
        ('anual',      'Anual'),
    ]

    categoria           = models.ForeignKey(
        CategoriaEgreso,
        on_delete=models.PROTECT,
        verbose_name="Categoría"
    )
    proveedor           = models.ForeignKey(
        Proveedor,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name="Proveedor"
    )
    concepto            = models.CharField(max_length=300, verbose_name="Concepto")
    monto_estimado      = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        verbose_name="Monto estimado (Bs.)",
        help_text="El monto real puede ajustarse al generar el egreso"
    )
    frecuencia          = models.CharField(
        max_length=20,
        choices=FRECUENCIA_CHOICES,
        default='mensual',
        verbose_name="Frecuencia"
    )
    dia_vencimiento     = models.PositiveSmallIntegerField(
        default=1,
        verbose_name="Día de vencimiento",
        help_text="Día del mes en que vence este egreso (1-28)"
    )
    metodo_pago_default = models.ForeignKey(
        'facturacion.MetodoPago',
        on_delete=models.PROTECT,
        verbose_name="Método de pago por defecto"
    )
    sucursal            = models.ForeignKey(
        'servicios.Sucursal',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name="Sucursal"
    )
    activo              = models.BooleanField(default=True, verbose_name="Activo")
    fecha_inicio        = models.DateField(verbose_name="Fecha de inicio")
    fecha_fin           = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fecha de fin",
        help_text="Dejar vacío si no tiene fecha de fin"
    )
    ultimo_generado     = models.DateField(
        null=True,
        blank=True,
        verbose_name="Último generado",
        help_text="Fecha del último Egreso generado desde esta plantilla"
    )
    observaciones       = models.TextField(blank=True, verbose_name="Observaciones")

    class Meta:
        verbose_name = "Egreso Recurrente"
        verbose_name_plural = "Egresos Recurrentes"
        ordering = ['categoria__tipo', 'concepto']

    def __str__(self):
        return f"{self.concepto} ({self.get_frecuencia_display()}) - Bs. {self.monto_estimado}"

    def clean(self):
        if self.dia_vencimiento < 1 or self.dia_vencimiento > 28:
            raise ValidationError({
                'dia_vencimiento': 'El día de vencimiento debe estar entre 1 y 28.'
            })
        if self.fecha_fin and self.fecha_fin < self.fecha_inicio:
            raise ValidationError({
                'fecha_fin': 'La fecha de fin no puede ser anterior a la fecha de inicio.'
            })


class ResumenFinanciero(models.Model):
    """
    Snapshot del estado financiero del centro por mes/año.
    Se recalcula automáticamente vía signal cuando hay cambios en Egreso o Pago.
    Permite ver histórico de rentabilidad sin recalcular todo cada vez.

    El campo 'sucursal=None' representa el resumen GLOBAL de todo el centro.
    """
    mes             = models.PositiveSmallIntegerField(
        choices=[(i, str(i).zfill(2)) for i in range(1, 13)],
        verbose_name="Mes"
    )
    anio            = models.PositiveSmallIntegerField(verbose_name="Año")
    sucursal        = models.ForeignKey(
        'servicios.Sucursal',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name="Sucursal",
        help_text="Null = resumen global de todo el centro"
    )

    # ── Ingresos ──────────────────────────────────────────────────────────────
    ingresos_brutos             = models.DecimalField(max_digits=12, decimal_places=0, default=0,
                                                       verbose_name="Ingresos brutos")
    total_devoluciones          = models.DecimalField(max_digits=12, decimal_places=0, default=0,
                                                       verbose_name="Total devoluciones")
    ingresos_netos              = models.DecimalField(max_digits=12, decimal_places=0, default=0,
                                                       verbose_name="Ingresos netos")

    # ── Egresos por tipo (espejo de TIPO_CHOICES de CategoriaEgreso) ──────────
    egresos_arriendo            = models.DecimalField(max_digits=12, decimal_places=0, default=0,
                                                       verbose_name="Arriendo / Alquiler")
    egresos_servicios_basicos   = models.DecimalField(max_digits=12, decimal_places=0, default=0,
                                                       verbose_name="Servicios básicos")
    egresos_personal            = models.DecimalField(max_digits=12, decimal_places=0, default=0,
                                                       verbose_name="Personal interno")
    egresos_honorarios          = models.DecimalField(max_digits=12, decimal_places=0, default=0,
                                                       verbose_name="Honorarios profesionales")
    egresos_equipamiento        = models.DecimalField(max_digits=12, decimal_places=0, default=0,
                                                       verbose_name="Equipamiento y materiales")
    egresos_mantenimiento       = models.DecimalField(max_digits=12, decimal_places=0, default=0,
                                                       verbose_name="Mantenimiento")
    egresos_marketing           = models.DecimalField(max_digits=12, decimal_places=0, default=0,
                                                       verbose_name="Marketing y publicidad")
    egresos_impuestos           = models.DecimalField(max_digits=12, decimal_places=0, default=0,
                                                       verbose_name="Impuestos y tasas")
    egresos_seguros             = models.DecimalField(max_digits=12, decimal_places=0, default=0,
                                                       verbose_name="Seguros")
    egresos_capacitacion        = models.DecimalField(max_digits=12, decimal_places=0, default=0,
                                                       verbose_name="Capacitación")
    egresos_otros               = models.DecimalField(max_digits=12, decimal_places=0, default=0,
                                                       verbose_name="Otros egresos")
    total_egresos               = models.DecimalField(max_digits=12, decimal_places=0, default=0,
                                                       verbose_name="Total egresos")

    # ── Resultado ─────────────────────────────────────────────────────────────
    resultado_neto              = models.DecimalField(max_digits=12, decimal_places=0, default=0,
                                                       verbose_name="Resultado neto")
    margen_porcentaje           = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        verbose_name="Margen (%)",
        help_text="resultado_neto / ingresos_netos × 100"
    )

    ultima_actualizacion        = models.DateTimeField(auto_now=True, verbose_name="Última actualización")

    class Meta:
        verbose_name = "Resumen Financiero"
        verbose_name_plural = "Resúmenes Financieros"
        unique_together = [['mes', 'anio', 'sucursal']]
        ordering = ['-anio', '-mes']

    def __str__(self):
        sufijo = f" - {self.sucursal}" if self.sucursal else " (Global)"
        return f"Resumen {str(self.mes).zfill(2)}/{self.anio}{sufijo}"

    @property
    def es_rentable(self):
        return self.resultado_neto >= 0

    @property
    def mes_display(self):
        meses = [
            '', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
            'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'
        ]
        return f"{meses[self.mes]} {self.anio}"


class PagoHonorario(models.Model):
    """
    Registro de cada pago realizado a un profesional externo.

    La deuda se calcula desde ComisionSesion (monto_profesional de cada sesión).
    El pago puede ser menor a la deuda — en ese caso se puede marcar como
    'saldado' para dar el tema por cerrado aunque quede diferencia.

    Cada pago genera un Egreso EGR-XXXX como respaldo contable.
    """

    profesional     = models.ForeignKey(
        'profesionales.Profesional',
        on_delete=models.PROTECT,
        related_name='pagos_honorarios',
        verbose_name="Profesional"
    )
    # Sesiones que cubre este pago (selección manual)
    sesiones        = models.ManyToManyField(
        'agenda.Sesion',
        related_name='pago_honorario',
        verbose_name="Sesiones cubiertas"
    )

    # Montos
    monto_deuda     = models.DecimalField(
        max_digits=10, decimal_places=0,
        verbose_name="Deuda de las sesiones seleccionadas",
        help_text="Suma de ComisionSesion.monto_profesional de las sesiones elegidas"
    )
    monto_pagado    = models.DecimalField(
        max_digits=10, decimal_places=0,
        verbose_name="Monto pagado realmente"
    )
    diferencia      = models.DecimalField(
        max_digits=10, decimal_places=0, default=0,
        verbose_name="Diferencia (deuda − pagado)",
        help_text="Positivo = faltó pagar. Negativo = se pagó de más (adelanto)."
    )

    # Saldado: da por cerradas las sesiones aunque quede diferencia
    saldado         = models.BooleanField(
        default=False,
        verbose_name="Marcar como saldado",
        help_text="Si está activo, las sesiones se consideran pagadas aunque el monto no cuadre."
    )

    # Pago
    fecha           = models.DateField(verbose_name="Fecha de pago")
    metodo_pago     = models.ForeignKey(
        'facturacion.MetodoPago',
        on_delete=models.PROTECT,
        verbose_name="Método de pago"
    )
    observaciones   = models.TextField(blank=True, verbose_name="Observaciones")

    # Egreso generado automáticamente
    egreso          = models.OneToOneField(
        'egresos.Egreso',
        on_delete=models.PROTECT,
        related_name='pago_honorario',
        verbose_name="Egreso (EGR-XXXX)"
    )

    # Control
    registrado_por  = models.ForeignKey(
        'auth.User',
        on_delete=models.PROTECT,
        related_name='pagos_honorarios_registrados',
        verbose_name="Registrado por"
    )
    fecha_registro  = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Pago de Honorario"
        verbose_name_plural = "Pagos de Honorarios"
        ordering = ['-fecha', '-fecha_registro']

    def __str__(self):
        return (
            f"{self.egreso.numero_egreso} — {self.profesional} — "
            f"Bs. {self.monto_pagado} "
            f"({'Saldado' if self.saldado else 'Parcial'})"
        )

    def save(self, *args, **kwargs):
        self.diferencia = self.monto_deuda - self.monto_pagado
        super().save(*args, **kwargs)