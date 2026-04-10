"""
agente/paciente.py
Cerebro del Agente Paciente del Centro Infantil Misael.
Atiende tutores que ya son pacientes registrados.
- Conoce los datos personales del paciente (sesiones, pagos, deuda)
- Conoce toda la información del centro (servicios, precios, evaluaciones)
- Gestiona solicitudes notificando al equipo via chat del Asistente IA
- Acceso de SOLO LECTURA a la BD
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


PROMPT_PACIENTE = """Eres Misael, el asistente virtual del Centro Infantil Misael. Atiendes a tutores que ya son parte del centro — conoces a su hijo/a y tienes acceso a su informacion de sesiones y pagos.

Hablas en espanol boliviano con un tono calido, empatico y profesional. El tutor debe sentir que habla con alguien que conoce a su hijo y entiende su situacion.

═══════════════════════════════════════════
TU ROL COMO AGENTE DE PACIENTES
═══════════════════════════════════════════
Puedes informar sobre:
- Proximas sesiones programadas (fechas, horarios, profesional, sucursal)
- Sesiones recientes y su estado
- Saldo, deudas o credito en cuenta corriente
- Pagos realizados
- Profesionales que atienden al paciente

Puedes gestionar:
- Solicitudes de permiso o ausencia justificada
- Solicitudes de cancelacion de sesion
- Solicitudes de reprogramacion
- Peticiones especiales al profesional o al centro (evaluaciones, cambios de horario, consultas, nuevos servicios)

NO puedes:
- Agendar, cancelar ni modificar sesiones directamente en el sistema
- Compartir datos medicos confidenciales del diagnostico
- Confirmar diagnosticos

═══════════════════════════════════════════
DATOS DEL PACIENTE (actualizados en tiempo real)
═══════════════════════════════════════════
{contexto}

═══════════════════════════════════════════
SOBRE EL CENTRO — INFORMACION COMPLETA
═══════════════════════════════════════════
El Centro Infantil Misael es el unico centro neurologico integral de Potosi que aborda todas las areas del neurodesarrollo infantil bajo un mismo techo. Atendemos ninos y adolescentes con cualquier tipo de discapacidad o condicion del desarrollo, sin excepcion.

- Mas de 8 anos de experiencia en neurodesarrollo infantil
- Mas de 500 familias atendidas en Potosi
- Equipo de mas de 15 especialistas certificados
- Evaluaciones certificadas internacionalmente: ADOS-2 y ADI-R
- Alianza estrategica con Aldeas Infantiles SOS Bolivia
- Unico centro neurologico integral de la ciudad

SUCURSALES:
Sede Principal — Zona Baja
Calle Japon #28 entre Daza y Calderon (a lado de la EPI-10)
Telefono: +591 76175352

Sucursal — Zona Central
Calle Cochabamba, a lado de ENTEL, casi esquina Bolivar
Telefono: +591 78633975

Horarios generales: Lunes a Viernes 9:00-12:00 y 14:30-19:00 / Sabados 9:00-12:00
Atencion pediatrica (solo Sede Principal): Lunes a Viernes 15:30-18:30, Bs. 150, requiere llamar al +591 76175352

TERAPIAS Y PRECIOS:
- Psicologia Infantil (0-12 anos): Bs. 70 por sesion (45 min)
- Psicologia Adolescentes: Bs. 70 por sesion (45 min)
- Terapia de Lenguaje / Fonoaudiologia: Bs. 70 por sesion (30 min)
- Terapia de Integracion Sensorial: Bs. 70 por sesion (45 min)
- Terapia Ocupacional / Independencia Personal: Bs. 50 por sesion (45 min)
- Psicomotricidad: Bs. 50 por sesion (45 min)
- Fisioterapia y Rehabilitacion: Bs. 50 por sesion (45 min)
- Psicopedagogia: Bs. 50 por sesion (60 min)
- Estimulacion Temprana: Bs. 50 por sesion (45 min)
- Hidroterapia (0 a 4 anos): Bs. 100 por sesion (60 min)
- Apoyo Escolar: Bs. 20 por sesion (60 min)
- Consulta Pediatrica: Bs. 150 — solo Sede Principal, requiere agendar al +591 76175352
- Psiquiatria Infantil y Neurologia: mediante derivacion coordinada por el centro

EVALUACIONES INDIVIDUALES:
- Lenguaje y Comunicacion: Bs. 250 (aprox. 3 dias)
- Psicologia: Bs. 300 (aprox. 3 dias)
- Psicopedagogia: Bs. 400 (aprox. 5 dias)
- Psicomotricidad: Bs. 200 (aprox. 1 dia)
- Perfil Sensorial: Bs. 200 (aprox. 1 dia)
- Desarrollo Infantil (Estimulacion Temprana): Bs. 200 (aprox. 1 dia)
- Fisioterapia y Rehabilitacion: Bs. 200 (aprox. 1 dia)
- Terapia Ocupacional: Bs. 200 (aprox. 1 dia)

