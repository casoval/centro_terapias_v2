"""
migrar_agente_publico_a_paciente.py
====================================
Corrige registros de ConversacionAgente guardados con agente='publico'
que pertenecen a tutores de pacientes registrados.

USO:
  # Ver qué cambiaría SIN aplicar (dry-run):
  python3 manage.py shell < migrar_agente_publico_a_paciente.py

  # Aplicar cambios: cambiar DRY_RUN = False y ejecutar de nuevo.
"""

DRY_RUN = True   # <- cambiar a False para aplicar

# ─────────────────────────────────────────────────────────────────────────────

def _normalizar_tel(telefono):
    """Normaliza a formato canonico 591XXXXXXXX."""
    tel = telefono.strip().replace(' ','').replace('-','').replace('(','').replace(')','')
    if tel.startswith('+591'):
        tel = tel[4:]
    elif tel.startswith('591') and len(tel) > 9:
        tel = tel[3:]
    if not tel.startswith('591'):
        tel = f'591{tel}'
    return tel


def _tel_variantes(telefono):
    """Genera las 3 variantes de formato posibles para un numero."""
    tel = telefono.strip().replace(' ','').replace('-','').replace('(','').replace(')','')
    if tel.startswith('+591'):
        base = tel[4:]
    elif tel.startswith('591') and len(tel) > 9:
        base = tel[3:]
    else:
        base = tel
    return list(dict.fromkeys([base, f'591{base}', f'+591{base}']))


def buscar_tutor(telefono):
    """
    Busca si el telefono es tutor activo en la BD de Pacientes.
    Retorna (paciente, cual_tutor) o (None, None).
    Usa distinct() para evitar duplicados por variantes de formato.
    """
    from pacientes.models import Paciente
    variantes = _tel_variantes(telefono)

    matches_t1 = list(
        Paciente.objects
        .filter(telefono_tutor__in=variantes, estado='activo')
        .distinct()
    )
    if len(matches_t1) == 1:
        return matches_t1[0], 'tutor_1'
    if len(matches_t1) > 1:
        ids = list({p.id for p in matches_t1})
        if len(ids) == 1:
            return matches_t1[0], 'tutor_1'
        print(f'  ALERTA: {telefono} es tutor_1 en {len(ids)} pacientes distintos (IDs: {ids}) -- omitido')
        return None, None

    matches_t2 = list(
        Paciente.objects
        .filter(telefono_tutor_2__in=variantes, estado='activo')
        .distinct()
    )
    if len(matches_t2) == 1:
        return matches_t2[0], 'tutor_2'
    if len(matches_t2) > 1:
        ids = list({p.id for p in matches_t2})
        if len(ids) == 1:
            return matches_t2[0], 'tutor_2'
        print(f'  ALERTA: {telefono} es tutor_2 en {len(ids)} pacientes distintos (IDs: {ids}) -- omitido')
        return None, None

    return None, None


def migrar():
    from agente.models import ConversacionAgente

    print('=' * 65)
    print('MIGRACION: publico -> paciente en ConversacionAgente')
    print(f'MODO: {"DRY-RUN (sin cambios reales)" if DRY_RUN else "APLICANDO CAMBIOS"}')
    print('=' * 65)

    # 1. Telefonos unicos con agente='publico'
    telefonos_raw = list(
        ConversacionAgente.objects
        .filter(agente='publico')
        .values_list('telefono', flat=True)
        .distinct()
    )
    print(f'\nTelefonos unicos con agente="publico": {len(telefonos_raw)}')

    # 2. Agrupar por numero canonico para no procesar variantes del mismo
    #    numero como entradas separadas
    grupos = {}
    for tel in telefonos_raw:
        canon = _normalizar_tel(tel)
        grupos.setdefault(canon, []).append(tel)

    print(f'Numeros unicos (normalizados):         {len(grupos)}')

    # 3. Analizar cada numero canonico
    a_migrar        = []
    no_son_paciente = []

    for canon, originales in grupos.items():
        paciente, cual_tutor = buscar_tutor(canon)
        total_msgs = ConversacionAgente.objects.filter(
            agente='publico',
            telefono__in=originales,
        ).count()

        if paciente:
            a_migrar.append((originales, canon, paciente, cual_tutor, total_msgs))
        else:
            no_son_paciente.append((canon, total_msgs))

    # 4. Resumen
    total_msgs_migrar = sum(x[4] for x in a_migrar)

    print(f'\nRESUMEN DE ANALISIS:')
    print(f'  Tutores registrados (a migrar):      {len(a_migrar)} numeros')
    print(f'  Mensajes a reclasificar:             {total_msgs_migrar}')
    print(f'  Desconocidos (se quedan en publico): {len(no_son_paciente)} numeros')

    if a_migrar:
        print(f'\nDETALLE A MIGRAR:')
        for originales, canon, paciente, cual_tutor, total_msgs in a_migrar:
            tutor_nombre = (
                getattr(paciente, 'nombre_tutor_2', '-')
                if cual_tutor == 'tutor_2'
                else paciente.nombre_tutor
            )
            formatos_str = ', '.join(originales)
            print(
                f'  {canon} | '
                f'Paciente: {paciente.nombre} {paciente.apellido} | '
                f'Tutor: {tutor_nombre} ({cual_tutor}) | '
                f'{total_msgs} msgs'
                + (f' [formatos en BD: {formatos_str}]' if len(originales) > 1 else '')
            )

    # 5. Salir si dry-run o sin datos
    if not a_migrar:
        print('\nNo hay registros a migrar.')
        return

    if DRY_RUN:
        print('\nDRY-RUN activo -- no se aplicaron cambios.')
        print('Cambia DRY_RUN = False y ejecuta de nuevo para aplicar.')
        return

    # 6. Aplicar cambios
    print(f'\nAplicando cambios...')
    total_actualizados = 0

    for originales, canon, paciente, cual_tutor, total_msgs in a_migrar:
        updated = ConversacionAgente.objects.filter(
            agente='publico',
            telefono__in=originales,
        ).update(
            agente='paciente',
            telefono=canon,
        )
        total_actualizados += updated
        print(f'  OK {canon} | {updated} registros actualizados')

    print(f'\nMIGRACION COMPLETADA')
    print(f'  Registros actualizados: {total_actualizados}')
    print(f'  Numeros migrados:       {len(a_migrar)}')

    # 7. Verificacion post-migracion
    print('\nVERIFICACION:')
    errores = 0
    for originales, canon, paciente, cual_tutor, _ in a_migrar:
        en_paciente = ConversacionAgente.objects.filter(agente='paciente', telefono=canon).count()
        en_publico  = ConversacionAgente.objects.filter(agente='publico', telefono__in=originales).count()
        ok = en_publico == 0
        if not ok:
            errores += 1
        estado = 'OK' if ok else 'ERROR'
        print(f'  {estado} {canon} | paciente: {en_paciente} msgs | publico restante: {en_publico}')

    if errores == 0:
        print('\nTodo correcto -- ningun registro quedo en publico.')
    else:
        print(f'\n{errores} numeros con registros que no se pudieron mover. Revisar manualmente.')


migrar()