# egresos/pdf_generator.py
# Generador de comprobantes PDF para egresos (recibo EGR-XXXX).
# Usa ReportLab — mismo stack que facturacion/pdf_generator.py

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.colors import HexColor, black, white, gray
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.pdfgen import canvas as pdfcanvas

from io import BytesIO
from datetime import date


# ── Colores del tema ──────────────────────────────────────────────────────────
COLOR_PRIMARY    = HexColor('#2C3E50')   # Azul oscuro — encabezados
COLOR_SECONDARY  = HexColor('#E74C3C')   # Rojo — egresos (salida de dinero)
COLOR_ACCENT     = HexColor('#ECF0F1')   # Gris muy claro — fondos de tabla
COLOR_ANULADO    = HexColor('#C0392B')   # Rojo oscuro — sello de anulado
COLOR_TEXT_LIGHT = HexColor('#7F8C8D')   # Gris — texto secundario
COLOR_SUCCESS    = HexColor('#27AE60')   # Verde — activo


def generar_egreso_pdf(egreso):
    """
    Genera el comprobante PDF de un egreso y retorna los bytes.

    Args:
        egreso: instancia de Egreso (con select_related ya cargado)

    Returns:
        bytes: contenido del PDF
    """
    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title=f'Comprobante de Egreso {egreso.numero_egreso}',
    )

    styles  = getSampleStyleSheet()
    story   = []

    # ── Estilos personalizados ────────────────────────────────────────────────
    estilo_titulo = ParagraphStyle(
        'titulo',
        parent=styles['Normal'],
        fontSize=22,
        textColor=COLOR_PRIMARY,
        spaceAfter=0,
        fontName='Helvetica-Bold',
        alignment=TA_LEFT,
    )
    estilo_subtitulo = ParagraphStyle(
        'subtitulo',
        parent=styles['Normal'],
        fontSize=10,
        textColor=COLOR_TEXT_LIGHT,
        spaceAfter=2,
        fontName='Helvetica',
        alignment=TA_LEFT,
    )
    estilo_numero = ParagraphStyle(
        'numero',
        parent=styles['Normal'],
        fontSize=14,
        textColor=COLOR_SECONDARY,
        fontName='Helvetica-Bold',
        alignment=TA_RIGHT,
    )
    estilo_label = ParagraphStyle(
        'label',
        parent=styles['Normal'],
        fontSize=8,
        textColor=COLOR_TEXT_LIGHT,
        fontName='Helvetica',
        spaceAfter=1,
    )
    estilo_valor = ParagraphStyle(
        'valor',
        parent=styles['Normal'],
        fontSize=10,
        textColor=COLOR_PRIMARY,
        fontName='Helvetica-Bold',
        spaceAfter=6,
    )
    estilo_monto = ParagraphStyle(
        'monto',
        parent=styles['Normal'],
        fontSize=26,
        textColor=COLOR_SECONDARY,
        fontName='Helvetica-Bold',
        alignment=TA_CENTER,
    )
    estilo_anulado = ParagraphStyle(
        'anulado',
        parent=styles['Normal'],
        fontSize=36,
        textColor=COLOR_ANULADO,
        fontName='Helvetica-Bold',
        alignment=TA_CENTER,
    )
    estilo_footer = ParagraphStyle(
        'footer',
        parent=styles['Normal'],
        fontSize=8,
        textColor=COLOR_TEXT_LIGHT,
        fontName='Helvetica',
        alignment=TA_CENTER,
    )

    # ── ENCABEZADO: nombre del centro + número de egreso ─────────────────────
    encabezado_data = [
        [
            Paragraph('Centro de Rehabilitación', estilo_titulo),
            Paragraph(egreso.numero_egreso, estilo_numero),
        ],
        [
            Paragraph('COMPROBANTE DE EGRESO', estilo_subtitulo),
            Paragraph(
                f'<font color="#7F8C8D" size="9">Fecha: {egreso.fecha.strftime("%d/%m/%Y")}</font>',
                ParagraphStyle('p', parent=styles['Normal'], alignment=TA_RIGHT,
                               fontSize=9, textColor=COLOR_TEXT_LIGHT)
            ),
        ],
    ]
    encabezado_table = Table(encabezado_data, colWidths=[11 * cm, 6 * cm])
    encabezado_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
    ]))
    story.append(encabezado_table)

    # Línea separadora
    story.append(Spacer(1, 0.3 * cm))
    story.append(HRFlowable(width='100%', thickness=2, color=COLOR_SECONDARY))
    story.append(Spacer(1, 0.5 * cm))

    # ── SELLO DE ANULADO (si aplica) ──────────────────────────────────────────
    if egreso.anulado:
        story.append(Paragraph('⛔  EGRESO ANULADO  ⛔', estilo_anulado))
        story.append(Spacer(1, 0.3 * cm))
        story.append(Paragraph(
            f'Motivo: {egreso.motivo_anulacion}',
            ParagraphStyle('mot', parent=styles['Normal'], fontSize=10,
                           textColor=COLOR_ANULADO, alignment=TA_CENTER,
                           fontName='Helvetica-Oblique')
        ))
        story.append(Spacer(1, 0.5 * cm))
        story.append(HRFlowable(width='100%', thickness=1, color=COLOR_ANULADO))
        story.append(Spacer(1, 0.5 * cm))

    # ── BLOQUE PRINCIPAL: monto ───────────────────────────────────────────────
    story.append(Paragraph(
        f'Bs. {egreso.monto:,.0f}',
        estilo_monto
    ))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(
        egreso.concepto,
        ParagraphStyle('concepto', parent=styles['Normal'], fontSize=12,
                       textColor=COLOR_PRIMARY, alignment=TA_CENTER,
                       fontName='Helvetica-Oblique')
    ))
    story.append(Spacer(1, 0.5 * cm))
    story.append(HRFlowable(width='100%', thickness=1, color=COLOR_ACCENT))
    story.append(Spacer(1, 0.5 * cm))

    # ── TABLA DE DETALLES ─────────────────────────────────────────────────────
    def fila(label, valor):
        return [
            Paragraph(label, estilo_label),
            Paragraph(str(valor) if valor else '—', estilo_valor),
        ]

    detalles = [
        fila('Categoría',    f'{egreso.categoria.nombre} ({egreso.categoria.get_tipo_display()})'),
        fila('Período',      egreso.periodo_display),
        fila('Método de Pago', str(egreso.metodo_pago)),
    ]

    if egreso.numero_transaccion:
        detalles.append(fila('N° Transacción / Cheque', egreso.numero_transaccion))

    if egreso.proveedor:
        detalles.append(fila('Proveedor / Beneficiario', egreso.proveedor.nombre))
        if egreso.proveedor.nit_ci:
            detalles.append(fila('NIT / CI Proveedor', egreso.proveedor.nit_ci))

    if egreso.numero_documento_proveedor:
        detalles.append(fila('N° Doc. Proveedor', egreso.numero_documento_proveedor))

    if egreso.sucursal:
        detalles.append(fila('Sucursal', str(egreso.sucursal)))

    if egreso.observaciones:
        detalles.append(fila('Observaciones', egreso.observaciones))

    tabla_detalles = Table(detalles, colWidths=[5 * cm, 12 * cm])
    tabla_detalles.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), COLOR_ACCENT),
        ('VALIGN',     (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING',  (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING',   (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 6),
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [white, COLOR_ACCENT]),
        ('BOX', (0, 0), (-1, -1), 0.5, gray),
        ('INNERGRID', (0, 0), (-1, -1), 0.25, gray),
    ]))
    story.append(tabla_detalles)
    story.append(Spacer(1, 0.8 * cm))

    # ── SESIONES CUBIERTAS (solo si es honorario con sesiones) ────────────────
    sesiones = egreso.sesiones_cubiertas.select_related('paciente').all()
    if sesiones.exists():
        story.append(Paragraph(
            'Sesiones cubiertas por este honorario',
            ParagraphStyle('sh', parent=styles['Normal'], fontSize=10,
                           textColor=COLOR_PRIMARY, fontName='Helvetica-Bold',
                           spaceBefore=4, spaceAfter=4)
        ))
        ses_data = [['Fecha', 'Paciente', 'Monto cobrado']]
        for s in sesiones:
            ses_data.append([
                s.fecha.strftime('%d/%m/%Y') if hasattr(s, 'fecha') else '—',
                str(s.paciente),
                f'Bs. {s.monto_cobrado:,.0f}' if hasattr(s, 'monto_cobrado') else '—',
            ])
        tabla_ses = Table(ses_data, colWidths=[4 * cm, 9 * cm, 4 * cm])
        tabla_ses.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), COLOR_PRIMARY),
            ('TEXTCOLOR',  (0, 0), (-1, 0), white),
            ('FONTNAME',   (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE',   (0, 0), (-1, -1), 9),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, COLOR_ACCENT]),
            ('BOX',        (0, 0), (-1, -1), 0.5, gray),
            ('INNERGRID',  (0, 0), (-1, -1), 0.25, gray),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ]))
        story.append(tabla_ses)
        story.append(Spacer(1, 0.5 * cm))

    # ── PIE: registrado por + fecha de registro ───────────────────────────────
    story.append(HRFlowable(width='100%', thickness=1, color=COLOR_ACCENT))
    story.append(Spacer(1, 0.3 * cm))

    pie_data = [
        [
            Paragraph(
                f'Registrado por: <b>{egreso.registrado_por.get_full_name() or egreso.registrado_por.username}</b>',
                estilo_footer
            ),
            Paragraph(
                f'Fecha de registro: <b>{egreso.fecha_registro.strftime("%d/%m/%Y %H:%M")}</b>',
                estilo_footer
            ),
        ]
    ]
    tabla_pie = Table(pie_data, colWidths=[8.5 * cm, 8.5 * cm])
    tabla_pie.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(tabla_pie)
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(
        f'Documento generado el {date.today().strftime("%d/%m/%Y")} — '
        f'Sistema de Gestión del Centro',
        estilo_footer
    ))

    # ── Generar PDF ───────────────────────────────────────────────────────────
    doc.build(story)
    return buffer.getvalue()