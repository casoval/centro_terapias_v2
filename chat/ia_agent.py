"""
Agente IA para el sistema de chat interno.
Motor: Anthropic Claude (claude-haiku-4-5 para consultas simples, claude-sonnet-4-5 para complejas)
Acceso a BD: via tools que el agente llama dinámicamente
✅ Migrado de Groq/Llama a Anthropic Claude
✅ Restricción de tools por rol + system prompts detallados por rol
"""

import json
import os
import re
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)
from django.contrib.auth.models import User
from django.db.models import Q, Sum, Count, Avg
from django.utils import timezone

# ============================================================
# CONFIGURACIÓN
# ============================================================

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
IA_USER_USERNAME  = 'asistente_ia'
MODELO_RAPIDO     = 'claude-haiku-4-5-20251001'   # consultas simples
MODELO_COMPLEJO   = 'claude-sonnet-4-20250514'  # consultas con tools / análisis


def get_o_crear_usuario_ia():
    """Obtiene o crea el usuario ficticio que representa al agente IA."""
    user, _ = User.objects.get_or_create(
        username=IA_USER_USERNAME,
        defaults={
            'first_name': 'Asistente',
            'last_name':  'IA',
            'is_active':  True,
            'email':      'ia@sistema.interno',
        }
    )
    return user


# ============================================================
# TOOLS — funciones que el agente puede invocar
# ============================================================

def tool_obtener_pacientes(filtro: str = '', limite: int = 20) -> dict:
    """Busca pacientes en la base de datos."""
    try:
        from pacientes.models import Paciente
        qs = Paciente.objects.select_related('user').all()
        if filtro:
            qs = qs.filter(
                Q(nombre__icontains=filtro) |
                Q(apellido__icontains=filtro) |
                Q(user__email__icontains=filtro)
            )
        qs = qs[:limite]
        resultado = []
        for p in qs:
            resultado.append({
                'id':       p.id,
                'nombre':   f'{p.nombre} {p.apellido}',
                'email':    p.user.email if p.user else 'Sin usuario',
                'tutor':    getattr(p, 'nombre_tutor', 'N/A'),
                'telefono': getattr(p, 'telefono_tutor', 'N/A'),
            })
        return {'pacientes': resultado, 'total': len(resultado)}
    except Exception as e:
        return {'error': str(e)}


def tool_obtener_agenda(fecha_inicio: str = '', fecha_fin: str = '',
                        profesional_id: int = None, paciente_id: int = None) -> dict:
    """Consulta citas/sesiones en la agenda."""
    try:
        from agenda.models import Sesion
        qs = Sesion.objects.select_related('paciente', 'profesional', 'servicio', 'sucursal')

        if fecha_inicio:
            qs = qs.filter(fecha__gte=fecha_inicio)
        else:
            qs = qs.filter(fecha__gte=timezone.now().date())

        if fecha_fin:
            qs = qs.filter(fecha__lte=fecha_fin)
        else:
            qs = qs.filter(fecha__lte=(timezone.now().date() + timedelta(days=7)))

        if profesional_id:
            qs = qs.filter(profesional_id=profesional_id)
        if paciente_id:
            qs = qs.filter(paciente_id=paciente_id)

        qs = qs.order_by('fecha', 'hora_inicio')[:50]

        sesiones = []
        for s in qs:
            sesiones.append({
                'id':               s.id,
                'fecha':            str(s.fecha),
                'hora_inicio':      str(s.hora_inicio),
                'hora_fin':         str(s.hora_fin),
                'duracion_minutos': s.duracion_minutos,
                'paciente':         f'{s.paciente.nombre} {s.paciente.apellido}',
                'profesional':      f'{s.profesional.nombre} {s.profesional.apellido}' if s.profesional else 'N/A',
                'estado':           s.estado,
                'servicio':         s.servicio.nombre if s.servicio else 'N/A',
                'sucursal':         str(s.sucursal) if s.sucursal else 'N/A',
            })
        return {'sesiones': sesiones, 'total': len(sesiones)}
    except Exception as e:
        return {'error': str(e)}


def tool_obtener_profesionales(filtro: str = '', especialidad: str = '') -> dict:
    """Busca profesionales por nombre o especialidad."""
    try:
        from profesionales.models import Profesional
        qs = Profesional.objects.all()
        if filtro:
            qs = qs.filter(
                Q(nombre__icontains=filtro) |
                Q(apellido__icontains=filtro)
            )
        if especialidad:
            qs = qs.filter(especialidad__icontains=especialidad)

        resultado = []
        for p in qs[:30]:
            resultado.append({
                'id':          p.id,
                'nombre':      f'{p.nombre} {p.apellido}',
                'especialidad': getattr(p, 'especialidad', 'N/A'),
                'email':       p.email or 'N/A',
                'telefono':    getattr(p, 'telefono', 'N/A'),
            })
        return {'profesionales': resultado, 'total': len(resultado)}
    except Exception as e:
        return {'error': str(e)}


