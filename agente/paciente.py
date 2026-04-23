"""
agente/paciente.py
Cerebro del Agente Paciente del Centro Infantil Misael.
Atiende tutores que ya son pacientes registrados.

CORRECCIONES APLICADAS:
  1. get_prompt() ahora inyecta nombre_paciente y nombre_tutor correctamente.
  2. responder() ya no duplica el mensaje del usuario en el historial enviado a Claude.
  3. Ventana de sesiones próximas ampliada de 14 a 30 días.
  4. Sesiones recientes ampliadas de 3 a 8 entradas.
  5. Contexto incluye conteo del mes actual (faltas, permisos, etc.).
  6. Contexto incluye crédito disponible (pagos_adelantados) de CuentaCorriente.
  7. Contexto incluye estadísticas por profesional (total sesiones + realizadas).
  8. Contexto distingue correctamente sesiones de mensualidad/proyecto (sin monto individual).
  9. _detectar_solicitud_pagos() y _detectar_solicitud_sesiones() ampliadas con más variantes.
  10. get_client() usa el singleton de agente_base en vez de duplicarlo.
  11. PROMPT_BASE_PACIENTE eliminado — única fuente de verdad es ConfigAgente en el admin.
  12. Fecha y hora actual de Bolivia inyectada en el contexto — corrige errores de día/hora.
  13. Sesiones de hoy que ya pasaron marcadas como "ya realizada hoy" — no aparecen como futuras.
  14. Deuda verificada con campo correcto (balance_final / saldo_actual) directamente en contexto.
"""

import logging
import re
from datetime import date, datetime
import pytz

log = logging.getLogger('agente')

# ─────────────────────────────────────────────────────────────────────────────
# Zona horaria y helpers de fecha/hora
# ─────────────────────────────────────────────────────────────────────────────

_TZ_BOLIVIA = pytz.timezone('America/La_Paz')

DIAS_ES  = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
MESES_ES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
            'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']


def _ahora_bolivia() -> datetime:
    """Retorna el datetime actual en zona horaria de Bolivia (UTC-4)."""
    return datetime.now(_TZ_BOLIVIA)


