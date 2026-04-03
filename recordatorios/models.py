from django.db import models


class RegistroBackup(models.Model):
    TIPO_CHOICES = [('automatico', 'Automático'), ('manual', 'Manual')]

    fecha             = models.DateTimeField(auto_now_add=True)
    tipo              = models.CharField(max_length=20, choices=TIPO_CHOICES, default='automatico')
    exitoso           = models.BooleanField(default=False)
    tamanio_mb        = models.CharField(max_length=20, blank=True)
    duracion_segundos = models.FloatField(null=True, blank=True)
    destinatarios     = models.TextField(blank=True)
    mensaje_error     = models.TextField(blank=True)

    class Meta:
        ordering = ['-fecha']
        verbose_name = 'Registro de Backup'
        verbose_name_plural = 'Registros de Backup'

    def __str__(self):
        estado = '✅' if self.exitoso else '❌'
        return f"{estado} {self.get_tipo_display()} — {self.fecha:%d/%m/%Y %H:%M}"