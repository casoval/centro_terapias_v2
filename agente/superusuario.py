"""
agente/superusuario.py
Agente Superusuario — asistente privado e integral del dueño del Centro Misael.

Acceso TOTAL sin restricciones: pacientes, sesiones, finanzas, clínica, staff.

Modelos:
  - Sonnet: consultas rápidas del día a día
  - Opus:   informes detallados, análisis estratégico, asesoría compleja

El prompt se lee desde ConfigAgente en el admin de Django.
Se admiten dos entradas en BD:
  - agente='superusuario'  → prompt Sonnet (consultas rápidas)
  - Si el prompt de BD contiene la palabra OPUS_PROMPT: se usa para Opus
    (o se puede gestionar con un segundo campo en el futuro)

Por simplicidad actual: un solo prompt en BD que se usa tanto para Sonnet
como para Opus. El código fallback mantiene los dos prompts hardcodeados.
"""

import logging
from agente.agente_base import AgenteBase
from agente.superusuario_db import construir_contexto_superusuario

log = logging.getLogger('agente')

MODELO_SONNET = 'claude-sonnet-4-6'
MODELO_OPUS   = 'claude-opus-4-6'

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

# ── Prompts de respaldo (se usan solo si NO hay config en BD) ─────────────────

PROMPT_SONNET_FALLBACK = """Eres el asistente privado e inteligente de {nombre}, dueño del Centro Infantil Misael.

Eres sus "ojos en tiempo real" sobre el negocio. Acceso total y sin restricciones a:
pacientes, sesiones, pagos, ingresos, deudas, profesionales, mensualidades y más.

ROLES:
- Informador ejecutivo: datos precisos del centro al instante
- Asesor financiero: analiza ingresos, deudas, flujo de caja
- Asesor estratégico: crecimiento, marketing, captación de pacientes
- Asesor operativo: productividad del equipo, asistencia, eficiencia
- Orientación legal/contable general (siempre recomendando profesionales certificados para decisiones importantes)

TONO: Directo, ejecutivo. Llama a {nombre} por su nombre. Si ves algo preocupante en los datos,
menciónalo proactivamente. Usa números concretos. Sé conciso para consultas simples, profundo para análisis.

DATOS ACTUALIZADOS:
{contexto}
"""

PROMPT_OPUS_FALLBACK = """Eres el asesor estratégico e inteligente de {nombre}, dueño del Centro Infantil Misael.

Tienes acceso TOTAL a todos los datos del centro. Tu misión ahora es generar un análisis profundo,
detallado y de alto valor para {nombre}. Actúas como:

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
    if any(p in msg for p in PALABRAS_OPUS) or len(mensaje.split()) > 30:
        return MODELO_OPUS, 'Opus'
    return MODELO_SONNET, 'Sonnet'


class AgenteSuper(AgenteBase):
    TIPO = 'superusuario'

    def responder(self, telefono: str, mensaje: str, staff=None) -> str:
        try:
            # Leer nombre del dueño desde StaffAgente (admin de Django)
            nombre = 'estimado'
            if staff and hasattr(staff, 'nombre') and staff.nombre:
                nombre = staff.nombre.split()[0]  # Solo el primer nombre

            contexto = construir_contexto_superusuario(mensaje)
            modelo, etiqueta = _elegir_modelo(mensaje)
            max_tokens = 2000 if etiqueta == 'Opus' else 800

            # ── Prompt desde BD, con fallback hardcodeado ─────────────────────
            prompt_base = self.get_prompt()
            if prompt_base:
                prompt = prompt_base.format(nombre=nombre, contexto=contexto)
            else:
                log.warning('[Superusuario] Usando prompt hardcodeado — configura el prompt en el admin')
                fallback = PROMPT_OPUS_FALLBACK if etiqueta == 'Opus' else PROMPT_SONNET_FALLBACK
                prompt = fallback.format(nombre=nombre, contexto=contexto)

            self.guardar_mensaje(telefono, 'user', mensaje, origen='interno')
            historial = self.get_historial(telefono)
            log.info(f'[Superusuario] {telefono} | {etiqueta} | max_tokens={max_tokens} | {mensaje[:50]}')

            respuesta = self.llamar_claude(
                historial=historial, system_prompt=prompt,
                modelo=modelo, max_tokens=max_tokens,
            )

            self.guardar_mensaje(telefono, 'assistant', respuesta, f'{etiqueta.lower()}-superusuario', origen='interno')
            self.log_respuesta(telefono, respuesta, extra=etiqueta)
            return respuesta

        except Exception as e:
            log.error(f'[Superusuario] Error para {telefono}: {e}', exc_info=True)
            fallback = self.fallback_mensaje()
            self.guardar_mensaje(telefono, 'assistant', fallback, 'error', origen='interno')
            return fallback


class AgenteRecepcionistaProfesional(AgenteBase):
    """
    Agente combinado para usuarios con rol recepcionista + profesional vinculado.
    Combina el acceso clínico del profesional con el financiero de la recepcionista.
    """
    TIPO = 'recepcionista'

    PROMPT_FALLBACK = """Eres el asistente del Centro Infantil Misael para {nombre},
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

            ctx_r = ctx_recep(staff, mensaje)
            ctx_p = ctx_prof(staff, mensaje) if prof else ''
            contexto = ctx_r
            if ctx_p and ctx_p != ctx_r:
                contexto += f'\n\n--- INFORMACIÓN CLÍNICA (como profesional) ---\n{ctx_p}'

            modelo, etiqueta = _elegir_modelo(mensaje)

            # ── Prompt desde BD (usa el de recepcionista), con fallback ───────
            prompt_base = self.get_prompt()
            if prompt_base:
                prompt = prompt_base.format(
                    nombre          = nombre,
                    especialidad    = espec,
                    sucursal_propia = suc_prop,
                    contexto        = contexto,
                )
            else:
                prompt = self.PROMPT_FALLBACK.format(
                    nombre          = nombre,
                    especialidad    = espec,
                    sucursal_propia = suc_prop,
                    contexto        = contexto,
                )

            self.guardar_mensaje(telefono, 'user', mensaje, origen='interno')
            historial = self.get_historial(telefono)
            log.info(f'[Recep+Prof] {telefono} | {nombre} | {etiqueta} | {mensaje[:50]}')

            respuesta = self.llamar_claude(
                historial=historial, system_prompt=prompt,
                modelo=modelo, max_tokens=650,
            )
            self.guardar_mensaje(telefono, 'assistant', respuesta, f'{etiqueta.lower()}-recep-prof', origen='interno')
            self.log_respuesta(telefono, respuesta)
            return respuesta

        except Exception as e:
            log.error(f'[Recep+Prof] Error para {telefono}: {e}', exc_info=True)
            fallback = self.fallback_mensaje()
            self.guardar_mensaje(telefono, 'assistant', fallback, 'error', origen='interno')
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