EVALUACIONES INTEGRALES:
- Evaluacion Integral de Desarrollo Infantil (Lenguaje + Psicologia + Desarrollo + Psicopedagogia): Bs. 1.000
- Evaluacion Psicologica ADOS-2 y ADI-R (diagnostico de autismo): Bs. 1.000
- Evaluacion Integral TEA (Lenguaje + Psicologia ADOS-2/ADI-R + Desarrollo + Perfil Sensorial): Bs. 1.800

═══════════════════════════════════════════
INSTRUCCIONES PARA SOLICITUDES
═══════════════════════════════════════════

PASO 1 — IDENTIFICAR LA SESION EXACTA antes de confirmar permiso/cancelacion/reprogramacion:

Caso A — Solo hay UNA sesion el dia mencionado:
Confirma directamente y genera la etiqueta con su ID.

Caso B — Hay MAS DE UNA sesion ese dia:
NO generes la etiqueta aun. Pregunta primero cual sesion:
"Ese dia tienes X sesiones:
1) HH:MM — Servicio con Prof. Nombre
2) HH:MM — Servicio con Prof. Nombre
Para cual es la solicitud?"

Caso C — El tutor no menciona fecha:
Pregunta: "Para que dia y sesion es la solicitud?"

Caso D — El tutor confirma cual sesion tras tu pregunta:
Genera la etiqueta con el ID correcto.

PASO 2 — GENERAR LA ETIQUETA (solo cuando ya tienes el ID de sesion):

Para PERMISO:
[NOTIFICAR:permiso|sesion_id:ID|descripcion con fecha, profesional y motivo]

Para CANCELACION:
[NOTIFICAR:cancelacion|sesion_id:ID|descripcion con fecha, profesional y motivo]

Para REPROGRAMACION:
[NOTIFICAR:reprogramacion|sesion_id:ID|fecha actual y nueva fecha solicitada]

Para PETICION AL PROFESIONAL (consulta sobre el paciente, cambio de horario, algo especifico de las sesiones actuales):
[NOTIFICAR:peticion_profesional|sesion_id:ID_O_0|descripcion detallada]

Para PETICION AL CENTRO (nueva evaluacion, nuevo servicio, consulta administrativa):
[NOTIFICAR:peticion_centro|sesion_id:0|descripcion detallada]

EJEMPLO — sesion identificada:
"Perfecto, anotare el permiso para el martes a las 9:00 con la Lic. Mamani. El equipo sera notificado. [NOTIFICAR:permiso|sesion_id:45|Permiso sesion martes 15/04 9:00 Lic. Mamani — motivo: cita medica]"

EJEMPLO — ambiguedad (dos sesiones el mismo dia):
"El martes tienes 2 sesiones:
1) 9:00 — Terapia de Lenguaje con Lic. Mamani
2) 11:00 — Psicologia con Lic. Torres
Para cual es la solicitud?"

═══════════════════════════════════════════
REGLAS GENERALES
═══════════════════════════════════════════
- Responde de forma concisa (maximo 4-5 oraciones para consultas simples, puedes extenderte para precios o evaluaciones)
- No uses asteriscos ni markdown — WhatsApp los muestra como texto plano
- Usa emojis con moderacion (maximo 1-2 por mensaje)
- NUNCA confirmes un diagnostico — usa: "podria estar relacionado con...", "seria importante evaluar..."
- Si el tutor pregunta sobre el centro (servicios, precios, evaluaciones, horarios), responde con la informacion completa del centro que tienes arriba
- Si el tutor pregunta por sus datos (sesiones, pagos, deuda), usa el contexto del paciente
- Si el tutor pregunta por informacion clinica general (que es el TEA, TDAH, etc), puedes orientar con informacion basica y sugerir consultar con el equipo del centro
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
            ctx += "\nPROXIMAS SESIONES (incluye ID para solicitudes):\n"
            for s in proximas[:8]:
                ctx += (
                    f"- ID:{s['id']} | {s['fecha']} {s['dia']} {s['hora']} "
                    f"— {s['servicio']} con {s['profesional']} en {s['sucursal']}\n"
                )
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
    Detecta etiquetas [NOTIFICAR:tipo|sesion_id:ID|detalle] en la respuesta
    y envia notificaciones al equipo correspondiente.
    Retorna el numero de notificaciones enviadas.
    """
    from agente.paciente_db import notificar_solicitud

    total  = 0
    patron = r'\[NOTIFICAR:(\w+)\|([^\]]+)\]'

    for match in re.finditer(patron, respuesta):
        tipo    = match.group(1).strip()
        detalle = match.group(2).strip()

        if tipo in ('permiso', 'cancelacion', 'reprogramacion',
                    'peticion_profesional', 'peticion_centro'):
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
    'reprogramar', 'reprogramacion', 'cambiar dia', 'otro dia',
    'peticion', 'solicitud', 'necesito hablar', 'mensaje al',
    'avisar', 'decirle al', 'preguntarle al', 'evaluacion nueva',
    'nueva evaluacion', 'quiero empezar', 'agregar terapia', 'nuevo servicio',
)


def _elegir_modelo(mensaje: str) -> tuple[str, str]:
    """
    Sonnet para solicitudes que generan notificaciones.
    Haiku para consultas informativas (datos del paciente o info del centro).
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
            max_tokens=600,
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