import math
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

DIAS_SEMANA = [
    ('LUN', 'Lunes'), ('MAR', 'Martes'), ('MIE', 'Miércoles'),
    ('JUE', 'Jueves'), ('VIE', 'Viernes'), ('SAB', 'Sábado'), ('DOM', 'Domingo'),
]
WEEKDAY_MAP = {0: 'LUN', 1: 'MAR', 2: 'MIE', 3: 'JUE', 4: 'VIE', 5: 'SAB', 6: 'DOM'}


class ZonaAsistencia(models.Model):
    sucursal = models.ForeignKey(
        'servicios.Sucursal', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='zonas_asistencia',
        help_text="Sucursal de referencia (opcional)"
    )
    nombre = models.CharField(max_length=150)
    latitud = models.DecimalField(max_digits=9, decimal_places=6)
    longitud = models.DecimalField(max_digits=9, decimal_places=6)
    radio_metros = models.PositiveIntegerField(default=100)
    activa = models.BooleanField(default=True)
    creada_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Zona de asistencia'
        verbose_name_plural = 'Zonas de asistencia'
        ordering = ['nombre']

    def __str__(self):
        return f"{self.nombre} (radio: {self.radio_metros}m)"

    def contiene_punto(self, lat, lon):
        R = 6371000
        lat1 = math.radians(float(self.latitud))
        lat2 = math.radians(float(lat))
        dlat = math.radians(float(lat) - float(self.latitud))
        dlon = math.radians(float(lon) - float(self.longitud))
        a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
        distancia = R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return distancia <= self.radio_metros, round(distancia, 1)


class HorarioPredeterminado(models.Model):
    """
    Horario base por zona.
    dias_partido: ej ["LUN","MAR","MIE","JUE","VIE"]
    dias_continuo: ej ["SAB"]
    Bloque manana/continuo: hora_entrada, hora_salida, tolerancia_minutos
    Bloque tarde (solo partido): hora_entrada_tarde, hora_salida_tarde, tolerancia_tarde
    """
    zona = models.OneToOneField(
        ZonaAsistencia, on_delete=models.CASCADE,
        related_name='horario_predeterminado'
    )
    dias_partido = models.JSONField(
        default=list,
        help_text='Dias con horario partido. Ej: ["LUN","MAR","MIE","JUE","VIE"]'
    )
    dias_continuo = models.JSONField(
        default=list,
        help_text='Dias con horario continuo. Ej: ["SAB"]'
    )
    hora_entrada = models.TimeField(default='08:00')
    hora_salida = models.TimeField(default='13:00')
    tolerancia_minutos = models.PositiveIntegerField(default=10)
    hora_entrada_tarde = models.TimeField(null=True, blank=True, default='14:00')
    hora_salida_tarde = models.TimeField(null=True, blank=True, default='18:00')
    tolerancia_tarde = models.PositiveIntegerField(null=True, blank=True, default=10)

    class Meta:
        verbose_name = 'Horario predeterminado'
        verbose_name_plural = 'Horarios predeterminados'

    def __str__(self):
        return f"{self.zona.nombre} — Partido: {self.dias_partido} / Continuo: {self.dias_continuo}"

    def tipo_para_dia(self, fecha):
        codigo = WEEKDAY_MAP.get(fecha.weekday())
        if codigo in (self.dias_partido or []):
            return 'partido'
        if codigo in (self.dias_continuo or []):
            return 'continuo'
        return None


