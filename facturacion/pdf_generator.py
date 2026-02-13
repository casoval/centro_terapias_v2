# facturacion/pdf_generator.py
# =====================================================
# GENERADOR DE PDF - VERSIÓN PERSONALIZADA
# Ajustes aplicados:
# 1. Recuadro azul bajado más
# 2. Sin iconografía (eliminados todos los íconos)
# 3. Firmas subidas en la parte inferior
# 4. QR más grande (2.0 cm)
# 5. Eliminado texto "CORTAR AQUÍ" del centro
# 6. Diseño limpio y profesional
# 7. Tabla con 3 columnas: #, CONCEPTO, MONTO
# 8. Concepto detallado (ej: "Pago sesión 2026-02-23 - Servicio 1")
# =====================================================

import os
import logging
from io import BytesIO
from decimal import Decimal
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.units import cm, mm
from reportlab.lib import colors
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.platypus import Table, TableStyle, Paragraph
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics import renderPDF
from django.conf import settings 
from pathlib import Path
import hashlib

logger = logging.getLogger(__name__)

# =====================================================
# 1. PALETA DE COLORES PROFESIONAL
# =====================================================
# Colores principales - Tonos más suaves y profesionales
COLOR_AZUL_PRIMARIO = colors.HexColor('#1E88E5')      # Azul vibrante pero no agresivo
COLOR_AZUL_CLARO = colors.HexColor('#64B5F6')
COLOR_AZUL_OSCURO = colors.HexColor('#1565C0')

COLOR_VERDE_PRIMARIO = colors.HexColor('#43A047')
COLOR_VERDE_CLARO = colors.HexColor('#81C784')

COLOR_NARANJA_PRIMARIO = colors.HexColor('#FB8C00')
COLOR_NARANJA_CLARO = colors.HexColor('#FFB74D')

COLOR_AMARILLO_PRIMARIO = colors.HexColor('#FDD835')
COLOR_AMARILLO_CLARO = colors.HexColor('#FFF176')

COLOR_ROJO_PRIMARIO = colors.HexColor('#E53935')
COLOR_ROJO_CLARO = colors.HexColor('#EF5350')
COLOR_ROJO_OSCURO = colors.HexColor('#8B0000')  # Rojo oscuro para campos específicos

# Colores de fondo y texto
COLOR_FONDO_PAGINA = colors.HexColor('#F8F9FA')
COLOR_FONDO_TARJETA = colors.white
COLOR_TEXTO_PRINCIPAL = colors.HexColor('#212121')
COLOR_TEXTO_SECUNDARIO = colors.HexColor('#757575')
COLOR_GRIS_CLARO = colors.HexColor('#EEEEEE')
COLOR_GRIS_MEDIO = colors.HexColor('#BDBDBD')
COLOR_GRIS_BORDE = colors.HexColor('#E0E0E0')

# Colores para tabla
COLOR_FILA_PAR = colors.HexColor('#FAFAFA')
COLOR_FILA_IMPAR = colors.white

# Datos del Centro
NOMBRE_CENTRO = "Centro de Neurodesarrollo Infantil Misael"
DIRECCION = "Calle Japón #28 • Potosí, Bolivia"
TELEFONO = "Tel.: 76175352"

# Configuración de Página
PAGE_WIDTH, PAGE_HEIGHT = landscape(letter)
MARGIN = 0.5 * cm
GAP_CENTRAL = 1.0 * cm
ANCHO_RECIBO = (PAGE_WIDTH - (2 * MARGIN) - GAP_CENTRAL) / 2
ALTO_RECIBO = PAGE_HEIGHT - (2 * MARGIN)

# =====================================================
# 2. FUNCIONES DE UTILIDAD PARA DISEÑO
# =====================================================

def dibujar_gradiente_horizontal(c, x, y, ancho, alto, color1, color2, steps=30):
    """Dibuja un gradiente horizontal suave entre dos colores"""
    c.saveState()
    step_width = ancho / steps
    
    for i in range(steps):
        ratio = i / steps
        r = color1.red + (color2.red - color1.red) * ratio
        g = color1.green + (color2.green - color1.green) * ratio
        b = color1.blue + (color2.blue - color1.blue) * ratio
        
        c.setFillColor(colors.Color(r, g, b))
        c.rect(x + i * step_width, y, step_width + 1, alto, fill=1, stroke=0)
    
    c.restoreState()

def dibujar_gradiente_redondeado(c, x, y, ancho, alto, color1, color2, radio=8, steps=30):
    """Dibuja un gradiente horizontal con bordes redondeados usando clipPath"""
    c.saveState()
    
    # Crear máscara de recorte con bordes redondeados
    path = c.beginPath()
    path.roundRect(x, y, ancho, alto, radio)
    c.clipPath(path, stroke=0)
    
    # Dibujar gradiente dentro de la máscara
    step_width = ancho / steps
    for i in range(steps):
        ratio = i / steps
        r = color1.red + (color2.red - color1.red) * ratio
        g = color1.green + (color2.green - color1.green) * ratio
        b = color1.blue + (color2.blue - color1.blue) * ratio
        
        c.setFillColor(colors.Color(r, g, b))
        c.rect(x + i * step_width, y, step_width + 1, alto, fill=1, stroke=0)
    
    c.restoreState()

