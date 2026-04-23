"""
migrar_agente_publico_a_paciente.py
====================================
Script de migración para corregir registros de ConversacionAgente que
fueron guardados con agente='publico' pero pertenecen a tutores de pacientes
registrados.

PROBLEMA:
  Antes de los fixes de normalización de teléfonos, los tutores registrados
  podían ser mal identificados y sus mensajes se guardaban con agente='publico'
  en lugar de agente='paciente'. Esto causaba:
    - Sus conversaciones aparecían en la pestaña "Público" del panel.
    - El agente paciente no encontraba su historial previo (filtraba agente='paciente').

SOLUCIÓN:
  Este script:
    1. Lee todos los teléfonos únicos con agente='publico'.
    2. Para cada uno, verifica si corresponde a un tutor activo en la BD de Pacientes
       (buscando con todas las variantes de formato del número).
    3. Si es tutor registrado, actualiza sus registros a agente='paciente'.
    4. También normaliza el campo telefono al formato canónico 591XXXXXXXX.

USO:
  Ejecutar como management command de Django:
    python manage.py shell < migrar_agente_publico_a_paciente.py

  O copiar este archivo a:
    tu_app/management/commands/migrar_historial_agente.py
  y ejecutar:
    python manage.py migrar_historial_agente

  Para ver qué cambiaría SIN aplicar cambios (modo dry-run):
    python manage.py shell
    >>> DRY_RUN = True
    >>> exec(open('migrar_agente_publico_a_paciente.py').read())

SEGURIDAD:
  - Solo modifica registros con agente='publico'.
  - No toca registros de staff (superusuario, gerente, recepcionista, profesional).
  - Hace un dry-run por defecto — cambiar DRY_RUN = False para aplicar.
  - Imprime resumen detallado antes y después.
"""

import os
import sys
import django

# ── Configuración ─────────────────────────────────────────────────────────────
# Cambiar a False para aplicar los cambios realmente.
DRY_RUN = True

# ─────────────────────────────────────────────────────────────────────────────

def _normalizar_tel(telefono: str) -> str:
    """Normaliza a formato canónico 591XXXXXXXX."""
    tel = telefono.strip().replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
    if tel.startswith('+591'):
        tel = tel[4:]
    elif tel.startswith('591') and len(tel) > 9:
        tel = tel[3:]
    if not tel.startswith('591'):
        tel = f'591{tel}'
    return tel


def _tel_variantes(telefono: str) -> list:
    """Genera todas las variantes de formato para búsqueda robusta en BD."""
    tel = telefono.strip().replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
    if tel.startswith('+591'):
        base = tel[4:]
    elif tel.startswith('591') and len(tel) > 9:
        base = tel[3:]
    else:
        base = tel
    return list(dict.fromkeys([base, f'591{base}', f'+591{base}']))


def es_tutor_registrado(telefono: str):
    """
    Verifica si el teléfono corresponde a un tutor activo.
    Retorna (paciente, cual_tutor) o (None, None).
    """
    from pacientes.models import Paciente
    variantes = _tel_variantes(telefono)

    matches_t1 = list(Paciente.objects.filter(telefono_tutor__in=variantes, estado='activo'))
    if len(matches_t1) == 1:
        return matches_t1[0], 'tutor_1'
    if len(matches_t1) > 1:
        print(f'  ⚠️  ALERTA: {telefono} aparece como tutor_1 en {len(matches_t1)} pacientes — omitido')
        return None, None

    matches_t2 = list(Paciente.objects.filter(telefono_tutor_2__in=variantes, estado='activo'))
    if len(matches_t2) == 1:
        return matches_t2[0], 'tutor_2'
    if len(matches_t2) > 1:
        print(f'  ⚠️  ALERTA: {telefono} aparece como tutor_2 en {len(matches_t2)} pacientes — omitido')
        return None, None

    return None, None


