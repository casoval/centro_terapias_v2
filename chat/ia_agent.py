"""
Agente IA para el sistema de chat interno.
Motor: Anthropic Claude (claude-haiku-4-5 para consultas simples, claude-sonnet-4-5 para complejas)
Acceso a BD: via tools que el agente llama dinámicamente
✅ Migrado de Groq/Llama a Anthropic Claude
✅ Restricción de tools por rol + system prompts detallados por rol
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
    'buscar_en_sistema':    tool_buscar_en_sistema,
}

# ============================================================
# PERMISOS DE TOOLS POR ROL
# ============================================================

_TOOLS_POR_ROL = {
    'paciente':      ['obtener_agenda', 'obtener_facturacion'],
    'profesional':   ['obtener_agenda', 'obtener_pacientes', 'obtener_profesionales', 'buscar_en_sistema'],
    'recepcionista': ['obtener_agenda', 'obtener_pacientes', 'obtener_profesionales', 'buscar_en_sistema'],
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

CAPACIDADES:
- Consultar sus propias citas: próximas, pasadas, canceladas.
- Ver el estado de sus facturas y pagos pendientes.
- Resolver dudas generales sobre la clínica.

ESTILO: Tono amable y cercano. Tutor registrado: {tutor}."""

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

def responder_con_ia(conversacion, usuario_humano):
    """
    Función principal. Llama a Claude con el historial de la conversación
    y ejecuta las tools necesarias. Guarda la respuesta como Mensaje.
    """
    from .models import Mensaje, NotificacionChat

    usuario_ia     = get_o_crear_usuario_ia()
    historial      = _construir_historial(conversacion, usuario_ia)
    system_prompt  = _get_system_prompt(usuario_humano)
    tools_permitidas = _get_tools_para_rol(usuario_humano)

    respuesta_texto = _llamar_claude_con_tools(historial, system_prompt, tools_permitidas)

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