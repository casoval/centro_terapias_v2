"""
agente/profesional.py
Agente Profesional — terapeutas y especialistas del Centro Infantil Misael.

Acceso COMPLETO de sus propios pacientes:
  - Sesiones (historial completo, próximas, estado)
  - Notas clínicas (Sesion.notas_sesion — TextField en el modelo Sesion)
  - Evaluaciones: EvaluacionADOS2, EvaluacionADIR, InformeEvaluacion
  - Datos generales del paciente y familia

SIN acceso a:
  - Pagos, deudas, saldos, facturación
  - Pacientes de otros profesionales

BUGS CORREGIDOS vs versión anterior:
  - from agenda.models import NotaSesion → no existe.
    Las notas están en Sesion.notas_sesion (TextField); se lee directamente
    desde Sesion filtrando notas_sesion__gt='' 
  - from agenda.models import Evaluacion → no existe.
    Los modelos reales son EvaluacionADOS2, EvaluacionADIR, InformeEvaluacion
    en evaluaciones.models, con campos 'evaluador' (FK Profesional)
    y 'fecha_evaluacion' / 'fecha_informe'
  - getattr(e, 'tipo', '') → campo no existe en los modelos reales
  - Soporte de fechas históricas con extraer_rango_fechas()

Modelos: Haiku (simple) / Sonnet (clínico/complejo)
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
    'informe', 'reporte', 'evolución', 'evolucion', 'progreso', 'avance',
    'diagnóstico', 'diagnostico', 'evaluación', 'evaluacion',
    'análisis', 'analisis', 'resumen', 'historial', 'historia clínica',
    'observación', 'observacion', 'plan', 'objetivos', 'tratamiento',
    'notas', 'sesiones pasadas', 'detalla', 'explica',
    'anterior', 'pasado', 'enero', 'febrero', 'marzo', 'abril', 'mayo',
    'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre',
)

PROMPT_FALLBACK = """Eres el asistente clínico de apoyo para los profesionales del Centro Infantil Misael.

Asistes a {nombre} ({especialidad}) con información completa de sus pacientes:
- Historial de sesiones realizadas y próximas (cualquier período)
- Notas clínicas de sesiones
- Evaluaciones ADOS-2, ADI-R e informes de evaluación
- Datos generales del paciente y su familia

TONO: Clínico, preciso y profesional.

LÍMITES ESTRICTOS:
- Solo accedes a los pacientes de {nombre}
- NO tienes información de pagos ni facturación. Si preguntan: "Esa información la maneja administración."
- NO compartas datos de otros profesionales

Sucursales de {nombre}: {sucursales}

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


