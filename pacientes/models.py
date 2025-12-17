from django.db import models
from datetime import date

class Paciente(models.Model):
    """Modelo para pacientes (niños y adolescentes)"""
    
    ESTADO_CHOICES = [
        ('activo', 'Activo'),
        ('inactivo', 'Inactivo'),
        ('suspendido', 'Suspendido'),
    ]
    
    PARENTESCO_CHOICES = [
        ('padre', 'Padre'),
        ('madre', 'Madre'),
        ('tutor', 'Tutor Legal'),
        ('abuelo', 'Abuelo/a'),
        ('tio', 'Tío/a'),
        ('hermano', 'Hermano/a'),
        ('otro', 'Otro'),
    ]
    
    # ✅ NUEVO: Relación ManyToMany con Sucursales
    sucursales = models.ManyToManyField(
        'servicios.Sucursal',
        related_name='pacientes',
        help_text="Sucursales donde puede ser atendido el paciente"
    )
    
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
    # ✅ NUEVO: Campo parentesco
    parentesco = models.CharField(
        max_length=20,
        choices=PARENTESCO_CHOICES,
        default='tutor',
        help_text="Relación del tutor con el paciente"
    )
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
        indexes = [
            models.Index(fields=['estado']),
            models.Index(fields=['apellido', 'nombre']),
        ]
    
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
    
    def tiene_sucursal(self, sucursal):
        """Verifica si el paciente tiene asignada una sucursal"""
        return self.sucursales.filter(id=sucursal.id).exists()


class PacienteServicio(models.Model):
    """Relación entre paciente y servicios contratados"""
    
    paciente = models.ForeignKey(Paciente, on_delete=models.CASCADE)
    servicio = models.ForeignKey('servicios.TipoServicio', on_delete=models.CASCADE)
    # ✅ El costo_sesion se autocompletará con el costo_base del servicio
    costo_sesion = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Costo en Bs. por sesión (puede personalizarse por paciente)"
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
    
    def save(self, *args, **kwargs):
        # ✅ Si no se especifica costo, usar el costo_base del servicio
        if not self.costo_sesion and self.servicio:
            self.costo_sesion = self.servicio.costo_base
        super().save(*args, **kwargs)