def dibujar_sombra_suave(c, x, y, ancho, alto, radio=10, offset=2):
    """Dibuja una sombra suave y sutil"""
    c.saveState()
    c.setFillColor(colors.HexColor('#00000015'))  # Muy sutil
    c.roundRect(x + offset, y - offset, ancho, alto, radio, fill=1, stroke=0)
    c.restoreState()

def generar_hash_verificacion(numero_recibo, fecha, monto):
    """Genera un hash único para validación del recibo"""
    texto = f"{numero_recibo}{fecha}{monto}"
    return hashlib.md5(texto.encode()).hexdigest()[:8].upper()

def crear_qr_code(c, x, y, data, size=1.5*cm):
    """Crea y dibuja un código QR"""
    try:
        qr_code = QrCodeWidget(data)
        bounds = qr_code.getBounds()
        width = bounds[2] - bounds[0]
        height = bounds[3] - bounds[1]
        
        d = Drawing(size, size, transform=[size/width, 0, 0, size/height, 0, 0])
        d.add(qr_code)
        renderPDF.draw(d, c, x, y)
    except Exception as e:
        logger.error(f"Error generando QR: {e}")

# =====================================================
# 3. ENTRADAS PRINCIPALES
# =====================================================

def generar_recibo_pdf(pago, **kwargs):
    return generar_pdf_maestro(pago, es_devolucion=False)

def generar_devolucion_pdf(devolucion, **kwargs):
    return generar_pdf_maestro(devolucion, es_devolucion=True)

# =====================================================
# 4. GENERADOR MAESTRO
# =====================================================

def generar_pdf_maestro(objeto, es_devolucion=False):
    buffer = BytesIO()
    c = pdf_canvas.Canvas(buffer, pagesize=landscape(letter))
    obj_id = getattr(objeto, 'id', '000') or '000'
    c.setTitle(f"{'Devolucion' if es_devolucion else 'Recibo'}_{obj_id}")

    # Fondo de página
    c.setFillColor(COLOR_FONDO_PAGINA)
    c.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, fill=1, stroke=0)

    # 1. Recibo Izquierdo (ORIGINAL)
    dibujar_recibo_optimizado(c, MARGIN, MARGIN, objeto, es_devolucion, "ORIGINAL: CLIENTE")

    # 2. Línea de corte
    dibujar_linea_corte(c)

    # 3. Recibo Derecho (COPIA)
    dibujar_recibo_optimizado(c, MARGIN + ANCHO_RECIBO + GAP_CENTRAL, MARGIN, objeto, es_devolucion, "COPIA: ADMINISTRACIÓN")

    c.save()
    pdf_data = buffer.getvalue()
    buffer.close()
    return pdf_data

# =====================================================
# 5. FUNCIÓN PRINCIPAL DE DIBUJO
# =====================================================

def dibujar_recibo_optimizado(c, x, y, obj, es_devolucion, texto_copia):
    """Dibuja un recibo completo con diseño optimizado"""
    top = y + ALTO_RECIBO
    
    # --- A. TARJETA BASE CON SOMBRA SUTIL ---
    dibujar_sombra_suave(c, x, y, ANCHO_RECIBO, ALTO_RECIBO, radio=10, offset=3)
    
    c.saveState()
    c.setFillColor(COLOR_FONDO_TARJETA)
    c.setStrokeColor(COLOR_GRIS_BORDE)
    c.setLineWidth(0.5)
    c.roundRect(x, y, ANCHO_RECIBO, ALTO_RECIBO, 10, fill=1, stroke=1)
    c.restoreState()

    # --- C. BARRA SUPERIOR CON GRADIENTES ---
    y_barra = top - 0.6*cm
    alto_barra = 0.45 * cm
    
    if es_devolucion:
        # Gradiente rojo para devoluciones
        dibujar_gradiente_horizontal(
            c, x + 0.2*cm, y_barra, 
            ANCHO_RECIBO - 0.4*cm, alto_barra,
            COLOR_ROJO_CLARO, COLOR_ROJO_PRIMARIO
        )
    else:
        # Gradiente multicolor para pagos
        ancho_seccion = (ANCHO_RECIBO - 0.4*cm) / 4
        colores_inicio = [COLOR_AZUL_CLARO, COLOR_VERDE_CLARO, COLOR_AMARILLO_CLARO, COLOR_NARANJA_CLARO]
        colores_fin = [COLOR_AZUL_PRIMARIO, COLOR_VERDE_PRIMARIO, COLOR_AMARILLO_PRIMARIO, COLOR_NARANJA_PRIMARIO]
        
        for i in range(4):
            dibujar_gradiente_horizontal(
                c, x + 0.2*cm + i * ancho_seccion, y_barra,
                ancho_seccion, alto_barra,
                colores_inicio[i], colores_fin[i],
                steps=15
            )
    
    # Borde redondeado
    c.saveState()
    c.setStrokeColor(colors.white)
    c.setLineWidth(1.5)
    c.roundRect(x + 0.2*cm, y_barra, ANCHO_RECIBO - 0.4*cm, alto_barra, 5, fill=0, stroke=1)
    c.restoreState()

    # --- D. HEADER OPTIMIZADO ---
    y_header = y_barra - 0.3*cm
    dibujar_header_optimizado(c, x, y_header, obj, es_devolucion)

    # --- E. INFORMACIÓN DEL PACIENTE ---
    y_paciente = y_header - 3.5*cm  # Ajustado
    dibujar_info_paciente_optimizada(c, x, y_paciente, obj)

    # --- F. TABLA DE DETALLES ---
    y_tabla = y_paciente - 1.90*cm  # Ajustado
    altura_tabla = dibujar_tabla_detalles_optimizada(c, x, y_tabla, obj, es_devolucion)

    # --- F.1. OBSERVACIONES (si existen) ---
    y_observaciones = y_tabla - altura_tabla - 0.3*cm
    altura_observaciones = dibujar_observaciones_si_existen(c, x, y_observaciones, obj)

    # --- G. TOTALES ---
    y_totales = y_observaciones - altura_observaciones - 0.3*cm
    dibujar_seccion_totales_optimizada(c, x, y_totales, obj, es_devolucion)

    # --- H. QR CODE ---
    dibujar_qr_optimizado(c, x, y, obj, es_devolucion)

    # --- I. FOOTER ---
    dibujar_footer_optimizado(c, x, y, texto_copia)

    # --- J. FIRMAS ---
    dibujar_seccion_firmas_optimizada(c, x, y)
    
    # --- K. MARCA DE AGUA (POR ENCIMA) ---
    dibujar_marca_agua_optimizada(c, x, y, texto_copia)

