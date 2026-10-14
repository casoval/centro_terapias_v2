"""
Evaluación mensual de cada profesional, como indicador visual para el administrador (y para el propio
profesional): para saber cómo va el mes ANTES de que haya descuentos fuertes y poder conversar a tiempo.

PUNTUALIDAD — estrellas (solo mira el retraso):
    5 ★  Excelente   verde            siempre a la hora o antes: nunca usó la tolerancia
    4 ★  Buena       verde-amarillo   usó la tolerancia pero no acumuló ni un segundo de retraso
    3 ★  Regular     amarillo         ya acumula retraso, pero todavía sin descuento
  2½ ★  Regular      amarillo-naranja ya tiene medio día de descuento
    2 ★  Mala        naranja          ya tiene un día de descuento
    1 ★  Muy mala    rojo             ya tiene dos días de descuento
    0 ★  Pésima      morado           ya tiene tres días de descuento (o más)

ASISTENCIA — semáforo (solo mira las faltas):
    verde     Buena    asistió todos los días con horario
    amarillo  Regular  faltó, pero con permiso justificado (sin descuento)
    rojo      Mala     faltó sin justificar (con descuento)

Cada evaluación trae su «motivo» en texto: por qué tiene esas estrellas o ese color.
"""

# (estrellas, etiqueta, color, fondo)
NIVELES_PUNTUALIDAD = {
    5.0: ('Excelente', '#16a34a', '#dcfce7'),
    4.0: ('Buena', '#84cc16', '#ecfccb'),
    3.0: ('Regular', '#eab308', '#fef9c3'),
    2.5: ('Regular (con descuento)', '#f59e0b', '#fef3c7'),
    2.0: ('Mala', '#f97316', '#ffedd5'),
    1.0: ('Muy mala', '#dc2626', '#fee2e2'),
    0.0: ('Pésima', '#7c3aed', '#ede9fe'),
}
SEMAFORO = {
    'verde': ('Buena', '#16a34a', '#dcfce7'),
    'amarillo': ('Regular', '#eab308', '#fef9c3'),
    'rojo': ('Mala', '#dc2626', '#fee2e2'),
}


def _mmss(segundos):
    m, s = divmod(max(int(segundos), 0), 60)
    return f"{m}:{s:02d}"


def _dias_txt(d):
    d = float(d)
    if d == 0.5:
        return 'medio día'
    n = int(d) if d == int(d) else d
    return f"{n} día" + ('' if d == 1 else 's')


def _fechas_txt(fechas, limite=6):
    nombres = [f"{f:%d/%m}" for f in fechas[:limite]]
    extra = len(fechas) - limite
    return ', '.join(nombres) + (f" y {extra} más" if extra > 0 else '')


def estrellas_para(acum_seg, desc_dias, usos_tolerancia):
    """Estrellas según el retraso acumulado, el descuento que ya generó y si usó la tolerancia."""
    if desc_dias > 0:
        if desc_dias <= 0.5:
            return 2.5
        if desc_dias <= 1:
            return 2.0
        if desc_dias <= 2:
            return 1.0
        return 0.0
    if acum_seg > 0:
        return 3.0
    return 4.0 if usos_tolerancia > 0 else 5.0


def evaluar_puntualidad(entradas, usos_tolerancia, max_tarde_en_tolerancia, acum_seg, desc_dias,
                        hay_reglas, sin_descuento_seg, provisional=False):
    """
    entradas: ingresos del mes a bloques del horario · usos_tolerancia: ingresos que llegaron después de la
    hora pero dentro de la tolerancia · acum_seg: retraso acumulado (solo el excedente de la tolerancia) ·
    desc_dias: días de descuento que eso genera · sin_descuento_seg: retraso máximo sin descuento (o None).
    Devuelve None si no hay ingresos que evaluar.
    """
    if not entradas:
        return None
    estrellas = estrellas_para(acum_seg, desc_dias, usos_tolerancia)
    etiqueta, color, fondo = NIVELES_PUNTUALIDAD[estrellas]

    if estrellas == 5.0:
        motivo = (f"Los {entradas} ingreso(s) del mes fueron a la hora o antes: "
                  "nunca usó su tolerancia.")
    elif estrellas == 4.0:
        motivo = (f"Usó la tolerancia en {usos_tolerancia} de {entradas} ingreso(s) (hasta "
                  f"{_mmss(max_tarde_en_tolerancia)} después de la hora), pero no acumuló ningún minuto "
                  "ni segundo de retraso.")
    elif estrellas == 3.0:
        if hay_reglas and sin_descuento_seg is not None:
            motivo = (f"Acumula {_mmss(acum_seg)} min de retraso (lo que excede la tolerancia). Todavía no hay "
                      f"descuento: empieza al pasar {_mmss(sin_descuento_seg)} min.")
        else:
            motivo = (f"Acumula {_mmss(acum_seg)} min de retraso (lo que excede la tolerancia)."
                      + ('' if hay_reglas else ' No hay reglas de descuento configuradas.'))
    else:
        motivo = (f"Acumula {_mmss(acum_seg)} min de retraso: {_dias_txt(desc_dias)} de descuento "
                  "por puntualidad.")
    if provisional:
        motivo += ' (A la fecha: el mes aún no termina.)'
    return dict(estrellas=estrellas, etiqueta=etiqueta, color=color, fondo=fondo, motivo=motivo,
                provisional=provisional)


def evaluar_asistencia(dias_con_horario, faltas_injustificadas, faltas_justificadas, desc_faltas,
                       fechas_injustificadas, permisos, provisional=False):
    """
    faltas_*: días (fracciones: medio día = 0.5) · permisos: [(fecha, texto del tipo)].
    Devuelve None si no hubo días con horario que evaluar.
    """
    if not dias_con_horario:
        return None
    if faltas_injustificadas > 0:
        nivel = 'rojo'
        motivo = (f"Faltó sin justificar {_dias_txt(faltas_injustificadas)} "
                  f"({_fechas_txt(fechas_injustificadas)}): {_dias_txt(desc_faltas)} de descuento.")
        if faltas_justificadas > 0:
            motivo += f" Además tiene {_dias_txt(faltas_justificadas)} con permiso."
    elif faltas_justificadas > 0:
        nivel = 'amarillo'
        detalle = ', '.join(f"{f:%d/%m} ({t})" for f, t in permisos[:6])
        motivo = (f"Faltó {_dias_txt(faltas_justificadas)} pero con permiso justificado: {detalle}. "
                  "No genera descuento.")
    else:
        nivel = 'verde'
        motivo = f"Asistió a todos los días con horario ({dias_con_horario} día(s) evaluados)."
    if provisional:
        motivo += ' (A la fecha: el mes aún no termina.)'
    etiqueta, color, fondo = SEMAFORO[nivel]
    return dict(nivel=nivel, etiqueta=etiqueta, color=color, fondo=fondo, motivo=motivo, provisional=provisional)


def es_alerta(puntualidad, asistencia):
    """¿Conviene que el administrador hable con el profesional? (puntualidad 2★ o peor, o asistencia en rojo)."""
    return bool((puntualidad and puntualidad['estrellas'] <= 2.0) or (asistencia and asistencia['nivel'] == 'rojo'))
