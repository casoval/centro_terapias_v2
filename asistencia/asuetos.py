"""
Asuetos: tiempo libre CONCEDIDO por el centro (Día de la Mujer, cumpleaños, vacaciones...).

* No es falta, no es permiso (justificación de una falta) ni asistencia: es neutro. El bloque cubierto por un
  asueto no genera AUSENTE, no descuenta, no cuenta como día con horario ni como horas esperadas.
* Funciona con SALDO: el administrador OTORGA un derecho (DerechoAsueto: ½ día, 1 día, varios...) a quien
  corresponda (todos, una sucursal, una zona, profesionales elegidos, por sexo, por cumpleaños) y cada
  profesional lo USA (UsoAsueto) en la fecha y el bloque que elija, sin pasarse del saldo ni del vencimiento.
* Cada bloque del horario pesa 1/N del día (igual que las faltas): en un horario partido, medio día = un bloque.
"""
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable, Optional

from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from .models import ConfigAsistencia, DerechoAsueto, RegistroAsistencia, TipoAsueto, UsoAsueto

TOLERANCIA_SALDO = Decimal('0.02')       # evita que 3 × 0,33 deje un saldo «fantasma» de 0,01


class AsuetoError(ValueError):
    """Error de negocio con un mensaje listo para mostrar al administrador."""


def fmt_dias_asueto(valor) -> str:
    """0.5 -> 'medio día', 1 -> '1 día', 1.5 -> '1,5 días'."""
    v = round(float(valor), 2)
    if v == 0.5:
        return 'medio día'
    txt = str(int(v)) if v == int(v) else f"{v:.2f}".rstrip('0').replace('.', ',')
    return f"{txt} día" + ('' if v == 1 else 's')


# ── Destinatarios ────────────────────────────────────────────────────────────

def profesionales_activos():
    return User.objects.filter(perfil__rol='profesional', is_active=True)


def destinatarios(destino='todos', sucursal_ids=(), zona_ids=(), user_ids=(), sexo='', cumple_mes=None,
                  cumple_dia=None):
    """
    Profesionales que recibirán el asueto.
      destino: 'todos' | 'sucursal' | 'zona' | 'elegidos'
      sexo:    'F' | 'M' | '' (filtro adicional; requiere el dato en la ficha del profesional)
      cumple_mes / cumple_dia: filtro adicional por cumpleaños (mes, o mes y día)
    """
    qs = profesionales_activos()
    if destino == 'sucursal':
        qs = qs.filter(profesional__sucursales__in=list(sucursal_ids))
    elif destino == 'zona':
        qs = qs.filter(configs_asistencia__zona__in=list(zona_ids))
    elif destino == 'elegidos':
        qs = qs.filter(pk__in=list(user_ids))
    if sexo:
        qs = qs.filter(profesional__sexo=sexo)
    if cumple_mes:
        qs = qs.filter(profesional__fecha_nacimiento__month=cumple_mes)
        if cumple_dia:
            qs = qs.filter(profesional__fecha_nacimiento__day=cumple_dia)
    return qs.distinct().order_by('last_name', 'first_name')


# ── Otorgar ──────────────────────────────────────────────────────────────────

def otorgar(tipo: TipoAsueto, users: Iterable, dias, motivo='', otorgado_el: Optional[date] = None,
            vence_el: Optional[date] = None, creado_por=None, referencia=''):
    """
    Crea un DerechoAsueto por usuario. No duplica: si el usuario ya tiene el mismo tipo + motivo + fecha de
    otorgamiento (p. ej. se envió dos veces el formulario) lo omite. Devuelve (creados, omitidos).
    """
    dias = Decimal(str(dias))
    if dias <= 0:
        raise AsuetoError('Los días del asueto deben ser mayores que cero.')
    otorgado_el = otorgado_el or timezone.localdate()
    if vence_el is None and tipo.vence_dias:
        vence_el = otorgado_el + timedelta(days=tipo.vence_dias)
    if vence_el is not None and vence_el < otorgado_el:
        raise AsuetoError('La fecha de vencimiento no puede ser anterior a la de otorgamiento.')
    creados = omitidos = 0
    with transaction.atomic():
        for u in users:
            existe = DerechoAsueto.objects.filter(user=u, tipo=tipo, motivo=motivo, otorgado_el=otorgado_el)
            if referencia:
                existe = existe | DerechoAsueto.objects.filter(user=u, tipo=tipo, referencia=referencia)
            if existe.exists():
                omitidos += 1
                continue
            DerechoAsueto.objects.create(
                user=u, tipo=tipo, motivo=motivo, dias=dias, otorgado_el=otorgado_el, vence_el=vence_el,
                creado_por=creado_por, referencia=referencia)
            creados += 1
    return creados, omitidos


