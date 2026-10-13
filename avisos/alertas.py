"""
Alertas automáticas (se calculan al momento, no se guardan).

Cada alerta: {'clave', 'nivel': 'urgente'|'atencion', 'titulo', 'detalle', 'url', 'etiqueta_link'}
Alcance:
  admin/gerente  → todo el centro (gerente con sucursales asignadas → solo esas)
  recepcionista  → solo sus sucursales
  profesional    → solo sus pacientes / sus sesiones
  paciente       → solo su cuenta
"""
import logging
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.db.models import Max
from django.urls import reverse
from django.utils import timezone

from .visibilidad import ROL_ADMIN, rol_de, sucursales_ids

log = logging.getLogger(__name__)


def _cfg(nombre, defecto):
    return getattr(settings, nombre, defecto)


def _bs(x):
    return f'Bs. {x:,.2f}'


def _plural(n, uno, varios):
    return f'{n} {uno if n == 1 else varios}'


def _alerta(clave, nivel, titulo, detalle, url_name, etiqueta):
    return {'clave': clave, 'nivel': nivel, 'titulo': titulo, 'detalle': detalle,
            'url': reverse(url_name), 'etiqueta_link': etiqueta}


# ─────────────────────────── alcance de pacientes ───────────────────────────
def _pacientes_activos_en(sucursales):
    """Ids de pacientes activos que pertenecen a alguna de las sucursales (None = todos)."""
    from pacientes.models import Paciente
    qs = Paciente.objects.filter(estado='activo')
    if sucursales is not None:
        qs = qs.filter(sucursales__in=sucursales)
    return set(qs.values_list('id', flat=True).distinct())


def _alcance_pacientes(user, rol):
    """None = todos los pacientes activos; set = solo esos ids. Para profesional se maneja aparte."""
    if rol in (ROL_ADMIN, 'gerente', 'recepcionista'):
        suc = sucursales_ids(user)
        return None if suc is None else _pacientes_activos_en(suc)
    return set()


# ─────────────────────────── bots de WhatsApp ───────────────────────────
def _estado_bot(clave, puerto):
    import requests
    llave = f'avisos_bot_{clave}'
    estado = cache.get(llave)
    if estado is None:
        estado = 'desconectado'
        try:
            r = requests.get(f'http://localhost:{puerto}/status', timeout=2)
            estado = (r.json() or {}).get('status', 'desconectado')
        except Exception:
            pass
        cache.set(llave, estado, 60)
    return estado


def _bot_pausado(clave):
    try:
        from recordatorios.views import _PAUSA_FILES
        ruta = _PAUSA_FILES.get(clave)
        return bool(ruta) and Path(ruta).exists()
    except Exception:
        return False


def alertas_bots(user, rol):
    if not _cfg('AVISOS_CHEQUEAR_BOTS', False) or rol not in (ROL_ADMIN, 'gerente', 'recepcionista'):
        return []
    suc = sucursales_ids(user)
    out = []
    for clave, cfg in _cfg('AVISOS_BOTS', {}).items():
        if suc is not None and cfg['sucursal_id'] not in suc:
            continue
        nombre = cfg['nombre']
        if _estado_bot(clave, cfg['puerto']) != 'conectado':
            out.append(_alerta(f'bot_{clave}', 'urgente', f'WhatsApp de {nombre} desconectado',
                               'No se están enviando recordatorios. Revisa el monitor y reconecta el bot.',
                               'recordatorios:bots-monitor', 'Abrir Monitor de Bots'))
        elif _bot_pausado(clave):
            out.append(_alerta(f'bot_pausa_{clave}', 'atencion', f'WhatsApp de {nombre} en pausa',
                               'El bot está conectado pero pausado: no enviará mensajes hasta reanudarlo.',
                               'recordatorios:bots-monitor', 'Abrir Monitor de Bots'))
    return out


# ─────────────────────────── deuda antigua (pacientes activos) ───────────────────────────
def _cartera_cacheada(hoy):
    cartera = cache.get('avisos_cartera')
    if cartera is None:
        from facturacion.reporte_financiero_data import _cartera
        cartera = _cartera(hoy, None)
        cache.set('avisos_cartera', cartera, 600)
    return cartera


