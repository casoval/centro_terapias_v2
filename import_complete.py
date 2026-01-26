import psycopg2
import sys

DATABASE_URL = "postgresql://postgres:Ricardomisael.0@db.gypyooflbjjxrqgjuehz.supabase.co:5432/postgres"

print("🔄 Paso 1: Limpiando backup...")

with open('backupmisael140126.sql', 'r', encoding='utf-8') as f:
    content = f.read()

# Reemplazar usuario
content = content.replace('centro_misael_user', 'postgres')

# Remover comandos problemáticos
lines = content.split('\n')
cleaned_lines = []
skip_next = False

for line in lines:
    # Saltar ALTER OWNER
    if 'OWNER TO centro_misael_user' in line or 'OWNER TO postgres' in line:
        if line.strip().startswith('ALTER'):
            continue
    
    # Saltar comentarios de restricción
    if line.strip().startswith('-- *not* creating schema'):
        continue
        
    cleaned_lines.append(line)

cleaned_content = '\n'.join(cleaned_lines)
print("   ✓ Backup limpio")

print("\n🔄 Paso 2: Conectando a Supabase...")
try:
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    conn.autocommit = False
    cur = conn.cursor()
    print("   ✓ Conectado")
    
    print("\n🔄 Paso 3: Importando base de datos...")
    print("   (Esto puede tomar 3-5 minutos...)\n")
    
    # Dividir en statements individuales
    statements = []
    current = []
    in_copy = False
    
    for line in cleaned_lines:
        if line.strip().startswith('COPY '):
            in_copy = True
            current = [line]
        elif in_copy and line.strip() == '\\.':
            current.append(line)
            statements.append('\n'.join(current))
            current = []
            in_copy = False
        elif in_copy:
            current.append(line)
        elif line.strip().endswith(';') and not in_copy:
            current.append(line)
            statements.append('\n'.join(current))
            current = []
        elif not in_copy:
            current.append(line)
    
    # Ejecutar statements
    total = len(statements)
    errors = 0
    
    for i, stmt in enumerate(statements, 1):
        stmt = stmt.strip()
        if not stmt or stmt.startswith('--'):
            continue
            
        if i % 50 == 0:
            print(f"   Procesando: {i}/{total}")
            
        try:
            cur.execute(stmt)
        except psycopg2.Error as e:
            error_msg = str(e)
            # Ignorar errores de "already exists"
            if 'already exists' in error_msg or 'duplicate key' in error_msg:
                continue
            else:
                errors += 1
                if errors < 5:  # Solo mostrar primeros 5 errores
                    print(f"   ⚠️  Warning: {error_msg[:100]}")
    
    conn.commit()
    print("\n   ✓ Datos importados")
    
    print("\n📊 Verificando importación:")
    
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
    
    if users == 17 and pacientes == 49:
        print("\n🎉 ¡Importación exitosa!")
        print("\n📝 Siguiente paso:")
        print("   Actualiza DATABASE_URL en Render con:")
        print("   postgresql://postgres.gypyooflbjjxrqgjuehz:Ricardomisael.0@aws-1-sa-east-1.pooler.supabase.com:6543/postgres")
    else:
        print("\n⚠️  Los datos se importaron pero las cantidades no coinciden.")
        print("   Esto puede ser normal si había datos previos en Supabase.")
    
    cur.close()
    conn.close()
    
except psycopg2.Error as e:
    print(f"\n❌ Error de PostgreSQL:")
    print(f"   {e}")
    if 'conn' in locals():
        conn.rollback()
    sys.exit(1)
    
except Exception as e:
    print(f"\n❌ Error inesperado:")
    print(f"   {e}")
    if 'conn' in locals():
        conn.rollback()
    sys.exit(1)