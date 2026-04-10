"""
agente/paciente.py
Cerebro del Agente Paciente del Centro Infantil Misael.
Atiende tutores que ya son pacientes registrados.
Acceso de SOLO LECTURA a la BD — notificaciones via chat interno.
"""

import os
import logging
import re
import anthropic

log = logging.getLogger('agente')

_client = None

def get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))
    return _client


PROMPT_PACIENTE = """Eres el asistente virtual del Centro Infantil Misael, especializado en atender a los tutores de pacientes que ya forman parte del centro. Tu nombre es Misael.

Hablas en español boliviano, con un tono cálido, empático y profesional. Tratas al tutor de forma cercana porque ya conoces a su hijo/a.

TU ROL:
Puedes informar sobre:
- Proximas sesiones programadas (fechas, horarios, profesional)
- Sesiones recientes y su estado
- Saldo, deudas o credito en cuenta corriente
- Pagos realizados
- Profesionales que atienden al paciente

Puedes gestionar:
- Solicitudes de permiso o ausencia justificada
- Solicitudes de cancelacion de sesion
- Peticiones especiales al profesional o al centro

IMPORTANTE:
- NO puedes agendar, cancelar ni modificar sesiones directamente en el sistema
- Cuando el tutor pide un permiso o cancelacion, confirmas que notificaras al equipo y usas la etiqueta especial
- NO compartas datos medicos confidenciales
- Responde de forma concisa (maximo 4-5 oraciones)
- No uses asteriscos ni markdown — WhatsApp los muestra como texto plano
- Usa emojis con moderacion (maximo 1-2 por mensaje)

CONTEXTO DEL PACIENTE:
{contexto}

INSTRUCCIONES PARA SOLICITUDES:
Cuando el tutor pida PERMISO para una sesion, incluye al final de tu respuesta:
[NOTIFICAR:permiso|descripcion detallada de la solicitud incluyendo fecha si la menciono]

Cuando pida CANCELAR una sesion, incluye:
[NOTIFICAR:cancelacion|descripcion detallada incluyendo fecha y motivo si los menciono]

Cuando haga una PETICION ESPECIAL al profesional o centro, incluye:
[NOTIFICAR:peticion|descripcion detallada de la peticion]

Ejemplo correcto:
"Entendido, anotare su solicitud de permiso para el martes. El equipo sera notificado. [NOTIFICAR:permiso|Permiso para sesion del martes 15/04 con Lic. Mamani — motivo: cita medica]"
"""


def construir_contexto(paciente) -> str:
    try:
        from agente.paciente_db import (
            get_info_basica, get_sesiones_proximas,
            get_sesiones_recientes, get_cuenta_corriente,
            get_profesionales_del_paciente
        )

        info      = get_info_basica(paciente)
        proximas  = get_sesiones_proximas(paciente, dias=14)
        recientes = get_sesiones_recientes(paciente, limite=3)
        cuenta    = get_cuenta_corriente(paciente)
        profs     = get_profesionales_del_paciente(paciente)

        ctx = f"PACIENTE: {info.get('nombre', '')} {info.get('apellido', '')}"
        if info.get('edad'):
            ctx += f" ({info['edad']} anios)"
        ctx += f"\nTUTOR: {info.get('nombre_tutor', '—')}\n"

        if profs:
            ctx += "\nPROFESIONALES QUE LO ATIENDEN:\n"
            for p in profs:
                ctx += f"- {p['nombre']} ({p['servicio']})\n"

        if proximas:
            ctx += "\nPROXIMAS SESIONES:\n"
            for s in proximas[:5]:
                ctx += f"- {s['fecha']} {s['dia']} a las {s['hora']} — {s['servicio']} con {s['profesional']} en {s['sucursal']}\n"
        else:
            ctx += "\nPROXIMAS SESIONES: No hay sesiones programadas en los proximos 14 dias\n"

        if recientes:
            ctx += "\nULTIMAS SESIONES:\n"
            for s in recientes:
                ctx += f"- {s['fecha']} {s['servicio']} con {s['profesional']}: {s['estado']}\n"

        if cuenta:
            ctx += "\nCUENTA CORRIENTE:\n"
            ctx += f"- Total pagado: Bs. {cuenta.get('total_pagado', 0):.2f}\n"
            ctx += f"- Total consumido: Bs. {cuenta.get('total_consumido', 0):.2f}\n"
            if cuenta.get('deuda', 0) > 0:
                ctx += f"- DEUDA PENDIENTE: Bs. {cuenta['deuda']:.2f}\n"
            elif cuenta.get('credito', 0) > 0:
                ctx += f"- CREDITO A FAVOR: Bs. {cuenta['credito']:.2f}\n"
            else:
                ctx += "- Cuenta al dia\n"

        return ctx

    except Exception as e:
        log.error(f'[Agente Paciente] Error construyendo contexto: {e}')
        return "CONTEXTO NO DISPONIBLE"


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


