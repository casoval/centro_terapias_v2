from django.db import models
from django.contrib.auth.models import User

class Profesional(models.Model):
    """Profesionales que atienden en el centro"""
    
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)
    especialidad = models.CharField(max_length=100)
    telefono = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    
    # Servicios que puede ofrecer
    servicios = models.ManyToManyField(
        'servicios.TipoServicio',
        related_name='profesionales'
    )
    
    activo = models.BooleanField(default=True)
    fecha_ingreso = models.DateField(auto_now_add=True)
    
    class Meta:
        verbose_name = 'Profesional'
        verbose_name_plural = 'Profesionales'
        ordering = ['apellido', 'nombre']
    
    def __str__(self):
        return f"{self.apellido}, {self.nombre}"
    
    @property
    def nombre_completo(self):
        return f"{self.nombre} {self.apellido}"