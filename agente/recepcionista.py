"""
agente/recepcionista.py
Agente Recepcionista — personal de recepción del Centro Infantil Misael.

Acceso:
  - Sesiones, agenda, estado de citas — con soporte histórico completo
  - Pagos, deudas, saldos, facturación
  - Información general de pacientes
  - Mensualidades y proyectos
  Por defecto muestra SU sucursal, puede pedir otras.

SIN acceso a:
  - Evolución clínica, notas de sesión
  - Diagnósticos, evaluaciones médicas

BUGS CORREGIDOS vs versión anterior:
  - Pago.fecha → Pago.fecha_pago  (campo real del modelo)
  - Pago filtrado por sucursal a través de sesion__sucursal (no FK directo)
  - anulado=False en todas las queries de Pago
  - from facturacion.models import Mensualidad → está en agenda.models
  - estados Mensualidad: 'activa', 'pausada' (no 'pendiente'/'parcial')
  - campo monto_total → costo_mensual
  - fecha_vencimiento → no existe; Mensualidad usa mes + anio
  - Soporte de fechas históricas con extraer_rango_fechas()

Modelos: Haiku (simple) / Sonnet (complejo)
"""

import re
import logging
import calendar
from datetime import date, timedelta
from agente.agente_base import AgenteBase

log = logging.getLogger('agente')

MODELO_RAPIDO   = 'claude-haiku-4-5-20251001'
MODELO_COMPLETO = 'claude-sonnet-4-6'

PALABRAS_SONNET = (
    'informe', 'reporte', 'resumen', 'detalle', 'deuda', 'deudas',
    'mensualidad', 'mensualidades', 'proyecto', 'proyectos',
    'facturación', 'facturacion', 'historial de pagos', 'todas las',
    'comparar', 'análisis', 'analisis', 'cuánto', 'cuanto',
    'pendiente', 'pendientes', 'balance', 'histórico', 'historico',
    'anterior', 'pasado', 'enero', 'febrero', 'marzo', 'abril', 'mayo',
    'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre',
)

PROMPT_FALLBACK = """Eres el asistente de recepción del Centro Infantil Misael.

Asistes a {nombre} (recepcionista) en sus tareas operativas y administrativas:
- Agenda del día y períodos históricos
- Información de pacientes: datos de contacto, tutor, estado
- Facturación: pagos realizados, deudas, saldos, historial
- Mensualidades y proyectos pendientes

TONO: Eficiente, organizado y profesional.

IMPORTANTE — SUCURSALES:
- Tu sucursal asignada: {sucursal_propia}
- Por defecto SIEMPRE muestra datos de tu sucursal
- Si pides otra sucursal o "todas", amplía la vista

LÍMITES ESTRICTOS:
- NO tienes acceso a evolución clínica, diagnósticos ni informes de terapeutas
- Si preguntan por historial clínico: "Esa información es clínica y la maneja el profesional a cargo."

=== DATOS ACTUALIZADOS ===
{contexto}
"""

_MESES_ES = {
    'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4,
    'mayo': 5, 'junio': 6, 'julio': 7, 'agosto': 8,
    'septiembre': 9, 'setiembre': 9, 'octubre': 10,
    'noviembre': 11, 'diciembre': 12,
}


def extraer_rango_fechas(mensaje: str) -> tuple:
    """Detecta el rango de fechas del mensaje en lenguaje natural."""
    hoy = date.today()
    msg = mensaje.lower().strip()

    if re.search(r'\bhoy\b', msg):
        return hoy, hoy
    if re.search(r'\bayer\b', msg):
        ayer = hoy - timedelta(days=1)
        return ayer, ayer
    if re.search(r'\besta semana\b', msg):
        lunes = hoy - timedelta(days=hoy.weekday())
        return lunes, hoy
    if re.search(r'\bsemana pasada\b|\bsemana anterior\b', msg):
        lunes_esta = hoy - timedelta(days=hoy.weekday())
        lunes_ant  = lunes_esta - timedelta(days=7)
        return lunes_ant, lunes_ant + timedelta(days=6)
    if re.search(r'\beste mes\b', msg):
        return date(hoy.year, hoy.month, 1), hoy
    if re.search(r'\bmes pasado\b|\bmes anterior\b', msg):
        primer = date(hoy.year, hoy.month, 1)
        ultimo = primer - timedelta(days=1)
        return date(ultimo.year, ultimo.month, 1), ultimo
    if re.search(r'\beste año\b', msg):
        return date(hoy.year, 1, 1), hoy
    if re.search(r'\baño pasado\b|\baño anterior\b', msg):
        return date(hoy.year - 1, 1, 1), date(hoy.year - 1, 12, 31)

    m = re.search(r'últimos?\s+(\d+)\s+d[ií]as?', msg)
    if m:
        return hoy - timedelta(days=int(m.group(1))), hoy

    _mp = '|'.join(_MESES_ES.keys())
    m = re.search(rf'\b({_mp})\b(?:\s+(?:de\s+)?(\d{{4}}))?', msg)
    if m:
        mes  = _MESES_ES[m.group(1)]
        anio = int(m.group(2)) if m.group(2) else hoy.year
        ultimo = calendar.monthrange(anio, mes)[1]
        return date(anio, mes, 1), date(anio, mes, ultimo)

    m = re.search(r'\b(20\d{2})\b', msg)
    if m:
        anio = int(m.group(1))
        fin  = date(anio, 12, 31) if anio < hoy.year else hoy
        return date(anio, 1, 1), fin

    return hoy - timedelta(days=30), hoy


