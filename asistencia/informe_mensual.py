"""
Informe mensual de asistencia por profesional.

Para cada día del mes indica si asistió, a qué hora marcó, el retraso, el retraso acumulado y el descuento
acumulado en DÍAS (nunca montos de pago: eso lo decide el administrador). Incluye la evaluación del mes:
estrellas de puntualidad y semáforo de asistencia, cada una con su motivo (ver evaluacion.py).

Reglas
------
* Retraso: solo se acumula lo que EXCEDE la tolerancia (tolerancia de 10 min y marca a las 08:11:00 ->
  1 minuto). Se suma en segundos durante el mes y el total cae en un tramo de ReglasAsistencia que fija
  los días de descuento (services.dias_descuento).
* Falta: un bloque del horario sin ingreso marcado (y ya cerrado el marcado) es una falta. Cada bloque pesa
  1/N del día: en un horario partido faltar uno es MEDIO día y faltar los dos DÍA completo; en un horario
  continuo (un solo bloque, p. ej. el sábado) faltar es DÍA completo.
* Permiso: si el administrador registró una justificación (PermisoAsistencia) para ese día o bloque, no es
  falta con descuento sino «permiso». Se puede justificar hasta el último día del mes de la falta.
* Las faltas se calculan comparando horario y marcaciones (no dependen del comando generar_ausentes). Si el
  admin registró la entrada a mano, el bloque cuenta como cubierto.
* Asueto: tiempo libre concedido por el centro (asuetos.py). El bloque cubierto por un asueto y sin marcar no es
  falta, ni permiso, ni descuento: es neutro (no cuenta como día con horario ni como horas esperadas).
* Reglas de descuento por retraso: cada profesional usa la regla más específica (profesional > sucursal >
  general) vigente el día 1 del mes (services.ResolvedorReglas).
* Control de asistencia: solo se evalúan los días desde que el profesional empezó a ser controlado
  (primera marcación o enrolamiento, lo que ocurra antes). Antes figuran «Sin control» y no generan faltas.
"""
import calendar
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

from django.db.models import Min, prefetch_related_objects
from django.utils import timezone

from .asuetos import fmt_dias_asueto, usos_por_usuario_fecha
from .evaluacion import es_alerta, evaluar_asistencia, evaluar_puntualidad
from .models import (
    EnrolamientoFacial, FechaEspecial, PermisoAsistencia, RegistroAsistencia,
)
from .services import (
    ResolvedorReglas, _sucursal_ids, _aware, _configs_por_usuario, calcular_estado_dia, dias_descuento, elegir_config_y_horario,
    fmt_min_seg, segundos_sin_descuento, texto_tramos,
)

DIAS_ABREV = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']
MESES = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto',
         'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']


def fmt_dias(valor) -> str:
    """0 -> '0', 0.5 -> '0,5', 1.5 -> '1,5' (coma decimal, sin ceros sobrantes)."""
    valor = round(float(valor), 2)
    if valor == int(valor):
        return str(int(valor))
    return f"{valor:.2f}".rstrip('0').replace('.', ',')


def fmt_horas(minutos: int) -> str:
    h, m = divmod(max(int(minutos), 0), 60)
    return f"{h} h {m:02d} min"


@dataclass
class DiaInforme:
    fecha: date
    # puntual | tolerancia | retraso | falta | permiso | asueto | libre | sin_horario | sin_control | futuro | pendiente
    estado: str
    horario: str = ''               # texto del horario del día
    nota: str = ''                  # p. ej. motivo de una fecha especial
    pares: list = field(default_factory=list)   # [(entrada 'HH:MM', salida 'HH:MM'|None, es_retraso)]
    retraso_seg: int = 0            # retraso que se acumula ese día (solo lo que excede la tolerancia)
    acum_seg: int = 0               # retraso acumulado del mes hasta este día
    falta_dias: float = 0.0         # descuento por faltas SIN justificar de este día
    falta_texto: str = ''           # 'Falta medio día' | 'Falta día completo' ...
    permiso_dias: float = 0.0       # parte del día cubierta por un permiso
    permiso_texto: str = ''         # 'Permiso: Certificado médico'
    asueto_dias: float = 0.0        # parte del día cubierta por un asueto (neutro: ni falta ni descuento)
    asueto_texto: str = ''          # 'Asueto: Día de la Mujer (medio día)'
    descuento_acum: float = 0.0     # descuento total (faltas + retraso) acumulado hasta este día
    sin_salida: bool = False        # entrada sin salida en un día ya terminado
    bloques_falta: list = field(default_factory=list)   # números de bloque en falta SIN justificar

    @property
    def dia_abrev(self):
        return DIAS_ABREV[self.fecha.weekday()]

    @property
    def evaluado(self):
        return self.estado not in ('futuro', 'sin_control')