def procesar_notificaciones(respuesta: str, paciente) -> int:
    """
    Detecta etiquetas [NOTIFICAR:tipo|detalle] en la respuesta
    y envía notificaciones al equipo correspondiente.
    Retorna el número de notificaciones enviadas.
    """
    from agente.paciente_db import notificar_solicitud

    total = 0
    patron = r'\[NOTIFICAR:(\w+)\|([^\]]+)\]'

    for match in re.finditer(patron, respuesta):
        tipo    = match.group(1).strip()
        detalle = match.group(2).strip()

        if tipo in ('permiso', 'cancelacion', 'peticion'):
            notificados = notificar_solicitud(paciente, tipo, detalle)
            total += notificados
            log.info(f'[Agente Paciente] Notificacion {tipo} enviada a {notificados} usuarios')

    return total


def limpiar_etiquetas(texto: str) -> str:
    """Elimina las etiquetas internas antes de enviar al tutor."""
    return re.sub(r'\[NOTIFICAR:[^\]]*\]', '', texto).strip()


PALABRAS_SOLICITUD = (
    'permiso', 'permisos', 'ausencia', 'faltar', 'falta', 'no voy', 'no podre',
    'no puedo', 'cancelar', 'cancelacion', 'suspender', 'suspendida',
    'peticion', 'solicitud', 'pedir', 'necesito hablar', 'mensaje al',
    'avisar', 'avisar al', 'decirle al', 'preguntarle', 'cambiar',
)

def _elegir_modelo(mensaje: str) -> tuple[str, str]:
    """
    Retorna (modelo, etiqueta_log).
    Usa Sonnet si el mensaje parece una solicitud, Haiku si es consulta.
    """
    msg = mensaje.lower()
    if any(p in msg for p in PALABRAS_SOLICITUD):
        return 'claude-sonnet-4-6', 'Sonnet'
    return 'claude-haiku-4-5-20251001', 'Haiku'


def responder(telefono: str, mensaje_usuario: str, paciente) -> str:
    try:
        contexto = construir_contexto(paciente)
        prompt   = PROMPT_PACIENTE.format(contexto=contexto)

        guardar_mensaje(telefono, 'user', mensaje_usuario)
        historial = get_historial_db(telefono)

        modelo, etiqueta = _elegir_modelo(mensaje_usuario)
        log.info(f'[Agente Paciente] {telefono} | {paciente.nombre} {paciente.apellido} | {etiqueta}')

        response = get_client().messages.create(
            model=modelo,
            max_tokens=500,
            system=prompt,
            messages=historial,
        )

        respuesta_raw = response.content[0].text.strip()

        # Procesar notificaciones antes de limpiar
        procesar_notificaciones(respuesta_raw, paciente)

        # Limpiar etiquetas internas
        respuesta = limpiar_etiquetas(respuesta_raw)

        guardar_mensaje(telefono, 'assistant', respuesta, f'{etiqueta.lower()}-paciente')
        log.info(f'[Agente Paciente] {telefono} | {respuesta[:60]}')
        return respuesta

    except Exception as e:
        log.error(f'[Agente Paciente] Error: {e}')
        return (
            'Disculpe, tuve un problema tecnico. '
            'Por favor comuniquese directamente con nosotros:\n'
            'Sede Japon: +591 76175352\n'
            'Sede Central: +591 78633975'
        )