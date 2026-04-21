from django.db import models


# ── Lista centralizada de agentes ────────────────────────────────────────────
# Definida UNA SOLA VEZ aquí para que todos los modelos la reutilicen.
# Al agregar un nuevo agente solo se modifica este lugar.
TIPO_AGENTE = [
    ('publico',       'Agente Público'),
    ('paciente',      'Agente Paciente'),
    ('superusuario',  'Agente Superusuario'),
    ('recepcionista', 'Agente Recepcionista'),
    ('profesional',   'Agente Profesional'),
    ('gerente',       'Agente Gerente'),
]

# Límites de historial por defecto para cada agente (editable desde ConfigAgente)
MAX_HISTORIAL_DEFAULTS = {
    'publico':       20,
    'paciente':      30,
    'recepcionista': 15,
    'profesional':   20,
    'gerente':       15,
    'superusuario':  10,
}


class ConversacionAgente(models.Model):
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
    agente        = models.CharField(max_length=20, choices=TIPO_AGENTE, unique=True)
    activo        = models.BooleanField(default=True)
    prompt        = models.TextField(help_text='Prompt del sistema para este agente')
    max_historial = models.PositiveIntegerField(
        default=20,
        help_text=(
            'Número máximo de mensajes del historial que se envían a la IA. '
            'Más mensajes = más contexto pero mayor costo. '
            'Recomendado: Público 20, Paciente 30, Recepcionista 15, '
            'Profesional 20, Gerente 15, Superusuario 10.'
        )
    )
    actualizado   = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Configuración de Agente'
        verbose_name_plural = 'Configuración de Agentes'

    def __str__(self):
        estado = '✅' if self.activo else '❌'
        return f"{estado} {self.get_agente_display()} (historial: {self.max_historial} msgs)"

    @classmethod
    def get_max_historial(cls, tipo_agente: str) -> int:
        """
        Devuelve el límite de historial configurado para un agente.
        Si no existe configuración en BD, usa el valor por defecto del diccionario.
        """
        try:
            config = cls.objects.get(agente=tipo_agente)
            return config.max_historial
        except cls.DoesNotExist:
            return MAX_HISTORIAL_DEFAULTS.get(tipo_agente, 20)


class StaffAgente(models.Model):
    """
    Registra el número de WhatsApp del dueño del centro (Superusuario).
    Solo debe existir UN registro.

    Recepcionistas y Gerentes se identifican por PerfilUsuario.telefono
    y no necesitan registro aquí.
    """
    telefono  = models.CharField(
        max_length=20,
        unique=True,
        db_index=True,
        help_text='Número SIN prefijo de país. Ej: 76543210',
    )
    nombre    = models.CharField(
        max_length=100,
        help_text='Nombre de referencia — solo para identificar en el admin',
    )
    activo    = models.BooleanField(default=True)
    creado    = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Superusuario WhatsApp (Dueño)'
        verbose_name_plural = 'Superusuario WhatsApp (Dueño)'

    def __str__(self):
        estado = '✅' if self.activo else '❌'
        return f"{estado} {self.nombre} ({self.telefono}) — Superusuario"

    @classmethod
    def buscar_por_telefono(cls, telefono: str):
        """
        Busca el superusuario por teléfono.
        Retorna (instancia, 'superusuario') o (None, None).
        """
        tel = telefono.strip().replace(' ', '').replace('-', '')
        if tel.startswith('+591'):
            tel = tel[4:]
        elif tel.startswith('591') and len(tel) > 9:
            tel = tel[3:]

        try:
            staff = cls.objects.get(telefono=tel, activo=True)
            return staff, 'superusuario'
        except cls.DoesNotExist:
            return None, None


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