def migrar():
    from agente.models import ConversacionAgente

    print('=' * 65)
    print('MIGRACIÓN: publico → paciente en ConversacionAgente')
    print(f'MODO: {"DRY-RUN (sin cambios reales)" if DRY_RUN else "⚡ APLICANDO CAMBIOS"}')
    print('=' * 65)

    # ── 1. Obtener teléfonos únicos con agente='publico' ──────────────────
    telefonos_publico = (
        ConversacionAgente.objects
        .filter(agente='publico')
        .values_list('telefono', flat=True)
        .distinct()
    )
    telefonos_publico = list(telefonos_publico)
    print(f'\nTeléfonos únicos con agente="publico": {len(telefonos_publico)}')

    # ── 2. Analizar cada teléfono ─────────────────────────────────────────
    a_migrar        = []   # (telefono_original, tel_canonico, paciente, cual_tutor, count)
    ya_canonicos    = []   # teléfonos que ya están en formato 591XXXXXXXX
    no_son_paciente = []   # teléfonos que no son tutores registrados

    for tel in telefonos_publico:
        paciente, cual_tutor = es_tutor_registrado(tel)
        tel_canonico         = _normalizar_tel(tel)
        count                = ConversacionAgente.objects.filter(
            agente='publico', telefono=tel
        ).count()

        if paciente:
            a_migrar.append((tel, tel_canonico, paciente, cual_tutor, count))
        else:
            no_son_paciente.append((tel, count))

    # ── 3. Mostrar resumen ────────────────────────────────────────────────
    print(f'\n📋 RESUMEN DE ANÁLISIS:')
    print(f'  Tutores registrados (a migrar):  {len(a_migrar)}')
    print(f'  Desconocidos (se quedan en público): {len(no_son_paciente)}')

    if a_migrar:
        print(f'\n🔄 REGISTROS A MIGRAR:')
        total_mensajes = 0
        for tel_orig, tel_canon, paciente, cual_tutor, count in a_migrar:
            normalizado_str = f' → {tel_canon}' if tel_orig != tel_canon else ' (ya canónico)'
            tutor_nombre = paciente.nombre_tutor if cual_tutor == 'tutor_1' else getattr(paciente, 'nombre_tutor_2', '—')
            print(
                f'  📱 {tel_orig}{normalizado_str} | '
                f'Paciente: {paciente.nombre} {paciente.apellido} | '
                f'Tutor: {tutor_nombre} ({cual_tutor}) | '
                f'{count} mensajes'
            )
            total_mensajes += count
        print(f'\n  Total mensajes a reclasificar: {total_mensajes}')

    # ── 4. Aplicar cambios ────────────────────────────────────────────────
    if not a_migrar:
        print('\n✅ No hay registros a migrar.')
        return

    if DRY_RUN:
        print('\n⏸  DRY-RUN activo — no se aplicaron cambios.')
        print('   Cambia DRY_RUN = False y ejecuta de nuevo para aplicar.')
        return

    print(f'\n⚡ Aplicando cambios...')
    total_actualizados = 0

    for tel_orig, tel_canon, paciente, cual_tutor, count in a_migrar:
        # Actualizar agente y normalizar teléfono en un solo UPDATE
        updated = ConversacionAgente.objects.filter(
            agente='publico',
            telefono=tel_orig,
        ).update(
            agente='paciente',
            telefono=tel_canon,
        )
        total_actualizados += updated
        print(f'  ✅ {tel_orig} → {tel_canon} | {updated} registros actualizados')

    print(f'\n✅ MIGRACIÓN COMPLETADA')
    print(f'   Total registros actualizados: {total_actualizados}')
    print(f'   Teléfonos migrados:           {len(a_migrar)}')

    # ── 5. Verificación post-migración ────────────────────────────────────
    print('\n🔍 VERIFICACIÓN POST-MIGRACIÓN:')
    for tel_orig, tel_canon, paciente, cual_tutor, count in a_migrar:
        en_paciente = ConversacionAgente.objects.filter(
            agente='paciente', telefono=tel_canon
        ).count()
        en_publico  = ConversacionAgente.objects.filter(
            agente='publico', telefono__in=[tel_orig, tel_canon]
        ).count()
        estado = '✅' if en_publico == 0 else '❌ PROBLEMA'
        print(
            f'  {estado} {tel_canon} | '
            f'en paciente: {en_paciente} | '
            f'en publico: {en_publico}'
        )


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    # Si se ejecuta directamente (no desde manage.py shell), configurar Django.
    # Ajustar DJANGO_SETTINGS_MODULE según tu proyecto.
    if 'DJANGO_SETTINGS_MODULE' not in os.environ:
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
        django.setup()

migrar()
