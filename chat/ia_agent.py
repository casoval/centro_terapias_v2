"""
Agente IA para el sistema de chat.
Motor: Groq (gratis) con llama-3.3-70b-versatile
Acceso a BD: via tools/funciones que el agente llama dinámicamente
✅ MEJORADO: Restricción de tools por rol + system prompts detallados por rol
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

GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')
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

        qs = qs.order_by('fecha', 'hora_inicio')[:50]

        sesiones = []
        for s in qs:
            sesiones.append({
                'id': s.id,
                'fecha': str(s.fecha),
                'hora_inicio': str(s.hora_inicio),
                'hora_fin': str(s.hora_fin),
                'duracion_minutos': s.duracion_minutos,
                'paciente': f'{s.paciente.nombre} {s.paciente.apellido}',
                'profesional': s.profesional.user.get_full_name() if s.profesional and s.profesional.user else 'N/A',
                'estado': s.estado,
                'servicio': s.servicio.nombre if s.servicio else 'N/A',
                'sucursal': str(s.sucursal) if s.sucursal else 'N/A',
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
            'sesiones_programadas_hoy': Sesion.objects.filter(
                fecha=hoy, estado='programada'
            ).count(),
            'sesiones_pendientes': Sesion.objects.filter(
                fecha__gte=hoy,
                estado='programada'
            ).count(),
            'sesiones_realizadas_mes': Sesion.objects.filter(
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

# Catálogo completo de tools con su definición
_TOOLS_CATALOGO = {
    'obtener_pacientes': {
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
    'obtener_agenda': {
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
    'obtener_profesionales': {
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
    'obtener_facturacion': {
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
    'estadisticas_generales': {
        "type": "function",
        "function": {
            "name": "estadisticas_generales",
            "description": "Genera un resumen estadístico general del sistema: totales de pacientes, sesiones del día, del mes, facturación, etc. Ideal para informes rápidos.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    'buscar_en_sistema': {
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
}

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
# PERMISOS DE TOOLS POR ROL
# ============================================================

# Define qué tools puede usar cada rol
_TOOLS_POR_ROL = {
    # Paciente: solo su propia información
    'paciente': [
        'obtener_agenda',       # filtrada a su paciente_id en el prompt
        'obtener_facturacion',  # filtrada a su paciente_id en el prompt
    ],
    # Profesional: su agenda y sus pacientes, sin acceso financiero global
    'profesional': [
        'obtener_agenda',
        'obtener_pacientes',
        'obtener_profesionales',
        'buscar_en_sistema',
    ],
    # Recepcionista: gestión operativa, sin datos financieros
    'recepcionista': [
        'obtener_agenda',
        'obtener_pacientes',
        'obtener_profesionales',
        'buscar_en_sistema',
    ],
    # Gerente: acceso total excepto... todo permitido
    'gerente': [
        'obtener_agenda',
        'obtener_pacientes',
        'obtener_profesionales',
        'obtener_facturacion',
        'estadisticas_generales',
        'buscar_en_sistema',
    ],
    # Superadmin: acceso total
    'superadmin': list(_TOOLS_CATALOGO.keys()),
}


def _get_tools_para_rol(usuario) -> list:
    """
    Devuelve la lista de definiciones de tools permitidas para el rol del usuario.
    """
    if usuario.is_superuser:
        claves = _TOOLS_POR_ROL['superadmin']
    elif not hasattr(usuario, 'perfil'):
        # Usuario sin perfil definido: acceso mínimo
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

    # Base común a todos los roles
    base = f"""Eres el Asistente IA del sistema de gestión de la clínica. Fecha y hora actual: {hoy}.
Tienes acceso en tiempo real a la base de datos de la clínica mediante herramientas (tools).

REGLAS GENERALES:
- Usa SIEMPRE las herramientas para obtener datos reales; nunca inventes ni supongas información.
- Responde en español, de forma clara y estructurada.
- Si no encuentras datos, dilo claramente y sugiere cómo reformular la búsqueda.
- Ante emergencias médicas, indica siempre llamar a emergencias (118 o 911).
- Sé conciso: evita párrafos innecesarios, prioriza la información útil."""

    # Sin perfil definido
    if not hasattr(usuario, 'perfil') and not usuario.is_superuser:
        return base + "\n\nResponde de forma general. No tienes acceso a datos sensibles de pacientes."

    # ── SUPERADMIN ──────────────────────────────────────────
    if usuario.is_superuser:
        nombre = usuario.get_full_name() or usuario.username
        return base + f"""

