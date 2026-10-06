"""
Lógica de negocio del control de asistencia.

Conceptos
---------
* Un día de trabajo tiene N *bloques* (1 = continuo, 2 = partido, ...). Los bloques
  salen de, en orden de prioridad:
      1. FechaEspecial (feriado, evento, medio día...)
      2. Plantillas personales del profesional (si ConfigAsistencia.personalizado)
      3. Plantillas predeterminadas de la zona
  Cada PlantillaHorario agrupa los días de la semana a los que aplica, así que una
  misma zona puede tener "Lun-Vie partido" y "Sábado solo mañana" a la vez.

* El marcado es una secuencia ENTRADA → SALIDA → ENTRADA → SALIDA ... validada en el
  servidor (no solo en la interfaz).

* Todas las fechas/horas se manejan en la zona horaria local (settings.TIME_ZONE).
"""
import base64
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import List, Optional

import numpy as np
from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from .models import (
    ConfigAsistencia, EnrolamientoFacial, FechaEspecial, RegistroAsistencia,
    ordenar_bloques,
)

logger = logging.getLogger(__name__)

DESCRIPTOR_LEN = 128                      # tamaño del descriptor de face-api.js
MAX_FOTO_BYTES = 3 * 1024 * 1024          # 3 MB
FORMATOS_FOTO = {'jpeg', 'jpg', 'png', 'webp'}


def _cfg(nombre, default):
    return getattr(settings, nombre, default)


def _aware(fecha, t):
    """date + time → datetime aware en la zona horaria local."""
    return timezone.make_aware(datetime.combine(fecha, t))


# ══════════════════════════════════════════════════════════════════════════════
# HORARIO DEL DÍA
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class BloqueResuelto:
    numero: int            # 1, 2, 3... (orden dentro del día)
    entrada: time
    salida: time
    tolerancia: int = 10

    def etiqueta(self):
        return f"{self.entrada:%H:%M}–{self.salida:%H:%M}"


@dataclass
class HorarioDia:
    """Horario efectivo de un profesional en una fecha."""
    bloques: List[BloqueResuelto] = field(default_factory=list)
    tipo: str = 'sin_horario'          # 'normal' | 'libre' | 'sin_horario'
    origen: str = ''                   # 'fecha_especial' | 'personal' | 'zona' | ''
    nombre: str = ''

    @property
    def es_laborable(self):
        return bool(self.bloques)

    @property
    def tipo_display(self):
        n = len(self.bloques)
        if self.tipo == 'libre':
            return 'Día libre'
        if n == 0:
            return 'Sin horario'
        return 'Continuo' if n == 1 else ('Partido' if n == 2 else f'{n} bloques')

    def descripcion(self):
        return ' · '.join(b.etiqueta() for b in self.bloques) or self.tipo_display


def _bloques_resueltos(objs) -> List[BloqueResuelto]:
    return [
        BloqueResuelto(i, b.hora_entrada, b.hora_salida, b.tolerancia_minutos)
        for i, b in enumerate(ordenar_bloques(objs), start=1)
    ]


