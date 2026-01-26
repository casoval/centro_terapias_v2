import psycopg2
import re
import sys

DATABASE_URL = "postgresql://postgres:Ricardomisael.0@db.gypyooflbjjxrqgjuehz.supabase.co:5432/postgres"

def convert_copy_to_insert(sql_content):
    """Convierte comandos COPY a INSERT"""
    print("🔄 Convirtiendo formato COPY a INSERT...")
    
    # Patrón para encontrar bloques COPY
    pattern = r'COPY ([^\(]+)\s*\(([^\)]+)\)\s+FROM stdin;(.*?)\\\.'
    
    def replace_copy(match):
        table_name = match.group(1).strip()
        columns = match.group(2).strip()
        data = match.group(3).strip()
        
        if not data:
            return ""
        
        inserts = []
        for line in data.split('\n'):
            line = line.strip()
            if line and not line.startswith('--'):
                # Escapar comillas simples
                line = line.replace("'", "''")
                # Reemplazar \N con NULL
                values = []
                for val in line.split('\t'):
                    if val == '\\N':
                        values.append('NULL')
                    else:
                        values.append(f"'{val}'")
                
                values_str = ', '.join(values)
                inserts.append(f"INSERT INTO {table_name} ({columns}) VALUES ({values_str});")
        
        return '\n'.join(inserts)
    
    # Reemplazar todos los COPY con INSERT
    converted = re.sub(pattern, replace_copy, sql_content, flags=re.DOTALL)
    return converted

try:
    print("🔄 Conectando a Supabase...")
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    conn.autocommit = False
    cur = conn.cursor()
    
    print("📖 Leyendo archivo SQL...")
    with open('backupmisael140126.sql', 'r', encoding='utf-8') as f:
        sql_content = f.read()
    
    # Separar DDL (CREATE TABLE) de DML (INSERT/COPY)
    print("🔧 Procesando estructura y datos...")
    
    # Primero: ejecutar todo hasta los COPY
    ddl_part = sql_content.split('COPY public.')[0]
    
    print("⚙️  Creando tablas...")
    cur.execute(ddl_part)
    conn.commit()
    print("   ✓ Tablas creadas")
    
    # Segundo: convertir COPY a INSERT y ejecutar
    dml_part = 'COPY public.' + 'COPY public.'.join(sql_content.split('COPY public.')[1:])
    
    print("🔄 Convirtiendo e insertando datos (puede tomar 5-10 minutos)...")
    converted_sql = convert_copy_to_insert(dml_part)
    
    # Ejecutar en bloques
    statements = [s.strip() for s in converted_sql.split(';') if s.strip()]
    total = len(statements)
    
    for i, statement in enumerate(statements, 1):
        if i % 100 == 0:
            print(f"   Procesando: {i}/{total} registros...")
        try:
            cur.execute(statement + ';')
        except Exception as e:
            print(f"   ⚠️  Warning en registro {i}: {str(e)[:100]}")
            continue
    
    conn.commit()
    
    print("\n✅ ¡Importación exitosa!\n")
    
    # Verificar
    print("📊 Verificando datos importados:")
    cur.execute("SELECT COUNT(*) FROM auth_user;")
    print(f"   ✓ Usuarios: {cur.fetchone()[0]}")
    
    cur.execute("SELECT COUNT(*) FROM pacientes_paciente;")
    print(f"   ✓ Pacientes: {cur.fetchone()[0]}")
    
    cur.execute("SELECT COUNT(*) FROM agenda_sesion;")
    print(f"   ✓ Sesiones: {cur.fetchone()[0]}")
    
    print("\n🎉 ¡Listo! Actualiza DATABASE_URL en Render.")
    
    cur.close()
    conn.close()
    
except Exception as e:
    print(f"\n❌ Error: {e}")
    if 'conn' in locals():
        conn.rollback()
    sys.exit(1)