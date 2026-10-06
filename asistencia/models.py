import math
from django.core.exceptions import ValidationError
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


class BloqueBase(models.Model):
    """Franja horaria de trabajo (entrada/salida + tolerancia). Base abstracta."""
    orden = models.PositiveSmallIntegerField(default=1)
    hora_entrada = models.TimeField()
    hora_salida = models.TimeField()
    tolerancia_minutos = models.PositiveIntegerField(default=10)

    class Meta:
        abstract = True
        ordering = ['orden', 'hora_entrada']

    def clean(self):
        if self.hora_entrada and self.hora_salida and self.hora_salida <= self.hora_entrada:
            raise ValidationError('La hora de salida debe ser posterior a la de entrada.')

    def __str__(self):
        return f"{self.hora_entrada:%H:%M}-{self.hora_salida:%H:%M}"


def ordenar_bloques(bloques):
    """Ordena bloques por hora de entrada (funciona con querysets prefetch)."""
    return sorted(bloques, key=lambda b: (b.hora_entrada, b.hora_salida))


class PlantillaHorario(models.Model):
    """
    Horario semanal reutilizable: un grupo de dias con N bloques de trabajo.

    Ejemplos para una misma zona:
      - "Lunes a viernes (partido)": dias LUN..VIE, bloques 08:00-13:00 y 14:00-18:00
      - "Sabado (continuo)":         dias SAB,      bloque  08:00-12:00

    user = NULL  -> horario predeterminado de la zona
    user = <X>   -> horario personal de X en esa zona (solo cuenta si
                    ConfigAsistencia.personalizado = True)
    """
    zona = models.ForeignKey(ZonaAsistencia, on_delete=models.CASCADE, related_name='plantillas')
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, null=True, blank=True,
        related_name='plantillas_asistencia',
        help_text='Vacio = predeterminado de la zona'
    )
    nombre = models.CharField(max_length=100, blank=True)
    dias = models.JSONField(default=list, help_text='Ej: ["LUN","MAR","MIE","JUE","VIE"]')
    creada_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Plantilla de horario'
        verbose_name_plural = 'Plantillas de horario'
        ordering = ['zona__nombre', 'id']

    def __str__(self):
        quien = self.user.get_full_name() if self.user_id else 'zona'
        return f"{self.zona.nombre} [{quien}] — {self.nombre or self.dias_display}"

    @property
    def dias_display(self):
        nombres = dict(DIAS_SEMANA)
        return ', '.join(nombres[d][:3] for d in DIAS_SEMANA_ORDEN if d in (self.dias or []))

    @property
    def tipo_display(self):
        n = len(self.bloques_ordenados())
        return {0: 'Sin bloques', 1: 'Continuo', 2: 'Partido'}.get(n, f'{n} bloques')

    def bloques_ordenados(self):
        return ordenar_bloques(self.bloques.all())

    def aplica_en(self, fecha):
        return WEEKDAY_MAP.get(fecha.weekday()) in (self.dias or [])


DIAS_SEMANA_ORDEN = [d for d, _ in DIAS_SEMANA]


class BloqueHorario(BloqueBase):
    plantilla = models.ForeignKey(PlantillaHorario, on_delete=models.CASCADE, related_name='bloques')

    class Meta(BloqueBase.Meta):
        verbose_name = 'Bloque de horario'
        verbose_name_plural = 'Bloques de horario'


class FechaEspecial(models.Model):
    """
    Fecha con horario propio (o dia libre). Prioridad maxima sobre cualquier otro horario.
    Si profesionales esta vacio aplica a todos los de la zona.
    tipo 'horario' -> usa sus BloqueFechaEspecial (si no tiene bloques, no altera nada).
    """
    TIPO_CHOICES = [
        ('horario', 'Horario especial'),
        ('libre', 'Dia libre'),
    ]
    zona = models.ForeignKey(ZonaAsistencia, on_delete=models.CASCADE, related_name='fechas_especiales')
    fecha = models.DateField()
    tipo_horario = models.CharField(max_length=10, choices=TIPO_CHOICES, default='horario')
    profesionales = models.ManyToManyField(
        User, blank=True, related_name='fechas_especiales',
        help_text="Dejar vacio para aplicar a todos los profesionales de la zona"
    )
    motivo = models.CharField(max_length=200, blank=True)
    creado_por = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name='fechas_especiales_creadas'
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Fecha especial'
        verbose_name_plural = 'Fechas especiales'
        ordering = ['-fecha']
        unique_together = ['zona', 'fecha']

    def __str__(self):
        return f"{self.zona.nombre} — {self.fecha} ({self.get_tipo_horario_display()})"

    def bloques_ordenados(self):
        return ordenar_bloques(self.bloques.all())

    def aplica_a_user(self, user):
        # .all() para aprovechar prefetch_related('profesionales')
        ids = {u.pk for u in self.profesionales.all()}
        return not ids or (user is not None and user.pk in ids)


class BloqueFechaEspecial(BloqueBase):
    fecha_especial = models.ForeignKey(FechaEspecial, on_delete=models.CASCADE, related_name='bloques')

    class Meta(BloqueBase.Meta):
        verbose_name = 'Bloque de fecha especial'
        verbose_name_plural = 'Bloques de fecha especial'


