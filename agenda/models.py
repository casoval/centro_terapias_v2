from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db.models import Q
from pacientes.models import Paciente
from servicios.models import TipoServicio, Sucursal
from profesionales.models import Profesional
from datetime import datetime, timedelta


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
    
    # Cobros
    monto_cobrado = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Monto a cobrar por esta sesión"
    )
    pagado = models.BooleanField(default=False)
    fecha_pago = models.DateField(null=True, blank=True)
    
    # Observaciones
    observaciones = models.TextField(blank=True)
    notas_sesion = models.TextField(
        blank=True,
        help_text="Notas clínicas/evolución de la sesión"
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
            models.Index(fields=['pagado']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['paciente', 'fecha', 'hora_inicio'],
                name='unique_paciente_fecha_hora'
            )
        ]
    
    def __str__(self):
        return f"{self.fecha} {self.hora_inicio} - {self.paciente} - {self.servicio}"
    
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
        
        # 🚫 VALIDAR CHOQUES DE HORARIOS (SIN IMPORTAR SUCURSAL)
        self._validar_choque_paciente()
        self._validar_choque_profesional()
    
    def _validar_choque_paciente(self):
        """
        ✅ CRÍTICO: El paciente NO puede tener otra sesión al mismo tiempo,
        INDEPENDIENTEMENTE de la sucursal
        """
        # Buscar sesiones del mismo paciente en la misma fecha (EN CUALQUIER SUCURSAL)
        sesiones_existentes = Sesion.objects.filter(
            paciente=self.paciente,
            fecha=self.fecha,
            estado__in=['programada', 'realizada', 'realizada_retraso']
        ).exclude(pk=self.pk)  # Excluir la sesión actual si está editando
        
        for sesion in sesiones_existentes:
            if self._hay_solapamiento(sesion):
                raise ValidationError({
                    'hora_inicio': f'⚠️ CHOQUE DE HORARIOS: El paciente {self.paciente} ya tiene una sesión programada de {sesion.hora_inicio.strftime("%H:%M")} a {sesion.hora_fin.strftime("%H:%M")} en {sesion.sucursal} ({sesion.servicio}).'
                })
    
    def _validar_choque_profesional(self):
        """
        ✅ CRÍTICO: El profesional NO puede tener otra sesión al mismo tiempo,
        INDEPENDIENTEMENTE de la sucursal
        """
        # Buscar sesiones del mismo profesional en la misma fecha (EN CUALQUIER SUCURSAL)
        sesiones_existentes = Sesion.objects.filter(
            profesional=self.profesional,
            fecha=self.fecha,
            estado__in=['programada', 'realizada', 'realizada_retraso']
        ).exclude(pk=self.pk)
        
        for sesion in sesiones_existentes:
            if self._hay_solapamiento(sesion):
                raise ValidationError({
                    'profesional': f'⚠️ CHOQUE DE HORARIOS: El/la profesional {self.profesional} ya tiene una sesión programada de {sesion.hora_inicio.strftime("%H:%M")} a {sesion.hora_fin.strftime("%H:%M")} en {sesion.sucursal} con {sesion.paciente}.'
                })
    
    def _hay_solapamiento(self, otra_sesion):
        """Verificar si hay solapamiento de horarios con otra sesión"""
        inicio1 = datetime.combine(self.fecha, self.hora_inicio)
        fin1 = datetime.combine(self.fecha, self.hora_fin)
        inicio2 = datetime.combine(otra_sesion.fecha, otra_sesion.hora_inicio)
        fin2 = datetime.combine(otra_sesion.fecha, otra_sesion.hora_fin)
        
        return (inicio1 < fin2 and fin1 > inicio2) or (inicio2 < fin1 and fin2 > inicio1)
    
    def save(self, *args, **kwargs):
        # Validar antes de guardar
        self.full_clean()
        super().save(*args, **kwargs)
        
        # Actualizar cuenta corriente del paciente si cambió el estado o monto
        if self.estado in ['realizada', 'realizada_retraso']:
            self._actualizar_cuenta_corriente()
    
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
        ✅ CRÍTICO: Valida disponibilidad SIN IMPORTAR la sucursal
        
        Retorna: (disponible: bool, mensaje: str)
        """
        inicio = datetime.combine(fecha, hora_inicio)
        fin = datetime.combine(fecha, hora_fin)
        
        # Validar paciente (EN CUALQUIER SUCURSAL)
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
        
        # Validar profesional (EN CUALQUIER SUCURSAL)
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