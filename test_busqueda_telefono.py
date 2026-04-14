"""
Script de diagnóstico para verificar que la búsqueda de teléfonos
funciona correctamente con el código nuevo.

CÓMO EJECUTAR en el servidor:
    cd /var/www/centro_terapias
    python manage.py shell < test_busqueda_telefono.py

O de forma interactiva:
    python manage.py shell
    exec(open('test_busqueda_telefono.py').read())
"""

import os
import sys

# ─── Números a probar ──────────────────────────────────────────────────────
# Edita esta lista con los números reales que quieras verificar.
# Pon el número exacto como llega desde WhatsApp (con prefijo 591).
NUMEROS_A_PROBAR = [
    '59172416623',   # número visto en pantalla — verificar si está registrado o no
]

# ──────────────────────────────────────────────────────────────────────────

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
        print("  ❌ Formato inválido — va a Agente Público")
        return

    # Buscar como tutor_1
    m1 = list(Paciente.objects.filter(telefono_tutor=tel_norm, estado='activo'))
    print(f"\n  Coincidencias como telefono_tutor   : {len(m1)}")
    for p in m1:
        print(f"    → Paciente ID {p.id}: {p.nombre} {p.apellido} | Tutor: {p.nombre_tutor}")

    # Buscar como tutor_2
    m2 = list(Paciente.objects.filter(telefono_tutor_2=tel_norm, estado='activo'))
    print(f"  Coincidencias como telefono_tutor_2 : {len(m2)}")
    for p in m2:
        print(f"    → Paciente ID {p.id}: {p.nombre} {p.apellido} | Tutor: {p.nombre_tutor}")

    # Diagnóstico final
    print()
    if len(m1) > 1:
        print("  🚨 ALERTA: mismo número en múltiples pacientes como tutor_1 — va a Agente Público (bloqueado por seguridad)")
    elif len(m2) > 1:
        print("  🚨 ALERTA: mismo número en múltiples pacientes como tutor_2 — va a Agente Público (bloqueado por seguridad)")
    elif len(m1) == 1:
        print(f"  ✅ CORRECTO: es tutor_1 de {m1[0].nombre} {m1[0].apellido} → va a Agente Paciente")
    elif len(m2) == 1:
        print(f"  ✅ CORRECTO: es tutor_2 de {m2[0].nombre} {m2[0].apellido} → va a Agente Paciente")
    else:
        print("  🔵 No registrado → va a Agente Público (comportamiento correcto)")


# ─── Ejecutar ──────────────────────────────────────────────────────────────

if not NUMEROS_A_PROBAR:
    print("\n⚠️  Edita la lista NUMEROS_A_PROBAR en el script y agrega los números a verificar.")
    print("   Ejemplo: NUMEROS_A_PROBAR = ['59172416623', '59176543210']\n")
else:
    for numero in NUMEROS_A_PROBAR:
        diagnosticar(numero)
    print(f"\n{'='*60}")
    print("  Diagnóstico completo.")
    print(f"{'='*60}\n")