def tool_obtener_facturacion(fecha_inicio: str = '', fecha_fin: str = '',
                              paciente_id: int = None) -> dict:
    """Consulta facturas/pagos. Devuelve resumen financiero."""
    try:
        from facturacion.models import Factura
        qs = Factura.objects.all()

        if fecha_inicio:
            qs = qs.filter(fecha__gte=fecha_inicio)
        if fecha_fin:
            qs = qs.filter(fecha__lte=fecha_fin)
        if paciente_id:
            qs = qs.filter(paciente_id=paciente_id)

        totales = qs.aggregate(
            total=Sum('monto'),
            cantidad=Count('id'),
            promedio=Avg('monto')
        )

        facturas = []
        for f in qs.order_by('-fecha')[:20]:
            facturas.append({
                'id':       f.id,
                'fecha':    str(getattr(f, 'fecha', '')),
                'paciente': str(getattr(f, 'paciente', 'N/A')),
                'monto':    float(getattr(f, 'monto', 0) or 0),
                'estado':   getattr(f, 'estado', 'N/A'),
            })

        return {
            'facturas': facturas,
            'resumen': {
                'total_monto':        float(totales['total'] or 0),
                'cantidad_facturas':  totales['cantidad'],
                'promedio':           float(totales['promedio'] or 0),
            }
        }
    except Exception as e:
        return {'error': str(e)}


def tool_estadisticas_generales() -> dict:
    """Genera un resumen estadístico general del sistema."""
    try:
        from pacientes.models import Paciente
        from profesionales.models import Profesional
        from agenda.models import Sesion

        hoy        = timezone.now().date()
        inicio_mes = hoy.replace(day=1)

        stats = {
            'pacientes_total':            Paciente.objects.count(),
            'profesionales_total':        Profesional.objects.count(),
            'sesiones_hoy':               Sesion.objects.filter(fecha=hoy).count(),
            'sesiones_mes':               Sesion.objects.filter(fecha__gte=inicio_mes).count(),
            'sesiones_programadas_hoy':   Sesion.objects.filter(fecha=hoy, estado='programada').count(),
            'sesiones_pendientes':        Sesion.objects.filter(fecha__gte=hoy, estado='programada').count(),
            'sesiones_realizadas_mes':    Sesion.objects.filter(
                fecha__gte=inicio_mes,
                estado__in=['realizada', 'realizada_retraso']
            ).count(),
        }

        try:
            from facturacion.models import Factura
            stats['facturacion_mes'] = float(
                Factura.objects.filter(fecha__gte=inicio_mes).aggregate(t=Sum('monto'))['t'] or 0
            )
        except Exception:
            stats['facturacion_mes'] = 'N/A'

        return stats
    except Exception as e:
        return {'error': str(e)}


def tool_registrar_aviso_pago(paciente_id: int, monto: str = '', medio: str = '', descripcion: str = '') -> dict:
    """
    Registra un aviso de pago realizado por el tutor y notifica
    a recepcionistas, gerentes y admins del centro para que
    verifiquen y apliquen el pago en el sistema.
    """
    try:
        from pacientes.models import Paciente
        from chat.models import Conversacion, Mensaje, NotificacionChat

        paciente = Paciente.objects.select_related('user').get(id=paciente_id)
        nombre_paciente = f'{paciente.nombre} {paciente.apellido}'

        detalle = f'Aviso de pago — Paciente: {nombre_paciente} (ID: {paciente_id})'
        if monto:
            detalle += f' | Monto: {monto}'
        if medio:
            detalle += f' | Medio: {medio}'
        if descripcion:
            detalle += f' | Detalle: {descripcion}'

        from django.utils import timezone
        detalle += f' | Registrado: {timezone.now().strftime("%d/%m/%Y %H:%M")}'

        # Destinatarios: recepcionistas, gerentes y admins
        from django.contrib.auth.models import User
        from django.db.models import Q

        destinatarios = User.objects.filter(
            Q(is_superuser=True) |
            Q(perfil__rol__in=['recepcionista', 'gerente'])
        ).distinct()

        usuario_ia = get_o_crear_usuario_ia()
        notificados = []

        for dest in destinatarios:
            # Obtener o crear conversación con el usuario IA
            conv = Conversacion.objects.filter(
                Q(usuario_1=dest, usuario_2=usuario_ia) |
                Q(usuario_1=usuario_ia, usuario_2=dest)
            ).first()

            if not conv:
                conv = Conversacion.objects.create(
                    usuario_1=usuario_ia,
                    usuario_2=dest
                )

            msg = Mensaje.objects.create(
                conversacion=conv,
                remitente=usuario_ia,
                contenido=f'💰 AVISO DE PAGO REGISTRADO\n{detalle}'
            )
            NotificacionChat.objects.create(
                usuario=dest,
                conversacion=conv,
                mensaje=msg
            )
            conv.save()
            notificados.append(dest.get_full_name() or dest.username)

        return {
            'success': True,
            'paciente': nombre_paciente,
            'detalle': detalle,
            'notificados': notificados,
            'total_notificados': len(notificados)
        }

    except Exception as e:
        return {'error': str(e)}