def _construir_contexto(staff, mensaje: str) -> str:
    msg  = mensaje.lower()
    prof = staff.profesional if staff else None
    partes = []
    hoy  = date.today()

    if not prof:
        return 'No se encontró información del profesional vinculado.'

    fecha_desde, fecha_hasta = extraer_rango_fechas(mensaje)
    periodo = _periodo_str(fecha_desde, fecha_hasta)

    partes.append(
        f"Profesional: {prof.nombre} {prof.apellido} — {prof.especialidad}\n"
        f"Sucursales: {', '.join(s.nombre for s in prof.sucursales.all()) or '—'}\n"
        f"Período consultado: {periodo}"
    )

    # ── Agenda de HOY (siempre presente) ──────────────────────────────────────
    try:
        from agenda.models import Sesion
        sesiones_hoy = (
            Sesion.objects.filter(profesional=prof, fecha=hoy)
            .select_related('paciente', 'servicio', 'sucursal')
            .order_by('hora_inicio')
        )
        if sesiones_hoy.exists():
            lineas = []
            for s in sesiones_hoy:
                hora = s.hora_inicio.strftime('%H:%M') if s.hora_inicio else '—'
                pac  = f'{s.paciente.nombre} {s.paciente.apellido}' if s.paciente else '—'
                serv = s.servicio.nombre if s.servicio else '—'
                lineas.append(f"  {hora} — {pac} ({serv}) [{s.estado}]")
            partes.append("=== AGENDA DE HOY ===\n" + '\n'.join(lineas))
        else:
            partes.append(f"Sin sesiones programadas para hoy ({hoy:%d/%m/%Y})")
    except Exception as e:
        log.error(f'[Profesional] Error agenda hoy: {e}')

    # ── Sesiones del período histórico consultado ─────────────────────────────
    es_hoy_exacto = (fecha_desde == hoy and fecha_hasta == hoy)
    if not es_hoy_exacto and any(p in msg for p in (
        'sesion', 'sesiones', 'historial', 'anterior', 'pasado',
        'semana', 'mes', 'año', 'cuántas', 'cuantas',
        'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
        'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre',
    )):
        try:
            from agenda.models import Sesion
            from django.db.models import Count, Sum
            qs_p = Sesion.objects.filter(
                profesional=prof,
                fecha__gte=fecha_desde,
                fecha__lte=fecha_hasta,
            ).select_related('paciente', 'servicio', 'sucursal').order_by('-fecha')

            total     = qs_p.count()
            realizadas = qs_p.filter(estado__in=['realizada', 'realizada_retraso']).count()
            faltas    = qs_p.filter(estado='falta').count()
            lineas    = [
                f"  [{s.fecha:%d/%m/%Y}] {s.paciente.nombre} {s.paciente.apellido if s.paciente else '—'} "
                f"— {s.servicio.nombre if s.servicio else '—'} [{s.estado}]"
                for s in qs_p[:50]
            ]
            partes.append(
                f"=== SESIONES: {periodo} ===\n"
                f"Total: {total} | Realizadas: {realizadas} | Faltas: {faltas}\n"
                + '\n'.join(lineas)
                + (f"\n  ... y {total - 50} más" if total > 50 else '')
            )
        except Exception as e:
            log.error(f'[Profesional] Error sesiones periodo: {e}')

    # ── Próximas sesiones ─────────────────────────────────────────────────────
    if any(p in msg for p in ('proxim', 'siguiente', 'mañana', 'manana',
                               'próxima semana', 'esta semana')):
        try:
            from agenda.models import Sesion
            sesiones_fut = (
                Sesion.objects.filter(
                    profesional=prof,
                    fecha__gt=hoy,
                    fecha__lte=hoy + timedelta(days=7),
                    estado='programada',
                )
                .select_related('paciente', 'servicio')
                .order_by('fecha', 'hora_inicio')
            )
            if sesiones_fut.exists():
                lineas = [
                    f"  {s.fecha:%d/%m} {s.hora_inicio.strftime('%H:%M') if s.hora_inicio else '—'}"
                    f" — {s.paciente.nombre} {s.paciente.apellido if s.paciente else '—'}"
                    f" ({s.servicio.nombre if s.servicio else '—'})"
                    for s in sesiones_fut
                ]
                partes.append("=== PRÓXIMOS 7 DÍAS ===\n" + '\n'.join(lineas))
        except Exception as e:
            log.error(f'[Profesional] Error próximas: {e}')

    # ── Notas clínicas ────────────────────────────────────────────────────────
    # CORRECCIÓN: NotaSesion no existe en el modelo.
    # Las notas están en Sesion.notas_sesion (TextField).
    # Filtramos sesiones que tengan notas_sesion no vacío.
    if any(p in msg for p in ('nota', 'notas', 'evolución', 'evolucion',
                               'progreso', 'observ', 'avance', 'clínico', 'clinico')):
        try:
            from agenda.models import Sesion
            sesiones_con_notas = (
                Sesion.objects.filter(
                    profesional=prof,
                    fecha__gte=fecha_desde,
                    fecha__lte=fecha_hasta,
                    notas_sesion__gt='',
                )
                .select_related('paciente')
                .order_by('-fecha')[:10]
            )
            if sesiones_con_notas.exists():
                lineas = []
                for s in sesiones_con_notas:
                    pac   = f'{s.paciente.nombre} {s.paciente.apellido}' if s.paciente else '—'
                    nota  = (s.notas_sesion or '')[:200]
                    lineas.append(f"  [{s.fecha:%d/%m/%Y}] {pac}: {nota}")
                partes.append(
                    f"=== NOTAS CLÍNICAS ({periodo}) ===\n" + '\n'.join(lineas)
                )
            else:
                partes.append(f"Sin notas clínicas registradas para {periodo}.")
        except Exception as e:
            log.error(f'[Profesional] Error notas: {e}')

    # ── Evaluaciones e informes ───────────────────────────────────────────────
    # CORRECCIÓN: Evaluacion no existe en agenda.models.
    # Los modelos correctos son EvaluacionADOS2, EvaluacionADIR, InformeEvaluacion
    # en evaluaciones.models con campo 'evaluador' (FK a Profesional)
    if any(p in msg for p in ('diagnóstico', 'diagnostico', 'informe', 'evaluación',
                               'evaluacion', 'reporte', 'historia', 'historial',
                               'ados', 'adir')):
        # InformeEvaluacion
        try:
            from evaluaciones.models import InformeEvaluacion
            informes = (
                InformeEvaluacion.objects
                .filter(
                    evaluador=prof,
                    fecha_informe__gte=fecha_desde,
                    fecha_informe__lte=fecha_hasta,
                )
                .select_related('paciente')
                .order_by('-fecha_informe')[:8]
            )
            if informes.exists():
                lineas = [
                    f"  [{i.fecha_informe:%d/%m/%Y}] {i.paciente.nombre} {i.paciente.apellido}"
                    f" — {i.estado}"
                    for i in informes if i.paciente
                ]
                partes.append(
                    f"=== INFORMES DE EVALUACIÓN ({periodo}) ===\n" + '\n'.join(lineas)
                )
        except Exception as e:
            log.error(f'[Profesional] Error informes: {e}')

        # EvaluacionADOS2
        try:
            from evaluaciones.models import EvaluacionADOS2
            evals_ados = (
                EvaluacionADOS2.objects
                .filter(
                    evaluador=prof,
                    fecha_evaluacion__gte=fecha_desde,
                    fecha_evaluacion__lte=fecha_hasta,
                )
                .select_related('paciente')
                .order_by('-fecha_evaluacion')[:8]
            )
            if evals_ados.exists():
                lineas = [
                    f"  [{e.fecha_evaluacion:%d/%m/%Y}] {e.paciente.nombre} {e.paciente.apellido}"
                    for e in evals_ados if e.paciente
                ]
                partes.append("=== EVALUACIONES ADOS-2 ===\n" + '\n'.join(lineas))
        except Exception as e:
            log.error(f'[Profesional] Error ADOS-2: {e}')

        # EvaluacionADIR
        try:
            from evaluaciones.models import EvaluacionADIR
            evals_adir = (
                EvaluacionADIR.objects
                .filter(
                    evaluador=prof,
                    fecha_evaluacion__gte=fecha_desde,
                    fecha_evaluacion__lte=fecha_hasta,
                )
                .select_related('paciente')
                .order_by('-fecha_evaluacion')[:8]
            )
            if evals_adir.exists():
                lineas = [
                    f"  [{e.fecha_evaluacion:%d/%m/%Y}] {e.paciente.nombre} {e.paciente.apellido}"
                    for e in evals_adir if e.paciente
                ]
                partes.append("=== EVALUACIONES ADI-R ===\n" + '\n'.join(lineas))
        except Exception as e:
            log.error(f'[Profesional] Error ADI-R: {e}')

    # ── Lista de mis pacientes ────────────────────────────────────────────────
    if any(p in msg for p in ('paciente', 'pacientes', 'lista', 'mis pacientes',
                               'cuántos', 'cuantos', 'cuántos pacientes')):
        try:
            from pacientes.models import Paciente
            pacientes = (
                Paciente.objects
                .filter(sesiones__profesional=prof, estado='activo')
                .distinct()
                .order_by('apellido', 'nombre')[:25]
            )
            if pacientes.exists():
                lineas = [
                    f"  {p.nombre} {p.apellido} — Tutor: {p.nombre_tutor or '—'} "
                    f"Tel: {p.telefono_tutor or '—'}"
                    for p in pacientes
                ]
                partes.append(
                    f"=== MIS PACIENTES ACTIVOS ({pacientes.count()}) ===\n"
                    + '\n'.join(lineas)
                )
        except Exception as e:
            log.error(f'[Profesional] Error pacientes: {e}')

    return '\n\n'.join(partes) if partes else f"Fecha: {hoy:%d/%m/%Y}."


