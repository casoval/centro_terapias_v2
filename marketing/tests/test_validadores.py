from django.test import SimpleTestCase

from marketing.models import Marca
from marketing.validadores import normalizar, validar_guion


def guion(**kw):
    base = {
        'gancho': '¿Tu hijo necesita apoyo para hablar?',
        'escenas': [{'texto_pantalla': 'Terapia de lenguaje', 'locucion': 'Te acompañamos.',
                     'prompt_visual': 'zoom lento a la sala', 'duracion_seg': 5}],
        'caption': 'Agenda tu evaluación.', 'hashtags': '#potosi',
    }
    base.update(kw)
    return base


def marca(**kw):
    datos = dict(slug='m', nombre='M', palabras_prohibidas='cura\ngarantizado', permite_precios=False)
    datos.update(kw)
    return Marca(**datos)


def reglas(res):
    return {e['regla'] for e in res['errores']}


class ValidadorTests(SimpleTestCase):
    def test_guion_correcto(self):
        r = validar_guion(guion(), marca())
        self.assertTrue(r['valido'], r)

    def test_normalizar_quita_acentos_y_enie(self):
        self.assertEqual(normalizar('Niño ÁÉÍ'), 'nino aei')

    def test_palabra_prohibida_con_acento_y_mayusculas(self):
        r = validar_guion(guion(caption='Resultados GARANTIZADOS'), marca(palabras_prohibidas='garantizados'))
        self.assertIn('palabra_prohibida', reglas(r))

    def test_palabra_prohibida_no_dispara_dentro_de_otra(self):
        # "cura" no debe saltar con "procura" ni "curación"
        r = validar_guion(guion(caption='Procuramos acompañarte'), marca())
        self.assertNotIn('palabra_prohibida', reglas(r))

    def test_palabra_prohibida_si_dispara_exacta(self):
        r = validar_guion(guion(caption='Esto cura la dislalia'), marca())
        self.assertIn('palabra_prohibida', reglas(r))

    def test_precio_bloqueado_si_no_permitido(self):
        for texto in ('Cuesta solo 100 Bs', 'Desde $50', 'El precio es bajo', 'tarifa especial'):
            r = validar_guion(guion(caption=texto), marca())
            self.assertIn('precio', reglas(r), texto)

    def test_precio_permitido_en_marca_tienda(self):
        r = validar_guion(guion(caption='Solo 100 Bs'), marca(permite_precios=True))
        self.assertNotIn('precio', reglas(r))

    def test_testimonios(self):
        for texto in ('Mi hijo mejoró mucho', 'Un testimonio real', 'Nuestros pacientes dicen que sí',
                      'Caso de éxito'):
            r = validar_guion(guion(caption=texto), marca())
            self.assertIn('testimonio', reglas(r), texto)

    def test_pregunta_a_la_familia_no_es_testimonio(self):
        r = validar_guion(guion(gancho='¿Tu hijo tiene dificultades?'), marca())
        self.assertNotIn('testimonio', reglas(r))

    def test_porcentaje_inventado(self):
        r = validar_guion(guion(caption='El 95% mejora'), marca(), corpus_fuente='texto sin cifras')
        self.assertIn('cifra_no_respaldada', reglas(r))

    def test_porcentaje_respaldado_por_fuente(self):
        r = validar_guion(guion(caption='El 95% mejora'), marca(), corpus_fuente='Estudios: 95 % de mejora')
        self.assertNotIn('cifra_no_respaldada', reglas(r))

    def test_cantidad_de_ninos_inventada(self):
        r = validar_guion(guion(caption='Más de 500 niños atendidos'), marca(), corpus_fuente='nada')
        self.assertIn('cifra_no_respaldada', reglas(r))

    def test_anos_de_experiencia_es_advertencia_no_error(self):
        r = validar_guion(guion(caption='15 años de experiencia'), marca(), corpus_fuente='nada')
        self.assertTrue(r['valido'])
        self.assertTrue(any(a['regla'] == 'cifra_dudosa' for a in r['advertencias']))

    def test_telefono_inventado(self):
        r = validar_guion(guion(caption='Llama al 71234567'), marca(), contactos_permitidos=['76175352'])
        self.assertIn('telefono', reglas(r))

    def test_telefono_permitido_con_formato_distinto(self):
        r = validar_guion(guion(caption='Escríbenos al +591 76175352'), marca(), contactos_permitidos=['76175352'])
        self.assertNotIn('telefono', reglas(r))

    def test_estructura(self):
        self.assertIn('estructura', reglas(validar_guion(guion(gancho=''), marca())))
        self.assertIn('estructura', reglas(validar_guion(guion(escenas=[]), marca())))
        self.assertIn('estructura', reglas(validar_guion(guion(gancho='x' * 200), marca())))
        e = [{'texto_pantalla': 't', 'locucion': 'l', 'duracion_seg': 15}] * 7  # 105 s
        self.assertIn('estructura', reglas(validar_guion(guion(escenas=e), marca())))
        e = [{'texto_pantalla': 't' * 95, 'locucion': 'l', 'duracion_seg': 5}]
        self.assertIn('estructura', reglas(validar_guion(guion(escenas=e), marca())))

    def test_ninos_realistas_bloqueados_en_ia_total(self):
        e = [{'texto_pantalla': 't', 'locucion': 'l', 'duracion_seg': 5,
              'prompt_visual': 'Una niña fotorrealista jugando'}]
        r = validar_guion(guion(escenas=e), marca(), origen_visual='ia_total')
        self.assertIn('ninos_realistas', reglas(r))

    def test_ninos_realistas_permitidos_si_se_habilita(self):
        e = [{'texto_pantalla': 't', 'locucion': 'l', 'duracion_seg': 5,
              'prompt_visual': 'Una niña fotorrealista jugando'}]
        r = validar_guion(guion(escenas=e), marca(), origen_visual='ia_total', permite_ninos_realistas=True)
        self.assertNotIn('ninos_realistas', reglas(r))

    def test_ninos_ilustrados_ok_en_ia_total(self):
        e = [{'texto_pantalla': 't', 'locucion': 'l', 'duracion_seg': 5,
              'prompt_visual': 'Una niña en estilo ilustración 3D jugando'}]
        r = validar_guion(guion(escenas=e), marca(), origen_visual='ia_total')
        self.assertNotIn('ninos_realistas', reglas(r))

    def test_fotos_propias_no_aplican_regla_de_ninos_realistas(self):
        e = [{'texto_pantalla': 't', 'locucion': 'l', 'duracion_seg': 5, 'prompt_visual': 'foto real de niños'}]
        r = validar_guion(guion(escenas=e), marca(), origen_visual='propias')
        self.assertNotIn('ninos_realistas', reglas(r))

    # ── plural / género / comodín ───────────────────────────────────────────
    def test_prohibida_tolera_plural_y_genero(self):
        m = marca(palabras_prohibidas='garantizado')
        for texto in ('Resultados garantizados', 'Mejoría garantizada', 'Efectos garantizadas', 'GARANTIZADO'):
            self.assertIn('palabra_prohibida', reglas(validar_guion(guion(caption=texto), m)), texto)

    def test_prohibida_cura_detecta_curas_pero_no_procura(self):
        m = marca(palabras_prohibidas='cura')
        self.assertIn('palabra_prohibida', reglas(validar_guion(guion(caption='Esto curas todo'), m)))
        self.assertNotIn('palabra_prohibida', reglas(validar_guion(guion(caption='Procuramos ayudarte'), m)))
        self.assertNotIn('palabra_prohibida', reglas(validar_guion(guion(caption='Un curso de verano'), m)))

    def test_comodin_explicito(self):
        m = marca(palabras_prohibidas='garantiz*')
        for texto in ('Garantizamos todo', 'Se garantiza', 'Podemos garantizar', 'garantizado'):
            self.assertIn('palabra_prohibida', reglas(validar_guion(guion(caption=texto), m)), texto)
        self.assertNotIn('palabra_prohibida', reglas(validar_guion(guion(caption='Te acompañamos'), m)))

    def test_prohibida_frase_con_plural_en_la_ultima_palabra(self):
        m = marca(palabras_prohibidas='resultado asegurado')
        self.assertIn('palabra_prohibida', reglas(validar_guion(guion(caption='Resultado asegurados'), m)))

    def test_mensaje_de_error_sin_asterisco(self):
        r = validar_guion(guion(caption='Garantizamos'), marca(palabras_prohibidas='garantiz*'))
        self.assertIn('"garantiz"', r['errores'][0]['detalle'])

