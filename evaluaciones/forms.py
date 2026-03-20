"""
Formularios para evaluaciones ADOS-2, ADI-R e Informe.
Ajustados al modelo Paciente real de la app 'pacientes':
  - nombre + apellido (property nombre_completo)
  - fecha_nacimiento (edad calculada en property .edad)
  - genero (M/F/O)
  - diagnostico (ya existe en el modelo)
  - nombre_tutor / parentesco (pre-rellena el campo informante en ADI-R)
"""

from django import forms
from django.contrib.auth.models import User
from pacientes.models import Paciente
from .models import EvaluacionADOS2, EvaluacionADIR, InformeEvaluacion


# ─────────────────────────────────────────────
# Queryset base de pacientes
# ─────────────────────────────────────────────

def pacientes_qs():
    """Devuelve pacientes activos ordenados por apellido, nombre."""
    return Paciente.objects.filter(estado='activo').order_by('apellido', 'nombre')


def label_paciente(obj):
    """Etiqueta para el select de paciente: Nombre Apellido (X años)."""
    base = f"{obj.nombre_completo} ({obj.edad} años)"
    if obj.diagnostico:
        resumen = obj.diagnostico[:50] + ('…' if len(obj.diagnostico) > 50 else '')
        return f"{base} — {resumen}"
    return base


def evaluadores_qs():
    """Profesionales activos ordenados por apellido."""
    from profesionales.models import Profesional
    return Profesional.objects.filter(activo=True).order_by('apellido', 'nombre')


def label_evaluador(obj):
    """obj es Profesional directamente."""
    esp = f" — {obj.especialidad}" if obj.especialidad else ""
    return f"{obj.nombre} {obj.apellido}{esp}"


# ── Mixin para radio buttons 0/1/2 ó 0/1/2/3 ────────────────

class IntRadioSelect(forms.RadioSelect):
    """
    RadioSelect que acepta valores int además de string al validar.
    RadioSelect.validate() compara el valor enviado contra las choices
    como string, pero IntegerField.to_python() devuelve int antes de
    esa validación → el campo se marca como inválido y no guarda.
    Sobreescribir valid_value() resuelve el conflicto sin cambiar el
    resto del flujo del formulario.
    """
    def valid_value(self, value):
        # Comparar como string para ser compatible con choices de strings
        str_value = str(value) if value not in ('', None) else ''
        for k, v in self.choices:
            if isinstance(v, (list, tuple)):
                for k2, _ in v:
                    if str(k2) == str_value:
                        return True
            else:
                if str(k) == str_value:
                    return True
        return False


class ItemsRadioMixin:
    """
    Convierte todos los campos del formulario en radio buttons
    horizontales: — / 0 / 1 / 2 (o hasta 3 si MAX_VAL=3).
    """
    MAX_VAL = 2

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        opciones = [('', '—')] + [(str(i), str(i)) for i in range(self.MAX_VAL + 1)]
        for field_name in self.fields:
            self.fields[field_name].widget = IntRadioSelect(choices=opciones)
            self.fields[field_name].required = False
            # Convertir valor de instancia a string para que el widget
            # lo encuentre en las choices al renderizar (display).
            if self.instance and self.instance.pk:
                raw = getattr(self.instance, field_name, None)
                if raw is not None:
                    self.initial[field_name] = str(raw)


# ═══════════════════════════════════════════════════════════════
# ADOS-2
# ═══════════════════════════════════════════════════════════════

class EvaluacionADOS2GeneralForm(forms.ModelForm):
    """Paso 1: Datos generales de la evaluación ADOS-2."""

    class Meta:
        model = EvaluacionADOS2
        fields = [
            'paciente', 'evaluador', 'modulo', 'fecha_evaluacion',
            'edad_cronologica_anos', 'edad_cronologica_meses', 'contexto_evaluacion',
        ]
        widgets = {
            'paciente': forms.Select(attrs={'class': 'form-select', 'id': 'id_paciente'}),
            'evaluador': forms.Select(attrs={'class': 'form-select'}),
            'modulo': forms.Select(attrs={'class': 'form-select', 'id': 'id_modulo'}),
            'fecha_evaluacion': forms.DateInput(
                format='%Y-%m-%d',
                attrs={'class': 'form-control', 'type': 'date'}),
            'edad_cronologica_anos': forms.NumberInput(
                attrs={'class': 'form-control', 'min': 0, 'max': 99}),
            'edad_cronologica_meses': forms.NumberInput(
                attrs={'class': 'form-control', 'min': 0, 'max': 11}),
            'contexto_evaluacion': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 3,
                'placeholder': 'Contexto, condiciones de la sala, comportamiento general del evaluado...'
            }),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        self.fields['paciente'].queryset = pacientes_qs()
        self.fields['paciente'].label_from_instance = label_paciente
        self.fields['evaluador'].queryset = evaluadores_qs()
        self.fields['evaluador'].label_from_instance = label_evaluador
        if user:
            try:
                self.fields['evaluador'].initial = user.profesional.pk
            except Exception:
                pass