def _elegir_modelo(mensaje: str) -> tuple:
    msg = mensaje.lower()
    if any(p in msg for p in PALABRAS_SONNET) or len(mensaje.split()) > 20:
        return MODELO_COMPLETO, 'Sonnet'
    return MODELO_RAPIDO, 'Haiku'


class AgenteProfesional(AgenteBase):
    TIPO = 'profesional'

    def responder(self, telefono: str, mensaje: str, staff=None) -> str:
        try:
            from agente.staff_db import get_nombre_sucursales
            prof     = staff.profesional if staff else None
            nombre   = staff.nombre if staff else 'Profesional'
            espec    = prof.especialidad if prof else '—'
            sucs     = get_nombre_sucursales(staff) if staff else '—'
            contexto = _construir_contexto(staff, mensaje)
            modelo, etiqueta = _elegir_modelo(mensaje)

            prompt_base = self.get_prompt()
            if prompt_base:
                prompt = prompt_base.format(
                    nombre       = nombre,
                    especialidad = espec,
                    sucursales   = sucs,
                    contexto     = contexto,
                )
            else:
                log.warning('[Profesional] Usando prompt hardcodeado — configura el prompt en el admin')
                prompt = PROMPT_FALLBACK.format(
                    nombre       = nombre,
                    especialidad = espec,
                    sucursales   = sucs,
                    contexto     = contexto,
                )

            self.guardar_mensaje(telefono, 'user', mensaje, origen='interno')
            historial = self.get_historial(telefono)
            log.info(f'[Profesional] {telefono} | {nombre} | {etiqueta} | {mensaje[:50]}')

            respuesta = self.llamar_claude(
                historial=historial, system_prompt=prompt,
                modelo=modelo, max_tokens=600,
            )
            self.guardar_mensaje(telefono, 'assistant', respuesta, f'{etiqueta.lower()}-profesional', origen='interno')
            self.log_respuesta(telefono, respuesta)
            return respuesta

        except Exception as e:
            log.error(f'[Profesional] Error para {telefono}: {e}', exc_info=True)
            fallback = self.fallback_mensaje()
            self.guardar_mensaje(telefono, 'assistant', fallback, 'error', origen='interno')
            return fallback


_agente = None

def get_agente() -> AgenteProfesional:
    global _agente
    if _agente is None:
        _agente = AgenteProfesional()
    return _agente

def responder(telefono: str, mensaje: str, staff=None) -> str:
    return get_agente().responder(telefono, mensaje, staff=staff)