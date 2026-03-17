"""
Modelos para la sistematización de evaluaciones ADOS-2 y ADI-R.
Vinculados al modelo Paciente de la app 'pacientes'.
"""

from django.db import models
from profesionales.models import Profesional
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from decimal import Decimal


# ─────────────────────────────────────────────
# Helpers de validación de rango 0-3, 0-2
# ─────────────────────────────────────────────

def val_0_3():
    return [MinValueValidator(0), MaxValueValidator(3)]

def val_0_2():
    return [MinValueValidator(0), MaxValueValidator(2)]

def val_0_1():
    return [MinValueValidator(0), MaxValueValidator(1)]


def item(max_val=3, label='', help_text=''):
    """Campo de ítem de evaluación, entero nullable."""
    validators = [MinValueValidator(0), MaxValueValidator(max_val)]
    return models.IntegerField(
        verbose_name=label,
        help_text=help_text,
        validators=validators,
        null=True,
        blank=True,
    )


# ═══════════════════════════════════════════════════════════════
# EVALUACIÓN ADOS-2
# ═══════════════════════════════════════════════════════════════

class EvaluacionADOS2(models.Model):
    """
    Evaluación ADOS-2 (Autism Diagnostic Observation Schedule, 2nd Edition).
    Cubre los módulos 1, 2, 3, 4 y T (Toddler).
    Cada módulo tiene sus propios ítems y puntos de corte.
    """

    MODULO_CHOICES = [
        ('T', 'Módulo T — Niños pequeños (12-30 meses)'),
        ('1', 'Módulo 1 — Sin lenguaje consistente'),
        ('2', 'Módulo 2 — Lenguaje frasal'),
        ('3', 'Módulo 3 — Lenguaje fluido, niños/adolescentes'),
        ('4', 'Módulo 4 — Lenguaje fluido, adultos'),
    ]

    CLASIFICACION_CHOICES = [
        ('no_espectro', 'No espectro'),
        ('espectro', 'Espectro autista'),
        ('autismo', 'Autismo'),
        ('leve_moderado', 'Leve a moderado'),
        ('pendiente', 'Pendiente de cálculo'),
    ]

    # ── Datos generales ──────────────────────────────────────────
    paciente = models.ForeignKey(
        'pacientes.Paciente',
        on_delete=models.CASCADE,
        related_name='evaluaciones_ados2',
        verbose_name='Paciente',
        # Busca por nombre_completo (property) en formularios
    )
    evaluador = models.ForeignKey(
        Profesional,
        on_delete=models.PROTECT,
        related_name='evaluaciones_ados2_realizadas',
        verbose_name='Evaluador',
    )
    modulo = models.CharField(max_length=2, choices=MODULO_CHOICES, verbose_name='Módulo')
    fecha_evaluacion = models.DateField(verbose_name='Fecha de evaluación', default=timezone.now)

    # Edad cronológica en el momento de la evaluación
    # (calculada automáticamente desde Paciente.fecha_nacimiento si se deja en 0)
    edad_cronologica_anos = models.PositiveSmallIntegerField(
        verbose_name='Años (edad al momento de la evaluación)', default=0)
    edad_cronologica_meses = models.PositiveSmallIntegerField(
        verbose_name='Meses adicionales', default=0,
        validators=[MaxValueValidator(11)]
    )
    contexto_evaluacion = models.TextField(
        verbose_name='Contexto / observaciones generales',
        blank=True
    )

    # ── MÓDULO 1 — Ítems ─────────────────────────────────────────
    # Dominio A: Comunicación
    m1_A1_uso_funcional_comunicativo = item(2, 'A1. Uso funcional comunicativo')
    m1_A2_cantidad_vocalizaciones = item(2, 'A2. Cantidad de vocalizaciones sociales/comunicativas')
    m1_A3_vocalizaciones_con_palabras = item(2, 'A3. Vocalizaciones con palabras o aproximaciones')
    m1_A4_senar_con_dedo = item(2, 'A4. Señalar con el dedo índice')
    m1_A5_gestos = item(2, 'A5. Gestos')
    m1_A6_accion_coordinada = item(2, 'A6. Acción coordinada y atención conjunta')
    m1_A7_uso_del_cuerpo_del_otro = item(2, 'A7. Uso del cuerpo del otro como herramienta')
    m1_A8_dar_y_mostrar = item(2, 'A8. Dar y mostrar')

    # Dominio B: Interacción social recíproca
    m1_B1_contacto_visual_inusual = item(2, 'B1. Contacto visual inusual')
    m1_B2_sonrisa_social_responsiva = item(2, 'B2. Sonrisa social responsiva')
    m1_B3_disfrute_compartido = item(2, 'B3. Disfrute en la interacción / disfrute compartido')
    m1_B4_iniciacion_atencion_conjunta = item(2, 'B4. Iniciación de atención conjunta')
    m1_B5_respuesta_atencion_conjunta = item(2, 'B5. Respuesta a la atención conjunta')
    m1_B6_calidad_acercamientos = item(2, 'B6. Calidad de los acercamientos sociales')
    m1_B7_comprension_de_comunicacion = item(2, 'B7. Comprensión de comunicación')
    m1_B8_imitacion = item(2, 'B8. Imitación')
    m1_B9_juego_funcional = item(2, 'B9. Juego funcional con objetos')
    m1_B10_juego_simbolico = item(2, 'B10. Juego simbólico / imaginativo')

    # Dominio C: Comportamientos restringidos y repetitivos (solo para CSS, no clasificación)
    m1_C1_intereses_inusuales = item(2, 'C1. Intereses sensoriales inusuales')
    m1_C2_manierismos_mano_dedos = item(2, 'C2. Manierismos con manos/dedos')
    m1_C3_comportamiento_repetitivo = item(2, 'C3. Comportamiento repetitivo con objetos')

    # ── MÓDULO 2 — Ítems ─────────────────────────────────────────
    # Dominio A: Comunicación
    m2_A1_espontaneidad_del_lenguaje = item(2, 'A1. Espontaneidad del lenguaje')
    m2_A2_preguntas_directas = item(2, 'A2. Respuesta a preguntas directas')
    m2_A3_produccion_narrativa = item(2, 'A3. Producción de narrativa')
    m2_A4_uso_comunicativo_gestos = item(2, 'A4. Uso comunicativo de gestos')
    m2_A5_contacto_visual_inusual = item(2, 'A5. Contacto visual inusual')
    m2_A6_expresiones_faciales_dirigidas = item(2, 'A6. Expresiones faciales dirigidas hacia otros')

    # Dominio B: Interacción social recíproca
    m2_B1_disfrute_compartido = item(2, 'B1. Disfrute en la interacción / disfrute compartido')
    m2_B2_atencion_conjunta = item(2, 'B2. Atención conjunta durante la prueba')
    m2_B3_calidad_acercamientos = item(2, 'B3. Calidad de los acercamientos sociales')
    m2_B4_comprension_comunicacion = item(2, 'B4. Comprensión de comunicación')
    m2_B5_imitacion = item(2, 'B5. Imitación')
    m2_B6_juego_imaginativo = item(2, 'B6. Juego imaginativo')
    m2_B7_respuesta_nombre = item(2, 'B7. Respuesta al nombre')

    # Dominio C: Comportamientos restringidos y repetitivos
    m2_C1_intereses_inusuales = item(2, 'C1. Intereses sensoriales inusuales')
    m2_C2_manierismos_mano_dedos = item(2, 'C2. Manierismos con manos/dedos')
    m2_C3_comportamiento_repetitivo = item(2, 'C3. Comportamiento repetitivo con objetos')

    # ── MÓDULO 3 — Ítems ─────────────────────────────────────────
    # Dominio A: Comunicación
    m3_A1_espontaneidad_lenguaje = item(2, 'A1. Espontaneidad del lenguaje')
    m3_A2_reporte_eventos = item(2, 'A2. Reporte de eventos')
    m3_A3_conversacion = item(2, 'A3. Conversación')
    m3_A4_gestos_descriptivos = item(2, 'A4. Gestos descriptivos, convencionales, instrumentales')
    m3_A5_contacto_visual_inusual = item(2, 'A5. Contacto visual inusual')
    m3_A6_expresiones_faciales = item(2, 'A6. Expresiones faciales dirigidas hacia otros')

    # Dominio B: Interacción social recíproca
    m3_B1_disfrute_compartido = item(2, 'B1. Disfrute en la interacción')
    m3_B2_perspectiva = item(2, 'B2. Perspectiva / insight')
    m3_B3_responsividad_emocional = item(2, 'B3. Responsividad socioemocional')
    m3_B4_calidad_acercamientos = item(2, 'B4. Calidad de los acercamientos sociales')
    m3_B5_cantidad_iniciacion = item(2, 'B5. Cantidad de iniciación social')
    m3_B6_narrativa_global = item(2, 'B6. Narrativa global')

    # Dominio C: Comportamientos restringidos y repetitivos
    m3_C1_intereses_inusuales = item(2, 'C1. Intereses sensoriales inusuales')
    m3_C2_manierismos_mano_dedos = item(2, 'C2. Manierismos con manos/dedos')
    m3_C3_comportamiento_repetitivo = item(2, 'C3. Comportamiento repetitivo con objetos')

    # ── MÓDULO 4 — Ítems ─────────────────────────────────────────
    # Dominio A: Comunicación
    m4_A1_lenguaje = item(2, 'A1. Espontaneidad del lenguaje')
    m4_A2_reporte_eventos = item(2, 'A2. Reporte de eventos')
    m4_A3_conversacion = item(2, 'A3. Conversación')
    m4_A4_gestos = item(2, 'A4. Gestos descriptivos, convencionales, instrumentales')
    m4_A5_contacto_visual = item(2, 'A5. Contacto visual inusual')
    m4_A6_expresiones_faciales = item(2, 'A6. Expresiones faciales dirigidas hacia otros')

    # Dominio B: Interacción social recíproca
    m4_B1_disfrute_compartido = item(2, 'B1. Disfrute en la interacción')
    m4_B2_perspectiva = item(2, 'B2. Perspectiva / insight')
    m4_B3_responsividad_emocional = item(2, 'B3. Responsividad socioemocional')
    m4_B4_calidad_acercamientos = item(2, 'B4. Calidad de los acercamientos sociales')
    m4_B5_cantidad_iniciacion = item(2, 'B5. Cantidad de iniciación social')
    m4_B6_narrativa_global = item(2, 'B6. Narrativa global')
    m4_B7_responsividad_examinador = item(2, 'B7. Responsividad al examinador')

    # Dominio C: Comportamientos restringidos y repetitivos
    m4_C1_intereses_inusuales = item(2, 'C1. Intereses sensoriales inusuales')
    m4_C2_manierismos_mano_dedos = item(2, 'C2. Manierismos con manos/dedos')
    m4_C3_comportamiento_repetitivo = item(2, 'C3. Comportamiento repetitivo con objetos')

    # ── MÓDULO T — Ítems ─────────────────────────────────────────
    mt_A1_vocalizacion_social = item(2, 'A1. Vocalización social / frecuencia comunicativa')
    mt_A2_senal_con_dedo = item(2, 'A2. Señalar con el dedo índice')
    mt_A3_accion_coordinada = item(2, 'A3. Acción coordinada y atención conjunta')
    mt_A4_uso_cuerpo_otro = item(2, 'A4. Uso del cuerpo del otro')
    mt_A5_palabras_o_frases = item(2, 'A5. Palabras o frases')
    mt_B1_contacto_visual = item(2, 'B1. Contacto visual inusual')
    mt_B2_sonrisa_responsiva = item(2, 'B2. Sonrisa social responsiva')
    mt_B3_disfrute_compartido = item(2, 'B3. Disfrute compartido')
    mt_B4_iniciacion_atencion = item(2, 'B4. Iniciación de atención conjunta')
    mt_B5_respuesta_nombre = item(2, 'B5. Respuesta al nombre')
    mt_B6_juego_funcional = item(2, 'B6. Juego funcional con objetos')
    mt_C1_intereses_inusuales = item(2, 'C1. Intereses sensoriales inusuales')
    mt_C2_manierismos = item(2, 'C2. Manierismos')

    # ── Puntuaciones calculadas ───────────────────────────────────
    total_comunicacion = models.IntegerField(
        verbose_name='Total Comunicación', null=True, blank=True)
    total_interaccion_social = models.IntegerField(
        verbose_name='Total Interacción Social', null=True, blank=True)
    total_comunicacion_social = models.IntegerField(
        verbose_name='Total Comunicación + Interacción Social (SA)', null=True, blank=True)
    total_comportamiento_restringido = models.IntegerField(
        verbose_name='Total Comportamiento Restringido y Repetitivo (RRB)', null=True, blank=True)
    comparison_score = models.IntegerField(
        verbose_name='Puntuación de Comparación (CSS)', null=True, blank=True,
        help_text='Escala 1-10. CSS ≥ 4 = espectro; CSS ≥ 7 = autismo (aprox.)'
    )

    # ── Clasificación ─────────────────────────────────────────────
    clasificacion = models.CharField(
        max_length=30,
        choices=CLASIFICACION_CHOICES,
        default='pendiente',
        verbose_name='Clasificación diagnóstica ADOS-2',
    )

    # ── Metadatos ────────────────────────────────────────────────
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)
    observaciones = models.TextField(blank=True, verbose_name='Observaciones clínicas adicionales')

    class Meta:
        verbose_name = 'Evaluación ADOS-2'
        verbose_name_plural = 'Evaluaciones ADOS-2'
        ordering = ['-fecha_evaluacion']

    def __str__(self):
        return f'ADOS-2 Módulo {self.modulo} — {self.paciente} ({self.fecha_evaluacion})'

    # ── Lógica de cálculo ────────────────────────────────────────

    def _suma_items(self, campos):
        """Suma una lista de campos del modelo, ignorando None."""
        total = 0
        for campo in campos:
            val = getattr(self, campo, None)
            if val is not None:
                total += val
        return total

    def calcular_puntuaciones(self):
        """
        Calcula totales de dominio y clasificación según el módulo seleccionado.
        Aplica el algoritmo diagnóstico ADOS-2 oficial.
        """
        m = self.modulo

        if m == '1':
            com_items = [
                'm1_A1_uso_funcional_comunicativo', 'm1_A4_senar_con_dedo',
                'm1_A5_gestos', 'm1_A6_accion_coordinada', 'm1_A8_dar_y_mostrar',
            ]
            soc_items = [
                'm1_B1_contacto_visual_inusual', 'm1_B2_sonrisa_social_responsiva',
                'm1_B3_disfrute_compartido', 'm1_B4_iniciacion_atencion_conjunta',
                'm1_B5_respuesta_atencion_conjunta', 'm1_B6_calidad_acercamientos',
            ]
            rrb_items = ['m1_C1_intereses_inusuales', 'm1_C2_manierismos_mano_dedos', 'm1_C3_comportamiento_repetitivo']

        elif m == '2':
            com_items = [
                'm2_A1_espontaneidad_del_lenguaje', 'm2_A2_preguntas_directas',
                'm2_A4_uso_comunicativo_gestos', 'm2_A5_contacto_visual_inusual',
            ]
            soc_items = [
                'm2_B1_disfrute_compartido', 'm2_B2_atencion_conjunta',
                'm2_B3_calidad_acercamientos', 'm2_B4_comprension_comunicacion',
                'm2_B6_juego_imaginativo',
            ]
            rrb_items = ['m2_C1_intereses_inusuales', 'm2_C2_manierismos_mano_dedos', 'm2_C3_comportamiento_repetitivo']

        elif m == '3':
            com_items = [
                'm3_A1_espontaneidad_lenguaje', 'm3_A2_reporte_eventos',
                'm3_A3_conversacion', 'm3_A5_contacto_visual_inusual',
            ]
            soc_items = [
                'm3_B1_disfrute_compartido', 'm3_B2_perspectiva',
                'm3_B3_responsividad_emocional', 'm3_B4_calidad_acercamientos',
                'm3_B5_cantidad_iniciacion',
            ]
            rrb_items = ['m3_C1_intereses_inusuales', 'm3_C2_manierismos_mano_dedos', 'm3_C3_comportamiento_repetitivo']

        elif m == '4':
            com_items = [
                'm4_A1_lenguaje', 'm4_A2_reporte_eventos',
                'm4_A3_conversacion', 'm4_A5_contacto_visual',
            ]
            soc_items = [
                'm4_B1_disfrute_compartido', 'm4_B2_perspectiva',
                'm4_B3_responsividad_emocional', 'm4_B4_calidad_acercamientos',
                'm4_B5_cantidad_iniciacion', 'm4_B7_responsividad_examinador',
            ]
            rrb_items = ['m4_C1_intereses_inusuales', 'm4_C2_manierismos_mano_dedos', 'm4_C3_comportamiento_repetitivo']

        elif m == 'T':
            com_items = [
                'mt_A1_vocalizacion_social', 'mt_A2_senal_con_dedo',
                'mt_A3_accion_coordinada', 'mt_A5_palabras_o_frases',
            ]
            soc_items = [
                'mt_B1_contacto_visual', 'mt_B2_sonrisa_responsiva',
                'mt_B3_disfrute_compartido', 'mt_B4_iniciacion_atencion',
                'mt_B5_respuesta_nombre',
            ]
            rrb_items = ['mt_C1_intereses_inusuales', 'mt_C2_manierismos']
        else:
            return

        self.total_comunicacion = self._suma_items(com_items)
        self.total_interaccion_social = self._suma_items(soc_items)
        self.total_comunicacion_social = self.total_comunicacion + self.total_interaccion_social
        self.total_comportamiento_restringido = self._suma_items(rrb_items)

        # Clasificación aproximada según puntos de corte ADOS-2 por módulo
        self.clasificacion = self._clasificar()

    def _clasificar(self):
        """
        Retorna clasificación basada en puntos de corte del manual ADOS-2.
        Los puntos de corte son del Total SA (Comunicación + Interacción Social).
        Referencia: Lord et al., 2012 — ADOS-2 Manual.
        """
        sa = self.total_comunicacion_social
        if sa is None:
            return 'pendiente'

        m = self.modulo

        # Puntos de corte SA por módulo (no espectro / espectro / autismo)
        cortes = {
            'T': (8, 12),
            '1': (12, 16),
            '2': (8, 12),
            '3': (7, 11),
            '4': (7, 11),
        }

        bajo, alto = cortes.get(m, (999, 999))

        if sa < bajo:
            return 'no_espectro'
        elif sa < alto:
            return 'espectro'
        else:
            return 'autismo'

    def get_clasificacion_display_color(self):
        colores = {
            'no_espectro': 'success',
            'espectro': 'warning',
            'autismo': 'danger',
            'leve_moderado': 'warning',
            'pendiente': 'secondary',
        }
        return colores.get(self.clasificacion, 'secondary')

    def save(self, *args, **kwargs):
        self.calcular_puntuaciones()
        super().save(*args, **kwargs)


