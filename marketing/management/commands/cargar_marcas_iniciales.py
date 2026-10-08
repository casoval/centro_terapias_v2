"""
Crea (sin duplicar) las 3 marcas iniciales y la configuración global.

    python manage.py cargar_marcas_iniciales

Es idempotente: si la marca ya existe NO sobrescribe nada de lo que hayas
editado en el admin. Los valores son un punto de partida: revísalos y
complétalos (WhatsApp, colores, reglas) en Admin > Marketing > Marcas.
"""

from django.core.management.base import BaseCommand

from marketing.models import ConfigMarketing, Marca

REGLAS_SALUD = (
    'Somos un centro de rehabilitación y desarrollo infantil. No prometer curas ni resultados '
    'garantizados. No hacer diagnósticos ni dar consejos médicos individuales. No usar '
    'testimonios ni historias de pacientes reales. Invitar siempre a una evaluación profesional.'
)
PROHIBIDAS_SALUD = '\n'.join([
    'cura', 'curar*', 'curamos', 'curación', 'curativ*', 'garantiz*', 'garantía de resultados',
    'resultados asegurados', '100% efectivo', 'milagro', 'milagroso', 'sin falla',
])

MARCAS = [
    {
        'slug': 'centro-misael',
        'nombre': 'Centro Misael',
        'tono_voz': 'Cálido, cercano y profesional. Trata de "tú". Sin tecnicismos innecesarios. '
                    'Transmite tranquilidad y acompañamiento a las familias.',
        'reglas_contenido': REGLAS_SALUD,
        'palabras_prohibidas': PROHIBIDAS_SALUD,
        'cierre_fijo': 'Agenda tu evaluación por WhatsApp',
        'url_web': 'https://neuromisael.com',
        'cuenta_facebook': 'CentroMisael',
        'cuenta_instagram': 'rehabilitacioninfantilmisael',
        'cuenta_tiktok': 'centroinfantilmisael',
    },
    {
        'slug': 'misael-kids',
        'nombre': 'Misael Kids',
        'tono_voz': 'Alegre, cálido y confiable. Trata de "tú". Habla a madres y padres de niños pequeños. '
                    'Enfoque en educación temprana, neurodesarrollo e inclusión.',
        'reglas_contenido': (
            'Jardín infantil y parvulario. No prometer resultados académicos garantizados. '
            'No mostrar niños reconocibles sin autorización escrita de sus tutores. '
            'No comparar con otras instituciones.'
        ),
        'palabras_prohibidas': 'garantiz*\nel mejor jardín\nel número uno\nresultados asegurados',
        'cierre_fijo': 'Inscripciones abiertas. Escríbenos por WhatsApp',
    },
    {
        'slug': 'misael-toys',
        'nombre': 'Misael Toys',
        'tono_voz': 'Lúdico, creativo y cercano. Trata de "tú". Destaca juguetes sensoriales y de '
                    'estimulación impresos en 3D, pensados para el desarrollo infantil.',
        'reglas_contenido': (
            'Tienda de juguetes. No afirmar que un juguete trata, cura o mejora un diagnóstico (TEA, TDAH, etc.). '
            'Se puede decir que está "pensado para acompañar" el juego y el desarrollo. '
            'Mostrar siempre el producto real, sin alterarlo.'
        ),
        'palabras_prohibidas': 'cura\ncurar*\ntrata el autismo\ntrata el TDAH\ngarantiz*\nmilagroso',
        'cierre_fijo': 'Compra en tienda.neuromisael.com · Envíos a todo Bolivia',
        'url_web': 'https://tienda.neuromisael.com',
        'permite_precios': True,
    },
]


class Command(BaseCommand):
    help = 'Crea las marcas iniciales (Centro Misael, Misael Kids, Misael Toys) y la configuración global.'

    def handle(self, *args, **options):
        for datos in MARCAS:
            slug = datos['slug']
            _, creada = Marca.objects.get_or_create(slug=slug, defaults=datos)
            self.stdout.write(
                self.style.SUCCESS(f'Creada: {datos["nombre"]}') if creada
                else f'Ya existía (sin cambios): {datos["nombre"]}'
            )
        ConfigMarketing.get()
        self.stdout.write(self.style.SUCCESS('Configuración global lista.'))
