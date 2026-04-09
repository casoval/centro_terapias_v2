from django.db import models


class ConversacionAgente(models.Model):
    TIPO_AGENTE = [
        ('publico',      'Agente Público'),
        ('paciente',     'Agente Paciente'),
        ('superusuario', 'Agente Superusuario'),
    ]
    ROL_CHOICES = [
        ('user',      'Usuario'),
        ('assistant', 'Asistente'),
    ]

    agente       = models.CharField(max_length=20, choices=TIPO_AGENTE, default='publico')
    telefono     = models.CharField(max_length=20, db_index=True)
    rol          = models.CharField(max_length=10, choices=ROL_CHOICES)
    contenido    = models.TextField()
    modelo_usado = models.CharField(max_length=60, blank=True)
    creado       = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['creado']
        verbose_name = 'Mensaje de Agente'
        verbose_name_plural = 'Historial de Agentes'

    def __str__(self):
        return f"[{self.get_agente_display()}] {self.telefono} — {self.rol} ({self.creado:%d/%m %H:%M})"


class ConfigAgente(models.Model):
    TIPO_AGENTE = [
        ('publico',      'Agente Público'),
        ('paciente',     'Agente Paciente'),
        ('superusuario', 'Agente Superusuario'),
    ]

    agente      = models.CharField(max_length=20, choices=TIPO_AGENTE, unique=True)
    activo      = models.BooleanField(default=True)
    prompt      = models.TextField(help_text='Prompt del sistema para este agente')
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Configuración de Agente'
        verbose_name_plural = 'Configuración de Agentes'

    def __str__(self):
        estado = '✅' if self.activo else '❌'
        return f"{estado} {self.get_agente_display()}"


class ModoHumano(models.Model):
    """
    Controla si un número específico está en modo humano (IA desactivada)
    o en modo bot (IA activa).
    Se activa automáticamente cuando el staff responde desde su celular.
    """
    SUCURSAL_CHOICES = [
        (3, 'Sede Japón'),
        (4, 'Sede Camacho'),
    ]

    telefono     = models.CharField(max_length=20, unique=True, db_index=True)
    modo_humano  = models.BooleanField(default=False)
    sucursal_id  = models.IntegerField(choices=SUCURSAL_CHOICES, default=3)
    activado_por = models.CharField(max_length=100, blank=True)
    activado_en  = models.DateTimeField(null=True, blank=True)
    actualizado  = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Modo Humano'
        verbose_name_plural = 'Modos Humano'
        ordering = ['-actualizado']

    def __str__(self):
        estado = '👤 Humano' if self.modo_humano else '🤖 Bot'
        return f"{estado} — {self.telefono}"


class SucursalIA(models.Model):
    """
    Control global de la IA por sucursal.
    Si ia_activa=False, el agente NO responde a NINGÚN mensaje
    de esa sucursal, independientemente del modo individual.
    """
    SUCURSAL_CHOICES = [
        (3, 'Sede Japón'),
        (4, 'Sede Camacho'),
    ]

    sucursal_id  = models.IntegerField(choices=SUCURSAL_CHOICES, unique=True)
    ia_activa    = models.BooleanField(default=True)
    cambiado_por = models.CharField(max_length=100, blank=True)
    cambiado_en  = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Control IA por Sucursal'
        verbose_name_plural = 'Control IA por Sucursal'

    def __str__(self):
        nombre = dict(self.SUCURSAL_CHOICES).get(self.sucursal_id, str(self.sucursal_id))
        estado = '🤖 IA activa' if self.ia_activa else '⏸ IA suspendida'
        return f"{estado} — {nombre}"

    @classmethod
    def esta_activa(cls, sucursal_id: int) -> bool:
        """Devuelve True si la IA está activa para esa sucursal."""
        obj, _ = cls.objects.get_or_create(
            sucursal_id=sucursal_id,
            defaults={'ia_activa': True}
        )
        return obj.ia_activa