# ═══════════════════════════════════════════════════════════════
# EVALUACIÓN ADI-R
# ═══════════════════════════════════════════════════════════════

class EvaluacionADIR(models.Model):
    """
    Evaluación ADI-R (Autism Diagnostic Interview — Revised).
    Entrevista semiestructurada a cuidadores/padres.
    93 ítems organizados en dominios A, B, C, D y secciones de desarrollo.
    Lord, Rutter & Le Couteur (1994).
    """

    TIPO_COMUNICACION_CHOICES = [
        ('verbal', 'Verbal (palabras espontáneas usadas regularmente)'),
        ('no_verbal', 'No verbal (sin lenguaje funcional)'),
    ]

    CLASIFICACION_CHOICES = [
        ('cumple', 'Cumple criterios para Autismo'),
        ('no_cumple', 'No cumple criterios para Autismo'),
        ('pendiente', 'Pendiente de cálculo'),
    ]

    # ── Datos generales ──────────────────────────────────────────
    paciente = models.ForeignKey(
        'pacientes.Paciente',
        on_delete=models.CASCADE,
        related_name='evaluaciones_adir',
        verbose_name='Paciente',
    )
    evaluador = models.ForeignKey(
        Profesional,
        on_delete=models.PROTECT,
        related_name='evaluaciones_adir_realizadas',
        verbose_name='Evaluador',
    )
    informante = models.CharField(
        max_length=100,
        verbose_name='Informante (nombre)',
        help_text='Persona que responde la entrevista (padre, madre, tutor...)'
    )
    relacion_informante = models.CharField(
        max_length=50,
        verbose_name='Relación con el evaluado',
        help_text='Ej: madre, padre, tutor legal',
        default=''
    )
    fecha_evaluacion = models.DateField(verbose_name='Fecha de evaluación', default=timezone.now)
    tipo_comunicacion = models.CharField(
        max_length=10,
        choices=TIPO_COMUNICACION_CHOICES,
        verbose_name='Tipo de comunicación del evaluado',
        help_text='Determina qué ítems del algoritmo aplican'
    )

    # ── SECCIÓN B: Historia del desarrollo y síntomas tempranos ───
    edad_primeras_palabras = models.PositiveSmallIntegerField(
        verbose_name='Edad primeras palabras (meses)', null=True, blank=True)
    edad_primeras_frases = models.PositiveSmallIntegerField(
        verbose_name='Edad primeras frases de 2+ palabras (meses)', null=True, blank=True)
    perdida_lenguaje = models.BooleanField(
        verbose_name='¿Hubo pérdida de lenguaje?', null=True, blank=True)
    edad_perdida_lenguaje = models.PositiveSmallIntegerField(
        verbose_name='Edad pérdida de lenguaje (meses)', null=True, blank=True)
    perdida_habilidades_sociales = models.BooleanField(
        verbose_name='¿Hubo pérdida de habilidades sociales?', null=True, blank=True)

    # ── DOMINIO A: Lenguaje y Comunicación ───────────────────────
    # Ítems 9-19 (lenguaje actual/más reciente)
    A9_jerga = item(3, 'A9. Jerga')
    A10_ecolalia_inmediata = item(3, 'A10. Ecolalia inmediata')
    A11_ecolalia_retardada = item(3, 'A11. Ecolalia retardada / frases estereotipadas')
    A12_inversion_pronominal = item(3, 'A12. Inversión pronominal')
    A13_neologismos = item(3, 'A13. Neologismos / lenguaje idiosincrático')
    A14_conversacion_reciproca = item(3, 'A14. Conversación recíproca social')
    A15_preguntas_inapropiadas = item(3, 'A15. Preguntas inapropiadas / comentarios')
    A16_uso_del_cuerpo = item(3, 'A16. Uso del cuerpo de otro como herramienta')
    A17_gesto_para_senalar = item(3, 'A17. Gesto para señalar — para pedir')
    A18_senalar_compartir = item(3, 'A18. Señalar para compartir interés')
    A19_cabeceo_si = item(3, 'A19. Cabeceo para decir sí')

    # Ítems para no verbales (sección adicional)
    A_nv1_vocaliza_para_pedir = item(3, 'A(NV)1. Vocalización para pedir')
    A_nv2_vocaliza_para_mostrar = item(3, 'A(NV)2. Vocalización para mostrar')
    A_nv3_otros_gestos = item(3, 'A(NV)3. Otros gestos para comunicar')

    # ── DOMINIO B: Interacción social recíproca ───────────────────
    # Ítems 20-36
    B20_juego_peer = item(3, 'B20. Fracaso en el juego con pares')
    B21_amistades = item(3, 'B21. Falta de amistades')
    B22_bsqueda_placer = item(3, 'B22. Falta de búsqueda de placer compartido')
    B23_oferta_consuelo = item(3, 'B23. Falta de oferta de consuelo')
    B24_calidad_acercamiento = item(3, 'B24. Calidad del acercamiento social')
    B25_respuesta_emociones = item(3, 'B25. Respuesta a las emociones de otros')
    B26_contacto_visual = item(3, 'B26. Contacto visual directo')
    B27_expresiones_faciales = item(3, 'B27. Expresiones faciales dirigidas')
    B28_sonrisa_social = item(3, 'B28. Sonrisa social responsiva')
    B29_atencion_conjunta = item(3, 'B29. Atencion conjunta')
    B30_seguimiento_senal = item(3, 'B30. Seguimiento de señal con dedo / mirada')
    B31_dar_mostrar = item(3, 'B31. Dar y mostrar')
    B32_juego_imaginativo = item(3, 'B32. Juego imaginativo — con otros')
    B33_interes_ninos = item(3, 'B33. Interés en otros niños')
    B34_respuesta_acercamiento = item(3, 'B34. Respuesta al acercamiento de niños')
    B35_juego_grupo = item(3, 'B35. Juego en grupo')
    B36_incapacidad_expresar = item(3, 'B36. Incapacidad para expresar emociones')

    # ── DOMINIO C: Comportamientos restringidos y repetitivos ──────
    # Ítems 67-93
    C67_preocupaciones_inusuales = item(3, 'C67. Preocupaciones / intereses inusuales')
    C68_adherencia_rutinas = item(3, 'C68. Adherencia a rutinas / resistencia al cambio')
    C69_intereses_circunscritos = item(3, 'C69. Intereses circunscritos')
    C70_ritual_compulsivo = item(3, 'C70. Ritual / comportamiento compulsivo')
    C71_estereotipias_mano_cuerpo = item(3, 'C71. Estereotipias de mano y cuerpo')
    C72_estereotipias_dedos = item(3, 'C72. Estereotipias de dedos / manierismos')
    C73_auto_agresion = item(3, 'C73. Comportamiento autolesivo')
    C74_uso_objetos = item(3, 'C74. Uso inusual de objetos')
    C75_alineamiento_girar = item(3, 'C75. Alineamiento / girar objetos')
    C76_apego_objetos = item(3, 'C76. Apego a objetos inusuales')
    C77_preocupacion_parte_objeto = item(3, 'C77. Preocupación por partes de objetos')
    C78_sensibilidad_ruido = item(3, 'C78. Sensibilidad inusual a ruidos')
    C79_sensibilidad_dolor = item(3, 'C79. Respuesta inusual al dolor')
    C80_sensibilidad_tactil = item(3, 'C80. Reacción inusual al tacto')
    C81_olfato_sabor = item(3, 'C81. Olfateo / contacto oral de objetos')
    C82_respuesta_visual = item(3, 'C82. Respuesta visual inusual')
    C83_examinacion_proximal = item(3, 'C83. Examinación proximal de objetos')
    C84_fascinacion_luz = item(3, 'C84. Fascinación por la luz / objetos giratorios')
    C85_respuesta_calor_frio = item(3, 'C85. Respuesta inusual a calor / frío')
    C86_gran_habilidad = item(3, 'C86. Gran habilidad especial')

    # Ítems de comportamiento en el periodo 4-5 años (retrospectivo)
    C87_preocupaciones_4_5 = item(3, 'C87. Preocupaciones (4-5 años)')
    C88_rutinas_4_5 = item(3, 'C88. Adherencia a rutinas (4-5 años)')
    C89_estereotipias_4_5 = item(3, 'C89. Estereotipias (4-5 años)')
    C90_compulsiones_4_5 = item(3, 'C90. Comportamiento compulsivo (4-5 años)')
    C91_autolesion_4_5 = item(3, 'C91. Autolesión (4-5 años)')

    # ── Puntuaciones del Algoritmo Diagnóstico ────────────────────
    # Comunicación (verbal o no verbal)
    algoritmo_comunicacion = models.IntegerField(
        verbose_name='Puntuación Algoritmo — Comunicación', null=True, blank=True)
    algoritmo_interaccion_social = models.IntegerField(
        verbose_name='Puntuación Algoritmo — Interacción Social', null=True, blank=True)
    algoritmo_comportamientos_rr = models.IntegerField(
        verbose_name='Puntuación Algoritmo — Comportamientos Restringidos y Repetitivos',
        null=True, blank=True)

    # Puntos de corte superados
    cumple_corte_comunicacion = models.BooleanField(null=True, blank=True)
    cumple_corte_interaccion = models.BooleanField(null=True, blank=True)
    cumple_corte_comportamiento = models.BooleanField(null=True, blank=True)
    cumple_criterio_edad_inicio = models.BooleanField(
        null=True, blank=True,
        verbose_name='Cumple criterio de inicio antes de los 36 meses'
    )

    # Clasificación
    clasificacion = models.CharField(
        max_length=20,
        choices=CLASIFICACION_CHOICES,
        default='pendiente',
        verbose_name='Clasificación ADI-R',
    )

    # ── Metadatos ────────────────────────────────────────────────
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)
    observaciones = models.TextField(blank=True, verbose_name='Observaciones clínicas')

    class Meta:
        verbose_name = 'Evaluación ADI-R'
        verbose_name_plural = 'Evaluaciones ADI-R'
        ordering = ['-fecha_evaluacion']

    def __str__(self):
        return f'ADI-R — {self.paciente} ({self.fecha_evaluacion})'

    # ── Algoritmo diagnóstico ─────────────────────────────────────

    def _suma_items(self, campos):
        total = 0
        for campo in campos:
            val = getattr(self, campo, None)
            if val is not None:
                # En ADI-R se convierten los 3 a 2 para el algoritmo
                total += min(val, 2)
        return total

    def calcular_algoritmo(self):
        """
        Calcula las puntuaciones del algoritmo diagnóstico ADI-R.
        Los ítems del algoritmo difieren según si el evaluado es verbal o no verbal.
        Referencia: Lord, Rutter & Le Couteur (1994). ADI-R Manual.
        """
        verbal = self.tipo_comunicacion == 'verbal'

        # ── Algoritmo Comunicación ─────────────────────────
        if verbal:
            com_items = [
                'A11_ecolalia_retardada', 'A12_inversion_pronominal',
                'A13_neologismos', 'A14_conversacion_reciproca',
                'A17_gesto_para_senalar', 'A18_senalar_compartir',
                'A19_cabeceo_si',
            ]
            corte_com = 8
        else:
            com_items = [
                'A_nv1_vocaliza_para_pedir', 'A_nv2_vocaliza_para_mostrar',
                'A_nv3_otros_gestos', 'A17_gesto_para_senalar',
                'A18_senalar_compartir',
            ]
            corte_com = 7

        # ── Algoritmo Interacción Social ───────────────────
        soc_items = [
            'B22_bsqueda_placer', 'B26_contacto_visual',
            'B27_expresiones_faciales', 'B28_sonrisa_social',
            'B29_atencion_conjunta', 'B31_dar_mostrar',
            'B32_juego_imaginativo',
        ]
        corte_soc = 10

        # ── Algoritmo Comportamientos RR ──────────────────
        rrb_items = [
            'C67_preocupaciones_inusuales', 'C68_adherencia_rutinas',
            'C69_intereses_circunscritos', 'C70_ritual_compulsivo',
            'C71_estereotipias_mano_cuerpo', 'C72_estereotipias_dedos',
        ]
        corte_rrb = 3

        self.algoritmo_comunicacion = self._suma_items(com_items)
        self.algoritmo_interaccion_social = self._suma_items(soc_items)
        self.algoritmo_comportamientos_rr = self._suma_items(rrb_items)

        self.cumple_corte_comunicacion = self.algoritmo_comunicacion >= corte_com
        self.cumple_corte_interaccion = self.algoritmo_interaccion_social >= corte_soc
        self.cumple_corte_comportamiento = self.algoritmo_comportamientos_rr >= corte_rrb

        # Criterio de inicio antes de 36 meses
        # (presencia de anormalidades antes de los 36 meses según items de historia)
        self.cumple_criterio_edad_inicio = self._evaluar_inicio_temprano()

        # Clasificación final
        if all([
            self.cumple_corte_comunicacion,
            self.cumple_corte_interaccion,
            self.cumple_corte_comportamiento,
            self.cumple_criterio_edad_inicio,
        ]):
            self.clasificacion = 'cumple'
        elif any([
            self.cumple_corte_comunicacion is None,
            self.cumple_corte_interaccion is None,
            self.cumple_corte_comportamiento is None,
        ]):
            self.clasificacion = 'pendiente'
        else:
            self.clasificacion = 'no_cumple'

    def _evaluar_inicio_temprano(self):
        """
        Verifica si hay evidencia de inicio de síntomas antes de los 36 meses.
        Basado en ítems de historia del desarrollo.
        """
        # Si edad de primeras palabras es None, no podemos evaluar
        if self.edad_primeras_palabras is None:
            return None

        # Indicadores de inicio temprano
        indicadores = []

        # Lenguaje tardío
        if self.edad_primeras_palabras is not None:
            indicadores.append(self.edad_primeras_palabras > 24)

        # Pérdida de lenguaje antes de los 36 meses
        if self.perdida_lenguaje and self.edad_perdida_lenguaje:
            indicadores.append(self.edad_perdida_lenguaje < 36)

        return any(indicadores) if indicadores else None

    def get_clasificacion_color(self):
        return {'cumple': 'danger', 'no_cumple': 'success', 'pendiente': 'secondary'}.get(
            self.clasificacion, 'secondary')

    def save(self, *args, **kwargs):
        self.calcular_algoritmo()
        super().save(*args, **kwargs)


