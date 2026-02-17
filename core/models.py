from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

# ✅ Variable de control para signals
_disable_signals = False

class PerfilUsuario(models.Model):
    """
    Perfil extendido del usuario con roles y permisos
    """
    
    # Tipos de roles - ✅ AGREGADO ROL PACIENTE
    ROL_CHOICES = [
        ('paciente', 'Paciente'),
        ('profesional', 'Profesional'),
        ('recepcionista', 'Recepcionista'),
        ('gerente', 'Gerente'),
    ]

    # ✅ NUEVO: Opciones de tema de chat — disponibles para TODOS los roles
    TEMA_CHAT_CHOICES = [
        ('default', 'Normal'),
        ('arcoiris', 'Arcoíris'),
        ('oceano', 'Océano'),
        ('espacio', 'Espacio'),
        ('selva', 'Safari'),
        ('dulces', 'Dulces'),
    ]
    
    user = models.OneToOneField(
        User, 
        on_delete=models.CASCADE, 
        related_name='perfil'
    )
    
    rol = models.CharField(
        max_length=20,
        choices=ROL_CHOICES,
        null=True,
        blank=True,
        help_text='Rol del usuario en el sistema'
    )

    # ✅ NUEVO: Campo de tema de chat para todos los roles
    tema_chat = models.CharField(
        max_length=20,
        choices=TEMA_CHAT_CHOICES,
        default='default',
        help_text='Tema visual del chat (aplica a todos los roles)'
    )
    
    # Relación con Profesional (si aplica)
    profesional = models.OneToOneField(
        'profesionales.Profesional',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='perfil_usuario',
        help_text='Vinculación con el profesional (si es profesional)'
    )
    
    # ✅ Relación con Paciente (si aplica)
    paciente = models.OneToOneField(
        'pacientes.Paciente',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='perfil_usuario',
        help_text='Vinculación con el paciente (si es paciente)'
    )
    
    # Sucursales asignadas (para Recepcionista y Gerente)
    sucursales = models.ManyToManyField(
        'servicios.Sucursal',
        blank=True,
        related_name='usuarios_asignados',
        help_text='Sucursales a las que tiene acceso este usuario'
    )
    
    # Metadata
    activo = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_modificacion = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Perfil de Usuario'
        verbose_name_plural = 'Perfiles de Usuarios'
    
    def __str__(self):
        rol_display = self.get_rol_display() if self.rol else 'Sin rol'
        return f"{self.user.username} - {rol_display}"
    
    # ==================== MÉTODOS DE PERMISOS ====================
    
    def es_superadmin(self):
        """Verifica si es superusuario"""
        return self.user.is_superuser
    
    def es_paciente(self):
        """✅ Verifica si tiene rol de paciente"""
        return self.rol == 'paciente'
    
    def es_profesional(self):
        """Verifica si tiene rol de profesional"""
        return self.rol == 'profesional'
    
    def es_recepcionista(self):
        """Verifica si tiene rol de recepcionista"""
        return self.rol == 'recepcionista'
    
    def es_gerente(self):
        """Verifica si tiene rol de gerente"""
        return self.rol == 'gerente'
    
    def puede_crear_pacientes(self):
        """Todos excepto profesionales y pacientes pueden crear pacientes"""
        if self.es_superadmin():
            return True
        return self.rol in ['recepcionista', 'gerente']
    
    def puede_crear_sesiones(self):
        """Recepcionistas y gerentes pueden crear sesiones"""
        if self.es_superadmin():
            return True
        return self.rol in ['recepcionista', 'gerente']
    
    def puede_crear_proyectos(self):
        """Recepcionistas y gerentes pueden crear proyectos"""
        if self.es_superadmin():
            return True
        return self.rol in ['recepcionista', 'gerente']
    
    def puede_registrar_pagos(self):
        """Recepcionistas y gerentes pueden registrar pagos"""
        if self.es_superadmin():
            return True
        return self.rol in ['recepcionista', 'gerente']
    
    def puede_crear_servicios(self):
        """Solo superadmin y gerentes pueden crear servicios"""
        if self.es_superadmin():
            return True
        return self.rol == 'gerente'
    
    def puede_crear_profesionales(self):
        """Solo superadmin y gerentes pueden crear profesionales"""
        if self.es_superadmin():
            return True
        return self.rol == 'gerente'
    
    def puede_crear_sucursales(self):
        """Solo superadmin puede crear sucursales"""
        return self.es_superadmin()
    
    def puede_eliminar_sesiones(self):
        """Solo gerentes y superadmin pueden eliminar sesiones"""
        if self.es_superadmin():
            return True
        return self.rol == 'gerente'
    
    def puede_eliminar_proyectos(self):
        """Solo gerentes y superadmin pueden eliminar proyectos"""
        if self.es_superadmin():
            return True
        return self.rol == 'gerente'
    
    def puede_anular_pagos(self):
        """Solo gerentes y superadmin pueden anular pagos"""
        if self.es_superadmin():
            return True
        return self.rol == 'gerente'
    
    def puede_eliminar_pacientes(self):
        """Solo superadmin puede eliminar pacientes"""
        return self.es_superadmin()
    
    def puede_eliminar_profesionales(self):
        """Solo superadmin puede eliminar profesionales"""
        return self.es_superadmin()
    
    def puede_eliminar_servicios(self):
        """Solo superadmin puede eliminar servicios"""
        return self.es_superadmin()
    
    def puede_eliminar_sucursales(self):
        """Solo superadmin puede eliminar sucursales"""
        return self.es_superadmin()
    
    def puede_ver_reportes(self):
        """Gerentes y superadmin pueden ver reportes completos"""
        if self.es_superadmin():
            return True
        return self.rol == 'gerente'
    
    def puede_editar_observaciones_privadas(self):
        """Profesionales solo pueden editar observaciones privadas"""
        return self.es_profesional()
    
    # ✅ PERMISOS PARA PACIENTES
    def puede_ver_solo_sus_datos(self):
        """Los pacientes solo pueden ver sus propios datos"""
        return self.es_paciente()
    
    def puede_acceder_dashboard_completo(self):
        """Los pacientes NO pueden acceder al dashboard completo"""
        if self.es_paciente():
            return False
        return True
    
    def get_sucursales(self):
        """
        Retorna las sucursales del usuario según su rol
        - Superadmin: None (acceso a todas)
        - Profesional: sucursales del profesional vinculado
        - Recepcionista/Gerente: sucursales asignadas
        - Paciente: None (no aplica)
        """
        if self.es_superadmin():
            return None  # Acceso a todas
        
        if self.es_profesional() and self.profesional:
            return self.profesional.sucursales.all()
        
        if self.es_paciente():
            return None  # Los pacientes no tienen sucursales asignadas
        
        return self.sucursales.all()
    
    def tiene_acceso_sucursal(self, sucursal):
        """
        Verifica si el usuario tiene acceso a una sucursal específica
        """
        if self.es_superadmin():
            return True
        
        if self.es_paciente():
            return False  # Los pacientes no filtran por sucursal
        
        sucursales = self.get_sucursales()
        if sucursales is None:
            return False
        
        return sucursales.filter(id=sucursal.id).exists()


# ==================== SIGNALS ====================

# Variable de control para desactivar signals durante operaciones del admin
_disable_signals = False

@receiver(post_save, sender=User)
def gestionar_perfil_usuario(sender, instance, created, raw, **kwargs):
    """
    Gestiona la creación del perfil de usuario
    ✅ Se desactiva cuando viene del admin
    """
    global _disable_signals
    
    # Si las signals están desactivadas, no hacer nada
    if _disable_signals:
        return
    
    # Ignorar si es fixture/loaddata
    if raw:
        return
    
    # No crear perfil para superusuarios
    if instance.is_superuser:
        return
    
    # Solo crear si es nuevo Y no tiene perfil
    if created:
        # Doble verificación para evitar duplicados
        if not hasattr(instance, 'perfil'):
            try:
                PerfilUsuario.objects.get_or_create(
                    user=instance,
                    defaults={'activo': True}
                )
            except Exception as e:
                # Si falla, registrar el error pero no romper la aplicación
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Error creando perfil para {instance.username}: {e}")