def otorgar_cumpleanos(fecha: Optional[date] = None):
    """
    Otorga el asueto de cumpleaños (tipos con cumpleanos_auto) a quienes cumplen años en `fecha`
    (29/02 se celebra el 28/02 en años no bisiestos). Idempotente. Devuelve cuántos derechos creó.
    """
    fecha = fecha or timezone.localdate()
    dias_cumple = [(fecha.month, fecha.day)]
    if fecha.month == 2 and fecha.day == 28 and not _bisiesto(fecha.year):
        dias_cumple.append((2, 29))
    total = 0
    for tipo in TipoAsueto.objects.filter(cumpleanos_auto=True, activo=True):
        for mes, dia in dias_cumple:
            users = destinatarios(cumple_mes=mes, cumple_dia=dia)
            c, _o = otorgar(tipo, users, tipo.dias, motivo=f"{tipo.nombre} {fecha.year}", otorgado_el=fecha,
                            referencia=f"cumple-{fecha.year}")
            total += c
    return total


def _bisiesto(anio):
    return anio % 4 == 0 and (anio % 100 != 0 or anio % 400 == 0)


# ── Usar ─────────────────────────────────────────────────────────────────────

def _horario_del_dia(user, fecha):
    # import tardío: services importa este módulo
    from .services import _configs_por_usuario, elegir_config_y_horario
    configs = [c for c in ConfigAsistencia.objects.filter(user=user, zona__activa=True)
               .select_related('zona').prefetch_related('zona__plantillas__bloques', 'periodos_propios')]
    return elegir_config_y_horario(user, fecha, configs)[1]


def registrar_uso(derecho: DerechoAsueto, fecha: date, bloque='', admin=None, nota='') -> UsoAsueto:
    """
    Usa (parte de) un derecho en `fecha`. bloque '' = todo el día; '1', '2'... = solo ese bloque.
    Valida vencimiento, horario del día, solapes y saldo. Si ya se había generado un AUSENTE para los bloques
    cubiertos, lo elimina. Lanza AsuetoError con un mensaje claro si algo no corresponde.
    """
    bloque = str(bloque or '')
    user = derecho.user
    if derecho.vence_el and fecha > derecho.vence_el:
        raise AsuetoError(f"Este asueto vence el {derecho.vence_el:%d/%m/%Y}: elige una fecha hasta ese día.")
    horario = _horario_del_dia(user, fecha)
    if not horario.es_laborable:
        raise AsuetoError(f"El {fecha:%d/%m/%Y} no es un día con horario para esta persona: no hace falta asueto.")
    n = len(horario.bloques)
    numeros = {str(b.numero) for b in horario.bloques}
    if bloque and bloque not in numeros:
        raise AsuetoError(f"Ese día no tiene el bloque {bloque} (bloques: {', '.join(sorted(numeros))}).")
    if bloque and n == 1:
        bloque = ''                                    # un solo bloque = el día completo
    dias = Decimal(1) if not bloque else (Decimal(1) / n).quantize(Decimal('0.01'))

    previos = UsoAsueto.objects.filter(user=user, fecha=fecha)
    if previos.filter(bloque='').exists() or (not bloque and previos.exists()) or previos.filter(bloque=bloque).exists():
        raise AsuetoError(f"El {fecha:%d/%m/%Y} ya tiene un asueto registrado que se solapa con este.")
    if dias > derecho.saldo + TOLERANCIA_SALDO:
        raise AsuetoError(f"El saldo de este asueto es de {fmt_dias_asueto(derecho.saldo)} y esto usa "
                          f"{fmt_dias_asueto(dias)}.")
    with transaction.atomic():
        uso = UsoAsueto.objects.create(derecho=derecho, user=user, fecha=fecha, bloque=bloque, dias=dias,
                                       nota=nota, registrado_por=admin)
        ausentes = RegistroAsistencia.objects.filter(user=user, tipo='ENTRADA', estado='AUSENTE',
                                                     fecha_hora__date=fecha)
        if bloque:
            ausentes = ausentes.filter(bloque=bloque)
        ausentes.delete()
    return uso


# ── Consulta (lo usan panel, informe mensual y reportes) ─────────────────────

def usos_por_usuario_fecha(inicio: date, fin: date, user_ids=None):
    """{(user_id, fecha): [UsoAsueto]} del rango."""
    qs = UsoAsueto.objects.filter(fecha__gte=inicio, fecha__lte=fin).select_related('derecho__tipo')
    if user_ids is not None:
        qs = qs.filter(user_id__in=user_ids)
    out = {}
    for u in qs:
        out.setdefault((u.user_id, u.fecha), []).append(u)
    return out


def bloques_en_asueto(usos, numeros_bloque):
    """Subconjunto de `numeros_bloque` (ints) cubierto por esos usos."""
    return {n for n in numeros_bloque if any(u.cubre(n) for u in usos)}


def saldos_por_usuario(user_ids=None, hoy=None):
    """{user_id: {'disponible': Decimal, 'derechos': [DerechoAsueto]}} solo con derechos vigentes y con saldo."""
    hoy = hoy or timezone.localdate()
    qs = DerechoAsueto.objects.select_related('tipo').prefetch_related('usos')
    if user_ids is not None:
        qs = qs.filter(user_id__in=user_ids)
    out = {}
    for d in qs:
        if d.estado(hoy) != 'disponible':
            continue
        e = out.setdefault(d.user_id, {'disponible': Decimal(0), 'derechos': []})
        e['disponible'] += d.saldo
        e['derechos'].append(d)
    return out
