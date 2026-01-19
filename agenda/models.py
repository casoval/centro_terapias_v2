from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db.models import Q, Sum
from django.utils.functional import cached_property
from pacientes.models import Paciente
from servicios.models import TipoServicio, Sucursal
from profesionales.models import Profesional
from datetime import datetime, timedelta
from decimal import Decimal


class Proyecto(models.Model):
    """
    Para servicios de duración variable (evaluaciones, tratamientos especiales)
    Ejemplo: Evaluación Psicológica de 500 Bs que puede durar 1-10 días
    """
    
    TIPO_CHOICES = [
        ('evaluacion', 'Evaluación'),
        ('tratamiento_especial', 'Tratamiento Especial'),
        ('otro', 'Otro'),
    ]
    
    ESTADO_CHOICES = [
        ('planificado', 'Planificado'),
        ('en_progreso', 'En Progreso'),
        ('finalizado', 'Finalizado'),
        ('cancelado', 'Cancelado'),
    ]
    
    # Identificación
    codigo = models.CharField(
        max_length=20,
        unique=True,
        help_text="Código único del proyecto (ej: EVAL-PSI-001)"
    )
    nombre = models.CharField(
        max_length=200,
        help_text="Nombre descriptivo del proyecto"
    )
    tipo = models.CharField(max_length=30, choices=TIPO_CHOICES)
    
    # Relaciones
    paciente = models.ForeignKey(
        Paciente,
        on_delete=models.PROTECT,
        related_name='proyectos'
    )
    servicio_base = models.ForeignKey(
        TipoServicio,
        on_delete=models.PROTECT,
        help_text="Servicio base (ej: Evaluación Psicológica)"
    )
    profesional_responsable = models.ForeignKey(
        Profesional,
        on_delete=models.PROTECT,
        related_name='proyectos_responsable'
    )
    sucursal = models.ForeignKey(
        Sucursal,
        on_delete=models.PROTECT
    )
    
    # Fechas
    fecha_inicio = models.DateField()
    fecha_fin_estimada = models.DateField(
        null=True,
        blank=True,
        help_text="Fecha estimada de finalización"
    )
    fecha_fin_real = models.DateField(
        null=True,
        blank=True,
        help_text="Fecha real de finalización"
    )
    
    # Costos
    costo_total = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Costo FIJO del proyecto completo"
    )
    
    # Estado
    estado = models.CharField(
        max_length=20,
        choices=ESTADO_CHOICES,
        default='planificado'
    )
    
    # Descripción
    descripcion = models.TextField(
        blank=True,
        help_text="Descripción del alcance del proyecto"
    )
    observaciones = models.TextField(blank=True)
    
    # Control
    creado_por = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='proyectos_creados'
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    modificado_por = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='proyectos_modificados',
        null=True,
        blank=True
    )
    fecha_modificacion = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Proyecto"
        verbose_name_plural = "Proyectos"
        ordering = ['-fecha_inicio']
        indexes = [
            models.Index(fields=['paciente', '-fecha_inicio']),
            models.Index(fields=['estado']),
            models.Index(fields=['codigo']),
        ]
    
    def __str__(self):
        return f"{self.codigo} - {self.nombre} ({self.paciente})"
    
    @property
    def total_pagado(self):
        """Total de pagos recibidos para este proyecto"""
        from facturacion.models import Pago
        return Pago.objects.filter(
            proyecto=self,
            anulado=False
        ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
    
    @property
    def saldo_pendiente(self):
        """Monto que aún falta por pagar"""
        return self.costo_total - self.total_pagado
    
    @property
    def pagado_completo(self):
        """Verifica si el proyecto está pagado completamente"""
        return self.total_pagado >= self.costo_total
    
    @property
    def duracion_dias(self):
        """Duración real en días"""
        if self.fecha_fin_real:
            return (self.fecha_fin_real - self.fecha_inicio).days + 1
        elif self.estado == 'en_progreso':
            from datetime import date
            return (date.today() - self.fecha_inicio).days + 1
        return 0
    
    def save(self, *args, **kwargs):
        if not self.codigo:
            # Generar código automático
            ultimo = Proyecto.objects.order_by('-id').first()
            numero = 1 if not ultimo else ultimo.id + 1
            prefijo = self.tipo[:4].upper()
            self.codigo = f"{prefijo}-{numero:04d}"
        super().save(*args, **kwargs)


class Sesion(models.Model):
    """Sesión de terapia/consulta"""
    
    ESTADO_CHOICES = [
        ('programada', 'Programada'),
        ('realizada', 'Realizada'),
        ('realizada_retraso', 'Realizada con Retraso'),
        ('falta', 'Falta sin Aviso'),
        ('permiso', 'Permiso (con aviso)'),
        ('cancelada', 'Cancelada'),
        ('reprogramada', 'Reprogramada'),
    ]
    
    # Relaciones principales
    paciente = models.ForeignKey(
        Paciente,
        on_delete=models.PROTECT,
        related_name='sesiones'
    )
    servicio = models.ForeignKey(
        TipoServicio,
        on_delete=models.PROTECT,
        related_name='sesiones'
    )
    profesional = models.ForeignKey(
        Profesional,
        on_delete=models.PROTECT,
        related_name='sesiones'
    )
    sucursal = models.ForeignKey(
        Sucursal,
        on_delete=models.PROTECT,
        related_name='sesiones'
    )
    
    # 🆕 NUEVO: Relación con Proyecto (opcional)
    proyecto = models.ForeignKey(
        Proyecto,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sesiones',
        help_text="Si pertenece a un proyecto (evaluación, tratamiento especial)"
    )
    
    # Fecha y hora
    fecha = models.DateField()
    hora_inicio = models.TimeField()
    hora_fin = models.TimeField()
    duracion_minutos = models.PositiveIntegerField()
    
    # Estado
    estado = models.CharField(
        max_length=20,
        choices=ESTADO_CHOICES,
        default='programada'
    )
    
    # Para reprogramaciones
    fecha_reprogramada = models.DateField(null=True, blank=True)
    hora_reprogramada = models.TimeField(null=True, blank=True)
    motivo_reprogramacion = models.TextField(blank=True)
    reprogramacion_realizada = models.BooleanField(
        default=False,
        help_text="Marcar cuando ya se creó manualmente la nueva sesión"
    )
    
    # Para retrasos
    hora_real_inicio = models.TimeField(
        null=True,
        blank=True,
        help_text="Hora real de inicio si hubo retraso"
    )
    minutos_retraso = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Minutos de retraso"
    )
    
    # 🔥 CAMBIO CRÍTICO: Monto a cobrar (puede ser 0)
    monto_cobrado = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        help_text="Monto a cobrar por esta sesión (0 si es parte de proyecto/evaluación o gratuita)"
    )
    
    # 🔥 ELIMINADOS: pagado y fecha_pago (ahora son @property)
    
    # Observaciones
    observaciones = models.TextField(blank=True)
    notas_sesion = models.TextField(
        blank=True,
        help_text="Notas clínicas/evolución de la sesión"
    )
    
    # 🆕 Control de edición por profesionales
    editada_por_profesional = models.BooleanField(
        default=False,
        help_text="Indica si un profesional ya editó esta sesión"
    )
    fecha_edicion_profesional = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Fecha en que el profesional editó la sesión"
    )
    profesional_editor = models.ForeignKey(
        Profesional,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sesiones_editadas',
        help_text="Profesional que editó la sesión"
    )
    
    # Control
    creada_por = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='sesiones_creadas'
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    modificada_por = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='sesiones_modificadas',
        null=True,
        blank=True
    )
    fecha_modificacion = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Sesión"
        verbose_name_plural = "Sesiones"
        ordering = ['fecha', 'hora_inicio']
        indexes = [
            models.Index(fields=['fecha', 'hora_inicio']),
            models.Index(fields=['paciente', 'fecha']),
            models.Index(fields=['profesional', 'fecha']),
            models.Index(fields=['estado']),
            models.Index(fields=['proyecto']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['paciente', 'fecha', 'hora_inicio'],
                name='unique_paciente_fecha_hora'
            )
        ]
    
    def __str__(self):
        return f"{self.fecha} {self.hora_inicio} - {self.paciente} - {self.servicio}"
    
    # 🆕 NUEVAS PROPIEDADES CALCULADAS
    @cached_property  # ✅ Solo cambia esto
    def total_pagado(self):
        return self.pagos.filter(anulado=False).exclude(
            metodo_pago__nombre="Uso de Crédito"
        ).aggregate(Sum('monto'))['monto__sum'] or Decimal('0.00')
    
    @property
    def saldo_pendiente(self):
        """Monto que aún falta por pagar"""
        return self.monto_cobrado - self.total_pagado
    
    @property
    def pagado(self):
        """
        Verifica si la sesión está pagada completamente
        - Si monto_cobrado = 0 → Siempre True (no requiere pago)
        - Si monto_cobrado > 0 → True si total_pagado >= monto_cobrado
        """
        if self.monto_cobrado == 0:
            return True  # Sesiones gratuitas o de proyecto
        return self.total_pagado >= self.monto_cobrado
    
    @property
    def fecha_pago(self):
        """Obtiene la fecha del último pago"""
        pago = self.pagos.filter(anulado=False).order_by('-fecha_pago').first()
        return pago.fecha_pago if pago else None
    
    @property
    def pago_activo(self):
        """Obtiene el primer pago válido (para compatibilidad)"""
        return self.pagos.filter(anulado=False).first()
    
    @property
    def requiere_pago(self):
        """Verifica si esta sesión debe ser cobrada"""
        # Estados que NO se cobran
        if self.estado in ['permiso', 'cancelada', 'reprogramada']:
            return False
        # Si es parte de un proyecto, el pago es del proyecto
        if self.proyecto:
            return False
        # Si el monto es 0 (sesión gratuita)
        if self.monto_cobrado == 0:
            return False
        return True
    
    @property
    def estado_pago(self):
        """
        Retorna el estado del pago como string
        Útil para mostrar en templates
        """
        if not self.requiere_pago:
            return 'no_aplica'
        if self.pagado:
            return 'pagado'
        if self.total_pagado > 0:
            return 'parcial'
        return 'pendiente'

    @property
    def total_pagado_contado(self):
        """Total pagado en efectivo/contado (sin crédito)"""
        from django.db.models import Sum
        from decimal import Decimal
        
        return self.pagos.filter(
            anulado=False
        ).exclude(
            metodo_pago__nombre="Uso de Crédito"
        ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
    
    @property
    def total_pagado_credito(self):
        """Total pagado con crédito"""
        from django.db.models import Sum
        from decimal import Decimal
        
        return self.pagos.filter(
            anulado=False,
            metodo_pago__nombre="Uso de Crédito"
        ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
    
    def clean(self):
        """Validación de choques de horarios"""
        super().clean()
        
        if not self.hora_fin:
            # Calcular hora_fin automáticamente
            inicio = datetime.combine(self.fecha, self.hora_inicio)
            fin = inicio + timedelta(minutes=self.duracion_minutos)
            self.hora_fin = fin.time()
        
        # Validar que hora_fin sea después de hora_inicio
        if self.hora_inicio >= self.hora_fin:
            raise ValidationError({
                'hora_fin': 'La hora de fin debe ser posterior a la hora de inicio.'
            })
        
        # ✅ VALIDAR: Paciente debe tener la sucursal asignada
        if not self.paciente.tiene_sucursal(self.sucursal):
            raise ValidationError({
                'sucursal': f'❌ El paciente {self.paciente} no está asignado a la sucursal {self.sucursal}.'
            })
        
        # ✅ VALIDAR: Profesional debe tener la sucursal asignada
        if not self.profesional.tiene_sucursal(self.sucursal):
            raise ValidationError({
                'sucursal': f'❌ El profesional {self.profesional} no trabaja en la sucursal {self.sucursal}.'
            })
        
        # ✅ VALIDAR: Profesional debe ofrecer el servicio
        if not self.profesional.puede_atender_servicio(self.servicio):
            raise ValidationError({
                'profesional': f'❌ El profesional {self.profesional} no ofrece el servicio {self.servicio}.'
            })
        
        # 🚫 VALIDAR CHOQUES DE HORARIOS
        self._validar_choque_paciente()
        self._validar_choque_profesional()
    
    def _validar_choque_paciente(self):
        """El paciente NO puede tener otra sesión al mismo tiempo"""
        sesiones_existentes = Sesion.objects.filter(
            paciente=self.paciente,
            fecha=self.fecha,
            estado__in=['programada', 'realizada', 'realizada_retraso']
        ).exclude(pk=self.pk)
        
        for sesion in sesiones_existentes:
            if self._hay_solapamiento(sesion):
                raise ValidationError({
                    'hora_inicio': f'⚠️ CHOQUE: El paciente ya tiene sesión de {sesion.hora_inicio.strftime("%H:%M")} a {sesion.hora_fin.strftime("%H:%M")} en {sesion.sucursal}.'
                })
    
    def _validar_choque_profesional(self):
        """El profesional NO puede tener otra sesión al mismo tiempo"""
        sesiones_existentes = Sesion.objects.filter(
            profesional=self.profesional,
            fecha=self.fecha,
            estado__in=['programada', 'realizada', 'realizada_retraso']
        ).exclude(pk=self.pk)
        
        for sesion in sesiones_existentes:
            if self._hay_solapamiento(sesion):
                raise ValidationError({
                    'profesional': f'⚠️ CHOQUE: El profesional ya tiene sesión de {sesion.hora_inicio.strftime("%H:%M")} a {sesion.hora_fin.strftime("%H:%M")} en {sesion.sucursal}.'
                })
    
    def _hay_solapamiento(self, otra_sesion):
        """Verificar si hay solapamiento de horarios"""
        inicio1 = datetime.combine(self.fecha, self.hora_inicio)
        fin1 = datetime.combine(self.fecha, self.hora_fin)
        inicio2 = datetime.combine(otra_sesion.fecha, otra_sesion.hora_inicio)
        fin2 = datetime.combine(otra_sesion.fecha, otra_sesion.hora_fin)
        
        return (inicio1 < fin2 and fin1 > inicio2) or (inicio2 < fin1 and fin2 > inicio1)
    
    def save(self, *args, **kwargs):
        # Validar antes de guardar
        self.full_clean()
        
        # 🆕 NUEVA LÓGICA: Ajustar monto según estado
        if self.estado in ['permiso', 'cancelada', 'reprogramada']:
            self.monto_cobrado = Decimal('0.00')
        
        super().save(*args, **kwargs)
            
    def _actualizar_cuenta_corriente(self):
        """Actualizar la cuenta corriente del paciente"""
        try:
            from facturacion.models import CuentaCorriente
            cuenta, created = CuentaCorriente.objects.get_or_create(
                paciente=self.paciente
            )
            cuenta.actualizar_saldo()
        except:
            pass
    
    @classmethod
    def validar_disponibilidad(cls, paciente, profesional, fecha, hora_inicio, hora_fin, sesion_actual=None):
        """
        Valida disponibilidad SIN IMPORTAR la sucursal
        Retorna: (disponible: bool, mensaje: str)
        """
        inicio = datetime.combine(fecha, hora_inicio)
        fin = datetime.combine(fecha, hora_fin)
        
        # Validar paciente
        sesiones_paciente = cls.objects.filter(
            paciente=paciente,
            fecha=fecha,
            estado__in=['programada', 'realizada', 'realizada_retraso']
        )
        if sesion_actual:
            sesiones_paciente = sesiones_paciente.exclude(pk=sesion_actual.pk)
        
        for sesion in sesiones_paciente:
            s_inicio = datetime.combine(fecha, sesion.hora_inicio)
            s_fin = datetime.combine(fecha, sesion.hora_fin)
            if (inicio < s_fin and fin > s_inicio):
                return False, f"⚠️ Paciente ocupado de {sesion.hora_inicio.strftime('%H:%M')} a {sesion.hora_fin.strftime('%H:%M')} en {sesion.sucursal}"
        
        # Validar profesional
        sesiones_profesional = cls.objects.filter(
            profesional=profesional,
            fecha=fecha,
            estado__in=['programada', 'realizada', 'realizada_retraso']
        )
        if sesion_actual:
            sesiones_profesional = sesiones_profesional.exclude(pk=sesion_actual.pk)
        
        for sesion in sesiones_profesional:
            s_inicio = datetime.combine(fecha, sesion.hora_inicio)
            s_fin = datetime.combine(fecha, sesion.hora_fin)
            if (inicio < s_fin and fin > s_inicio):
                return False, f"⚠️ Profesional ocupado de {sesion.hora_inicio.strftime('%H:%M')} a {sesion.hora_fin.strftime('%H:%M')} en {sesion.sucursal}"
        
        return True, "✅ Horario disponible"