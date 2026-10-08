"""
Garantiza que marketing sea independiente: no importa nada de las apps
operativas/clínicas. Solo `fuentes.py` (cuando exista) podrá importar de
servicios / profesionales / core.servicios_data.
"""

import ast
from pathlib import Path

from django.test import SimpleTestCase

RAIZ = Path(__file__).resolve().parent.parent

PROHIBIDAS = {
    'pacientes', 'agenda', 'facturacion', 'asistencia', 'chat', 'egresos', 'evaluaciones',
    'agente', 'recordatorios', 'documentos', 'archivos_centro', 'inventario',
    'integracion_misael_kids', 'profesionales', 'servicios', 'core',
}
# Solo estos archivos pueden leer de servicios / profesionales / core
PERMITIDAS_SOLO_EN = {'fuentes.py'}
SOLO_LECTURA = {'servicios', 'profesionales', 'core'}


def _modulos_importados(ruta):
    arbol = ast.parse(ruta.read_text(encoding='utf-8'))
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            for a in nodo.names:
                yield a.name.split('.')[0]
        elif isinstance(nodo, ast.ImportFrom) and nodo.level == 0 and nodo.module:
            yield nodo.module.split('.')[0]


class IndependenciaTests(SimpleTestCase):
    def test_marketing_no_importa_apps_del_centro(self):
        violaciones = []
        for ruta in RAIZ.rglob('*.py'):
            if 'migrations' in ruta.parts or 'tests' in ruta.parts:
                continue
            for mod in set(_modulos_importados(ruta)):
                if mod not in PROHIBIDAS:
                    continue
                if mod in SOLO_LECTURA and ruta.name in PERMITIDAS_SOLO_EN:
                    continue
                violaciones.append(f'{ruta.relative_to(RAIZ)} importa "{mod}"')
        self.assertEqual(violaciones, [], 'Marketing debe ser independiente: ' + '; '.join(violaciones))

    def test_referencias_por_string_solo_a_servicios_y_profesionales(self):
        """Las ForeignKey a otras apps se limitan a servicios y profesionales."""
        from django.apps import apps
        permitidas = {'marketing', 'servicios', 'profesionales', 'auth'}
        ajenas = []
        for modelo in apps.get_app_config('marketing').get_models():
            for campo in modelo._meta.get_fields():
                if campo.is_relation and campo.related_model is not None and not campo.auto_created:
                    app = campo.related_model._meta.app_label
                    if app not in permitidas:
                        ajenas.append(f'{modelo.__name__}.{campo.name} -> {app}')
        self.assertEqual(ajenas, [])
