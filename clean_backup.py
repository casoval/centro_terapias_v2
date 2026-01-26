print("🔄 Limpiando backup para Supabase...")

with open('backupmisael140126.sql', 'r', encoding='utf-8') as f:
    content = f.read()

# Reemplazar el usuario
content = content.replace('centro_misael_user', 'postgres')

# Remover líneas problemáticas
lines_to_remove = [
    'ALTER SCHEMA public OWNER TO',
    'ALTER TABLE ONLY public',
    'ALTER SEQUENCE public',
]

lines = content.split('\n')
cleaned_lines = []

for line in lines:
    # Saltar líneas de ALTER OWNER
    if any(skip in line for skip in lines_to_remove) and 'OWNER TO' in line:
        continue
    cleaned_lines.append(line)

cleaned_content = '\n'.join(cleaned_lines)

# Guardar archivo limpio
with open('backup_clean.sql', 'w', encoding='utf-8') as f:
    f.write(cleaned_content)

print("✅ Backup limpio guardado como: backup_clean.sql")
print("📊 Tamaño original:", len(content), "bytes")
print("📊 Tamaño limpio:", len(cleaned_content), "bytes")