# Módulo 1

class ADOS2Modulo1ComunicacionForm(ItemsRadioMixin, forms.ModelForm):
    class Meta:
        model = EvaluacionADOS2
        fields = [
            'm1_A1_uso_funcional_comunicativo', 'm1_A2_cantidad_vocalizaciones',
            'm1_A3_vocalizaciones_con_palabras', 'm1_A4_senar_con_dedo',
            'm1_A5_gestos', 'm1_A6_accion_coordinada',
            'm1_A7_uso_del_cuerpo_del_otro', 'm1_A8_dar_y_mostrar',
        ]


class ADOS2Modulo1InteraccionForm(ItemsRadioMixin, forms.ModelForm):
    class Meta:
        model = EvaluacionADOS2
        fields = [
            'm1_B1_contacto_visual_inusual', 'm1_B2_sonrisa_social_responsiva',
            'm1_B3_disfrute_compartido', 'm1_B4_iniciacion_atencion_conjunta',
            'm1_B5_respuesta_atencion_conjunta', 'm1_B6_calidad_acercamientos',
            'm1_B7_comprension_de_comunicacion', 'm1_B8_imitacion',
            'm1_B9_juego_funcional', 'm1_B10_juego_simbolico',
        ]


class ADOS2Modulo1RRBForm(ItemsRadioMixin, forms.ModelForm):
    class Meta:
        model = EvaluacionADOS2
        fields = [
            'm1_C1_intereses_inusuales', 'm1_C2_manierismos_mano_dedos',
            'm1_C3_comportamiento_repetitivo',
        ]


# Módulo 2

class ADOS2Modulo2Form(ItemsRadioMixin, forms.ModelForm):
    class Meta:
        model = EvaluacionADOS2
        fields = [
            'm2_A1_espontaneidad_del_lenguaje', 'm2_A2_preguntas_directas',
            'm2_A3_produccion_narrativa', 'm2_A4_uso_comunicativo_gestos',
            'm2_A5_contacto_visual_inusual', 'm2_A6_expresiones_faciales_dirigidas',
            'm2_B1_disfrute_compartido', 'm2_B2_atencion_conjunta',
            'm2_B3_calidad_acercamientos', 'm2_B4_comprension_comunicacion',
            'm2_B5_imitacion', 'm2_B6_juego_imaginativo', 'm2_B7_respuesta_nombre',
            'm2_C1_intereses_inusuales', 'm2_C2_manierismos_mano_dedos',
            'm2_C3_comportamiento_repetitivo',
        ]


# Módulo 3

class ADOS2Modulo3Form(ItemsRadioMixin, forms.ModelForm):
    class Meta:
        model = EvaluacionADOS2
        fields = [
            'm3_A1_espontaneidad_lenguaje', 'm3_A2_reporte_eventos',
            'm3_A3_conversacion', 'm3_A4_gestos_descriptivos',
            'm3_A5_contacto_visual_inusual', 'm3_A6_expresiones_faciales',
            'm3_B1_disfrute_compartido', 'm3_B2_perspectiva',
            'm3_B3_responsividad_emocional', 'm3_B4_calidad_acercamientos',
            'm3_B5_cantidad_iniciacion', 'm3_B6_narrativa_global',
            'm3_C1_intereses_inusuales', 'm3_C2_manierismos_mano_dedos',
            'm3_C3_comportamiento_repetitivo',
        ]


# Módulo 4

