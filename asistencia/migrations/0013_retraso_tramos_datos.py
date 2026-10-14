"""
Paso 2/3 — convierte los datos existentes al criterio nuevo.

1) Reglas guardadas con «medio día / día completo» -> tramos sugeridos:
       hasta 30 min: 0 días · hasta 45: ½ · hasta 60: 1 · hasta 90: 2 · más de 90: 3
   (una regla sin ningún valor queda con un único tramo de 0 días = sin descuento).
2) Registros con retraso: se calculan los segundos nuevos. Antes el retraso contaba los minutos desde la hora
   de entrada; ahora solo se acumula lo que excede la tolerancia. La tolerancia se toma del bloque del horario
   que regía ese día (si no se encuentra, 10 min). minutos_tardanza (informativo) no cambia.
"""
from django.db import migrations
from django.db.models import Q
from django.utils import timezone

DIAS = ['LUN', 'MAR', 'MIE', 'JUE', 'VIE', 'SAB', 'DOM']
TRAMOS_SUGERIDOS = [(30, 0), (45, 0.5), (60, 1), (90, 2), (None, 3)]


def convertir(apps, schema_editor):
    Reglas = apps.get_model('asistencia', 'ReglasAsistencia')
    Tramo = apps.get_model('asistencia', 'TramoDescuento')
    Registro = apps.get_model('asistencia', 'RegistroAsistencia')
    Plantilla = apps.get_model('asistencia', 'PlantillaHorario')
    Bloque = apps.get_model('asistencia', 'BloqueHorario')

    for regla in Reglas.objects.all():
        if Tramo.objects.filter(regla=regla).exists():
            continue
        if regla.minutos_medio_dia or regla.minutos_dia_completo:
            for hasta, dias in TRAMOS_SUGERIDOS:
                Tramo.objects.create(regla=regla, hasta_minutos=hasta, dias=dias)
        else:
            Tramo.objects.create(regla=regla, hasta_minutos=None, dias=0)

    for r in Registro.objects.filter(tipo='ENTRADA', estado='TARDANZA', minutos_tardanza__gt=0,
                                     segundos_tarde=0, segundos_acumulables=0):
        dia = timezone.localtime(r.fecha_hora).date()
        codigo = DIAS[dia.weekday()]
        tolerancia = 10
        if r.zona_id and r.bloque and r.bloque.isdigit():
            vigentes = Plantilla.objects.filter(zona_id=r.zona_id, vigente_desde__lte=dia).filter(
                Q(vigente_hasta__isnull=True) | Q(vigente_hasta__gte=dia))
            candidatas = [p for p in vigentes if codigo in (p.dias or [])]
            elegidas = [p for p in candidatas if p.user_id == r.user_id] or [p for p in candidatas if p.user_id is None]
            for p in elegidas:
                b = Bloque.objects.filter(plantilla=p, orden=int(r.bloque)).first()
                if b:
                    tolerancia = b.tolerancia_minutos
                    break
        r.segundos_tarde = r.minutos_tardanza * 60
        r.segundos_acumulables = max(r.minutos_tardanza - tolerancia, 0) * 60
        r.save(update_fields=['segundos_tarde', 'segundos_acumulables'])


class Migration(migrations.Migration):

    dependencies = [
        ('asistencia', '0012_retraso_tramos_permisos'),
    ]

    operations = [
        migrations.RunPython(convertir, migrations.RunPython.noop),
    ]