# ═══════════════════════════════════════════════════════════════
# INFORME COMBINADO
# ═══════════════════════════════════════════════════════════════

class InformeEvaluacion(models.Model):
    """
    Informe clínico combinado que puede incluir una evaluación ADOS-2
    y/o una evaluación ADI-R, generando un documento PDF final.
    """

    ESTADO_CHOICES = [
        ('borrador', 'Borrador'),
        ('revision', 'En revisión'),
        ('finalizado', 'Finalizado'),
    ]

    paciente = models.ForeignKey(
        'pacientes.Paciente',
        on_delete=models.CASCADE,
        related_name='informes_evaluacion',
        verbose_name='Paciente',
    )
    evaluador = models.ForeignKey(
        Profesional,
        on_delete=models.PROTECT,
        related_name='informes_generados',
        verbose_name='Evaluador responsable',
    )
    evaluacion_ados2 = models.ForeignKey(
        EvaluacionADOS2,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='informes',
        verbose_name='Evaluación ADOS-2 asociada',
    )
    evaluacion_adir = models.ForeignKey(
        EvaluacionADIR,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='informes',
        verbose_name='Evaluación ADI-R asociada',
    )

    fecha_informe = models.DateField(default=timezone.now, verbose_name='Fecha del informe')
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='borrador')

    # Secciones del informe (texto libre)
    motivo_consulta = models.TextField(verbose_name='Motivo de consulta', blank=True)
    historia_clinica = models.TextField(verbose_name='Historia clínica relevante', blank=True)
    instrumentos_utilizados = models.TextField(
        verbose_name='Instrumentos utilizados',
        default='ADOS-2 (Lord et al., 2012)\nADI-R (Lord, Rutter & Le Couteur, 1994)'
    )
    resultados_ados2 = models.TextField(verbose_name='Resultados ADOS-2', blank=True)
    resultados_adir = models.TextField(verbose_name='Resultados ADI-R', blank=True)
    integracion_resultados = models.TextField(verbose_name='Integración de resultados', blank=True)
    conclusiones = models.TextField(verbose_name='Conclusiones y diagnóstico', blank=True)
    recomendaciones = models.TextField(verbose_name='Recomendaciones', blank=True)

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Informe de Evaluación'
        verbose_name_plural = 'Informes de Evaluación'
        ordering = ['-fecha_informe']

    def __str__(self):
        return f'Informe — {self.paciente} ({self.fecha_informe}) [{self.get_estado_display()}]'

    def get_estado_color(self):
        return {
            'borrador': 'secondary',
            'revision': 'warning',
            'finalizado': 'success',
        }.get(self.estado, 'secondary')