# =====================================================
# 6. FUNCIONES DE SECCIONES OPTIMIZADAS
# =====================================================

def convertir_imagen_a_escala_grises(logo_path):
    """Convierte una imagen a escala de grises"""
    try:
        from PIL import Image
        img = Image.open(logo_path)
        # Convertir a escala de grises
        img_gray = img.convert('LA')  # L=Luminancia, A=Alpha
        return img_gray
    except Exception as e:
        logger.error(f"Error convirtiendo imagen a escala de grises: {e}")
        return None

def dibujar_marca_agua_optimizada(c, x, y, texto_copia):
    """Marca de agua en patrón repetido con escala de grises y opacidad adaptativa"""
    logo_path = encontrar_logo_misael()
    
    if not logo_path:
        return
    
    try:
        # Convertir logo a escala de grises
        img_gray = convertir_imagen_a_escala_grises(logo_path)
        if not img_gray:
            return
        
        # Guardar temporalmente la imagen en escala de grises
        from io import BytesIO
        buffer = BytesIO()
        img_gray.save(buffer, format='PNG')
        buffer.seek(0)
        
        img_reader = ImageReader(buffer)
        iw, ih = img_reader.getSize()
        aspect = ih / float(iw)
        
        # Configuración del patrón - REDUCIDO Y MÁS ESPACIADO
        logo_size = 3.5 * cm  # Reducido de 4.5 a 3.0 cm
        logo_height = logo_size * aspect
        spacing_x = 6.5 * cm  # Aumentado de 5.5 a 7.0 cm
        spacing_y = 5.0 * cm  # Aumentado de 5.5 a 7.0 cm
        rotation = -25  # Rotación diagonal del patrón
        
        # Calcular cuántos logos caben en el recibo
        num_cols = int(ANCHO_RECIBO / spacing_x) + 1  # Reducido para menos logos
        num_rows = int(ALTO_RECIBO / spacing_y) + 1
        
        # Definir secciones del recibo para opacidad adaptativa
        top = y + ALTO_RECIBO
        y_barra = top - 0.6*cm
        y_header = y_barra - 0.3*cm
        y_fin_header = y_header - 3.5*cm
        
        y_paciente = y_header - 3.5*cm
        y_fin_paciente = y_paciente - 1.5*cm
        
        y_tabla = y_paciente - 1.90*cm
        y_fin_tabla = y + 2.5*cm
        
        # Dibujar patrón de logos
        for row in range(num_rows):
            for col in range(num_cols):
                c.saveState()
                
                # Calcular posición de este logo
                # Patrón alternado (offset en filas impares)
                offset_x = (spacing_x / 2) if row % 2 == 1 else 0
                logo_x = x + (col * spacing_x) + offset_x - (spacing_x * 0.3)
                logo_y = y + (row * spacing_y) - (spacing_y * 0.3)
                
                # Calcular el centro del logo para determinar su zona
                logo_center_y = logo_y + (logo_height / 2)
                
                # Determinar opacidad según la zona del recibo donde está el centro del logo
                if logo_center_y >= y_header - 1*cm:
                    # Zona de header con gradientes de colores → más claro
                    opacity = 0.03
                elif logo_center_y >= y_fin_paciente:
                    # Zona de info paciente con fondo gris claro → intermedio
                    opacity = 0.06
                elif logo_center_y >= y_fin_tabla:
                    # Zona de tabla y totales con fondo blanco → más oscuro
                    opacity = 0.08
                else:
                    # Zona de footer/firmas con fondos → más claro
                    opacity = 0.04
                
                c.setFillAlpha(opacity)
                
                # Aplicar rotación desde el centro del logo
                c.translate(logo_x + logo_size/2, logo_y + logo_height/2)
                c.rotate(rotation)
                c.translate(-(logo_x + logo_size/2), -(logo_y + logo_height/2))
                
                # Dibujar el logo
                c.drawImage(img_reader, logo_x, logo_y, 
                           width=logo_size, height=logo_height, 
                           mask='auto', preserveAspectRatio=True)
                
                c.restoreState()
            
    except Exception as e:
        logger.error(f"Error en marca de agua con patrón repetido: {e}")

