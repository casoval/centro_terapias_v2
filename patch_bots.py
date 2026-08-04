#!/usr/bin/env python3
"""
patch_bots.py
Aplica cambios a los bots de WhatsApp para soportar el envío de
documentos (PDF) adjuntos a través de /send (campo opcional `documento`
en base64 + `documento_nombre`). El delay entre envíos reutiliza el
'largo' que ya existe (4-7 min aleatorio) — no se agrega ningún delay nuevo.

Uso en el servidor:
    python3 patch_bots.py

Modifica en sitio (con backup .bak) los archivos:
    /var/www/whatsapp-bot/index.js
    /var/www/whatsapp-bot-camacho/index.js
"""
import re
import sys
import shutil

ARCHIVOS = [
    '/var/www/whatsapp-bot/index.js',
    '/var/www/whatsapp-bot-camacho/index.js',
]

# ── Cambio 1: destructuring de la cola + envío con soporte de documento ────
OLD_1 = """        const { numero, mensaje, paciente, sucursal, delay_type, tipo, resolve, reject } = messageQueue.shift();
        const tipoFinal = _resolverTipo(tipo, sucursal);
        try {
            await client.sendMessage(numero, mensaje);
            const telefono = numero.replace('591', '').replace('@c.us', '');
            console.log('ok Mensaje enviado a ' + telefono);
            guardarHistorial({
                fecha:    new Date().toISOString(),
                telefono,
                paciente: paciente || '',
                sucursal: sucursal || \""""

def build_old1(nombre_sucursal_default):
    return (
        "        const { numero, mensaje, paciente, sucursal, delay_type, tipo, documento, documento_nombre, resolve, reject } = messageQueue.shift();\n"
        "        const tipoFinal = _resolverTipo(tipo, sucursal);\n"
        "        try {\n"
        "            if (documento) {\n"
        "                const media = new MessageMedia('application/pdf', documento, documento_nombre || 'documento.pdf');\n"
        "                await client.sendMessage(numero, media, { caption: mensaje });\n"
        "            } else {\n"
        "                await client.sendMessage(numero, mensaje);\n"
        "            }\n"
        "            const telefono = numero.replace('591', '').replace('@c.us', '');\n"
        "            console.log('ok Mensaje enviado a ' + telefono + (documento ? ' [con PDF]' : ''));\n"
        "            guardarHistorial({\n"
        "                fecha:    new Date().toISOString(),\n"
        "                telefono,\n"
        "                paciente: paciente || '',\n"
        f"                sucursal: sucursal || \"{nombre_sucursal_default}\""
    )

# ── Cambio 2: reintento en error de protocolo debe conservar `documento` ───
OLD_RETRY = "messageQueue.unshift({ numero, mensaje, paciente, sucursal, delay_type, tipo, resolve, reject });"
NEW_RETRY = "messageQueue.unshift({ numero, mensaje, paciente, sucursal, delay_type, tipo, documento, documento_nombre, resolve, reject });"

# ── Cambio 3: rango de delay -> ya no se agrega 'medio', se usa 'largo' existente ──
OLD_DELAY = None
NEW_DELAY = None

# ── Cambio 4: ruta /send debe leer y encolar documento/documento_nombre ────
OLD_SEND = """app.post('/send', async (req, res) => {
    const { telefono, mensaje, paciente, sucursal, delay_type, tipo } = req.body;
    if (!telefono || !mensaje) return res.status(400).json({ error: 'Faltan datos' });
    if (pausado) return res.json({ success: false, motivo: 'pausado', telefono });
    const numero = '591' + telefono + '@c.us';
    new Promise((resolve, reject) => {
        messageQueue.push({ numero, mensaje, paciente, sucursal, delay_type: delay_type || 'largo', tipo, resolve, reject });
    });
    processQueue();
    res.json({ success: true, telefono, cola: messageQueue.length, bot_listo: clienteListo });
});"""
NEW_SEND = """app.post('/send', async (req, res) => {
    const { telefono, mensaje, paciente, sucursal, delay_type, tipo, documento, documento_nombre } = req.body;
    if (!telefono || !mensaje) return res.status(400).json({ error: 'Faltan datos' });
    if (pausado) return res.json({ success: false, motivo: 'pausado', telefono });
    const numero = '591' + telefono + '@c.us';
    new Promise((resolve, reject) => {
        messageQueue.push({ numero, mensaje, paciente, sucursal, delay_type: delay_type || 'largo', tipo, documento, documento_nombre, resolve, reject });
    });
    processQueue();
    res.json({ success: true, telefono, cola: messageQueue.length, bot_listo: clienteListo });
});"""


