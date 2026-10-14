from django.db import models
from django.contrib.auth.models import User
from cloudinary.models import CloudinaryField


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
    
    # ==================== FOTO DEL PROFESIONAL ====================
    foto = CloudinaryField(
        'foto',
        blank=True,
        null=True,
        folder='profesionales',  # Carpeta en Cloudinary
        transformation={
            'width': 400,
            'height': 400,
            'crop': 'fill',
            'gravity': 'face',  # Enfoque en rostro
            'quality': 'auto',  # Calidad automática
            'fetch_format': 'auto'  # Formato óptimo (WebP, etc)
        },
        help_text='Foto del profesional (se optimizará automáticamente)'
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
    
    @property
    def tiene_foto(self):
        """Verifica si tiene foto registrada"""
        return bool(self.foto)
    
    def get_foto_url(self, width=400, height=400):
        """
        Obtiene URL de la foto con transformaciones específicas
        """
        if self.foto:
            try:
                return self.foto.build_url(
                    width=width,
                    height=height,
                    crop='fill',
                    gravity='face',
                    quality='auto',
                    fetch_format='auto'
                )
            except Exception as e:
                # Si falla la transformación, retornar URL básica
                return self.foto.url if hasattr(self.foto, 'url') else None
        return None

    def get_foto_thumbnail(self):
        """Obtiene URL de thumbnail (100x100)"""
        return self.get_foto_url(width=100, height=100)
    
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