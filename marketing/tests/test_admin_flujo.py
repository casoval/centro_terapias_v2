"""Recorrido completo como lo haría el dueño desde el admin (con un proveedor de IA falso)."""
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from marketing.models import Campana, FichaContenido, Guion, Marca
from marketing.tests.test_guiones import ProveedorFalso, guion_json
from servicios.models import Sucursal


class FlujoAdminTests(TestCase):
    def setUp(self):
        call_command('cargar_marcas_iniciales', verbosity=0)
        Sucursal.objects.create(nombre='Sede Uno', direccion='Av. 1', telefono='76175352')
        self.dueno = User.objects.create_superuser('dueno', 'd@x.com', 'x')
        self.client.force_login(self.dueno)

    def _accion(self, modelo, accion, ids):
        return self.client.post(reverse(f'admin:marketing_{modelo}_changelist'),
                                {'action': accion, '_selected_action': ids}, follow=True)

    def test_flujo_completo(self):
        # 1) sincronizar fichas desde el admin
        f0 = FichaContenido.objects.create(marca=Marca.objects.get(slug='centro-misael'), titulo='x', texto='x')
        r = self._accion('fichacontenido', 'sincronizar_centro', [f0.pk])
        self.assertContains(r, 'Creadas')
        fichas = FichaContenido.objects.filter(fuente='servicios_data')
        self.assertTrue(fichas.exists())
        self.assertFalse(fichas.filter(aprobada=True).exists())

        # 2) aprobar una ficha
        ficha = fichas.first()
        self._accion('fichacontenido', 'aprobar_fichas', [ficha.pk])
        ficha.refresh_from_db()
        self.assertTrue(ficha.aprobada)
        self.assertEqual(ficha.aprobada_por, self.dueno)

        # 3) campaña con esa ficha
        campana = Campana.objects.create(marca=ficha.marca, titulo='Prueba', redes=['instagram'])
        campana.fichas.add(ficha)

        # 4) generar guion con IA (proveedor falso)
        prov = ProveedorFalso([guion_json()])
        with mock.patch('marketing.guiones.obtener_proveedor_texto', return_value=prov):
            r = self._accion('campana', 'generar_guion_ia', [campana.pk])
        self.assertContains(r, 'Validado')
        g = Guion.objects.get(campana=campana)
        self.assertEqual(g.estado, 'validado')

        # 5) aprobar el guion
        r = self._accion('guion', 'aprobar_guiones', [g.pk])
        g.refresh_from_db()
        self.assertEqual(g.estado, 'aprobado')

        # 6) la página de detalle del guion abre sin errores
        r = self.client.get(reverse('admin:marketing_guion_change', args=[g.pk]))
        self.assertEqual(r.status_code, 200)

    def test_campana_sin_fichas_aprobadas_muestra_error_claro(self):
        c = Campana.objects.create(marca=Marca.objects.get(slug='centro-misael'), titulo='Vacía')
        r = self._accion('campana', 'generar_guion_ia', [c.pk])
        self.assertContains(r, 'fichas APROBADAS')
        self.assertFalse(Guion.objects.exists())

    def test_comando_sincronizar_fichas(self):
        from io import StringIO
        out = StringIO()
        call_command('sincronizar_fichas', stdout=out)
        self.assertIn('Creadas:', out.getvalue())
