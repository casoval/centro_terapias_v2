# facturacion/reporte_profesional_data.py
# =====================================================================
# MOTOR DE DATOS DEL REPORTE POR PROFESIONAL
# Lo usan la vista (pantalla) y el generador de PDF, para que ambos
# muestren exactamente los mismos números.
#
# CRITERIOS (alineados con el reporte financiero):
#   · "Consumida"  = realizada, realizada_retraso o falta sin aviso.
#   · "Atendida"   = realizada o realizada_retraso (horas efectivamente trabajadas).
#   · "Ocupa agenda" = programada + consumidas (cancelada/permiso/reprogramada liberan el hueco).
#   · Sesión individual  → genera su monto_cobrado.
#   · Proyecto/Mensualidad → el costo es FIJO, no por sesión. Se reparte entre los
#       profesionales según sus sesiones consumidas (costo / sesiones_consumidas_totales
#       por cada sesión consumida). Si el profesional está solo, se lleva el 100%.
#   · Horas trabajadas = horas de RELOJ (sesiones grupales simultáneas no se duplican).
#   · Horario: asistencia (FechaEspecial > ConfigAsistencia > HorarioPredeterminado);
#       si no hay nada configurado → predeterminado L-V 9:00-12:00 y 14:30-19:00,
#       sábado 9:00-12:00 (editable desde el reporte).
# =====================================================================

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.db.models import Count, Q

CONSUMIDAS = ('realizada', 'realizada_retraso', 'falta')
ATENDIDAS = ('realizada', 'realizada_retraso')
OCUPAN = ('programada', 'realizada', 'realizada_retraso', 'falta')