def dibujar_header_optimizado(c, x, y_base, obj, es_devolucion):
    """Header con mejor proporción y espaciado"""
    
    # Logo
    logo_path = encontrar_logo_misael()
    logo_height_used = 0
    
    if logo_path:
        try:
            logo_x = x + 0.5*cm
            logo_y_base = y_base - 2.5*cm
            
            img = ImageReader(logo_path)
            iw, ih = img.getSize()
            aspect = ih / float(iw)
            logo_w = 2.2 * cm
            logo_h = logo_w * aspect
            logo_height_used = logo_h
            
            c.drawImage(logo_path, logo_x, logo_y_base, 
                       width=logo_w, height=logo_h, mask='auto')
        except:
            pass

    # Información del centro - SIN ICONOS
    text_x = x + 3.0 * cm
    y_text = y_base - 0.5*cm
    
    c.setFillColor(COLOR_TEXTO_PRINCIPAL)
    c.setFont("Helvetica-Bold", 13.5)
    c.drawString(text_x, y_text, NOMBRE_CENTRO)
    
    c.setFont("Helvetica", 9)
    c.setFillColor(COLOR_TEXTO_SECUNDARIO)
    c.drawString(text_x, y_text - 0.45*cm, DIRECCION)
    c.drawString(text_x, y_text - 0.95*cm, TELEFONO)

    # Caja de número de recibo - BAJADA MÁS
    titulo = "RECIBO DE PAGO" if not es_devolucion else "DEVOLUCIÓN"
    num = safe_str(getattr(obj, 'numero_devolucion', getattr(obj, 'numero_recibo', '---')))
    
    box_w = 4.2 * cm
    box_h = 1.7 * cm
    box_x = x + ANCHO_RECIBO - box_w - 0.5*cm
    box_y = y_base - 3.00*cm  # BAJADO DE -2.2cm A -3.0cm
    
    # Colores para el gradiente
    color_inicio = COLOR_ROJO_CLARO if es_devolucion else COLOR_AZUL_CLARO
    color_fin = COLOR_ROJO_PRIMARIO if es_devolucion else COLOR_AZUL_PRIMARIO
    
    # Sombra
    dibujar_sombra_suave(c, box_x, box_y, box_w, box_h, radio=8, offset=2)
    
    # Fondo con gradiente redondeado
    dibujar_gradiente_redondeado(c, box_x, box_y, box_w, box_h, color_inicio, color_fin, radio=8, steps=20)
    
    # Borde blanco redondeado
    c.saveState()
    c.setStrokeColor(colors.white)
    c.setLineWidth(1.5)
    c.roundRect(box_x, box_y, box_w, box_h, 8, fill=0, stroke=1)
    c.restoreState()
    
    # Texto
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(box_x + box_w/2, box_y + 1.15*cm, titulo)
    
    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(box_x + box_w/2, box_y + 0.4*cm, f"N° {num}")

def dibujar_info_paciente_optimizada(c, x, y_base, obj):
    """Panel de información del paciente más limpio"""
    
    alto_panel = 1.5 * cm
    
    # Panel con fondo sutil
    c.saveState()
    c.setFillColor(COLOR_GRIS_CLARO)
    c.setFillAlpha(0.4)
    c.roundRect(x + 0.4*cm, y_base - alto_panel, ANCHO_RECIBO - 0.8*cm, alto_panel, 6, fill=1, stroke=0)
    c.restoreState()
    
    # Borde sutil
    c.saveState()
    c.setStrokeColor(COLOR_GRIS_MEDIO)
    c.setLineWidth(0.5)
    c.roundRect(x + 0.4*cm, y_base - alto_panel, ANCHO_RECIBO - 0.8*cm, alto_panel, 6, fill=0, stroke=1)
    c.restoreState()
    
    # Datos del paciente
    paciente = "---"
    tutor = "---"
    if hasattr(obj, 'paciente') and obj.paciente:
        p_nombre = safe_str(obj.paciente.nombre)
        p_apellido = safe_str(obj.paciente.apellido)
        paciente = f"{p_nombre} {p_apellido}".title()
        if hasattr(obj.paciente, 'tutor'):
            tutor = safe_str(str(obj.paciente.tutor))
        elif hasattr(obj.paciente, 'padre'):
            tutor = safe_str(str(obj.paciente.padre))
        elif hasattr(obj.paciente, 'nombre_tutor'):
            tutor = safe_str(obj.paciente.nombre_tutor)
    
    fecha = getattr(obj, 'fecha_emision', getattr(obj, 'fecha_pago', None))
    fecha_str = fecha.strftime("%d/%m/%Y") if fecha else "---"
    
    # Datos - SIN ICONOS
    y_datos = y_base - 0.60*cm
    x_datos = x + 0.7*cm
    
    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(COLOR_ROJO_OSCURO)
    c.drawString(x_datos, y_datos, "PACIENTE:")
    
    c.setFont("Helvetica", 10)
    c.setFillColor(COLOR_TEXTO_PRINCIPAL)
    c.drawString(x_datos + 1.9*cm, y_datos, paciente)
    
    y_datos -= 0.55*cm
    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(COLOR_ROJO_OSCURO)
    c.drawString(x_datos, y_datos, "TUTOR:")
    
    c.setFont("Helvetica", 10)
    c.setFillColor(COLOR_TEXTO_PRINCIPAL)
    c.drawString(x_datos + 1.9*cm, y_datos, tutor)
    
    # Fecha en el lado derecho
    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(COLOR_ROJO_OSCURO)
    c.drawRightString(x + ANCHO_RECIBO - 0.8*cm, y_base - 0.60*cm, "FECHA:")
    
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(COLOR_TEXTO_PRINCIPAL)
    c.drawRightString(x + ANCHO_RECIBO - 0.8*cm, y_base - 1.15*cm, fecha_str)

