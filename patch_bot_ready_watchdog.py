#!/usr/bin/env python3
"""
patch_bot_ready_watchdog.py

Corrige un segundo problema, distinto del crash-loop ya arreglado por
patch_bot_crash_fix.py: el cliente puede quedarse colgado entre los
eventos 'authenticated' y 'ready' de whatsapp-web.js, SIN lanzar ningun
error. Como no hay excepcion, no dispara ningun mecanismo de reintento
existente (ni el try/catch de arranque, ni 'disconnected', ni
'auth_failure') — el bot se queda "vivo" pero nunca queda operativo,
indefinidamente, hasta que alguien lo reinicia a mano.

Cambio que aplica:
  - Agrega un watchdog de 90s: si 'authenticated' dispara pero 'ready'
    no llega a tiempo, se fuerza client.destroy() + reiniciarCliente().
  - El timer se cancela limpio en 'ready', 'disconnected' y
    'auth_failure' para no disparar de mas.

Requiere haber aplicado antes patch_bot_crash_fix.py (usa el mismo
estilo de reintento que reiniciarCliente() ya trae).

Uso en el servidor:
    python3 patch_bot_ready_watchdog.py
"""
import sys
import shutil

ARCHIVOS = [
    '/var/www/whatsapp-bot/index.js',
    '/var/www/whatsapp-bot-camacho/index.js',
]

OLD_LET = "let reiniciando = false;"
NEW_LET = "let reiniciando = false;\nlet authTimeoutHandle = null; // watchdog: fuerza reconexion si 'authenticated' nunca llega a 'ready'"

OLD_AUTHENTICATED = """client.on('authenticated', () => {
    console.log('ok Sesion autenticada correctamente');
});"""
NEW_AUTHENTICATED = """client.on('authenticated', () => {
    console.log('ok Sesion autenticada correctamente');
    if (authTimeoutHandle) clearTimeout(authTimeoutHandle);
    authTimeoutHandle = setTimeout(async () => {
        console.error('error Timeout: autenticado pero "ready" nunca llego tras 90s — forzando reconexion');
        authTimeoutHandle = null;
        clienteListo = false;
        botStatus = 'desconectado';
        try { await client.destroy(); } catch(e) { console.error('error destroy() en watchdog: ' + e.message); }
        reiniciarCliente();
    }, 90000);
});"""

OLD_READY = """client.on('ready', () => {
    console.log('ok WhatsApp Bot JAPON conectado y listo!');
    botStatus = 'conectado';"""
NEW_READY = """client.on('ready', () => {
    if (authTimeoutHandle) { clearTimeout(authTimeoutHandle); authTimeoutHandle = null; }
    console.log('ok WhatsApp Bot JAPON conectado y listo!');
    botStatus = 'conectado';"""

OLD_AUTHFAIL = """client.on('auth_failure', (msg) => {
    console.error('error Fallo de autenticacion: ' + msg);
    clienteListo = false;
    botStatus = 'error_auth';
});"""
NEW_AUTHFAIL = """client.on('auth_failure', (msg) => {
    if (authTimeoutHandle) { clearTimeout(authTimeoutHandle); authTimeoutHandle = null; }
    console.error('error Fallo de autenticacion: ' + msg);
    clienteListo = false;
    botStatus = 'error_auth';
});"""

OLD_DISCONNECTED = """client.on('disconnected', (reason) => {
    console.log('warn Bot desconectado: ' + reason);
    botStatus = 'desconectado';"""
NEW_DISCONNECTED = """client.on('disconnected', (reason) => {
    if (authTimeoutHandle) { clearTimeout(authTimeoutHandle); authTimeoutHandle = null; }
    console.log('warn Bot desconectado: ' + reason);
    botStatus = 'desconectado';"""


def patch(path):
    with open(path, 'r', encoding='utf-8') as f:
        contenido = f.read()

    cambios = 0
    reemplazos = [
        ('declaracion authTimeoutHandle', OLD_LET, NEW_LET),
        ("watchdog en 'authenticated'", OLD_AUTHENTICATED, NEW_AUTHENTICATED),
        ("limpiar watchdog en 'ready'", OLD_READY, NEW_READY),
        ("limpiar watchdog en 'auth_failure'", OLD_AUTHFAIL, NEW_AUTHFAIL),
        ("limpiar watchdog en 'disconnected'", OLD_DISCONNECTED, NEW_DISCONNECTED),
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

    shutil.copy(path, path + '.bak2')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(contenido)
    print(f"  OK: {path} parchado ({cambios}/{len(reemplazos)} cambios). Backup en {path}.bak2")
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