class FechaEspecial(models.Model):
    """
    Fecha con horario especial definido por el admin.
    Prioridad maxima sobre cualquier otro horario.
    Si profesionales esta vacio aplica a todos los de la zona.
    """
    TIPO_CHOICES = [
        ('continuo', 'Horario continuo'),
        ('partido', 'Horario partido'),
        ('libre', 'Dia libre'),
    ]
    zona = models.ForeignKey(
        ZonaAsistencia, on_delete=models.CASCADE,
        related_name='fechas_especiales'
    )
    fecha = models.DateField()
    tipo_horario = models.CharField(max_length=10, choices=TIPO_CHOICES)
    profesionales = models.ManyToManyField(
        User, blank=True, related_name='fechas_especiales',
        help_text="Dejar vacio para aplicar a todos los profesionales de la zona"
    )
    motivo = models.CharField(max_length=200, blank=True)

    # Horario especifico para esta fecha (opcional)
    # Si es None usa el horario base de la zona segun el tipo
    hora_entrada_especial = models.TimeField(
        null=True, blank=True,
        help_text="Dejar vacio para usar el horario base de la zona"
    )
    hora_salida_especial = models.TimeField(
        null=True, blank=True,
        help_text="Dejar vacio para usar el horario base de la zona"
    )
    tolerancia_especial = models.PositiveIntegerField(
        null=True, blank=True,
        help_text="Dejar vacio para usar la tolerancia base de la zona"
    )
    # Para horario partido con horario especifico
    hora_entrada_tarde_especial = models.TimeField(
        null=True, blank=True,
        help_text="Solo para tipo partido. Dejar vacio para usar el horario base."
    )
    hora_salida_tarde_especial = models.TimeField(
        null=True, blank=True,
    )
    tolerancia_tarde_especial = models.PositiveIntegerField(null=True, blank=True)

    creado_por = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='fechas_especiales_creadas'
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Fecha especial'
        verbose_name_plural = 'Fechas especiales'
        ordering = ['-fecha']
        unique_together = ['zona', 'fecha']

    def __str__(self):
        return f"{self.zona.nombre} — {self.fecha} ({self.get_tipo_horario_display()})"

    def aplica_a_user(self, user):
        if not self.profesionales.exists():
            return True
        return self.profesionales.filter(pk=user.pk).exists()


class ConfigAsistencia(models.Model):
    """Configuracion por usuario + zona. Puede sobreescribir dias y horarios."""
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='configs_asistencia'
    )
    zona = models.ForeignKey(
        ZonaAsistencia, on_delete=models.CASCADE, related_name='configs'
    )
    dias_partido_custom = models.JSONField(null=True, blank=True)
    dias_continuo_custom = models.JSONField(null=True, blank=True)
    hora_entrada_custom = models.TimeField(null=True, blank=True)
    hora_salida_custom = models.TimeField(null=True, blank=True)
    tolerancia_custom = models.PositiveIntegerField(null=True, blank=True)
    hora_entrada_tarde_custom = models.TimeField(null=True, blank=True)
    hora_salida_tarde_custom = models.TimeField(null=True, blank=True)
    tolerancia_tarde_custom = models.PositiveIntegerField(null=True, blank=True)
    personalizado = models.BooleanField(default=False)
    modificado_por = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='modificaciones_asistencia'
    )
    fecha_modificacion = models.DateTimeField(null=True, blank=True)
    device_id = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = 'Configuracion de asistencia'
        verbose_name_plural = 'Configuraciones de asistencia'
        unique_together = ['user', 'zona']

    def __str__(self):
        tipo = "personalizado" if self.personalizado else "predeterminado"
        return f"{self.user.get_full_name()} — {self.zona.nombre} ({tipo})"

    def get_dias_partido(self):
        if self.personalizado and self.dias_partido_custom is not None:
            return self.dias_partido_custom
        try:
            return self.zona.horario_predeterminado.dias_partido or []
        except HorarioPredeterminado.DoesNotExist:
            return []

    def get_dias_continuo(self):
        if self.personalizado and self.dias_continuo_custom is not None:
            return self.dias_continuo_custom
        try:
            return self.zona.horario_predeterminado.dias_continuo or []
        except HorarioPredeterminado.DoesNotExist:
            return []

    def tipo_para_dia(self, fecha):
        codigo = WEEKDAY_MAP.get(fecha.weekday())
        if codigo in self.get_dias_partido():
            return 'partido'
        if codigo in self.get_dias_continuo():
            return 'continuo'
        return None

    def get_hora_entrada(self):
        if self.personalizado and self.hora_entrada_custom:
            return self.hora_entrada_custom
        try:
            return self.zona.horario_predeterminado.hora_entrada
        except HorarioPredeterminado.DoesNotExist:
            return None

    def get_hora_salida(self):
        if self.personalizado and self.hora_salida_custom:
            return self.hora_salida_custom
        try:
            return self.zona.horario_predeterminado.hora_salida
        except HorarioPredeterminado.DoesNotExist:
            return None

    def get_tolerancia(self):
        if self.personalizado and self.tolerancia_custom is not None:
            return self.tolerancia_custom
        try:
            return self.zona.horario_predeterminado.tolerancia_minutos
        except HorarioPredeterminado.DoesNotExist:
            return 10

    def get_hora_entrada_tarde(self):
        if self.personalizado and self.hora_entrada_tarde_custom:
            return self.hora_entrada_tarde_custom
        try:
            return self.zona.horario_predeterminado.hora_entrada_tarde
        except HorarioPredeterminado.DoesNotExist:
            return None

    def get_hora_salida_tarde(self):
        if self.personalizado and self.hora_salida_tarde_custom:
            return self.hora_salida_tarde_custom
        try:
            return self.zona.horario_predeterminado.hora_salida_tarde
        except HorarioPredeterminado.DoesNotExist:
            return None

    def get_tolerancia_tarde(self):
        if self.personalizado and self.tolerancia_tarde_custom is not None:
            return self.tolerancia_tarde_custom
        try:
            return self.zona.horario_predeterminado.tolerancia_tarde or 10
        except HorarioPredeterminado.DoesNotExist:
            return 10


