import psycopg2
import sys

# Connection string de Supabase (puerto 5432 - conexión directa)
DATABASE_URL = "postgresql://postgres:Ricardomisael.0@db.gypyooflbjjxrqgjuehz.supabase.co:5432/postgres"

try:
    print("🔄 Conectando a Supabase...")
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    conn.autocommit = False
    cur = conn.cursor()
    
    print("📖 Leyendo archivo SQL...")
    with open('backup_clean.sql', 'r', encoding='utf-8') as f:
        sql = f.read()
    
    print("⚙️  Ejecutando importación (esto puede tomar 2-3 minutos)...")
    cur.execute(sql)
    conn.commit()
    
    print("\n✅ ¡Importación exitosa!\n")
    
    # Verificar datos importados
    print("📊 Verificando datos importados:")
    
    cur.execute("SELECT COUNT(*) FROM auth_user;")
    users = cur.fetchone()[0]
    print(f"   ✓ Usuarios: {users}")
    
    cur.execute("SELECT COUNT(*) FROM pacientes_paciente;")
    pacientes = cur.fetchone()[0]
    print(f"   ✓ Pacientes: {pacientes}")
    
    cur.execute("SELECT COUNT(*) FROM agenda_sesion;")
    sesiones = cur.fetchone()[0]
    print(f"   ✓ Sesiones: {sesiones}")
    
    cur.execute("SELECT COUNT(*) FROM profesionales_profesional;")
    profesionales = cur.fetchone()[0]
    print(f"   ✓ Profesionales: {profesionales}")
    
    print("\n🎉 ¡Todo listo! Ahora actualiza DATABASE_URL en Render.")
    
    cur.close()
    conn.close()
    
except psycopg2.Error as e:
    print(f"\n❌ Error de PostgreSQL: {e}")
    if conn:
        conn.rollback()
    sys.exit(1)
    
except FileNotFoundError:
    print("\n❌ Error: No se encontró el archivo 'backupmisael140126.sql'")
    print("   Asegúrate de que esté en la misma carpeta.")
    sys.exit(1)
    
except Exception as e:
    print(f"\n❌ Error inesperado: {e}")
    if conn:
        conn.rollback()
    sys.exit(1)