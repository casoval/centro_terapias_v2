"""
agente/recepcionista.py
Agente Recepcionista — personal de recepción del Centro Infantil Misael.

Acceso:
  - Sesiones, agenda, estado de citas
  - Pagos, deudas, saldos, facturación
  - Información general de pacientes (datos, tutores, contactos)
  - Mensualidades y proyectos
  Por defecto muestra SU sucursal, pero puede pedir otras.

SIN acceso a:
  - Evolución clínica, notas de sesión
  - Diagnósticos, evaluaciones médicas
  - Informes de profesionales

Modelos: Haiku (simple) / Sonnet (complejo)
"""

import logging
from agente.agente_base import AgenteBase

log = logging.getLogger('agente')

MODELO_RAPIDO   = 'claude-haiku-4-5-20251001'
MODELO_COMPLETO = 'claude-sonnet-4-6'

PALABRAS_SONNET = (
    'informe', 'reporte', 'resumen', 'detalle', 'deuda', 'deudas',
    'mensualidad', 'mensualidades', 'proyecto', 'proyectos',
    'facturación', 'facturacion', 'historial de pagos', 'todas las',
    'comparar', 'análisis', 'analisis', 'cuánto', 'cuanto',
    'pendiente', 'pendientes', 'balance',
)

PROMPT_SISTEMA = """Eres el asistente de recepción del Centro Infantil Misael.

Asistes a {nombre} (recepcionista) en sus tareas operativas y administrativas:
- Agenda del día: sesiones programadas, cancelaciones, permisos, faltas
- Información de pacientes: datos de contacto, tutor, estado
- Facturación: pagos realizados, deudas, saldos de cuentas corrientes
- Mensualidades y proyectos pendientes
- Coordinación de citas

TONO: Eficiente, organizado y profesional.

IMPORTANTE — SUCURSALES:
- Tu sucursal asignada: {sucursal_propia}
- Por defecto SIEMPRE muestra datos de tu sucursal
- Si la recepcionista pide explícitamente otra sucursal o "todas", amplía la vista

LÍMITES ESTRICTOS:
- NO tienes acceso a evolución clínica, diagnósticos ni informes de terapeutas
- Si preguntan por historial clínico, indica: "Esa información es clínica y la maneja el profesional a cargo."

=== DATOS ACTUALIZADOS ===
{contexto}
"""


def _get_sucursal_ids_propios(staff) -> list:
    """IDs de sucursales propias. Vacío = todas."""
    if not staff or not staff.sucursales:
        return []
    try:
        return list(staff.sucursales.values_list('id', flat=True))
    except Exception:
        return []


def _pide_otra_sucursal(mensaje: str) -> bool:
    """Detecta si la recepcionista pide datos de otra sucursal."""
    msg = mensaje.lower()
    return any(p in msg for p in (
        'otra sucursal', 'todas las sucursales', 'todas sucursales',
        'ambas sedes', 'las dos sedes', 'sede japón', 'sede japon',
        'sede camacho', 'todas las sedes', 'sede central', 'sede principal',
        'otra sede', 'en total', 'todo el centro',
    ))


