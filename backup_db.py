"""
backup_db.py
------------
Genera un dump nativo de PostgreSQL (.dump, formato custom comprimido),
y lo envía por correo electrónico vía Gmail SMTP.

Uso manual:
    python backup_db.py

Programado con cron:
    0 3 * * * /ruta/venv/bin/python /ruta/backup_db.py >> /ruta/logs/backup.log 2>&1
"""

import os
import smtplib
import logging
import subprocess
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from pathlib import Path
from dotenv import load_dotenv

# --------------------------------------------------
# CONFIGURACIÓN
# --------------------------------------------------

load_dotenv()

# Base de datos
DB_NAME     = os.environ.get('DB_NAME')
DB_USER     = os.environ.get('DB_USER')
DB_PASSWORD = os.environ.get('DB_PASSWORD')
DB_HOST     = os.environ.get('DB_HOST', 'localhost')
DB_PORT     = os.environ.get('DB_PORT', '5432')

# Gmail
GMAIL_USER     = os.environ.get('BACKUP_GMAIL_USER')
GMAIL_PASSWORD = os.environ.get('BACKUP_GMAIL_APP_PASS')

# Múltiples destinatarios separados por coma
_destinos_raw  = os.environ.get('BACKUP_EMAIL_DESTINO', GMAIL_USER)
EMAILS_DESTINO = [e.strip() for e in _destinos_raw.split(',') if e.strip()]

# Directorio temporal para guardar el dump
BACKUP_DIR = Path(os.environ.get('BACKUP_DIR', '/tmp/db_backups'))
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

# Cuántos archivos locales conservar (0 = eliminar tras enviar)
KEEP_LOCAL = int(os.environ.get('BACKUP_KEEP_LOCAL', '3'))

# Nivel de compresión del dump (0-9, donde 9 es máxima compresión)
# pg_dump -F c usa zlib internamente; valor recomendado: 6
COMPRESS_LEVEL = int(os.environ.get('BACKUP_COMPRESS_LEVEL', '6'))

# --------------------------------------------------
# LOGGING
# --------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger(__name__)

# --------------------------------------------------
# FUNCIONES
# --------------------------------------------------

def generar_nombre_archivo() -> Path:
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    return BACKUP_DIR / f"backup_{DB_NAME}_{ts}.dump"


def hacer_dump(destino: Path) -> None:
    """
    Ejecuta pg_dump en formato custom (-F c).
    Este formato es binario, comprime internamente con zlib
    y permite restauración selectiva con pg_restore.
    """
    log.info(f"Iniciando pg_dump (formato .dump) → {destino}")

    env = os.environ.copy()
    env['PGPASSWORD'] = DB_PASSWORD

    cmd = [
        'pg_dump',
        '-h', DB_HOST,
        '-p', DB_PORT,
        '-U', DB_USER,
        '-d', DB_NAME,
        '--no-password',
        '-F', 'c',                        # Formato custom (binario comprimido)
        f'-Z', str(COMPRESS_LEVEL),       # Nivel de compresión zlib
        '-f', str(destino),               # Archivo de salida directo
    ]

    resultado = subprocess.run(
        cmd,
        env=env,
        stderr=subprocess.PIPE,
    )

    if resultado.returncode != 0:
        raise RuntimeError(
            f"pg_dump falló (código {resultado.returncode}):\n"
            f"{resultado.stderr.decode()}"
        )

    size_mb = destino.stat().st_size / (1024 * 1024)
    log.info(f"Dump completado. Tamaño: {size_mb:.2f} MB")


