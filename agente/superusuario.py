"""
agente/superusuario.py
Agente Superusuario — asistente privado e integral del dueño del Centro Misael.

Acceso TOTAL sin restricciones: pacientes, sesiones, finanzas, clínica, staff.

Modelos:
  - Sonnet: consultas rápidas del día a día
  - Opus:   informes detallados, análisis estratégico, asesoría compleja

Roles del agente:
  - Informador: datos en tiempo real de todo el centro
  - Asesor financiero: ingresos, deudas, flujo de caja, rentabilidad
  - Asesor estratégico: crecimiento, marketing, captación de pacientes
  - Asesor operativo: productividad, asistencia, eficiencia
  - Asesor legal/contable: orientación general (no reemplaza profesionales)
  - Generador de informes: reportes completos y detallados con Opus
"""

import logging
from agente.agente_base import AgenteBase
from agente.superusuario_db import construir_contexto_superusuario

log = logging.getLogger('agente')

MODELO_SONNET = 'claude-sonnet-4-6'
MODELO_OPUS   = 'claude-opus-4-6'

# Palabras que activan Opus (análisis complejo / informes / asesoría estratégica)
PALABRAS_OPUS = (
    'informe', 'reporte', 'análisis', 'analisis', 'detallado', 'detalla',
    'completo', 'completa', 'resumen ejecutivo', 'genera', 'generar',
    'estrategia', 'plan', 'planificación', 'planificacion',
    'proyección', 'proyeccion', 'proyectar', 'comparar meses',
    'evaluación financiera', 'evaluacion financiera',
    'asesoría', 'asesoria', 'recomienda', 'recomendación', 'recomendacion',
    'qué debería', 'que deberia', 'cómo mejorar', 'como mejorar',
    'problema', 'solución', 'solucion', 'oportunidad', 'riesgo',
    'flujo de caja', 'rentabilidad', 'roi', 'captación', 'captacion',
    'marketing', 'publicidad', 'crecer', 'crecimiento', 'expansión', 'expansion',
    'legal', 'contrato', 'obligaciones', 'impuesto', 'tributario',
    'contador', 'contabilidad', 'balance general', 'estado de resultados',
    'mes completo', 'año completo', 'anual', 'trimestral',
    'todos los pacientes', 'todos los profesionales',
)

PROMPT_SONNET = """Eres el asistente privado e inteligente del dueño del Centro Infantil Misael.

Eres sus "ojos en tiempo real" sobre el negocio. Acceso total y sin restricciones a:
pacientes, sesiones, pagos, ingresos, deudas, profesionales, mensualidades y más.

ROLES:
- Informador ejecutivo: datos precisos del centro al instante
- Asesor financiero: analiza ingresos, deudas, flujo de caja
- Asesor estratégico: crecimiento, marketing, captación de pacientes
- Asesor operativo: productividad del equipo, asistencia, eficiencia
- Orientación legal/contable general (siempre recomendando profesionales certificados para decisiones importantes)

TONO: Directo, ejecutivo. Si ves algo preocupante en los datos, menciónalo proactivamente.
Usa números concretos. Sé conciso para consultas simples, profundo para análisis.

DATOS ACTUALIZADOS:
{contexto}
"""

PROMPT_OPUS = """Eres el asesor estratégico e inteligente del dueño del Centro Infantil Misael.

Tienes acceso TOTAL a todos los datos del centro. Tu misión ahora es generar un análisis profundo,
detallado y de alto valor. Actúas como:

🏦 ASESOR FINANCIERO: Analiza ingresos, deudas, flujo de caja, rentabilidad por servicio/sucursal.
   Detecta tendencias, riesgos financieros y oportunidades de mejora.

📈 ASESOR DE MARKETING Y CRECIMIENTO: Evalúa captación de pacientes, retención, servicios más
   demandados, horarios pico, potencial de expansión.

⚖️ ASESOR LEGAL/CONTABLE (orientación general): Señala aspectos que requieren atención legal
   o contable, siempre recomendando verificar con profesionales certificados.

🏥 ASESOR OPERATIVO: Evalúa productividad del equipo, asistencia, eficiencia de sesiones,
   profesionales con mayor/menor rendimiento.

INSTRUCCIONES PARA INFORMES:
- Estructura el informe con secciones claras
- Incluye números, porcentajes y comparativas cuando estén disponibles
- Destaca hallazgos importantes con 🔴 (urgente), 🟡 (atención) o 🟢 (positivo)
- Termina SIEMPRE con: "RECOMENDACIONES PRIORITARIAS" (máx. 3 acciones concretas)
- Si faltan datos, indícalo y sugiere cómo obtenerlos

DATOS COMPLETOS DEL CENTRO:
{contexto}
"""


def _elegir_modelo(mensaje: str) -> tuple[str, str]:
    msg = mensaje.lower()
    # Opus si el mensaje es largo O contiene palabras clave de análisis profundo
    if any(p in msg for p in PALABRAS_OPUS) or len(mensaje.split()) > 30:
        return MODELO_OPUS, 'Opus'
    return MODELO_SONNET, 'Sonnet'


