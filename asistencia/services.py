import base64
import numpy as np
from django.core.files.base import ContentFile
from django.utils import timezone
from .models import ZonaAsistencia, ConfigAsistencia, FechaEspecial, RegistroAsistencia


class ResolvedorHorario:
    """
    Resuelve qué horario aplica a un usuario en una fecha dada.
    Orden de prioridad:
      1. FechaEspecial (prioridad maxima)
      2. ConfigAsistencia personalizada del profesional
      3. HorarioPredeterminado de la zona
    """

    def __init__(self, user, zona, config, fecha=None):
        self.user = user
        self.zona = zona
        self.config = config
        self.fecha = fecha or timezone.now().date()

    def resolver(self):
        """
        Devuelve un dict con:
          tipo: 'partido' | 'continuo' | 'libre' | None
          hora_entrada, hora_salida, tolerancia  (bloque manana/continuo)
          hora_entrada_tarde, hora_salida_tarde, tolerancia_tarde (bloque tarde, solo partido)
        """
        # 1 — Fecha especial (prioridad maxima)
        fecha_esp = FechaEspecial.objects.filter(
            zona=self.zona, fecha=self.fecha
        ).first()

        if fecha_esp and fecha_esp.aplica_a_user(self.user):
            tipo = fecha_esp.tipo_horario

            # Usar horario especifico de la fecha si existe,
            # si no caer al horario base de la zona segun el tipo
            hora_entrada = (
                fecha_esp.hora_entrada_especial
                or self.config.get_hora_entrada()
            )
            hora_salida = (
                fecha_esp.hora_salida_especial
                or self.config.get_hora_salida()
            )
            tolerancia = (
                fecha_esp.tolerancia_especial
                if fecha_esp.tolerancia_especial is not None
                else self.config.get_tolerancia()
            )
            hora_entrada_tarde = (
                fecha_esp.hora_entrada_tarde_especial
                or self.config.get_hora_entrada_tarde()
            )
            hora_salida_tarde = (
                fecha_esp.hora_salida_tarde_especial
                or self.config.get_hora_salida_tarde()
            )
            tolerancia_tarde = (
                fecha_esp.tolerancia_tarde_especial
                if fecha_esp.tolerancia_tarde_especial is not None
                else self.config.get_tolerancia_tarde()
            )
        else:
            # 2/3 — Config profesional o predeterminado zona
            tipo = self.config.tipo_para_dia(self.fecha)
            hora_entrada       = self.config.get_hora_entrada()
            hora_salida        = self.config.get_hora_salida()
            tolerancia         = self.config.get_tolerancia()
            hora_entrada_tarde = self.config.get_hora_entrada_tarde()
            hora_salida_tarde  = self.config.get_hora_salida_tarde()
            tolerancia_tarde   = self.config.get_tolerancia_tarde()

        return {
            'tipo': tipo,
            'hora_entrada': hora_entrada,
            'hora_salida': hora_salida,
            'tolerancia': tolerancia,
            'hora_entrada_tarde': hora_entrada_tarde,
            'hora_salida_tarde': hora_salida_tarde,
            'tolerancia_tarde': tolerancia_tarde,
        }