def dibujar_tabla_detalles_optimizada(c, x, y_base, obj, es_devolucion):
    """Tabla con 3 columnas: #, CONCEPTO detallado, MONTO"""
    
    filas_datos = extraer_detalles_enriquecidos(obj)
    
    # Encabezados - 3 COLUMNAS CON CONTADOR
    headers = [[
        "#",
        "CONCEPTO",
        "MONTO (Bs.)"
    ]]
    
    # Filas de datos - CON NUMERACIÓN
    filas_formateadas = []
    contador = 1
    for concepto, monto in filas_datos:
        filas_formateadas.append([
            str(contador),
            concepto,
            monto
        ])
        contador += 1
    
    # Combinar
    tabla_data = headers + filas_formateadas
    
    # Anchos - 3 COLUMNAS: 7% contador, 70% concepto, 23% monto
    ancho_tabla = ANCHO_RECIBO - 0.8*cm
    col_widths = [ancho_tabla * 0.07, ancho_tabla * 0.75, ancho_tabla * 0.18]
    
    # Crear tabla
    tabla = Table(tabla_data, colWidths=col_widths, repeatRows=1)
    
    # Estilos
    color_header = COLOR_ROJO_PRIMARIO if es_devolucion else COLOR_AZUL_PRIMARIO
    
    estilos_tabla = [
        # Header
        ('BACKGROUND', (0, 0), (-1, 0), color_header),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (0, 0), 'CENTER'),  # Columna # centrada
        ('ALIGN', (1, 0), (1, 0), 'LEFT'),    # Columna CONCEPTO a la izquierda
        ('ALIGN', (2, 0), (2, 0), 'RIGHT'),   # Columna MONTO a la derecha
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
        ('TOPPADDING', (0, 0), (-1, 0), 6),
        
        # Datos
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('ALIGN', (0, 1), (0, -1), 'CENTER'),  # Columna 0 (#) centrado
        ('ALIGN', (2, 1), (2, -1), 'RIGHT'),   # Columna 2 (MONTO) alineada a la derecha
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 1), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 5),
        
        # Bordes
        ('BOX', (0, 0), (-1, -1), 1, COLOR_GRIS_MEDIO),
        ('LINEBELOW', (0, 0), (-1, 0), 1.5, colors.white),
        ('INNERGRID', (0, 1), (-1, -1), 0.5, COLOR_GRIS_CLARO),
    ]
    
    # Zebra striping
    for i in range(1, len(tabla_data)):
        if i % 2 == 0:
            estilos_tabla.append(('BACKGROUND', (0, i), (-1, i), COLOR_FILA_PAR))
    
    tabla.setStyle(TableStyle(estilos_tabla))
    
    # Dibujar
    w_t, h_t = tabla.wrapOn(c, ancho_tabla, ALTO_RECIBO)
    tabla.drawOn(c, x + 0.4*cm, y_base - h_t)
    
    return h_t