def tool_buscar_en_sistema(termino: str) -> dict:
    """Búsqueda general en todo el sistema por un término."""
    resultados = {}

    try:
        from pacientes.models import Paciente
        pacientes = Paciente.objects.filter(
            Q(nombre__icontains=termino) | Q(apellido__icontains=termino)
        )[:5]
        resultados['pacientes'] = [f"{p.nombre} {p.apellido} (ID:{p.id})" for p in pacientes]
    except Exception:
        resultados['pacientes'] = []

    try:
        from profesionales.models import Profesional
        profesionales = Profesional.objects.filter(
            Q(nombre__icontains=termino) |
            Q(apellido__icontains=termino) |
            Q(especialidad__icontains=termino)
        )[:5]
        resultados['profesionales'] = [
            f"{p.nombre} {p.apellido} - {getattr(p, 'especialidad', '')}" for p in profesionales
        ]
    except Exception:
        resultados['profesionales'] = []

    try:
        from servicios.models import TipoServicio
        servicios = TipoServicio.objects.filter(nombre__icontains=termino)[:5]
        resultados['servicios'] = [str(s) for s in servicios]
    except Exception:
        resultados['servicios'] = []

    return resultados


# ============================================================
# DEFINICIÓN DE TOOLS PARA ANTHROPIC
# ============================================================

_TOOLS_CATALOGO = {
    'obtener_pacientes': {
        'name': 'obtener_pacientes',
        'description': 'Busca y lista pacientes registrados en el sistema.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'filtro': {'type': 'string', 'description': 'Nombre, apellido a buscar'},
                'limite': {'type': 'integer', 'description': 'Número máximo de resultados (default 20)'},
            }
        }
    },
    'obtener_agenda': {
        'name': 'obtener_agenda',
        'description': 'Consulta citas y sesiones programadas. Puede filtrar por rango de fechas, profesional o paciente.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'fecha_inicio':    {'type': 'string', 'description': 'Fecha inicio YYYY-MM-DD'},
                'fecha_fin':       {'type': 'string', 'description': 'Fecha fin YYYY-MM-DD'},
                'profesional_id':  {'type': 'integer', 'description': 'ID del profesional'},
                'paciente_id':     {'type': 'integer', 'description': 'ID del paciente'},
            }
        }
    },
    'obtener_profesionales': {
        'name': 'obtener_profesionales',
        'description': 'Busca profesionales de salud registrados en el sistema.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'filtro':       {'type': 'string', 'description': 'Nombre a buscar'},
                'especialidad': {'type': 'string', 'description': 'Especialidad a filtrar'},
            }
        }
    },
    'obtener_facturacion': {
        'name': 'obtener_facturacion',
        'description': 'Consulta facturas y datos financieros.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'fecha_inicio': {'type': 'string', 'description': 'Fecha inicio YYYY-MM-DD'},
                'fecha_fin':    {'type': 'string', 'description': 'Fecha fin YYYY-MM-DD'},
                'paciente_id':  {'type': 'integer', 'description': 'ID del paciente'},
            }
        }
    },
    'estadisticas_generales': {
        'name': 'estadisticas_generales',
        'description': 'Genera un resumen estadístico general del sistema.',
        'input_schema': {'type': 'object', 'properties': {}}
    },
    'registrar_aviso_pago': {
        'name': 'registrar_aviso_pago',
        'description': (
            'Registra un aviso de pago realizado por el tutor y notifica automáticamente '
            'a recepcionistas, gerentes y admins del centro. '
            'Llamar SOLO después de confirmar los datos con el tutor. '
            'Incluir en descripcion: fecha del pago, banco de origen, número de comprobante '
            'o referencia, y cualquier detalle adicional que el tutor haya mencionado.'
        ),
        'input_schema': {
            'type': 'object',
            'properties': {
                'paciente_id': {'type': 'integer', 'description': 'ID del paciente en el sistema'},
                'monto':       {'type': 'string',  'description': 'Monto pagado (ej: "Bs. 210")'},
                'medio':       {'type': 'string',  'description': 'Medio de pago: efectivo, transferencia bancaria, QR, depósito u otro'},
                'descripcion': {'type': 'string',  'description': (
                    'Datos adicionales del pago en formato: '
                    '"Fecha: DD/MM/AAAA | Banco/Ref: [banco y número de comprobante o N/A] | [detalle extra]"'
                )},
            },
            'required': ['paciente_id', 'monto', 'medio']
        }
    },
    'buscar_en_sistema': {
        'name': 'buscar_en_sistema',
        'description': 'Búsqueda general en todo el sistema por un término.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'termino': {'type': 'string', 'description': 'Término de búsqueda'},
            },
            'required': ['termino']
        }
    },
}

