"""
Formatos de fecha/hora del sistema (sobrescriben los del locale 'es' de Django).

Por qué existe este archivo: desde Django 5 la localización siempre está
activa, por lo que DATE_FORMAT / DATETIME_FORMAT definidos en settings.py se
IGNORAN y se usa el formato del locale ("11 de octubre de 2026").
Con FORMAT_MODULE_PATH, Django usa estos valores en todas partes:
plantillas ({{ fecha }}), admin, formularios, etc.

CONVENCIÓN: día-mes-año  →  dd/mm/aaaa
"""

DATE_FORMAT = "d/m/Y"
DATETIME_FORMAT = "d/m/Y H:i"
TIME_FORMAT = "H:i"
SHORT_DATE_FORMAT = "d/m/Y"
SHORT_DATETIME_FORMAT = "d/m/Y H:i"
YEAR_MONTH_FORMAT = r"F \d\e Y"
MONTH_DAY_FORMAT = r"j \d\e F"
FIRST_DAY_OF_WEEK = 1  # Lunes

# El PRIMER formato es el que usan los widgets al mostrar el valor.
DATE_INPUT_FORMATS = [
    "%d/%m/%Y",  # 31/12/2009
    "%d-%m-%Y",  # 31-12-2009
    "%d/%m/%y",  # 31/12/09
]
DATETIME_INPUT_FORMATS = [
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M:%S.%f",
    "%d/%m/%Y %H:%M",
    "%d-%m-%Y %H:%M:%S",
    "%d-%m-%Y %H:%M",
    "%d/%m/%y %H:%M:%S",
    "%d/%m/%y %H:%M",
]

# Separadores numéricos (DECIMAL_SEPARATOR, THOUSAND_SEPARATOR, ...): se heredan del
# locale 'es' de Django; este módulo solo redefine FECHAS Y HORAS.
