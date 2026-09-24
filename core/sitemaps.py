# core/sitemaps.py

from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from core.servicios_data import SERVICIOS_PUBLICOS


class StaticViewSitemap(Sitemap):
    priority = 0.8
    changefreq = 'monthly'
    protocol = 'https'

    def items(self):
        return ['core:landing', 'core:misael_kids', 'core:servicios_publicos']

    def location(self, item):
        return reverse(item)


class ServiciosPublicosSitemap(Sitemap):
    """Una entrada de sitemap por cada página de /nuestros-servicios/<slug>/."""
    priority = 0.9
    changefreq = 'monthly'
    protocol = 'https'

    def items(self):
        return list(SERVICIOS_PUBLICOS.keys())

    def location(self, slug):
        return reverse('core:servicio_publico_detalle', args=[slug])