TOOLS_MAP = {
    'obtener_pacientes':    tool_obtener_pacientes,
    'obtener_agenda':       tool_obtener_agenda,
    'obtener_profesionales': tool_obtener_profesionales,
    'obtener_facturacion':  tool_obtener_facturacion,
    'estadisticas_generales': tool_estadisticas_generales,
    'registrar_aviso_pago':   tool_registrar_aviso_pago,
    'buscar_en_sistema':    tool_buscar_en_sistema,
}

# ============================================================
# PERMISOS DE TOOLS POR ROL
# ============================================================

_TOOLS_POR_ROL = {
    'paciente':      ['obtener_agenda', 'obtener_facturacion', 'registrar_aviso_pago'],
    'profesional':   ['obtener_agenda', 'obtener_pacientes', 'obtener_profesionales', 'buscar_en_sistema'],
    'recepcionista': ['obtener_agenda', 'obtener_pacientes', 'obtener_profesionales', 'buscar_en_sistema', 'registrar_aviso_pago'],
    'gerente':       list(_TOOLS_CATALOGO.keys()),
    'superadmin':    list(_TOOLS_CATALOGO.keys()),
}


def _get_tools_para_rol(usuario) -> list:
    """Devuelve la lista de tools permitidas para el rol del usuario."""
    if usuario.is_superuser:
        claves = _TOOLS_POR_ROL['superadmin']
    elif not hasattr(usuario, 'perfil'):
        claves = ['obtener_agenda', 'buscar_en_sistema']
    elif usuario.perfil.es_paciente():
        claves = _TOOLS_POR_ROL['paciente']
    elif usuario.perfil.es_profesional():
        claves = _TOOLS_POR_ROL['profesional']
    elif usuario.perfil.es_recepcionista():
        claves = _TOOLS_POR_ROL['recepcionista']
    elif usuario.perfil.es_gerente():
        claves = _TOOLS_POR_ROL['gerente']
    else:
        claves = ['buscar_en_sistema']

    return [_TOOLS_CATALOGO[k] for k in claves if k in _TOOLS_CATALOGO]


# ============================================================
# SYSTEM PROMPT SEGÚN ROL
# ============================================================

