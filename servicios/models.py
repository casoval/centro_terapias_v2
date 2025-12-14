from django.db import models

class TipoServicio(models.Model):
    """Tipos de terapia/servicio que ofrece el centro"""
    
    nombre = models.CharField(max_length=100, unique=True)
    descripcion = models.TextField(blank=True)
    duracion_minutos = models.IntegerField(
        default=60,
        help_text="Duración estándar en minutos"
    )
    costo_base = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Costo base en Bs."
    )
    color = models.CharField(
        max_length=7,
        default='#3B82F6',
        help_text="Color para el calendario (formato: #RRGGBB)"
    )
    activo = models.BooleanField(default=True)
    
    class Meta:
        verbose_name = 'Tipo de Servicio'
        verbose_name_plural = 'Tipos de Servicios'
        ordering = ['nombre']
    
    def __str__(self):
        return self.nombre


class Sucursal(models.Model):
    """Sucursales del centro"""
    
    nombre = models.CharField(max_length=100)
    direccion = models.TextField()
    telefono = models.CharField(max_length=20, blank=True)
    activa = models.BooleanField(default=True)
    
    class Meta:
        verbose_name = 'Sucursal'
        verbose_name_plural = 'Sucursales'
        ordering = ['nombre']
    
    def __str__(self):
        return self.nombre