def _periodo_str(desde: date, hasta: date) -> str:
    if desde == hasta:
        return desde.strftime('%d/%m/%Y')
    if (desde.day == 1 and hasta.day == calendar.monthrange(hasta.year, hasta.month)[1]
            and desde.month == hasta.month and desde.year == hasta.year):
        return f"{calendar.month_name[desde.month].capitalize()} {desde.year}"
    return f"{desde.strftime('%d/%m/%Y')} al {hasta.strftime('%d/%m/%Y')}"


def _get_sucursal_ids(staff) -> list:
    if not staff or not staff.sucursales:
        return []
    try:
        return list(staff.sucursales.values_list('id', flat=True))
    except Exception:
        return []


def _pide_otra_sucursal(mensaje: str) -> bool:
    msg = mensaje.lower()
    return any(p in msg for p in (
        'otra sucursal', 'todas las sucursales', 'todas sucursales',
        'ambas sedes', 'las dos sedes', 'sede japón', 'sede japon',
        'sede camacho', 'todas las sedes', 'otra sede', 'en total', 'todo el centro',
    ))


def _construir_contexto(staff, mensaje: str) -> str:
    from django.db.models import Sum, Count, Q
    msg    = mensaje.lower()
    partes = []
    hoy    = date.today()

    fecha_desde, fecha_hasta = extraer_rango_fechas(mensaje)
    periodo = _periodo_str(fecha_desde, fecha_hasta)

    suc_ids         = _get_sucursal_ids(staff)
    filtrar_sucursal = bool(suc_ids) and not _pide_otra_sucursal(mensaje)
    scope           = 'su sucursal' if filtrar_sucursal else 'todas las sucursales'

    partes.append(f"Fecha: {hoy:%d/%m/%Y} | Vista: {scope} | Período: {periodo}")

    # ── Agenda de HOY (siempre) ───────────────────────────────────────────────
    try:
        from agenda.models import Sesion
        qs = Sesion.objects.filter(fecha=hoy)
        if filtrar_sucursal:
            qs = qs.filter(sucursal__id__in=suc_ids)

        por_estado = {r['estado']: r['total'] for r in qs.values('estado').annotate(total=Count('id'))}
        partes.append(
            f"=== AGENDA DE HOY ({scope}) ===\n"
            f"Programadas: {por_estado.get('programada', 0)} | "
            f"Realizadas: {por_estado.get('realizada', 0) + por_estado.get('realizada_retraso', 0)} | "
            f"Permisos: {por_estado.get('permiso', 0)} | "
            f"Faltas: {por_estado.get('falta', 0)} | "
            f"Canceladas: {por_estado.get('cancelada', 0)}"
        )

        # Detalle de sesiones de hoy si lo piden
        if any(p in msg for p in ('quién', 'quien', 'lista', 'detalle', 'sesiones de hoy', 'agenda')):
            sesiones_det = (
                qs.filter(estado='programada')
                .select_related('paciente', 'profesional', 'servicio', 'sucursal')
                .order_by('hora_inicio')
            )
            if sesiones_det.exists():
                lineas = []
                for s in sesiones_det:
                    hora = s.hora_inicio.strftime('%H:%M') if s.hora_inicio else '—'
                    pac  = f'{s.paciente.nombre} {s.paciente.apellido}' if s.paciente else '—'
                    prof = f'{s.profesional.nombre} {s.profesional.apellido}' if s.profesional else '—'
                    suc  = s.sucursal.nombre if s.sucursal else '—'
                    lineas.append(f"  {hora} — {pac} con {prof} ({suc})")
                partes.append("=== DETALLE SESIONES HOY ===\n" + '\n'.join(lineas))
    except Exception as e:
        log.error(f'[Recepcionista] Error agenda hoy: {e}')

    # ── Sesiones del período histórico consultado ─────────────────────────────
    es_hoy_exacto = (fecha_desde == hoy and fecha_hasta == hoy)
    if not es_hoy_exacto and any(p in msg for p in (
        'sesion', 'sesiones', 'semana', 'mes', 'anterior', 'pasado',
        'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
        'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre',
    )):
        try:
            from agenda.models import Sesion
            qs_p = Sesion.objects.filter(fecha__gte=fecha_desde, fecha__lte=fecha_hasta)
            if filtrar_sucursal:
                qs_p = qs_p.filter(sucursal__id__in=suc_ids)
            res_p = {r['estado']: r['total'] for r in qs_p.values('estado').annotate(total=Count('id'))}
            partes.append(
                f"=== SESIONES: {periodo} ({scope}) ===\n"
                f"Total: {qs_p.count()} | "
                f"Realizadas: {res_p.get('realizada', 0) + res_p.get('realizada_retraso', 0)} | "
                f"Programadas: {res_p.get('programada', 0)} | "
                f"Permisos: {res_p.get('permiso', 0)} | "
                f"Faltas: {res_p.get('falta', 0)} | "
                f"Canceladas: {res_p.get('cancelada', 0)}"
            )
        except Exception as e:
            log.error(f'[Recepcionista] Error sesiones periodo: {e}')

    # ── Pagos / deudas / facturación ──────────────────────────────────────────
    if any(p in msg for p in ('pago', 'pagos', 'deuda', 'deudas', 'saldo', 'factur',
                               'debe', 'pendiente', 'cobro', 'balance', 'cuenta',
                               'cuánto', 'cuanto', 'ingreso', 'ingresos')):
        try:
            from facturacion.models import Pago, CuentaCorriente

            # Ingresos de HOY
            qs_hoy = Pago.objects.filter(fecha_pago=hoy, anulado=False)
            if filtrar_sucursal:
                qs_hoy = qs_hoy.filter(
                    Q(sesion__sucursal__id__in=suc_ids) |
                    Q(proyecto__sucursal__id__in=suc_ids) |
                    Q(mensualidad__sucursal__id__in=suc_ids)
                )
            total_hoy = float(qs_hoy.aggregate(t=Sum('monto'))['t'] or 0)

            # Ingresos del período consultado
            qs_per = Pago.objects.filter(
                fecha_pago__gte=fecha_desde,
                fecha_pago__lte=fecha_hasta,
                anulado=False,
            )
            if filtrar_sucursal:
                qs_per = qs_per.filter(
                    Q(sesion__sucursal__id__in=suc_ids) |
                    Q(proyecto__sucursal__id__in=suc_ids) |
                    Q(mensualidad__sucursal__id__in=suc_ids)
                )
            total_per = float(qs_per.aggregate(t=Sum('monto'))['t'] or 0)

            partes.append(
                f"=== INGRESOS ({scope}) ===\n"
                f"Hoy: Bs. {total_hoy:,.2f}\n"
                f"Período ({periodo}): Bs. {total_per:,.2f} en {qs_per.count()} pagos"
            )

            # Detalle de pagos del período si lo piden
            if any(p in msg for p in ('detalle', 'lista', 'quién registró', 'desglose',
                                       'recibo', 'recibos', 'cada pago', 'quién cobró')):
                pagos_det = (
                    qs_per.select_related('paciente', 'metodo_pago', 'registrado_por')
                    .order_by('-fecha_pago')[:30]
                )
                lineas = [
                    f"  [{p.fecha_pago:%d/%m/%Y}] {p.numero_recibo} | "
                    f"{p.paciente.nombre} {p.paciente.apellido if p.paciente else '—'} | "
                    f"Bs.{float(p.monto):,.0f} | {p.metodo_pago.nombre if p.metodo_pago else '—'} | "
                    f"Registró: {p.registrado_por.get_full_name() or p.registrado_por.username if p.registrado_por else '—'}"
                    for p in pagos_det
                ]
                if lineas:
                    partes.append("=== DETALLE PAGOS ===\n" + '\n'.join(lineas))

            # Deudas
            deudas = (
                CuentaCorriente.objects
                .filter(saldo_actual__lt=0)
                .select_related('paciente')
                .order_by('saldo_actual')[:10]
            )
            if deudas.exists():
                lineas = [
                    f"  {c.paciente.nombre} {c.paciente.apellido}: Bs. {abs(float(c.saldo_actual)):,.2f}"
                    for c in deudas if c.paciente
                ]
                partes.append("=== PACIENTES CON DEUDA ===\n" + '\n'.join(lineas))
        except Exception as e:
            log.error(f'[Recepcionista] Error pagos/deudas: {e}')

    # ── Mensualidades ─────────────────────────────────────────────────────────
    # CORRECCIÓN: Mensualidad está en agenda.models, NO en facturacion.models
    # Estados válidos: 'activa', 'pausada', 'completada', 'cancelada'
    # Campo: costo_mensual (no monto_total); período: mes + anio (no fecha_vencimiento)
    if any(p in msg for p in ('mensualidad', 'mensualidades', 'cuota', 'cuotas')):
        try:
            from agenda.models import Mensualidad
            mens = (
                Mensualidad.objects
                .filter(estado__in=['activa', 'pausada'])
                .select_related('paciente', 'sucursal')
                .order_by('-anio', '-mes')[:12]
            )
            if mens.exists():
                lineas = []
                for m in mens:
                    try:
                        pendiente = float(m.saldo_pendiente)
                    except Exception:
                        pendiente = float(m.costo_mensual)
                    pac = f'{m.paciente.nombre} {m.paciente.apellido}' if m.paciente else '—'
                    suc = m.sucursal.nombre if m.sucursal else '—'
                    lineas.append(
                        f"  {pac} — {m.mes:02d}/{m.anio} — "
                        f"Bs. {float(m.costo_mensual):,.2f} "
                        f"(pendiente: Bs. {pendiente:,.2f}) [{m.estado}] {suc}"
                    )
                partes.append("=== MENSUALIDADES ACTIVAS/PAUSADAS ===\n" + '\n'.join(lineas))
        except Exception as e:
            log.error(f'[Recepcionista] Error mensualidades: {e}')

    # ── Pacientes ─────────────────────────────────────────────────────────────
    if any(p in msg for p in ('paciente', 'tutor', 'contacto', 'teléfono', 'telefono', 'buscar')):
        partes.append(
            "=== BÚSQUEDA DE PACIENTES ===\n"
            "Indica el nombre o teléfono del paciente para que pueda darte su información completa."
        )

    return '\n\n'.join(partes) if partes else f"Fecha: {hoy:%d/%m/%Y}. Listo para ayudarte."


