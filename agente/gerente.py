"""
agente/gerente.py
Agente Gerente — gestión operativa completa del Centro Infantil Misael.

Acceso TOTAL (recepcionista + profesional):
  - Agenda, sesiones, asistencia
  - Facturación: pagos, deudas, saldos, mensualidades
  - Información clínica: evolución, diagnósticos, evaluaciones
  - Rendimiento por profesional
  Por defecto SU sucursal, puede pedir otras.

Modelos: Haiku (simple) / Sonnet (análisis / reportes)
"""

import logging
from agente.agente_base import AgenteBase

log = logging.getLogger('agente')

MODELO_RAPIDO   = 'claude-haiku-4-5-20251001'
MODELO_COMPLETO = 'claude-sonnet-4-6'

PALABRAS_SONNET = (
    'informe', 'reporte', 'resumen', 'análisis', 'analisis', 'detallado',
    'rendimiento', 'productividad', 'comparar', 'evolución', 'evolucion',
    'diagnóstico', 'diagnostico', 'deuda', 'deudas', 'mensualidad',
    'facturación', 'facturacion', 'proyección', 'proyeccion',
    'semana', 'mes', 'todos', 'todas', 'general',
)

PROMPT_SISTEMA = """Eres el asistente de gestión del Centro Infantil Misael, trabajando con {nombre} (gerente).

Tienes acceso COMPLETO a toda la información del centro:

OPERATIVO:
- Agenda diaria y semanal de sesiones por profesional y sucursal
- Estado de asistencia: realizadas, permisos, faltas, cancelaciones

FINANCIERO:
- Ingresos del día, semana y mes
- Deudas y saldos de pacientes
- Mensualidades y proyectos pendientes

CLÍNICO (visión gerencial):
- Resumen de evolución de pacientes (sin entrar en detalle terapéutico privado)
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


def _pide_otra_sucursal(mensaje: str) -> bool:
    msg = mensaje.lower()
    return any(p in msg for p in (
        'otra sucursal', 'todas las sucursales', 'todas sucursales',
        'ambas sedes', 'las dos sedes', 'sede japón', 'sede japon',
        'sede camacho', 'todas las sedes', 'sede central', 'sede principal',
        'otra sede', 'en total', 'todo el centro', 'global',
    ))


def _construir_contexto(staff, mensaje: str) -> str:
    from datetime import date, timedelta
    from django.db.models import Sum, Count
    msg  = mensaje.lower()
    partes = []
    hoy  = date.today()

    suc_ids = []
    if staff and staff.sucursales:
        try:
            suc_ids = list(staff.sucursales.values_list('id', flat=True))
        except Exception:
            pass
    filtrar = bool(suc_ids) and not _pide_otra_sucursal(mensaje)
    scope   = 'su sucursal' if filtrar else 'todas las sucursales'

    partes.append(f"Fecha: {hoy:%d/%m/%Y} — Vista: {scope}")

    # Resumen operativo siempre
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
        log.error(f'[Gerente] Error operaciones: {e}')

    # Financiero
    if any(p in msg for p in ('ingreso', 'pago', 'cobro', 'caja', 'dinero', 'factur',
                               'deuda', 'saldo', 'balance', 'mensualidad', 'pendiente')):
        try:
            from facturacion.models import Pago, CuentaCorriente
            qs_p = Pago.objects.filter(fecha=hoy)
            if filtrar:
                qs_p = qs_p.filter(sucursal__id__in=suc_ids)
            hoy_total = qs_p.aggregate(t=Sum('monto'))['t'] or 0

            mes_qs = Pago.objects.filter(fecha__year=hoy.year, fecha__month=hoy.month)
            if filtrar:
                mes_qs = mes_qs.filter(sucursal__id__in=suc_ids)
            mes_total = mes_qs.aggregate(t=Sum('monto'))['t'] or 0

            partes.append(
                f"=== INGRESOS ===\n"
                f"Hoy: Bs. {float(hoy_total):.2f} | "
                f"Este mes: Bs. {float(mes_total):.2f}"
            )

            deudas = CuentaCorriente.objects.filter(
                saldo_actual__lt=0
            ).select_related('paciente').order_by('saldo_actual')[:10]
            if deudas.exists():
                lineas = [
                    f"  {c.paciente.nombre} {c.paciente.apellido}: Bs. {abs(float(c.saldo_actual)):.2f}"
                    for c in deudas if c.paciente
                ]
                partes.append("=== TOP DEUDAS ===\n" + '\n'.join(lineas))
        except Exception as e:
            log.error(f'[Gerente] Error financiero: {e}')

    # Rendimiento profesionales
    if any(p in msg for p in ('profesional', 'terapeuta', 'rendimiento', 'productividad')):
        try:
            from agenda.models import Sesion
            desde = hoy - timedelta(days=30)
            qs_r  = Sesion.objects.filter(fecha__gte=desde, estado__in=['realizada', 'realizada_retraso'])
            if filtrar:
                qs_r = qs_r.filter(sucursal__id__in=suc_ids)
            datos = qs_r.values(
                'profesional__nombre', 'profesional__apellido'
            ).annotate(total=Count('id')).order_by('-total')
            if datos:
                lineas = [
                    f"  {d['profesional__nombre']} {d['profesional__apellido']}: {d['total']} sesiones"
                    for d in datos
                ]
                partes.append("=== RENDIMIENTO PROFESIONALES (30 días) ===\n" + '\n'.join(lineas))
        except Exception as e:
            log.error(f'[Gerente] Error rendimiento: {e}')

    # Resumen clínico (sin detalle terapéutico privado)
    if any(p in msg for p in ('evaluación', 'evaluacion', 'diagnóstico', 'diagnostico',
                               'informe', 'clínico', 'clinico', 'evolución', 'evolucion')):
        try:
            from agenda.models import Evaluacion
            evals = Evaluacion.objects.order_by('-fecha')
            if filtrar:
                evals = evals.filter(sucursal__id__in=suc_ids)
            evals = evals.select_related('paciente', 'profesional')[:10]
            if evals.exists():
                lineas = [
                    f"  [{e.fecha:%d/%m/%Y}] {e.paciente.nombre if e.paciente else '—'}"
                    f" — {getattr(e, 'tipo', '') or '—'}"
                    f" — Prof: {e.profesional.nombre if e.profesional else '—'}"
                    for e in evals
                ]
                partes.append("=== EVALUACIONES RECIENTES ===\n" + '\n'.join(lineas))
        except Exception as e:
            log.error(f'[Gerente] Error clínico: {e}')

    # Semana
    if any(p in msg for p in ('semana', 'semanal')):
        try:
            from agenda.models import Sesion
            lunes  = hoy - timedelta(days=hoy.weekday())
            sabado = lunes + timedelta(days=5)
            qs_s   = Sesion.objects.filter(fecha__gte=lunes, fecha__lte=sabado)
            if filtrar:
                qs_s = qs_s.filter(sucursal__id__in=suc_ids)
            res_s = {r['estado']: r['total'] for r in qs_s.values('estado').annotate(total=Count('id'))}
            partes.append(
                f"=== SEMANA ({lunes:%d/%m} al {sabado:%d/%m}) ===\n"
                f"Programadas: {res_s.get('programada', 0)} | "
                f"Realizadas: {res_s.get('realizada', 0) + res_s.get('realizada_retraso', 0)} | "
                f"Permisos: {res_s.get('permiso', 0)} | "
                f"Faltas: {res_s.get('falta', 0)}"
            )
        except Exception as e:
            log.error(f'[Gerente] Error semana: {e}')

    return '\n\n'.join(partes) if partes else f"Fecha: {hoy:%d/%m/%Y}."


def _elegir_modelo(mensaje: str) -> tuple[str, str]:
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

            prompt = PROMPT_SISTEMA.format(
                nombre          = nombre,
                sucursal_propia = suc_prop,
                contexto        = contexto,
            )

            self.guardar_mensaje(telefono, 'user', mensaje)
            historial = self.get_historial(telefono)
            log.info(f'[Gerente] {telefono} | {nombre} | {etiqueta} | {mensaje[:50]}')

            respuesta = self.llamar_claude(
                historial=historial, system_prompt=prompt,
                modelo=modelo, max_tokens=700,
            )
            self.guardar_mensaje(telefono, 'assistant', respuesta, f'{etiqueta.lower()}-gerente')
            self.log_respuesta(telefono, respuesta)
            return respuesta

        except Exception as e:
            log.error(f'[Gerente] Error para {telefono}: {e}', exc_info=True)
            fallback = self.fallback_mensaje()
            self.guardar_mensaje(telefono, 'assistant', fallback, 'error')
            return fallback


_agente = None

def get_agente() -> AgenteGerente:
    global _agente
    if _agente is None:
        _agente = AgenteGerente()
    return _agente

def responder(telefono: str, mensaje: str, staff=None) -> str:
    return get_agente().responder(telefono, mensaje, staff=staff)