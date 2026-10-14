import datetime
import math
from django.core.exceptions import ValidationError
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from core.fechas import fmt_fecha  # dd/mm/aaaa

DIAS_SEMANA = [
    ('LUN', 'Lunes'), ('MAR', 'Martes'), ('MIE', 'Miércoles'),
    ('JUE', 'Jueves'), ('VIE', 'Viernes'), ('SAB', 'Sábado'), ('DOM', 'Domingo'),
]
WEEKDAY_MAP = {0: 'LUN', 1: 'MAR', 2: 'MIE', 3: 'JUE', 4: 'VIE', 5: 'SAB', 6: 'DOM'}


# Fecha de inicio de todo lo configurado antes de existir las vigencias: "rige desde siempre".
DESDE_SIEMPRE = datetime.date(2000, 1, 1)


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
    # Minutos de retraso que NO cuentan como tardanza (hasta el minuto N inclusive).
    tolerancia_minutos = models.PositiveIntegerField(default=10)
    # Opcional: pasado este retraso ya no se puede marcar el ingreso y el bloque cuenta como falta.
    max_retraso_minutos = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Minutos de retraso hasta los que se puede marcar. Vacío = sin límite.'
    )

    class Meta:
        abstract = True
        ordering = ['orden', 'hora_entrada']

    def clean(self):
        if self.hora_entrada and self.hora_salida and self.hora_salida <= self.hora_entrada:
            raise ValidationError('La hora de salida debe ser posterior a la de entrada.')
        if self.max_retraso_minutos is not None and self.tolerancia_minutos is not None \
                and self.max_retraso_minutos < self.tolerancia_minutos:
            raise ValidationError('El límite para marcar no puede ser menor que la tolerancia.')

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
    # Vigencia: un cambio de horario NO es retroactivo. Al editar con una fecha de inicio, la versión
    # anterior se cierra el día previo y se crea una nueva; los meses pasados conservan la que regía.
    vigente_desde = models.DateField(default=DESDE_SIEMPRE, help_text='Primer día en que rige este horario')
    vigente_hasta = models.DateField(null=True, blank=True, help_text='Último día en que rige (vacío = sin fin)')
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

    def vigente_en(self, fecha):
        return self.vigente_desde <= fecha and (self.vigente_hasta is None or fecha <= self.vigente_hasta)

    def aplica_en(self, fecha):
        return self.vigente_en(fecha) and WEEKDAY_MAP.get(fecha.weekday()) in (self.dias or [])

    def estado_vigencia(self, hoy=None):
        """'programado' (aún no empieza), 'finalizado' (ya terminó) o 'vigente'."""
        hoy = hoy or timezone.localdate()
        if self.vigente_desde > hoy:
            return 'programado'
        if self.vigente_hasta is not None and self.vigente_hasta < hoy:
            return 'finalizado'
        return 'vigente'

    @property
    def vigencia_texto(self):
        desde = None if self.vigente_desde <= DESDE_SIEMPRE else self.vigente_desde.strftime('%d/%m/%Y')
        hasta = self.vigente_hasta.strftime('%d/%m/%Y') if self.vigente_hasta else None
        if desde and hasta:
            return f"del {desde} al {hasta}"
        if desde:
            return f"desde el {desde}"
        if hasta:
            return f"hasta el {hasta}"
        return ''


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
        return f"{self.zona.nombre} — {fmt_fecha(self.fecha)} ({self.get_tipo_horario_display()})"

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