ROL: Administrador del sistema — {nombre}
ACCESO: Total a todos los módulos del sistema.

CAPACIDADES:
- Ver y buscar cualquier paciente, profesional, sesión o factura.
- Generar informes globales: estadísticas, facturación, actividad por profesional.
- Comparar períodos, identificar tendencias y anomalías.

ESTILO DE RESPUESTA:
- Usa formato de informe cuando presentes estadísticas (secciones, totales destacados).
- Para búsquedas rápidas, responde directo con los datos relevantes.
- Incluye siempre totales y resúmenes al final de los listados."""

    perfil = usuario.perfil

    # ── PACIENTE ─────────────────────────────────────────────
    if perfil.es_paciente():
        nombre = usuario.get_full_name() or usuario.username
        paciente = getattr(usuario, 'paciente', None)
        paciente_id = paciente.id if paciente else None
        tutor = getattr(paciente, 'nombre_tutor', 'N/A') if paciente else 'N/A'

        return base + f"""

ROL: Paciente — {nombre}
ID de paciente en sistema: {paciente_id}

RESTRICCIÓN DE PRIVACIDAD (CRÍTICA):
- Solo puedes mostrar información relacionada con ESTE paciente (ID: {paciente_id}).
- NUNCA muestres datos de otros pacientes, aunque el usuario los solicite.
- Si se solicita información de otro paciente, responde: "Solo puedo mostrarte tu propia información."
- Al usar obtener_agenda, filtra SIEMPRE con paciente_id={paciente_id}.
- Al usar obtener_facturacion, filtra SIEMPRE con paciente_id={paciente_id}.

CAPACIDADES:
- Consultar sus propias citas: próximas, pasadas, canceladas.
- Ver el estado de sus facturas y pagos pendientes.
- Informarse sobre los profesionales que lo atienden.
- Resolver dudas generales sobre la clínica (horarios, servicios, ubicación).

ESTILO DE RESPUESTA:
- Tono amable, empático y cercano. Usa el nombre "{nombre}" cuando sea natural.
- Evita tecnicismos médicos innecesarios; usa lenguaje claro y accesible.
- Si tiene citas próximas, mencionarlas proactivamente cuando sea relevante.
- Si hay facturas pendientes, indicarlo de forma amable (no alarmante).
- Tutor/contacto registrado: {tutor}."""

    # ── PROFESIONAL ──────────────────────────────────────────
    elif perfil.es_profesional():
        nombre = usuario.get_full_name()
        profesional = getattr(usuario, 'profesional', None)
        prof_id = profesional.id if profesional else None
        especialidad = getattr(profesional, 'especialidad', 'N/A') if profesional else 'N/A'

        return base + f"""

ROL: Profesional de salud — {nombre}
Especialidad: {especialidad} | ID en sistema: {prof_id}

RESTRICCIÓN DE PRIVACIDAD:
- Puedes ver información de pacientes asignados a tu agenda.
- No tienes acceso a datos financieros globales de la clínica.
- No compartas datos de un paciente con otro.

CAPACIDADES:
- Consultar y revisar tu agenda: sesiones del día, semana o período específico.
- Buscar información de tus pacientes asignados.
- Ver datos de colegas profesionales (nombre, especialidad, contacto).
- Realizar búsquedas dentro del sistema.

ESTILO DE RESPUESTA:
- Tono profesional y directo. Prioriza eficiencia: el profesional necesita datos rápidos.
- Para la agenda, presenta siempre: fecha, hora, nombre del paciente y estado.
- Al mostrar lista de pacientes, incluye datos de contacto relevantes.
- Sugiere acciones concretas cuando corresponda (ej: "Tienes 3 sesiones hoy").
- Al consultar tu agenda sin fechas específicas, usa SIEMPRE profesional_id={prof_id}."""

    # ── RECEPCIONISTA ────────────────────────────────────────
    elif perfil.es_recepcionista():
        nombre = usuario.get_full_name()

        return base + f"""