class ADOS2Modulo4Form(ItemsRadioMixin, forms.ModelForm):
    class Meta:
        model = EvaluacionADOS2
        fields = [
            'm4_A1_lenguaje', 'm4_A2_reporte_eventos', 'm4_A3_conversacion',
            'm4_A4_gestos', 'm4_A5_contacto_visual', 'm4_A6_expresiones_faciales',
            'm4_B1_disfrute_compartido', 'm4_B2_perspectiva',
            'm4_B3_responsividad_emocional', 'm4_B4_calidad_acercamientos',
            'm4_B5_cantidad_iniciacion', 'm4_B6_narrativa_global',
            'm4_B7_responsividad_examinador',
            'm4_C1_intereses_inusuales', 'm4_C2_manierismos_mano_dedos',
            'm4_C3_comportamiento_repetitivo',
        ]


# Módulo T

class ADOS2ModuloTForm(ItemsRadioMixin, forms.ModelForm):
    class Meta:
        model = EvaluacionADOS2
        fields = [
            'mt_A1_vocalizacion_social', 'mt_A2_senal_con_dedo',
            'mt_A3_accion_coordinada', 'mt_A4_uso_cuerpo_otro', 'mt_A5_palabras_o_frases',
            'mt_B1_contacto_visual', 'mt_B2_sonrisa_responsiva',
            'mt_B3_disfrute_compartido', 'mt_B4_iniciacion_atencion', 'mt_B5_respuesta_nombre',
            'mt_B6_juego_funcional', 'mt_C1_intereses_inusuales', 'mt_C2_manierismos',
        ]


class ADOS2ObservacionesForm(forms.ModelForm):
    class Meta:
        model = EvaluacionADOS2
        fields = ['observaciones']
        widgets = {
            'observaciones': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 6,
                'placeholder': 'Observaciones cualitativas: colaboración, conductas no codificadas, nivel de angustia...'
            })
        }


# ═══════════════════════════════════════════════════════════════
# ADI-R
# ═══════════════════════════════════════════════════════════════

class EvaluacionADIRGeneralForm(forms.ModelForm):
    """
    Paso 1: Datos generales de la evaluación ADI-R.
    Pre-rellena el informante con nombre_tutor + parentesco del Paciente.
    """

    class Meta:
        model = EvaluacionADIR
        fields = [
            'paciente', 'evaluador', 'informante', 'relacion_informante',
            'fecha_evaluacion', 'tipo_comunicacion',
        ]
        widgets = {
            'paciente': forms.Select(attrs={'class': 'form-select', 'id': 'id_paciente_adir'}),
            'evaluador': forms.Select(attrs={'class': 'form-select'}),
            'informante': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nombre completo del informante (ej: María González)',
            }),
            'relacion_informante': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ej: madre, padre, tutor legal',
            }),
            'fecha_evaluacion': forms.DateInput(
                format='%Y-%m-%d',
                attrs={'class': 'form-control', 'type': 'date'}),
            'tipo_comunicacion': forms.RadioSelect(),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        self.fields['paciente'].queryset = pacientes_qs()
        self.fields['paciente'].label_from_instance = label_paciente
        self.fields['evaluador'].queryset = evaluadores_qs()
        self.fields['evaluador'].label_from_instance = label_evaluador
        if user:
            try:
                self.fields['evaluador'].initial = user.profesional.pk
            except Exception:
                pass

        # Pre-rellenar informante desde el tutor del paciente
        if self.instance and self.instance.pk and self.instance.paciente_id:
            try:
                pac = Paciente.objects.get(pk=self.instance.paciente_id)
                if not self.instance.informante:
                    self.fields['informante'].initial = pac.nombre_tutor
                    self.fields['relacion_informante'].initial = pac.get_parentesco_display() if hasattr(pac, 'get_parentesco_display') else pac.parentesco
            except Paciente.DoesNotExist:
                pass


class ADIRHistoriaDesarrolloForm(forms.ModelForm):
    class Meta:
        model = EvaluacionADIR
        fields = [
            'edad_primeras_palabras', 'edad_primeras_frases',
            'perdida_lenguaje', 'edad_perdida_lenguaje',
            'perdida_habilidades_sociales',
        ]
        widgets = {
            'edad_primeras_palabras': forms.NumberInput(attrs={
                'class': 'form-control', 'min': 0, 'max': 120,
                'placeholder': 'meses (ej: 18)'}),
            'edad_primeras_frases': forms.NumberInput(attrs={
                'class': 'form-control', 'min': 0, 'max': 120,
                'placeholder': 'meses (ej: 24)'}),
            'perdida_lenguaje': forms.RadioSelect(
                choices=[(True, 'Sí, hubo pérdida de lenguaje'),
                         (False, 'No hubo pérdida')]),
            'edad_perdida_lenguaje': forms.NumberInput(attrs={
                'class': 'form-control', 'min': 0, 'max': 120,
                'placeholder': 'meses'}),
            'perdida_habilidades_sociales': forms.RadioSelect(
                choices=[(True, 'Sí, hubo pérdida de habilidades sociales'),
                         (False, 'No hubo pérdida')]),
        }


