"""
agente/gerente.py
Agente Gerente — gestión operativa completa del Centro Infantil Misael.

Acceso TOTAL (recepcionista + profesional):
  - Agenda, sesiones, asistencia — con soporte histórico completo
  - Facturación: pagos, deudas, saldos, mensualidades
  - Información clínica: evaluaciones e informes
  - Rendimiento por profesional
  Por defecto SU sucursal, puede pedir otras.

BUGS CORREGIDOS vs versión anterior:
  - Pago.fecha → Pago.fecha_pago  (el campo real del modelo)
  - Pago filtrado por sucursal a través de sesion__sucursal (no FK directo)
  - anulado=False en todas las queries de Pago
  - from agenda.models import Evaluacion → no existe;
    ahora usa EvaluacionADOS2, EvaluacionADIR, InformeEvaluacion de evaluaciones.models
  - Mensualidad está en agenda.models, no en facturacion.models
  - estados Mensualidad correctos: 'activa', 'pausada' (no 'pendiente'/'parcial')
  - costo_mensual en vez de monto_total
  - Soporte de fechas históricas con extraer_rango_fechas()

Modelos: Haiku (simple) / Sonnet (análisis / reportes)
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
    'informe', 'reporte', 'resumen', 'análisis', 'analisis', 'detallado',
    'rendimiento', 'productividad', 'comparar', 'evolución', 'evolucion',
    'diagnóstico', 'diagnostico', 'deuda', 'deudas', 'mensualidad',
    'facturación', 'facturacion', 'proyección', 'proyeccion',
    'semana', 'mes', 'todos', 'todas', 'general', 'histórico', 'historico',
    'anterior', 'pasado', 'enero', 'febrero', 'marzo', 'abril', 'mayo',
    'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre',
)

PROMPT_FALLBACK = """Eres el asistente de gestión del Centro Infantil Misael, trabajando con {nombre} (gerente).

Tienes acceso COMPLETO a toda la información del centro:

OPERATIVO:
- Agenda de sesiones por profesional y sucursal (histórico completo)
- Estado de asistencia: realizadas, permisos, faltas, cancelaciones

FINANCIERO:
- Ingresos por período (hoy, semana, mes, rangos históricos)
- Deudas y saldos de pacientes
- Mensualidades y proyectos

CLÍNICO (visión gerencial):
- Evaluaciones e informes completados
- Rendimiento por profesional

TONO: Ejecutivo, analítico. Si detectas algo que requiere atención, menciónalo.

SUCURSALES:
- Sucursal principal de {nombre}: {sucursal_propia}
- Por defecto muestra datos de tu sucursal
- Si pides "todas" o nombras otra sede, amplía la vista

