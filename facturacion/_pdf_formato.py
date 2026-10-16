"""
Funciones de formato compartidas por los informes PDF (profesional, sucursal, paciente, familia, asistencia).

Viven aquí, sin importar ningún otro módulo de informes, para evitar importaciones circulares:
informe_profesional_pdf -> informe_paciente_pdf -> informe_paciente_extra_pdf -> (formato) ya no vuelve a
informe_profesional_pdf. Los módulos de informe las reexportan, así que los imports existentes siguen valiendo.
"""

_REEMPLAZOS = {'≥': '>=', '≤': '<=', '×': 'x', '→': '->', '✔': 'OK', '✖': 'X', '●': '*',
               '′': "'", '’': "'", '“': '"', '”': '"', '\u00a0': ' ', '…': '...',
               '⚠': '(!)', '≈': '~', '💡': '', '·': '-', '—': '-', '–': '-'}


def _t(s):
    """Limpia caracteres fuera de WinAnsi (Helvetica estándar de ReportLab)."""
    s = '' if s is None else str(s)
    for a, b in _REEMPLAZOS.items():
        s = s.replace(a, b)
    return s.encode('latin-1', 'replace').decode('latin-1')


def fm(v, d=2):
    """1234.5 -> 1.234,50"""
    try:
        s = f"{float(v or 0):,.{d}f}"
    except Exception:
        return "0"
    return s.replace(',', '\x00').replace('.', ',').replace('\x00', '.')


def bs(v, d=2):
    return f"Bs. {fm(v, d)}"


def pc(v):
    try:
        return f"{float(v):.1f}%".replace('.', ',')
    except Exception:
        return "0,0%"


def fd(d, fmt='%d/%m/%Y'):
    try:
        return d.strftime(fmt)
    except Exception:
        return '-'
