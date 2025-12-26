from django.db import models
from servicios.models import TipoServicio, Sucursal
from datetime import date


class Paciente(models.Model):
    """Modelo para gestionar pacientes del centro"""
    
    GENERO_CHOICES = [
        ('M', 'Masculino'),
        ('F', 'Femenino'),
        ('O', 'Otro'),
    ]
    
    PARENTESCO_CHOICES = [
        ('madre', 'Madre'),
        ('padre', 'Padre'),
        ('tutor', 'Tutor/a Legal'),
        ('abuelo', 'Abuelo/a'),
        ('tio', 'Tío/a'),
        ('hermano', 'Hermano/a'),
        ('otro', 'Otro'),
    ]
    
    ESTADO_CHOICES = [
        ('activo', 'Activo'),
        ('inactivo', 'Inactivo'),
    ]
    
    # Sucursales donde puede ser atendido
    sucursales = models.ManyToManyField(
        Sucursal,
        related_name='pacientes',
        help_text='Sucursales donde puede ser atendido este paciente'
    )
    
    # Información del paciente
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)
    fecha_nacimiento = models.DateField()
    genero = models.CharField(max_length=1, choices=GENERO_CHOICES)
    
    # Información del tutor
    nombre_tutor = models.CharField(max_length=200)
    parentesco = models.CharField(max_length=20, choices=PARENTESCO_CHOICES)
    telefono_tutor = models.CharField(max_length=20)
    email_tutor = models.EmailField(blank=True, null=True)
    direccion = models.TextField(blank=True)
    
    # Información clínica
    diagnostico = models.TextField(blank=True, help_text='Diagnóstico o motivo de consulta')
    observaciones_medicas = models.TextField(blank=True)
    alergias = models.TextField(blank=True)
    
    # Estado
    estado = models.CharField(max_length=10, choices=ESTADO_CHOICES, default='activo')
    
    # Metadata
    fecha_registro = models.DateTimeField(auto_now_add=True)
    fecha_modificacion = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Paciente'
        verbose_name_plural = 'Pacientes'
        ordering = ['apellido', 'nombre']
    
    def __str__(self):
        return f"{self.nombre_completo} ({self.edad} años)"
    
    @property
    def nombre_completo(self):
        """Retorna nombre completo del paciente"""
        return f"{self.nombre} {self.apellido}"
    
    @property
    def edad(self):
        """Calcula edad actual del paciente"""
        hoy = date.today()
        edad = hoy.year - self.fecha_nacimiento.year
        
        # Ajustar si aún no cumplió años este año
        if hoy.month < self.fecha_nacimiento.month or \
           (hoy.month == self.fecha_nacimiento.month and hoy.day < self.fecha_nacimiento.day):
            edad -= 1
        
        return edad
    
    def tiene_sucursal(self, sucursal):
        """
        ✅ Verifica si el paciente puede ser atendido en una sucursal específica
        """
        return self.sucursales.filter(id=sucursal.id).exists()
    
    def tiene_servicio_activo(self, servicio):
        """
        Verifica si el paciente tiene un servicio específico activo
        """
        return self.servicios.filter(servicio=servicio, activo=True).exists()
    
    def get_costo_servicio(self, servicio):
        """
        Obtiene el costo personalizado del servicio para este paciente
        Retorna None si no tiene el servicio configurado
        """
        try:
            paciente_servicio = self.servicios.get(servicio=servicio, activo=True)
            return paciente_servicio.costo_sesion
        except PacienteServicio.DoesNotExist:
            return None


class PacienteServicio(models.Model):
    """
    Relación entre Paciente y Servicio con costo personalizado
    Permite que cada paciente tenga un precio diferente por servicio
    """
    
    paciente = models.ForeignKey(
        Paciente,
        on_delete=models.CASCADE,
        related_name='servicios'
    )
    
    servicio = models.ForeignKey(
        TipoServicio,
        on_delete=models.PROTECT,
        related_name='pacientes'
    )
    
    # Costo personalizado para este paciente
    costo_sesion = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Costo por sesión para este paciente (se autocompleta con el precio base)'
    )
    
    # Estado
    activo = models.BooleanField(
        default=True,
        help_text='Si está inactivo, no se puede programar sesiones con este servicio'
    )
    
    observaciones = models.TextField(
        blank=True,
        help_text='Observaciones específicas sobre este servicio para el paciente'
    )
    
    # Metadata
    fecha_inicio = models.DateTimeField(auto_now_add=True)
    fecha_modificacion = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Servicio del Paciente'
        verbose_name_plural = 'Servicios de los Pacientes'
        unique_together = ['paciente', 'servicio']
        ordering = ['-activo', 'servicio__nombre']
    
    def __str__(self):
        return f"{self.paciente.nombre_completo} - {self.servicio.nombre}"
    
    def save(self, *args, **kwargs):
        """
        ✅ CRÍTICO: Autocompletar costo_sesion con el precio base si está vacío
        """
        # Si costo_sesion es None o 0, usar el precio base del servicio
        if (self.costo_sesion is None or self.costo_sesion == 0) and self.servicio:
            self.costo_sesion = self.servicio.costo_base
        
        super().save(*args, **kwargs)
    
    @property
    def diferencia_precio(self):
        """Calcula la diferencia entre el costo personalizado y el precio base"""
        if self.costo_sesion and self.servicio:
            return self.costo_sesion - self.servicio.costo_base
        return 0
    
    @property
    def tiene_descuento(self):
        """Verifica si tiene descuento aplicado"""
        return self.diferencia_precio < 0
    
    @property
    def tiene_recargo(self):
        """Verifica si tiene recargo aplicado"""
        return self.diferencia_precio > 0
    
    @property
    def es_precio_estandar(self):
        """Verifica si usa el precio estándar"""
        return self.diferencia_precio == 0