class EnrolamientoFacial(models.Model):
    ESTADO_CHOICES = [
        ('pendiente', 'Pendiente'),
        ('enrolado', 'Enrolado'),
        ('bloqueado', 'Bloqueado'),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='enrolamiento')
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='pendiente')
    vector_facial = models.JSONField(null=True, blank=True)
    intentos_fallidos = models.PositiveIntegerField(default=0)
    fecha_enrolamiento = models.DateTimeField(null=True, blank=True)
    score_promedio = models.FloatField(null=True, blank=True)

    class Meta:
        verbose_name = 'Enrolamiento facial'
        verbose_name_plural = 'Enrolamientos faciales'

    def __str__(self):
        return f"{self.user.get_full_name()} — {self.get_estado_display()}"

    def tiene_permiso_activo(self):
        return self.permisos.filter(usado=False).exists()

    def puede_enrolar(self):
        if self.estado == 'bloqueado':
            return self.tiene_permiso_activo()
        return self.estado in ['pendiente', 'enrolado']


class PermisoReenrolamiento(models.Model):
    enrolamiento = models.ForeignKey(EnrolamientoFacial, on_delete=models.CASCADE, related_name='permisos')
    otorgado_por = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='permisos_reenrolamiento_otorgados'
    )
    motivo = models.TextField()
    fecha_otorgado = models.DateTimeField(auto_now_add=True)
    usado = models.BooleanField(default=False)
    fecha_usado = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Permiso de re-enrolamiento'
        verbose_name_plural = 'Permisos de re-enrolamiento'
        ordering = ['-fecha_otorgado']

    def __str__(self):
        estado = "usado" if self.usado else "activo"
        return f"{self.enrolamiento.user.get_full_name()} — {self.fecha_otorgado.strftime('%d/%m/%Y')} ({estado})"


class RegistroAsistencia(models.Model):
    TIPO_CHOICES = [('ENTRADA', 'Entrada'), ('SALIDA', 'Salida')]
    ESTADO_CHOICES = [
        ('PUNTUAL', 'Puntual'), ('TARDANZA', 'Tardanza'), ('AUSENTE', 'Ausente'),
        ('DENEGADO_GPS', 'Denegado GPS'), ('DENEGADO_BIO', 'Denegado biometrico'),
    ]
    BLOQUE_CHOICES = [('manana', 'Manana'), ('tarde', 'Tarde'), ('continuo', 'Continuo')]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='registros_asistencia')
    zona = models.ForeignKey(ZonaAsistencia, on_delete=models.SET_NULL, null=True, blank=True, related_name='registros')
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES)
    estado = models.CharField(max_length=15, choices=ESTADO_CHOICES)
    bloque = models.CharField(max_length=10, choices=BLOQUE_CHOICES, blank=True)
    fecha_hora = models.DateTimeField(default=timezone.now)
    latitud = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitud = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    distancia_metros = models.FloatField(null=True, blank=True)
    biometrico_score = models.FloatField(null=True, blank=True)
    foto_captura = models.ImageField(upload_to='asistencia/capturas/%Y/%m/%d/', null=True, blank=True)
    minutos_tardanza = models.IntegerField(default=0)
    device_id = models.CharField(max_length=255, blank=True)
    observacion = models.TextField(blank=True)

    class Meta:
        verbose_name = 'Registro de asistencia'
        verbose_name_plural = 'Registros de asistencia'
        ordering = ['-fecha_hora']
        indexes = [
            models.Index(fields=['user', 'fecha_hora']),
            models.Index(fields=['estado', 'fecha_hora']),
        ]

    def __str__(self):
        return f"{self.user.get_full_name()} — {self.tipo} {self.fecha_hora.strftime('%d/%m/%Y %H:%M')} ({self.estado})"

    def es_editable_hoy(self):
        return self.fecha_hora.date() == timezone.now().date()

    @property
    def profesional(self):
        try:
            return self.user.perfil.profesional
        except Exception:
            return None
