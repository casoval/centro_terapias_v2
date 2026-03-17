"""
Admin de Django para evaluaciones ADOS-2, ADI-R e Informes.
"""

from django.contrib import admin
from django.utils.html import format_html
from .models import EvaluacionADOS2, EvaluacionADIR, InformeEvaluacion


@admin.register(EvaluacionADOS2)
class EvaluacionADOS2Admin(admin.ModelAdmin):
    list_display = [
        'paciente', 'modulo', 'fecha_evaluacion', 'evaluador',
        'total_comunicacion_social', 'clasificacion_badge',
    ]
    list_filter = ['modulo', 'clasificacion', 'fecha_evaluacion', 'evaluador']
    search_fields = ['paciente__nombre', 'evaluador__nombre', 'evaluador__apellido']
    readonly_fields = [
        'total_comunicacion', 'total_interaccion_social',
        'total_comunicacion_social', 'total_comportamiento_restringido',
        'comparison_score', 'clasificacion', 'creado_en', 'actualizado_en',
    ]
    date_hierarchy = 'fecha_evaluacion'

    fieldsets = (
        ('Datos generales', {
            'fields': (
                'paciente', 'evaluador', 'modulo', 'fecha_evaluacion',
                'edad_cronologica_anos', 'edad_cronologica_meses', 'contexto_evaluacion',
            )
        }),
        ('Módulo 1 — Comunicación', {
            'classes': ('collapse',),
            'fields': (
                'm1_A1_uso_funcional_comunicativo', 'm1_A2_cantidad_vocalizaciones',
                'm1_A3_vocalizaciones_con_palabras', 'm1_A4_senar_con_dedo',
                'm1_A5_gestos', 'm1_A6_accion_coordinada',
                'm1_A7_uso_del_cuerpo_del_otro', 'm1_A8_dar_y_mostrar',
            )
        }),
        ('Módulo 1 — Interacción Social', {
            'classes': ('collapse',),
            'fields': (
                'm1_B1_contacto_visual_inusual', 'm1_B2_sonrisa_social_responsiva',
                'm1_B3_disfrute_compartido', 'm1_B4_iniciacion_atencion_conjunta',
                'm1_B5_respuesta_atencion_conjunta', 'm1_B6_calidad_acercamientos',
                'm1_B7_comprension_de_comunicacion', 'm1_B8_imitacion',
                'm1_B9_juego_funcional', 'm1_B10_juego_simbolico',
            )
        }),
        ('Módulo 1 — Comportamiento Restringido', {
            'classes': ('collapse',),
            'fields': (
                'm1_C1_intereses_inusuales', 'm1_C2_manierismos_mano_dedos',
                'm1_C3_comportamiento_repetitivo',
            )
        }),
        ('Puntuaciones calculadas', {
            'fields': (
                'total_comunicacion', 'total_interaccion_social',
                'total_comunicacion_social', 'total_comportamiento_restringido',
                'comparison_score', 'clasificacion',
            )
        }),
        ('Observaciones', {'fields': ('observaciones',)}),
        ('Metadatos', {
            'classes': ('collapse',),
            'fields': ('creado_en', 'actualizado_en'),
        }),
    )

    def clasificacion_badge(self, obj):
        colores = {
            'no_espectro': '#198754',
            'espectro': '#ffc107',
            'autismo': '#dc3545',
            'pendiente': '#6c757d',
        }
        color = colores.get(obj.clasificacion, '#6c757d')
        return format_html(
            '<span style="background:{};color:white;padding:3px 8px;'
            'border-radius:4px;font-size:12px">{}</span>',
            color, obj.get_clasificacion_display()
        )
    clasificacion_badge.short_description = 'Clasificación'


