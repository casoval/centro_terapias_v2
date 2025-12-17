from django.db import models
from django.contrib.auth.models import User

class Profesional(models.Model):
    """Profesionales que atienden en el centro"""
    
    # Relación con User (para permisos)
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="Usuario del sistema para este profesional"
    )
    
    # ✅ NUEVO: Relación ManyToMany con Sucursales
    sucursales = models.ManyToManyField(
        'servicios.Sucursal',
        related_name='profesionales',
        help_text="Sucursales donde trabaja el profesional"
    )
    
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)
    especialidad = models.CharField(max_length=100)
    telefono = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    
    # Servicios que puede ofrecer
    servicios = models.ManyToManyField(
        'servicios.TipoServicio',
        related_name='profesionales',
        help_text="Servicios/terapias que este profesional puede ofrecer"
    )
    
    activo = models.BooleanField(default=True)
    fecha_ingreso = models.DateField(auto_now_add=True)
    
    class Meta:
        verbose_name = 'Profesional'
        verbose_name_plural = 'Profesionales'
        ordering = ['apellido', 'nombre']
        indexes = [
            models.Index(fields=['activo']),
            models.Index(fields=['apellido', 'nombre']),
        ]
    
    def __str__(self):
        return f"{self.apellido}, {self.nombre}"
    
    @property
    def nombre_completo(self):
        return f"{self.nombre} {self.apellido}"
    
    def puede_atender_servicio(self, servicio):
        """Verifica si el profesional puede ofrecer un servicio específico"""
        return self.servicios.filter(id=servicio.id).exists()
    
    def tiene_sucursal(self, sucursal):
        """Verifica si el profesional trabaja en una sucursal específica"""
        return self.sucursales.filter(id=sucursal.id).exists()
    
    def puede_atender_en(self, sucursal, servicio):
        """Verifica si puede atender un servicio en una sucursal específica"""
        return self.tiene_sucursal(sucursal) and self.puede_atender_servicio(servicio)
    
    def get_pacientes(self):
        """Retorna los pacientes que atiende este profesional"""
        from pacientes.models import Paciente
        return Paciente.objects.filter(
            sesiones__profesional=self
        ).distinct()