class ConfigAsistencia(models.Model):
    """
    Asignacion usuario + zona.
    personalizado=False -> usa las PlantillaHorario de la zona (user NULL)
    personalizado=True  -> usa solo las PlantillaHorario propias del usuario en esa zona
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='configs_asistencia')
    zona = models.ForeignKey(ZonaAsistencia, on_delete=models.CASCADE, related_name='configs')
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

    def plantillas_efectivas(self):
        """Plantillas que rigen para este usuario (usa prefetch si existe)."""
        todas = list(self.zona.plantillas.all())
        if self.personalizado:
            return [p for p in todas if p.user_id == self.user_id]
        return [p for p in todas if p.user_id is None]

    def plantilla_para_dia(self, fecha):
        for p in self.plantillas_efectivas():
            if p.aplica_en(fecha):
                return p
        return None

    def bloques_para_dia(self, fecha):
        p = self.plantilla_para_dia(fecha)
        return p.bloques_ordenados() if p else []


class EnrolamientoFacial(models.Model):
    """
    vector_facial: lista de descriptores faciales (cada uno = lista de 128 floats,
    generados en el navegador con face-api.js).
    """
    ESTADO_CHOICES = [
        ('pendiente', 'Pendiente'),
        ('enrolado', 'Enrolado'),
        ('bloqueado', 'Bloqueado'),
    ]
    MAX_INTENTOS = 5

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='enrolamiento')
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='pendiente')
    vector_facial = models.JSONField(null=True, blank=True)
    intentos_fallidos = models.PositiveIntegerField(default=0)
    fecha_enrolamiento = models.DateTimeField(null=True, blank=True)
    score_promedio = models.FloatField(null=True, blank=True)
    foto_referencia = models.ImageField(
        upload_to='asistencia/enrolamiento/', null=True, blank=True,
        help_text='Foto tomada al enrolar, para revision del administrador'
    )

    class Meta:
        verbose_name = 'Enrolamiento facial'
        verbose_name_plural = 'Enrolamientos faciales'

    def __str__(self):
        return f"{self.user.get_full_name()} — {self.get_estado_display()}"

    def tiene_permiso_activo(self):
        return self.permisos.filter(usado=False).exists()

    def puede_enrolar(self):
        """Primer enrolamiento libre; re-enrolar o salir de bloqueo requiere permiso del admin."""
        if self.estado == 'pendiente':
            return True
        return self.tiene_permiso_activo()

    def registrar_fallo(self):
        """Suma un intento fallido; bloquea al llegar a MAX_INTENTOS."""
        self.intentos_fallidos += 1
        if self.intentos_fallidos >= self.MAX_INTENTOS:
            self.estado = 'bloqueado'
        self.save(update_fields=['intentos_fallidos', 'estado'])

    def registrar_exito(self):
        if self.intentos_fallidos:
            self.intentos_fallidos = 0
            self.save(update_fields=['intentos_fallidos'])


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
    ESTADOS_VALIDOS = ('PUNTUAL', 'TARDANZA')

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='registros_asistencia')
    zona = models.ForeignKey(ZonaAsistencia, on_delete=models.SET_NULL, null=True, blank=True, related_name='registros')
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES)
    estado = models.CharField(max_length=15, choices=ESTADO_CHOICES)
    # Numero de bloque del dia ("1", "2", ...). Vacio = fuera de horario / sin horario.
    bloque = models.CharField(max_length=10, blank=True)
    fecha_hora = models.DateTimeField(default=timezone.now)
    latitud = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitud = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    distancia_metros = models.FloatField(null=True, blank=True)
    precision_metros = models.FloatField(null=True, blank=True, help_text='Precision reportada por el GPS del dispositivo')
    # Distancia euclidiana entre descriptores faciales (menor = mas parecido)
    biometrico_score = models.FloatField(null=True, blank=True)
    foto_captura = models.ImageField(upload_to='asistencia/capturas/%Y/%m/%d/', null=True, blank=True)
    minutos_tardanza = models.IntegerField(default=0)
    device_id = models.CharField(max_length=255, blank=True)
    observacion = models.TextField(blank=True)
    registrado_por = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='registros_marcados',
        help_text="Si no es null, este registro fue creado manualmente por un administrador"
    )

    class Meta:
        verbose_name = 'Registro de asistencia'
        verbose_name_plural = 'Registros de asistencia'
        ordering = ['-fecha_hora']
        indexes = [
            models.Index(fields=['user', 'fecha_hora']),
            models.Index(fields=['estado', 'fecha_hora']),
        ]

    def __str__(self):
        return f"{self.user.get_full_name()} — {self.tipo} {timezone.localtime(self.fecha_hora):%d/%m/%Y %H:%M} ({self.estado})"

    def es_editable_hoy(self):
        return timezone.localtime(self.fecha_hora).date() == timezone.localdate()

    @property
    def es_manual(self):
        return self.registrado_por_id is not None

    @property
    def bloque_display(self):
        return f"Bloque {self.bloque}" if self.bloque else ''

    @property
    def profesional(self):
        try:
            return self.user.perfil.profesional
        except Exception:
            return None