class ResolvedorHorario:
    """Resuelve qué horario aplica a un usuario en una fecha."""

    def __init__(self, user, zona, config, fecha=None, fechas_especiales=None):
        self.user = user
        self.zona = zona
        self.config = config
        self.fecha = fecha or timezone.localdate()
        # Permite precargar las fechas especiales (evita consultas por usuario).
        self._fechas_especiales = fechas_especiales

    def _fecha_especial(self) -> Optional[FechaEspecial]:
        if self._fechas_especiales is None:
            candidatas = FechaEspecial.objects.filter(
                zona=self.zona, fecha=self.fecha
            ).prefetch_related('bloques', 'profesionales')
        else:
            candidatas = self._fechas_especiales
        for fe in candidatas:
            if fe.zona_id == self.zona.pk and fe.fecha == self.fecha and fe.aplica_a_user(self.user):
                return fe
        return None

    def resolver(self) -> HorarioDia:
        # 1 — Fecha especial (prioridad máxima)
        fe = self._fecha_especial()
        if fe:
            if fe.tipo_horario == 'libre':
                return HorarioDia(tipo='libre', origen='fecha_especial', nombre=fe.motivo or 'Día libre')
            bloques = _bloques_resueltos(fe.bloques.all())
            if bloques:
                return HorarioDia(bloques=bloques, tipo='normal', origen='fecha_especial',
                                  nombre=fe.motivo or 'Fecha especial')

        # 2/3 — Plantilla personal o predeterminada de la zona
        plantilla = self.config.plantilla_para_dia(self.fecha) if self.config else None
        if plantilla:
            bloques = _bloques_resueltos(plantilla.bloques.all())
            if bloques:
                return HorarioDia(
                    bloques=bloques, tipo='normal',
                    origen='personal' if plantilla.user_id else 'zona',
                    nombre=plantilla.nombre or plantilla.dias_display,
                )
        return HorarioDia()


def elegir_config_y_horario(user, fecha, configs, fechas_por_zona=None):
    """
    Entre las zonas del usuario, devuelve (config, horario) de la primera que tenga
    horario laborable ese día; si ninguna, la primera config con su horario vacío.
    fechas_por_zona: dict zona_id -> [FechaEspecial] precargadas (opcional).
    """
    primera = None
    for config in configs:
        precargadas = None if fechas_por_zona is None else fechas_por_zona.get(config.zona_id, [])
        horario = ResolvedorHorario(
            user, config.zona, config, fecha, fechas_especiales=precargadas
        ).resolver()
        if horario.es_laborable:
            return config, horario
        if primera is None:
            primera = (config, horario)
    return primera if primera else (None, HorarioDia())


# ══════════════════════════════════════════════════════════════════════════════
# CÁLCULO DE ESTADO (puntual / tardanza)
# ══════════════════════════════════════════════════════════════════════════════