def _encabezado_fecha_hora() -> str:
    """
    Bloque de fecha y hora actual que va al inicio de cada contexto.
    Permite que Claude sepa exactamente cuándo es 'ahora' en Bolivia.
    """
    ahora   = _ahora_bolivia()
    dia_sem = DIAS_ES[ahora.weekday()]
    mes_nom = MESES_ES[ahora.month - 1]
    return (
        f"FECHA Y HORA ACTUAL (Bolivia, UTC-4):\n"
        f"{dia_sem} {ahora.day} de {mes_nom} de {ahora.year} — {ahora.strftime('%H:%M')} hs\n"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Cliente Anthropic — usa el singleton de agente_base (sin duplicar)
# ─────────────────────────────────────────────────────────────────────────────

def get_client():
    from agente.agente_base import get_client as _gc
    return _gc()


# ─────────────────────────────────────────────────────────────────────────────
# Prompt — única fuente de verdad: ConfigAgente en el admin
# ─────────────────────────────────────────────────────────────────────────────

# Prompt de emergencia — solo si ConfigAgente no existe o falla.
# Mantenerlo mínimo; el prompt real vive en el admin.
_PROMPT_FALLBACK = """Eres Misael, el asistente virtual del Centro Infantil Misael.
Atendés a tutores que ya son pacientes registrados.

DATOS DEL PACIENTE:
{contexto}

Si el contexto dice CONTEXTO NO DISPONIBLE, no entregués ningún dato personal.

{modo_conversacion}
"""


def get_prompt(
    contexto: str = '',
    modo_conversacion: str = '',
    nombre_paciente: str = '',
    nombre_tutor: str = '',
) -> str:
    """
    Lee el prompt desde ConfigAgente en la BD.
    Si no existe o falla, usa _PROMPT_FALLBACK.
    Inyecta contexto, modo_conversacion, nombre_paciente y nombre_tutor.
    """
    try:
        from agente.models import ConfigAgente
        config = ConfigAgente.objects.filter(agente='paciente', activo=True).first()
        prompt = config.prompt if (config and config.prompt) else _PROMPT_FALLBACK
    except Exception:
        prompt = _PROMPT_FALLBACK

    try:
        return prompt.format(
            contexto=contexto,
            modo_conversacion=modo_conversacion,
            nombre_paciente=nombre_paciente,
            nombre_tutor=nombre_tutor,
        )
    except KeyError:
        # Si el prompt tiene variables desconocidas, devolver tal cual con lo que se puede
        return prompt.replace('{contexto}', contexto).replace('{modo_conversacion}', modo_conversacion)


# ─────────────────────────────────────────────────────────────────────────────
# Modo conversación — instrucción de apertura según historial
# ─────────────────────────────────────────────────────────────────────────────

def _modo_conversacion(historial: list) -> str:
    """
    Genera la instrucción de apertura según si hay historial previo o no.
    Recibe el historial SIN el mensaje actual del usuario.
    """
    if not historial:
        return (
            "Es el PRIMER mensaje de esta persona. Saludá de forma breve y cálida, "
            "usando su nombre si lo tenés. Una sola frase de bienvenida, luego andá "
            "directo a lo que necesita. Ejemplo: 'Hola [nombre]! Claro, te cuento...' "
            "NO hagás un párrafo de presentación. NO digás 'Soy Misael, tu asistente...'"
        )
    else:
        return (
            "Ya existe conversación previa con esta persona. NO saludes, NO te presentes, "
            "NO digás 'Hola' ni 'Soy Misael'. Respondé DIRECTAMENTE como si fuera la "
            "continuación natural de una charla. Si el mensaje anterior fue un recordatorio "
            "automático y el tutor responde, recogé el hilo de forma natural. "
            "NUNCA reiniciés el saludo aunque hayan pasado horas."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Construcción del contexto
# ─────────────────────────────────────────────────────────────────────────────

def construir_contexto(
    paciente,
    pedir_pagos: dict = None,
    pedir_sesiones: dict = None,
    cual_tutor: str = 'tutor_1',
) -> str:
    """
    Construye el bloque de contexto del paciente para el agente.
    Incluye toda la información que el tutor ve en la app web,
    excepto notas clínicas internas y observaciones del staff.

    cual_tutor: 'tutor_1' o 'tutor_2' — indica qué número envió el mensaje.
    pedir_pagos: dict con claves 'mes', 'anio', 'todos' para historial de pagos.
    pedir_sesiones: dict con claves 'mes', 'anio', 'todos' para historial de sesiones.
    """
    try:
        from agente.paciente_db import (
            get_info_basica,
            get_sesiones_proximas,
            get_sesiones_recientes,
            get_cuenta_corriente,
            get_profesionales_del_paciente,
            get_deudas_detalle,
            get_pagos_detalle,
            get_proyectos,
            get_mensualidades,
            get_sesiones_completo,
            get_conteo_sesiones_mes_actual,
        )

        info          = get_info_basica(paciente)
        proximas      = get_sesiones_proximas(paciente, dias=30)   # FIX: antes 14 días
        recientes     = get_sesiones_recientes(paciente, limite=8)  # FIX: antes 3
        cuenta        = get_cuenta_corriente(paciente)
        profs         = get_profesionales_del_paciente(paciente)
        proyectos     = get_proyectos(paciente)
        mensualidades = get_mensualidades(paciente)
        conteo_mes    = get_conteo_sesiones_mes_actual(paciente)

        # ── Fecha y hora actual (primera línea del contexto) ──────────────────
        # Claude no tiene acceso al reloj. Sin este dato, adivina el día y la
        # hora, y comete errores al hablar de sesiones pasadas/futuras.
        ctx = _encabezado_fecha_hora() + "\n"

        # ── Encabezado del paciente ───────────────────────────────────────────
        ctx += f"PACIENTE: {info.get('nombre', '')} {info.get('apellido', '')}"
        if info.get('edad'):
            ctx += f" ({info['edad']} años)"

        # ── Identificar qué tutor escribe ─────────────────────────────────────
        nombre_tutor_principal = info.get('nombre_tutor', '—')
        nombre_tutor_2         = info.get('nombre_tutor_2', '')

        if cual_tutor == 'tutor_2':
            nombre_quien_escribe = nombre_tutor_2 or 'Tutor secundario'
            ctx += f"\nTUTOR PRINCIPAL: {nombre_tutor_principal}"
            ctx += f"\nQUIEN ESCRIBE AHORA: {nombre_quien_escribe} (tutor secundario registrado)"
            ctx += (
                "\n⚠️ IMPORTANTE: Quien escribe es el tutor SECUNDARIO del paciente. "
                "Dirigite por su nombre si lo tenés, o usá un saludo neutro. "
                "Tiene el mismo acceso que el tutor principal."
            )
        else:
            ctx += f"\nTUTOR: {nombre_tutor_principal}"
            if nombre_tutor_2:
                ctx += f" (tutor secundario registrado: {nombre_tutor_2})"
        ctx += "\n"

        # ── Profesionales ─────────────────────────────────────────────────────
        if profs:
            ctx += "\nPROFESIONALES QUE LO ATIENDEN:\n"
            for p in profs:
                servicios_str = ', '.join(p['servicios']) if p['servicios'] else '—'
                ctx += (
                    f"- {p['nombre']} ({p['especialidad']}) | Servicio: {servicios_str} | "
                    f"Sesiones totales: {p['total_sesiones']} | Realizadas: {p['sesiones_realizadas']}"
                )
                if p['proxima_sesion']:
                    ps = p['proxima_sesion']
                    ctx += f" | Próxima: {ps['fecha']} {ps['hora']} en {ps['sucursal']}"
                ctx += "\n"

        # ── Próximas sesiones (30 días) ───────────────────────────────────────
        # Separar: las de hoy cuya hora ya pasó vs las genuinamente futuras.
        # Esto evita que el agente hable en futuro de sesiones que ya ocurrieron.
        proximas_futuras     = [s for s in proximas if not s.get('ya_paso_hoy')]
        proximas_pasadas_hoy = [s for s in proximas if s.get('ya_paso_hoy')]

        if proximas_pasadas_hoy:
            ctx += "\nSESIONES DE HOY YA REALIZADAS (su horario ya pasó — hablar en pasado):\n"
            for s in proximas_pasadas_hoy:
                tipo_label = ''
                if s['tipo_sesion'] == 'mensualidad':
                    tipo_label = ' [Mensualidad]'
                elif s['tipo_sesion'] == 'proyecto/evaluacion':
                    tipo_label = ' [Proyecto/Evaluacion]'
                ctx += (
                    f"- ID:{s['id']} | HOY {s['hora']}-{s['hora_fin']}"
                    f" — {s['servicio']} con {s['profesional']}"
                    f" en {s['sucursal']}{tipo_label}\n"
                )

        if proximas_futuras:
            ctx += "\nPROXIMAS SESIONES (próximos 30 días — incluye ID para solicitudes):\n"
            for s in proximas_futuras[:12]:
                tipo_label = ''
                if s['tipo_sesion'] == 'mensualidad':
                    tipo_label = ' [Mensualidad]'
                elif s['tipo_sesion'] == 'proyecto/evaluacion':
                    tipo_label = ' [Proyecto/Evaluacion]'

                ctx += (
                    f"- ID:{s['id']} | {s['fecha']} {s['dia']} {s['hora']}"
                    f" — {s['servicio']} con {s['profesional']}"
                    f" en {s['sucursal']}{tipo_label}"
                )
                if s['monto'] is not None and s['monto'] > 0:
                    ctx += f" | Bs. {s['monto']:.0f}"
                ctx += "\n"
        else:
            ctx += "\nPROXIMAS SESIONES: No hay sesiones programadas próximamente.\n"

        # ── Últimas sesiones (con estado) ─────────────────────────────────────
        if recientes:
            ctx += "\nULTIMAS SESIONES:\n"
            for s in recientes:
                ctx += f"- {s['fecha']} {s['dia']} {s['hora']} | {s['servicio']} con {s['profesional']} | {s['estado']}"
                if s['tipo_sesion'] == 'mensualidad':
                    ctx += " [Mensualidad]"
                elif s['tipo_sesion'] == 'proyecto/evaluacion':
                    ctx += " [Proyecto]"
                if s['monto'] is not None and s['monto'] > 0:
                    ctx += f" | Bs. {s['monto']:.0f}"
                if s['minutos_retraso']:
                    ctx += f" ({s['minutos_retraso']} min de retraso)"
                if s['reprogramada_al']:
                    ctx += f" → reprogramada al {s['reprogramada_al']}"
                ctx += "\n"

        # ── Conteo del mes actual ─────────────────────────────────────────────
        if conteo_mes and conteo_mes.get('total', 0) > 0:
            hoy = date.today()
            MESES = ['Enero','Febrero','Marzo','Abril','Mayo','Junio',
                     'Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre']
            mes_nombre = MESES[hoy.month - 1]
            ctx += f"\nRESUMEN SESIONES {mes_nombre.upper()} {hoy.year}:\n"
            ctx += (
                f"Total: {conteo_mes['total']} | "
                f"Realizadas: {conteo_mes['realizadas']} | "
                f"Programadas: {conteo_mes['programadas']} | "
                f"Permisos: {conteo_mes['permisos']} | "
                f"Faltas: {conteo_mes['faltas']} | "
                f"Canceladas: {conteo_mes['canceladas']} | "
                f"Reprogramadas: {conteo_mes['reprogramadas']}\n"
            )

        # ── Proyectos / Evaluaciones ──────────────────────────────────────────
        if proyectos:
            ctx += "\nEVALUACIONES Y PROYECTOS:\n"
            for p in proyectos:
                ctx += (
                    f"- [{p['estado']}] {p['nombre']} ({p['tipo']}) | "
                    f"{p['servicio']} con {p['profesional']} | "
                    f"{p['sucursal']} | Inicio: {p['fecha_inicio']}"
                )
                if p['fecha_fin_real'] != '—':
                    ctx += f" | Fin: {p['fecha_fin_real']}"
                elif p['fecha_fin_est'] != '—':
                    ctx += f" | Fin estimado: {p['fecha_fin_est']}"
                ctx += f"\n  Costo total: Bs.{p['costo_total']:.0f} | Pagado: Bs.{p['pagado']:.0f} | Saldo: Bs.{p['saldo']:.0f}"
                if p['informe_entregado']:
                    ctx += f"\n  Informe: Entregado el {p['fecha_informe']}"
                    if p['tiene_informe_digital']:
                        ctx += " (informe digital disponible en neuromisael.com)"
                else:
                    ctx += "\n  Informe: Pendiente de entrega (evaluaciones anteriores a abril 2026 — consultar en el centro)"
                s = p['sesiones']
                ctx += (
                    f"\n  Sesiones: {s['total']} total | "
                    f"{s['realizadas']} realizadas | "
                    f"{s['programadas']} programadas"
                )
                if s['permisos']:
                    ctx += f" | {s['permisos']} permisos"
                if s['faltas']:
                    ctx += f" | {s['faltas']} faltas"
                ctx += "\n"

        # ── Mensualidades ─────────────────────────────────────────────────────
        if mensualidades:
            ctx += "\nMENSUALIDADES:\n"
            for m in mensualidades:
                ctx += (
                    f"- [{m['estado']}] {m['periodo']} | "
                    f"{m['sucursal']} | "
                    f"Costo: Bs.{m['costo_mensual']:.0f} | "
                    f"Pagado: Bs.{m['pagado']:.0f} | "
                    f"Saldo: Bs.{m['saldo']:.0f}\n"
                )
                if m['servicios']:
                    ctx += f"  Servicios incluidos: {', '.join(m['servicios'])}\n"
                s = m['sesiones']
                ctx += (
                    f"  Sesiones: {s['total']} total | "
                    f"{s['realizadas']} realizadas | "
                    f"{s['programadas']} programadas"
                )
                if s['permisos']:
                    ctx += f" | {s['permisos']} permisos"
                if s['faltas']:
                    ctx += f" | {s['faltas']} faltas"
                ctx += "\n"

        # ── Cuenta corriente ──────────────────────────────────────────────────
        if cuenta:
            ctx += "\nCUENTA CORRIENTE:\n"
            ctx += f"- Consumo total (realizado): Bs. {cuenta.get('consumo_total', 0):.0f}\n"
            ctx += f"- Total pagado: Bs. {cuenta.get('pagado_total', 0):.0f}\n"

            balance = cuenta.get('balance_final', 0)
            if balance < 0:
                ctx += f"- DEUDA PENDIENTE: Bs. {abs(balance):.0f}\n"
                # Detalle de deuda
                deudas = get_deudas_detalle(paciente)
                if deudas.get('sesiones'):
                    ctx += "\nDETALLE DEUDA — SESIONES INDIVIDUALES:\n"
                    for s in deudas['sesiones'][:10]:
                        ctx += (
                            f"  · {s['fecha']} | {s['descripcion']} | "
                            f"Costo: Bs.{s['costo']:.0f} | "
                            f"Pagado: Bs.{s['pagado']:.0f} | "
                            f"Debe: Bs.{s['saldo']:.0f}"
                            f"{' (sesión futura)' if s['es_futura'] else ''}\n"
                        )
                    if len(deudas['sesiones']) > 10:
                        ctx += f"  ... y {len(deudas['sesiones']) - 10} sesiones más con deuda\n"
                if deudas.get('proyectos'):
                    ctx += "\nDETALLE DEUDA — PROYECTOS/EVALUACIONES:\n"
                    for p in deudas['proyectos']:
                        ctx += (
                            f"  · {p['descripcion']} | {p['estado']} | "
                            f"Costo: Bs.{p['costo']:.0f} | "
                            f"Pagado: Bs.{p['pagado']:.0f} | "
                            f"Debe: Bs.{p['saldo']:.0f}\n"
                        )
                if deudas.get('mensualidades'):
                    ctx += "\nDETALLE DEUDA — MENSUALIDADES:\n"
                    for m in deudas['mensualidades']:
                        ctx += (
                            f"  · {m['descripcion']} | {m['estado']} | "
                            f"Costo: Bs.{m['costo']:.0f} | "
                            f"Pagado: Bs.{m['pagado']:.0f} | "
                            f"Debe: Bs.{m['saldo']:.0f}\n"
                        )
            elif balance > 0:
                ctx += f"- CREDITO A FAVOR: Bs. {balance:.0f}\n"
            else:
                ctx += "- Cuenta al día (sin deuda ni crédito)\n"

            # Crédito disponible (pagos adelantados sin consumir) — FIX nuevo campo
            credito = cuenta.get('credito_disponible', 0)
            if credito > 0:
                ctx += f"- CREDITO DISPONIBLE (adelantos sin usar): Bs. {credito:.0f}\n"
                ctx += "  (Este monto se aplica automáticamente a futuras sesiones, no requiere pago adicional)\n"

        # ── Historial de sesiones por período (si el tutor lo pidió) ─────────
        if pedir_sesiones:
            datos_ses = get_sesiones_completo(
                paciente,
                mes=pedir_sesiones.get('mes'),
                anio=pedir_sesiones.get('anio'),
                todos=pedir_sesiones.get('todos', False),
            )
            if datos_ses.get('sesiones'):
                if pedir_sesiones.get('todos'):
                    periodo_label = 'HISTORIAL COMPLETO'
                else:
                    MESES = ['Enero','Febrero','Marzo','Abril','Mayo','Junio',
                             'Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre']
                    m_num = pedir_sesiones.get('mes', date.today().month)
                    a_num = pedir_sesiones.get('anio', date.today().year)
                    periodo_label = f"{MESES[m_num - 1].upper()} {a_num}"
                ctx += f"\nHISTORIAL DE SESIONES — {periodo_label}:\n"
                c = datos_ses['conteo']
                ctx += (
                    f"Total: {datos_ses['total']} | "
                    f"Realizadas: {c.get('realizada', 0) + c.get('realizada_retraso', 0)} | "
                    f"Con retraso: {c.get('realizada_retraso', 0)} | "
                    f"Programadas: {c.get('programada', 0)} | "
                    f"Permisos: {c.get('permiso', 0)} | "
                    f"Faltas: {c.get('falta', 0)} | "
                    f"Canceladas: {c.get('cancelada', 0)} | "
                    f"Reprogramadas: {c.get('reprogramada', 0)}\n"
                )
                for s in datos_ses['sesiones'][:25]:
                    ctx += f"- {s['fecha']} {s['dia']} {s['hora']} | {s['servicio']} con {s['profesional']} | {s['estado']}"
                    if s['tipo_sesion'] != 'sesion_normal':
                        ctx += f" [{s['tipo_sesion']}]"
                    if s['monto'] is not None and s['monto'] > 0:
                        ctx += f" | Bs.{s['monto']:.0f}"
                    if s['minutos_retraso']:
                        ctx += f" ({s['minutos_retraso']} min de retraso)"
                    if s['fecha_reprogramada']:
                        ctx += f" → reprogramada al {s['fecha_reprogramada']}"
                    ctx += "\n"
                if len(datos_ses['sesiones']) > 25:
                    ctx += f"  ... y {len(datos_ses['sesiones']) - 25} sesiones más. Ver detalle en neuromisael.com\n"
            else:
                ctx += "\nHISTORIAL DE SESIONES: No se encontraron sesiones para el período indicado.\n"

        # ── Historial de pagos por período (si el tutor lo pidió) ─────────────
        if pedir_pagos:
            pagos = get_pagos_detalle(
                paciente,
                mes=pedir_pagos.get('mes'),
                anio=pedir_pagos.get('anio'),
                todos=pedir_pagos.get('todos', False),
            )
            if pagos.get('pagos'):
                if pedir_pagos.get('todos'):
                    periodo_label = 'TODOS LOS PERÍODOS'
                else:
                    MESES = ['Enero','Febrero','Marzo','Abril','Mayo','Junio',
                             'Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre']
                    m_num = pedir_pagos.get('mes', date.today().month)
                    a_num = pedir_pagos.get('anio', date.today().year)
                    periodo_label = f"{MESES[m_num - 1].upper()} {a_num}"
                ctx += f"\nHISTORIAL DE PAGOS — {periodo_label}:\n"
                ctx += (
                    f"Total pagado: Bs.{pagos['total_pagado']:.0f} | "
                    f"Devoluciones: Bs.{pagos['total_devoluciones']:.0f} | "
                    f"Neto: Bs.{pagos['total_neto']:.0f}\n"
                )
                for p in pagos['pagos'][:15]:
                    tipo = "DEVOLUCION" if p['es_devolucion'] else "Pago"
                    ctx += (
                        f"- {p['fecha']} | Recibo: {p['recibo']} | "
                        f"{p['metodo']} | {p['concepto']} | "
                        f"{tipo}: Bs.{p['monto']:.0f}\n"
                    )
                if len(pagos['pagos']) > 15:
                    ctx += f"  ... y {len(pagos['pagos']) - 15} pagos más. Ver detalle en neuromisael.com\n"
            else:
                ctx += "\nHISTORIAL DE PAGOS: No se encontraron pagos para el período indicado.\n"

        return ctx

    except Exception as e:
        log.error(f'[Agente Paciente] Error construyendo contexto: {e}', exc_info=True)
        return "CONTEXTO NO DISPONIBLE"


# ─────────────────────────────────────────────────────────────────────────────
# Historial y persistencia
# ─────────────────────────────────────────────────────────────────────────────

def get_historial_db(telefono: str, limite: int = 15) -> list:
    try:
        from agente.models import ConversacionAgente
        mensajes = ConversacionAgente.objects.filter(
            agente='paciente', telefono=telefono,
        ).order_by('-creado')[:limite]
        return [
            {'role': m.rol, 'content': m.contenido}
            for m in reversed(list(mensajes))
        ]
    except Exception as e:
        log.error(f'[Agente Paciente] Error obteniendo historial: {e}')
        return []


def guardar_mensaje(telefono: str, rol: str, contenido: str, modelo: str = ''):
    try:
        from agente.models import ConversacionAgente
        ConversacionAgente.objects.create(
            agente='paciente',
            telefono=telefono,
            rol=rol,
            contenido=contenido,
            modelo_usado=modelo,
        )
    except Exception as e:
        log.error(f'[Agente Paciente] Error guardando mensaje: {e}')


# ─────────────────────────────────────────────────────────────────────────────
# Procesamiento de etiquetas de notificación
# ─────────────────────────────────────────────────────────────────────────────

def procesar_notificaciones(respuesta: str, paciente) -> int:
    from agente.paciente_db import notificar_solicitud

    total  = 0
    patron = r'\[NOTIFICAR:(\w+)\|([^\]]+)\]'

    for match in re.finditer(patron, respuesta):
        tipo    = match.group(1).strip()
        detalle = match.group(2).strip()

        if tipo in ('permiso', 'cancelacion', 'reprogramacion',
                    'peticion_profesional', 'peticion_centro', 'aviso_pago'):
            notificados = notificar_solicitud(paciente, tipo, detalle)
            total += notificados
            log.info(f'[Agente Paciente] Notificación {tipo} enviada a {notificados} usuarios')

    return total


def limpiar_etiquetas(texto: str) -> str:
    return re.sub(r'\[NOTIFICAR:[^\]]*\]', '', texto).strip()


# ─────────────────────────────────────────────────────────────────────────────
# Selección de modelo
# ─────────────────────────────────────────────────────────────────────────────

PALABRAS_SOLICITUD = (
    'permiso', 'permisos', 'ausencia', 'faltar', 'falta', 'no voy', 'no podre',
    'no puedo', 'cancelar', 'cancelacion', 'suspender', 'suspendida',
    'reprogramar', 'reprogramacion', 'cambiar dia', 'otro dia',
    'peticion', 'solicitud', 'necesito hablar', 'mensaje al',
    'avisar', 'decirle al', 'preguntarle al', 'evaluacion nueva',
    'nueva evaluacion', 'quiero empezar', 'agregar terapia', 'nuevo servicio',
    'cambiar horario', 'cambiar profesional', 'constancia', 'certificado',
    'medicacion', 'medicamento', 'medicacion cambio',
)


def _elegir_modelo(mensaje: str) -> tuple[str, str]:
    msg = mensaje.lower()
    if any(p in msg for p in PALABRAS_SOLICITUD):
        return 'claude-sonnet-4-6', 'Sonnet'
    return 'claude-haiku-4-5-20251001', 'Haiku'


# ─────────────────────────────────────────────────────────────────────────────
# Detección de solicitudes de datos ampliada
# ─────────────────────────────────────────────────────────────────────────────

def _detectar_solicitud_pagos(mensaje: str) -> dict | None:
    """
    Detecta si el tutor pide ver sus pagos y en qué período.
    Retorna dict con mes/anio/todos, o None si no aplica.
    """
    msg = mensaje.lower()

    # Palabras clave ampliadas
    palabras_pago = (
        'pago', 'pagos', 'recibo', 'recibos', 'historial', 'devolucion',
        'devoluciones', 'pagado', 'pague', 'pague', 'abone', 'abono',
        'cuanto pague', 'cuánto pagué', 'mis pagos', 'ver pagos',
        'comprobante', 'transferencia', 'qr',
    )
    if not any(p in msg for p in palabras_pago):
        return None

    if any(p in msg for p in ('todos', 'todo', 'siempre', 'historial completo', 'todos los pagos', 'todo el historial')):
        return {'todos': True}

    MESES = {
        'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4,
        'mayo': 5, 'junio': 6, 'julio': 7, 'agosto': 8,
        'septiembre': 9, 'octubre': 10, 'noviembre': 11, 'diciembre': 12,
    }
    mes_encontrado = None
    for nombre, num in MESES.items():
        if nombre in msg:
            mes_encontrado = num
            break

    anio_encontrado = None
    match_anio = re.search(r'\b(202[0-9])\b', msg)
    if match_anio:
        anio_encontrado = int(match_anio.group(1))

    hoy = date.today()
    return {
        'mes':  mes_encontrado or hoy.month,
        'anio': anio_encontrado or hoy.year,
        'todos': False,
    }


def _detectar_solicitud_sesiones(mensaje: str) -> dict | None:
    """
    Detecta si el tutor pide ver historial de sesiones y en qué período.
    Retorna dict con mes/anio/todos, o None si no aplica.
    """
    msg = mensaje.lower()

    # Palabras clave ampliadas para capturar más variantes naturales
    palabras_sesion = (
        'historial de sesiones', 'mis sesiones', 'sesiones realizadas',
        'sesiones que tuve', 'cuantas sesiones', 'cuántas sesiones',
        'sesiones del mes', 'sesiones pasadas', 'todas mis sesiones',
        'sesiones de enero', 'sesiones de febrero', 'sesiones de marzo',
        'sesiones de abril', 'sesiones de mayo', 'sesiones de junio',
        'sesiones de julio', 'sesiones de agosto', 'sesiones de septiembre',
        'sesiones de octubre', 'sesiones de noviembre', 'sesiones de diciembre',
        'faltas que tuve', 'permisos que tuve', 'cuantas faltas', 'cuántas faltas',
        'cuantos permisos', 'cuántos permisos',
        'mis terapias', 'terapias del mes', 'clases del mes',
        'cuantas terapias', 'cuántas terapias',
        'ver sesiones', 'mis clases', 'asistencia',
        'falte', 'falté', 'cuándo falté', 'cuando falte',
    )
    if not any(p in msg for p in palabras_sesion):
        return None

    if any(p in msg for p in ('todas', 'todo', 'siempre', 'historial completo', 'todas mis sesiones', 'todo el historial')):
        return {'todos': True}

    MESES = {
        'enero': 1, 'febrero': 2, 'marzo': 3, 'abril': 4,
        'mayo': 5, 'junio': 6, 'julio': 7, 'agosto': 8,
        'septiembre': 9, 'octubre': 10, 'noviembre': 11, 'diciembre': 12,
    }
    mes_encontrado = None
    for nombre, num in MESES.items():
        if nombre in msg:
            mes_encontrado = num
            break

    anio_encontrado = None
    match_anio = re.search(r'\b(202[0-9])\b', msg)
    if match_anio:
        anio_encontrado = int(match_anio.group(1))

    hoy = date.today()
    return {
        'mes':  mes_encontrado or hoy.month,
        'anio': anio_encontrado or hoy.year,
        'todos': False,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Función principal de respuesta
# ─────────────────────────────────────────────────────────────────────────────

def responder(
    telefono: str,
    mensaje_usuario: str,
    paciente,
    cual_tutor: str = 'tutor_1',
) -> str:
    """
    Procesa un mensaje del tutor y retorna la respuesta del agente.

    Flujo corregido:
      1. Recuperar historial PREVIO (antes de guardar el mensaje actual).
      2. Determinar modo de conversación con ese historial previo.
      3. Construir contexto.
      4. Guardar el mensaje del usuario en BD.
      5. Construir el historial para Claude = historial_previo + mensaje_actual.
      6. Llamar a Claude.
      7. Procesar notificaciones y guardar respuesta.
    """
    try:
        # ── 1. Historial previo (antes de agregar el mensaje actual) ───────────
        historial_previo = get_historial_db(telefono)

        # ── 2. Modo conversación basado en historial previo ────────────────────
        modo = _modo_conversacion(historial_previo)

        # ── 3. Detección de solicitudes de datos ───────────────────────────────
        solicitud_pagos    = _detectar_solicitud_pagos(mensaje_usuario)
        solicitud_sesiones = _detectar_solicitud_sesiones(mensaje_usuario)

        # ── 4. Construir contexto ──────────────────────────────────────────────
        contexto = construir_contexto(
            paciente,
            pedir_pagos=solicitud_pagos,
            pedir_sesiones=solicitud_sesiones,
            cual_tutor=cual_tutor,
        )

        # ── 5. Construir prompt ────────────────────────────────────────────────
        nombre_paciente = f"{paciente.nombre} {paciente.apellido}".strip()
        info = {'nombre_tutor': '', 'nombre_tutor_2': ''}
        try:
            from agente.paciente_db import get_info_basica
            info = get_info_basica(paciente)
        except Exception:
            pass

        if cual_tutor == 'tutor_2':
            nombre_tutor = info.get('nombre_tutor_2') or info.get('nombre_tutor', '')
        else:
            nombre_tutor = info.get('nombre_tutor', '')

        prompt = get_prompt(
            contexto=contexto,
            modo_conversacion=modo,
            nombre_paciente=nombre_paciente,
            nombre_tutor=nombre_tutor,
        )

        # ── 6. Guardar mensaje del usuario en BD ───────────────────────────────
        guardar_mensaje(telefono, 'user', mensaje_usuario)

        # ── 7. Historial para Claude = previo + mensaje actual ─────────────────
        # FIX: no recuperar de BD de nuevo (evita duplicación).
        historial_claude = historial_previo + [{'role': 'user', 'content': mensaje_usuario}]

        # ── 8. Seleccionar modelo y llamar a Claude ────────────────────────────
        modelo, etiqueta = _elegir_modelo(mensaje_usuario)
        log.info(f'[Agente Paciente] {telefono} | {paciente.nombre} {paciente.apellido} | {etiqueta}')

        response = get_client().messages.create(
            model=modelo,
            max_tokens=600,
            system=prompt,
            messages=historial_claude,
        )

        respuesta_raw = response.content[0].text.strip()

        # ── 9. Procesar notificaciones y limpiar etiquetas ─────────────────────
        procesar_notificaciones(respuesta_raw, paciente)
        respuesta = limpiar_etiquetas(respuesta_raw)

        # ── 10. Guardar respuesta del asistente ────────────────────────────────
        guardar_mensaje(telefono, 'assistant', respuesta, f'{etiqueta.lower()}-paciente')
        log.info(f'[Agente Paciente] {telefono} | {respuesta[:80]}')
        return respuesta

    except Exception as e:
        log.error(f'[Agente Paciente] Error para {telefono}: {e}', exc_info=True)
        fallback = (
            'Disculpe, tuve un problema técnico. '
            'Por favor comuníquese directamente con nosotros:\n'
            'Sede Japón: +591 76175352\n'
            'Sede Camacho: +591 78633975'
        )
        try:
            guardar_mensaje(telefono, 'assistant', fallback, 'error')
        except Exception:
            pass
        return fallback