def _get_system_prompt(usuario) -> str:
    hoy = datetime.now().strftime('%d/%m/%Y %H:%M')

    base = f"""Eres el Asistente IA del sistema de gestión del Centro Infantil Misael. Fecha y hora actual: {hoy}.
Tienes acceso en tiempo real a la base de datos mediante herramientas (tools).

REGLAS GENERALES:
- Usa SIEMPRE las herramientas para obtener datos reales; nunca inventes ni supongas información.
- Responde en español, de forma clara y estructurada.
- Si no encuentras datos, dilo claramente y sugiere cómo reformular la búsqueda.
- Sé conciso: evita párrafos innecesarios, prioriza la información útil.
- No uses markdown con asteriscos — el chat los muestra como texto plano."""

    if not hasattr(usuario, 'perfil') and not usuario.is_superuser:
        return base + "\n\nResponde de forma general. No tienes acceso a datos sensibles."

    if usuario.is_superuser:
        nombre = usuario.get_full_name() or usuario.username
        return base + f"""

ROL: Administrador del sistema — {nombre}
ACCESO: Total a todos los módulos del sistema.

CAPACIDADES:
- Ver y buscar cualquier paciente, profesional, sesión o factura.
- Generar informes globales: estadísticas, facturación, actividad por profesional.
- Comparar períodos, identificar tendencias y anomalías."""

    perfil = usuario.perfil

    if perfil.es_paciente():
        nombre     = usuario.get_full_name() or usuario.username
        paciente   = getattr(usuario, 'paciente', None)
        paciente_id = paciente.id if paciente else None
        tutor      = getattr(paciente, 'nombre_tutor', 'N/A') if paciente else 'N/A'

        return base + f"""

ROL: Paciente — {nombre}
ID de paciente en sistema: {paciente_id}

RESTRICCION DE PRIVACIDAD (CRITICA):
- Solo puedes mostrar información relacionada con ESTE paciente (ID: {paciente_id}).
- NUNCA muestres datos de otros pacientes.
- Al usar obtener_agenda, filtra SIEMPRE con paciente_id={paciente_id}.
- Al usar obtener_facturacion, filtra SIEMPRE con paciente_id={paciente_id}.
- Al usar registrar_aviso_pago, usa SIEMPRE paciente_id={paciente_id}.

CAPACIDADES:
- Consultar sus propias citas: próximas, pasadas, canceladas.
- Ver el estado de sus facturas y pagos pendientes.
- Resolver dudas generales sobre la clínica.
- Registrar avisos de pago cuando el tutor mencione que realizó un pago.

AVISO DE PAGO — FLUJO OBLIGATORIO (SEGUIR EN ORDEN):

PASO 1 — DETECTAR INTENCIÓN DE PAGO:
Si el tutor menciona que realizó un pago o que va a avisar un pago,
NO llames a la tool todavía. Primero saluda la intención y pregunta
los detalles en un solo mensaje amable. Ejemplo:
"Gracias por avisarnos 😊 Para registrar tu pago necesito algunos datos:"
Luego lista las preguntas numeradas:
1. Monto abonado
2. Fecha en que se realizó el pago
3. Medio de pago (efectivo, transferencia bancaria, QR, depósito u otro)
4. Banco de origen y número de comprobante o referencia (opcional, pero
   ayuda al staff a verificar más rápido)
5. Algún detalle adicional (opcional)

PASO 2 — RECOPILAR RESPUESTAS:
Espera a que el tutor responda. Los únicos datos obligatorios son
monto, fecha y medio — con esos tres el staff ya puede verificar el pago.
Si falta alguno de esos tres, pídelo puntualmente sin repetir
lo que el tutor ya respondió.
Banco y comprobante son bienvenidos pero nunca bloquean el registro.

PASO 3 — CONFIRMAR ANTES DE REGISTRAR:
Cuando tengas monto, fecha y medio, muestra un resumen al tutor:
"Voy a registrar este aviso de pago:
- Monto: [monto]
- Fecha: [fecha]
- Medio: [medio]
- Banco / Comprobante: [dato si lo dio, o 'No proporcionado']
- Detalle: [detalle si lo dio, o 'Ninguno']
¿Los datos son correctos?"

PASO 4 — REGISTRAR:
Solo cuando el tutor confirme (responda "sí", "correcto", "ok" o similar),
llama a registrar_aviso_pago con paciente_id={paciente_id} y todos los
datos recopilados en el campo descripcion con este formato:
"Fecha: [fecha] | Banco/Ref: [dato] | [detalle adicional]"

PASO 5 — CONFIRMAR AL TUTOR:
Después de ejecutar la tool con éxito, responde:
"Listo ✅ Tu aviso de pago quedó registrado. El equipo del centro
lo verificará y lo aplicará en tu cuenta a la brevedad.
Si tenés el comprobante físico, podés presentarlo en la sucursal
para agilizar el proceso."

---

CAMBIO DE PROFESIONAL:
Si el tutor solicita cambiar al profesional que atiende a su hijo,
no minimices ni normalices la situación, pero tampoco tomes partido.
Responde con calidez y redirige al equipo:
"Entendemos que la relación entre el profesional y el paciente es parte
fundamental del proceso terapéutico. Si sentís que necesitás un cambio,
es importante conversarlo directamente con el equipo del centro — ellos
pueden orientarte, escucharte y evaluar la mejor opción para el proceso
de [nombre]. Podés llamar al +591 76175352 o acercarte personalmente
a tu sucursal en horario de atención."
No preguntes el motivo. No juzgues ni des tu opinión sobre el profesional.
No prometas que el cambio es posible ni que habrá disponibilidad.
Genera una etiqueta de petición al centro:
[NOTIFICAR:peticion_centro|sesion_id:0|Tutor solicita evaluación de cambio de profesional para paciente {paciente_id}. Requiere atención del equipo.]

---

CONSTANCIAS Y CERTIFICADOS:
Si el tutor pide una constancia de atención, certificado de tratamiento,
carta para el colegio o cualquier documento oficial que acredite que el
paciente está siendo atendido en el centro, responde:
"Las constancias de atención y certificados se gestionan directamente en
el centro. Para solicitarla, acercate a tu sucursal en horario de atención
con tu documento de identidad y, si el colegio o institución tiene un
formulario específico, llevalo también. El equipo te indicará el plazo
de entrega y si tiene algún costo.
Sede Japón: +591 76175352 / Sede Central: +591 78633975."
No confirmes plazos ni costos exactos — eso lo define el equipo presencialmente.
Genera una etiqueta de petición al centro:
[NOTIFICAR:peticion_centro|sesion_id:0|Tutor solicita constancia/certificado de atención para paciente {paciente_id}. Pendiente gestión presencial.]

---

ALTA O FIN DE TRATAMIENTO:
Si el tutor pregunta cuándo termina el tratamiento, si su hijo ya recibió
el alta, o qué significa el alta terapéutica, responde con calidez:
"El alta terapéutica es una decisión clínica que toma el profesional
que atiende a [nombre], en base a la evolución observada sesión a sesión.
No hay una fecha fija — cada proceso es único y el equipo lo va evaluando
de forma continua. Si querés saber cómo va evolucionando [nombre] y
cuándo podría llegarse a esa etapa, lo más recomendable es conversarlo
directamente con el profesional en la próxima sesión, o coordinar una
reunión de seguimiento a través del centro."
Si el profesional ya comunicó el alta y el tutor lo menciona, valida
el logro con genuino calor antes de redirigir:
"Que buena noticia — llegar al alta es el resultado del esfuerzo de toda
la familia y del trabajo del equipo. Si tenés dudas sobre los próximos
pasos, el equipo del centro puede orientarte."
No confirmes ni niegues el alta por mensaje — eso lo comunica el profesional.

---

MEDICACIÓN:
Si el tutor pregunta sobre medicación — si el centro receta, qué pasa si
cambian la dosis, si el profesional puede orientar sobre un medicamento —
responde con claridad sin invadir terreno médico:
"El Centro Misael es un centro de neurodesarrollo terapéutico — no
prescribimos ni gestionamos medicación. Las decisiones sobre medicamentos
las toma exclusivamente el médico o neurólogo que lleva esa parte del
seguimiento de [nombre].
Si necesitás orientación sobre cómo coordinar la parte médica con las
terapias que recibe en el centro, podés conversarlo con el equipo — hay
casos en que el profesional puede comunicarse con el médico tratante
para alinear criterios, siempre con el consentimiento de la familia."
Si el tutor menciona que le cambiaron la medicación y quiere avisarlo al
profesional, genera una petición:
[NOTIFICAR:peticion_profesional|sesion_id:0|Tutor informa cambio de medicación en paciente {paciente_id}. Solicita que el profesional esté al tanto antes de la próxima sesión.]

---

CRISIS EMOCIONAL DEL TUTOR:
Si el tutor llega emocionalmente desbordado — acaba de recibir un
diagnóstico difícil, expresa desesperanza, no sabe qué hacer, o describe
una situación de mucho dolor — NO redirijas de inmediato ni des
información del centro. Primero contén, luego orienta.
Ejemplo de respuesta de contención:
"Lo que estás sintiendo tiene mucho sentido. Recibir una noticia así
es difícil, y es normal que en este momento todo se sienta abrumador.
No tenés que tenerlo todo claro ahora mismo.
Lo que sí podemos decirte es que no están solos en esto — el equipo del
Centro Misael acompaña a las familias no solo en las sesiones, sino en
todo el proceso. Cuando te sientas listo/a, podés comunicarte con nosotros
y vamos a orientarte con calma. Estamos acá."
Solo después de ese primer mensaje de contención, y si el tutor lo pide
o continúa la conversación, orientá sobre los pasos concretos.
Nunca minimices el diagnóstico ni uses frases como "todo va a estar bien"
o "otros niños han pasado por esto". Acompañá sin trivializar.

---

RECESO Y VACACIONES:
Si el tutor pregunta sobre receso escolar, vacaciones de invierno,
feriados o qué pasa con las sesiones en esas fechas, responde:
"Los feriados nacionales o cívicos pueden afectar el funcionamiento del
centro, dependiendo de la fecha. Para saber si hay sesiones en una fecha
específica, lo más seguro es consultar directamente con el centro:
+591 76175352 (Sede Japón) / +591 78633975 (Sede Central).
En cuanto al receso escolar, el centro generalmente mantiene su
funcionamiento — los tratamientos no dependen del calendario escolar, ya
que cada plan terapéutico tiene su propia continuidad. Pero cualquier
cambio puntual lo comunica el equipo con anticipación."
No confirmes ni niegues fechas de cierre específicas — eso puede cambiar
y el equipo es quien debe confirmarlo.

---

ORIENTACIÓN A PADRES EN SESIONES:
Si el tutor pregunta si puede participar en las sesiones de su hijo, si
hay espacio para los padres o si existe orientación para tutores, responde:
"La participación de los tutores en el proceso terapéutico es muy
valorada en el Centro Misael. Dependiendo del tipo de terapia y de la
etapa del tratamiento, el profesional puede incluir espacios de
orientación a la familia, observación de sesiones o reuniones de
seguimiento. Esto varía según el criterio del profesional y las
necesidades de [nombre].
Si querés saber qué posibilidades hay específicamente en el caso de tu
hijo, te recomendamos conversarlo directamente con el profesional que
lo atiende — podés hacerlo en la próxima sesión o a través del chat
privado en tu cuenta de neuromisael.com."
Genera una petición si el tutor lo pide explícitamente:
[NOTIFICAR:peticion_profesional|sesion_id:0|Tutor de paciente {paciente_id} solicita información sobre participación en sesiones o espacios de orientación a padres.]

---

DERIVACIÓN A PSIQUIATRÍA O NEUROLOGÍA:
Si el tutor llega con una derivación externa de otro médico, o pregunta
con urgencia si el centro puede gestionar una derivación pronto, responde:
"Si tenés una derivación de otro profesional de salud, podés acercarte
al centro con ese documento y el equipo evaluará cómo integrarlo al plan
de seguimiento de [nombre]. El centro coordina con el médico derivante
cuando es necesario.
Para derivaciones internas — cuando el equipo del centro considera que
[nombre] necesita evaluación psiquiátrica o neurológica — el proceso lo
coordina directamente el profesional tratante con la familia. Si esto fue
recomendado y aún no recibiste más información, te recomendamos contactar
al centro para hacer seguimiento:
+591 76175352 (Sede Japón) / +591 78633975 (Sede Central)."
Si el tutor expresa urgencia, validá esa urgencia antes de orientar:
"Entendemos que cuando se trata de la salud de tu hijo, el tiempo importa.
Contactá al centro directamente por teléfono para que puedan darte
prioridad en la atención."

---

ESTILO: Tono amable y cercano. Tutor registrado: {tutor}.
FALLBACK modo_conversacion: Si la variable de modo de conversación no está
disponible, arranca la respuesta de forma directa y cálida, usando el
nombre del tutor si está disponible, sin fórmulas genéricas."""

    elif perfil.es_profesional():
        nombre      = usuario.get_full_name()
        profesional = getattr(usuario, 'profesional', None)
        prof_id     = profesional.id if profesional else None
        especialidad = getattr(profesional, 'especialidad', 'N/A') if profesional else 'N/A'

        return base + f"""

ROL: Profesional de salud — {nombre}
Especialidad: {especialidad} | ID en sistema: {prof_id}

RESTRICCION DE PRIVACIDAD:
- Puedes ver información de pacientes asignados a tu agenda.
- No tienes acceso a datos financieros globales.
- Al consultar tu agenda sin fechas específicas, usa SIEMPRE profesional_id={prof_id}.

CAPACIDADES:
- Consultar y revisar tu agenda.
- Buscar información de tus pacientes asignados.
- Ver datos de colegas profesionales.

ESTILO: Tono profesional y directo."""

    elif perfil.es_recepcionista():
        nombre = usuario.get_full_name()
        return base + f"""

ROL: Recepcionista — {nombre}

RESTRICCION: No tienes acceso a datos financieros ni de facturación.

CAPACIDADES:
- Consultar y gestionar la agenda general.
- Buscar pacientes y profesionales.
- Ver disponibilidad y datos de contacto.

ESTILO: Tono eficiente y operativo. Respuestas cortas y concretas."""

    elif perfil.es_gerente():
        nombre = usuario.get_full_name()
        return base + f"""

ROL: Gerente — {nombre}
ACCESO: Amplio a todos los módulos operativos y financieros.

CAPACIDADES:
- Consultar estadísticas globales y generar informes financieros.
- Analizar actividad por profesional y comparar períodos.
- Acceso completo a agenda, pacientes, profesionales y facturación.

ESTILO: Tono ejecutivo y analítico."""

    return base + "\n\nResponde de forma general con la información disponible."