class AgenteSuper(AgenteBase):
    TIPO = 'superusuario'

    def responder(self, telefono: str, mensaje: str, staff=None) -> str:
        try:
            contexto = construir_contexto_superusuario(mensaje)
            modelo, etiqueta = _elegir_modelo(mensaje)

            # Elegir el prompt según el modelo
            prompt_template = PROMPT_OPUS if etiqueta == 'Opus' else PROMPT_SONNET
            prompt = prompt_template.format(contexto=contexto)

            self.guardar_mensaje(telefono, 'user', mensaje)
            historial = self.get_historial(telefono)

            # Opus necesita más tokens para informes detallados
            max_tokens = 2000 if etiqueta == 'Opus' else 800

            log.info(f'[Superusuario] {telefono} | {etiqueta} | max_tokens={max_tokens} | {mensaje[:50]}')

            respuesta = self.llamar_claude(
                historial=historial, system_prompt=prompt,
                modelo=modelo, max_tokens=max_tokens,
            )

            self.guardar_mensaje(telefono, 'assistant', respuesta, f'{etiqueta.lower()}-superusuario')
            self.log_respuesta(telefono, respuesta, extra=etiqueta)
            return respuesta

        except Exception as e:
            log.error(f'[Superusuario] Error para {telefono}: {e}', exc_info=True)
            fallback = self.fallback_mensaje()
            self.guardar_mensaje(telefono, 'assistant', fallback, 'error')
            return fallback


# Agente combinado Recepcionista+Profesional
# Tiene acceso a TODO: clínica (profesional) + finanzas (recepcionista)
class AgenteRecepcionistaProfesional(AgenteBase):
    """
    Agente combinado para usuarios con rol recepcionista + profesional vinculado.
    Combina el acceso clínico del profesional con el financiero de la recepcionista.
    """
    TIPO = 'recepcionista'  # Guarda en historial como recepcionista

    PROMPT = """Eres el asistente del Centro Infantil Misael para {nombre},
quien cumple doble función: recepcionista y profesional ({especialidad}).

Como RECEPCIONISTA tienes acceso a:
- Agenda, sesiones, estado de citas
- Pagos, deudas, saldos, facturación
- Información general de pacientes

Como PROFESIONAL tienes acceso adicional a:
- Evolución clínica y notas de sesión de tus pacientes
- Diagnósticos y evaluaciones de tus pacientes
- Historial terapéutico

TONO: Eficiente y profesional.
Sucursal: {sucursal_propia}

=== DATOS ===
{contexto}
"""

    def responder(self, telefono: str, mensaje: str, staff=None) -> str:
        try:
            from agente.staff_db import get_nombre_sucursales
            from agente.recepcionista import _construir_contexto as ctx_recep
            from agente.profesional import _construir_contexto as ctx_prof
            from agente.recepcionista import _elegir_modelo

            nombre   = staff.nombre if staff else 'Staff'
            prof     = staff.profesional if staff else None
            espec    = prof.especialidad if prof else '—'
            suc_prop = get_nombre_sucursales(staff) if staff else '—'

            # Combinar contextos: recepcionista (finanzas) + profesional (clínica)
            ctx_r = ctx_recep(staff, mensaje)
            ctx_p = ctx_prof(staff, mensaje) if prof else ''
            contexto = ctx_r
            if ctx_p and ctx_p != ctx_r:
                contexto += f'\n\n--- INFORMACIÓN CLÍNICA (como profesional) ---\n{ctx_p}'

            modelo, etiqueta = _elegir_modelo(mensaje)
            prompt = self.PROMPT.format(
                nombre          = nombre,
                especialidad    = espec,
                sucursal_propia = suc_prop,
                contexto        = contexto,
            )

            self.guardar_mensaje(telefono, 'user', mensaje)
            historial = self.get_historial(telefono)
            log.info(f'[Recep+Prof] {telefono} | {nombre} | {etiqueta} | {mensaje[:50]}')

            respuesta = self.llamar_claude(
                historial=historial, system_prompt=prompt,
                modelo=modelo, max_tokens=650,
            )
            self.guardar_mensaje(telefono, 'assistant', respuesta, f'{etiqueta.lower()}-recep-prof')
            self.log_respuesta(telefono, respuesta)
            return respuesta

        except Exception as e:
            log.error(f'[Recep+Prof] Error para {telefono}: {e}', exc_info=True)
            fallback = self.fallback_mensaje()
            self.guardar_mensaje(telefono, 'assistant', fallback, 'error')
            return fallback


# Instancias singleton
_agente_super = None
_agente_combo = None

def get_agente() -> AgenteSuper:
    global _agente_super
    if _agente_super is None:
        _agente_super = AgenteSuper()
    return _agente_super

def get_agente_combinado() -> AgenteRecepcionistaProfesional:
    global _agente_combo
    if _agente_combo is None:
        _agente_combo = AgenteRecepcionistaProfesional()
    return _agente_combo

def responder(telefono: str, mensaje: str, staff=None) -> str:
    return get_agente().responder(telefono, mensaje, staff=staff)

def responder_combinado(telefono: str, mensaje: str, staff=None) -> str:
    return get_agente_combinado().responder(telefono, mensaje, staff=staff)