class ReglasAsistencia(models.Model):
    """
    Descuento por retraso acumulado, por TRAMOS (ver TramoDescuento). Hay una versión por fecha de inicio
    (siempre el día 1 de un mes): un mes se evalúa completo con la versión que regía el día 1, así que
    cambiar las reglas NO es retroactivo. Ver services.dias_descuento() y ReglasAsistencia.para_mes().

    Los segundos de retraso de cada ingreso (solo lo que excede la tolerancia) se acumulan durante el mes
    y el total cae en un tramo que fija los días de descuento. Ejemplo sugerido:
        hasta 30 min -> 0 días · hasta 45 -> ½ día · hasta 60 -> 1 día · hasta 90 -> 2 días · más de 90 -> 3 días
    La tolerancia y el límite para marcar no están aquí: son por bloque de horario (BloqueBase).
    """
    ALCANCE_CHOICES = [
        ('global', 'Todo el personal'),
        ('sucursal', 'Una sucursal'),
        ('profesional', 'Un profesional'),
    ]
    # Alcance: la regla más específica gana (profesional > sucursal > global). Cada alcance tiene su propio
    # historial de versiones por fecha de inicio.
    alcance = models.CharField(max_length=12, choices=ALCANCE_CHOICES, default='global')
    sucursal = models.ForeignKey('servicios.Sucursal', null=True, blank=True, on_delete=models.CASCADE,
                                 related_name='+')
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.CASCADE, related_name='+')
    vigente_desde = models.DateField(
        default=DESDE_SIEMPRE,
        help_text='Primer día del mes desde el cual rige esta versión de las reglas.'
    )
    hereda = models.BooleanField(
        default=False,
        help_text='Solo en excepciones: desde esta fecha la excepción termina y se usa la regla más general.')
    modificado_por = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    fecha_modificacion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Reglas de asistencia'
        verbose_name_plural = 'Reglas de asistencia'
        ordering = ['-vigente_desde']

    def __str__(self):
        return 'Reglas de asistencia' + ('' if self.vigente_desde <= DESDE_SIEMPRE
                                         else f" desde {self.vigente_desde:%m/%Y}") + f" · {self.alcance_texto}"

    @property
    def alcance_texto(self):
        if self.alcance == 'sucursal' and self.sucursal_id:
            return f"sucursal {self.sucursal.nombre}"
        if self.alcance == 'profesional' and self.user_id:
            return f"profesional {self.user.get_full_name() or self.user.username}"
        return 'todo el personal'

    def clean(self):
        if self.alcance == 'sucursal' and not self.sucursal_id:
            raise ValidationError('Elige la sucursal.')
        if self.alcance == 'profesional' and not self.user_id:
            raise ValidationError('Elige el profesional.')

    def save(self, *args, **kwargs):
        # Cada alcance guarda solo su propia referencia
        if self.alcance != 'sucursal':
            self.sucursal = None
        if self.alcance != 'profesional':
            self.user = None
        # Guardar con una fecha que ya existe (en el mismo alcance) actualiza esa versión (no duplica).
        if self.pk is None:
            existente = type(self).objects.filter(
                vigente_desde=self.vigente_desde, alcance=self.alcance,
                sucursal=self.sucursal, user=self.user).first()
            if existente:
                self.pk = existente.pk
        super().save(*args, **kwargs)

    def tramos_lista(self):
        """[(tope_en_segundos | None, días)] ordenado; None = «más allá del último tope»."""
        if self.pk is None:                      # instancia vacía (todavía no hay reglas guardadas)
            return []
        ordenados = sorted(self.tramos.all(), key=lambda t: (t.hasta_minutos is None, t.hasta_minutos or 0))
        return [(None if t.hasta_minutos is None else int(round(float(t.hasta_minutos) * 60)), float(t.dias))
                for t in ordenados]

    def texto_resumen(self):
        return 'vuelve a la regla general' if self.hereda else None

    @property
    def hay_descuento(self):
        return any(dias > 0 for _tope, dias in self.tramos_lista())

    @classmethod
    def para_fecha(cls, fecha, alcance='global', sucursal=None, user=None):
        """Versión que rige en `fecha` dentro de ese alcance exacto (None si todavía no hay reglas)."""
        qs = cls.objects.filter(vigente_desde__lte=fecha, alcance=alcance)
        if alcance == 'sucursal':
            qs = qs.filter(sucursal=sucursal)
        elif alcance == 'profesional':
            qs = qs.filter(user=user)
        return qs.order_by('-vigente_desde').prefetch_related('tramos').first()

    @classmethod
    def para_mes(cls, anio, mes):
        """Versión GENERAL con la que se evalúa un mes completo: la vigente el día 1.
        Para un profesional concreto (con excepciones) ver services.ResolvedorReglas."""
        return cls.para_fecha(datetime.date(anio, mes, 1))

    @classmethod
    def obtener(cls):
        """Versión general vigente hoy; si no hay ninguna, una instancia vacía (sin guardar)."""
        return cls.para_fecha(timezone.localdate()) or cls()

    def estado_vigencia(self, vigente_actual_pk=None, hoy=None):
        hoy = hoy or timezone.localdate()
        if self.vigente_desde > hoy:
            return 'programada'
        return 'vigente' if self.pk == vigente_actual_pk else 'anterior'