# ============================================================
# LÓGICA PRINCIPAL — Llamada a Anthropic con tool use
# ============================================================

# ============================================================
# HELPERS PARA ETIQUETAS [NOTIFICAR:...]
# ============================================================

def _limpiar_etiquetas(texto: str) -> str:
    """
    Elimina las etiquetas [NOTIFICAR:...] del texto visible en el chat.
    El paciente nunca debe ver esas marcas internas.
    """
    return re.sub(r'\[NOTIFICAR:[^\]]*\]', '', texto).strip()


def _procesar_notificaciones_ia(respuesta: str, usuario_humano) -> int:
    """
    Detecta etiquetas [NOTIFICAR:tipo|sesion_id:X|detalle] en la respuesta
    del agente y despacha las notificaciones al chat interno de los
    involucrados (profesional, recepción, gerencia, admin).

    Solo actúa cuando el usuario es un paciente — los demás roles no
    generan este tipo de etiquetas.

    Retorna el número total de usuarios notificados.
    """
    # Solo aplica para pacientes
    if not hasattr(usuario_humano, 'perfil') or not usuario_humano.perfil.es_paciente():
        return 0

    paciente = getattr(usuario_humano, 'paciente', None)
    if not paciente:
        logger.warning(
            f'[IA Agent] Usuario {usuario_humano.username} tiene perfil paciente '
            f'pero no tiene objeto paciente asociado.'
        )
        return 0

    try:
        from agente.paciente_db import notificar_solicitud
    except ImportError:
        logger.error('[IA Agent] No se pudo importar agente.paciente_db.notificar_solicitud')
        return 0

    total = 0
    patron = r'\[NOTIFICAR:(\w+)\|([^\]]+)\]'

    for match in re.finditer(patron, respuesta):
        tipo    = match.group(1).strip()
        detalle = match.group(2).strip()

        if tipo in ('permiso', 'cancelacion', 'reprogramacion',
                    'peticion_profesional', 'peticion_centro', 'aviso_pago'):
            try:
                notificados = notificar_solicitud(paciente, tipo, detalle)
                total += notificados
                logger.info(
                    f'[IA Agent] Notificación [{tipo}] enviada a {notificados} usuario(s) '
                    f'— paciente: {paciente.nombre} {paciente.apellido}'
                )
            except Exception as exc:
                logger.error(
                    f'[IA Agent] Error al notificar [{tipo}] para paciente {paciente.id}: {exc}',
                    exc_info=True
                )

    return total