class ADIRComunicacionVerbalesForm(ItemsRadioMixin, forms.ModelForm):
    """Dominio A — Lenguaje y Comunicación Verbal (ítems 9-19)."""
    MAX_VAL = 3

    class Meta:
        model = EvaluacionADIR
        fields = [
            'A9_jerga', 'A10_ecolalia_inmediata', 'A11_ecolalia_retardada',
            'A12_inversion_pronominal', 'A13_neologismos',
            'A14_conversacion_reciproca', 'A15_preguntas_inapropiadas',
            'A16_uso_del_cuerpo', 'A17_gesto_para_senalar',
            'A18_senalar_compartir', 'A19_cabeceo_si',
        ]


class ADIRComunicacionNoVerbalesForm(ItemsRadioMixin, forms.ModelForm):
    """Dominio A — Comunicación No Verbal."""
    MAX_VAL = 3

    class Meta:
        model = EvaluacionADIR
        fields = [
            'A_nv1_vocaliza_para_pedir', 'A_nv2_vocaliza_para_mostrar',
            'A_nv3_otros_gestos',
            'A17_gesto_para_senalar', 'A18_senalar_compartir',
        ]


class ADIRInteraccionSocialForm(ItemsRadioMixin, forms.ModelForm):
    """Dominio B — Interacción Social Recíproca (ítems 20-36)."""
    MAX_VAL = 3

    class Meta:
        model = EvaluacionADIR
        fields = [
            'B20_juego_peer', 'B21_amistades', 'B22_bsqueda_placer',
            'B23_oferta_consuelo', 'B24_calidad_acercamiento',
            'B25_respuesta_emociones', 'B26_contacto_visual',
            'B27_expresiones_faciales', 'B28_sonrisa_social',
            'B29_atencion_conjunta', 'B30_seguimiento_senal',
            'B31_dar_mostrar', 'B32_juego_imaginativo',
            'B33_interes_ninos', 'B34_respuesta_acercamiento',
            'B35_juego_grupo', 'B36_incapacidad_expresar',
        ]


class ADIRComportamientoRRForm(ItemsRadioMixin, forms.ModelForm):
    """Dominio C — Comportamientos RR + sensorialidad + retrospectivo (4-5 años)."""
    MAX_VAL = 3

    class Meta:
        model = EvaluacionADIR
        fields = [
            'C67_preocupaciones_inusuales', 'C68_adherencia_rutinas',
            'C69_intereses_circunscritos', 'C70_ritual_compulsivo',
            'C71_estereotipias_mano_cuerpo', 'C72_estereotipias_dedos',
            'C73_auto_agresion', 'C74_uso_objetos', 'C75_alineamiento_girar',
            'C76_apego_objetos', 'C77_preocupacion_parte_objeto',
            'C78_sensibilidad_ruido', 'C79_sensibilidad_dolor',
            'C80_sensibilidad_tactil', 'C81_olfato_sabor',
            'C82_respuesta_visual', 'C83_examinacion_proximal',
            'C84_fascinacion_luz', 'C85_respuesta_calor_frio',
            'C86_gran_habilidad',
            'C87_preocupaciones_4_5', 'C88_rutinas_4_5',
            'C89_estereotipias_4_5', 'C90_compulsiones_4_5', 'C91_autolesion_4_5',
        ]


class ADIRObservacionesForm(forms.ModelForm):
    class Meta:
        model = EvaluacionADIR
        fields = ['observaciones']
        widgets = {
            'observaciones': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 6,
                'placeholder': 'Observaciones sobre la entrevista: actitud del informante, inconsistencias, contexto cultural...'
            })
        }


# ═══════════════════════════════════════════════════════════════
# INFORME COMBINADO
# ═══════════════════════════════════════════════════════════════