class CalculadorEstado:
    """
    Dado el horario del día y la hora actual calcula (estado, bloque, minutos).
    La tardanza NUNCA bloquea el marcado.

    bloques_usados: números de bloque que ya tienen una entrada válida hoy. Si la
    entrada cae en un bloque ya usado (p. ej. salió a una gestión y volvió) se
    registra como re-entrada: PUNTUAL, sin bloque y sin cálculo de tardanza.
    """

    def __init__(self, horario: HorarioDia, ahora=None, bloques_usados=()):
        self.h = horario
        self.ahora = timezone.localtime(ahora or timezone.now())
        self.fecha = self.ahora.date()
        self.usados = set(bloques_usados or ())

    def bloque_correspondiente(self) -> Optional[BloqueResuelto]:
        """Bloque al que pertenece el instante actual (corte = mitad entre bloques)."""
        bl = self.h.bloques
        if not bl:
            return None
        elegido = bl[-1]
        for actual, siguiente in zip(bl, bl[1:]):
            s, e = _aware(self.fecha, actual.salida), _aware(self.fecha, siguiente.entrada)
            if self.ahora < s + (e - s) / 2:
                elegido = actual
                break
        return elegido

    def calcular(self):
        bloque = self.bloque_correspondiente()
        if bloque is None:
            return 'PUNTUAL', '', 0                     # sin horario: se registra igual
        if bloque.numero in self.usados:
            return 'PUNTUAL', '', 0                     # re-entrada dentro de un bloque ya cubierto
        entrada = _aware(self.fecha, bloque.entrada)
        if self.ahora <= entrada + timedelta(minutes=bloque.tolerancia):
            return 'PUNTUAL', str(bloque.numero), 0
        minutos = int((self.ahora - entrada).total_seconds() // 60)
        return 'TARDANZA', str(bloque.numero), minutos


# ══════════════════════════════════════════════════════════════════════════════
# ESTADO DEL DÍA (secuencia entrada/salida validada en servidor)
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class EstadoDia:
    registros: list                    # registros válidos del día, orden cronológico
    siguiente: Optional[str]           # 'ENTRADA' | 'SALIDA' | None (jornada completa)
    bloques_usados: set
    ultima_entrada: Optional[RegistroAsistencia] = None

    @property
    def completo(self):
        return self.siguiente is None

    @property
    def pares(self):
        """[(entrada, salida|None), ...] emparejando en orden."""
        pares, abierta = [], None
        for r in self.registros:
            if r.tipo == 'ENTRADA':
                if abierta is not None:
                    pares.append((abierta, None))
                abierta = r
            elif abierta is not None:
                pares.append((abierta, r))
                abierta = None
        if abierta is not None:
            pares.append((abierta, None))
        return pares


def registros_validos_del_dia(user, fecha):
    return list(
        RegistroAsistencia.objects.filter(
            user=user, fecha_hora__date=fecha,
            estado__in=RegistroAsistencia.ESTADOS_VALIDOS,
        ).select_related('zona').order_by('fecha_hora', 'pk')
    )


def calcular_estado_dia(registros, horario: HorarioDia, ahora=None) -> EstadoDia:
    """Determina qué puede marcar ahora el profesional (ENTRADA, SALIDA o nada)."""
    ahora = timezone.localtime(ahora or timezone.now())
    entradas = [r for r in registros if r.tipo == 'ENTRADA']
    ultimo = registros[-1] if registros else None
    usados = {int(r.bloque) for r in entradas if r.bloque and r.bloque.isdigit()}
    ultima_entrada = entradas[-1] if entradas else None

    if ultimo is not None and ultimo.tipo == 'ENTRADA':
        return EstadoDia(registros, 'SALIDA', usados, ultima_entrada)

    # Último fue SALIDA (o aún no hay registros): ¿puede volver a entrar?
    n = len(horario.bloques)
    limite = max(n, 1) + _cfg('ASISTENCIA_REENTRADAS_EXTRA', 3)
    if len(entradas) >= limite:
        return EstadoDia(registros, None, usados, ultima_entrada)

    if ultimo is not None:
        if n == 0:
            return EstadoDia(registros, None, usados, ultima_entrada)   # sin horario: un par por día
        pendientes = [
            b for b in horario.bloques
            if b.numero not in usados and ahora < _aware(ahora.date(), b.salida)
        ]
        if not pendientes:
            return EstadoDia(registros, None, usados, ultima_entrada)

    return EstadoDia(registros, 'ENTRADA', usados, ultima_entrada)


# ══════════════════════════════════════════════════════════════════════════════
# RECONOCIMIENTO FACIAL
# ══════════════════════════════════════════════════════════════════════════════
# El navegador (face-api.js) convierte el rostro en un descriptor de 128 números.
# Dos fotos de la misma persona dan descriptores a distancia euclidiana pequeña
# (< ~0.5); personas distintas suelen superar 0.6.

def normalizar_descriptor(valor) -> Optional[np.ndarray]:
    """Devuelve un vector float de 128 posiciones o None si no es válido."""
    try:
        v = np.asarray(valor, dtype=float)
    except (TypeError, ValueError):
        return None
    if v.shape != (DESCRIPTOR_LEN,) or not np.all(np.isfinite(v)):
        return None
    return v


def descriptores_enrolados(enrolamiento) -> List[np.ndarray]:
    datos = enrolamiento.vector_facial
    if not isinstance(datos, list):
        return []
    out = [normalizar_descriptor(d) for d in datos]
    return [d for d in out if d is not None]


def distancia_facial(referencias: List[np.ndarray], candidato: np.ndarray) -> float:
    return float(min(np.linalg.norm(r - candidato) for r in referencias))


class ErrorEnrolamiento(Exception):
    pass


def procesar_enrolamiento(enrolamiento: EnrolamientoFacial, descriptores_raw, foto_base64=None):
    """
    Valida y guarda un enrolamiento. Lanza ErrorEnrolamiento con un mensaje para
    el usuario si los datos no sirven.
    """
    if not isinstance(descriptores_raw, list):
        raise ErrorEnrolamiento('No se recibieron los datos faciales. Intenta nuevamente.')
    minimo = _cfg('ASISTENCIA_ENROLAMIENTO_MIN_CAPTURAS', 3)
    descriptores = [normalizar_descriptor(d) for d in descriptores_raw]
    descriptores = [d for d in descriptores if d is not None]
    if len(descriptores) < minimo:
        raise ErrorEnrolamiento(
            f'No se detectó tu rostro en suficientes capturas (mínimo {minimo}). '
            'Mejora la iluminación, mira a la cámara e intenta de nuevo.'
        )

    distancias = [
        float(np.linalg.norm(a - b))
        for i, a in enumerate(descriptores) for b in descriptores[i + 1:]
    ]
    if max(distancias) > _cfg('ASISTENCIA_ENROLAMIENTO_MAX_DISPERSION', 0.65):
        raise ErrorEnrolamiento(
            'Las capturas no parecen de la misma persona o salieron muy distintas. '
            'Asegúrate de estar solo frente a la cámara e intenta de nuevo.'
        )

    ahora = timezone.now()
    enrolamiento.vector_facial = [[round(float(x), 6) for x in d] for d in descriptores]
    enrolamiento.estado = 'enrolado'
    enrolamiento.intentos_fallidos = 0
    enrolamiento.fecha_enrolamiento = ahora
    enrolamiento.score_promedio = round(1 - float(np.mean(distancias)), 4)   # 1 = capturas idénticas

    foto = _decodificar_foto(foto_base64, f"enrol_{enrolamiento.user_id}_{ahora:%Y%m%d%H%M%S}")
    if foto is not None:
        try:
            enrolamiento.foto_referencia.save(foto.name, foto, save=False)
        except Exception:
            logger.error('No se pudo guardar la foto de enrolamiento', exc_info=True)

    with transaction.atomic():
        enrolamiento.save()
        permiso = enrolamiento.permisos.filter(usado=False).first()
        if permiso:
            permiso.usado = True
            permiso.fecha_usado = ahora
            permiso.save(update_fields=['usado', 'fecha_usado'])
    return enrolamiento


def _decodificar_foto(foto_base64, nombre_base) -> Optional[ContentFile]:
    """data-URL base64 → ContentFile; None si falta o no es una imagen aceptable."""
    if not foto_base64:
        return None
    try:
        formato, datos = foto_base64.split(';base64,', 1)
        ext = formato.split('/')[-1].lower()
        if ext not in FORMATOS_FOTO:
            return None
        binario = base64.b64decode(datos, validate=True)
        if not binario or len(binario) > MAX_FOTO_BYTES:
            return None
        return ContentFile(binario, name=f"{nombre_base}.{'jpg' if ext == 'jpeg' else ext}")
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# VALIDACIÓN Y REGISTRO DE UN MARCADO
# ══════════════════════════════════════════════════════════════════════════════

class ValidadorAsistencia:
    """
    Marcado del profesional: GPS → secuencia del día → biométrico → registro.
    Retorna (exito, registro, errores) en ejecutar().
    """

    def __init__(self, user, tipo, latitud, longitud,
                 vector_facial_recibido, foto_base64=None,
                 device_id=None, observacion='', precision_gps=None):
        self.user = user
        self.tipo = tipo
        self.lat = latitud
        self.lon = longitud
        self.vector_recibido = vector_facial_recibido
        self.foto_base64 = foto_base64
        self.device_id = device_id or ''
        self.observacion = observacion or ''
        self.precision = precision_gps
        self.errores = []
        self.score_facial = None
        self.zona_valida = None
        self.distancia = None
        self.config_valida = None

    @property
    def umbral_facial(self):
        return _cfg('ASISTENCIA_UMBRAL_FACIAL', 0.5)

    # ── Capa 1: GPS ──────────────────────────────────────────────────────────

    def validar_gps(self):
        if self.lat is None or self.lon is None:
            self.errores.append("No se recibieron coordenadas GPS.")
            return False
        if not (-90 <= float(self.lat) <= 90 and -180 <= float(self.lon) <= 180):
            self.errores.append("Las coordenadas GPS no son válidas.")
            return False

        precision_max = _cfg('ASISTENCIA_PRECISION_GPS_MAX', 150)
        if self.precision is not None and self.precision > precision_max:
            self.errores.append(
                f"Precisión GPS insuficiente (±{self.precision:.0f} m, máximo ±{precision_max} m). "
                "Espera unos segundos a que mejore la señal o sal a un lugar abierto."
            )
            return False

        configs = list(
            ConfigAsistencia.objects.filter(user=self.user, zona__activa=True)
            .select_related('zona')
            .prefetch_related('zona__plantillas__bloques')
        )
        if not configs:
            self.errores.append("No tienes zonas de asistencia asignadas.")
            return False

        mas_cercana = None
        for config in configs:
            en_zona, distancia = config.zona.contiene_punto(self.lat, self.lon)
            if en_zona:
                self.zona_valida = config.zona
                self.distancia = distancia
                self.config_valida = config
                return True
            if mas_cercana is None or distancia < mas_cercana[0]:
                mas_cercana = (distancia, config.zona)

        self.distancia = mas_cercana[0]
        self.errores.append(
            f"Fuera de todas tus zonas autorizadas. "
            f"La más cercana es «{mas_cercana[1].nombre}», a {mas_cercana[0]:.0f} m."
        )
        return False

    # ── Capa 2: Biométrico ───────────────────────────────────────────────────

    def validar_facial(self):
        try:
            enrolamiento = self.user.enrolamiento
        except EnrolamientoFacial.DoesNotExist:
            self.errores.append("No tienes enrolamiento facial registrado.")
            return False

        if enrolamiento.estado == 'bloqueado':
            self.errores.append("Tu verificación facial está bloqueada. Contacta al administrador.")
            return False
        if enrolamiento.estado != 'enrolado':
            self.errores.append("Aún no registraste tu rostro. Hazlo desde «Mi asistencia».")
            return False

        referencias = descriptores_enrolados(enrolamiento)
        if not referencias:
            self.errores.append(
                "Tu registro facial es inválido o de una versión anterior. "
                "Pide al administrador que habilite un nuevo enrolamiento."
            )
            return False

        candidato = normalizar_descriptor(self.vector_recibido)
        if candidato is None:
            self.errores.append(
                "No se pudo leer tu rostro. Asegúrate de que se vea claramente y vuelve a intentar."
            )
            return False

        self.score_facial = distancia_facial(referencias, candidato)
        if self.score_facial > self.umbral_facial:
            self.errores.append("No se pudo verificar tu identidad. Intenta con mejor iluminación.")
            return False
        return True

    # ── Foto ─────────────────────────────────────────────────────────────────

    def _foto_como_archivo(self):
        return _decodificar_foto(
            self.foto_base64,
            f"cap_{self.user.id}_{timezone.localtime():%H%M%S}",
        )

    # ── Ejecución ────────────────────────────────────────────────────────────

    def ejecutar(self):
        with transaction.atomic():
            # Bloquea al usuario: dos marcados simultáneos no pueden duplicarse.
            User.objects.select_for_update().get(pk=self.user.pk)
            return self._ejecutar()

    def _datos_base(self, **extra):
        datos = dict(
            user=self.user, tipo=self.tipo,
            latitud=self.lat, longitud=self.lon,
            distancia_metros=self.distancia, precision_metros=self.precision,
            device_id=self.device_id,
        )
        datos.update(extra)
        return datos

    def _ejecutar(self):
        # 1 — GPS
        if not self.validar_gps():
            registro = RegistroAsistencia.objects.create(**self._datos_base(
                estado='DENEGADO_GPS', zona=self.zona_valida))
            return False, registro, self.errores

        # 2 — Secuencia del día (servidor)
        ahora = timezone.now()
        fecha = timezone.localdate(ahora)
        horario = ResolvedorHorario(
            self.user, self.zona_valida, self.config_valida, fecha
        ).resolver()
        estado_dia = calcular_estado_dia(registros_validos_del_dia(self.user, fecha), horario, ahora)

        if estado_dia.completo:
            self.errores.append("Ya completaste tu jornada de hoy.")
            return False, None, self.errores
        if self.tipo != estado_dia.siguiente:
            ya = 'una entrada' if self.tipo == 'ENTRADA' else 'una salida'
            falta = 'salida' if estado_dia.siguiente == 'SALIDA' else 'entrada'
            self.errores.append(f"Ya registraste {ya}. Lo siguiente que debes marcar es la {falta}.")
            return False, None, self.errores

        # 3 — Biométrico
        if not self.validar_facial():
            registro = RegistroAsistencia.objects.create(**self._datos_base(
                estado='DENEGADO_BIO', zona=self.zona_valida,
                biometrico_score=self.score_facial))
            enrol = getattr(self.user, 'enrolamiento', None)
            if enrol is not None and enrol.estado == 'enrolado':
                enrol.registrar_fallo()
                if enrol.estado == 'bloqueado':
                    self.errores.append(
                        "Superaste el máximo de intentos fallidos. "
                        "Tu verificación facial fue bloqueada: contacta al administrador."
                    )
            return False, registro, self.errores
        self.user.enrolamiento.registrar_exito()

        # 4 — Estado (puntual / tardanza)
        if self.tipo == 'ENTRADA':
            estado, bloque, minutos = CalculadorEstado(horario, ahora, estado_dia.bloques_usados).calcular()
        else:
            estado, minutos = 'PUNTUAL', 0
            bloque = estado_dia.ultima_entrada.bloque if estado_dia.ultima_entrada else ''

        registro = self._guardar_registro(
            estado=estado, bloque=bloque, minutos_tardanza=minutos,
            zona=self.zona_valida, biometrico_score=self.score_facial,
            observacion=self.observacion, fecha_hora=ahora,
        )
        if self.tipo == 'ENTRADA' and bloque:
            anular_ausencia(self.user, fecha, bloque)
        return True, registro, []

    def _guardar_registro(self, **extra):
        datos = self._datos_base(**extra)
        foto = self._foto_como_archivo()
        try:
            return RegistroAsistencia.objects.create(foto_captura=foto, **datos)
        except Exception:
            if foto is None:
                raise
            # La foto se sube a almacenamiento externo (R2) al guardar. Si falla, el
            # marcado NO debe perderse: se registra sin foto y se deja constancia en el log.
            logger.error('No se pudo guardar la foto de captura; se registra sin foto', exc_info=True)
            return RegistroAsistencia.objects.create(foto_captura=None, **datos)


# ══════════════════════════════════════════════════════════════════════════════
# MARCADO MANUAL (administrador)
# ══════════════════════════════════════════════════════════════════════════════

def _configs_usuario(user):
    return list(
        ConfigAsistencia.objects.filter(user=user, zona__activa=True)
        .select_related('zona').prefetch_related('zona__plantillas__bloques')
    )


def registrar_manual(user, tipo, admin, observacion='', ahora=None):
    """
    El administrador registra una entrada/salida. Usa la misma secuencia y el mismo
    cálculo de tardanza que el marcado normal, pero sin GPS ni rostro.
    Retorna (exito, registro_o_None, mensaje_error).
    """
    ahora = ahora or timezone.now()
    fecha = timezone.localdate(ahora)
    with transaction.atomic():
        User.objects.select_for_update().get(pk=user.pk)
        config, horario = elegir_config_y_horario(user, fecha, _configs_usuario(user))
        estado_dia = calcular_estado_dia(registros_validos_del_dia(user, fecha), horario, ahora)

        if estado_dia.completo:
            return False, None, f'{user.get_full_name()} ya completó su jornada de hoy.'
        if tipo != estado_dia.siguiente:
            return False, None, (
                f'{user.get_full_name()} no puede tener ahora una '
                f'{"entrada" if tipo == "ENTRADA" else "salida"}: '
                f'lo siguiente es la {estado_dia.siguiente.lower()}.'
            )

        if tipo == 'ENTRADA':
            estado, bloque, minutos = CalculadorEstado(horario, ahora, estado_dia.bloques_usados).calcular()
        else:
            estado, minutos = 'PUNTUAL', 0
            bloque = estado_dia.ultima_entrada.bloque if estado_dia.ultima_entrada else ''

        nota = f"Registrado manualmente por {admin.get_full_name() or admin.username}."
        if observacion:
            nota += f" Motivo: {observacion}"

        registro = RegistroAsistencia.objects.create(
            user=user, zona=config.zona if config else None, tipo=tipo,
            estado=estado, bloque=bloque, minutos_tardanza=minutos,
            observacion=nota, registrado_por=admin, fecha_hora=ahora,
        )
        if tipo == 'ENTRADA' and bloque:
            anular_ausencia(user, fecha, bloque)
        return True, registro, ''


# ══════════════════════════════════════════════════════════════════════════════
# AUSENCIAS
# ══════════════════════════════════════════════════════════════════════════════

def anular_ausencia(user, fecha, bloque):
    """Si ya se había generado un AUSENTE para ese bloque y luego llegó, se elimina."""
    RegistroAsistencia.objects.filter(
        user=user, tipo='ENTRADA', estado='AUSENTE', bloque=str(bloque), fecha_hora__date=fecha,
    ).delete()


def _fechas_especiales_por_zona(fecha):
    por_zona = {}
    for fe in FechaEspecial.objects.filter(fecha=fecha).prefetch_related('bloques', 'profesionales'):
        por_zona.setdefault(fe.zona_id, []).append(fe)
    return por_zona


def _configs_por_usuario():
    por_user = {}
    qs = (ConfigAsistencia.objects.filter(zona__activa=True)
          .select_related('zona').prefetch_related('zona__plantillas__bloques').order_by('pk'))
    for c in qs:
        por_user.setdefault(c.user_id, []).append(c)
    return por_user


def generar_ausentes(fecha: Optional[date] = None, ahora=None, incluir_sin_enrolar=False):
    """
    Crea un registro AUSENTE por cada bloque laborable YA TERMINADO en el que el
    profesional no marcó entrada. Es idempotente: puede ejecutarse cada hora.

    No genera ausencias en días libres, fechas especiales libres, días sin horario,
    ni (por defecto) para profesionales que aún no enrolaron su rostro.
    Retorna la cantidad de ausencias creadas.
    """
    ahora = timezone.localtime(ahora or timezone.now())
    fecha = fecha or ahora.date()
    fechas_por_zona = _fechas_especiales_por_zona(fecha)
    configs_por_user = _configs_por_usuario()

    profesionales = User.objects.filter(perfil__rol='profesional', is_active=True).select_related('enrolamiento')
    regs = {}
    for r in RegistroAsistencia.objects.filter(fecha_hora__date=fecha, tipo='ENTRADA',
                                               estado__in=['PUNTUAL', 'TARDANZA', 'AUSENTE']):
        regs.setdefault(r.user_id, []).append(r)

    creadas = 0
    for user in profesionales:
        enrol = getattr(user, 'enrolamiento', None)
        if not incluir_sin_enrolar and (enrol is None or enrol.estado == 'pendiente'):
            continue
        config, horario = elegir_config_y_horario(
            user, fecha, configs_por_user.get(user.pk, []), fechas_por_zona)
        if config is None or not horario.es_laborable:
            continue

        cubiertos = {r.bloque for r in regs.get(user.pk, []) if r.bloque}
        for b in horario.bloques:
            fin = _aware(fecha, b.salida)
            if ahora < fin or str(b.numero) in cubiertos:
                continue
            RegistroAsistencia.objects.create(
                user=user, zona=config.zona, tipo='ENTRADA', estado='AUSENTE',
                bloque=str(b.numero), fecha_hora=fin,
                observacion='Generado automáticamente: sin entrada en este bloque.',
            )
            creadas += 1
    return creadas


# ══════════════════════════════════════════════════════════════════════════════
# PANEL DEL ADMINISTRADOR (resumen diario)
# ══════════════════════════════════════════════════════════════════════════════

def construir_panel(fecha: date, ahora=None):
    """
    Una fila por profesional con su día completo. Usa un número fijo de consultas
    (no depende de cuántos profesionales haya).
    """
    ahora = timezone.localtime(ahora or timezone.now())
    es_hoy = fecha == ahora.date()
    profesionales = list(
        User.objects.filter(perfil__rol='profesional', is_active=True)
        .select_related('perfil__profesional', 'enrolamiento')
        .order_by('last_name', 'first_name')
    )
    fechas_por_zona = _fechas_especiales_por_zona(fecha)
    configs_por_user = _configs_por_usuario()

    por_user = {}
    for r in (RegistroAsistencia.objects.filter(fecha_hora__date=fecha)
              .select_related('zona').order_by('fecha_hora', 'pk')):
        por_user.setdefault(r.user_id, []).append(r)

    filas = []
    for user in profesionales:
        todos = por_user.get(user.pk, [])
        validos = [r for r in todos if r.estado in RegistroAsistencia.ESTADOS_VALIDOS]
        ausencias = [r for r in todos if r.estado == 'AUSENTE']
        denegados = [r for r in todos if r.estado.startswith('DENEGADO')]

        config, horario = elegir_config_y_horario(
            user, fecha, configs_por_user.get(user.pk, []), fechas_por_zona)
        estado_dia_obj = calcular_estado_dia(validos, horario, ahora if es_hoy else None)

        enrol = getattr(user, 'enrolamiento', None)
        enrolado = enrol is not None and enrol.estado == 'enrolado'
        entradas = [r for r in validos if r.tipo == 'ENTRADA']

        if entradas:
            estado = 'TARDANZA' if any(r.estado == 'TARDANZA' for r in entradas) else 'PUNTUAL'
        elif not enrolado:
            estado = 'sin_enrolar'
        elif ausencias:
            estado = 'ausente'
        elif horario.tipo == 'libre':
            estado = 'libre'
        elif not horario.es_laborable:
            estado = 'sin_horario'
        else:
            primer_fin = _aware(fecha, horario.bloques[0].salida)
            estado = 'ausente' if (fecha < ahora.date() or ahora >= primer_fin) else 'pendiente'

        filas.append({
            'user': user,
            'profesional': getattr(getattr(user, 'perfil', None), 'profesional', None),
            'zona': (config.zona if config else (validos[0].zona if validos else None)),
            'horario': horario,
            'pares': estado_dia_obj.pares,
            'entradas': entradas,
            'ausencias': ausencias,
            'minutos_tardanza': sum(r.minutos_tardanza for r in entradas),
            'siguiente': estado_dia_obj.siguiente,
            'estado_dia': estado,
            'estado_enrolamiento': enrol.estado if enrol else 'pendiente',
            'intentos_fallidos': len(denegados),
        })

    resumen = {
        'presentes': sum(1 for f in filas if f['estado_dia'] in ('PUNTUAL', 'TARDANZA')),
        'tardanzas': sum(1 for f in filas if f['estado_dia'] == 'TARDANZA'),
        'ausentes': sum(1 for f in filas if f['estado_dia'] == 'ausente'),
        'sin_enrolar': sum(1 for f in filas if f['estado_dia'] == 'sin_enrolar'),
    }
    return filas, resumen