=== DATOS ACTUALIZADOS ===
{contexto}
"""

# ── Nombres de meses para el extractor de fechas ──────────────────────────────
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


def _pide_otra_sucursal(mensaje: str) -> bool:
    msg = mensaje.lower()
    return any(p in msg for p in (
        'otra sucursal', 'todas las sucursales', 'todas sucursales',
        'ambas sedes', 'las dos sedes', 'sede japón', 'sede japon',
        'sede camacho', 'todas las sedes', 'otra sede',
        'en total', 'todo el centro', 'global',
    ))


def _construir_contexto(staff, mensaje: str) -> str:
    from django.db.models import Sum, Count, Q
    msg    = mensaje.lower()
    partes = []
    hoy    = date.today()

    # Rango de fechas detectado en el mensaje
    fecha_desde, fecha_hasta = extraer_rango_fechas(mensaje)
    periodo = _periodo_str(fecha_desde, fecha_hasta)

    # Sucursales del gerente
    suc_ids = []
    if staff and staff.sucursales:
        try:
            suc_ids = list(staff.sucursales.values_list('id', flat=True))
        except Exception:
            pass
    filtrar = bool(suc_ids) and not _pide_otra_sucursal(mensaje)
    scope   = 'su sucursal' if filtrar else 'todas las sucursales'

    partes.append(f"Fecha: {hoy:%d/%m/%Y} | Vista: {scope} | Período consultado: {periodo}")

    # ── Operaciones de HOY (siempre) ──────────────────────────────────────────
    try:
        from agenda.models import Sesion
        qs = Sesion.objects.filter(fecha=hoy)
        if filtrar:
            qs = qs.filter(sucursal__id__in=suc_ids)
        resumen = {r['estado']: r['total'] for r in qs.values('estado').annotate(total=Count('id'))}
        partes.append(
            f"=== OPERACIONES DE HOY ({scope}) ===\n"
            f"Programadas: {resumen.get('programada', 0)} | "
            f"Realizadas: {resumen.get('realizada', 0) + resumen.get('realizada_retraso', 0)} | "
            f"Permisos: {resumen.get('permiso', 0)} | "
            f"Faltas: {resumen.get('falta', 0)} | "
            f"Canceladas: {resumen.get('cancelada', 0)}"
        )
    except Exception as e:
        log.error(f'[Gerente] Error operaciones hoy: {e}')

    # ── Sesiones del período consultado ───────────────────────────────────────
    if any(p in msg for p in ('sesion', 'sesiones', 'agenda', 'asistencia', 'realiz',
                               'falta', 'cancelad', 'semana', 'mes', 'período', 'periodo')):
        try:
            from agenda.models import Sesion
            qs_p = Sesion.objects.filter(fecha__gte=fecha_desde, fecha__lte=fecha_hasta)
            if filtrar:
                qs_p = qs_p.filter(sucursal__id__in=suc_ids)
            res_p = {r['estado']: r['total'] for r in qs_p.values('estado').annotate(total=Count('id'))}
            por_prof = (
                qs_p.filter(estado__in=['realizada', 'realizada_retraso'])
                .values('profesional__nombre', 'profesional__apellido')
                .annotate(total=Count('id'))
                .order_by('-total')
            )
            lineas_prof = [
                f"  {d['profesional__nombre']} {d['profesional__apellido']}: {d['total']} sesiones"
                for d in por_prof
            ]
            partes.append(
                f"=== SESIONES: {periodo} ({scope}) ===\n"
                f"Total: {qs_p.count()} | "
                f"Realizadas: {res_p.get('realizada', 0) + res_p.get('realizada_retraso', 0)} | "
                f"Programadas: {res_p.get('programada', 0)} | "
                f"Permisos: {res_p.get('permiso', 0)} | "
                f"Faltas: {res_p.get('falta', 0)} | "
                f"Canceladas: {res_p.get('cancelada', 0)}"
                + ('\nPor profesional:\n' + '\n'.join(lineas_prof) if lineas_prof else '')
            )
        except Exception as e:
            log.error(f'[Gerente] Error sesiones periodo: {e}')

    # ── Financiero ────────────────────────────────────────────────────────────
    if any(p in msg for p in ('ingreso', 'pago', 'cobro', 'caja', 'dinero', 'factur',
                               'deuda', 'saldo', 'balance', 'mensualidad', 'pendiente',
                               'cuánto', 'cuanto', 'total cobrado')):
        try:
            from facturacion.models import Pago, CuentaCorriente

            # ── Ingresos de HOY ────────────────────────────────────────────────
            qs_hoy = Pago.objects.filter(fecha_pago=hoy, anulado=False)
            if filtrar:
                # Pago no tiene FK directo a sucursal — filtrar a través de sesion
                qs_hoy = qs_hoy.filter(
                    Q(sesion__sucursal__id__in=suc_ids) |
                    Q(proyecto__sucursal__id__in=suc_ids) |
                    Q(mensualidad__sucursal__id__in=suc_ids)
                )
            total_hoy = float(qs_hoy.aggregate(t=Sum('monto'))['t'] or 0)

            # ── Ingresos del período consultado ────────────────────────────────
            qs_per = Pago.objects.filter(
                fecha_pago__gte=fecha_desde,
                fecha_pago__lte=fecha_hasta,
                anulado=False,
            )
            if filtrar:
                qs_per = qs_per.filter(
                    Q(sesion__sucursal__id__in=suc_ids) |
                    Q(proyecto__sucursal__id__in=suc_ids) |
                    Q(mensualidad__sucursal__id__in=suc_ids)
                )
            total_per = float(qs_per.aggregate(t=Sum('monto'))['t'] or 0)

            # ── Desglose por método ────────────────────────────────────────────
            por_metodo = (
                qs_per.values('metodo_pago__nombre')
                .annotate(total=Sum('monto'), count=Count('id'))
                .order_by('-total')
            )
            lineas_met = [
                f"  {d['metodo_pago__nombre'] or '—'}: {d['count']} pagos — Bs. {float(d['total'] or 0):,.0f}"
                for d in por_metodo
            ]

            partes.append(
                f"=== INGRESOS ({scope}) ===\n"
                f"Hoy: Bs. {total_hoy:,.2f}\n"
                f"Período ({periodo}): Bs. {total_per:,.2f} en {qs_per.count()} pagos"
                + ('\nPor método:\n' + '\n'.join(lineas_met) if lineas_met else '')
            )

            # ── Deudas ────────────────────────────────────────────────────────
            deudas = (
                CuentaCorriente.objects
                .filter(saldo_actual__lt=0)
                .select_related('paciente')
                .order_by('saldo_actual')[:12]
            )
            if deudas.exists():
                lineas = [
                    f"  {c.paciente.nombre} {c.paciente.apellido}: Bs. {abs(float(c.saldo_actual)):,.2f}"
                    for c in deudas if c.paciente
                ]
                total_deuda = sum(abs(float(c.saldo_actual)) for c in deudas if c.paciente)
                partes.append(
                    f"=== DEUDAS PENDIENTES (total: Bs. {total_deuda:,.2f}) ===\n"
                    + '\n'.join(lineas)
                )
        except Exception as e:
            log.error(f'[Gerente] Error financiero: {e}')

    # ── Mensualidades ─────────────────────────────────────────────────────────
    if any(p in msg for p in ('mensualidad', 'mensualidades', 'cuota')):
        try:
            from agenda.models import Mensualidad  # ← en agenda, NO en facturacion
            # estados válidos: 'activa', 'pausada', 'completada', 'cancelada'
            mens = (
                Mensualidad.objects
                .filter(estado__in=['activa', 'pausada'])
                .select_related('paciente', 'sucursal')
                .order_by('-anio', '-mes')[:15]
            )
            if mens.exists():
                lineas = []
                for m in mens:
                    try:
                        pendiente = float(m.saldo_pendiente)
                    except Exception:
                        pendiente = float(m.costo_mensual)
                    suc = m.sucursal.nombre if m.sucursal else '—'
                    pac = f'{m.paciente.nombre} {m.paciente.apellido}' if m.paciente else '—'
                    lineas.append(
                        f"  {pac} — {m.mes:02d}/{m.anio} — "
                        f"Bs. {float(m.costo_mensual):,.2f} (pendiente: Bs. {pendiente:,.2f}) "
                        f"[{m.estado}] {suc}"
                    )
                partes.append("=== MENSUALIDADES ACTIVAS/PAUSADAS ===\n" + '\n'.join(lineas))
        except Exception as e:
            log.error(f'[Gerente] Error mensualidades: {e}')

    # ── Rendimiento profesionales ─────────────────────────────────────────────
    if any(p in msg for p in ('profesional', 'terapeuta', 'rendimiento', 'productividad',
                               'desempeño', 'desempeno', 'quién atendió', 'quien atendio')):
        try:
            from agenda.models import Sesion
            qs_r = Sesion.objects.filter(
                fecha__gte=fecha_desde,
                fecha__lte=fecha_hasta,
                estado__in=['realizada', 'realizada_retraso'],
            )
            if filtrar:
                qs_r = qs_r.filter(sucursal__id__in=suc_ids)
            datos = (
                qs_r.values('profesional__nombre', 'profesional__apellido')
                .annotate(total=Count('id'))
                .order_by('-total')
            )
            if datos.exists():
                lineas = [
                    f"  {d['profesional__nombre']} {d['profesional__apellido']}: {d['total']} sesiones"
                    for d in datos
                ]
                partes.append(
                    f"=== RENDIMIENTO PROFESIONALES ({periodo}) ===\n" + '\n'.join(lineas)
                )
        except Exception as e:
            log.error(f'[Gerente] Error rendimiento: {e}')

    # ── Evaluaciones e informes ───────────────────────────────────────────────
    # CORRECCIÓN: Evaluacion no existe en agenda.models.
    # Los modelos reales son EvaluacionADOS2, EvaluacionADIR, InformeEvaluacion
    # en evaluaciones.models, con campo 'evaluador' (FK a Profesional) y 'fecha_evaluacion'
    if any(p in msg for p in ('evaluación', 'evaluacion', 'informe', 'ados', 'adir',
                               'clínico', 'clinico', 'diagnóstico', 'diagnostico')):
        try:
            from evaluaciones.models import InformeEvaluacion
            informes = (
                InformeEvaluacion.objects
                .filter(fecha_informe__gte=fecha_desde, fecha_informe__lte=fecha_hasta)
                .select_related('paciente', 'evaluador')
                .order_by('-fecha_informe')[:10]
            )
            if informes.exists():
                lineas = [
                    f"  [{i.fecha_informe:%d/%m/%Y}] {i.paciente.nombre} {i.paciente.apellido}"
                    f" — Prof: {i.evaluador.nombre} {i.evaluador.apellido}"
                    f" — {i.estado}"
                    for i in informes if i.paciente and i.evaluador
                ]
                partes.append(
                    f"=== INFORMES DE EVALUACIÓN ({periodo}) ===\n" + '\n'.join(lineas)
                )
        except Exception as e:
            log.error(f'[Gerente] Error informes: {e}')

        try:
            from evaluaciones.models import EvaluacionADOS2
            evals = (
                EvaluacionADOS2.objects
                .filter(fecha_evaluacion__gte=fecha_desde, fecha_evaluacion__lte=fecha_hasta)
                .select_related('paciente', 'evaluador')
                .order_by('-fecha_evaluacion')[:8]
            )
            if evals.exists():
                lineas = [
                    f"  [{e.fecha_evaluacion:%d/%m/%Y}] {e.paciente.nombre} {e.paciente.apellido}"
                    f" — Evaluador: {e.evaluador.nombre} {e.evaluador.apellido}"
                    for e in evals if e.paciente and e.evaluador
                ]
                partes.append("=== EVALUACIONES ADOS-2 ===\n" + '\n'.join(lineas))
        except Exception as e:
            log.error(f'[Gerente] Error ADOS-2: {e}')

    return '\n\n'.join(partes) if partes else f"Fecha: {hoy:%d/%m/%Y}."


def _elegir_modelo(mensaje: str) -> tuple:
    msg = mensaje.lower()
    if any(p in msg for p in PALABRAS_SONNET) or len(mensaje.split()) > 20:
        return MODELO_COMPLETO, 'Sonnet'
    return MODELO_RAPIDO, 'Haiku'


class AgenteGerente(AgenteBase):
    TIPO = 'gerente'

    def responder(self, telefono: str, mensaje: str, staff=None) -> str:
        try:
            from agente.staff_db import get_nombre_sucursales
            nombre   = staff.nombre if staff else 'Gerente'
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
                log.warning('[Gerente] Usando prompt hardcodeado — configura el prompt en el admin')
                prompt = PROMPT_FALLBACK.format(
                    nombre          = nombre,
                    sucursal_propia = suc_prop,
                    contexto        = contexto,
                )

            self.guardar_mensaje(telefono, 'user', mensaje, origen='interno')
            historial = self.get_historial(telefono)
            log.info(f'[Gerente] {telefono} | {nombre} | {etiqueta} | {mensaje[:50]}')

            respuesta = self.llamar_claude(
                historial=historial, system_prompt=prompt,
                modelo=modelo, max_tokens=700,
            )
            self.guardar_mensaje(telefono, 'assistant', respuesta, f'{etiqueta.lower()}-gerente', origen='interno')
            self.log_respuesta(telefono, respuesta)
            return respuesta

        except Exception as e:
            log.error(f'[Gerente] Error para {telefono}: {e}', exc_info=True)
            fallback = self.fallback_mensaje()
            self.guardar_mensaje(telefono, 'assistant', fallback, 'error', origen='interno')
            return fallback


_agente = None

def get_agente() -> AgenteGerente:
    global _agente
    if _agente is None:
        _agente = AgenteGerente()
    return _agente

def responder(telefono: str, mensaje: str, staff=None) -> str:
    return get_agente().responder(telefono, mensaje, staff=staff)