DIAS_ES = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
DIAS_CORTO = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']
MESES_ES = ['', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio',
            'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
MESES_CORTO = ['', 'Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep',
               'Oct', 'Nov', 'Dic']

MAX_DIAS = 800            # tope de seguridad del rango analizado
GAP_MIN = 30              # huecos menores a esto no se listan
HORA_HEAT_INI, HORA_HEAT_FIN = 7, 21   # franja del mapa de calor (7:00 a 21:00)

HORARIO_DEFAULT = {
    'dias_partido': [0, 1, 2, 3, 4],
    'dias_continuo': [5],
    'manana_ini': '09:00', 'manana_fin': '12:00',
    'tarde_ini': '14:30', 'tarde_fin': '19:00',
    'cont_ini': '09:00', 'cont_fin': '12:00',
}


# ─────────────────────────────────────────────────────────────────────
# UTILIDADES
# ─────────────────────────────────────────────────────────────────────
def _t2m(t):
    return t.hour * 60 + t.minute


def _hhmm(m):
    m = int(m)
    return f"{m // 60:02d}:{m % 60:02d}"


def _parse_hhmm(s, default):
    try:
        h, m = str(s).strip().split(':')[:2]
        h, m = int(h), int(m)
        if 0 <= h <= 23 and 0 <= m <= 59:
            return f"{h:02d}:{m:02d}"
    except Exception:
        pass
    return default


def hm(minutos):
    """Minutos → '12h 30m' (o '45m')."""
    minutos = int(round(minutos or 0))
    h, m = divmod(minutos, 60)
    if h and m:
        return f"{h}h {m:02d}m"
    if h:
        return f"{h}h"
    return f"{m}m"


_NUM_RE = None


def es_num(texto):
    """Convierte números de un texto al formato boliviano: 1,234.50 → 1.234,50"""
    import re
    global _NUM_RE
    if _NUM_RE is None:
        _NUM_RE = re.compile(r'\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+')
    def _c(m):
        return m.group(0).replace(',', '\x00').replace('.', ',').replace('\x00', '.')
    return _NUM_RE.sub(_c, texto) if isinstance(texto, str) else texto


def _pct(num, den):
    return round(float(num) / float(den) * 100, 1) if den else 0.0


def _f(v):
    try:
        return float(v or 0)
    except Exception:
        return 0.0


def _merge(intervalos):
    """Une intervalos [(ini, fin)] solapados."""
    out = []
    for a, b in sorted(i for i in intervalos if i[1] > i[0]):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def _largo(intervalos):
    return sum(b - a for a, b in intervalos)


def _solape(intervalos, bloques):
    """Minutos de `intervalos` que caen dentro de `bloques`."""
    total = 0
    for a, b in intervalos:
        for c, d in bloques:
            lo, hi = max(a, c), min(b, d)
            if hi > lo:
                total += hi - lo
    return total


def _restar(bloques, ocupados):
    """Huecos = bloques − ocupados."""
    huecos = []
    for c, d in bloques:
        cursor = c
        for a, b in ocupados:
            if b <= cursor or a >= d:
                continue
            if a > cursor:
                huecos.append((cursor, min(a, d)))
            cursor = max(cursor, b)
            if cursor >= d:
                break
        if cursor < d:
            huecos.append((cursor, d))
    return huecos


# ─────────────────────────────────────────────────────────────────────
# FECHAS Y FILTROS
# ─────────────────────────────────────────────────────────────────────
def resolver_rango(rango, desde_str, hasta_str, mes_str, anio_str, hoy):
    """
    Devuelve (desde, hasta, rango_efectivo).
    Prioridad: rango rápido → mes+año → fechas manuales → últimos 30 días.
    """
    def _lun(d):
        return d - timedelta(days=d.weekday())

    if rango == 'hoy':
        return hoy, hoy, rango
    if rango == 'ayer':
        d = hoy - timedelta(days=1)
        return d, d, rango
    if rango == 'semana':
        return _lun(hoy), _lun(hoy) + timedelta(days=6), rango
    if rango == 'semana_anterior':
        l = _lun(hoy) - timedelta(days=7)
        return l, l + timedelta(days=6), rango
    if rango == 'mes':
        ini = hoy.replace(day=1)
        fin = (ini + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        return ini, fin, rango
    if rango == 'mes_anterior':
        fin = hoy.replace(day=1) - timedelta(days=1)
        return fin.replace(day=1), fin, rango
    if rango == 'trimestre':
        return hoy - timedelta(days=89), hoy, rango
    if rango == 'semestre':
        return hoy - timedelta(days=179), hoy, rango
    if rango == 'anio':
        return hoy.replace(month=1, day=1), hoy.replace(month=12, day=31), rango
    if rango == 'ultimos_30':
        return hoy - timedelta(days=29), hoy, rango

    # mes + año concretos
    if mes_str and anio_str:
        try:
            m, a = int(mes_str), int(anio_str)
            ini = date(a, m, 1)
            fin = (ini + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            return ini, fin, 'mes_sel'
        except (ValueError, TypeError):
            pass
    # solo año
    if anio_str and not mes_str and not desde_str:
        try:
            a = int(anio_str)
            return date(a, 1, 1), date(a, 12, 31), 'anio_sel'
        except (ValueError, TypeError):
            pass

    if desde_str and hasta_str:
        try:
            d = datetime.strptime(desde_str, '%Y-%m-%d').date()
            h = datetime.strptime(hasta_str, '%Y-%m-%d').date()
            if h < d:
                h = d
            return d, h, ''
        except ValueError:
            pass
    return hoy - timedelta(days=29), hoy, 'ultimos_30'


def leer_horario_manual(get):
    """
    Lee del querystring el horario manual (solo se usa si asistencia no tiene
    horario configurado, o si el usuario marca 'forzar horario manual').
    """
    cfg = dict(HORARIO_DEFAULT)
    cfg['dias_partido'] = list(HORARIO_DEFAULT['dias_partido'])
    cfg['dias_continuo'] = list(HORARIO_DEFAULT['dias_continuo'])
    editado = get.get('h_editado') == '1'
    if editado:
        def _dias(nombre):
            out = []
            for v in get.getlist(nombre):
                try:
                    n = int(v)
                    if 0 <= n <= 6 and n not in out:
                        out.append(n)
                except ValueError:
                    pass
            return out
        cfg['dias_partido'] = _dias('h_partido')
        cfg['dias_continuo'] = [d for d in _dias('h_continuo') if d not in cfg['dias_partido']]
    for k in ('manana_ini', 'manana_fin', 'tarde_ini', 'tarde_fin', 'cont_ini', 'cont_fin'):
        cfg[k] = _parse_hhmm(get.get('h_' + k), HORARIO_DEFAULT[k])
    forzar = get.get('h_forzar') == '1'
    return cfg, forzar, editado


# ─────────────────────────────────────────────────────────────────────
# HORARIO DEL PROFESIONAL
# ─────────────────────────────────────────────────────────────────────
def _bloques_manual(cfg, d):
    wd = d.weekday()
    if wd in cfg['dias_partido']:
        return [(_t2m(datetime.strptime(cfg['manana_ini'], '%H:%M')),
                 _t2m(datetime.strptime(cfg['manana_fin'], '%H:%M'))),
                (_t2m(datetime.strptime(cfg['tarde_ini'], '%H:%M')),
                 _t2m(datetime.strptime(cfg['tarde_fin'], '%H:%M')))]
    if wd in cfg['dias_continuo']:
        return [(_t2m(datetime.strptime(cfg['cont_ini'], '%H:%M')),
                 _t2m(datetime.strptime(cfg['cont_fin'], '%H:%M')))]
    return []


def _buscar_config_asistencia(prof, sucursal_id):
    """Devuelve (zona, config) con horario válido o (None, None)."""
    from asistencia.models import ConfigAsistencia, ZonaAsistencia

    def _valida(cfg):
        try:
            return bool(cfg.get_dias_partido() or cfg.get_dias_continuo())
        except Exception:
            return False

    candidatas = []
    user = prof.user
    if user:
        candidatas = list(
            ConfigAsistencia.objects.filter(user=user, zona__activa=True)
            .select_related('zona')
        )
    if not candidatas:
        zonas = ZonaAsistencia.objects.filter(
            activa=True, sucursal__in=prof.sucursales.all()
        ).select_related('sucursal')
        for z in zonas:
            candidatas.append(ConfigAsistencia(user=user, zona=z))

    candidatas = [c for c in candidatas if _valida(c)]
    if not candidatas:
        return None, None
    if sucursal_id:
        try:
            sid = int(sucursal_id)
            pref = [c for c in candidatas if c.zona.sucursal_id == sid]
            if pref:
                candidatas = pref
        except ValueError:
            pass
    cfg = candidatas[0]
    return cfg.zona, cfg


def preparar_horario(prof, sucursal_id, desde, hasta, manual_cfg, forzar_manual):
    """
    Devuelve (funcion_bloques(d) -> [(min_ini, min_fin)], info_dict).
    """
    from asistencia.models import FechaEspecial
    from asistencia.services import ResolvedorHorario

    info = {
        'fuente': 'predeterminado',
        'fuente_txt': 'Horario predeterminado del sistema',
        'zona': '',
        'especiales': [],
        'semana': [],
    }

    zona = cfg = None
    if not forzar_manual:
        zona, cfg = _buscar_config_asistencia(prof, sucursal_id)

    if zona is None:
        usando_manual = forzar_manual or manual_cfg != HORARIO_DEFAULT
        info['fuente'] = 'manual' if usando_manual else 'predeterminado'
        info['fuente_txt'] = (
            'Horario manual definido en este reporte' if usando_manual else
            'Sin horario en Asistencia → se usa el horario predeterminado '
            '(L-V 9:00-12:00 y 14:30-19:00, Sáb 9:00-12:00)'
        )

        def bloques(d):
            return _bloques_manual(manual_cfg, d)
    else:
        info['fuente'] = 'asistencia'
        info['zona'] = zona.nombre
        info['fuente_txt'] = f'Horario configurado en Asistencia (zona: {zona.nombre})'
        user = prof.user
        especiales = {}
        for fe in FechaEspecial.objects.filter(zona=zona, fecha__gte=desde, fecha__lte=hasta):
            if (not fe.profesionales.exists()) or (user and fe.profesionales.filter(pk=user.pk).exists()):
                especiales[fe.fecha] = fe
                info['especiales'].append({
                    'fecha': fe.fecha, 'tipo': fe.get_tipo_horario_display(),
                    'motivo': fe.motivo,
                })

        def _bl(h):
            tipo = h.get('tipo')
            if tipo in (None, 'libre'):
                return []
            out = []
            if h.get('hora_entrada') and h.get('hora_salida'):
                out.append((_t2m(h['hora_entrada']), _t2m(h['hora_salida'])))
            if tipo == 'partido' and h.get('hora_entrada_tarde') and h.get('hora_salida_tarde'):
                out.append((_t2m(h['hora_entrada_tarde']), _t2m(h['hora_salida_tarde'])))
            return [(a, b) for a, b in out if b > a]

        def bloques(d):
            if d in especiales:
                return _bl(ResolvedorHorario(user, zona, cfg, d).resolver())
            return _bl({
                'tipo': cfg.tipo_para_dia(d),
                'hora_entrada': cfg.get_hora_entrada(),
                'hora_salida': cfg.get_hora_salida(),
                'hora_entrada_tarde': cfg.get_hora_entrada_tarde(),
                'hora_salida_tarde': cfg.get_hora_salida_tarde(),
            })

    # Resumen semanal tipo (usa una semana de referencia)
    ref = desde - timedelta(days=desde.weekday())
    for i in range(7):
        d = ref + timedelta(days=i)
        bl = bloques(d)
        info['semana'].append({
            'dia': DIAS_ES[i],
            'bloques': [f"{_hhmm(a)} – {_hhmm(b)}" for a, b in bl],
            'horas_txt': hm(_largo(bl)) if bl else 'Libre',
            'minutos': _largo(bl),
        })
    info['especiales'].sort(key=lambda x: x['fecha'])
    return bloques, info


def proximos_huecos(prof, sucursal_id, manual_cfg, forzar_manual, hoy, dias=14):
    """
    Disponibilidad de los PRÓXIMOS `dias` días (desde hoy), sin importar el rango
    que se esté consultando. Hoy solo cuenta lo que falta de la jornada.
    """
    from agenda.models import Sesion
    fin = hoy + timedelta(days=dias - 1)
    bloques_fn, _ = preparar_horario(prof, sucursal_id, hoy, fin, manual_cfg, forzar_manual)
    qs = Sesion.objects.filter(profesional=prof, fecha__gte=hoy, fecha__lte=fin, estado__in=OCUPAN)
    if sucursal_id:
        qs = qs.filter(sucursal_id=sucursal_id)
    por = defaultdict(list)
    for s_ in qs.values_list('fecha', 'hora_inicio', 'hora_fin'):
        por[s_[0]].append((_t2m(s_[1]), _t2m(s_[2])))
    ahora_m = None
    if hoy == date.today():
        from django.utils import timezone
        n = timezone.localtime()
        ahora_m = n.hour * 60 + n.minute
    huecos, cap_tot, libre_tot, ocup_tot = [], 0, 0, 0
    d = hoy
    while d <= fin:
        bl = bloques_fn(d)
        if d == hoy and ahora_m is not None:
            bl = [(max(a, ahora_m), b) for a, b in bl if b > max(a, ahora_m)]
        busy = _merge(por.get(d, []))
        libres = _restar(bl, busy)
        cap_tot += _largo(bl)
        libre_tot += _largo(libres)
        ocup_tot += _solape(busy, bl)
        for a, b in libres:
            if b - a >= GAP_MIN:
                huecos.append({'fecha': d, 'dia': DIAS_ES[d.weekday()], 'ini': _hhmm(a),
                               'fin': _hhmm(b), 'min': b - a, 'txt': hm(b - a)})
        d += timedelta(days=1)
    return {
        'dias': dias, 'desde': hoy, 'hasta': fin, 'huecos': huecos,
        'cap': cap_tot, 'cap_txt': hm(cap_tot), 'libre': libre_tot, 'libre_txt': hm(libre_tot),
        'agendado': ocup_tot, 'agendado_txt': hm(ocup_tot),
        'ocup': _pct(ocup_tot, cap_tot),
    }


# ─────────────────────────────────────────────────────────────────────
# ANÁLISIS PRINCIPAL
# ─────────────────────────────────────────────────────────────────────
def analizar(prof, desde, hasta, sucursal_id='', servicio_id='', paciente_id='',
             tipo='', estado='', manual_cfg=None, forzar_manual=False,
             hoy=None, comparar=True, costo_mensual=0.0, completo=True):
    from agenda.models import Sesion, ServicioProfesionalMensualidad
    from profesionales.models import Profesional

    hoy = hoy or date.today()
    manual_cfg = manual_cfg or dict(HORARIO_DEFAULT)

    nota_rango = ''
    if (hasta - desde).days + 1 > MAX_DIAS:
        hasta = desde + timedelta(days=MAX_DIAS - 1)
        nota_rango = f'El rango se limitó a {MAX_DIAS} días para mantener el reporte ágil.'
    n_dias = (hasta - desde).days + 1

    # ── 1. Sesiones ─────────────────────────────────────────────────
    qs = (Sesion.objects
          .filter(profesional=prof, fecha__gte=desde, fecha__lte=hasta)
          .select_related('paciente', 'servicio', 'sucursal', 'proyecto',
                          'mensualidad', 'comision')
          .order_by('fecha', 'hora_inicio'))
    if sucursal_id:
        qs = qs.filter(sucursal_id=sucursal_id)
    todas = list(qs)   # base de la agenda (todas las sesiones del profesional)

    def _tipo_s(s):
        return 'proyecto' if s.proyecto_id else ('mensualidad' if s.mensualidad_id else 'individual')

    def _pasa(s):
        if servicio_id and str(s.servicio_id) != str(servicio_id):
            return False
        if paciente_id and str(s.paciente_id) != str(paciente_id):
            return False
        if tipo and _tipo_s(s) != tipo:
            return False
        if estado and s.estado != estado:
            return False
        return True

    vista = [s for s in todas if _pasa(s)]
    hay_filtros_contenido = bool(servicio_id or paciente_id or tipo or estado)

    # ── 2. Reparto de proyectos y mensualidades ─────────────────────
    # PARTICIPACIÓN PONDERADA POR PRECIO INDIVIDUAL DE REFERENCIA:
    #   cada sesión pesa lo que costaría como sesión individual de ese paciente
    #   (PacienteServicio.costo_sesion; si no existe, TipoServicio.costo_base).
    #   participación = peso de sus sesiones / peso de TODAS las sesiones del
    #   proyecto/mensualidad (consumidas + programadas, para que el % sea estable
    #   durante el mes y no cambie al ir registrándose las sesiones).
    #   El costo fijo se reparte con ese %; "generado" va devengándose conforme
    #   se consumen las sesiones y "por generar" es lo que falta.
    from pacientes.models import PacienteServicio
    from servicios.models import TipoServicio
    PLANIF = CONSUMIDAS + ('programada',)

    pids = {s.proyecto_id for s in todas if s.proyecto_id}
    mids = {s.mensualidad_id for s in todas if s.mensualidad_id}

    w_tot = {'p': defaultdict(float), 'm': defaultdict(float)}     # peso total por grupo
    w_mio = {'p': defaultdict(float), 'm': defaultdict(float)}     # peso del profesional
    n_tot = {'p': defaultdict(int), 'm': defaultdict(int)}         # nº sesiones planificadas
    n_mio = {'p': defaultdict(int), 'm': defaultdict(int)}
    n_cons_mio = {'p': defaultdict(int), 'm': defaultdict(int)}
    participantes_p = defaultdict(set)
    participantes_m = defaultdict(set)
    precio_base = {t.id: _f(t.costo_base) for t in TipoServicio.objects.all()}
    precios_pac = {}

    def _precio(pac_id, srv_id):
        v = precios_pac.get((pac_id, srv_id))
        if v is None or v <= 0:
            v = precio_base.get(srv_id, 0.0)
        return v

    if pids or mids:
        filtro = Q()
        if pids:
            filtro |= Q(proyecto_id__in=pids)
        if mids:
            filtro |= Q(mensualidad_id__in=mids)
        grupos_rows = list(
            Sesion.objects.filter(filtro, estado__in=PLANIF)
            .values('proyecto_id', 'mensualidad_id', 'profesional_id',
                    'servicio_id', 'paciente_id', 'estado')
            .annotate(n=Count('id')))
        for pid_, sid_, v in PacienteServicio.objects.filter(
                paciente_id__in={r['paciente_id'] for r in grupos_rows}
        ).values_list('paciente_id', 'servicio_id', 'costo_sesion'):
            precios_pac[(pid_, sid_)] = _f(v)
        for r in grupos_rows:
            if r['proyecto_id'] in pids:
                k, gid = 'p', r['proyecto_id']
                participantes_p[gid].add(r['profesional_id'])
            elif r['mensualidad_id'] in mids:
                k, gid = 'm', r['mensualidad_id']
                participantes_m[gid].add(r['profesional_id'])
            else:
                continue
            peso = r['n'] * _precio(r['paciente_id'], r['servicio_id'])
            w_tot[k][gid] += peso
            n_tot[k][gid] += r['n']
            if r['profesional_id'] == prof.id:
                w_mio[k][gid] += peso
                n_mio[k][gid] += r['n']
                if r['estado'] in CONSUMIDAS:
                    n_cons_mio[k][gid] += r['n']
        for s in todas:
            if s.proyecto_id:
                participantes_p[s.proyecto_id].add(s.proyecto.profesional_responsable_id)
        for sp in ServicioProfesionalMensualidad.objects.filter(mensualidad_id__in=mids):
            participantes_m[sp.mensualidad_id].add(sp.profesional_id)
    nombres_prof = {p.id: p.nombre_completo for p in Profesional.objects.all()}

    def _peso_sesion(s):
        """Peso de UNA sesión dentro de su proyecto/mensualidad."""
        k, gid = ('p', s.proyecto_id) if s.proyecto_id else ('m', s.mensualidad_id)
        if w_tot[k][gid] > 0:
            return _precio(s.paciente_id, s.servicio_id), w_tot[k][gid]
        return 1.0, float(n_tot[k][gid] or 1)       # sin precios → reparto por nº de sesiones

    def _alloc(s):
        """Parte del costo fijo que le corresponde a esta sesión."""
        if s.proyecto_id:
            costo = _f(s.proyecto.costo_total)
        else:
            costo = _f(s.mensualidad.costo_mensual)
        peso, total = _peso_sesion(s)
        return costo * peso / total if total else 0.0

    def _gen(s):
        """Ingreso generado por la sesión (criterio del reporte financiero)."""
        if s.estado not in CONSUMIDAS:
            return 0.0
        if s.proyecto_id or s.mensualidad_id:
            return _alloc(s)
        return _f(s.monto_cobrado)

    def _por_generar(s):
        if s.estado != 'programada':
            return 0.0
        if s.proyecto_id or s.mensualidad_id:
            return _alloc(s)
        return _f(s.monto_cobrado)

    # ── 3. Filas ────────────────────────────────────────────────────
    def _fila(s):
        t = _tipo_s(s)
        origen = ''
        modalidad = ''
        if t == 'proyecto':
            origen = s.proyecto.codigo
            modalidad = 'Solo' if len(participantes_p[s.proyecto_id]) <= 1 else 'Grupal'
        elif t == 'mensualidad':
            origen = s.mensualidad.codigo
            modalidad = 'Solo' if len(participantes_m[s.mensualidad_id]) <= 1 else 'Grupal'
        com = getattr(s, 'comision', None) if hasattr(s, 'comision') else None
        try:
            com = s.comision
        except Exception:
            com = None
        gen = _gen(s)
        return {
            'id': s.id,
            'fecha': s.fecha,
            'dia': DIAS_CORTO[s.fecha.weekday()],
            'ini': s.hora_inicio.strftime('%H:%M'),
            'fin': s.hora_fin.strftime('%H:%M'),
            'ini_m': _t2m(s.hora_inicio),
            'fin_m': _t2m(s.hora_fin),
            'dur': s.duracion_minutos or max(_t2m(s.hora_fin) - _t2m(s.hora_inicio), 0),
            'paciente_id': s.paciente_id,
            'paciente': f"{s.paciente.nombre} {s.paciente.apellido}",
            'servicio_id': s.servicio_id,
            'servicio': s.servicio.nombre,
            'color': s.servicio.color or '#3B82F6',
            'sucursal': s.sucursal.nombre,
            'tipo': t,
            'origen': origen,
            'modalidad': modalidad,
            'estado': s.estado,
            'estado_txt': s.get_estado_display(),
            'retraso': s.minutos_retraso or 0,
            'monto': _f(s.monto_cobrado),
            'generado': round(gen, 2),
            'por_generar': round(_por_generar(s), 2),
            'ref': round(_precio(s.paciente_id, s.servicio_id), 2),
            'comision_prof': _f(com.monto_profesional) if (com and s.estado in ATENDIDAS) else None,
            'comision_centro': _f(com.monto_centro) if (com and s.estado in ATENDIDAS) else None,
            'obs': (s.observaciones or '').strip(),
            'tiene_nota': bool((s.notas_sesion or '').strip()),
        }

    filas = [_fila(s) for s in vista]
    filas_todas = filas if not hay_filtros_contenido else [_fila(s) for s in todas]

    # ── 4. Horario y agenda día a día ───────────────────────────────
    bloques_fn, horario_info = preparar_horario(
        prof, sucursal_id, desde, hasta, manual_cfg, forzar_manual)

    por_fecha_all = defaultdict(list)
    for r in filas_todas:
        por_fecha_all[r['fecha']].append(r)
    por_fecha_vista = defaultdict(list)
    for r in filas:
        por_fecha_vista[r['fecha']].append(r)

    dias = []
    heat_busy = defaultdict(float)     # (wd, hora) -> minutos ocupados
    heat_cap = defaultdict(float)      # (wd, hora) -> minutos de horario
    huecos_pasados, huecos_futuros = [], []

    d = desde
    while d <= hasta:
        bl = bloques_fn(d)
        wd = d.weekday()
        rs_all = por_fecha_all.get(d, [])
        busy_iv = _merge([(r['ini_m'], r['fin_m']) for r in rs_all if r['estado'] in OCUPAN])
        att_iv = _merge([(r['ini_m'], r['fin_m']) for r in rs_all if r['estado'] in ATENDIDAS])
        cap = _largo(bl)
        busy_in = _solape(busy_iv, bl)
        att_in = _solape(att_iv, bl)
        busy_tot = _largo(busy_iv)
        att_tot = _largo(att_iv)
        transcurrido = d <= hoy

        # ── Desglose del horario por causa (qué pasó con cada hora) ──
        # efectivo | falta sin aviso | permiso | cancelada | reprogramada |
        # programada (pendiente/agendada) | sin agendar
        def _iv(*estados):
            return _merge([(r['ini_m'], r['fin_m']) for r in rs_all if r['estado'] in estados])
        rem = _restar(bl, att_iv)
        causas = {}
        for nombre, iv in (('falta', _iv('falta')), ('permiso', _iv('permiso')),
                           ('cancelada', _iv('cancelada')), ('reprogramada', _iv('reprogramada')),
                           ('programada', _iv('programada'))):
            causas[nombre] = _solape(iv, rem) if rem else 0
            rem = _restar(rem, iv) if rem else rem
        sin_agendar = _largo(rem)

        gaps = [(a, b) for a, b in _restar(bl, busy_iv) if b - a >= GAP_MIN]
        for a, b in gaps:
            item = {'fecha': d, 'dia': DIAS_ES[wd], 'ini': _hhmm(a), 'fin': _hhmm(b),
                    'min': b - a, 'txt': hm(b - a)}
            (huecos_pasados if transcurrido else huecos_futuros).append(item)

        if transcurrido and cap:
            for h in range(HORA_HEAT_INI, HORA_HEAT_FIN):
                franja = [(h * 60, (h + 1) * 60)]
                heat_cap[(wd, h)] += _solape(bl, franja)
                heat_busy[(wd, h)] += _solape(busy_iv, franja) if bl else 0
                # solo cuenta ocupación dentro del horario
                if bl:
                    inter = _merge([(max(a, h * 60), min(b, (h + 1) * 60))
                                    for a, b in busy_iv if min(b, (h + 1) * 60) > max(a, h * 60)])
                    heat_busy[(wd, h)] += _solape(inter, bl) - _solape(busy_iv, franja)

        rs_v = por_fecha_vista.get(d, [])
        dias.append({
            'fecha': d, 'wd': wd, 'dia': DIAS_ES[wd], 'dia_c': DIAS_CORTO[wd],
            'transcurrido': transcurrido,
            'bloques': [f"{_hhmm(a)}–{_hhmm(b)}" for a, b in bl],
            'cap': cap, 'busy_in': busy_in, 'att_in': att_in,
            'busy_tot': busy_tot, 'att_tot': att_tot,
            'extra': max(busy_tot - busy_in, 0),
            'libre': max(cap - busy_in, 0),
            'ocup': _pct(busy_in, cap),
            'ocup_efect': _pct(att_in, cap),
            'c_falta': causas['falta'], 'c_permiso': causas['permiso'],
            'c_cancel': causas['cancelada'], 'c_reprog': causas['reprogramada'],
            'c_prog': causas['programada'], 'c_libre': sin_agendar,
            'n': len(rs_v),
            'n_atend': sum(1 for r in rs_v if r['estado'] in ATENDIDAS),
            'n_falta': sum(1 for r in rs_v if r['estado'] == 'falta'),
            'n_prog': sum(1 for r in rs_v if r['estado'] == 'programada'),
            'n_otras': sum(1 for r in rs_v if r['estado'] in ('cancelada', 'permiso', 'reprogramada')),
            'gen': round(sum(r['generado'] for r in rs_v), 2),
            'gaps': gaps,
        })
        d += timedelta(days=1)

    # ── 5. Agrupaciones temporales ──────────────────────────────────
    def _agrupar(keyfn, labelfn, subfn=None):
        grupos = {}
        for dd in dias:
            k = keyfn(dd['fecha'])
            g = grupos.setdefault(k, {
                'key': k, 'label': labelfn(dd['fecha']), 'sub': subfn(dd['fecha']) if subfn else '',
                'dias_trab': 0, 'n': 0, 'n_atend': 0, 'n_falta': 0, 'n_prog': 0, 'n_otras': 0,
                'cap': 0, 'busy_in': 0, 'att_in': 0, 'att_tot': 0, 'extra': 0, 'libre': 0,
                'gen': 0.0, 'cap_el': 0, 'busy_el': 0, 'att_el': 0,
                'c_falta': 0, 'c_permiso': 0, 'c_cancel': 0, 'c_reprog': 0, 'c_libre': 0,
            })
            if dd['cap']:
                g['dias_trab'] += 1
            for kk in ('n', 'n_atend', 'n_falta', 'n_prog', 'n_otras', 'cap', 'busy_in',
                       'att_in', 'att_tot', 'extra', 'libre', 'gen'):
                g[kk] += dd[kk]
            if dd['transcurrido']:
                g['cap_el'] += dd['cap']
                g['busy_el'] += dd['busy_in']
                g['att_el'] += dd['att_in']
                for kk in ('c_falta', 'c_permiso', 'c_cancel', 'c_reprog', 'c_libre'):
                    g[kk] += dd[kk]
        out = []
        for k in sorted(grupos):
            g = grupos[k]
            g['ocup'] = _pct(g['busy_in'], g['cap'])
            g['ocup_el'] = _pct(g['busy_el'], g['cap_el'])
            g['ocup_efect'] = _pct(g['att_el'], g['cap_el'])
            g['falta_txt'] = hm(g['c_falta'])
            g['perd_txt'] = hm(g['c_falta'] + g['c_permiso'] + g['c_cancel'] + g['c_reprog'])
            g['sinag_txt'] = hm(g['c_libre'])
            g['gen'] = round(g['gen'], 2)
            g['cap_txt'] = hm(g['cap'])
            g['att_txt'] = hm(g['att_tot'])
            g['libre_txt'] = hm(g['libre'])
            g['extra_txt'] = hm(g['extra'])
            g['busy_txt'] = hm(g['busy_in'])
            out.append(g)
        return out

    def _lunes(f):
        return f - timedelta(days=f.weekday())

    por_mes = _agrupar(lambda f: (f.year, f.month),
                       lambda f: f"{MESES_CORTO[f.month]} {f.year}")
    por_semana = _agrupar(
        _lunes,
        lambda f: f"{_lunes(f).strftime('%d/%m')} – {(_lunes(f) + timedelta(days=6)).strftime('%d/%m')}",
        lambda f: f"Semana {_lunes(f).isocalendar()[1]} · {_lunes(f).year}")
    por_dia = []
    for dd in dias:
        x = dict(dd)
        x['cap_txt'] = hm(dd['cap'])
        x['att_txt'] = hm(dd['att_tot'])
        x['libre_txt'] = hm(dd['libre'])
        x['extra_txt'] = hm(dd['extra'])
        x['busy_txt'] = hm(dd['busy_in'])
        x['gaps_txt'] = ', '.join(f"{_hhmm(a)}–{_hhmm(b)}" for a, b in dd['gaps'])
        por_dia.append(x)

    # por día de la semana
    wd_agg = {i: {'dia': DIAS_ES[i], 'n': 0, 'n_atend': 0, 'att': 0, 'cap': 0, 'busy': 0,
                  'gen': 0.0, 'dias': 0} for i in range(7)}
    for dd in dias:
        w = wd_agg[dd['wd']]
        w['n'] += dd['n']
        w['n_atend'] += dd['n_atend']
        w['att'] += dd['att_tot']
        w['gen'] += dd['gen']
        if dd['transcurrido']:
            w['cap'] += dd['cap']
            w['busy'] += dd['busy_in']
        if dd['cap']:
            w['dias'] += 1
    por_dia_semana = []
    for i in range(7):
        w = wd_agg[i]
        w['ocup'] = _pct(w['busy'], w['cap'])
        w['libre_pct'] = round(100 - w['ocup'], 1) if w['cap'] else 0
        w['att_txt'] = hm(w['att'])
        w['gen'] = round(w['gen'], 2)
        por_dia_semana.append(w)

    # mapa de calor
    heat = []
    for i in range(7):
        celdas = []
        for h in range(HORA_HEAT_INI, HORA_HEAT_FIN):
            cap = heat_cap.get((i, h), 0)
            ocup = _pct(min(heat_busy.get((i, h), 0), cap), cap) if cap else None
            celdas.append({'h': h, 'ocup': ocup})
        if any(c['ocup'] is not None for c in celdas):
            heat.append({'dia': DIAS_ES[i], 'dia_c': DIAS_CORTO[i], 'celdas': celdas})
    heat_horas = [f"{h:02d}h" for h in range(HORA_HEAT_INI, HORA_HEAT_FIN)]

    # franjas horarias con más tiempo libre
    franjas = defaultdict(lambda: [0.0, 0.0])
    for (wd, h), cap in heat_cap.items():
        franjas[h][0] += cap
        franjas[h][1] += min(heat_busy.get((wd, h), 0), cap)
    franja_list = [{'h': f"{h:02d}:00 – {h + 1:02d}:00", 'cap': c, 'busy': b,
                    'ocup': _pct(b, c), 'libre': round(c - b)}
                   for h, (c, b) in sorted(franjas.items()) if c > 0]
    franjas_libres = sorted(franja_list, key=lambda x: x['ocup'])[:3]
    franjas_llenas = sorted(franja_list, key=lambda x: -x['ocup'])[:3]

    # ── 6. Estadísticas de sesiones (vista filtrada) ────────────────
    def _cnt(est):
        return sum(1 for r in filas if r['estado'] == est)

    realizadas, retrasos, faltas = _cnt('realizada'), _cnt('realizada_retraso'), _cnt('falta')
    permisos, canceladas = _cnt('permiso'), _cnt('cancelada')
    reprog, programadas = _cnt('reprogramada'), _cnt('programada')
    atendidas = realizadas + retrasos
    base_asist = atendidas + faltas + permisos

    min_pacientes = sum(r['dur'] for r in filas if r['estado'] in ATENDIDAS)       # horas-paciente
    min_reloj = sum(dd['att_tot'] for dd in dias)                                  # horas de reloj
    min_faltas = sum(r['dur'] for r in filas if r['estado'] == 'falta')
    min_prog = sum(r['dur'] for r in filas if r['estado'] == 'programada')

    gen_ind = sum(r['generado'] for r in filas if r['tipo'] == 'individual')
    gen_proy = sum(r['generado'] for r in filas if r['tipo'] == 'proyecto')
    gen_mens = sum(r['generado'] for r in filas if r['tipo'] == 'mensualidad')
    gen_proy_solo = sum(r['generado'] for r in filas if r['tipo'] == 'proyecto' and r['modalidad'] == 'Solo')
    gen_proy_grupal = gen_proy - gen_proy_solo
    gen_mens_solo = sum(r['generado'] for r in filas if r['tipo'] == 'mensualidad' and r['modalidad'] == 'Solo')
    gen_mens_grupal = gen_mens - gen_mens_solo
    gen_total = gen_ind + gen_proy + gen_mens
    por_generar = sum(r['por_generar'] for r in filas)

    ext_prof = sum(r['comision_prof'] or 0 for r in filas)
    ext_centro = sum(r['comision_centro'] or 0 for r in filas)
    tiene_externos = any(r['comision_prof'] is not None for r in filas)

    cap_el = sum(dd['cap'] for dd in dias if dd['transcurrido'])
    busy_el = sum(dd['busy_in'] for dd in dias if dd['transcurrido'])
    cap_fut = sum(dd['cap'] for dd in dias if not dd['transcurrido'])
    busy_fut = sum(dd['busy_in'] for dd in dias if not dd['transcurrido'])
    cap_tot = cap_el + cap_fut
    att_el = sum(dd['att_in'] for dd in dias if dd['transcurrido'])
    c = {k: sum(dd[k] for dd in dias if dd['transcurrido'])
         for k in ('c_falta', 'c_permiso', 'c_cancel', 'c_reprog', 'c_libre')}
    c_prog_pas = sum(dd['c_prog'] for dd in dias if dd['transcurrido'])   # programadas sin registrar
    perdidas_inasist = c['c_falta'] + c['c_permiso'] + c['c_cancel'] + c['c_reprog']
    extra_tot = sum(dd['extra'] for dd in dias)
    ocup_el = _pct(busy_el, cap_el)

    horas_reloj = min_reloj / 60.0
    kpis = {
        'total': len(filas),
        'realizadas': realizadas, 'retrasos': retrasos, 'faltas': faltas,
        'permisos': permisos, 'canceladas': canceladas, 'reprogramadas': reprog,
        'programadas': programadas, 'atendidas': atendidas,
        'pacientes': len({r['paciente_id'] for r in filas if r['estado'] in ATENDIDAS}),
        'pacientes_total': len({r['paciente_id'] for r in filas}),
        'tasa_asistencia': _pct(atendidas, base_asist),
        'tasa_faltas': _pct(faltas, base_asist),
        'tasa_puntualidad': _pct(realizadas, atendidas),
        'tasa_cancel': _pct(canceladas + reprog, len(filas) - programadas) if (len(filas) - programadas) else 0.0,
        'min_reloj': min_reloj, 'horas_reloj_txt': hm(min_reloj),
        'min_pacientes': min_pacientes, 'horas_pac_txt': hm(min_pacientes),
        'min_faltas': min_faltas, 'horas_faltas_txt': hm(min_faltas),
        'min_prog': min_prog, 'horas_prog_txt': hm(min_prog),
        'horas_reloj': round(horas_reloj, 1),
        'cap_total': cap_tot, 'cap_total_txt': hm(cap_tot),
        'cap_el': cap_el, 'cap_el_txt': hm(cap_el),
        'busy_el': busy_el, 'busy_el_txt': hm(busy_el),
        'libre_el': max(cap_el - busy_el, 0), 'libre_el_txt': hm(max(cap_el - busy_el, 0)),
        'cap_fut': cap_fut, 'cap_fut_txt': hm(cap_fut),
        'busy_fut': busy_fut, 'busy_fut_txt': hm(busy_fut),
        'libre_fut': max(cap_fut - busy_fut, 0), 'libre_fut_txt': hm(max(cap_fut - busy_fut, 0)),
        'extra': extra_tot, 'extra_txt': hm(extra_tot),
        'ocup_el': ocup_el,
        # ── horas que debió trabajar y quedó libre, según la causa ──
        'ocup_efect': _pct(att_el, cap_el),
        'h_falta': c['c_falta'], 'h_falta_txt': hm(c['c_falta']),
        'h_permiso': c['c_permiso'], 'h_permiso_txt': hm(c['c_permiso']),
        'h_cancel': c['c_cancel'], 'h_cancel_txt': hm(c['c_cancel']),
        'h_reprog': c['c_reprog'], 'h_reprog_txt': hm(c['c_reprog']),
        'h_sinag': c['c_libre'], 'h_sinag_txt': hm(c['c_libre']),
        'h_prog_pas': c_prog_pas, 'h_prog_pas_txt': hm(c_prog_pas),
        'h_perdidas': perdidas_inasist, 'h_perdidas_txt': hm(perdidas_inasist),
        'pct_perdidas': _pct(perdidas_inasist, cap_el),
        'pct_sinag': _pct(c['c_libre'], cap_el),
        'ocup_total': _pct(busy_el + busy_fut, cap_tot),
        'libre_pct_el': round(100 - ocup_el, 1) if cap_el else 0.0,
        'dias_con_horario': sum(1 for dd in dias if dd['cap']),
        'dias_con_sesiones': sum(1 for dd in dias if dd['n']),
        'gen_total': round(gen_total, 2), 'gen_ind': round(gen_ind, 2),
        'gen_proy': round(gen_proy, 2), 'gen_mens': round(gen_mens, 2),
        'gen_proy_solo': round(gen_proy_solo, 2), 'gen_proy_grupal': round(gen_proy_grupal, 2),
        'gen_mens_solo': round(gen_mens_solo, 2), 'gen_mens_grupal': round(gen_mens_grupal, 2),
        'pct_ind': _pct(gen_ind, gen_total), 'pct_proy': _pct(gen_proy, gen_total),
        'pct_mens': _pct(gen_mens, gen_total),
        'por_generar': round(por_generar, 2),
        'ingreso_hora': round(gen_total / horas_reloj, 2) if horas_reloj else 0.0,
        'ingreso_sesion': round(gen_total / atendidas, 2) if atendidas else 0.0,
        'sesiones_por_dia': round(atendidas / max(sum(1 for dd in dias if dd['n_atend']), 1), 1),
        'ext_prof': round(ext_prof, 2), 'ext_centro': round(ext_centro, 2),
        'tiene_externos': tiene_externos,
        'n_dias': n_dias,
    }
    # carga de trabajo
    if cap_el == 0:
        carga = ('sin_datos', 'Sin horario transcurrido en el período', '#64748b')
    elif ocup_el >= 85:
        carga = ('alta', 'Carga ALTA — agenda casi completa', '#dc2626')
    elif ocup_el >= 60:
        carga = ('buena', 'Carga BUENA — agenda bien aprovechada', '#16a34a')
    elif ocup_el >= 35:
        carga = ('media', 'Carga MEDIA — hay margen para más pacientes', '#d97706')
    else:
        carga = ('baja', 'Carga BAJA — mucho tiempo libre', '#7c3aed')
    kpis['carga'], kpis['carga_txt'], kpis['carga_color'] = carga

    # Ingreso potencial no aprovechado: horas libres que NO generaron dinero
    # (la falta sin aviso sí se cobra, por eso no entra) × ingreso por hora real.
    h_no_pagadas = c['c_permiso'] + c['c_cancel'] + c['c_reprog'] + c['c_libre']
    kpis['h_no_pagadas_txt'] = hm(h_no_pagadas)
    kpis['potencial_no_aprovechado'] = round(h_no_pagadas / 60.0 * kpis['ingreso_hora'], 2)

    # Rentabilidad (el sistema no guarda sueldos internos → costo manual opcional)
    costo_mensual = _f(costo_mensual)
    neto_centro = gen_total - ext_prof if tiene_externos else gen_total
    costo_periodo = costo_mensual * n_dias / 30.4 if costo_mensual else 0.0
    kpis['costo_mensual'] = costo_mensual
    kpis['costo_periodo'] = round(costo_periodo, 2)
    kpis['neto_centro'] = round(neto_centro, 2)
    kpis['margen'] = round(neto_centro - costo_periodo, 2)
    kpis['cobertura'] = round(neto_centro / costo_periodo, 2) if costo_periodo else 0.0
    kpis['rentable'] = (neto_centro >= costo_periodo) if costo_periodo else None

    # ── 7. Por paciente ─────────────────────────────────────────────
    pac_map = {}
    for r in filas:
        p = pac_map.setdefault(r['paciente_id'], {
            'id': r['paciente_id'], 'nombre': r['paciente'], 'n': 0, 'atend': 0, 'faltas': 0,
            'permisos': 0, 'canceladas': 0, 'prog': 0, 'min': 0, 'gen': 0.0,
            'gen_ind': 0.0, 'gen_proy': 0.0, 'gen_mens': 0.0,
            'servicios': set(), 'proyectos': set(), 'mensualidades': set(), 'min_falta': 0,
            'primera': r['fecha'], 'ultima': r['fecha'],
        })
        p['n'] += 1
        p['atend'] += r['estado'] in ATENDIDAS
        p['faltas'] += r['estado'] == 'falta'
        if r['estado'] == 'falta':
            p['min_falta'] += r['dur']
        p['permisos'] += r['estado'] == 'permiso'
        p['canceladas'] += r['estado'] in ('cancelada', 'reprogramada')
        p['prog'] += r['estado'] == 'programada'
        if r['estado'] in ATENDIDAS:
            p['min'] += r['dur']
        p['gen'] += r['generado']
        p['gen_' + {'individual': 'ind', 'proyecto': 'proy', 'mensualidad': 'mens'}[r['tipo']]] += r['generado']
        p['servicios'].add(r['servicio'])
        if r['tipo'] == 'proyecto':
            p['proyectos'].add(r['origen'])
        if r['tipo'] == 'mensualidad':
            p['mensualidades'].add(r['origen'])
        p['primera'] = min(p['primera'], r['fecha'])
        p['ultima'] = max(p['ultima'], r['fecha'])

    from pacientes.models import Paciente
    pac_obj = {p.id: p for p in Paciente.objects.filter(id__in=pac_map.keys())}
    pacientes = []
    for pid, p in pac_map.items():
        ob = pac_obj.get(pid)
        base = p['atend'] + p['faltas'] + p['permisos']
        foto = None
        if ob is not None:
            try:
                foto = ob.get_foto_thumbnail()
            except Exception:
                foto = None
        p.update({
            'servicios': sorted(p['servicios']),
            'n_proy': len(p['proyectos']), 'n_mens': len(p['mensualidades']),
            'horas_txt': hm(p['min']), 'falta_txt': hm(p['min_falta']),
            'tasa': _pct(p['atend'], base),
            'gen': round(p['gen'], 2), 'gen_ind': round(p['gen_ind'], 2),
            'gen_proy': round(p['gen_proy'], 2), 'gen_mens': round(p['gen_mens'], 2),
            'inactivo': bool(ob and ob.estado == 'inactivo'),
            'edad': getattr(ob, 'edad', '') if ob else '',
            'diagnostico': (ob.diagnostico[:90] if ob and ob.diagnostico else ''),
            'foto': foto,
            'iniciales': (p['nombre'][:1] + (p['nombre'].split(' ')[-1][:1] if ' ' in p['nombre'] else '')).upper(),
        })
        pacientes.append(p)
    pacientes.sort(key=lambda x: (-x['atend'], x['nombre']))

    # ── 8. Por servicio / tipo / sucursal ───────────────────────────
    def _agrup(clave, extra=None):
        m = {}
        for r in filas:
            k = r[clave]
            g = m.setdefault(k, {'nombre': k, 'color': r['color'], 'n': 0, 'atend': 0, 'faltas': 0,
                                 'min': 0, 'gen': 0.0, 'pacs': set(),
                                 'ind': 0, 'proy': 0, 'mens': 0})
            g['n'] += 1
            g['atend'] += r['estado'] in ATENDIDAS
            g['faltas'] += r['estado'] == 'falta'
            if r['estado'] in ATENDIDAS:
                g['min'] += r['dur']
                g['pacs'].add(r['paciente_id'])
            g['gen'] += r['generado']
            g[{'individual': 'ind', 'proyecto': 'proy', 'mensualidad': 'mens'}[r['tipo']]] += 1
        out = []
        for g in m.values():
            g['pacs'] = len(g['pacs'])
            g['horas_txt'] = hm(g['min'])
            g['gen'] = round(g['gen'], 2)
            g['pct_gen'] = _pct(g['gen'], gen_total)
            out.append(g)
        return sorted(out, key=lambda x: -x['gen'] if gen_total else -x['n'])

    por_servicio = _agrup('servicio')
    por_sucursal = _agrup('sucursal')

    TIPO_TXT = {'individual': 'Sesiones individuales', 'proyecto': 'Proyectos / Evaluaciones',
                'mensualidad': 'Mensualidades'}
    por_tipo = []
    for t in ('individual', 'proyecto', 'mensualidad'):
        rs = [r for r in filas if r['tipo'] == t]
        at = [r for r in rs if r['estado'] in ATENDIDAS]
        g = sum(r['generado'] for r in rs)
        por_tipo.append({
            'clave': t, 'nombre': TIPO_TXT[t], 'n': len(rs), 'atend': len(at),
            'faltas': sum(1 for r in rs if r['estado'] == 'falta'),
            'prog': sum(1 for r in rs if r['estado'] == 'programada'),
            'min': sum(r['dur'] for r in at), 'horas_txt': hm(sum(r['dur'] for r in at)),
            'gen': round(g, 2), 'pct_gen': _pct(g, gen_total),
            'pacs': len({r['paciente_id'] for r in at}),
        })

    # ── 9. Proyectos del profesional ────────────────────────────────
    def _pm_comun(k, gid, costo, rs):
        """Métricas de participación compartidas por proyectos y mensualidades."""
        wt, wm = w_tot[k][gid], w_mio[k][gid]
        if wt > 0:
            share = wm / wt
        else:
            share = (n_mio[k][gid] / n_tot[k][gid]) if n_tot[k][gid] else 0.0
        ref_mio = wm                                   # lo que valdrían sus sesiones a precio individual
        atribuido = costo * share                      # su parte del costo fijo
        return {
            'share': round(share * 100, 1),
            'ref_mio': round(ref_mio, 2),
            'ref_total': round(wt, 2),
            # factor < 1 → el paquete se cobró con descuento vs. sesiones sueltas
            'factor': round(costo / wt, 3) if wt else 0.0,
            'atribuido': round(atribuido, 2),
            'sesiones_mias': n_mio[k][gid], 'sesiones_total': n_tot[k][gid],
            'sesiones_consumidas_mias': n_cons_mio[k][gid],
            'gen_periodo': round(sum(r['generado'] for r in rs), 2),
            'por_generar': round(sum(r['por_generar'] for r in rs), 2),
        }

    proyectos = []
    proy_rows = defaultdict(list)
    for r, s in zip(filas, vista):
        if s.proyecto_id:
            proy_rows[s.proyecto_id].append((r, s))
    for pid, items in proy_rows.items():
        p = items[0][1].proyecto
        parts = participantes_p[pid]
        otros = sorted(nombres_prof.get(i, '—') for i in parts if i != prof.id)
        rs = [x[0] for x in items]
        valor_total = _f(p.costo_total)
        try:
            cobrado, saldo = _f(p.total_pagado), _f(p.saldo_pendiente)
        except Exception:
            cobrado, saldo = 0.0, 0.0
        d = _pm_comun('p', pid, valor_total, rs)
        d.update({
            'id': pid, 'codigo': p.codigo, 'nombre': p.nombre, 'tipo': p.get_tipo_display(),
            'paciente': f"{p.paciente.nombre} {p.paciente.apellido}",
            'estado': p.get_estado_display(), 'estado_clave': p.estado,
            'responsable': p.profesional_responsable_id == prof.id,
            'responsable_nombre': nombres_prof.get(p.profesional_responsable_id, '—'),
            'modalidad': 'Solo' if not otros else 'Grupal',
            'companeros': otros,
            'valor': valor_total, 'cobrado': cobrado, 'saldo': saldo,
            'sesiones_periodo': len(rs),
            'atend_periodo': sum(1 for r in rs if r['estado'] in ATENDIDAS),
            'faltas': sum(1 for r in rs if r['estado'] == 'falta'),
            'horas_txt': hm(sum(r['dur'] for r in rs if r['estado'] in ATENDIDAS)),
            'inicio': p.fecha_inicio, 'fin': p.fecha_fin_real or p.fecha_fin_estimada,
        })
        proyectos.append(d)
    proyectos.sort(key=lambda x: -x['gen_periodo'])

    # ── 10. Mensualidades del profesional ───────────────────────────
    mensualidades = []
    mens_rows = defaultdict(list)
    for r, s in zip(filas, vista):
        if s.mensualidad_id:
            mens_rows[s.mensualidad_id].append((r, s))
    asign = defaultdict(list)
    for sp in (ServicioProfesionalMensualidad.objects
               .filter(mensualidad_id__in=mens_rows.keys(), profesional=prof)
               .select_related('servicio')):
        asign[sp.mensualidad_id].append(sp.servicio.nombre)
    for mid, items in mens_rows.items():
        m = items[0][1].mensualidad
        otros = sorted(nombres_prof.get(i, '—') for i in participantes_m[mid] if i != prof.id)
        rs = [x[0] for x in items]
        costo = _f(m.costo_mensual)
        try:
            cobrado, saldo = _f(m.total_pagado), _f(m.saldo_pendiente)
        except Exception:
            cobrado, saldo = 0.0, 0.0
        d = _pm_comun('m', mid, costo, rs)
        d.update({
            'id': mid, 'codigo': m.codigo, 'periodo': m.periodo_display,
            'paciente': f"{m.paciente.nombre} {m.paciente.apellido}",
            'estado': m.get_estado_display(), 'estado_clave': m.estado,
            'servicios': sorted(set(asign.get(mid, []) or {r['servicio'] for r in rs})),
            'modalidad': 'Solo' if not otros else 'Grupal', 'companeros': otros,
            'costo': costo, 'cobrado': cobrado, 'saldo': saldo,
            'sesiones_periodo': len(rs),
            'atend_periodo': sum(1 for r in rs if r['estado'] in ATENDIDAS),
            'faltas': sum(1 for r in rs if r['estado'] == 'falta'),
            'prog': sum(1 for r in rs if r['estado'] == 'programada'),
            'horas_txt': hm(sum(r['dur'] for r in rs if r['estado'] in ATENDIDAS)),
            'por_sesion': round(d['atribuido'] / d['sesiones_mias'], 2) if d['sesiones_mias'] else 0.0,
            'anio_mes': m.anio * 100 + m.mes,
        })
        mensualidades.append(d)
    mensualidades.sort(key=lambda x: (-x['anio_mes'], x['paciente']))

    # ── 11. Hallazgos automáticos para el dueño ─────────────────────
    hallazgos = []
    if cap_el:
        hallazgos.append({
            'tipo': 'info',
            'txt': f"Trabajó {hm(min_reloj)} efectivas de {hm(cap_el)} de horario transcurrido "
                   f"(ocupación {ocup_el}%). Tiempo libre: {hm(max(cap_el - busy_el, 0))}.",
        })
        if ocup_el < 35:
            hallazgos.append({'tipo': 'alerta',
                              'txt': 'La agenda está muy vacía: hay capacidad para sumar varios pacientes más.'})
        elif ocup_el >= 85:
            hallazgos.append({'tipo': 'ok',
                              'txt': 'Agenda prácticamente llena: considerar derivar nuevos pacientes a otro profesional.'})
        con_cap = [w for w in por_dia_semana if w['cap']]
        if con_cap:
            libre = min(con_cap, key=lambda w: w['ocup'])
            lleno = max(con_cap, key=lambda w: w['ocup'])
            if libre['dia'] != lleno['dia']:
                hallazgos.append({'tipo': 'info',
                                  'txt': f"Día más libre: {libre['dia']} ({libre['ocup']}% ocupado). "
                                         f"Día más cargado: {lleno['dia']} ({lleno['ocup']}%)."})
        if franjas_libres and franjas_libres[0]['ocup'] < 50:
            hallazgos.append({'tipo': 'info',
                              'txt': f"Franja con más tiempo libre: {franjas_libres[0]['h']} "
                                     f"({franjas_libres[0]['ocup']}% ocupada)."})
    if perdidas_inasist > 0:
        hallazgos.append({'tipo': 'alerta' if kpis['pct_perdidas'] >= 10 else 'info',
                          'txt': f"Horas que debió trabajar y quedó libre por inasistencia/cancelación: "
                                 f"{hm(perdidas_inasist)} ({kpis['pct_perdidas']}% de su horario) — "
                                 f"faltas sin aviso {hm(c['c_falta'])} (se cobran), "
                                 f"permisos {hm(c['c_permiso'])}, cancelaciones {hm(c['c_cancel'])}, "
                                 f"reprogramaciones {hm(c['c_reprog'])}."})
    if c['c_libre'] > 0 and cap_el:
        hallazgos.append({'tipo': 'alerta' if kpis['pct_sinag'] >= 30 else 'info',
                          'txt': f"Horario sin ningún paciente agendado: {hm(c['c_libre'])} "
                                 f"({kpis['pct_sinag']}% de su horario). Potencial no aprovechado "
                                 f"≈ Bs. {kpis['potencial_no_aprovechado']:,.2f}."})
    if extra_tot > 0:
        hallazgos.append({'tipo': 'info',
                          'txt': f"Atendió {hm(extra_tot)} fuera de su horario base (horas extra / flexibles)."})
    if kpis['tasa_faltas'] >= 15 and base_asist >= 5:
        hallazgos.append({'tipo': 'alerta',
                          'txt': f"{kpis['tasa_faltas']}% de las sesiones fueron falta sin aviso "
                                 f"({hm(min_faltas)} de agenda perdidas)."})
    if gen_total:
        hallazgos.append({'tipo': 'info',
                          'txt': f"Generó Bs. {gen_total:,.2f}: {kpis['pct_ind']}% sesiones individuales, "
                                 f"{kpis['pct_proy']}% proyectos y {kpis['pct_mens']}% mensualidades "
                                 f"(Bs. {kpis['ingreso_hora']:,.2f} por hora trabajada)."})
    crit = [p for p in pacientes if p['faltas'] >= 2]
    if crit:
        hallazgos.append({'tipo': 'alerta',
                          'txt': f"{len(crit)} paciente(s) con 2 o más faltas: "
                                 + ', '.join(p['nombre'] for p in crit[:4]) + ('…' if len(crit) > 4 else '')})
    if horario_info['fuente'] != 'asistencia':
        hallazgos.append({'tipo': 'nota',
                          'txt': 'El horario base no está configurado en Asistencia; se usó el predeterminado. '
                                 'Puedes ajustarlo en "Horario base" para cálculos exactos.'})

    for h_ in hallazgos:
        h_['txt'] = es_num(h_['txt'])

    # ── 12. Comparación con período anterior ────────────────────────
    comparacion = None
    if comparar:
        largo = (hasta - desde).days + 1
        prev_h = desde - timedelta(days=1)
        prev_d = prev_h - timedelta(days=largo - 1)
        try:
            prev = analizar(prof, prev_d, prev_h, sucursal_id, servicio_id, paciente_id, tipo,
                            estado, manual_cfg, forzar_manual, hoy, comparar=False,
                            costo_mensual=costo_mensual, completo=False)
            pk = prev['kpis']

            def _delta(a, b):
                return round(a - b, 1)
            comparacion = {
                'desde': prev_d, 'hasta': prev_h,
                'atendidas': (pk['atendidas'], kpis['atendidas'] - pk['atendidas']),
                'horas': (pk['horas_reloj_txt'], round(kpis['horas_reloj'] - pk['horas_reloj'], 1)),
                'ocup': (pk['ocup_el'], _delta(kpis['ocup_el'], pk['ocup_el'])),
                'gen': (pk['gen_total'], round(kpis['gen_total'] - pk['gen_total'], 2)),
                'pacientes': (pk['pacientes'], kpis['pacientes'] - pk['pacientes']),
            }
        except Exception:
            comparacion = None

    # ── 13. Datos para gráficos ─────────────────────────────────────
    graf = {
        'meses': {
            'labels': [g['label'] for g in por_mes],
            'atend': [g['n_atend'] for g in por_mes],
            'faltas': [g['n_falta'] for g in por_mes],
            'gen': [g['gen'] for g in por_mes],
            'horas': [round(g['att_tot'] / 60, 1) for g in por_mes],
            'cap': [round(g['cap'] / 60, 1) for g in por_mes],
            'ocup': [g['ocup_el'] for g in por_mes],
        },
        'semanas': {
            'labels': [g['label'] for g in por_semana],
            'atend': [g['n_atend'] for g in por_semana],
            'faltas': [g['n_falta'] for g in por_semana],
            'gen': [g['gen'] for g in por_semana],
            'horas': [round(g['att_tot'] / 60, 1) for g in por_semana],
            'cap': [round(g['cap'] / 60, 1) for g in por_semana],
            'ocup': [g['ocup_el'] for g in por_semana],
        },
        'dias': {
            'labels': [x['fecha'].strftime('%d/%m') for x in por_dia],
            'atend': [x['n_atend'] for x in por_dia],
            'faltas': [x['n_falta'] for x in por_dia],
            'gen': [x['gen'] for x in por_dia],
            'horas': [round(x['att_tot'] / 60, 1) for x in por_dia],
            'cap': [round(x['cap'] / 60, 1) for x in por_dia],
            'ocup': [x['ocup'] if x['transcurrido'] else None for x in por_dia],
        },
        'tipos': {'labels': [t['nombre'] for t in por_tipo], 'gen': [t['gen'] for t in por_tipo]},
        'semana_dia': {
            'labels': [w['dia'] for w in por_dia_semana],
            'ocup': [w['ocup'] for w in por_dia_semana],
            'atend': [w['n_atend'] for w in por_dia_semana],
        },
    }

    huecos_futuros.sort(key=lambda x: (x['fecha'], x['ini']))
    huecos_pasados.sort(key=lambda x: (x['fecha'], x['ini']))

    # Para un profesional inactivo la disponibilidad futura no tiene sentido: no se calcula
    proximos = proximos_huecos(prof, sucursal_id, manual_cfg, forzar_manual, hoy) if (completo and prof.activo) else None

    resultado = {
        'desde': desde, 'hasta': hasta, 'n_dias': n_dias, 'nota_rango': nota_rango,
        'hoy': hoy,
        'kpis': kpis, 'filas': filas, 'hay_filtros_contenido': hay_filtros_contenido,
        'pacientes': pacientes, 'n_ninos_inactivos': sum(1 for p_ in pacientes if p_.get('inactivo')),
        'por_servicio': por_servicio, 'por_sucursal': por_sucursal,
        'por_tipo': por_tipo, 'proyectos': proyectos, 'mensualidades': mensualidades,
        'por_dia': por_dia, 'por_semana': por_semana, 'por_mes': por_mes,
        'por_dia_semana': por_dia_semana, 'heat': heat, 'heat_horas': heat_horas,
        'franjas_libres': franjas_libres, 'franjas_llenas': franjas_llenas,
        'huecos_futuros': huecos_futuros, 'huecos_pasados': huecos_pasados, 'proximos': proximos,
        'horario': horario_info, 'hallazgos': hallazgos, 'comparacion': comparacion,
        'graf': graf,
    }

    if completo:
        from .reporte_profesional_extra import enriquecer
        enriquecer(prof, resultado, {
            'sucursal_id': sucursal_id, 'manual_cfg': manual_cfg,
        })
    return resultado
