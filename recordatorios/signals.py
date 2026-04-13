"""
signals.py — Recordatorios
Dispara automáticamente el mensaje post-falta/permiso cuando una sesión
cambia a estado 'falta' o 'permiso' en el sistema.
No requiere cron ni llamada manual.
"""
import requests
from django.db.models.signals import post_save
from django.dispatch import receiver
from agenda.models import Sesion


BOT_SEND_URL_JAPON   = 'http://localhost:3000/send'
BOT_SEND_URL_CAMACHO = 'http://localhost:3001/send'

SUCURSAL_JAPON   = 3
SUCURSAL_CAMACHO = 4

DIAS  = ['Lunes','Martes','Miércoles','Jueves','Viernes','Sábado','Domingo']
MESES = ['enero','febrero','marzo','abril','mayo','junio','julio','agosto',
         'septiembre','octubre','noviembre','diciembre']


def _bot_url(sucursal_id):
    return BOT_SEND_URL_CAMACHO if str(sucursal_id) == str(SUCURSAL_CAMACHO) else BOT_SEND_URL_JAPON


# Control en memoria para evitar mensajes duplicados por la misma sesion
_sesiones_notificadas = set()


@receiver(post_save, sender=Sesion)
def notificar_post_falta(sender, instance, **kwargs):
    """
    Se activa cada vez que se guarda una Sesion.
    Solo actua si el estado es 'falta' o 'permiso'.
    Controla duplicados para no enviar el mismo mensaje dos veces.
    """
    if instance.estado not in ('falta', 'permiso'):
        return

    # Clave unica por sesion + estado para evitar duplicados
    clave = f"{instance.id}:{instance.estado}"
    if clave in _sesiones_notificadas:
        return
    _sesiones_notificadas.add(clave)
    # Limpiar cache si crece demasiado
    if len(_sesiones_notificadas) > 1000:
        _sesiones_notificadas.clear()

    paciente = instance.paciente
    telefono = paciente.telefono_tutor
    if not telefono:
        return

    nombre_tutor    = paciente.nombre_tutor or 'estimado tutor/a'
    nombre_paciente = paciente.nombre_completo
    servicio        = instance.servicio.nombre
    fecha_str       = (
        f"{DIAS[instance.fecha.weekday()]} "
        f"{instance.fecha.day} de {MESES[instance.fecha.month - 1]}"
    )

    if instance.estado == 'permiso':
        mensaje = (
            f"Hola, *{nombre_tutor}*. 😊\n\n"
            f"Quedamos anotados del permiso de *{nombre_paciente}* para la sesión de "
            f"{servicio} del {fecha_str}.\n\n"
            f"Esperamos que todo esté bien. Cuando quieran retomar, aquí estamos. "
            f"Recuerde que puede ver el detalle de sesiones y permisos en *neuromisael.com* 💙"
        )
    else:  # falta
        mensaje = (
            f"Hola, *{nombre_tutor}*. 😊\n\n"
            f"Notamos que *{nombre_paciente}* no pudo asistir a su sesión de {servicio} "
            f"del {fecha_str}. Esperamos que todo esté bien por casa.\n\n"
            f"La continuidad es muy importante en el proceso terapéutico — cada sesión "
            f"tiene un propósito dentro del plan individual de {nombre_paciente}. "
            f"Cuando puedan, con gusto los esperamos. 🙏\n\n"
            f"— Centro de Neurodesarrollo Misael"
        )

    url = _bot_url(instance.sucursal_id)
    try:
        requests.post(url, json={'phone': telefono, 'message': mensaje, 'tipo': 'recordatorio'}, timeout=10)
    except Exception:
        pass  # Si el bot no responde, no debe romper el guardado de la sesion

    # ── Guardar en historial del panel de conversaciones ────────────────
    try:
        from agente.models import ConversacionAgente
        tel_completo = f'591{telefono}' if not telefono.startswith('591') else telefono
        tipo_label   = 'permiso' if instance.estado == 'permiso' else 'falta'
        ConversacionAgente.objects.create(
            agente       = 'paciente',
            telefono     = tel_completo,
            rol          = 'assistant',
            contenido    = mensaje,
            modelo_usado = f'recordatorio-{tipo_label}',
        )
    except Exception:
        pass  # No debe romper el flujo principal