def dibujar_observaciones_si_existen(c, x, y_base, obj):
    """Dibuja observaciones si existen, retorna altura usada"""
    
    # Verificar si hay observaciones
    observaciones = getattr(obj, 'observaciones', None)
    
    if not observaciones or not observaciones.strip():
        return 0  # No hay observaciones, no ocupa espacio
    
    # Dimensiones
    ancho_panel = ANCHO_RECIBO - 0.8*cm
    padding = 0.3*cm
    
    # Panel con fondo sutil
    c.saveState()
    c.setFillColor(COLOR_GRIS_CLARO)
    c.setFillAlpha(0.3)
    
    # Calcular altura necesaria para el texto
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph
    
    estilo_obs = ParagraphStyle(
        'observaciones',
        fontName='Helvetica',
        fontSize=8,
        textColor=COLOR_TEXTO_PRINCIPAL,
        leading=10,
        leftIndent=0,
        rightIndent=0,
    )
    
    # Crear párrafo para calcular altura
    p = Paragraph(observaciones, estilo_obs)
    ancho_texto = ancho_panel - (2 * padding)
    w, h = p.wrap(ancho_texto, ALTO_RECIBO)
    
    # Altura total del panel
    altura_panel = h + (2 * padding) + 0.4*cm  # +0.4cm para el título
    
    # Dibujar fondo
    c.roundRect(x + 0.4*cm, y_base - altura_panel, ancho_panel, altura_panel, 6, fill=1, stroke=0)
    c.restoreState()
    
    # Borde sutil
    c.saveState()
    c.setStrokeColor(COLOR_GRIS_MEDIO)
    c.setLineWidth(0.5)
    c.roundRect(x + 0.4*cm, y_base - altura_panel, ancho_panel, altura_panel, 6, fill=0, stroke=1)
    c.restoreState()
    
    # Título "OBSERVACIONES:"
    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(COLOR_ROJO_OSCURO)
    c.drawString(x + 0.4*cm + padding, y_base - 0.5*cm, "OBSERVACIONES:")
    
    # Dibujar el texto de observaciones
    p.drawOn(c, x + 0.4*cm + padding, y_base - altura_panel + padding)
    
    return altura_panel

def dibujar_seccion_totales_optimizada(c, x, y_base, obj, es_devolucion):
    """Sección de totales más balanceada"""
    
    monto = safe_decimal(getattr(obj, 'monto', 0))
    
    # Caja de total
    box_w = 5.5 * cm
    box_h = 1.5 * cm
    box_x = x + ANCHO_RECIBO - box_w - 0.5*cm
    box_y = y_base - box_h
    
    # Sombra
    dibujar_sombra_suave(c, box_x, box_y, box_w, box_h, radio=8, offset=2)
    
    # Fondo con gradiente redondeado
    dibujar_gradiente_redondeado(
        c, box_x, box_y, box_w, box_h,
        COLOR_AMARILLO_CLARO, COLOR_AMARILLO_PRIMARIO,
        radio=8, steps=20
    )
    
    # Borde
    c.saveState()
    c.setStrokeColor(COLOR_AMARILLO_PRIMARIO)
    c.setLineWidth(1.5)
    c.roundRect(box_x, box_y, box_w, box_h, 8, fill=0, stroke=1)
    c.restoreState()
    
    # Texto
    c.setFillColor(COLOR_TEXTO_PRINCIPAL)
    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(box_x + box_w - 0.4*cm, box_y + 1.0*cm, "TOTAL PAGADO")
    
    c.setFont("Helvetica-Bold", 18)
    c.drawRightString(box_x + box_w - 0.4*cm, box_y + 0.25*cm, f"Bs. {monto:,.2f}")
    
    # Monto en letras
    monto_literal = monto_a_letras(monto)
    
    c.setFillColor(COLOR_TEXTO_SECUNDARIO)
    c.setFont("Helvetica-BoldOblique", 7)
    c.drawRightString(x + ANCHO_RECIBO - 0.5*cm, y_base - box_h - 0.45*cm, f"SON: {monto_literal}")
    
    # Info pago (izquierda)
    metodo = "Efectivo"
    if hasattr(obj, 'metodo_pago') and obj.metodo_pago:
        metodo = safe_str(obj.metodo_pago.nombre)
    
    usuario = "Sistema"
    if hasattr(obj, 'registrado_por') and obj.registrado_por:
        usuario = safe_str(obj.registrado_por.username)
    
    y_info = y_base - 0.4*cm
    x_info = x + 0.6*cm
    
    c.setFont("Helvetica", 7)
    c.setFillColor(COLOR_ROJO_OSCURO)
    c.drawString(x_info, y_info, "MÉTODO DE PAGO:")
    
    c.setFont("Helvetica", 8)
    c.setFillColor(COLOR_TEXTO_PRINCIPAL)
    c.drawString(x_info, y_info - 0.35*cm, metodo)
    
    y_info -= 0.75*cm
    c.setFont("Helvetica", 7)
    c.setFillColor(COLOR_ROJO_OSCURO)
    c.drawString(x_info, y_info, "REGISTRADO POR:")
    
    c.setFont("Helvetica", 8)
    c.setFillColor(COLOR_TEXTO_PRINCIPAL)
    c.drawString(x_info, y_info - 0.35*cm, usuario)