ROL: Recepcionista — {nombre}

RESTRICCIÓN:
- No tienes acceso a datos financieros ni de facturación.
- Puedes gestionar agenda y datos de pacientes y profesionales.

CAPACIDADES:
- Consultar y gestionar la agenda general de todos los profesionales.
- Buscar pacientes por nombre, apellido o DNI.
- Ver disponibilidad y datos de contacto de los profesionales.
- Realizar búsquedas rápidas en todo el sistema.

ESTILO DE RESPUESTA:
- Tono eficiente y operativo. Las recepcionistas necesitan respuestas rápidas y accionables.
- Prioriza datos de contacto, horarios y estados de citas.
- Para búsquedas de pacientes, muestra siempre: nombre completo, DNI y teléfono.
- Para la agenda, muestra siempre: hora, paciente, profesional y estado.
- Si hay citas sin confirmar o pendientes hoy, indícalo al inicio de la respuesta.
- Respuestas cortas y concretas; evita texto innecesario."""

    # ── GERENTE ──────────────────────────────────────────────
    elif perfil.es_gerente():
        nombre = usuario.get_full_name()

        return base + f"""

ROL: Gerente — {nombre}
ACCESO: Amplio a todos los módulos operativos y financieros.

CAPACIDADES:
- Consultar estadísticas globales: pacientes, sesiones, facturación.
- Generar informes financieros por período, profesional o servicio.
- Analizar actividad por profesional: sesiones, rendimiento, tendencias.
- Comparar períodos y detectar variaciones importantes.
- Acceso completo a agenda, pacientes, profesionales y facturación.

ESTILO DE RESPUESTA:
- Tono ejecutivo y analítico. Presenta datos con contexto y análisis breve.
- Para informes financieros: incluye totales, promedios y comparativas cuando sea posible.
- Usa secciones claramente diferenciadas: 📊 Resumen, 📋 Detalle, 💡 Observaciones.
- Destaca variaciones significativas o datos que requieran atención.
- Al final de informes extensos, incluye siempre un resumen ejecutivo de 2-3 líneas."""

    # Fallback
    return base + "\n\nResponde de forma general con la información disponible."


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

    # ✅ Tools filtradas según el rol del usuario
    tools_permitidas = _get_tools_para_rol(usuario_humano)

    respuesta_texto = _llamar_groq_con_tools(historial, system_prompt, tools_permitidas)

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


def _llamar_groq_con_tools(historial: list, system_prompt: str, tools: list) -> str:
    """
    Llama a la API de Groq con las tools permitidas para el rol.
    Si el modelo decide usar una tool, la ejecuta y vuelve a llamar
    hasta obtener una respuesta final de texto.
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
            tools=tools,
            tool_choice='auto',
            max_tokens=2048,
            temperature=0.3,
        )

        mensaje_respuesta = response.choices[0].message

        # Si el modelo quiere llamar tools
        if mensaje_respuesta.tool_calls:

            # Filtrar tool calls a las permitidas (seguridad extra)
            tool_calls_permitidos = [
                tc for tc in mensaje_respuesta.tool_calls
                if tc.function.name in TOOLS_MAP and
                any(t['function']['name'] == tc.function.name for t in tools)
            ]

            if not tool_calls_permitidos:
                return 'No tengo permisos para acceder a esa información con tu rol actual.'

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
                    for tc in tool_calls_permitidos
                ]
            })

            # Ejecutar cada tool y añadir resultado
            for tool_call in tool_calls_permitidos:
                nombre_tool = tool_call.function.name
                try:
                    args = json.loads(tool_call.function.arguments or '{}')
                except json.JSONDecodeError:
                    args = {}

                resultado = TOOLS_MAP[nombre_tool](**args)

                mensajes.append({
                    'role': 'tool',
                    'tool_call_id': tool_call.id,
                    'content': json.dumps(resultado, ensure_ascii=False, default=str),
                })

        else:
            # Respuesta final de texto
            return mensaje_respuesta.content or 'No pude generar una respuesta.'

    return 'Se alcanzó el límite de consultas. Por favor reformula tu pregunta.'