def _elegir_modelo(mensaje: str) -> tuple:
    msg = mensaje.lower()
    if any(p in msg for p in PALABRAS_SONNET) or len(mensaje.split()) > 20:
        return MODELO_COMPLETO, 'Sonnet'
    return MODELO_RAPIDO, 'Haiku'


class AgenteRecepcionista(AgenteBase):
    TIPO = 'recepcionista'

    def responder(self, telefono: str, mensaje: str, staff=None) -> str:
        try:
            from agente.staff_db import get_nombre_sucursales
            nombre   = staff.nombre if staff else 'Recepcionista'
            suc_prop = get_nombre_sucursales(staff) if staff else 'sin sucursal asignada'
            contexto = _construir_contexto(staff, mensaje)
            modelo, etiqueta = _elegir_modelo(mensaje)

            prompt_base = self.get_prompt()
            if prompt_base:
                prompt = prompt_base.format(
                    nombre          = nombre,
                    sucursal_propia = suc_prop,
                    contexto        = contexto,
                )
            else:
                log.warning('[Recepcionista] Usando prompt hardcodeado — configura el prompt en el admin')
                prompt = PROMPT_FALLBACK.format(
                    nombre          = nombre,
                    sucursal_propia = suc_prop,
                    contexto        = contexto,
                )

            self.guardar_mensaje(telefono, 'user', mensaje, origen='interno')
            historial = self.get_historial(telefono)
            log.info(f'[Recepcionista] {telefono} | {nombre} | {etiqueta} | {mensaje[:50]}')

            respuesta = self.llamar_claude(
                historial=historial, system_prompt=prompt,
                modelo=modelo, max_tokens=600,
            )
            self.guardar_mensaje(telefono, 'assistant', respuesta, f'{etiqueta.lower()}-recepcionista', origen='interno')
            self.log_respuesta(telefono, respuesta)
            return respuesta

        except Exception as e:
            log.error(f'[Recepcionista] Error para {telefono}: {e}', exc_info=True)
            fallback = self.fallback_mensaje()
            self.guardar_mensaje(telefono, 'assistant', fallback, 'error', origen='interno')
            return fallback


_agente = None

def get_agente() -> AgenteRecepcionista:
    global _agente
    if _agente is None:
        _agente = AgenteRecepcionista()
    return _agente

def responder(telefono: str, mensaje: str, staff=None) -> str:
    return get_agente().responder(telefono, mensaje, staff=staff)