def dibujar_qr_optimizado(c, x, y, obj, es_devolucion):
    """QR MÁS GRANDE (2.0 cm)"""
    
    # Generar datos
    numero = safe_str(getattr(obj, 'numero_devolucion' if es_devolucion else 'numero_recibo', '---'))
    fecha = getattr(obj, 'fecha_emision', getattr(obj, 'fecha_pago', None))
    fecha_str = fecha.strftime("%Y%m%d") if fecha else "00000000"
    monto = safe_decimal(getattr(obj, 'monto', 0))
    
    hash_verificacion = generar_hash_verificacion(numero, fecha_str, str(monto))
    
    url_validacion = f"https://centromisael.com/validar/{numero}/{hash_verificacion}"
    
    # Posición - QR MÁS GRANDE
    qr_size = 2.0 * cm  # AUMENTADO DE 1.6cm A 2.0cm
    qr_x = x + ANCHO_RECIBO - qr_size - 0.5*cm
    qr_y = y + 2.8*cm
    
    # Marco
    c.saveState()
    c.setFillColor(colors.white)
    c.setStrokeColor(COLOR_GRIS_MEDIO)
    c.setLineWidth(0.5)
    c.roundRect(qr_x - 0.1*cm, qr_y - 0.1*cm, 
                qr_size + 0.2*cm, qr_size + 0.2*cm, 
                4, fill=1, stroke=1)
    c.restoreState()
    
    # QR
    crear_qr_code(c, qr_x, qr_y, url_validacion, qr_size)
    
    # Texto
    c.setFont("Helvetica", 6)
    c.setFillColor(COLOR_TEXTO_SECUNDARIO)
    c.drawCentredString(qr_x + qr_size/2, qr_y - 0.35*cm, "Escanea para validar")
    
    c.setFont("Helvetica-Bold", 6)
    c.setFillColor(COLOR_TEXTO_PRINCIPAL)
    c.drawCentredString(qr_x + qr_size/2, y + 2.15*cm, f"#{hash_verificacion}")

def dibujar_footer_optimizado(c, x, y, texto_copia):
    """Footer más limpio"""
    
    y_footer = y + 0.35*cm
    
    if "CLIENTE" in texto_copia:
        bg_color = COLOR_AZUL_PRIMARIO
        fg_color = colors.white
    else:
        bg_color = COLOR_GRIS_CLARO
        fg_color = COLOR_TEXTO_PRINCIPAL
    
    badge_w = 6.5 * cm
    badge_h = 0.6 * cm
    badge_x = x + ANCHO_RECIBO/2 - badge_w/2
    
    dibujar_sombra_suave(c, badge_x, y_footer, badge_w, badge_h, radio=6, offset=1)
    
    c.setFillColor(bg_color)
    c.roundRect(badge_x, y_footer, badge_w, badge_h, 6, fill=1, stroke=0)
    
    c.setFillColor(fg_color)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(x + ANCHO_RECIBO/2, y_footer + 0.18*cm, texto_copia)

def dibujar_seccion_firmas_optimizada(c, x, y):
    """Firmas SUBIDAS - SIN ICONOS"""
    
    y_firmas = y + 1.6*cm  # SUBIDO DE 1.2cm A 1.6cm
    
    c.saveState()
    c.setStrokeColor(COLOR_GRIS_MEDIO)
    c.setLineWidth(0.5)
    c.setDash([2, 2])
    
    # Firma centro - SIN ICONO
    c.line(x + 0.8*cm, y_firmas, x + 4.5*cm, y_firmas)
    c.setFont("Helvetica", 7)
    c.setFillColor(COLOR_TEXTO_SECUNDARIO)
    c.drawCentredString(x + 2.65*cm, y_firmas - 0.3*cm, "FIRMA AUTORIZADA CENTRO")
    
    # Firma tutor - SIN ICONO
    c.line(x + ANCHO_RECIBO - 6.5*cm, y_firmas, x + ANCHO_RECIBO - 2.8*cm, y_firmas)
    c.drawCentredString(x + ANCHO_RECIBO - 4.65*cm, y_firmas - 0.3*cm, "FIRMA TUTOR/RESPONSABLE")
    
    c.setDash([])
    c.restoreState()

def dibujar_linea_corte(c):
    """Línea de corte SIMPLE - solo línea punteada"""
    
    x = PAGE_WIDTH / 2
    
    c.saveState()
    c.setStrokeColor(COLOR_GRIS_MEDIO)
    c.setLineWidth(0.5)
    c.setDash([4, 4])
    c.line(x, MARGIN + 0.5*cm, x, PAGE_HEIGHT - MARGIN - 0.5*cm)
    c.setDash([])
    c.restoreState()

# =====================================================
# 7. FUNCIONES AUXILIARES
# =====================================================

def monto_a_letras(monto):
    """Convierte un Decimal o float a texto literal"""
    try:
        monto = Decimal(monto).quantize(Decimal('0.01'))
        entero = int(monto)
        decimal = int(round((monto - entero) * 100))
        
        letras = NumeroALetras(entero)
        return f"{letras} {decimal:02d}/100 BOLIVIANOS".upper()
    except:
        return "MONTO NO VÁLIDO"

