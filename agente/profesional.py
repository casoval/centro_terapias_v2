"""
agente/profesional.py
Agente Profesional — terapeutas y especialistas del Centro Infantil Misael.

Acceso COMPLETO de sus pacientes:
  - Sesiones (historial, próximas, estado)
  - Evolución clínica y notas de sesión
  - Diagnósticos, evaluaciones e informes
  - Datos generales del paciente y familia

SIN acceso a:
  - Pagos, deudas, saldos, facturación
  - Pacientes de otros profesionales

Modelos: Haiku (simple) / Sonnet (clínico/complejo)
"""

import logging
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
)

PROMPT_SISTEMA = """Eres el asistente clínico de apoyo para los profesionales del Centro Infantil Misael.

Asistes a {nombre} ({especialidad}) con información completa de sus pacientes:
- Historial de sesiones realizadas y próximas
- Evolución clínica, notas de sesión y observaciones
- Diagnósticos, evaluaciones e informes terapéuticos
- Datos generales del paciente y su familia

TONO: Clínico, preciso y profesional.

LÍMITES ESTRICTOS:
- Solo accedes a los pacientes de {nombre}
- NO tienes información de pagos ni facturación. Si preguntan, indica: "Esa información la maneja administración."
- NO compartas datos de otros profesionales

Sucursales de {nombre}: {sucursales}

=== DATOS ACTUALIZADOS ===
{contexto}
"""


def _construir_contexto(staff, mensaje: str) -> str:
    from datetime import date, timedelta
    msg  = mensaje.lower()
    prof = staff.profesional if staff else None
    partes = []
    hoy  = date.today()

    if not prof:
        return 'No se encontró información del profesional vinculado.'

    partes.append(
        f"Profesional: {prof.nombre} {prof.apellido} — {prof.especialidad}\n"
        f"Sucursales: {', '.join(s.nombre for s in prof.sucursales.all()) or '—'}"
    )

    # Agenda de hoy siempre presente
    try:
        from agenda.models import Sesion
        sesiones_hoy = Sesion.objects.filter(
            profesional=prof, fecha=hoy
        ).select_related('paciente', 'servicio', 'sucursal').order_by('hora_inicio')

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

    # Próximas sesiones
    if any(p in msg for p in ('proxim', 'semana', 'siguiente', 'mañana', 'manana')):
        try:
            from agenda.models import Sesion
            sesiones = Sesion.objects.filter(
                profesional=prof, fecha__gt=hoy,
                fecha__lte=hoy + timedelta(days=7), estado='programada',
            ).select_related('paciente', 'servicio').order_by('fecha', 'hora_inicio')
            if sesiones.exists():
                lineas = [
                    f"  {s.fecha:%d/%m} {s.hora_inicio.strftime('%H:%M') if s.hora_inicio else '—'}"
                    f" — {s.paciente.nombre} {s.paciente.apellido}"
                    f" ({s.servicio.nombre if s.servicio else '—'})"
                    for s in sesiones
                ]
                partes.append("=== PRÓXIMOS 7 DÍAS ===\n" + '\n'.join(lineas))
        except Exception as e:
            log.error(f'[Profesional] Error próximas: {e}')

    # Notas de evolución clínica
    if any(p in msg for p in ('evolución', 'evolucion', 'nota', 'notas', 'progreso', 'observ', 'avance')):
        try:
            from agenda.models import NotaSesion
            notas = NotaSesion.objects.filter(
                sesion__profesional=prof
            ).select_related('sesion__paciente').order_by('-sesion__fecha')[:10]
            if notas.exists():
                lineas = []
                for n in notas:
                    fecha = n.sesion.fecha.strftime('%d/%m/%Y') if n.sesion else '—'
                    pac   = (f'{n.sesion.paciente.nombre} {n.sesion.paciente.apellido}'
                             if n.sesion and n.sesion.paciente else '—')
                    texto = (getattr(n, 'contenido', '') or
                             getattr(n, 'observaciones', '') or '')[:150]
                    lineas.append(f"  [{fecha}] {pac}: {texto}")
                partes.append("=== NOTAS CLÍNICAS RECIENTES ===\n" + '\n'.join(lineas))
        except Exception as e:
            log.error(f'[Profesional] Error notas: {e}')

    # Diagnósticos / evaluaciones / informes
    if any(p in msg for p in ('diagnóstico', 'diagnostico', 'informe', 'evaluación',
                               'evaluacion', 'reporte', 'historia', 'historial')):
        try:
            from agenda.models import Evaluacion
            evals = Evaluacion.objects.filter(
                profesional=prof
            ).select_related('paciente').order_by('-fecha')[:8]
            if evals.exists():
                lineas = [
                    f"  [{e.fecha:%d/%m/%Y}] {e.paciente.nombre} {e.paciente.apellido}"
                    f" — {getattr(e, 'tipo', '') or getattr(e, 'nombre', '') or '—'}"
                    for e in evals if e.paciente
                ]
                partes.append("=== EVALUACIONES E INFORMES ===\n" + '\n'.join(lineas))
        except Exception as e:
            log.error(f'[Profesional] Error evaluaciones: {e}')

    # Lista de mis pacientes
    if any(p in msg for p in ('paciente', 'pacientes', 'lista', 'mis pacientes', 'cuántos', 'cuantos')):
        try:
            from pacientes.models import Paciente
            pacientes = Paciente.objects.filter(
                sesiones__profesional=prof, estado='activo'
            ).distinct().order_by('apellido', 'nombre')[:25]
            if pacientes.exists():
                lineas = [
                    f"  {p.nombre} {p.apellido} — Tutor: {p.nombre_tutor or '—'}"
                    for p in pacientes
                ]
                partes.append(f"=== MIS PACIENTES ACTIVOS ({pacientes.count()}) ===\n" + '\n'.join(lineas))
        except Exception as e:
            log.error(f'[Profesional] Error pacientes: {e}')

    return '\n\n'.join(partes) if partes else f"Fecha: {hoy:%d/%m/%Y}."


def _elegir_modelo(mensaje: str) -> tuple[str, str]:
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

            prompt = PROMPT_SISTEMA.format(
                nombre       = nombre,
                especialidad = espec,
                sucursales   = sucs,
                contexto     = contexto,
            )

            self.guardar_mensaje(telefono, 'user', mensaje)
            historial = self.get_historial(telefono)
            log.info(f'[Profesional] {telefono} | {nombre} | {etiqueta} | {mensaje[:50]}')

            respuesta = self.llamar_claude(
                historial=historial, system_prompt=prompt,
                modelo=modelo, max_tokens=600,
            )
            self.guardar_mensaje(telefono, 'assistant', respuesta, f'{etiqueta.lower()}-profesional')
            self.log_respuesta(telefono, respuesta)
            return respuesta

        except Exception as e:
            log.error(f'[Profesional] Error para {telefono}: {e}', exc_info=True)
            fallback = self.fallback_mensaje()
            self.guardar_mensaje(telefono, 'assistant', fallback, 'error')
            return fallback


_agente = None

def get_agente() -> AgenteProfesional:
    global _agente
    if _agente is None:
        _agente = AgenteProfesional()
    return _agente

def responder(telefono: str, mensaje: str, staff=None) -> str:
    return get_agente().responder(telefono, mensaje, staff=staff)