def enviar_correo(archivo: Path) -> None:
    """Envía el archivo .dump como adjunto a todos los destinatarios configurados."""
    log.info(f"Enviando correo a: {', '.join(EMAILS_DESTINO)} …")

    fecha_str  = datetime.now().strftime('%d/%m/%Y %H:%M')
    size_mb    = archivo.stat().st_size / (1024 * 1024)
    nombre_adj = archivo.name

    # Advertencia si el adjunto supera el límite de Gmail (25 MB)
    if size_mb > 24:
        log.warning(
            f"⚠️  El archivo pesa {size_mb:.2f} MB. "
            "Gmail rechaza adjuntos mayores a 25 MB. "
            "Considera subir BACKUP_COMPRESS_LEVEL=9 o migrar a Google Drive."
        )

    msg = MIMEMultipart()
    msg['From']    = GMAIL_USER
    msg['To']      = ', '.join(EMAILS_DESTINO)
    msg['Subject'] = f"[Backup DB] {DB_NAME} — {fecha_str}"

    cuerpo = f"""
    <html><body>
    <h3>🗄️ Backup automático de base de datos</h3>
    <table cellpadding="6" style="border-collapse:collapse; font-family:Arial, sans-serif;">
      <tr><td><b>Base de datos</b></td><td>{DB_NAME}</td></tr>
      <tr><td><b>Servidor</b></td><td>{DB_HOST}:{DB_PORT}</td></tr>
      <tr><td><b>Fecha</b></td><td>{fecha_str} (hora del servidor)</td></tr>
      <tr><td><b>Formato</b></td><td>PostgreSQL Custom (.dump) — compresión zlib nivel {COMPRESS_LEVEL}</td></tr>
      <tr><td><b>Tamaño</b></td><td>{size_mb:.2f} MB</td></tr>
    </table>

    <h4>Cómo restaurar:</h4>
    <pre style="background:#f4f4f4; padding:10px; border-radius:4px;">
# Restaurar base de datos completa:
pg_restore -h HOST -U {DB_USER} -d {DB_NAME} --no-password {nombre_adj}

# Restaurar solo una tabla específica:
pg_restore -h HOST -U {DB_USER} -d {DB_NAME} -t nombre_tabla {nombre_adj}

# Ver contenido del dump sin restaurar:
pg_restore --list {nombre_adj}
    </pre>
    </body></html>
    """
    msg.attach(MIMEText(cuerpo, 'html'))

    with open(archivo, 'rb') as f:
        parte = MIMEBase('application', 'octet-stream')
        parte.set_payload(f.read())
    encoders.encode_base64(parte)
    parte.add_header('Content-Disposition', f'attachment; filename="{nombre_adj}"')
    msg.attach(parte)

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(GMAIL_USER, GMAIL_PASSWORD)
        server.sendmail(GMAIL_USER, EMAILS_DESTINO, msg.as_string())

    log.info(f"✅ Correo enviado a {len(EMAILS_DESTINO)} destinatario(s).")


def limpiar_backups_viejos() -> None:
    """Elimina backups locales más antiguos si se supera KEEP_LOCAL."""
    archivos = sorted(
        BACKUP_DIR.glob('backup_*.dump'),
        key=lambda p: p.stat().st_mtime
    )
    while len(archivos) > KEEP_LOCAL:
        viejo = archivos.pop(0)
        viejo.unlink()
        log.info(f"Backup local antiguo eliminado: {viejo.name}")


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def registrar_en_django(exitoso, tamanio='', duracion=None, error='', tipo='automatico'):
    """
    Guarda el resultado en la base de datos Django (modelo RegistroBackup).
    Solo funciona si el script se ejecuta desde la raíz del proyecto Django.
    """
    try:
        import django
        from pathlib import Path as _Path
        import sys as _sys

        # Agregar el proyecto al path
        project_dir = _Path(__file__).resolve().parent
        if str(project_dir) not in _sys.path:
            _sys.path.insert(0, str(project_dir))

        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
        django.setup()

        from recordatorios.models import RegistroBackup
        RegistroBackup.objects.create(
            tipo=tipo,
            exitoso=exitoso,
            tamanio_mb=tamanio,
            duracion_segundos=duracion,
            destinatarios=', '.join(EMAILS_DESTINO),
            mensaje_error=error,
        )
        log.info("📝 Resultado registrado en la base de datos.")
    except Exception as e:
        # No interrumpir el backup si falla el registro
        log.warning(f"No se pudo registrar en Django: {e}")


def main():
    log.info("=" * 55)
    log.info("INICIO DEL PROCESO DE BACKUP POSTGRESQL")
    log.info("=" * 55)

    faltantes = [v for v in [
        'DB_NAME', 'DB_USER', 'DB_PASSWORD',
        'BACKUP_GMAIL_USER', 'BACKUP_GMAIL_APP_PASS'
    ] if not os.environ.get(v)]

    if faltantes:
        raise EnvironmentError(
            f"Faltan variables de entorno: {', '.join(faltantes)}"
        )

    archivo = generar_nombre_archivo()
    inicio  = __import__('time').time()

    try:
        hacer_dump(archivo)
        enviar_correo(archivo)
        limpiar_backups_viejos()

        duracion  = round(__import__('time').time() - inicio, 1)
        tamanio   = f"{archivo.stat().st_size / (1024*1024):.2f} MB" if archivo.exists() else ''
        registrar_en_django(exitoso=True, tamanio=tamanio, duracion=duracion)

        log.info("✅ Proceso completado exitosamente.")
    except Exception as e:
        duracion = round(__import__('time').time() - inicio, 1)
        registrar_en_django(exitoso=False, duracion=duracion, error=str(e))
        log.error(f"❌ Error durante el backup: {e}")
        raise
    finally:
        if KEEP_LOCAL == 0 and archivo.exists():
            archivo.unlink()
            log.info("Archivo temporal eliminado (KEEP_LOCAL=0).")


if __name__ == '__main__':
    main()