class CalculadorEstado:
    """
    Dado un horario resuelto y la hora actual, calcula
    estado ('PUNTUAL'/'TARDANZA'), bloque y minutos de tardanza.
    Nunca bloquea el marcado — la tardanza siempre se registra.
    """

    def __init__(self, horario, ahora=None):
        self.h = horario
        self.ahora = ahora or timezone.now()
        self.fecha = self.ahora.date()

    def _dt(self, time_obj):
        """Convierte un TimeField en datetime aware del dia actual."""
        if not time_obj:
            return None
        return timezone.make_aware(
            timezone.datetime.combine(self.fecha, time_obj)
        )

    def _calcular_bloque(self, hora_entrada_dt, tolerancia):
        """
        Calcula estado y minutos para un bloque dado.
        Antes o dentro de tolerancia → PUNTUAL.
        Despues → TARDANZA con minutos desde hora_entrada (sin tolerancia).
        """
        limite = hora_entrada_dt + timezone.timedelta(minutes=tolerancia)
        if self.ahora <= limite:
            return 'PUNTUAL', 0
        minutos = int((self.ahora - hora_entrada_dt).total_seconds() / 60)
        return 'TARDANZA', minutos

    def calcular(self):
        """
        Devuelve (estado, bloque, minutos_tardanza).
        bloque: 'manana' | 'tarde' | 'continuo'
        """
        tipo = self.h.get('tipo')

        if tipo == 'libre' or tipo is None:
            # Dia sin horario definido — se registra igual pero sin calculo
            return 'PUNTUAL', '', 0

        entrada_dt = self._dt(self.h.get('hora_entrada'))
        tolerancia = self.h.get('tolerancia') or 10

        if tipo == 'continuo':
            if not entrada_dt:
                return 'PUNTUAL', 'continuo', 0
            estado, minutos = self._calcular_bloque(entrada_dt, tolerancia)
            return estado, 'continuo', minutos

        # tipo == 'partido'
        entrada_tarde_dt = self._dt(self.h.get('hora_entrada_tarde'))
        tolerancia_tarde = self.h.get('tolerancia_tarde') or 10

        if not entrada_dt and not entrada_tarde_dt:
            return 'PUNTUAL', '', 0

        # Detectar a qué bloque pertenece el marcado actual
        # Si la hora es antes de la mitad entre salida manana y entrada tarde → bloque manana
        # Si no → bloque tarde
        salida_manana_dt = self._dt(self.h.get('hora_salida'))

        en_bloque_tarde = False
        if entrada_tarde_dt and salida_manana_dt:
            # Punto de corte: mitad entre salida manana y entrada tarde
            corte = salida_manana_dt + (entrada_tarde_dt - salida_manana_dt) / 2
            en_bloque_tarde = self.ahora >= corte
        elif entrada_tarde_dt and not salida_manana_dt:
            en_bloque_tarde = self.ahora >= entrada_tarde_dt

        if en_bloque_tarde and entrada_tarde_dt:
            estado, minutos = self._calcular_bloque(entrada_tarde_dt, tolerancia_tarde)
            return estado, 'tarde', minutos
        elif entrada_dt:
            estado, minutos = self._calcular_bloque(entrada_dt, tolerancia)
            return estado, 'manana', minutos

        return 'PUNTUAL', '', 0