@dataclass
class InformeMensual:
    profesional: object
    user: object
    anio: int
    mes: int
    sucursales: List[str]
    dias: List[DiaInforme]
    control_desde: Optional[date]
    tramos: list                    # [(tope_seg | None, días)] de la regla de ese mes
    resumen: dict

    @property
    def nombre(self):
        return f"{self.profesional.nombre} {self.profesional.apellido}".strip()

    @property
    def periodo(self):
        return f"{MESES[self.mes]} {self.anio}"

    @property
    def texto_regla(self):
        return texto_tramos(self.tramos) if self.tramos else 'sin regla de descuento por retraso configurada'


# ──────────────────────────────────────────────────────────────────────────────

def _fechas_especiales_mes(inicio: date, fin: date):
    por_zona = {}
    for fe in FechaEspecial.objects.filter(fecha__gte=inicio, fecha__lte=fin).prefetch_related(
            'bloques', 'profesionales'):
        por_zona.setdefault(fe.zona_id, []).append(fe)
    return por_zona


def _bloque_dt_minutos(fecha, bloque) -> int:
    return int((_aware(fecha, bloque.salida) - _aware(fecha, bloque.entrada)).total_seconds() // 60)


def construir_informes_mensuales(profesionales, anio: int, mes: int, ahora=None) -> List[InformeMensual]:
    """
    Un InformeMensual por profesional (que tenga usuario). Usa un número fijo de consultas
    (no crece con la cantidad de profesionales).
    """
    ahora = timezone.localtime(ahora or timezone.now())
    hoy = ahora.date()
    profesionales = [p for p in profesionales if p.user_id]
    if not profesionales:
        return []

    # una sola consulta para todas las sucursales (aunque quien llama no haya hecho prefetch)
    prefetch_related_objects(profesionales, 'user', 'sucursales')

    ultimo = calendar.monthrange(anio, mes)[1]
    inicio_mes, fin_mes = date(anio, mes, 1), date(anio, mes, ultimo)
    provisional = fin_mes > hoy
    ids = [p.user_id for p in profesionales]

    resolvedor = ResolvedorReglas(anio, mes)           # reglas vigentes ese mes (los meses pasados no cambian)

    # Marcaciones válidas del mes agrupadas por usuario y día local
    por_user = {}
    for r in (RegistroAsistencia.objects.filter(
            user_id__in=ids, estado__in=RegistroAsistencia.ESTADOS_VALIDOS,
            fecha_hora__date__gte=inicio_mes, fecha_hora__date__lte=fin_mes,
    ).order_by('fecha_hora', 'pk')):
        dia = timezone.localtime(r.fecha_hora).date()
        por_user.setdefault(r.user_id, {}).setdefault(dia, []).append(r)

    # Permisos (justificaciones de faltas) del mes
    permisos = {}
    for pm in PermisoAsistencia.objects.filter(user_id__in=ids, fecha__gte=inicio_mes, fecha__lte=fin_mes):
        permisos.setdefault((pm.user_id, pm.fecha), []).append(pm)

    # Desde cuándo se controla a cada profesional
    inicio_control = {}
    for fila in (RegistroAsistencia.objects.filter(
            user_id__in=ids, estado__in=RegistroAsistencia.ESTADOS_VALIDOS,
    ).values('user_id').annotate(primero=Min('fecha_hora'))):
        inicio_control[fila['user_id']] = timezone.localtime(fila['primero']).date()
    for uid, fecha_enrol in EnrolamientoFacial.objects.filter(
            user_id__in=ids, estado='enrolado', fecha_enrolamiento__isnull=False
    ).values_list('user_id', 'fecha_enrolamiento'):
        d = timezone.localtime(fecha_enrol).date()
        inicio_control[uid] = min(d, inicio_control.get(uid, d))

    configs = _configs_por_usuario()
    fechas_por_zona = _fechas_especiales_mes(inicio_mes, fin_mes)
    asuetos = usos_por_usuario_fecha(inicio_mes, fin_mes, ids)

    informes = []
    for prof in profesionales:
        user = prof.user
        tramos = resolvedor.tramos(user.pk, [s.pk for s in prof.sucursales.all()])   # profesional > sucursal > general
        hay_reglas = any(d > 0 for _t, d in tramos)
        sin_descuento_seg = segundos_sin_descuento(tramos)
        control = inicio_control.get(user.pk)
        marcas = por_user.get(user.pk, {})
        dias = []
        acum = 0                         # segundos de retraso acumulados
        falta_acum = 0.0                 # días de falta SIN justificar
        justificada_acum = 0.0           # días de falta justificada con permiso
        asueto_acum = 0.0                # días cubiertos por asuetos (neutro)
        fechas_falta, lista_permisos = [], []

        tot = dict(dias_con_horario=0, dias_completos=0, dias_con_falta=0, dias_con_permiso=0,
                   faltas_completas=0, faltas_medias=0, tardanzas=0, sin_salida=0,
                   dias_con_asueto=0, trabajado_min=0, esperado_min=0, entradas=0, usos_tolerancia=0, max_tarde_tolerancia=0)

        for n_dia in range(1, ultimo + 1):
            d = date(anio, mes, n_dia)
            _cfg, horario = elegir_config_y_horario(user, d, configs.get(user.pk, []), fechas_por_zona)
            base = dict(fecha=d, horario=horario.descripcion() if horario.es_laborable else '',
                        nota=horario.nombre if horario.origen == 'fecha_especial' else '')
            if not horario.es_laborable:
                base['horario'] = 'Libre' if horario.tipo == 'libre' else ''

            if control is None or d < control:
                dias.append(DiaInforme(estado='sin_control', **base))
                continue
            if d > hoy:
                dias.append(DiaInforme(estado='futuro', **base))
                continue

            regs = marcas.get(d, [])
            estado_dia = calcular_estado_dia(regs, horario, ahora if d == hoy else None)
            entradas = [r for r in regs if r.tipo == 'ENTRADA']
            cubiertos = {r.bloque for r in entradas if r.bloque}
            entradas_bloque = [r for r in entradas if r.bloque]
            retraso_seg = sum(r.segundos_acumulables for r in entradas if r.estado == 'TARDANZA')
            tot['tardanzas'] += sum(1 for r in entradas if r.estado == 'TARDANZA')
            tot['entradas'] += len(entradas_bloque)
            uso_tolerancia = False
            for r in entradas_bloque:
                if r.segundos_tarde > 0 and r.segundos_acumulables == 0:       # llegó tarde pero dentro de la tolerancia
                    uso_tolerancia = True
                    tot['usos_tolerancia'] += 1
                    tot['max_tarde_tolerancia'] = max(tot['max_tarde_tolerancia'], r.segundos_tarde)

            pares, sin_salida = [], False
            for ent, sal in estado_dia.pares:
                pares.append((
                    f"{timezone.localtime(ent.fecha_hora):%H:%M}",
                    f"{timezone.localtime(sal.fecha_hora):%H:%M}" if sal else None,
                    ent.estado == 'TARDANZA',
                ))
                if sal:
                    tot['trabajado_min'] += int((sal.fecha_hora - ent.fecha_hora).total_seconds() // 60)
                elif d < hoy:
                    sin_salida = True
            if sin_salida:
                tot['sin_salida'] += 1

            n = len(horario.bloques)
            permisos_dia = permisos.get((user.pk, d), [])
            faltas = justificadas = pendientes = en_asueto = 0
            permiso_usado = None
            bloques_falta = []
            usos_asueto = asuetos.get((user.pk, d), [])
            for b in horario.bloques:
                if str(b.numero) not in cubiertos and any(u.cubre(b.numero) for u in usos_asueto):
                    en_asueto += 1                              # asueto: ni falta ni horas esperadas
                    continue
                if d < hoy or ahora >= _aware(d, b.salida):
                    tot['esperado_min'] += _bloque_dt_minutos(d, b)
                if str(b.numero) in cubiertos:
                    continue
                if d < hoy or ahora >= b.cierre_marcado(d):
                    pm = next((x for x in permisos_dia if x.cubre(b.numero)), None)
                    if pm:
                        justificadas += 1
                        permiso_usado = permiso_usado or pm
                    else:
                        faltas += 1
                        bloques_falta.append(b.numero)
                else:
                    pendientes += 1

            falta_dias = (faltas / n) if n else 0.0
            permiso_dias = (justificadas / n) if n else 0.0
            falta_texto = permiso_texto = asueto_texto = ''
            asueto_dias = (en_asueto / n) if n else 0.0
            if en_asueto:
                motivo = usos_asueto[0].derecho.motivo or str(usos_asueto[0].derecho.tipo)
                asueto_texto = f"Asueto: {motivo} ({fmt_dias_asueto(asueto_dias)})"
            if faltas:
                falta_texto = ('Falta día completo' if faltas == n else
                               'Falta medio día' if n == 2 else f'Falta {faltas} de {n} bloques')
            if justificadas:
                permiso_texto = f"Permiso: {permiso_usado.get_tipo_display()}"

            if n == 0:
                estado = 'libre' if horario.tipo == 'libre' else 'sin_horario'
            else:
                if en_asueto == n:
                    tot['dias_con_asueto'] += 1                # día entero en asueto: no se evalúa
                elif not (pendientes and not entradas):        # un día que aún no terminó no se cuenta
                    tot['dias_con_horario'] += 1
                    if en_asueto:
                        tot['dias_con_asueto'] += 1
                if faltas:
                    estado = 'falta'
                    tot['dias_con_falta'] += 1
                    tot['faltas_completas' if faltas == n else 'faltas_medias'] += 1
                elif justificadas:
                    estado = 'permiso'
                    tot['dias_con_permiso'] += 1
                elif retraso_seg or any(p[2] for p in pares):
                    estado = 'retraso'
                elif uso_tolerancia:
                    estado = 'tolerancia'
                elif en_asueto == n:
                    estado = 'asueto'
                elif pendientes and not entradas:
                    estado = 'pendiente'
                else:
                    estado = 'puntual'
                if not faltas and not justificadas and not pendientes and en_asueto < n:
                    tot['dias_completos'] += 1

            if faltas:
                fechas_falta.append(d)
            if justificadas:
                lista_permisos.append((d, permiso_usado.get_tipo_display()))
            acum += retraso_seg
            falta_acum += falta_dias
            justificada_acum += permiso_dias
            asueto_acum += asueto_dias
            dias.append(DiaInforme(
                estado=estado, pares=pares, retraso_seg=retraso_seg, acum_seg=acum,
                falta_dias=falta_dias, falta_texto=falta_texto,
                permiso_dias=permiso_dias, permiso_texto=permiso_texto, sin_salida=sin_salida,
                asueto_dias=asueto_dias, asueto_texto=asueto_texto,
                bloques_falta=bloques_falta,
                descuento_acum=falta_acum + dias_descuento(acum, tramos), **base
            ))

        desc_retraso = dias_descuento(acum, tramos)
        punt = evaluar_puntualidad(
            tot['entradas'], tot['usos_tolerancia'], tot['max_tarde_tolerancia'], acum, desc_retraso,
            hay_reglas, sin_descuento_seg, provisional)
        asist = evaluar_asistencia(
            tot['dias_con_horario'], falta_acum, justificada_acum, falta_acum, fechas_falta,
            lista_permisos, provisional)
        resumen = dict(
            tot,
            retraso_seg=acum, retraso_txt=fmt_min_seg(acum),
            desc_retraso=desc_retraso,
            desc_faltas=falta_acum, faltas_justificadas=justificada_acum, asueto_dias=asueto_acum,
            desc_total=falta_acum + desc_retraso,
            hay_control=control is not None, hay_reglas=hay_reglas,
            puntualidad=punt, asistencia=asist, alerta=es_alerta(punt, asist),
            provisional=provisional,
        )
        informes.append(InformeMensual(
            profesional=prof, user=user, anio=anio, mes=mes,
            sucursales=[s.nombre for s in prof.sucursales.all()],
            dias=dias, control_desde=control, tramos=tramos, resumen=resumen,
        ))
    return informes