def alertas_deuda(user, rol, hoy):
    if rol not in (ROL_ADMIN, 'gerente', 'recepcionista'):
        return []
    umbral_atencion = _cfg('AVISOS_DEUDA_DIAS_ATENCION', 30)
    umbral_urgente = _cfg('AVISOS_DEUDA_DIAS_URGENTE', 60)
    alcance = _alcance_pacientes(user, rol)
    filas = [f for f in _cartera_cacheada(hoy)['filas']
             if f['activo'] and f['real'] >= 1 and f['edad'] > umbral_atencion
             and (alcance is None or f['id'] in alcance)]
    if not filas:
        return []
    filas.sort(key=lambda f: (-f['edad'], -f['real']))
    total = sum(f['real'] for f in filas)
    urgentes = [f for f in filas if f['edad'] > umbral_urgente]
    peor = filas[0]
    nivel = 'urgente' if urgentes else 'atencion'
    umbral = umbral_urgente if urgentes else umbral_atencion
    n = len(urgentes) if urgentes else len(filas)
    titulo = f'Deuda de más de {umbral} días'
    detalle = (f'{_plural(n, "paciente activo", "pacientes activos")} · {_bs(sum(f["real"] for f in (urgentes or filas)))}. '
               f'La más antigua: {peor["nombre"]} ({peor["edad"]} días, {_bs(peor["real"])}).')
    if urgentes and len(filas) > len(urgentes):
        detalle += f' Además, {len(filas) - len(urgentes)} con más de {umbral_atencion} días.'
    return [_alerta('deuda', nivel, titulo, detalle, 'facturacion:cuentas_corrientes', 'Ver cuentas corrientes')]


# ─────────────────────────── faltas seguidas / abandono ───────────────────────────
def _sesiones_base(user, rol):
    """Sesiones del alcance del usuario + set de pacientes permitidos (None = todos)."""
    from agenda.models import Sesion
    qs = Sesion.objects.all()
    if rol == 'profesional':
        prof = user.perfil.profesional
        if not prof:
            return None, set()
        qs = qs.filter(profesional=prof)
        return qs, None
    return qs, _alcance_pacientes(user, rol)


def _url_pacientes(rol):
    return 'profesionales:mis_pacientes' if rol == 'profesional' else 'pacientes:lista'


def alertas_faltas(user, rol, hoy):
    if rol not in (ROL_ADMIN, 'gerente', 'recepcionista', 'profesional'):
        return []
    qs, alcance = _sesiones_base(user, rol)
    if qs is None:
        return []
    desde = hoy - timedelta(days=_cfg('AVISOS_FALTAS_VENTANA_DIAS', 120))
    qs = qs.filter(fecha__gte=desde, fecha__lte=hoy, paciente__estado='activo',
                   estado__in=['falta', 'permiso', 'realizada', 'realizada_retraso'])
    if alcance is not None:
        qs = qs.filter(paciente_id__in=alcance)
    # Más reciente primero; se cuentan las 'falta' hasta que aparece otro estado.
    racha, cerrado, nombres = {}, set(), {}
    for pid, estado, nom, ape in qs.order_by('paciente_id', '-fecha', '-hora_inicio').values_list(
            'paciente_id', 'estado', 'paciente__nombre', 'paciente__apellido'):
        if pid in cerrado:
            continue
        if estado == 'falta':
            racha[pid] = racha.get(pid, 0) + 1
            nombres[pid] = f'{nom} {ape}'.strip()
        else:
            cerrado.add(pid)
    umb_atencion = _cfg('AVISOS_FALTAS_ATENCION', 2)
    umb_urgente = _cfg('AVISOS_FALTAS_URGENTE', 3)
    lista = sorted(((n, pid) for pid, n in racha.items() if n >= umb_atencion), reverse=True)
    if not lista:
        return []
    nivel = 'urgente' if lista[0][0] >= umb_urgente else 'atencion'
    top = ', '.join(f'{nombres[pid]} ({n})' for n, pid in lista[:3])
    mas = f' y {len(lista) - 3} más' if len(lista) > 3 else ''
    titulo = f'{umb_urgente} o más faltas seguidas' if nivel == 'urgente' else f'{umb_atencion} faltas seguidas'
    return [_alerta('faltas', nivel, titulo,
                    f'{_plural(len(lista), "paciente", "pacientes")}: {top}{mas}.',
                    _url_pacientes(rol), 'Ver pacientes')]


def alertas_abandono(user, rol, hoy):
    if rol not in (ROL_ADMIN, 'gerente', 'recepcionista', 'profesional'):
        return []
    qs, alcance = _sesiones_base(user, rol)
    if qs is None:
        return []
    dias = _cfg('AVISOS_ABANDONO_DIAS', 21)
    qs = qs.filter(paciente__estado='activo')
    if alcance is not None:
        qs = qs.filter(paciente_id__in=alcance)
    ultima = dict(qs.filter(estado__in=['realizada', 'realizada_retraso'], fecha__lte=hoy)
                  .values_list('paciente_id').annotate(m=Max('fecha')))
    con_futuras = set(qs.filter(estado='programada', fecha__gte=hoy).values_list('paciente_id', flat=True))
    limite = hoy - timedelta(days=dias)
    ids = [pid for pid, f in ultima.items() if f <= limite and pid in con_futuras]
    if not ids:
        return []
    from pacientes.models import Paciente
    nombres = [f'{p.nombre} {p.apellido}'.strip() for p in Paciente.objects.filter(id__in=ids)[:3]]
    mas = f' y {len(ids) - 3} más' if len(ids) > 3 else ''
    return [_alerta('abandono', 'atencion', 'Posible abandono',
                    f'{_plural(len(ids), "paciente", "pacientes")} con sesiones agendadas pero sin asistir '
                    f'hace {dias} días o más: {", ".join(nombres)}{mas}.',
                    _url_pacientes(rol), 'Ver pacientes')]


