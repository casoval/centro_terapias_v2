"""
Script de diagnóstico para verificar que la búsqueda de teléfonos
funciona correctamente con el código nuevo.

CÓMO EJECUTAR en el servidor:
    cd /var/www/centro_terapias
    source venv/bin/activate
    python manage.py shell < test_busqueda_telefono.py
"""

NUMEROS_A_PROBAR = [
    '59172416623',
    '59178714541',
    '59177470591',
]


def _normalizar_telefono(telefono: str) -> str:
    tel = telefono.strip().replace(' ', '').replace('-', '')
    if tel.startswith('+591'):
        tel = tel[4:]
    elif tel.startswith('591') and len(tel) > 9:
        tel = tel[3:]
    return tel


def diagnosticar(telefono: str):
    from pacientes.models import Paciente

    tel_norm = _normalizar_telefono(telefono)
    print(f"\n{'='*60}")
    print(f"  NÚMERO ORIGINAL : {telefono}")
    print(f"  NORMALIZADO     : {tel_norm}")
    print(f"{'='*60}")

    if not tel_norm or not tel_norm.isdigit():
        print("  Formato inválido - va a Agente Publico")
        return

    # Buscar como tutor_1
    m1 = list(Paciente.objects.filter(telefono_tutor=tel_norm, estado='activo'))
    print(f"\n  Coincidencias como telefono_tutor   : {len(m1)}")
    for p in m1:
        t2_nombre = getattr(p, 'nombre_tutor_2', None) or 'no registrado'
        t2_tel    = getattr(p, 'telefono_tutor_2', None) or 'no registrado'
        print(f"    -> Paciente ID {p.id}: {p.nombre} {p.apellido}")
        print(f"       Tutor 1: {p.nombre_tutor} ({p.telefono_tutor})")
        print(f"       Tutor 2: {t2_nombre} ({t2_tel})")

    # Buscar como tutor_2
    m2 = list(Paciente.objects.filter(telefono_tutor_2=tel_norm, estado='activo'))
    print(f"  Coincidencias como telefono_tutor_2 : {len(m2)}")
    for p in m2:
        t2_nombre = getattr(p, 'nombre_tutor_2', None) or 'no registrado'
        t2_tel    = getattr(p, 'telefono_tutor_2', None) or 'no registrado'
        print(f"    -> Paciente ID {p.id}: {p.nombre} {p.apellido}")
        print(f"       Tutor 1: {p.nombre_tutor} ({p.telefono_tutor})")
        print(f"       Tutor 2: {t2_nombre} ({t2_tel})")

    # Diagnóstico final
    print()
    if len(m1) > 1:
        print("  ALERTA: mismo numero en multiples pacientes como tutor_1 - bloqueado por seguridad")
    elif len(m2) > 1:
        print("  ALERTA: mismo numero en multiples pacientes como tutor_2 - bloqueado por seguridad")
    elif len(m1) == 1:
        print(f"  CORRECTO: es tutor_1 de {m1[0].nombre} {m1[0].apellido} -> va a Agente Paciente")
    elif len(m2) == 1:
        t2 = getattr(m2[0], 'nombre_tutor_2', None) or 'sin nombre'
        print(f"  CORRECTO: es tutor_2 ({t2}) de {m2[0].nombre} {m2[0].apellido} -> va a Agente Paciente")
    else:
        print("  No registrado -> va a Agente Publico (comportamiento correcto)")


for numero in NUMEROS_A_PROBAR:
    diagnosticar(numero)

print(f"\n{'='*60}")
print("  Diagnostico completo.")
print(f"{'='*60}\n")