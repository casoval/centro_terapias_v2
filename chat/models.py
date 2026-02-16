from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class Conversacion(models.Model):
    """
    Conversación entre dos usuarios (genérica User-to-User)
    ✅ Ya NO es solo Paciente-Profesional
    """
    
    # Participantes de la conversación
    usuario_1 = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='conversaciones_como_usuario1',
        help_text='Primer participante de la conversación'
    )
    
    usuario_2 = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='conversaciones_como_usuario2',
        help_text='Segundo participante de la conversación'
    )
    
    # Metadata
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    ultima_actualizacion = models.DateTimeField(auto_now=True)
    activa = models.BooleanField(default=True)
    
    class Meta:
        verbose_name = 'Conversación'
        verbose_name_plural = 'Conversaciones'
        unique_together = ['usuario_1', 'usuario_2']
        ordering = ['-ultima_actualizacion']
        indexes = [
            models.Index(fields=['usuario_1', 'usuario_2']),
            models.Index(fields=['-ultima_actualizacion']),
        ]
    
    def __str__(self):
        return f"Chat: {self.usuario_1.get_full_name() or self.usuario_1.username} ↔ {self.usuario_2.get_full_name() or self.usuario_2.username}"
    
    def get_otro_usuario(self, usuario_actual):
        """Obtiene el otro participante de la conversación"""
        return self.usuario_2 if self.usuario_1 == usuario_actual else self.usuario_1
    
    def es_participante(self, usuario):
        """Verifica si un usuario es participante de esta conversación"""
        return self.usuario_1 == usuario or self.usuario_2 == usuario
    
    def get_ultimo_mensaje(self):
        """Obtiene el último mensaje de la conversación"""
        return self.mensajes.order_by('-fecha_envio').first()
    
    def get_mensajes_no_leidos(self, usuario):
        """Obtiene la cantidad de mensajes no leídos para un usuario"""
        return self.mensajes.filter(
            leido=False
        ).exclude(
            remitente=usuario
        ).count()
    
    def marcar_mensajes_como_leidos(self, usuario):
        """Marca todos los mensajes como leídos para un usuario"""
        self.mensajes.filter(
            leido=False
        ).exclude(
            remitente=usuario
        ).update(
            leido=True,
            fecha_lectura=timezone.now()
        )


class Mensaje(models.Model):
    """
    Mensajes individuales dentro de una conversación
    """
    
    conversacion = models.ForeignKey(
        Conversacion,
        on_delete=models.CASCADE,
        related_name='mensajes'
    )
    
    remitente = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='mensajes_enviados'
    )
    
    contenido = models.TextField(max_length=1000)
    
    # Control de lectura
    leido = models.BooleanField(default=False)
    fecha_envio = models.DateTimeField(auto_now_add=True)
    fecha_lectura = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        verbose_name = 'Mensaje'
        verbose_name_plural = 'Mensajes'
        ordering = ['fecha_envio']
        indexes = [
            models.Index(fields=['conversacion', 'fecha_envio']),
            models.Index(fields=['remitente', '-fecha_envio']),
        ]
    
    def __str__(self):
        preview = self.contenido[:50] + '...' if len(self.contenido) > 50 else self.contenido
        return f"{self.remitente.username}: {preview}"
    
    def marcar_como_leido(self):
        """Marca el mensaje como leído"""
        if not self.leido:
            self.leido = True
            self.fecha_lectura = timezone.now()
            self.save(update_fields=['leido', 'fecha_lectura'])


class NotificacionChat(models.Model):
    """
    Notificaciones de mensajes nuevos
    """
    
    usuario = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='notificaciones_chat'
    )
    
    conversacion = models.ForeignKey(
        Conversacion,
        on_delete=models.CASCADE,
        related_name='notificaciones'
    )
    
    mensaje = models.ForeignKey(
        Mensaje,
        on_delete=models.CASCADE,
        related_name='notificaciones'
    )
    
    leida = models.BooleanField(default=False)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = 'Notificación de Chat'
        verbose_name_plural = 'Notificaciones de Chat'
        ordering = ['-fecha_creacion']
        indexes = [
            models.Index(fields=['usuario', 'leida']),
            models.Index(fields=['-fecha_creacion']),
        ]
    
    def __str__(self):
        return f"Notificación para {self.usuario.username} - {self.mensaje}"