def patch(path):
    with open(path, 'r', encoding='utf-8') as f:
        contenido = f.read()

    default_suc = 'Suc. Camacho' if 'camacho' in path.lower() else 'Suc. Japon'
    old1 = build_old1_source(default_suc)

    cambios = 0
    if old1 in contenido:
        contenido = contenido.replace(old1, new1_source(default_suc))
        cambios += 1
    else:
        print(f"  [AVISO] Cambio 1 (envío con documento) no encontrado tal cual en {path} — revisar manualmente.")

    if OLD_RETRY in contenido:
        n = contenido.count(OLD_RETRY)
        contenido = contenido.replace(OLD_RETRY, NEW_RETRY)
        cambios += n
    else:
        print(f"  [AVISO] Cambio 2 (reintento con documento) no encontrado en {path}.")

    if OLD_DELAY and OLD_DELAY in contenido:
        contenido = contenido.replace(OLD_DELAY, NEW_DELAY)
        cambios += 1
    elif OLD_DELAY:
        print(f"  [AVISO] Cambio 3 (delay) no encontrado en {path} (¿ya aplicado?).")

    if OLD_SEND in contenido:
        contenido = contenido.replace(OLD_SEND, NEW_SEND)
        cambios += 1
    else:
        print(f"  [AVISO] Cambio 4 (ruta /send) no encontrado en {path} (¿ya aplicado?).")

    if cambios == 0:
        print(f"  Nada que aplicar en {path} (¿ya estaba parchado?).")
        return False

    shutil.copy(path, path + '.bak')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(contenido)
    print(f"  OK: {path} parchado ({cambios} cambios). Backup en {path}.bak")
    return True


def build_old1_source(default_suc):
    return (
        "        const { numero, mensaje, paciente, sucursal, delay_type, tipo, resolve, reject } = messageQueue.shift();\n"
        "        const tipoFinal = _resolverTipo(tipo, sucursal);\n"
        "        try {\n"
        "            await client.sendMessage(numero, mensaje);\n"
        "            const telefono = numero.replace('591', '').replace('@c.us', '');\n"
        "            console.log('ok Mensaje enviado a ' + telefono);\n"
        "            guardarHistorial({\n"
        "                fecha:    new Date().toISOString(),\n"
        "                telefono,\n"
        "                paciente: paciente || '',\n"
        f"                sucursal: sucursal || '{default_suc}',"
    )


def new1_source(default_suc):
    return (
        "        const { numero, mensaje, paciente, sucursal, delay_type, tipo, documento, documento_nombre, resolve, reject } = messageQueue.shift();\n"
        "        const tipoFinal = _resolverTipo(tipo, sucursal);\n"
        "        try {\n"
        "            if (documento) {\n"
        "                const media = new MessageMedia('application/pdf', documento, documento_nombre || 'documento.pdf');\n"
        "                await client.sendMessage(numero, media, { caption: mensaje });\n"
        "            } else {\n"
        "                await client.sendMessage(numero, mensaje);\n"
        "            }\n"
        "            const telefono = numero.replace('591', '').replace('@c.us', '');\n"
        "            console.log('ok Mensaje enviado a ' + telefono + (documento ? ' [con PDF]' : ''));\n"
        "            guardarHistorial({\n"
        "                fecha:    new Date().toISOString(),\n"
        "                telefono,\n"
        "                paciente: paciente || '',\n"
        f"                sucursal: sucursal || '{default_suc}',"
    )


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
        print("\nListo. Reinicia los bots para aplicar los cambios, por ejemplo:")
        print("  pm2 restart all")
        print("  (o el comando/servicio que uses para levantar whatsapp-bot y whatsapp-bot-camacho)")
    sys.exit(0)