# ============================================================
# LÓGICA PRINCIPAL — Llamada a Anthropic con tool use
# ============================================================

def responder_con_ia(conversacion, usuario_humano):
    """
    Función principal. Llama a Claude con el historial de la conversación
    y ejecuta las tools necesarias. Guarda la respuesta como Mensaje.

    ✅ CORREGIDO: procesa etiquetas [NOTIFICAR:...] para enviar
    notificaciones al chat interno de los involucrados, y limpia
    esas etiquetas antes de mostrar el texto al paciente.
    """
    from .models import Mensaje, NotificacionChat

    usuario_ia       = get_o_crear_usuario_ia()
    historial        = _construir_historial(conversacion, usuario_ia)
    system_prompt    = _get_system_prompt(usuario_humano)
    tools_permitidas = _get_tools_para_rol(usuario_humano)

    respuesta_raw = _llamar_claude_con_tools(historial, system_prompt, tools_permitidas)

    # ✅ 1. Despachar notificaciones al chat interno de los involucrados
    _procesar_notificaciones_ia(respuesta_raw, usuario_humano)

    # ✅ 2. Limpiar etiquetas antes de guardar — el paciente no debe verlas
    respuesta_limpia = _limpiar_etiquetas(respuesta_raw)

    mensaje_ia = Mensaje.objects.create(
        conversacion=conversacion,
        remitente=usuario_ia,
        contenido=respuesta_limpia
    )
    NotificacionChat.objects.create(
        usuario=usuario_humano,
        conversacion=conversacion,
        mensaje=mensaje_ia
    )
    conversacion.save()

    return mensaje_ia


