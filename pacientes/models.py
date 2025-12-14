from django.db import models
from datetime import date

class Paciente(models.Model):
    """Modelo para pacientes (niños y adolescentes)"""
    
    ESTADO_CHOICES = [
        ('activo', 'Activo'),
        ('inactivo', 'Inactivo'),
        ('suspendido', 'Suspendido'),
    ]
    
    # Información del paciente
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)
    fecha_nacimiento = models.DateField()
    genero = models.CharField(
        max_length=1,
        choices=[('M', 'Masculino'), ('F', 'Femenino')]
    )
    
    # Información del tutor/responsable
    nombre_tutor = models.CharField(max_length=200)
    telefono_tutor = models.CharField(max_length=20)
    email_tutor = models.EmailField(blank=True, null=True)
    direccion = models.TextField(blank=True)
    
    # Información clínica
    diagnostico = models.TextField(blank=True)
    observaciones_medicas = models.TextField(blank=True)
    alergias = models.TextField(blank=True)
    
    # Estado
    estado = models.CharField(
        max_length=20,
        choices=ESTADO_CHOICES,
        default='activo'
    )
    
    # Fechas
    fecha_registro = models.DateField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Paciente'
        verbose_name_plural = 'Pacientes'
        ordering = ['apellido', 'nombre']
    
    def __str__(self):
        return f"{self.apellido}, {self.nombre}"
    
    @property
    def nombre_completo(self):
        return f"{self.nombre} {self.apellido}"
    
    @property
    def edad(self):
        """Calcula la edad actual del paciente"""
        today = date.today()
        edad = today.year - self.fecha_nacimiento.year
        if today.month < self.fecha_nacimiento.month or \
           (today.month == self.fecha_nacimiento.month and today.day < self.fecha_nacimiento.day):
            edad -= 1
        return edad


class PacienteServicio(models.Model):
    """Relación entre paciente y servicios contratados"""
    
    paciente = models.ForeignKey(Paciente, on_delete=models.CASCADE)
    servicio = models.ForeignKey('servicios.TipoServicio', on_delete=models.CASCADE)
    costo_sesion = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Costo en Bs. por sesión (puede ser diferente al costo base)"
    )
    activo = models.BooleanField(default=True)
    fecha_inicio = models.DateField(auto_now_add=True)
    observaciones = models.TextField(blank=True)
    
    class Meta:
        verbose_name = 'Servicio del Paciente'
        verbose_name_plural = 'Servicios de Pacientes'
        unique_together = ['paciente', 'servicio']
    
    def __str__(self):
        return f"{self.paciente.nombre_completo} - {self.servicio.nombre}"