class TramoDescuento(models.Model):
    """
    Un escalón de la regla de descuento: «hasta N minutos acumulados en el mes -> X días de descuento».
    El tramo sin tope (hasta_minutos vacío) vale para todo lo que supere al último tope.
    Los topes son INCLUSIVOS: con 30 / 45 / 60 / 90, de 30:01 a 45:00 cae en el tramo de 45.
    """
    regla = models.ForeignKey(ReglasAsistencia, on_delete=models.CASCADE, related_name='tramos')
    hasta_minutos = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True,
        help_text='Hasta cuántos minutos acumulados (inclusive). Vacío = sin tope.'
    )
    dias = models.DecimalField(max_digits=4, decimal_places=2, default=0,
                               help_text='Días de descuento (0, 0.5, 1, 2, 3...).')

    class Meta:
        verbose_name = 'Tramo de descuento'
        verbose_name_plural = 'Tramos de descuento'
        ordering = ['hasta_minutos']

    def __str__(self):
        tope = 'más allá del último tope' if self.hasta_minutos is None else f'hasta {self.hasta_minutos} min'
        return f"{tope}: {self.dias} día(s)"


class PermisoAsistencia(models.Model):
    """
    Justificación de una falta. Solo la registra el administrador, después de revisar el comprobante o el
    justificativo escrito (certificado médico, nota, etc.). Mientras no exista, el bloque sigue siendo falta
    con descuento. Se puede justificar hasta el último día del mes de la falta.
    """
    TIPO_CHOICES = [
        ('medico', 'Certificado médico'),
        ('autorizado', 'Permiso autorizado por escrito'),
        ('otro', 'Otro justificativo escrito'),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='permisos_asistencia')
    fecha = models.DateField()
    bloque = models.CharField(max_length=2, blank=True, help_text='Vacío = todo el día; "1", "2"... = solo ese bloque')
    tipo = models.CharField(max_length=12, choices=TIPO_CHOICES, default='medico')
    detalle = models.TextField(help_text='Qué justificativo se presentó (certificado de..., nota firmada por..., etc.)')
    comprobante = models.FileField(upload_to='asistencia/justificativos/%Y/%m/', null=True, blank=True)
    registrado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='permisos_asistencia_registrados')
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Permiso de asistencia'
        verbose_name_plural = 'Permisos de asistencia'
        unique_together = ['user', 'fecha', 'bloque']
        ordering = ['-fecha', 'user_id']

    def __str__(self):
        alcance = 'todo el día' if not self.bloque else f'bloque {self.bloque}'
        return f"{self.user.get_full_name()} — {self.fecha:%d/%m/%Y} ({alcance}, {self.get_tipo_display()})"

    def cubre(self, bloque_numero):
        return self.bloque == '' or self.bloque == str(bloque_numero)

    @property
    def plazo_hasta(self):
        """Último día en que se puede registrar o quitar este permiso (fin del mes de la falta)."""
        siguiente = (self.fecha.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
        return siguiente - datetime.timedelta(days=1)


class DerechoAsueto(models.Model):
    """Saldo de asueto otorgado a un profesional. Se consume con UsoAsueto en las fechas que elija."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='derechos_asueto')
    motivo = models.CharField(max_length=200, help_text='Ej: Día de la Mujer 2026, Cumpleaños, Vacaciones')
    dias = models.DecimalField(max_digits=4, decimal_places=2, default=0.5)
    otorgado_el = models.DateField(default=timezone.localdate)
    vence_el = models.DateField(null=True, blank=True, help_text='Último día para usarlo. Vacío = no vence.')
    creado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Derecho de asueto'
        verbose_name_plural = 'Derechos de asueto'
        ordering = ['-otorgado_el', 'user_id']

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} — {self.motivo} ({self.dias} d)"

    @property
    def usados(self):
        # .all() para aprovechar prefetch_related('usos')
        return sum((u.dias for u in self.usos.all()), 0)

    @property
    def saldo(self):
        return self.dias - self.usados

    def vencido(self, hoy=None):
        hoy = hoy or timezone.localdate()
        return self.vence_el is not None and self.vence_el < hoy

    def estado(self, hoy=None):
        if self.saldo <= 0:
            return 'usado'
        return 'vencido' if self.vencido(hoy) else 'disponible'


class UsoAsueto(models.Model):
    """Una fecha (o un bloque de esa fecha) en la que el profesional toma su asueto."""
    derecho = models.ForeignKey(DerechoAsueto, on_delete=models.CASCADE, related_name='usos')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='usos_asueto')
    fecha = models.DateField()
    bloque = models.CharField(max_length=2, blank=True,
                              help_text='Vacío = todo el día; "1", "2"... = solo ese bloque')
    dias = models.DecimalField(max_digits=4, decimal_places=2,
                               help_text='Días que descuenta del saldo (cada bloque pesa 1/N del día).')
    nota = models.CharField(max_length=200, blank=True)
    registrado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Uso de asueto'
        verbose_name_plural = 'Usos de asueto'
        unique_together = ['user', 'fecha', 'bloque']
        ordering = ['-fecha', 'user_id']

    def __str__(self):
        alcance = 'todo el día' if not self.bloque else f'bloque {self.bloque}'
        return f"{self.user.get_full_name()} — {self.fecha:%d/%m/%Y} ({alcance})"

    def cubre(self, bloque_numero):
        return self.bloque == '' or self.bloque == str(bloque_numero)


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

    def _periodos(self):
        """Periodos en que rige el horario propio (se cargan una sola vez por instancia)."""
        if self.pk is None:
            return []
        if not hasattr(self, '_periodos_cache'):
            self._periodos_cache = list(self.periodos_propios.all())
        return self._periodos_cache

    def usa_horario_propio(self, fecha=None):
        """
        ¿Rige el horario propio del profesional en esa fecha? Sin fecha: según la marca actual.
        Si todavía no hay periodos registrados se respeta la marca `personalizado` (siempre).
        """
        if fecha is None:
            return self.personalizado
        periodos = self._periodos()
        if not periodos:
            return self.personalizado
        return any(p.cubre(fecha) for p in periodos)

    def plantillas_efectivas(self, fecha=None):
        """
        Plantillas que rigen para este usuario (usa prefetch si existe). Con `fecha` solo las vigentes
        ese día, del horario propio o del de la zona según corresponda; sin fecha, todas las versiones.
        """
        todas = list(self.zona.plantillas.all())
        if self.usa_horario_propio(fecha):
            elegidas = [p for p in todas if p.user_id == self.user_id]
        else:
            elegidas = [p for p in todas if p.user_id is None]
        if fecha is not None:
            elegidas = [p for p in elegidas if p.vigente_en(fecha)]
        return elegidas

    def plantilla_para_dia(self, fecha):
        candidatas = [p for p in self.plantillas_efectivas(fecha) if p.aplica_en(fecha)]
        return max(candidatas, key=lambda p: p.vigente_desde) if candidatas else None

    def bloques_para_dia(self, fecha):
        p = self.plantilla_para_dia(fecha)
        return p.bloques_ordenados() if p else []


class PeriodoHorarioPropio(models.Model):
    """
    Periodo en que rige el horario propio de un profesional (ConfigAsistencia). Permite activar o
    desactivar el horario propio desde una fecha sin cambiar lo ocurrido antes.
    Fuera de estos periodos rige el horario de la zona.
    """
    config = models.ForeignKey(ConfigAsistencia, on_delete=models.CASCADE, related_name='periodos_propios')
    desde = models.DateField(default=DESDE_SIEMPRE)
    hasta = models.DateField(null=True, blank=True, help_text='Último día (vacío = sin fin)')

    class Meta:
        verbose_name = 'Periodo de horario propio'
        verbose_name_plural = 'Periodos de horario propio'
        ordering = ['desde']

    def __str__(self):
        return f"{self.config} [{self.desde} → {self.hasta or 'sin fin'}]"

    def cubre(self, fecha):
        return self.desde <= fecha and (self.hasta is None or fecha <= self.hasta)


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
    # Minutos completos transcurridos desde la hora de entrada del bloque (informativo).
    minutos_tardanza = models.IntegerField(default=0)
    # Segundos después de la hora de entrada (0 si llegó a tiempo o antes). Dentro de la tolerancia
    # sigue siendo > 0: sirve para saber si el profesional "usó" su tolerancia.
    segundos_tarde = models.PositiveIntegerField(default=0)
    # Segundos de retraso que SE ACUMULAN: solo lo que excede la tolerancia (10 min de tolerancia y
    # marca a los 11:00 -> 60 s acumulables).
    segundos_acumulables = models.PositiveIntegerField(default=0)
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
