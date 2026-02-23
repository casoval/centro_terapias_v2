"""
Agente IA para el sistema de chat.
Motor: Groq (gratis) con llama-3.3-70b-versatile
Acceso a BD: via tools/funciones que el agente llama dinámicamente
"""

import json
import os
from datetime import datetime, timedelta
from django.contrib.auth.models import User
from django.db.models import Q, Sum, Count, Avg
from django.utils import timezone

# ============================================================
# CONFIGURACIÓN
# ============================================================

GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')  # Añadir en .env
IA_USER_USERNAME = 'asistente_ia'
MODELO_GROQ = 'llama-3.3-70b-versatile'


def get_o_crear_usuario_ia():
    """Obtiene o crea el usuario ficticio que representa al agente IA."""
    user, _ = User.objects.get_or_create(
        username=IA_USER_USERNAME,
        defaults={
            'first_name': 'Asistente',
            'last_name': 'IA',
            'is_active': True,
            'email': 'ia@sistema.interno',
        }
    )
    return user


# ============================================================
# TOOLS — funciones que el agente puede invocar
# ============================================================

def tool_obtener_pacientes(filtro: str = '', limite: int = 20) -> dict:
    """
    Busca pacientes en la base de datos.
    filtro: nombre, apellido o DNI parcial
    """
    try:
        from pacientes.models import Paciente
        qs = Paciente.objects.select_related('user').all()
        if filtro:
            qs = qs.filter(
                Q(nombre__icontains=filtro) |
                Q(apellido__icontains=filtro) |
                Q(dni__icontains=filtro) |
                Q(user__email__icontains=filtro)
            )
        qs = qs[:limite]
        resultado = []
        for p in qs:
            resultado.append({
                'id': p.id,
                'nombre': f'{p.nombre} {p.apellido}',
                'dni': getattr(p, 'dni', 'N/A'),
                'email': p.user.email if p.user else 'Sin usuario',
                'tutor': getattr(p, 'nombre_tutor', 'N/A'),
                'telefono': getattr(p, 'telefono', 'N/A'),
            })
        return {'pacientes': resultado, 'total': len(resultado)}
    except Exception as e:
        return {'error': str(e)}


def tool_obtener_agenda(fecha_inicio: str = '', fecha_fin: str = '',
                        profesional_id: int = None, paciente_id: int = None) -> dict:
    """
    Consulta citas/sesiones en la agenda.
    Fechas en formato YYYY-MM-DD. Si no se dan, devuelve los próximos 7 días.
    """
    try:
        from agenda.models import Sesion
        qs = Sesion.objects.select_related('paciente', 'profesional', 'profesional__user')

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

        qs = qs.order_by('fecha', 'hora')[:50]

        sesiones = []
        for s in qs:
            sesiones.append({
                'id': s.id,
                'fecha': str(s.fecha),
                'hora': str(getattr(s, 'hora', '')),
                'paciente': f'{s.paciente.nombre} {s.paciente.apellido}',
                'profesional': s.profesional.user.get_full_name() if s.profesional and s.profesional.user else 'N/A',
                'estado': getattr(s, 'estado', 'N/A'),
                'servicio': str(getattr(s, 'servicio', 'N/A')),
            })
        return {'sesiones': sesiones, 'total': len(sesiones)}
    except Exception as e:
        return {'error': str(e)}


def tool_obtener_profesionales(filtro: str = '', especialidad: str = '') -> dict:
    """Busca profesionales por nombre o especialidad."""
    try:
        from profesionales.models import Profesional
        qs = Profesional.objects.select_related('user')
        if filtro:
            qs = qs.filter(
                Q(user__first_name__icontains=filtro) |
                Q(user__last_name__icontains=filtro)
            )
        if especialidad:
            qs = qs.filter(especialidad__icontains=especialidad)

        resultado = []
        for p in qs[:30]:
            resultado.append({
                'id': p.id,
                'nombre': p.user.get_full_name() if p.user else 'N/A',
                'especialidad': getattr(p, 'especialidad', 'N/A'),
                'email': p.user.email if p.user else 'N/A',
                'telefono': getattr(p, 'telefono', 'N/A'),
            })
        return {'profesionales': resultado, 'total': len(resultado)}
    except Exception as e:
        return {'error': str(e)}