@admin.register(EvaluacionADIR)
class EvaluacionADIRAdmin(admin.ModelAdmin):
    list_display = [
        'paciente', 'fecha_evaluacion', 'evaluador', 'informante',
        'tipo_comunicacion', 'clasificacion_badge',
    ]
    list_filter = ['clasificacion', 'tipo_comunicacion', 'fecha_evaluacion', 'evaluador']
    search_fields = ['paciente__nombre', 'informante', 'evaluador__nombre', 'evaluador__apellido']
    readonly_fields = [
        'algoritmo_comunicacion', 'algoritmo_interaccion_social',
        'algoritmo_comportamientos_rr',
        'cumple_corte_comunicacion', 'cumple_corte_interaccion',
        'cumple_corte_comportamiento', 'cumple_criterio_edad_inicio',
        'clasificacion', 'creado_en', 'actualizado_en',
    ]
    date_hierarchy = 'fecha_evaluacion'

    fieldsets = (
        ('Datos generales', {
            'fields': (
                'paciente', 'evaluador', 'informante', 'relacion_informante',
                'fecha_evaluacion', 'tipo_comunicacion',
            )
        }),
        ('Historia del desarrollo', {
            'fields': (
                'edad_primeras_palabras', 'edad_primeras_frases',
                'perdida_lenguaje', 'edad_perdida_lenguaje',
                'perdida_habilidades_sociales',
            )
        }),
        ('A — Lenguaje y Comunicación', {
            'classes': ('collapse',),
            'fields': (
                'A9_jerga', 'A10_ecolalia_inmediata', 'A11_ecolalia_retardada',
                'A12_inversion_pronominal', 'A13_neologismos',
                'A14_conversacion_reciproca', 'A15_preguntas_inapropiadas',
                'A16_uso_del_cuerpo', 'A17_gesto_para_senalar',
                'A18_senalar_compartir', 'A19_cabeceo_si',
                'A_nv1_vocaliza_para_pedir', 'A_nv2_vocaliza_para_mostrar',
                'A_nv3_otros_gestos',
            )
        }),
        ('B — Interacción Social Recíproca', {
            'classes': ('collapse',),
            'fields': (
                'B20_juego_peer', 'B21_amistades', 'B22_bsqueda_placer',
                'B23_oferta_consuelo', 'B24_calidad_acercamiento',
                'B25_respuesta_emociones', 'B26_contacto_visual',
                'B27_expresiones_faciales', 'B28_sonrisa_social',
                'B29_atencion_conjunta', 'B30_seguimiento_senal',
                'B31_dar_mostrar', 'B32_juego_imaginativo',
                'B33_interes_ninos', 'B34_respuesta_acercamiento',
                'B35_juego_grupo', 'B36_incapacidad_expresar',
            )
        }),
        ('C — Comportamientos Restringidos y Repetitivos', {
            'classes': ('collapse',),
            'fields': (
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
            )
        }),
        ('Resultados del Algoritmo Diagnóstico', {
            'fields': (
                'algoritmo_comunicacion', 'algoritmo_interaccion_social',
                'algoritmo_comportamientos_rr',
                'cumple_corte_comunicacion', 'cumple_corte_interaccion',
                'cumple_corte_comportamiento', 'cumple_criterio_edad_inicio',
                'clasificacion',
            )
        }),
        ('Observaciones', {'fields': ('observaciones',)}),
        ('Metadatos', {
            'classes': ('collapse',),
            'fields': ('creado_en', 'actualizado_en'),
        }),
    )

    def clasificacion_badge(self, obj):
        colores = {
            'cumple': '#dc3545',
            'no_cumple': '#198754',
            'pendiente': '#6c757d',
        }
        color = colores.get(obj.clasificacion, '#6c757d')
        return format_html(
            '<span style="background:{};color:white;padding:3px 8px;'
            'border-radius:4px;font-size:12px">{}</span>',
            color, obj.get_clasificacion_display()
        )
    clasificacion_badge.short_description = 'Clasificación ADI-R'


@admin.register(InformeEvaluacion)
class InformeEvaluacionAdmin(admin.ModelAdmin):
    list_display = [
        'paciente', 'fecha_informe', 'evaluador',
        'tiene_ados2', 'tiene_adir', 'estado_badge',
    ]
    list_filter = ['estado', 'fecha_informe', 'evaluador']
    search_fields = ['paciente__nombre', 'evaluador__nombre', 'evaluador__apellido']
    date_hierarchy = 'fecha_informe'

    def tiene_ados2(self, obj):
        return '✅' if obj.evaluacion_ados2 else '—'
    tiene_ados2.short_description = 'ADOS-2'

    def tiene_adir(self, obj):
        return '✅' if obj.evaluacion_adir else '—'
    tiene_adir.short_description = 'ADI-R'

    def estado_badge(self, obj):
        colores = {
            'borrador': '#6c757d',
            'revision': '#ffc107',
            'finalizado': '#198754',
        }
        color = colores.get(obj.estado, '#6c757d')
        return format_html(
            '<span style="background:{};color:white;padding:3px 8px;'
            'border-radius:4px;font-size:12px">{}</span>',
            color, obj.get_estado_display()
        )
    estado_badge.short_description = 'Estado'