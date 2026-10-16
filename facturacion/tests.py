import os
import subprocess
import sys
from datetime import date

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

MODULOS_PDF = [
    'facturacion.informe_profesional_pdf',
    'facturacion.informe_sucursal_pdf',
    'facturacion.informe_paciente_pdf',
    'facturacion.informe_paciente_extra_pdf',
    'facturacion.informe_paciente_familia_pdf',
    'asistencia.informe_mensual_pdf',
]


class ImportacionInformesPdfTests(SimpleTestCase):
    """
    Cada módulo de informe PDF debe poder importarse PRIMERO, en un proceso limpio.

    Un ciclo de importaciones solo falla según cuál se cargue antes (p. ej. el informe de profesional
    daba «cannot import name 'fd' from partially initialized module»), por lo que hay que probarlos
    cada uno en un intérprete nuevo y no dentro del proceso de tests, donde ya están todos cargados.
    """

    def test_cada_modulo_se_importa_primero_sin_ciclos(self):
        raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        env = dict(os.environ)
        env.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
        for modulo in MODULOS_PDF:
            codigo = f"import django; django.setup(); import importlib; importlib.import_module('{modulo}')"
            r = subprocess.run([sys.executable, '-c', codigo], cwd=raiz, env=env,
                               capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, f"{modulo} falló al importarse primero:\n{r.stderr[-600:]}")

    def test_funciones_de_formato_son_las_mismas_en_todos_los_informes(self):
        from facturacion import _pdf_formato as fmt
        from facturacion import informe_profesional_pdf as prof
        from facturacion import informe_paciente_extra_pdf as extra
        from facturacion import informe_paciente_familia_pdf as fam
        for nombre in ('fd', 'fm', 'pc', 'bs', '_t'):
            self.assertIs(getattr(prof, nombre), getattr(fmt, nombre), nombre)
        self.assertIs(extra.fd, fmt.fd)
        self.assertIs(fam.fd, fmt.fd)

    def test_formatos(self):
        from facturacion._pdf_formato import bs, fd, fm, pc
        self.assertEqual(fm(1234.5), '1.234,50')
        self.assertEqual(bs(10), 'Bs. 10,00')
        self.assertEqual(pc(12.34), '12,3%')
        self.assertEqual(fd(date(2026, 10, 16)), '16/10/2026')
        self.assertEqual(fd(None), '-')


class ExportarPdfProfesionalTests(TestCase):
    """El botón «Exportar PDF» del reporte individual de un profesional devuelve un PDF."""

    def setUp(self):
        from profesionales.models import Profesional
        self.admin = User.objects.create_superuser('root', password='x')
        self.client.force_login(self.admin)
        self.prof = Profesional.objects.create(nombre='Jhosua', apellido='Callamullo', especialidad='Psicología')

    def test_exporta_pdf(self):
        r = self.client.get(reverse('facturacion:reporte_profesional'),
                            {'profesional': self.prof.pk, 'desde': '2026-09-17', 'hasta': '2026-10-16',
                             'export': 'pdf'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf', 'No se generó el PDF (¿mensaje de error en la página?)')
        self.assertTrue(r.content.startswith(b'%PDF'))