def _construir_contexto(staff, mensaje: str) -> str:
    from datetime import date, timedelta
    from django.db.models import Sum, Count
    msg  = mensaje.lower()
    partes = []
    hoy  = date.today()

    suc_ids = _get_sucursal_ids_propios(staff)
    # Si pide otra sucursal, no filtrar
    filtrar_sucursal = bool(suc_ids) and not _pide_otra_sucursal(mensaje)

    partes.append(f"Fecha: {hoy:%d/%m/%Y}")

    # Agenda del día
    try:
        from agenda.models import Sesion
        from django.db.models import Count as Cnt
        qs = Sesion.objects.filter(fecha=hoy)
        if filtrar_sucursal:
            qs = qs.filter(sucursal__id__in=suc_ids)

        resumen = qs.values('estado').annotate(total=Cnt('id'))
        por_estado = {r['estado']: r['total'] for r in resumen}
        partes.append(
            f"=== AGENDA DE HOY ({'su sucursal' if filtrar_sucursal else 'todas las sucursales'}) ===\n"
            f"Programadas: {por_estado.get('programada', 0)} | "
            f"Realizadas: {por_estado.get('realizada', 0) + por_estado.get('realizada_retraso', 0)} | "
            f"Permisos: {por_estado.get('permiso', 0)} | "
            f"Faltas: {por_estado.get('falta', 0)} | "
            f"Canceladas: {por_estado.get('cancelada', 0)}"
        )

        # Detalle de sesiones programadas
        if any(p in msg for p in ('quién', 'quien', 'lista', 'detalle', 'sesiones de hoy', 'agenda')):
            sesiones_det = qs.filter(estado='programada').select_related(
                'paciente', 'profesional', 'servicio', 'sucursal'
            ).order_by('hora_inicio')
            if sesiones_det.exists():
                lineas = []
                for s in sesiones_det:
                    hora = s.hora_inicio.strftime('%H:%M') if s.hora_inicio else '—'
                    pac  = f'{s.paciente.nombre} {s.paciente.apellido}' if s.paciente else '—'
                    prof = f'{s.profesional.nombre} {s.profesional.apellido}' if s.profesional else '—'
                    suc  = s.sucursal.nombre if s.sucursal else '—'
                    lineas.append(f"  {hora} — {pac} con {prof} — {suc}")
                partes.append("=== DETALLE SESIONES HOY ===\n" + '\n'.join(lineas))
    except Exception as e:
        log.error(f'[Recepcionista] Error agenda: {e}')

    # Pagos / deudas / facturación
    if any(p in msg for p in ('pago', 'pagos', 'deuda', 'deudas', 'saldo', 'factur',
                               'debe', 'pendiente', 'cobro', 'balance', 'cuenta')):
        try:
            from facturacion.models import Pago, CuentaCorriente
            # Ingresos del día
            qs_pagos = Pago.objects.filter(fecha=hoy)
            if filtrar_sucursal:
                qs_pagos = qs_pagos.filter(sucursal__id__in=suc_ids)
            total_hoy = qs_pagos.aggregate(t=Sum('monto'))['t'] or 0
            partes.append(f"=== INGRESOS DE HOY ===\nTotal cobrado: Bs. {float(total_hoy):.2f}")

            # Deudas pendientes
            deudas = CuentaCorriente.objects.filter(
                saldo_actual__lt=0
            ).select_related('paciente').order_by('saldo_actual')[:10]
            if deudas.exists():
                lineas = [
                    f"  {c.paciente.nombre} {c.paciente.apellido}: Bs. {abs(float(c.saldo_actual)):.2f}"
                    for c in deudas if c.paciente
                ]
                partes.append("=== PACIENTES CON DEUDA ===\n" + '\n'.join(lineas))
        except Exception as e:
            log.error(f'[Recepcionista] Error pagos/deudas: {e}')

    # Mensualidades pendientes
    if any(p in msg for p in ('mensualidad', 'mensualidades', 'cuota', 'cuotas')):
        try:
            from facturacion.models import Mensualidad
            from django.db.models import Q
            mens = Mensualidad.objects.filter(
                Q(estado='pendiente') | Q(estado='parcial')
            ).select_related('paciente').order_by('fecha_vencimiento')[:8]
            if mens.exists():
                lineas = [
                    f"  {m.paciente.nombre} {m.paciente.apellido}"
                    f" — Bs. {float(getattr(m, 'monto_total', 0) or 0):.2f} ({m.estado})"
                    for m in mens if m.paciente
                ]
                partes.append("=== MENSUALIDADES PENDIENTES ===\n" + '\n'.join(lineas))
        except Exception as e:
            log.error(f'[Recepcionista] Error mensualidades: {e}')

    # Búsqueda de paciente
    if any(p in msg for p in ('paciente', 'tutor', 'contacto', 'teléfono', 'telefono', 'buscar')):
        partes.append("=== NOTA ===\nPara buscar un paciente específico, indícame su nombre o teléfono.")

    return '\n\n'.join(partes) if partes else f"Fecha: {hoy:%d/%m/%Y}. Listo para ayudarte."


def _elegir_modelo(mensaje: str) -> tuple[str, str]:
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

            prompt = PROMPT_SISTEMA.format(
                nombre         = nombre,
                sucursal_propia = suc_prop,
                contexto       = contexto,
            )

            self.guardar_mensaje(telefono, 'user', mensaje)
            historial = self.get_historial(telefono)
            log.info(f'[Recepcionista] {telefono} | {nombre} | {etiqueta} | {mensaje[:50]}')

            respuesta = self.llamar_claude(
                historial=historial, system_prompt=prompt,
                modelo=modelo, max_tokens=600,
            )
            self.guardar_mensaje(telefono, 'assistant', respuesta, f'{etiqueta.lower()}-recepcionista')
            self.log_respuesta(telefono, respuesta)
            return respuesta

        except Exception as e:
            log.error(f'[Recepcionista] Error para {telefono}: {e}', exc_info=True)
            fallback = self.fallback_mensaje()
            self.guardar_mensaje(telefono, 'assistant', fallback, 'error')
            return fallback


_agente = None

def get_agente() -> AgenteRecepcionista:
    global _agente
    if _agente is None:
        _agente = AgenteRecepcionista()
    return _agente

def responder(telefono: str, mensaje: str, staff=None) -> str:
    return get_agente().responder(telefono, mensaje, staff=staff)