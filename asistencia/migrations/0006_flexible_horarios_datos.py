"""
Paso 2/3 — convierte los datos del esquema viejo al nuevo.

  HorarioPredeterminado  -> PlantillaHorario(user=NULL) + BloqueHorario
      dias_partido  -> 1 plantilla con 2 bloques (manana + tarde; si no hay tarde, 1 bloque)
      dias_continuo -> 1 plantilla con 1 bloque
  ConfigAsistencia personalizada -> PlantillaHorario(user=<usuario>) + bloques
  FechaEspecial continuo/partido -> tipo 'horario' + BloqueFechaEspecial
  RegistroAsistencia.bloque: 'manana'->'1', 'tarde'->'2', 'continuo'->'1'
  EnrolamientoFacial 'enrolado' con vector invalido (el anterior era 5 numeros al azar,
      no un descriptor facial real) -> 'pendiente' para que el profesional se re-enrole.

No borra nada: el paso 3 elimina las columnas viejas.
"""
import datetime as dt
from django.db import migrations

DEF_ENTRADA, DEF_SALIDA = dt.time(8, 0), dt.time(13, 0)
DEF_ENTRADA_T, DEF_SALIDA_T = dt.time(14, 0), dt.time(18, 0)


def _bloques(entrada, salida, tol, entrada_t=None, salida_t=None, tol_t=None, partido=False):
    out = []
    if entrada and salida:
        out.append((1, entrada, salida, 10 if tol is None else tol))
    if partido and entrada_t and salida_t:
        out.append((2, entrada_t, salida_t, 10 if tol_t is None else tol_t))
    return out


def convertir(apps, schema_editor):
    Zona = apps.get_model('asistencia', 'ZonaAsistencia')
    Horario = apps.get_model('asistencia', 'HorarioPredeterminado')
    Config = apps.get_model('asistencia', 'ConfigAsistencia')
    Plantilla = apps.get_model('asistencia', 'PlantillaHorario')
    Bloque = apps.get_model('asistencia', 'BloqueHorario')
    Fecha = apps.get_model('asistencia', 'FechaEspecial')
    BloqueF = apps.get_model('asistencia', 'BloqueFechaEspecial')
    Registro = apps.get_model('asistencia', 'RegistroAsistencia')

    def crear_plantilla(zona, user, nombre, dias, bloques):
        if not dias or not bloques:
            return
        p = Plantilla.objects.create(zona=zona, user=user, nombre=nombre, dias=list(dias))
        for orden, e, s, tol in bloques:
            Bloque.objects.create(plantilla=p, orden=orden, hora_entrada=e, hora_salida=s, tolerancia_minutos=tol)

    horarios = {h.zona_id: h for h in Horario.objects.all()}

    # 1) Predeterminados por zona
    for h in horarios.values():
        crear_plantilla(h.zona, None, 'Horario partido', h.dias_partido,
                        _bloques(h.hora_entrada, h.hora_salida, h.tolerancia_minutos,
                                 h.hora_entrada_tarde, h.hora_salida_tarde, h.tolerancia_tarde, partido=True))
        crear_plantilla(h.zona, None, 'Horario continuo', h.dias_continuo,
                        _bloques(h.hora_entrada, h.hora_salida, h.tolerancia_minutos))

    # 2) Personalizados por profesional (hereda de la zona lo que no se personalizo)
    for c in Config.objects.filter(personalizado=True).select_related('zona'):
        h = horarios.get(c.zona_id)
        z_ent = h.hora_entrada if h else DEF_ENTRADA
        z_sal = h.hora_salida if h else DEF_SALIDA
        z_tol = h.tolerancia_minutos if h else 10
        z_ent_t = h.hora_entrada_tarde if h else DEF_ENTRADA_T
        z_sal_t = h.hora_salida_tarde if h else DEF_SALIDA_T
        z_tol_t = h.tolerancia_tarde if h else 10

        ent = c.hora_entrada_custom or z_ent
        sal = c.hora_salida_custom or z_sal
        tol = c.tolerancia_custom if c.tolerancia_custom is not None else z_tol
        ent_t = c.hora_entrada_tarde_custom or z_ent_t
        sal_t = c.hora_salida_tarde_custom or z_sal_t
        tol_t = c.tolerancia_tarde_custom if c.tolerancia_tarde_custom is not None else z_tol_t

        d_part = c.dias_partido_custom if c.dias_partido_custom is not None else (h.dias_partido if h else [])
        d_cont = c.dias_continuo_custom if c.dias_continuo_custom is not None else (h.dias_continuo if h else [])

        crear_plantilla(c.zona, c.user, 'Horario partido', d_part,
                        _bloques(ent, sal, tol, ent_t, sal_t, tol_t, partido=True))
        crear_plantilla(c.zona, c.user, 'Horario continuo', d_cont,
                        _bloques(ent, sal, tol))

    # 3) Fechas especiales
    for f in Fecha.objects.all():
        if f.tipo_horario == 'libre':
            continue
        h = horarios.get(f.zona_id)
        partido = f.tipo_horario == 'partido'
        ent = f.hora_entrada_especial or (h.hora_entrada if h else DEF_ENTRADA)
        sal = f.hora_salida_especial or (h.hora_salida if h else DEF_SALIDA)
        tol = f.tolerancia_especial if f.tolerancia_especial is not None else (h.tolerancia_minutos if h else 10)
        ent_t = f.hora_entrada_tarde_especial or (h.hora_entrada_tarde if h else DEF_ENTRADA_T)
        sal_t = f.hora_salida_tarde_especial or (h.hora_salida_tarde if h else DEF_SALIDA_T)
        tol_t = f.tolerancia_tarde_especial if f.tolerancia_tarde_especial is not None else (
            (h.tolerancia_tarde if h and h.tolerancia_tarde is not None else 10))
        for orden, e, s, t in _bloques(ent, sal, tol, ent_t, sal_t, tol_t, partido=partido):
            BloqueF.objects.create(fecha_especial=f, orden=orden, hora_entrada=e, hora_salida=s, tolerancia_minutos=t)
        f.tipo_horario = 'horario'
        f.save(update_fields=['tipo_horario'])

    # 5) Enrolamientos con vector de la version anterior (simulado) -> deben re-enrolarse
    Enrol = apps.get_model('asistencia', 'EnrolamientoFacial')

    def descriptor_valido(v):
        return (isinstance(v, list) and len(v) > 0 and
                all(isinstance(d, list) and len(d) == 128 for d in v))

    for e in Enrol.objects.filter(estado='enrolado'):
        if not descriptor_valido(e.vector_facial):
            e.estado = 'pendiente'
            e.vector_facial = None
            e.score_promedio = None
            e.fecha_enrolamiento = None
            e.intentos_fallidos = 0
            e.save()

    # 4) Etiqueta de bloque en registros historicos
    Registro.objects.filter(bloque='manana').update(bloque='1')
    Registro.objects.filter(bloque='tarde').update(bloque='2')
    Registro.objects.filter(bloque='continuo').update(bloque='1')


class Migration(migrations.Migration):

    dependencies = [
        ('asistencia', '0005_flexible_horarios_crear'),
    ]

    operations = [
        # Sin reversa de datos: revertir solo restaura las columnas (ver paso 3).
        migrations.RunPython(convertir, migrations.RunPython.noop),
    ]