def tool_obtener_facturacion(fecha_inicio: str = '', fecha_fin: str = '',
                              paciente_id: int = None) -> dict:
    """
    Consulta facturas/pagos. Devuelve resumen financiero.
    """
    try:
        from facturacion.models import Factura  # ajustar al nombre real del modelo
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
                'id': f.id,
                'fecha': str(getattr(f, 'fecha', '')),
                'paciente': str(getattr(f, 'paciente', 'N/A')),
                'monto': float(getattr(f, 'monto', 0) or 0),
                'estado': getattr(f, 'estado', 'N/A'),
            })

        return {
            'facturas': facturas,
            'resumen': {
                'total_monto': float(totales['total'] or 0),
                'cantidad_facturas': totales['cantidad'],
                'promedio': float(totales['promedio'] or 0),
            }
        }
    except Exception as e:
        return {'error': str(e)}


def tool_estadisticas_generales() -> dict:
    """
    Genera un resumen estadístico general del sistema.
    Útil para informes rápidos.
    """
    try:
        from pacientes.models import Paciente
        from profesionales.models import Profesional
        from agenda.models import Sesion

        hoy = timezone.now().date()
        inicio_mes = hoy.replace(day=1)

        stats = {
            'pacientes_total': Paciente.objects.count(),
            'profesionales_total': Profesional.objects.count(),
            'sesiones_hoy': Sesion.objects.filter(fecha=hoy).count(),
            'sesiones_mes': Sesion.objects.filter(fecha__gte=inicio_mes).count(),
            'sesiones_pendientes': Sesion.objects.filter(
                fecha__gte=hoy,
                **({'estado__in': ['pendiente', 'confirmada']} if hasattr(Sesion, 'estado') else {})
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


def tool_buscar_en_sistema(termino: str) -> dict:
    """
    Búsqueda general en todo el sistema por un término.
    Busca en pacientes, profesionales y servicios.
    """
    resultados = {}

    try:
        from pacientes.models import Paciente
        pacientes = Paciente.objects.filter(
            Q(nombre__icontains=termino) | Q(apellido__icontains=termino)
        )[:5]
        resultados['pacientes'] = [
            f"{p.nombre} {p.apellido} (ID:{p.id})" for p in pacientes
        ]
    except Exception:
        resultados['pacientes'] = []

    try:
        from profesionales.models import Profesional
        profesionales = Profesional.objects.filter(
            Q(user__first_name__icontains=termino) |
            Q(user__last_name__icontains=termino) |
            Q(especialidad__icontains=termino)
        ).select_related('user')[:5]
        resultados['profesionales'] = [
            f"{p.user.get_full_name()} - {getattr(p, 'especialidad', '')}" for p in profesionales
        ]
    except Exception:
        resultados['profesionales'] = []

    try:
        from servicios.models import Servicio
        servicios = Servicio.objects.filter(nombre__icontains=termino)[:5]
        resultados['servicios'] = [str(s) for s in servicios]
    except Exception:
        resultados['servicios'] = []

    return resultados


# ============================================================
# DEFINICIÓN DE TOOLS PARA GROQ (formato OpenAI-compatible)
# ============================================================

TOOLS_DEFINICION = [
    {
        "type": "function",
        "function": {
            "name": "obtener_pacientes",
            "description": "Busca y lista pacientes registrados en el sistema. Útil para consultar datos de un paciente específico.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filtro": {"type": "string", "description": "Nombre, apellido o DNI a buscar (puede estar vacío para listar todos)"},
                    "limite": {"type": "integer", "description": "Número máximo de resultados (default 20)"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "obtener_agenda",
            "description": "Consulta citas y sesiones programadas. Puede filtrar por rango de fechas, profesional o paciente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "fecha_inicio": {"type": "string", "description": "Fecha inicio en formato YYYY-MM-DD"},
                    "fecha_fin": {"type": "string", "description": "Fecha fin en formato YYYY-MM-DD"},
                    "profesional_id": {"type": "integer", "description": "ID del profesional para filtrar"},
                    "paciente_id": {"type": "integer", "description": "ID del paciente para filtrar"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "obtener_profesionales",
            "description": "Busca profesionales de salud registrados en el sistema.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filtro": {"type": "string", "description": "Nombre a buscar"},
                    "especialidad": {"type": "string", "description": "Especialidad a filtrar"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "obtener_facturacion",
            "description": "Consulta facturas y datos financieros. Puede filtrar por fecha y paciente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "fecha_inicio": {"type": "string", "description": "Fecha inicio YYYY-MM-DD"},
                    "fecha_fin": {"type": "string", "description": "Fecha fin YYYY-MM-DD"},
                    "paciente_id": {"type": "integer", "description": "ID del paciente"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "estadisticas_generales",
            "description": "Genera un resumen estadístico general del sistema: totales de pacientes, sesiones del día, del mes, facturación, etc. Ideal para informes rápidos.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_en_sistema",
            "description": "Búsqueda general en todo el sistema por un término. Busca en pacientes, profesionales y servicios a la vez.",
            "parameters": {
                "type": "object",
                "properties": {
                    "termino": {"type": "string", "description": "Término de búsqueda"}
                },
                "required": ["termino"]
            }
        }
    },
]

# Mapa nombre → función real
TOOLS_MAP = {
    'obtener_pacientes': tool_obtener_pacientes,
    'obtener_agenda': tool_obtener_agenda,
    'obtener_profesionales': tool_obtener_profesionales,
    'obtener_facturacion': tool_obtener_facturacion,
    'estadisticas_generales': tool_estadisticas_generales,
    'buscar_en_sistema': tool_buscar_en_sistema,
}


# ============================================================
# SYSTEM PROMPT SEGÚN ROL
# ============================================================

def _get_system_prompt(usuario) -> str:
    hoy = datetime.now().strftime('%d/%m/%Y %H:%M')
    base = f"""Eres el Asistente IA del sistema de gestión de la clínica. Fecha y hora actual: {hoy}.

Tienes acceso en tiempo real a la base de datos de la clínica mediante herramientas (tools).
Puedes consultar pacientes, agenda, profesionales y facturación.
Puedes generar informes, resúmenes y análisis basándote en los datos reales.

REGLAS:
- Siempre usa las herramientas cuando necesites datos reales; nunca inventes información.
- Responde en español, de forma clara y estructurada.
- Para informes, usa formato con secciones claras.
- Si no encuentras datos, dilo claramente.
- Nunca compartas información de un paciente con otro paciente.
- Ante emergencias médicas, indica siempre llamar a emergencias."""

    if not hasattr(usuario, 'perfil') and not usuario.is_superuser:
        return base

    if usuario.is_superuser:
        return base + "\n\nTienes acceso TOTAL a todos los datos del sistema. Puedes ver todo."

    perfil = usuario.perfil

    if perfil.es_paciente():
        nombre = usuario.get_full_name() or usuario.username
        paciente_id = getattr(getattr(usuario, 'paciente', None), 'id', None)
        return base + f"""

Usuario actual: {nombre} (Paciente, ID:{paciente_id})
RESTRICCIÓN IMPORTANTE: Solo puedes mostrar información relacionada con ESTE paciente.
Puedes ayudarle con: sus citas, sus profesionales, sus facturas, y dudas generales sobre la clínica.
NO muestres datos de otros pacientes."""

    elif perfil.es_profesional():
        nombre = usuario.get_full_name()
        prof_id = getattr(getattr(usuario, 'profesional', None), 'id', None)
        return base + f"""

Usuario actual: Dr/a. {nombre} (Profesional, ID:{prof_id})
Puedes ayudarle con: su agenda, sus pacientes asignados, estadísticas de sus sesiones, informes de su actividad."""

    elif perfil.es_recepcionista():
        return base + f"""

Usuario actual: {usuario.get_full_name()} (Recepcionista)
Puedes ayudarle con: gestión de agenda, búsqueda de pacientes, citas del día, información general."""

    elif perfil.es_gerente():
        return base + f"""

Usuario actual: {usuario.get_full_name()} (Gerente)
Tienes acceso amplio. Puedes generar informes financieros, de actividad, de profesionales y estadísticas globales."""

    return base


# ============================================================
# LÓGICA PRINCIPAL — Llamada a Groq con tool use
# ============================================================

def responder_con_ia(conversacion, usuario_humano):
    """
    Función principal. Llama a Groq con el historial de la conversación
    y ejecuta las tools necesarias. Guarda la respuesta como Mensaje.
    """
    from .models import Mensaje, NotificacionChat

    usuario_ia = get_o_crear_usuario_ia()
    historial = _construir_historial(conversacion, usuario_ia)
    system_prompt = _get_system_prompt(usuario_humano)

    respuesta_texto = _llamar_groq_con_tools(historial, system_prompt)

    # Guardar en BD
    mensaje_ia = Mensaje.objects.create(
        conversacion=conversacion,
        remitente=usuario_ia,
        contenido=respuesta_texto
    )
    NotificacionChat.objects.create(
        usuario=usuario_humano,
        conversacion=conversacion,
        mensaje=mensaje_ia
    )
    conversacion.save()

    return mensaje_ia


def _construir_historial(conversacion, usuario_ia, limite=15):
    """Convierte los últimos N mensajes al formato Groq/OpenAI."""
    mensajes = list(
        conversacion.mensajes.order_by('-fecha_envio')[:limite]
    )
    mensajes.reverse()

    historial = []
    for msg in mensajes:
        rol = 'assistant' if msg.remitente == usuario_ia else 'user'
        historial.append({'role': rol, 'content': msg.contenido})
    return historial


def _llamar_groq_con_tools(historial: list, system_prompt: str) -> str:
    """
    Llama a la API de Groq. Si el modelo decide usar una tool,
    la ejecuta y vuelve a llamar hasta obtener una respuesta final de texto.
    """
    try:
        from groq import Groq
    except ImportError:
        return '⚠️ El paquete `groq` no está instalado. Ejecuta: pip install groq'

    if not GROQ_API_KEY:
        return '⚠️ No se ha configurado GROQ_API_KEY en las variables de entorno.'

    client = Groq(api_key=GROQ_API_KEY)

    mensajes = [{'role': 'system', 'content': system_prompt}] + historial

    # Máximo 5 rondas de tool use para evitar loops
    for _ in range(5):
        response = client.chat.completions.create(
            model=MODELO_GROQ,
            messages=mensajes,
            tools=TOOLS_DEFINICION,
            tool_choice='auto',
            max_tokens=2048,
            temperature=0.3,
        )

        mensaje_respuesta = response.choices[0].message

        # Si el modelo quiere llamar tools
        if mensaje_respuesta.tool_calls:
            # Añadir la respuesta del asistente al historial
            mensajes.append({
                'role': 'assistant',
                'content': mensaje_respuesta.content or '',
                'tool_calls': [
                    {
                        'id': tc.id,
                        'type': 'function',
                        'function': {
                            'name': tc.function.name,
                            'arguments': tc.function.arguments,
                        }
                    }
                    for tc in mensaje_respuesta.tool_calls
                ]
            })

            # Ejecutar cada tool y añadir resultado
            for tool_call in mensaje_respuesta.tool_calls:
                nombre_tool = tool_call.function.name
                try:
                    args = json.loads(tool_call.function.arguments or '{}')
                except json.JSONDecodeError:
                    args = {}

                if nombre_tool in TOOLS_MAP:
                    resultado = TOOLS_MAP[nombre_tool](**args)
                else:
                    resultado = {'error': f'Tool {nombre_tool} no encontrada'}

                mensajes.append({
                    'role': 'tool',
                    'tool_call_id': tool_call.id,
                    'content': json.dumps(resultado, ensure_ascii=False, default=str),
                })

        else:
            # Respuesta final de texto
            return mensaje_respuesta.content or 'No pude generar una respuesta.'

    return 'Se alcanzó el límite de consultas. Por favor reformula tu pregunta.'