def NumeroALetras(num):
    """Convierte enteros a letras"""
    if num == 0:
        return "CERO"
    
    unidades = ["", "UN", "DOS", "TRES", "CUATRO", "CINCO", "SEIS", "SIETE", "OCHO", "NUEVE"]
    decenas = ["", "DIEZ", "VEINTE", "TREINTA", "CUARENTA", "CINCUENTA", "SESENTA", "SETENTA", "OCHENTA", "NOVENTA"]
    diez_veinte = ["DIEZ", "ONCE", "DOCE", "TRECE", "CATORCE", "QUINCE", "DIECISEIS", "DIECISIETE", "DIECIOCHO", "DIECINUEVE"]
    veinte_treinta = ["VEINTE", "VEINTIUNO", "VEINTIDOS", "VEINTITRES", "VEINTICUATRO", "VEINTICINCO", "VEINTISEIS", "VEINTISIETE", "VEINTIOCHO", "VEINTINUEVE"]
    centenas = ["", "CIENTO", "DOSCIENTOS", "TRESCIENTOS", "CUATROCIENTOS", "QUINIENTOS", "SEISCIENTOS", "SETECIENTOS", "OCHOCIENTOS", "NOVECIENTOS"]

    if num < 10:
        return unidades[num]
    if num < 20:
        return diez_veinte[num - 10]
    if num < 30:
        return veinte_treinta[num - 20]
    if num < 100:
        u = num % 10
        return decenas[num // 10] + (" Y " + unidades[u] if u > 0 else "")
    if num == 100:
        return "CIEN"
    if num < 1000:
        return centenas[num // 100] + (" " + NumeroALetras(num % 100) if num % 100 > 0 else "")
    if num < 1000000:
        miles = num // 1000
        resto = num % 1000
        texto_miles = "MIL" if miles == 1 else NumeroALetras(miles) + " MIL"
        return texto_miles + (" " + NumeroALetras(resto) if resto > 0 else "")
    if num < 1000000000:
        millones = num // 1000000
        resto = num % 1000000
        texto_millones = "UN MILLON" if millones == 1 else NumeroALetras(millones) + " MILLONES"
        return texto_millones + (" " + NumeroALetras(resto) if resto > 0 else "")
    
    return str(num)

def safe_str(val):
    if val is None:
        return ""
    return str(val)

def safe_decimal(val):
    if val is None:
        return Decimal(0)
    try:
        return Decimal(val)
    except:
        return Decimal(0)

def encontrar_logo_misael():
    base_dir = settings.BASE_DIR
    rutas = [
        base_dir / 'centro_terapias_v2' / 'staticfiles' / 'img' / 'logo_misael.png',
        base_dir / 'staticfiles' / 'img' / 'logo_misael.png',
        base_dir / 'static' / 'img' / 'logo_misael.png',
    ]
    for ruta in rutas:
        if os.path.exists(ruta):
            return str(ruta)
    return None

def extraer_detalles_enriquecidos(obj):
    """Extrae detalles del pago/devolución - SIN PROFESIONAL"""
    filas = []
    try:
        if hasattr(obj, 'detalles_masivos') and obj.detalles_masivos.exists():
            for det in obj.detalles_masivos.all():
                concepto_detallado = "Detalle"
                
                if det.mensualidad:
                    # Mensualidad: "Pago mensualidad 02/2026"
                    concepto_detallado = f"Pago mensualidad {det.mensualidad.mes:02d}/{det.mensualidad.anio}"
                    
                elif det.sesion:
                    # Sesión: "Pago sesión 2026-02-23 - Servicio 1 (09:00)"
                    nom_servicio = det.sesion.servicio.nombre if det.sesion.servicio else "Sesión"
                    fecha = det.sesion.fecha
                    
                    concepto_detallado = f"Pago sesión {fecha} - {nom_servicio}"
                    
                    # Agregar hora si existe
                    hora = getattr(det.sesion, 'hora_inicio', '')
                    if hora:
                        concepto_detallado += f" ({hora})"
                    
                elif det.proyecto:
                    # Proyecto: "Pago proyecto Nombre del Proyecto"
                    concepto_detallado = f"Pago proyecto {det.proyecto.nombre}"
                    
                elif hasattr(det, 'descripcion') and det.descripcion:
                    concepto_detallado = det.descripcion
                
                monto_safe = safe_decimal(det.monto)
                filas.append((safe_str(concepto_detallado), f"{monto_safe:,.2f}"))
        else:
            # Pago simple (sin detalles masivos)
            concepto_detallado = getattr(obj, 'concepto', 'Pago')
            
            if hasattr(obj, 'mensualidad') and obj.mensualidad:
                # Mensualidad
                concepto_detallado = f"Pago mensualidad {obj.mensualidad.mes:02d}/{obj.mensualidad.anio}"
                
            elif hasattr(obj, 'sesion') and obj.sesion:
                # Sesión: "Pago sesión 2026-02-23 - Servicio 1"
                srv = obj.sesion.servicio.nombre if obj.sesion.servicio else "Sesión"
                fecha = obj.sesion.fecha
                concepto_detallado = f"Pago sesión {fecha} - {srv}"
                
            elif hasattr(obj, 'proyecto') and obj.proyecto:
                # Proyecto
                concepto_detallado = f"Pago proyecto {obj.proyecto.nombre}"
            
            monto_safe = safe_decimal(getattr(obj, 'monto', 0))
            filas.append((safe_str(concepto_detallado), f"{monto_safe:,.2f}"))
            
    except Exception as e:
        logger.error(f"Error extrayendo detalles: {e}")
        m_safe = safe_decimal(getattr(obj, 'monto', 0))
        filas.append(("Pago General", f"{m_safe:,.2f}"))
    
    return filas