from django.core.management.base import BaseCommand
from django.utils import timezone

from avisos.models import Anuncio


class Command(BaseCommand):
    help = ('Elimina (fila y archivo) los anuncios ya terminados que NO se guardan en el historial. '
            'Programar una vez al día.')

    def handle(self, *args, **opts):
        hoy = timezone.localdate()
        n = 0
        for a in Anuncio.objects.filter(fecha_fin__lt=hoy, guardar_en_historial=False):
            a.delete()
            n += 1
        self.stdout.write(f'Anuncios eliminados: {n}')