def _construir_historial(conversacion, usuario_ia, limite: int = 15):
    """Convierte los últimos N mensajes al formato Anthropic."""
    mensajes = list(conversacion.mensajes.order_by('-fecha_envio')[:limite])
    mensajes.reverse()

    historial = []
    for msg in mensajes:
        rol = 'assistant' if msg.remitente == usuario_ia else 'user'
        historial.append({'role': rol, 'content': msg.contenido})
    return historial


def _llamar_claude_con_tools(historial: list, system_prompt: str, tools: list) -> str:
    """
    Llama a la API de Anthropic con las tools permitidas para el rol.
    Ejecuta las tools que Claude solicite y vuelve a llamar hasta
    obtener una respuesta final de texto.
    """
    try:
        import anthropic
    except ImportError:
        return '⚠️ El paquete anthropic no está instalado. Ejecuta: pip install anthropic'

    if not ANTHROPIC_API_KEY:
        return '⚠️ No se ha configurado ANTHROPIC_API_KEY en las variables de entorno.'

    client   = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    mensajes = historial.copy()

    # Máximo 5 rondas de tool use para evitar loops
    for _ in range(5):
        kwargs = {
            'model':      MODELO_COMPLEJO,
            'max_tokens': 2048,
            'system':     system_prompt,
            'messages':   mensajes,
        }
        if tools:
            kwargs['tools'] = tools

        response = client.messages.create(**kwargs)

        # Verificar si hay tool_use en la respuesta
        tool_use_blocks = [b for b in response.content if b.type == 'tool_use']

        if tool_use_blocks:
            # Agregar respuesta del asistente al historial
            mensajes.append({
                'role':    'assistant',
                'content': response.content,
            })

            # Ejecutar cada tool y agregar resultados
            tool_results = []
            for block in tool_use_blocks:
                nombre_tool = block.name

                # Verificar que la tool está permitida
                nombres_permitidos = [t['name'] for t in tools]
                if nombre_tool not in nombres_permitidos or nombre_tool not in TOOLS_MAP:
                    resultado = {'error': 'No tienes permisos para usar esta herramienta.'}
                else:
                    try:
                        args    = block.input or {}
                        resultado = TOOLS_MAP[nombre_tool](**args)
                    except Exception as e:
                        resultado = {'error': str(e)}

                tool_results.append({
                    'type':        'tool_result',
                    'tool_use_id': block.id,
                    'content':     json.dumps(resultado, ensure_ascii=False, default=str),
                })

            # Agregar resultados al historial
            mensajes.append({
                'role':    'user',
                'content': tool_results,
            })

        else:
            # Respuesta final de texto
            texto_blocks = [b for b in response.content if b.type == 'text']
            if texto_blocks:
                return texto_blocks[0].text
            return 'No pude generar una respuesta.'

    return 'Se alcanzó el límite de consultas. Por favor reformula tu pregunta.'