class ValidadorAsistencia:
    UMBRAL_FACIAL = 0.85

    def __init__(self, user, tipo, latitud, longitud,
                 vector_facial_recibido, foto_base64=None,
                 device_id=None, observacion=''):
        self.user = user
        self.tipo = tipo
        self.lat = latitud
        self.lon = longitud
        self.vector_recibido = vector_facial_recibido
        self.foto_base64 = foto_base64
        self.device_id = device_id or ''
        self.observacion = observacion
        self.errores = []
        self.score_facial = None
        self.zona_valida = None
        self.distancia = None
        self.config_valida = None

    # ── Capa 1: GPS ──────────────────────────────────────────────────────────

    def validar_gps(self):
        if not self.lat or not self.lon:
            self.errores.append("No se recibieron coordenadas GPS.")
            return False

        configs = ConfigAsistencia.objects.filter(
            user=self.user, zona__activa=True
        ).select_related('zona')

        if not configs.exists():
            self.errores.append("No tienes zonas de asistencia asignadas.")
            return False

        ultima_distancia = None
        for config in configs:
            en_zona, distancia = config.zona.contiene_punto(self.lat, self.lon)
            ultima_distancia = distancia
            if en_zona:
                self.zona_valida = config.zona
                self.distancia = distancia
                self.config_valida = config
                return True

        self.distancia = ultima_distancia
        self.errores.append(
            f"Fuera de todas tus zonas autorizadas. "
            f"Distancia a la mas cercana: {ultima_distancia}m."
        )
        return False

    # ── Capa 2: Biometrico ───────────────────────────────────────────────────

    def validar_facial(self):
        try:
            enrolamiento = self.user.enrolamiento
        except Exception:
            self.errores.append("No tienes enrolamiento facial registrado.")
            return False

        if enrolamiento.estado != 'enrolado' or not enrolamiento.vector_facial:
            self.errores.append("Tu enrolamiento facial no esta completo.")
            return False

        if not self.vector_recibido:
            self.errores.append("No se recibio dato biometrico.")
            return False

        v1 = np.array(enrolamiento.vector_facial)
        v2 = np.array(self.vector_recibido)
        similitud = float(
            np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))
        )
        self.score_facial = similitud

        if similitud < self.UMBRAL_FACIAL:
            self.errores.append(
                f"Identidad no verificada (score: {similitud:.2f}, minimo: {self.UMBRAL_FACIAL})."
            )
            return False
        return True

    # ── Foto base64 → archivo ────────────────────────────────────────────────

    def _foto_como_archivo(self):
        if not self.foto_base64:
            return None
        try:
            formato, datos = self.foto_base64.split(';base64,')
            ext = formato.split('/')[-1]
            return ContentFile(
                base64.b64decode(datos),
                name=f"cap_{self.user.id}_{timezone.now().strftime('%H%M%S')}.{ext}"
            )
        except Exception:
            return None

    # ── Ejecucion completa ───────────────────────────────────────────────────

    def ejecutar(self):
        """
        Retorna (exito, registro, errores).
        La tardanza NUNCA bloquea el marcado.
        """
        # Paso 1: GPS
        if not self.validar_gps():
            registro = RegistroAsistencia.objects.create(
                user=self.user, tipo=self.tipo, estado='DENEGADO_GPS',
                latitud=self.lat, longitud=self.lon,
                distancia_metros=self.distancia, device_id=self.device_id,
            )
            return False, registro, self.errores

        # Paso 2: Biometrico
        if not self.validar_facial():
            registro = RegistroAsistencia.objects.create(
                user=self.user, zona=self.zona_valida,
                tipo=self.tipo, estado='DENEGADO_BIO',
                latitud=self.lat, longitud=self.lon,
                distancia_metros=self.distancia,
                biometrico_score=self.score_facial,
                device_id=self.device_id,
            )
            return False, registro, self.errores

        # Paso 3: Resolver horario y calcular estado
        ahora = timezone.now()
        resolvedor = ResolvedorHorario(
            user=self.user,
            zona=self.zona_valida,
            config=self.config_valida,
            fecha=ahora.date(),
        )
        horario = resolvedor.resolver()

        if self.tipo == 'ENTRADA':
            calculador = CalculadorEstado(horario, ahora)
            estado, bloque, minutos_tardanza = calculador.calcular()
        else:
            # Para SALIDA no calculamos tardanza
            estado, bloque, minutos_tardanza = 'PUNTUAL', '', 0
            # Heredar bloque de la entrada del dia si existe
            entrada_hoy = RegistroAsistencia.objects.filter(
                user=self.user,
                tipo='ENTRADA',
                fecha_hora__date=ahora.date(),
                estado__in=['PUNTUAL', 'TARDANZA'],
            ).first()
            if entrada_hoy:
                bloque = entrada_hoy.bloque

        registro = RegistroAsistencia.objects.create(
            user=self.user,
            zona=self.zona_valida,
            tipo=self.tipo,
            estado=estado,
            bloque=bloque,
            latitud=self.lat,
            longitud=self.lon,
            distancia_metros=self.distancia,
            biometrico_score=self.score_facial,
            foto_captura=self._foto_como_archivo(),
            minutos_tardanza=minutos_tardanza,
            device_id=self.device_id,
            observacion=self.observacion,
        )
        return True, registro, []