# ─────────────────────────── sesiones pasadas sin estado ───────────────────────────
def alertas_sin_estado(user, rol, hoy):
    if rol not in (ROL_ADMIN, 'gerente', 'recepcionista', 'profesional'):
        return []
    from agenda.models import Sesion
    desde = hoy - timedelta(days=_cfg('AVISOS_SIN_ESTADO_DIAS', 60))
    qs = Sesion.objects.filter(estado='programada', fecha__lt=hoy, fecha__gte=desde)
    if rol == 'profesional':
        prof = user.perfil.profesional
        if not prof:
            return []
        qs = qs.filter(profesional=prof)
    else:
        suc = sucursales_ids(user)
        if suc is not None:
            qs = qs.filter(sucursal_id__in=suc)
    n = qs.count()
    if not n:
        return []
    return [_alerta('sin_estado', 'atencion', 'Sesiones pasadas sin estado',
                    f'{_plural(n, "sesión pasada sigue", "sesiones pasadas siguen")} como «programada». '
                    'Márcalas como realizada, falta, permiso o cancelada.',
                    'agenda:calendario', 'Ir a la agenda')]


# ─────────────────────────── solo administrador ───────────────────────────
def alertas_admin(user, rol, hoy):
    if rol != ROL_ADMIN:
        return []
    out = []
    from inventario.models import TransferenciaInventario
    n = TransferenciaInventario.objects.filter(estado='pendiente').count()
    if n:
        out.append(_alerta('transferencias', 'atencion', 'Transferencias de inventario pendientes',
                           f'{_plural(n, "transferencia espera", "transferencias esperan")} tu aprobación.',
                           'inventario:transferencias', 'Revisar transferencias'))
    if _cfg('AVISOS_CHEQUEAR_RESPALDOS', False):
        from recordatorios.models import RegistroBackup
        ultimo = RegistroBackup.objects.first()
        margen = _cfg('AVISOS_RESPALDO_DIAS', 2)
        if ultimo and not ultimo.exitoso:
            out.append(_alerta('respaldo_fallo', 'urgente', 'El último respaldo falló',
                               f'Falló el {timezone.localtime(ultimo.fecha):%d/%m/%Y %H:%M}. Revisa el monitor de respaldos.',
                               'recordatorios:backup_monitor', 'Abrir Monitor de Respaldos'))
        else:
            ok = RegistroBackup.objects.filter(exitoso=True).first()
            if not ok or ok.fecha < timezone.now() - timedelta(days=margen):
                out.append(_alerta('respaldo_viejo', 'atencion', 'Sin respaldo reciente',
                                   f'No hay un respaldo exitoso en los últimos {margen} días.',
                                   'recordatorios:backup_monitor', 'Abrir Monitor de Respaldos'))
    return out


# ─────────────────────────── paciente ───────────────────────────
def alertas_paciente(user, rol, hoy):
    if rol != 'paciente':
        return []
    pac = user.perfil.paciente
    if not pac or pac.estado != 'activo':
        return []
    from facturacion.models import CuentaCorriente
    from facturacion.reporte_financiero_data import _antiguedad_fifo, _consumos_hasta
    cc = CuentaCorriente.objects.filter(paciente=pac).first()
    real = max(-float(cc.saldo_actual or 0), 0.0) if cc else 0.0
    if real < 1:
        return []
    _, edad = _antiguedad_fifo(_consumos_hasta([pac.id], hoy).get(pac.id, []), real, hoy)
    if edad <= _cfg('AVISOS_DEUDA_DIAS_ATENCION', 30):
        return []
    return [_alerta('saldo', 'atencion', 'Saldo pendiente',
                    f'Tienes un saldo pendiente de {_bs(real)}. Revisa el detalle cuando puedas o '
                    'acércate a recepción; con gusto te ayudamos.',
                    'facturacion:mis_deudas', 'Ver mis deudas')]


_ORDEN = {'urgente': 0, 'atencion': 1}


def alertas_para(user, hoy=None):
    hoy = hoy or timezone.localdate()
    rol = rol_de(user)
    if rol is None:
        return []
    out = []
    for fn in (alertas_bots, alertas_deuda, alertas_faltas, alertas_abandono,
               alertas_sin_estado, alertas_admin, alertas_paciente):
        try:
            if fn is alertas_bots:
                out += fn(user, rol)
            else:
                out += fn(user, rol, hoy)
        except Exception:      # un chequeo roto no debe tumbar el resto
            log.exception('Error calculando alerta %s', fn.__name__)
    out.sort(key=lambda a: _ORDEN[a['nivel']])
    return out
