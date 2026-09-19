#!/usr/bin/env python3
"""
patch_bot_crash_fix.py

Corrige el crash-loop del/de los bot(s) de WhatsApp causado por dos
"unhandled promise rejections" en index.js:

  1. app.post('/send', ...) crea una Promise para cada mensaje pero nunca
     le agrega .catch(). Cuando processQueue() hace reject(error) sobre esa
     promesa huérfana (p.ej. con el error "No LID for user"), Node mata el
     proceso entero (comportamiento por defecto desde Node 15). PM2 lo
     revive, pero el ciclo se repite.

  2. client.initialize() al final del archivo se llama sin .catch()/try-catch.
     Si falla durante el arranque (p.ej. "Execution context was destroyed"),
     también es una unhandled rejection que tumba el proceso.

Cambios que aplica:
  - Fix 1: agrega .catch(() => {}) a la promesa de /send.
  - Fix 2: envuelve el client.initialize() inicial y lo conecta con
    reiniciarCliente() si falla, igual que ya hace el resto del código.
  - Fix 3 (mejora, no crítico): "No LID for user" se reintenta una vez
    tras 20s en vez de descartarse de inmediato — suele ser una carrera
    de sincronización justo tras reconectar, no un error permanente.

Uso en el servidor:
    python3 patch_bot_crash_fix.py

Aplica (con backup .bak) a los archivos listados en ARCHIVOS. Si algún
archivo no tiene el texto esperado tal cual (p.ej. porque Camacho difiere
del código de Japón), lo avisa y no toca nada en ese archivo.
"""
import sys
import shutil

ARCHIVOS = [
    '/var/www/whatsapp-bot/index.js',
    '/var/www/whatsapp-bot-camacho/index.js',
]

# ── Fix 1: promesa huérfana en /send ────────────────────────────────────────
OLD_SEND_PROMISE = """    new Promise((resolve, reject) => {
        messageQueue.push({ numero, mensaje, paciente, sucursal, delay_type: delay_type || 'largo', tipo, documento, documento_nombre, resolve, reject });
    });
    processQueue();"""

NEW_SEND_PROMISE = """    new Promise((resolve, reject) => {
        messageQueue.push({ numero, mensaje, paciente, sucursal, delay_type: delay_type || 'largo', tipo, documento, documento_nombre, resolve, reject });
    }).catch(() => {}); // evita unhandled rejection — el detalle del error ya queda en el historial (ver processQueue)
    processQueue();"""

# ── Fix 2: client.initialize() inicial sin manejo de error ─────────────────
OLD_INIT = """app.listen(3000, () => console.log('Bot Japon corriendo en puerto 3000'));
client.initialize();"""

NEW_INIT = """app.listen(3000, () => console.log('Bot Japon corriendo en puerto 3000'));
client.initialize().catch((e) => {
    console.error('error Fallo en initialize() inicial: ' + e.message);
    reiniciarCliente();
});"""

# ── Fix 3 (mejora): reintentar "No LID for user" en vez de tumbar la promesa ──
OLD_DESTRUCT = """        const { numero, mensaje, paciente, sucursal, delay_type, tipo, documento, documento_nombre, resolve, reject } = messageQueue.shift();"""
NEW_DESTRUCT = """        const _item = messageQueue.shift();
        const { numero, mensaje, paciente, sucursal, delay_type, tipo, documento, documento_nombre, resolve, reject, _lidRetry } = _item;"""

OLD_REJECT_TAIL = """                reiniciarCliente();
                return;
            }
            reject(error);"""

NEW_REJECT_TAIL = """                reiniciarCliente();
                return;
            }
            if (error.message && error.message.includes('No LID for user') && !_lidRetry) {
                console.log('reintento "No LID for user" (probable carrera de sincronizacion) — reintentando en 20s...');
                messageQueue.unshift({ ..._item, _lidRetry: true });
                await sleep(20000);
                continue;
            }
            reject(error);"""


def patch(path):
    with open(path, 'r', encoding='utf-8') as f:
        contenido = f.read()

    cambios = 0
    reemplazos = [
        ('Fix 1 (promesa huerfana en /send)', OLD_SEND_PROMISE, NEW_SEND_PROMISE),
        ('Fix 2 (initialize() inicial sin catch)', OLD_INIT, NEW_INIT),
        ('Fix 3a (destructuring con _lidRetry)', OLD_DESTRUCT, NEW_DESTRUCT),
        ('Fix 3b (reintento No LID for user)', OLD_REJECT_TAIL, NEW_REJECT_TAIL),
    ]

    for nombre, old, new in reemplazos:
        if old in contenido:
            contenido = contenido.replace(old, new)
            cambios += 1
        else:
            print(f"  [AVISO] {nombre} no encontrado tal cual en {path} — revisar manualmente (¿ya aplicado?).")

    if cambios == 0:
        print(f"  Nada que aplicar en {path}.")
        return False

    shutil.copy(path, path + '.bak')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(contenido)
    print(f"  OK: {path} parchado ({cambios}/{len(reemplazos)} cambios). Backup en {path}.bak")
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
        print("\nListo. Reinicia los bots para aplicar los cambios:")
        print("  sudo pm2 restart whatsapp-bot")
        print("  sudo pm2 restart whatsapp-bot-camacho   # si tambien se parcheo")
    sys.exit(0)
