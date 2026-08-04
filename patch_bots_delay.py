#!/usr/bin/env python3
"""
patch_bots_delay.py
Agrega el delay_type 'horario_mensual' (5-60s aleatorio) a los bots de
WhatsApp, para el envío del horario mensual en PDF. No toca los delays
'corto' (5-10s) ni 'largo' (4-7min) que ya existen y siguen igual.

Uso en el servidor:
    python3 patch_bots_delay.py

Modifica en sitio (con backup .bak2) los archivos:
    /var/www/whatsapp-bot/index.js
    /var/www/whatsapp-bot-camacho/index.js
"""
import sys
import shutil

ARCHIVOS = [
    '/var/www/whatsapp-bot/index.js',
    '/var/www/whatsapp-bot-camacho/index.js',
]

OLD = """            let delay;
            if (delay_type === 'corto') {
                delay = (Math.floor(Math.random() * 6) + 5) * 1000;
            } else {
                delay = (Math.floor(Math.random() * 4) + 4) * 60 * 1000;
            }"""

NEW = """            let delay;
            if (delay_type === 'corto') {
                delay = (Math.floor(Math.random() * 6) + 5) * 1000;
            } else if (delay_type === 'horario_mensual') {
                delay = (Math.floor(Math.random() * 56) + 5) * 1000;
            } else {
                delay = (Math.floor(Math.random() * 4) + 4) * 60 * 1000;
            }"""


def patch(path):
    with open(path, 'r', encoding='utf-8') as f:
        contenido = f.read()

    if NEW in contenido:
        print(f"  Nada que aplicar en {path} (ya estaba parchado).")
        return False

    if OLD not in contenido:
        print(f"  [AVISO] Bloque de delay no encontrado tal cual en {path} — revisar manualmente.")
        return False

    contenido = contenido.replace(OLD, NEW)

    shutil.copy(path, path + '.bak2')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(contenido)
    print(f"  OK: {path} parchado. Backup en {path}.bak2")
    return True


if __name__ == '__main__':
    algun_cambio = False
    for path in ARCHIVOS:
        print(f"Procesando {path} ...")
        try:
            if patch(path):
                algun_cambio = True
        except FileNotFoundError:
            print(f"  [ERROR] No existe {path}")
    if algun_cambio:
        print("\nListo. Valida sintaxis antes de reiniciar:")
        print("  node -c /var/www/whatsapp-bot/index.js && echo japon OK")
        print("  node -c /var/www/whatsapp-bot-camacho/index.js && echo camacho OK")
        print("Luego: pm2 restart all")
    sys.exit(0)