class InformeEvaluacionForm(forms.ModelForm):
    """
    Informe clínico combinado ADOS-2 + ADI-R.
    Las evaluaciones se filtran por paciente seleccionado.
    """

    class Meta:
        model = InformeEvaluacion
        fields = [
            'paciente', 'evaluador', 'evaluacion_ados2', 'evaluacion_adir',
            'fecha_informe', 'estado',
            'motivo_consulta', 'historia_clinica', 'instrumentos_utilizados',
            'resultados_ados2', 'resultados_adir',
            'integracion_resultados', 'conclusiones', 'recomendaciones',
        ]
        widgets = {
            'paciente': forms.Select(attrs={'class': 'form-select'}),
            'evaluador': forms.Select(attrs={'class': 'form-select'}),
            'evaluacion_ados2': forms.Select(attrs={'class': 'form-select'}),
            'evaluacion_adir': forms.Select(attrs={'class': 'form-select'}),
            'fecha_informe': forms.DateInput(
                format='%Y-%m-%d',
                attrs={'class': 'form-control', 'type': 'date'}),
            'estado': forms.Select(attrs={'class': 'form-select'}),
            'motivo_consulta': forms.Textarea(
                attrs={'class': 'form-control', 'rows': 3,
                       'placeholder': 'Motivo de derivación y consulta...'}),
            'historia_clinica': forms.Textarea(
                attrs={'class': 'form-control', 'rows': 4,
                       'placeholder': 'Antecedentes del desarrollo, historia médica, intervenciones previas...'}),
            'instrumentos_utilizados': forms.Textarea(
                attrs={'class': 'form-control', 'rows': 3,
                       'initial': 'ADOS-2 (Lord et al., 2012)\nADI-R (Lord, Rutter & Le Couteur, 1994)'}),
            'resultados_ados2': forms.Textarea(
                attrs={'class': 'form-control', 'rows': 5,
                       'placeholder': 'Descripción cualitativa de los resultados ADOS-2...'}),
            'resultados_adir': forms.Textarea(
                attrs={'class': 'form-control', 'rows': 5,
                       'placeholder': 'Descripción cualitativa de los resultados ADI-R...'}),
            'integracion_resultados': forms.Textarea(
                attrs={'class': 'form-control', 'rows': 5,
                       'placeholder': 'Integración de ambos instrumentos con la historia clínica...'}),
            'conclusiones': forms.Textarea(
                attrs={'class': 'form-control', 'rows': 5,
                       'placeholder': 'Conclusiones diagnósticas e impresión clínica...'}),
            'recomendaciones': forms.Textarea(
                attrs={'class': 'form-control', 'rows': 5,
                       'placeholder': 'Recomendaciones terapéuticas, derivaciones, seguimiento...'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        self.fields['paciente'].queryset = pacientes_qs()
        self.fields['paciente'].label_from_instance = label_paciente
        self.fields['evaluador'].queryset = evaluadores_qs()
        self.fields['evaluador'].label_from_instance = label_evaluador
        if user:
            try:
                self.fields['evaluador'].initial = user.profesional.pk
            except Exception:
                pass

        # Filtrar evaluaciones por paciente.
        # Prioridad: 1) instancia guardada (edición), 2) POST data (creación).
        # Sin el punto 2, el queryset queda en none() al crear y form.is_valid()
        # rechaza cualquier evaluación seleccionada aunque sea válida.
        pid = None
        if self.instance and self.instance.pk:
            pid = self.instance.paciente_id
        elif self.data.get('paciente'):
            pid = self.data.get('paciente')

        if pid:
            ados2_qs = EvaluacionADOS2.objects.filter(paciente_id=pid).order_by('-fecha_evaluacion')
            adir_qs = EvaluacionADIR.objects.filter(paciente_id=pid).order_by('-fecha_evaluacion')
        else:
            ados2_qs = EvaluacionADOS2.objects.none()
            adir_qs = EvaluacionADIR.objects.none()

        self.fields['evaluacion_ados2'].queryset = ados2_qs
        self.fields['evaluacion_adir'].queryset = adir_qs
        self.fields['evaluacion_ados2'].required = False
        self.fields['evaluacion_adir'].required = False

        self.fields['evaluacion_ados2'].label_from_instance = lambda obj: (
            f"Módulo {obj.modulo} — {obj.fecha_evaluacion:%d/%m/%Y} [{obj.get_clasificacion_display()}]"
        )
        self.fields['evaluacion_adir'].label_from_instance = lambda obj: (
            f"{obj.fecha_evaluacion:%d/%m/%Y} [{obj.get_clasificacion_display()}]"
        )