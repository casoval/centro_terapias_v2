#!/usr/bin/env python3
"""
enviar_recordatorio.py
Uso:
  python enviar_recordatorio.py <endpoint> <sucursal> [bot_port]

Ejemplos:
  python enviar_recordatorio.py hitos 3
  python enviar_recordatorio.py hitos 4 3001
  python enviar_recordatorio.py orientacion-mensual 3
  python enviar_recordatorio.py orientacion-mensual 4 3001

Replica el flujo de n8n:
  1. GET al endpoint Django
  2. Verifica que haya resultados
  3. Por cada item, POST al bot /send
"""

import sys
import json
import urllib.request
import urllib.error
from datetime import datetime

# ── Configuración ──────────────────────────────────────────────
DJANGO_BASE = 'http://localhost:8000/recordatorios'
BOT_BASE    = 'http://localhost:{port}/send'

# Mapa: endpoint → clave del array en la respuesta JSON
ENDPOINT_MAP = {
    'hitos':              ('hitos',        'hitos'),
    'orientacion-mensual': ('orientaciones', 'orientaciones'),
}

# ── Helpers ────────────────────────────────────────────────────
def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)

def http_get(url):
    req = urllib.request.Request(url, headers={'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

def http_post(url, payload):
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())

# ── Main ───────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 3:
        print("Uso: python enviar_recordatorio.py <endpoint> <sucursal> [bot_port]")
        sys.exit(1)

    endpoint  = sys.argv[1]                        # hitos | orientacion-mensual
    sucursal  = sys.argv[2]                        # 3 | 4
    bot_port  = sys.argv[3] if len(sys.argv) > 3 else ('3001' if sucursal == '4' else '3000')

    if endpoint not in ENDPOINT_MAP:
        log(f"ERROR: endpoint '{endpoint}' no reconocido. Opciones: {list(ENDPOINT_MAP.keys())}")
        sys.exit(1)

    total_key, lista_key = ENDPOINT_MAP[endpoint]

    django_url = f"{DJANGO_BASE}/{endpoint}/?sucursal={sucursal}"
    bot_url    = BOT_BASE.format(port=bot_port)

    log(f"=== Iniciando: {endpoint} | sucursal={sucursal} | bot={bot_url} ===")

    # 1. GET al endpoint Django
    try:
        data = http_get(django_url)
    except Exception as e:
        log(f"ERROR GET {django_url}: {e}")
        sys.exit(1)

    items = data.get(lista_key, [])
    total = len(items)
    log(f"Resultados: {total}")

    # 2. Verificar que haya resultados (mismo If de n8n)
    if total == 0:
        log("Sin resultados. Nada que enviar.")
        sys.exit(0)

    # 3. Por cada item, POST al bot /send (mismo Split Out + HTTP Request de n8n)
    enviados = 0
    errores  = 0

    for item in items:
        telefono = item.get('tutor_telefono') or item.get('telefono')
        mensaje  = item.get('mensaje')
        paciente = item.get('paciente_nombre', '')
        sucursal_nombre = item.get('sucursal', '')

        if not telefono or not mensaje:
            log(f"SKIP: item sin telefono o mensaje — {item}")
            continue

        payload = {
            'telefono':   telefono,
            'mensaje':    mensaje,
            'paciente':   paciente,
            'sucursal':   sucursal_nombre,
            'delay_type': 'largo',
        }

        try:
            resp = http_post(bot_url, payload)
            log(f"OK enviado a {telefono} ({paciente}) — cola: {resp.get('cola', '?')}")
            enviados += 1
        except Exception as e:
            log(f"ERROR enviando a {telefono}: {e}")
            errores += 1

    log(f"=== Fin: {enviados} enviados, {errores} errores ===")

if __name__ == '__main__':
    main()
