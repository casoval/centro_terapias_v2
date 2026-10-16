import datetime as dt
import json
from unittest import mock

import numpy as np
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (
    BloqueFechaEspecial, BloqueHorario, ConfigAsistencia, EnrolamientoFacial, FechaEspecial,
    PermisoAsistencia, PermisoReenrolamiento, PlantillaHorario, RegistroAsistencia, ReglasAsistencia,
    TramoDescuento, ZonaAsistencia,
)
from .services import (
    CalculadorEstado, ErrorEnrolamiento, HorarioDia, ResolvedorHorario, ValidadorAsistencia,
    calcular_estado_dia, construir_panel, generar_ausentes, procesar_enrolamiento,
    dias_descuento, fmt_min_seg, registrar_manual, registros_validos_del_dia, segundos_acumulados_mes,
    segundos_para_proximo_tramo, segundos_sin_descuento, texto_tramos,
)

T = dt.time
LUN_VIE = ['LUN', 'MAR', 'MIE', 'JUE', 'VIE']

# Fechas fijas: 2026-10-05 es lunes, 2026-10-10 es sábado, 2026-10-11 es domingo
LUNES, SABADO, DOMINGO = dt.date(2026, 10, 5), dt.date(2026, 10, 10), dt.date(2026, 10, 11)
RNG = np.random.RandomState(7)
ROSTRO_A = RNG.normal(0, 0.1, 128)       # "persona A"
ROSTRO_B = RNG.normal(0, 0.1, 128)       # "persona B" (distancia ~1.6 de A)


def cercano(base, ruido=0.01, seed=0):
    """Descriptor de la misma persona con pequeñas variaciones."""
    return (base + np.random.RandomState(seed).normal(0, ruido, 128)).tolist()


def local(fecha, hora, minuto=0):
    return timezone.make_aware(dt.datetime.combine(fecha, T(hora, minuto)))


def crear_profesional(username, enrolado=True, zona=None, personalizado=False):
    u = User.objects.create_user(username, first_name=username.capitalize(), last_name='Test', password='x')
    u.perfil.rol = 'profesional'
    u.perfil.save()                                   # dispara la señal → EnrolamientoFacial
    if enrolado:
        enrol = u.enrolamiento
        procesar_enrolamiento(enrol, [cercano(ROSTRO_A, seed=i) for i in range(5)])
    if zona is not None:
        ConfigAsistencia.objects.create(user=u, zona=zona, personalizado=personalizado)
    return u


def crear_plantilla(zona, dias, bloques, user=None, nombre=''):
    p = PlantillaHorario.objects.create(zona=zona, user=user, dias=dias, nombre=nombre)
    for i, (e, s, tol, *resto) in enumerate(bloques, start=1):
        BloqueHorario.objects.create(plantilla=p, orden=i, hora_entrada=e, hora_salida=s, tolerancia_minutos=tol,
                                     max_retraso_minutos=resto[0] if resto else None)
    return p


TRAMOS_DEF = [(30, 0), (45, 0.5), (60, 1), (90, 2)]     # hasta N min -> días; más de 90 min -> 3 días (resto)


def crear_reglas(tramos=TRAMOS_DEF, resto=3, desde=None):
    """Guarda una versión de reglas con esos tramos (misma fecha = actualiza la versión)."""
    regla = ReglasAsistencia(vigente_desde=desde or dt.date(2000, 1, 1))
    regla.save()
    regla.tramos.all().delete()
    for hasta, dias in tramos:
        TramoDescuento.objects.create(regla=regla, hasta_minutos=hasta, dias=dias)
    TramoDescuento.objects.create(regla=regla, hasta_minutos=None, dias=resto)
    return regla


def datos_reglas(filas, resto, mes, anio, vacias=2):
    """POST para la pantalla de Reglas: filas = [(hasta_min, días), ...]."""
    data = {'mes': mes, 'anio': anio, 'dias_resto': resto, 'tramos-TOTAL_FORMS': len(filas) + vacias,
            'tramos-INITIAL_FORMS': 0, 'tramos-MIN_NUM_FORMS': 0, 'tramos-MAX_NUM_FORMS': 10}
    for i, (h, d) in enumerate(filas):
        data[f'tramos-{i}-hasta'] = h
        data[f'tramos-{i}-dias'] = d
    for j in range(vacias):
        data[f'tramos-{len(filas) + j}-hasta'] = ''
        data[f'tramos-{len(filas) + j}-dias'] = ''
    return data


class BaseAsistencia(TestCase):
    def setUp(self):
        self.zona = ZonaAsistencia.objects.create(
            nombre='Sede', latitud='-16.500000', longitud='-68.150000', radio_metros=100)
        # El caso pedido: L-V partido (mañana y tarde), sábado solo mañana
        self.p_semana = crear_plantilla(
            self.zona, LUN_VIE, [(T(8), T(13), 10), (T(14), T(18), 15)], nombre='Lun-Vie')
        self.p_sabado = crear_plantilla(self.zona, ['SAB'], [(T(8), T(12), 5)], nombre='Sábado')

    def horario(self, user, fecha):
        config = ConfigAsistencia.objects.get(user=user, zona=self.zona)
        return ResolvedorHorario(user, self.zona, config, fecha).resolver()

    def marcar(self, user, tipo, ahora, vector=None, lat=-16.5, lon=-68.15, precision=10):
        """Marca simulando que 'ahora' es la hora local indicada."""
        vector = cercano(ROSTRO_A, seed=99) if vector is None else vector
        with mock.patch('django.utils.timezone.now', return_value=ahora):
            u = User.objects.get(pk=user.pk)           # instancia fresca (sin caché de enrolamiento)
            return ValidadorAsistencia(
                u, tipo, lat, lon, vector, device_id='dev', precision_gps=precision).ejecutar()


# ══════════════════════════════════════════════════════════════════════════════
# HORARIOS
# ══════════════════════════════════════════════════════════════════════════════

class HorariosPorDiaTests(BaseAsistencia):
    def test_lunes_a_viernes_partido_y_sabado_solo_manana(self):
        u = crear_profesional('ana', zona=self.zona)

        lunes = self.horario(u, LUNES)
        self.assertEqual(len(lunes.bloques), 2)
        self.assertEqual(lunes.tipo_display, 'Partido')
        self.assertEqual([(b.entrada, b.salida) for b in lunes.bloques],
                         [(T(8), T(13)), (T(14), T(18))])
        self.assertEqual([b.tolerancia for b in lunes.bloques], [10, 15])

        sabado = self.horario(u, SABADO)
        self.assertEqual(len(sabado.bloques), 1)
        self.assertEqual(sabado.tipo_display, 'Continuo')
        self.assertEqual((sabado.bloques[0].entrada, sabado.bloques[0].salida), (T(8), T(12)))

        domingo = self.horario(u, DOMINGO)
        self.assertFalse(domingo.es_laborable)

    def test_horario_propio_reemplaza_al_de_la_zona(self):
        u = crear_profesional('beto', zona=self.zona, personalizado=True)
        crear_plantilla(self.zona, ['LUN', 'MIE'], [(T(9), T(15), 0)], user=u)
        self.assertEqual(len(self.horario(u, LUNES).bloques), 1)
        self.assertEqual(self.horario(u, LUNES).origen, 'personal')
        # el martes no está en su horario propio → libre (no hereda el de la zona)
        self.assertFalse(self.horario(u, LUNES + dt.timedelta(days=1)).es_laborable)

    def test_sin_personalizado_se_ignoran_plantillas_personales(self):
        u = crear_profesional('cata', zona=self.zona, personalizado=False)
        crear_plantilla(self.zona, ['LUN'], [(T(9), T(10), 0)], user=u)
        self.assertEqual(len(self.horario(u, LUNES).bloques), 2)

    def test_fecha_especial_horario_y_libre(self):
        u = crear_profesional('dani', zona=self.zona)
        fe = FechaEspecial.objects.create(zona=self.zona, fecha=LUNES, tipo_horario='horario', motivo='Medio día')
        BloqueFechaEspecial.objects.create(fecha_especial=fe, orden=1, hora_entrada=T(8), hora_salida=T(12), tolerancia_minutos=5)
        h = self.horario(u, LUNES)
        self.assertEqual(len(h.bloques), 1)
        self.assertEqual(h.origen, 'fecha_especial')

        FechaEspecial.objects.create(zona=self.zona, fecha=LUNES + dt.timedelta(days=1), tipo_horario='libre')
        self.assertEqual(self.horario(u, LUNES + dt.timedelta(days=1)).tipo, 'libre')

    def test_fecha_especial_solo_para_algunos_profesionales(self):
        a = crear_profesional('a1', zona=self.zona)
        b = crear_profesional('b1', zona=self.zona)
        fe = FechaEspecial.objects.create(zona=self.zona, fecha=LUNES, tipo_horario='libre')
        fe.profesionales.add(a)
        self.assertEqual(self.horario(a, LUNES).tipo, 'libre')
        self.assertEqual(self.horario(b, LUNES).tipo, 'normal')


class CalculadorEstadoTests(BaseAsistencia):
    def setUp(self):
        super().setUp()
        self.u = crear_profesional('eli', zona=self.zona)
        self.h = self.horario(self.u, LUNES)

    def calc(self, hora, minuto=0, usados=()):
        return CalculadorEstado(self.h, local(LUNES, hora, minuto), usados).calcular()

    def test_puntual_dentro_de_tolerancia(self):
        self.assertEqual(self.calc(8, 10), ('PUNTUAL', '1', 0))
        self.assertEqual(self.calc(7, 30), ('PUNTUAL', '1', 0))

    def test_tardanza_bloque_manana(self):
        self.assertEqual(self.calc(8, 25), ('TARDANZA', '1', 25))

    def test_bloque_tarde_con_su_propia_tolerancia(self):
        self.assertEqual(self.calc(14, 15, usados={1}), ('PUNTUAL', '2', 0))     # tolerancia tarde = 15
        self.assertEqual(self.calc(14, 30, usados={1}), ('TARDANZA', '2', 30))

    def test_corte_entre_bloques_es_la_mitad(self):
        # 13:29 aún es bloque 1; 13:31 ya es bloque 2
        self.assertEqual(self.calc(13, 29)[1], '1')
        self.assertEqual(self.calc(13, 31)[1], '2')

    def test_reentrada_en_bloque_ya_usado_no_calcula_tardanza(self):
        self.assertEqual(self.calc(10, 30, usados={1}), ('PUNTUAL', '', 0))

    def test_sabado_usa_su_propio_horario(self):
        h = self.horario(self.u, SABADO)
        self.assertEqual(CalculadorEstado(h, local(SABADO, 8, 5)).calcular(), ('PUNTUAL', '1', 0))
        self.assertEqual(CalculadorEstado(h, local(SABADO, 8, 20)).calcular(), ('TARDANZA', '1', 20))

    def test_dia_sin_horario_registra_sin_calculo(self):
        self.assertEqual(CalculadorEstado(HorarioDia(), local(DOMINGO, 9)).calcular(), ('PUNTUAL', '', 0))


# ══════════════════════════════════════════════════════════════════════════════
# MARCADO COMPLETO (GPS + secuencia + rostro)
# ══════════════════════════════════════════════════════════════════════════════

class MarcadoTests(BaseAsistencia):
    def setUp(self):
        super().setUp()
        self.u = crear_profesional('fer', zona=self.zona)

    def test_jornada_partida_completa(self):
        ok, r, _ = self.marcar(self.u, 'ENTRADA', local(LUNES, 8, 3))
        self.assertTrue(ok); self.assertEqual((r.estado, r.bloque), ('PUNTUAL', '1'))
        ok, r, _ = self.marcar(self.u, 'SALIDA', local(LUNES, 13, 0))
        self.assertTrue(ok); self.assertEqual(r.bloque, '1')
        ok, r, _ = self.marcar(self.u, 'ENTRADA', local(LUNES, 14, 30))
        self.assertTrue(ok); self.assertEqual((r.estado, r.bloque, r.minutos_tardanza), ('TARDANZA', '2', 30))
        ok, r, _ = self.marcar(self.u, 'SALIDA', local(LUNES, 18, 1))
        self.assertTrue(ok); self.assertEqual(r.bloque, '2')

        estado = calcular_estado_dia(registros_validos_del_dia(self.u, LUNES), self.horario(self.u, LUNES),
                                     local(LUNES, 18, 2))
        self.assertTrue(estado.completo)
        # y ya no se puede marcar más
        ok, _, errores = self.marcar(self.u, 'ENTRADA', local(LUNES, 18, 5))
        self.assertFalse(ok)
        self.assertIn('completaste', errores[0])

    def test_sabado_una_sola_jornada_de_manana(self):
        ok, r, _ = self.marcar(self.u, 'ENTRADA', local(SABADO, 8, 0))
        self.assertTrue(ok); self.assertEqual(r.bloque, '1')
        ok, _, _ = self.marcar(self.u, 'SALIDA', local(SABADO, 12, 0))
        self.assertTrue(ok)
        ok, _, errores = self.marcar(self.u, 'ENTRADA', local(SABADO, 12, 30))
        self.assertFalse(ok)          # sábado no tiene bloque de tarde
        self.assertEqual(RegistroAsistencia.objects.filter(estado__in=['PUNTUAL', 'TARDANZA']).count(), 2)

    def test_no_duplica_entrada_en_servidor(self):
        self.assertTrue(self.marcar(self.u, 'ENTRADA', local(LUNES, 8, 0))[0])
        ok, reg, errores = self.marcar(self.u, 'ENTRADA', local(LUNES, 8, 1))
        self.assertFalse(ok); self.assertIsNone(reg)
        self.assertIn('Ya registraste una entrada', errores[0])
        self.assertEqual(RegistroAsistencia.objects.filter(tipo='ENTRADA', estado='PUNTUAL').count(), 1)

    def test_no_permite_salida_sin_entrada(self):
        ok, reg, errores = self.marcar(self.u, 'SALIDA', local(LUNES, 9, 0))
        self.assertFalse(ok); self.assertIsNone(reg)
        self.assertEqual(RegistroAsistencia.objects.count(), 0)

    def test_reentrada_dentro_del_mismo_bloque(self):
        self.marcar(self.u, 'ENTRADA', local(LUNES, 8, 0))
        self.marcar(self.u, 'SALIDA', local(LUNES, 10, 0))          # sale a una gestión
        ok, r, _ = self.marcar(self.u, 'ENTRADA', local(LUNES, 10, 45))
        self.assertTrue(ok); self.assertEqual((r.estado, r.bloque), ('PUNTUAL', ''))
        self.marcar(self.u, 'SALIDA', local(LUNES, 13, 0))
        # sigue pudiendo marcar el bloque de la tarde
        ok, r, _ = self.marcar(self.u, 'ENTRADA', local(LUNES, 14, 0))
        self.assertTrue(ok); self.assertEqual(r.bloque, '2')

    def test_rostro_distinto_es_rechazado_y_se_registra(self):
        ok, r, errores = self.marcar(self.u, 'ENTRADA', local(LUNES, 8, 0), vector=ROSTRO_B.tolist())
        self.assertFalse(ok)
        self.assertEqual(r.estado, 'DENEGADO_BIO')
        self.assertGreater(r.biometrico_score, 1.0)
        self.u.enrolamiento.refresh_from_db()
        self.assertEqual(self.u.enrolamiento.intentos_fallidos, 1)

    def test_sin_vector_facial_es_rechazado(self):
        ok, r, errores = self.marcar(self.u, 'ENTRADA', local(LUNES, 8, 0), vector='')
        self.assertFalse(ok); self.assertEqual(r.estado, 'DENEGADO_BIO')

    def test_vector_de_tamano_incorrecto_es_rechazado(self):
        ok, r, _ = self.marcar(self.u, 'ENTRADA', local(LUNES, 8, 0), vector=[0.1] * 5)
        self.assertFalse(ok); self.assertEqual(r.estado, 'DENEGADO_BIO')

    def test_cinco_fallos_bloquean_y_el_rostro_correcto_ya_no_sirve(self):
        for i in range(5):
            self.marcar(self.u, 'ENTRADA', local(LUNES, 8, i), vector=ROSTRO_B.tolist())
        self.u.enrolamiento.refresh_from_db()
        self.assertEqual(self.u.enrolamiento.estado, 'bloqueado')
        ok, _, errores = self.marcar(self.u, 'ENTRADA', local(LUNES, 8, 30))
        self.assertFalse(ok); self.assertIn('bloqueada', errores[0])

    def test_exito_reinicia_intentos_fallidos(self):
        self.marcar(self.u, 'ENTRADA', local(LUNES, 8, 0), vector=ROSTRO_B.tolist())
        self.assertTrue(self.marcar(self.u, 'ENTRADA', local(LUNES, 8, 1))[0])
        self.u.enrolamiento.refresh_from_db()
        self.assertEqual(self.u.enrolamiento.intentos_fallidos, 0)

    def test_fuera_de_zona_indica_la_zona_mas_cercana(self):
        lejana = ZonaAsistencia.objects.create(nombre='Lejana', latitud='-16.600000', longitud='-68.150000', radio_metros=50)
        cercana = ZonaAsistencia.objects.create(nombre='Cercana', latitud='-16.502000', longitud='-68.150000', radio_metros=50)
        ConfigAsistencia.objects.filter(user=self.u).delete()
        ConfigAsistencia.objects.create(user=self.u, zona=cercana)
        ConfigAsistencia.objects.create(user=self.u, zona=lejana)      # la última del bucle es la MÁS LEJANA
        ok, r, errores = self.marcar(self.u, 'ENTRADA', local(LUNES, 8, 0), lat=-16.5, lon=-68.15)
        self.assertFalse(ok); self.assertEqual(r.estado, 'DENEGADO_GPS')
        self.assertIn('Cercana', errores[0])
        self.assertAlmostEqual(r.distancia_metros, 222.4, delta=2)

    def test_precision_gps_pobre_es_rechazada(self):
        ok, r, errores = self.marcar(self.u, 'ENTRADA', local(LUNES, 8, 0), precision=500)
        self.assertFalse(ok); self.assertIn('Precisión', errores[0])

    def test_precision_aceptable_se_guarda(self):
        ok, r, _ = self.marcar(self.u, 'ENTRADA', local(LUNES, 8, 0), precision=35.5)
        self.assertTrue(ok); self.assertEqual(r.precision_metros, 35.5)

    def test_coordenadas_cero_no_se_tratan_como_faltantes(self):
        ok, r, errores = self.marcar(self.u, 'ENTRADA', local(LUNES, 8, 0), lat=0, lon=0)
        self.assertFalse(ok)
        self.assertNotIn('No se recibieron', errores[0])       # hay coordenadas, solo que fuera de zona

    def test_sin_enrolar_no_puede_marcar(self):
        v = crear_profesional('sin', enrolado=False, zona=self.zona)
        ok, r, errores = self.marcar(v, 'ENTRADA', local(LUNES, 8, 0))
        self.assertFalse(ok); self.assertEqual(r.estado, 'DENEGADO_BIO')

    def test_registro_de_noche_cae_en_el_dia_local(self):
        # 21:00 hora de La Paz = 01:00 UTC del día siguiente. Debe contar como el MISMO día local.
        self.marcar(self.u, 'ENTRADA', local(LUNES, 8, 0))
        r = RegistroAsistencia.objects.get()
        self.assertEqual(timezone.localtime(r.fecha_hora).date(), LUNES)
        RegistroAsistencia.objects.create(
            user=self.u, tipo='SALIDA', estado='PUNTUAL', fecha_hora=local(LUNES, 21, 0))
        self.assertEqual(len(registros_validos_del_dia(self.u, LUNES)), 2)
        self.assertEqual(len(registros_validos_del_dia(self.u, LUNES + dt.timedelta(days=1))), 0)


class MarcadoManualTests(BaseAsistencia):
    def test_manual_usa_misma_logica_y_secuencia(self):
        admin = User.objects.create_superuser('adm', password='x')
        u = crear_profesional('gus', zona=self.zona)
        ok, r, _ = registrar_manual(u, 'ENTRADA', admin, 'Sin celular', ahora=local(LUNES, 8, 40))
        self.assertTrue(ok); self.assertEqual((r.estado, r.bloque, r.minutos_tardanza), ('TARDANZA', '1', 40))
        self.assertTrue(r.es_manual)
        ok, _, error = registrar_manual(u, 'ENTRADA', admin, ahora=local(LUNES, 8, 41))
        self.assertFalse(ok); self.assertIn('salida', error)
        self.assertTrue(registrar_manual(u, 'SALIDA', admin, ahora=local(LUNES, 13, 0))[0])
        # segundo bloque también se puede registrar a mano
        ok, r, _ = registrar_manual(u, 'ENTRADA', admin, ahora=local(LUNES, 14, 5))
        self.assertTrue(ok); self.assertEqual(r.bloque, '2')


# ══════════════════════════════════════════════════════════════════════════════
# ENROLAMIENTO
# ══════════════════════════════════════════════════════════════════════════════

class EnrolamientoTests(BaseAsistencia):
    def test_se_crea_enrolamiento_al_asignar_rol_profesional(self):
        u = User.objects.create_user('nuevo', password='x')
        self.assertFalse(EnrolamientoFacial.objects.filter(user=u).exists())
        u.perfil.rol = 'profesional'
        u.perfil.save()
        self.assertEqual(u.enrolamiento.estado, 'pendiente')

    def test_enrolamiento_valido_guarda_descriptores_reales(self):
        u = crear_profesional('hugo', enrolado=False)
        e = procesar_enrolamiento(u.enrolamiento, [cercano(ROSTRO_A, seed=i) for i in range(5)])
        self.assertEqual(e.estado, 'enrolado')
        self.assertEqual(len(e.vector_facial), 5)
        self.assertTrue(all(len(v) == 128 for v in e.vector_facial))
        self.assertGreater(e.score_promedio, 0.8)

    def test_capturas_insuficientes_o_invalidas(self):
        u = crear_profesional('ines', enrolado=False)
        with self.assertRaises(ErrorEnrolamiento):
            procesar_enrolamiento(u.enrolamiento, [cercano(ROSTRO_A)] * 2)
        with self.assertRaises(ErrorEnrolamiento):
            procesar_enrolamiento(u.enrolamiento, [[0.1] * 5] * 5)       # el vector "simulado" viejo
        with self.assertRaises(ErrorEnrolamiento):
            procesar_enrolamiento(u.enrolamiento, 'basura')
        u.enrolamiento.refresh_from_db()
        self.assertEqual(u.enrolamiento.estado, 'pendiente')

    def test_capturas_de_personas_distintas_se_rechazan(self):
        u = crear_profesional('jaime', enrolado=False)
        mezcla = [cercano(ROSTRO_A, seed=1), cercano(ROSTRO_A, seed=2), ROSTRO_B.tolist()]
        with self.assertRaises(ErrorEnrolamiento):
            procesar_enrolamiento(u.enrolamiento, mezcla)

    def test_reenrolar_requiere_permiso_y_se_consume(self):
        u = crear_profesional('karla')
        enrol = u.enrolamiento
        self.assertFalse(enrol.puede_enrolar())                      # ya enrolada: necesita permiso
        PermisoReenrolamiento.objects.create(enrolamiento=enrol, motivo='cambio de look')
        self.assertTrue(enrol.puede_enrolar())
        procesar_enrolamiento(enrol, [cercano(ROSTRO_B, seed=i) for i in range(4)])
        self.assertFalse(enrol.puede_enrolar())                      # permiso usado
        self.assertTrue(enrol.permisos.get().usado)


# ══════════════════════════════════════════════════════════════════════════════
# AUSENCIAS Y PANEL
# ══════════════════════════════════════════════════════════════════════════════

class AusenciasTests(BaseAsistencia):
    def test_ausente_por_bloque_terminado(self):
        u = crear_profesional('lola', zona=self.zona)
        # 13:30 del lunes: el bloque 1 terminó y no marcó; el bloque 2 aún no terminó
        self.assertEqual(generar_ausentes(LUNES, local(LUNES, 13, 30)), 1)
        a = RegistroAsistencia.objects.get(estado='AUSENTE')
        self.assertEqual((a.bloque, a.user), ('1', u))
        # idempotente
        self.assertEqual(generar_ausentes(LUNES, local(LUNES, 13, 45)), 0)
        # al final del día aparece también el bloque 2
        self.assertEqual(generar_ausentes(LUNES, local(LUNES, 19, 0)), 1)
        self.assertEqual(RegistroAsistencia.objects.filter(estado='AUSENTE').count(), 2)

    def test_no_hay_ausencia_si_marco_ese_bloque(self):
        u = crear_profesional('mario', zona=self.zona)
        self.marcar(u, 'ENTRADA', local(LUNES, 8, 0))
        self.marcar(u, 'SALIDA', local(LUNES, 13, 0))
        generar_ausentes(LUNES, local(LUNES, 19, 0))
        a = RegistroAsistencia.objects.filter(estado='AUSENTE')
        self.assertEqual([x.bloque for x in a], ['2'])               # solo faltó a la tarde

    def test_sin_ausencias_en_domingo_dias_libres_ni_sin_enrolar(self):
        crear_profesional('nora', zona=self.zona)
        crear_profesional('omar', enrolado=False, zona=self.zona)
        self.assertEqual(generar_ausentes(DOMINGO, local(DOMINGO, 23, 0)), 0)        # sin horario
        FechaEspecial.objects.create(zona=self.zona, fecha=LUNES, tipo_horario='libre')
        self.assertEqual(generar_ausentes(LUNES, local(LUNES, 23, 0)), 0)            # feriado
        martes = LUNES + dt.timedelta(days=1)
        self.assertEqual(generar_ausentes(martes, local(martes, 23, 0)), 2)          # solo 'nora' (2 bloques)

    def test_la_ausencia_se_anula_si_el_profesional_llega_tarde(self):
        u = crear_profesional('pili', zona=self.zona)
        generar_ausentes(LUNES, local(LUNES, 13, 30))
        self.assertEqual(RegistroAsistencia.objects.filter(estado='AUSENTE', bloque='1').count(), 1)
        # llega a las 13:20 de su bloque 1? no: marca a las 12:55 con reloj atrasado simulado vía manual
        admin = User.objects.create_superuser('adm2', password='x')
        registrar_manual(u, 'ENTRADA', admin, ahora=local(LUNES, 12, 50))
        self.assertEqual(RegistroAsistencia.objects.filter(estado='AUSENTE', bloque='1').count(), 0)

    def test_comando_de_gestion(self):
        crear_profesional('quique', zona=self.zona)
        pasado = LUNES - dt.timedelta(days=7)          # un lunes ya terminado (el comando usa la hora real)
        call_command('generar_ausentes', fecha=pasado.isoformat(), verbosity=0)
        self.assertEqual(RegistroAsistencia.objects.filter(estado='AUSENTE').count(), 2)


class PanelTests(BaseAsistencia):
    def test_panel_resume_pares_estados_y_pocas_consultas(self):
        for i in range(8):
            crear_profesional(f'p{i}', zona=self.zona)
        listo = User.objects.get(username='p0')
        self.marcar(listo, 'ENTRADA', local(LUNES, 8, 30))
        self.marcar(listo, 'SALIDA', local(LUNES, 13, 0))
        self.marcar(User.objects.get(username='p1'), 'ENTRADA', local(LUNES, 8, 0))

        with self.assertNumQueries(12):                # (asuetos + sucursales para las reglas por alcance + bajas del período) fijo, no crece con la cantidad de profesionales
            filas, resumen = construir_panel(LUNES, local(LUNES, 13, 30))
        por_user = {f['user'].username: f for f in filas}
        self.assertEqual(por_user['p0']['estado_dia'], 'TARDANZA')
        self.assertEqual(len(por_user['p0']['pares']), 1)
        self.assertEqual(por_user['p0']['siguiente'], 'ENTRADA')       # le falta la tarde
        self.assertEqual(por_user['p1']['siguiente'], 'SALIDA')
        self.assertEqual(por_user['p2']['estado_dia'], 'ausente')      # bloque 1 ya terminó
        self.assertEqual(resumen['presentes'], 2)
        self.assertEqual(resumen['tardanzas'], 1)

    def test_panel_pendiente_antes_de_que_termine_el_bloque(self):
        crear_profesional('temprano', zona=self.zona)
        filas, _ = construir_panel(LUNES, local(LUNES, 7, 0))
        self.assertEqual(filas[0]['estado_dia'], 'pendiente')


# ══════════════════════════════════════════════════════════════════════════════
# VISTAS
# ══════════════════════════════════════════════════════════════════════════════

class VistasAdminTests(BaseAsistencia):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser('root', password='x')
        self.client.force_login(self.admin)

    def test_paginas_cargan(self):
        crear_profesional('rita', zona=self.zona, personalizado=True)
        for nombre in ['panel_admin', 'zonas_gps', 'horarios', 'asignaciones', 'fechas_especiales',
                       'enrolamiento', 'permisos']:
            r = self.client.get(reverse(f'asistencia:{nombre}'))
            self.assertEqual(r.status_code, 200, nombre)
        self.assertEqual(self.client.get(reverse('asistencia:panel_admin') + '?fecha=2026-10-05').status_code, 200)
        self.assertEqual(self.client.get(reverse('asistencia:panel_admin') + '?fecha=basura').status_code, 200)

    def test_zonas_y_mi_asistencia_cargan_sus_librerias_y_datos_validos(self):
        r = self.client.get(reverse('asistencia:zonas_gps'))
        self.assertContains(r, 'leaflet.js'); self.assertContains(r, 'zonas-data')
        self.assertNotContains(r, 'lat: -16,')                       # coma decimal rompería el JS
        self.assertContains(r, "referrerPolicy: 'strict-origin-when-cross-origin'")   # sin Referer OSM da 403
        self.assertNotContains(r, '{s}.tile.openstreetmap.org')
        crear_profesional('lib', zona=self.zona)
        self.client.force_login(User.objects.get(username='lib'))
        self.assertContains(self.client.get(reverse('asistencia:mi_asistencia')), 'chart.umd.min.js')

    def test_crear_horario_de_sabado_solo_manana_desde_la_interfaz(self):
        zona = ZonaAsistencia.objects.create(nombre='Nueva', latitud='-16.4', longitud='-68.1', radio_metros=80)
        url = reverse('asistencia:nueva_plantilla', args=[zona.pk])
        self.assertEqual(self.client.get(url).status_code, 200)

        # Lun-Vie partido
        r = self.client.post(url, {
            'nombre': 'Semana', 'dias': LUN_VIE, 'vigente_desde': '2026-01-01',
            'bloques-TOTAL_FORMS': 3, 'bloques-INITIAL_FORMS': 0, 'bloques-MIN_NUM_FORMS': 0, 'bloques-MAX_NUM_FORMS': 4,
            'bloques-0-hora_entrada': '08:00', 'bloques-0-hora_salida': '13:00', 'bloques-0-tolerancia_minutos': 10,
            'bloques-1-hora_entrada': '14:00', 'bloques-1-hora_salida': '18:00', 'bloques-1-tolerancia_minutos': 15,
            'bloques-2-hora_entrada': '', 'bloques-2-hora_salida': '', 'bloques-2-tolerancia_minutos': 10,
        })
        self.assertRedirects(r, reverse('asistencia:horarios'))
        # Sábado continuo
        r = self.client.post(url, {
            'nombre': 'Sábado', 'dias': ['SAB'], 'vigente_desde': '2026-01-01',
            'bloques-TOTAL_FORMS': 3, 'bloques-INITIAL_FORMS': 0, 'bloques-MIN_NUM_FORMS': 0, 'bloques-MAX_NUM_FORMS': 4,
            'bloques-0-hora_entrada': '08:00', 'bloques-0-hora_salida': '12:00', 'bloques-0-tolerancia_minutos': 5,
            'bloques-1-hora_entrada': '', 'bloques-1-hora_salida': '', 'bloques-1-tolerancia_minutos': 10,
            'bloques-2-hora_entrada': '', 'bloques-2-hora_salida': '', 'bloques-2-tolerancia_minutos': 10,
        })
        self.assertRedirects(r, reverse('asistencia:horarios'))
        semana = PlantillaHorario.objects.get(zona=zona, nombre='Semana')
        sab = PlantillaHorario.objects.get(zona=zona, nombre='Sábado')
        self.assertEqual(semana.dias, LUN_VIE)
        self.assertEqual(semana.bloques.count(), 2)
        self.assertEqual(list(semana.bloques.values_list('orden', flat=True)), [1, 2])
        self.assertEqual(sab.bloques.count(), 1)

    def _post_plantilla(self, url, dias, bloques):
        data = {'nombre': '', 'dias': dias, 'vigente_desde': '2026-10-01', 'bloques-TOTAL_FORMS': len(bloques),
                'bloques-INITIAL_FORMS': 0, 'bloques-MIN_NUM_FORMS': 0, 'bloques-MAX_NUM_FORMS': 4}
        for i, (e, s) in enumerate(bloques):
            data.update({f'bloques-{i}-hora_entrada': e, f'bloques-{i}-hora_salida': s, f'bloques-{i}-tolerancia_minutos': 10})
        return self.client.post(url, data)

    def test_validaciones_de_plantilla(self):
        url = reverse('asistencia:nueva_plantilla', args=[self.zona.pk])
        # día repetido en otra plantilla de la zona (el sábado ya existe)
        r = self._post_plantilla(url, ['SAB', 'DOM'], [('09:00', '10:00')])
        self.assertEqual(r.status_code, 200); self.assertContains(r, 'ya está en el horario')
        # sin bloques
        r = self._post_plantilla(url, ['DOM'], [('', '')])
        self.assertEqual(r.status_code, 200); self.assertContains(r, 'al menos un bloque')
        # salida antes que entrada
        r = self._post_plantilla(url, ['DOM'], [('10:00', '09:00')])
        self.assertEqual(r.status_code, 200); self.assertContains(r, 'posterior')
        # bloques solapados
        r = self._post_plantilla(url, ['DOM'], [('08:00', '12:00'), ('11:00', '15:00')])
        self.assertEqual(r.status_code, 200); self.assertContains(r, 'se solapan')
        # sin días
        r = self._post_plantilla(url, [], [('08:00', '12:00')])
        self.assertEqual(r.status_code, 200); self.assertContains(r, 'al menos un día')
        self.assertEqual(PlantillaHorario.objects.filter(zona=self.zona).count(), 2)

    def test_editar_y_finalizar_plantilla(self):
        url = reverse('asistencia:editar_plantilla', args=[self.p_sabado.pk])
        r = self.client.get(url)
        self.assertContains(r, 'Sábado'); self.assertContains(r, 'Aplicar desde')
        # «Eliminar» ahora FINALIZA desde una fecha: el horario sigue existiendo para los días anteriores
        r = self.client.post(reverse('asistencia:eliminar_plantilla', args=[self.p_sabado.pk]), {'desde': '2026-10-01'})
        self.assertRedirects(r, reverse('asistencia:horarios'))
        self.p_sabado.refresh_from_db()
        self.assertEqual(self.p_sabado.vigente_hasta, dt.date(2026, 9, 30))
        # uno que nunca llegó a regir sí se borra
        futura = crear_plantilla(self.zona, ['DOM'], [(T(8), T(12), 10)])
        futura.vigente_desde = timezone.localdate() + dt.timedelta(days=30); futura.save()
        self.client.post(reverse('asistencia:eliminar_plantilla', args=[futura.pk]), {})
        self.assertFalse(PlantillaHorario.objects.filter(pk=futura.pk).exists())

    def test_activar_horario_propio_copia_el_de_la_zona(self):
        u = crear_profesional('sofi')
        r = self.client.post(reverse('asistencia:asignaciones'), {
            'user': u.pk, 'zona': self.zona.pk, 'personalizado': 'on', 'device_id': ''})
        self.assertRedirects(r, reverse('asistencia:asignaciones'))
        propias = PlantillaHorario.objects.filter(zona=self.zona, user=u)
        self.assertEqual(propias.count(), 2)                         # Lun-Vie y Sábado copiados
        cfg = ConfigAsistencia.objects.get(user=u)
        self.assertEqual(self.client.get(reverse('asistencia:editar_config', args=[cfg.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('asistencia:nueva_plantilla_personal', args=[cfg.pk])).status_code, 200)
        # eliminar asignación borra también sus plantillas personales
        self.client.post(reverse('asistencia:eliminar_config', args=[cfg.pk]))
        self.assertEqual(PlantillaHorario.objects.filter(zona=self.zona, user=u).count(), 0)
        self.assertEqual(PlantillaHorario.objects.filter(zona=self.zona, user__isnull=True).count(), 2)

    def test_fecha_especial_con_dos_bloques_y_dia_libre(self):
        url = reverse('asistencia:fechas_especiales')
        base = {'zona': self.zona.pk, 'tipo_horario': 'horario', 'motivo': 'Víspera',
                'bloques-TOTAL_FORMS': 3, 'bloques-INITIAL_FORMS': 0, 'bloques-MIN_NUM_FORMS': 0, 'bloques-MAX_NUM_FORMS': 4}
        r = self.client.post(url, {**base, 'fecha': '2026-12-24',
            'bloques-0-hora_entrada': '08:00', 'bloques-0-hora_salida': '12:00', 'bloques-0-tolerancia_minutos': 5,
            'bloques-1-hora_entrada': '15:00', 'bloques-1-hora_salida': '17:00', 'bloques-1-tolerancia_minutos': 5,
            'bloques-2-hora_entrada': '', 'bloques-2-hora_salida': '', 'bloques-2-tolerancia_minutos': 10})
        self.assertRedirects(r, url)
        fe = FechaEspecial.objects.get(fecha=dt.date(2026, 12, 24))
        self.assertEqual(fe.bloques.count(), 2)
        # día libre: no exige bloques
        r = self.client.post(url, {'zona': self.zona.pk, 'tipo_horario': 'libre', 'fecha': '2026-12-25', 'motivo': 'Navidad',
                                   'bloques-TOTAL_FORMS': 3, 'bloques-INITIAL_FORMS': 0,
                                   'bloques-MIN_NUM_FORMS': 0, 'bloques-MAX_NUM_FORMS': 4})
        self.assertRedirects(r, url)
        self.assertEqual(FechaEspecial.objects.get(fecha=dt.date(2026, 12, 25)).bloques.count(), 0)
        # horario sin bloques → error
        r = self.client.post(url, {**base, 'fecha': '2026-12-26',
            'bloques-0-hora_entrada': '', 'bloques-0-hora_salida': '', 'bloques-0-tolerancia_minutos': 10,
            'bloques-1-hora_entrada': '', 'bloques-1-hora_salida': '', 'bloques-1-tolerancia_minutos': 10,
            'bloques-2-hora_entrada': '', 'bloques-2-hora_salida': '', 'bloques-2-tolerancia_minutos': 10})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(FechaEspecial.objects.filter(fecha=dt.date(2026, 12, 26)).exists())
        self.assertContains(self.client.get(url), '08:00–12:00')

    def test_marcar_admin_y_permiso_de_reenrolamiento(self):
        u = crear_profesional('tina', zona=self.zona)
        r = self.client.post(reverse('asistencia:marcar_admin', args=[u.pk]), {'tipo': 'ENTRADA', 'observacion': 'x'})
        self.assertRedirects(r, reverse('asistencia:panel_admin'))
        self.assertEqual(u.registros_asistencia.filter(estado__in=['PUNTUAL', 'TARDANZA']).count(), 1)
        # segundo ENTRADA seguido: rechazado
        self.client.post(reverse('asistencia:marcar_admin', args=[u.pk]), {'tipo': 'ENTRADA'})
        self.assertEqual(u.registros_asistencia.filter(tipo='ENTRADA').count(), 1)
        # GET no marca
        self.assertEqual(self.client.get(reverse('asistencia:marcar_admin', args=[u.pk])).status_code, 405)
        # permiso a profesional ya enrolado: sigue enrolado pero puede re-enrolar
        enrol = u.enrolamiento
        self.client.post(reverse('asistencia:desbloquear', args=[enrol.pk]), {'enrolamiento_id': enrol.pk, 'motivo': 'nuevo look'})
        enrol.refresh_from_db()
        self.assertEqual(enrol.estado, 'enrolado'); self.assertTrue(enrol.puede_enrolar())

    def test_permiso_a_bloqueado_lo_deja_pendiente(self):
        u = crear_profesional('ugo')
        enrol = u.enrolamiento
        enrol.estado = 'bloqueado'; enrol.intentos_fallidos = 5; enrol.save()
        self.client.post(reverse('asistencia:desbloquear', args=[enrol.pk]), {'enrolamiento_id': enrol.pk, 'motivo': 'ok'})
        enrol.refresh_from_db()
        self.assertEqual((enrol.estado, enrol.intentos_fallidos), ('pendiente', 0))

    def test_profesional_no_accede_al_panel_admin(self):
        u = crear_profesional('vero', zona=self.zona)
        self.client.force_login(u)
        r = self.client.get(reverse('asistencia:panel_admin'))
        self.assertEqual(r.status_code, 302)


class VistasProfesionalTests(BaseAsistencia):
    def setUp(self):
        super().setUp()
        self.u = crear_profesional('walter', zona=self.zona)
        self.client.force_login(self.u)

    def test_marcar_get_muestra_horario_y_mapa_seguro(self):
        r = self.client.get(reverse('asistencia:marcar'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'zonas-data')                         # json_script (sin números con coma decimal)
        self.assertContains(r, 'asistencia/face/face-api.js')
        self.assertContains(r, 'asistencia/face/facial.js')
        self.assertContains(r, 'leaflet.js')
        self.assertContains(r, 'leaflet.css')
        self.assertNotContains(r, 'lat: -16,5')

    def test_marcar_get_sin_enrolar_pide_enrolamiento(self):
        v = crear_profesional('xavi', enrolado=False, zona=self.zona)
        self.client.force_login(v)
        r = self.client.get(reverse('asistencia:marcar'))
        self.assertContains(r, 'registra tu rostro')
        self.assertNotContains(r, 'btn-entrada')

    def test_post_ajax_marcar_ok_y_duplicado(self):
        datos = dict(tipo='ENTRADA', latitud='-16.500000', longitud='-68.150000', precision='12',
                     vector_facial=json.dumps(cercano(ROSTRO_A, seed=5)), device_id='d1', observacion='ok')
        hdr = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}
        r = self.client.post(reverse('asistencia:marcar'), datos, **hdr)
        self.assertEqual(r.status_code, 200); self.assertTrue(r.json()['aprobado'])
        r = self.client.post(reverse('asistencia:marcar'), datos, **hdr)
        self.assertEqual(r.status_code, 403); self.assertFalse(r.json()['aprobado'])
        self.assertEqual(self.u.registros_asistencia.filter(tipo='ENTRADA', estado__in=['PUNTUAL', 'TARDANZA']).count(), 1)

    def test_post_con_datos_invalidos_devuelve_400_json(self):
        r = self.client.post(reverse('asistencia:marcar'), dict(tipo='ENTRADA', latitud='abc', longitud='1',
                             vector_facial='{no es json'), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r.status_code, 400); self.assertFalse(r.json()['aprobado'])

    def test_mi_asistencia_tolera_parametros_invalidos(self):
        url = reverse('asistencia:mi_asistencia')
        for q in ['?mes=13', '?mes=0', '?mes=abc', '?anio=99999', '?mes=2&anio=x', '?mes=-1']:
            self.assertEqual(self.client.get(url + q).status_code, 200, q)
        self.assertContains(self.client.get(url + '?mes=3&anio=2026'), 'Mar')

    def test_mi_asistencia_cuenta_dias_y_bloques(self):
        for hora, estado, bloque in [(8, 'PUNTUAL', '1'), (14, 'TARDANZA', '2')]:
            RegistroAsistencia.objects.create(user=self.u, tipo='ENTRADA', estado=estado, bloque=bloque,
                                              minutos_tardanza=20 if estado == 'TARDANZA' else 0,
                                              segundos_tarde=1200 if estado == 'TARDANZA' else 0,
                                              segundos_acumulables=600 if estado == 'TARDANZA' else 0,
                                              fecha_hora=local(LUNES, hora))
        RegistroAsistencia.objects.create(user=self.u, tipo='ENTRADA', estado='AUSENTE', bloque='1',
                                          fecha_hora=local(LUNES + dt.timedelta(days=1), 13))
        r = self.client.get(reverse('asistencia:mi_asistencia') + '?mes=10&anio=2026')
        self.assertEqual((r.context['presentes'], r.context['tardanzas'], r.context['ausentes'],
                          r.context['acum_seg']), (1, 1, 1, 600))          # 20 min tarde - 10 de tolerancia = 10 min

    def test_enrolamiento_por_post(self):
        v = crear_profesional('yani', enrolado=False)
        self.client.force_login(v)
        self.assertEqual(self.client.get(reverse('asistencia:enrolamiento_facial')).status_code, 200)
        # datos malos
        r = self.client.post(reverse('asistencia:enrolamiento_facial'), {'vector_facial': '[[1,2,3]]'})
        self.assertRedirects(r, reverse('asistencia:enrolamiento_facial'))
        v.enrolamiento.refresh_from_db(); self.assertEqual(v.enrolamiento.estado, 'pendiente')
        # datos buenos
        r = self.client.post(reverse('asistencia:enrolamiento_facial'),
                             {'vector_facial': json.dumps([cercano(ROSTRO_A, seed=i) for i in range(5)])})
        self.assertRedirects(r, reverse('asistencia:mi_asistencia'))
        v.enrolamiento.refresh_from_db(); self.assertEqual(v.enrolamiento.estado, 'enrolado')
        # ya enrolada: no puede sobrescribir sin permiso
        r = self.client.post(reverse('asistencia:enrolamiento_facial'),
                             {'vector_facial': json.dumps([cercano(ROSTRO_B, seed=i) for i in range(5)])})
        v.enrolamiento.refresh_from_db()
        self.assertAlmostEqual(v.enrolamiento.vector_facial[0][0], cercano(ROSTRO_A, seed=0)[0], places=1)

    def test_editar_observacion_solo_el_mismo_dia(self):
        viejo = RegistroAsistencia.objects.create(user=self.u, tipo='ENTRADA', estado='PUNTUAL',
                                                  fecha_hora=timezone.now() - dt.timedelta(days=3))
        r = self.client.post(reverse('asistencia:editar_observacion', args=[viejo.pk]), {'observacion': 'x'})
        self.assertRedirects(r, reverse('asistencia:mi_asistencia'))
        viejo.refresh_from_db(); self.assertEqual(viejo.observacion, '')
        hoy = RegistroAsistencia.objects.create(user=self.u, tipo='ENTRADA', estado='PUNTUAL')
        self.client.post(reverse('asistencia:editar_observacion', args=[hoy.pk]), {'observacion': 'tráfico'})
        hoy.refresh_from_db(); self.assertEqual(hoy.observacion, 'tráfico')


# ══════════════════════════════════════════════════════════════════════════════
# INTEGRACIÓN: el reporte del profesional (facturacion) lee los horarios de asistencia
# ══════════════════════════════════════════════════════════════════════════════

class IntegracionReporteProfesionalTests(BaseAsistencia):
    """facturacion.reporte_profesional_data depende de la forma en que asistencia expone horarios."""

    def setUp(self):
        super().setUp()
        from profesionales.models import Profesional
        self.user = crear_profesional('rep', zona=self.zona)
        self.prof = Profesional.objects.create(
            user=self.user, nombre='Rep', apellido='Orte', especialidad='Psicología')

    def _horario(self, desde, hasta):
        from facturacion.reporte_profesional_data import HORARIO_DEFAULT, preparar_horario
        return preparar_horario(self.prof, '', desde, hasta, dict(HORARIO_DEFAULT), False)

    def test_bloques_por_dia_en_minutos_respetan_semana_partida_y_sabado_corto(self):
        bloques, info = self._horario(LUNES, LUNES + dt.timedelta(days=6))
        self.assertEqual(info['fuente'], 'asistencia')
        self.assertEqual(bloques(LUNES), [(8 * 60, 13 * 60), (14 * 60, 18 * 60)])
        self.assertEqual(bloques(SABADO), [(8 * 60, 12 * 60)])        # sábado solo mañana, 08–12
        self.assertEqual(bloques(DOMINGO), [])
        semana = {s['dia']: s['bloques'] for s in info['semana']}
        self.assertEqual(len(semana['Lunes']), 2)
        self.assertEqual(len(semana['Sábado']), 1)

    def test_horario_propio_y_fechas_especiales_llegan_al_reporte(self):
        ConfigAsistencia.objects.filter(user=self.user).update(personalizado=True)
        crear_plantilla(self.zona, ['LUN'], [(T(9), T(15), 0)], user=self.user)
        FechaEspecial.objects.create(zona=self.zona, fecha=SABADO, tipo_horario='libre', motivo='Feriado')
        bloques, info = self._horario(LUNES, SABADO)
        self.assertEqual(bloques(LUNES), [(9 * 60, 15 * 60)])
        self.assertEqual(bloques(LUNES + dt.timedelta(days=1)), [])    # no está en su horario propio
        self.assertEqual(bloques(SABADO), [])                          # feriado
        self.assertEqual([e['motivo'] for e in info['especiales']], ['Feriado'])

    def test_sin_config_usa_horario_de_la_zona_de_su_sucursal(self):
        from servicios.models import Sucursal
        ConfigAsistencia.objects.filter(user=self.user).delete()
        suc = Sucursal.objects.create(nombre='Central')
        self.zona.sucursal = suc; self.zona.save()
        self.prof.sucursales.add(suc)
        bloques, info = self._horario(LUNES, LUNES)
        self.assertEqual(info['fuente'], 'asistencia')
        self.assertEqual(bloques(LUNES), [(8 * 60, 13 * 60), (14 * 60, 18 * 60)])

    def test_sin_horarios_en_asistencia_cae_al_predeterminado(self):
        PlantillaHorario.objects.all().delete()
        bloques, info = self._horario(LUNES, LUNES)
        self.assertEqual(info['fuente'], 'predeterminado')
        self.assertTrue(bloques(LUNES))

    def test_fecha_especial_con_profesionales_y_usuario_nulo_no_falla(self):
        fe = FechaEspecial.objects.create(zona=self.zona, fecha=LUNES, tipo_horario='libre')
        fe.profesionales.add(self.user)
        self.assertFalse(fe.aplica_a_user(None))
        self.assertTrue(fe.aplica_a_user(self.user))

    def test_analizar_completo_no_falla_y_marcaje_soporta_varias_jornadas(self):
        from facturacion.reporte_profesional_data import analizar
        self.marcar(self.user, 'ENTRADA', local(LUNES, 8, 5)); self.marcar(self.user, 'SALIDA', local(LUNES, 13, 0))
        self.marcar(self.user, 'ENTRADA', local(LUNES, 14, 20)); self.marcar(self.user, 'SALIDA', local(LUNES, 18, 0))
        r = analizar(self.prof, LUNES, LUNES + dt.timedelta(days=6), hoy=LUNES + dt.timedelta(days=7))
        m = r['marcaje']
        self.assertTrue(m['disponible'])
        self.assertEqual(m['entradas'], 2)                      # los dos bloques del día cuentan
        self.assertEqual(m['presencia_min'], 295 + 220)         # 08:05→13:00 y 14:20→18:00
        self.assertEqual(m['dias_marcados'], 1)

    def test_pagina_y_pdf_del_reporte_con_horarios_y_marcajes_de_asistencia(self):
        """Recorre la vista real (HTML y PDF) con horarios multi-bloque y marcajes de varias jornadas."""
        self.marcar(self.user, 'ENTRADA', local(LUNES, 8, 5)); self.marcar(self.user, 'SALIDA', local(LUNES, 13, 0))
        self.marcar(self.user, 'ENTRADA', local(LUNES, 14, 20)); self.marcar(self.user, 'SALIDA', local(LUNES, 18, 0))
        admin = User.objects.create_superuser('rootrep', password='x')
        self.client.force_login(admin)
        url = reverse('facturacion:reporte_profesional')
        params = {'profesional': self.prof.pk, 'fecha_desde': '2026-10-05', 'fecha_hasta': '2026-10-11', 'rango': 'personalizado'}
        r = self.client.get(url, params)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Horario configurado en Asistencia')
        r = self.client.get(url, {**params, 'export': 'pdf'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(r.content.startswith(b'%PDF'))



# ══════════════════════════════════════════════════════════════════════════════
# REGLAS DE RETRASO: tolerancia al segundo, límite para marcar, acumulado y descuento
# ══════════════════════════════════════════════════════════════════════════════

def local_s(fecha, hora, minuto=0, segundo=0):
    return timezone.make_aware(dt.datetime.combine(fecha, T(hora, minuto, segundo)))


class ToleranciaAlSegundoTests(BaseAsistencia):
    """Tolerancia 10: hasta 10 min con 0 s es puntual; 10 min con 1 s ya es retraso."""

    def setUp(self):
        super().setUp()
        self.h = self.horario(crear_profesional('tol', zona=self.zona), LUNES)       # bloque 1: 08:00, tolerancia 10

    def calc(self, h, m, sg):
        return CalculadorEstado(self.h, local_s(LUNES, h, m, sg)).calcular()

    def test_el_limite_es_10_minutos_con_0_segundos(self):
        self.assertEqual(self.calc(8, 9, 59), ('PUNTUAL', '1', 0))
        self.assertEqual(self.calc(8, 10, 0), ('PUNTUAL', '1', 0))
        self.assertEqual(self.calc(8, 10, 1)[0], 'TARDANZA')               # 10 min con 1 s ya es retraso

    def test_se_acumulan_minutos_completos_desde_la_hora_de_entrada(self):
        self.assertEqual(self.calc(8, 10, 1), ('TARDANZA', '1', 10))       # 10 min completos (los segundos no suman)
        self.assertEqual(self.calc(8, 10, 59), ('TARDANZA', '1', 10))
        self.assertEqual(self.calc(8, 11, 0), ('TARDANZA', '1', 11))       # 08:11 = 11 min acumulados
        self.assertEqual(self.calc(8, 25, 59), ('TARDANZA', '1', 25))

    def test_el_retraso_se_cuenta_desde_la_entrada_no_desde_el_exceso(self):
        self.assertEqual(self.calc(8, 15, 0)[2], 15)                       # 15, no 5

    def test_llegar_antes_es_puntual(self):
        self.assertEqual(self.calc(7, 50, 0), ('PUNTUAL', '1', 0))

    def test_microsegundos_no_cuentan(self):
        ahora = local_s(LUNES, 8, 10, 0) + dt.timedelta(microseconds=900000)
        self.assertEqual(CalculadorEstado(self.h, ahora).calcular()[0], 'PUNTUAL')

    def test_tolerancia_cero(self):
        PlantillaHorario.objects.all().delete()
        crear_plantilla(self.zona, LUN_VIE, [(T(8), T(12), 0)])
        h = self.horario(User.objects.get(username='tol'), LUNES)
        self.assertEqual(CalculadorEstado(h, local_s(LUNES, 8, 0, 0)).calcular()[0], 'PUNTUAL')
        self.assertEqual(CalculadorEstado(h, local_s(LUNES, 8, 0, 1)).calcular(), ('TARDANZA', '1', 0))

    def test_marcado_real_a_las_08_10_01_es_tardanza(self):
        ok, r, _ = self.marcar(User.objects.get(username='tol'), 'ENTRADA', local_s(LUNES, 8, 10, 1))
        self.assertTrue(ok); self.assertEqual((r.estado, r.minutos_tardanza), ('TARDANZA', 10))


class LimiteParaMarcarTests(BaseAsistencia):
    """Opcional: pasado el límite de retraso ya no se puede marcar y el bloque cuenta como falta."""

    def setUp(self):
        super().setUp()
        PlantillaHorario.objects.all().delete()
        crear_plantilla(self.zona, LUN_VIE, [(T(8), T(13), 10, 30), (T(14), T(18), 10)])    # bloque 1 con límite 30
        self.u = crear_profesional('lim', zona=self.zona)

    def test_se_puede_marcar_hasta_el_limite_exacto_con_0_segundos(self):
        ok, r, _ = self.marcar(self.u, 'ENTRADA', local_s(LUNES, 8, 30, 0))
        self.assertTrue(ok)
        self.assertEqual((r.estado, r.bloque, r.minutos_tardanza), ('TARDANZA', '1', 30))

    def test_un_segundo_despues_del_limite_ya_no_deja_marcar(self):
        ok, r, errores = self.marcar(self.u, 'ENTRADA', local_s(LUNES, 8, 30, 1))
        self.assertFalse(ok)
        self.assertIsNone(r)                                            # no se crea registro de entrada
        self.assertIn('límite', errores[0]); self.assertIn('08:30', errores[0]); self.assertIn('falta', errores[0])
        self.assertEqual(RegistroAsistencia.objects.count(), 0)
        self.u.enrolamiento.refresh_from_db()
        self.assertEqual(self.u.enrolamiento.intentos_fallidos, 0)       # no penaliza el reconocimiento facial

    def test_el_limite_aplica_por_bloque_y_la_tarde_sin_limite_sigue_funcionando(self):
        self.assertFalse(self.marcar(self.u, 'ENTRADA', local(LUNES, 9, 0))[0])           # bloque 1 vencido
        ok, r, _ = self.marcar(self.u, 'ENTRADA', local(LUNES, 15, 0))                    # bloque 2 sin límite
        self.assertTrue(ok); self.assertEqual((r.estado, r.bloque, r.minutos_tardanza), ('TARDANZA', '2', 60))

    def test_reentrada_en_bloque_ya_cubierto_no_se_bloquea(self):
        self.marcar(self.u, 'ENTRADA', local(LUNES, 8, 0)); self.marcar(self.u, 'SALIDA', local(LUNES, 9, 0))
        ok, r, _ = self.marcar(self.u, 'ENTRADA', local(LUNES, 11, 0))                    # mucho después del límite
        self.assertTrue(ok); self.assertEqual((r.estado, r.bloque), ('PUNTUAL', ''))

    def test_la_falta_se_genera_justo_al_vencer_el_limite_no_al_final_del_bloque(self):
        self.assertEqual(generar_ausentes(LUNES, local_s(LUNES, 8, 30, 0)), 0)            # aún puede marcar
        self.assertEqual(generar_ausentes(LUNES, local_s(LUNES, 8, 30, 1)), 1)            # venció: falta
        a = RegistroAsistencia.objects.get(estado='AUSENTE')
        self.assertEqual((a.bloque, timezone.localtime(a.fecha_hora).strftime('%H:%M:%S')), ('1', '08:30:01'))
        self.assertEqual(generar_ausentes(LUNES, local(LUNES, 9, 0)), 0)                  # idempotente

    def test_el_panel_muestra_ausente_al_vencer_el_limite(self):
        filas, _ = construir_panel(LUNES, local(LUNES, 8, 20))
        self.assertEqual(filas[0]['estado_dia'], 'pendiente')
        filas, _ = construir_panel(LUNES, local(LUNES, 8, 45))
        self.assertEqual(filas[0]['estado_dia'], 'ausente')

    def test_el_admin_puede_registrar_a_mano_y_se_anula_la_falta(self):
        admin = User.objects.create_superuser('admlim', password='x')
        generar_ausentes(LUNES, local(LUNES, 9, 0))
        self.assertEqual(RegistroAsistencia.objects.filter(estado='AUSENTE', bloque='1').count(), 1)
        ok, r, _ = registrar_manual(self.u, 'ENTRADA', admin, 'Autorizado', ahora=local(LUNES, 9, 30))
        self.assertTrue(ok); self.assertEqual((r.estado, r.bloque, r.minutos_tardanza), ('TARDANZA', '1', 90))
        self.assertEqual(RegistroAsistencia.objects.filter(estado='AUSENTE', bloque='1').count(), 0)

    def test_sin_limite_nunca_se_bloquea(self):
        ok, r, _ = self.marcar(self.u, 'ENTRADA', local(LUNES, 14, 0))
        self.assertTrue(ok)                                # bloque 2 (sin límite)
        self.assertEqual(self.horario(self.u, LUNES).bloques[1].cierre_marcado(LUNES), local(LUNES, 18, 0))

    def test_el_limite_no_pasa_del_fin_del_bloque(self):
        PlantillaHorario.objects.all().delete()
        crear_plantilla(self.zona, LUN_VIE, [(T(8), T(9), 10, 500)])
        b = self.horario(self.u, LUNES).bloques[0]
        self.assertEqual(b.cierre_marcado(LUNES), local(LUNES, 9, 0))


class TramosDescuentoTests(TestCase):
    """Conversión del retraso acumulado (segundos) en días de descuento por tramos."""
    TR = [(1800, 0), (2700, 0.5), (3600, 1), (5400, 2), (None, 3)]          # 30 / 45 / 60 / 90 min, más de 90 -> 3

    def test_limites_exactos_de_los_tramos(self):
        esperado = {0: 0, 1: 0, 1800: 0,          # hasta 30:00 no se descuenta nada
                    1801: 0.5, 2700: 0.5,         # 30:01 a 45:00 -> medio día
                    2701: 1, 3600: 1,             # 45:01 a 60:00 -> un día
                    3601: 2, 5400: 2,             # 60:01 a 90:00 -> dos días
                    5401: 3, 99999: 3}            # desde 90:01 en adelante -> tres días
        for seg, dias in esperado.items():
            self.assertEqual(dias_descuento(seg, self.TR), dias, seg)

    def test_sin_tramos_no_hay_descuento(self):
        self.assertEqual(dias_descuento(5000, []), 0)

    def test_solo_un_tramo_sin_tope(self):
        self.assertEqual(dias_descuento(10, [(None, 2)]), 2)

    def test_sin_tramo_final_se_mantiene_el_ultimo(self):
        self.assertEqual(dias_descuento(99999, [(1800, 0), (3600, 1)]), 1)

    def test_segundos_que_faltan_para_el_siguiente_tramo(self):
        casos = {0: 1801, 1200: 601, 1800: 1, 1801: 900, 2700: 1, 3600: 1, 5400: 1, 5401: None}
        for seg, falta in casos.items():
            self.assertEqual(segundos_para_proximo_tramo(seg, self.TR), falta, seg)
        self.assertIsNone(segundos_para_proximo_tramo(5, []))

    def test_retraso_maximo_sin_descuento(self):
        self.assertEqual(segundos_sin_descuento(self.TR), 1800)
        self.assertIsNone(segundos_sin_descuento([(None, 0)]))                    # nunca hay descuento
        self.assertIsNone(segundos_sin_descuento([(1800, 0.5), (None, 1)]))       # sin tramo gratuito
        self.assertIsNone(segundos_sin_descuento([]))

    def test_texto_de_los_tramos(self):
        self.assertEqual(texto_tramos(self.TR),
                         'hasta 30 min: sin descuento · 30–45 min: medio día · 45–60 min: 1 día · '
                         '60–90 min: 2 días · más de 90 min: 3 días')

    def test_formato_minutos_segundos(self):
        self.assertEqual((fmt_min_seg(0), fmt_min_seg(7), fmt_min_seg(90), fmt_min_seg(1620), fmt_min_seg(7260)),
                         ('0:00', '0:07', '1:30', '27:00', '121:00'))


class ReglasAsistenciaTests(BaseAsistencia):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser('rootreg', password='x')
        self.client.force_login(self.admin)
        self.hoy = timezone.localdate()

    def guardar(self, filas=None, resto=3, mes=None, anio=None, follow=False):
        """Guarda una versión. Por defecto rige desde el MES EN CURSO (así se ve en 'vigente hoy')."""
        return self.client.post(reverse('asistencia:reglas'), datos_reglas(
            TRAMOS_DEF if filas is None else filas, resto, mes or self.hoy.month, anio or self.hoy.year), follow=follow)

    def test_sin_reglas_guardadas_obtener_devuelve_instancia_vacia_sin_crear(self):
        r = ReglasAsistencia.obtener()
        self.assertEqual((r.pk, r.tramos_lista(), r.hay_descuento), (None, [], False))
        self.assertEqual(ReglasAsistencia.objects.count(), 0)
        self.assertIsNone(ReglasAsistencia.para_mes(2026, 10))

    def test_guardar_con_la_misma_fecha_actualiza_esa_version(self):
        ReglasAsistencia().save(); ReglasAsistencia().save()
        self.assertEqual(ReglasAsistencia.objects.count(), 1)

    def test_si_no_hay_reglas_la_pantalla_sugiere_los_tramos(self):
        r = self.client.get(reverse('asistencia:reglas'))
        iniciales = [(float(f.initial['hasta']), float(f.initial['dias'])) for f in r.context['formset'].forms if f.initial]
        self.assertEqual(iniciales, [(30, 0), (45, 0.5), (60, 1), (90, 2)])
        self.assertEqual(float(r.context['form'].initial['dias_resto']), 3)
        self.assertContains(r, 'Todavía no hay reglas guardadas')

    def test_pagina_guarda_una_version_con_sus_tramos_y_avisa_si_es_el_mes_en_curso(self):
        url = reverse('asistencia:reglas')
        r = self.guardar(follow=True)
        self.assertRedirects(r, url)
        g = ReglasAsistencia.obtener()
        self.assertEqual(g.tramos_lista(), [(1800, 0), (2700, 0.5), (3600, 1), (5400, 2), (None, 3)])
        self.assertEqual((g.modificado_por, g.vigente_desde), (self.admin, self.hoy.replace(day=1)))
        self.assertTrue(any('mes en curso' in str(m) for m in r.context['messages']))
        self.assertTrue(g.hay_descuento)

    def test_por_defecto_se_propone_el_mes_siguiente(self):
        r = self.client.get(reverse('asistencia:reglas'))
        siguiente = (self.hoy.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        self.assertEqual((r.context['form'].initial['mes'], r.context['form'].initial['anio']),
                         (siguiente.month, siguiente.year))

    def test_los_topes_aceptan_decimales(self):
        self.guardar(filas=[(30, 0), (45.5, 0.5)], resto=1)
        self.assertEqual(ReglasAsistencia.obtener().tramos_lista(), [(1800, 0), (2730, 0.5), (None, 1)])

    def test_se_pueden_dejar_filas_vacias_y_un_solo_tramo(self):
        self.assertEqual(self.guardar(filas=[], resto=0).status_code, 302)           # solo «más allá» = 0: sin descuento
        self.assertFalse(ReglasAsistencia.obtener().hay_descuento)
        self.assertEqual(self.guardar(filas=[(60, 0)], resto=1).status_code, 302)
        self.assertEqual(ReglasAsistencia.obtener().tramos_lista(), [(3600, 0), (None, 1)])

    def test_validaciones_de_los_tramos(self):
        casos = {
            'tope repetido': self.guardar(filas=[(30, 0), (30, 1)]),
            'el descuento baja': self.guardar(filas=[(30, 1), (45, 0.5)]),
            'fila a medias': self.guardar(filas=[(30, '')]),
            'resto menor que el último tramo': self.guardar(filas=[(30, 0), (45, 2)], resto=1),
            'mes inválido': self.guardar(mes=13),
        }
        for nombre, r in casos.items():
            self.assertEqual(r.status_code, 200, nombre)
        self.assertEqual(ReglasAsistencia.objects.count(), 0)

    def test_la_pagina_muestra_la_tabla_de_ejemplo_con_lo_vigente(self):
        self.guardar()
        r = self.client.get(reverse('asistencia:reglas'))
        ej = dict(r.context['ejemplos'])
        self.assertEqual((ej['15:00'], ej['30:00'], ej['30:01'], ej['45:00'], ej['45:01']), (0, 0, 0.5, 0.5, 1))
        self.assertEqual((ej['60:00'], ej['60:01'], ej['90:00'], ej['90:01']), (1, 2, 2, 3))
        self.assertContains(r, 'medio día')

    def test_solo_admin(self):
        u = crear_profesional('noadm', zona=self.zona)
        self.client.force_login(u)
        self.assertEqual(self.client.get(reverse('asistencia:reglas')).status_code, 302)
        self.assertEqual(self.guardar().status_code, 302)
        self.assertEqual(ReglasAsistencia.objects.count(), 0)

    def test_editor_de_horarios_guarda_el_limite_y_valida_contra_tolerancia(self):
        url = reverse('asistencia:nueva_plantilla', args=[self.zona.pk])
        def post(tol, limite, dias=['DOM']):
            return self.client.post(url, {'nombre': '', 'dias': dias, 'vigente_desde': '2026-10-01',
                'bloques-TOTAL_FORMS': 1, 'bloques-INITIAL_FORMS': 0, 'bloques-MIN_NUM_FORMS': 0, 'bloques-MAX_NUM_FORMS': 4,
                'bloques-0-hora_entrada': '08:00', 'bloques-0-hora_salida': '12:00',
                'bloques-0-tolerancia_minutos': tol, 'bloques-0-max_retraso_minutos': limite})
        r = post(10, 5)                                      # límite menor que la tolerancia
        self.assertEqual(r.status_code, 200); self.assertContains(r, 'no puede ser menor que la tolerancia')
        self.assertEqual(post(10, 60).status_code, 302)
        self.assertEqual(BloqueHorario.objects.get(plantilla__dias=['DOM']).max_retraso_minutos, 60)
        self.assertContains(self.client.get(reverse('asistencia:horarios')), 'límite +60m')

    def test_limite_en_fecha_especial_y_horario_propio_se_copia(self):
        fe = FechaEspecial.objects.create(zona=self.zona, fecha=LUNES, tipo_horario='horario')
        BloqueFechaEspecial.objects.create(fecha_especial=fe, orden=1, hora_entrada=T(9), hora_salida=T(12),
                                           tolerancia_minutos=5, max_retraso_minutos=20)
        u = crear_profesional('fes', zona=self.zona)
        self.assertEqual(self.horario(u, LUNES).bloques[0].max_retraso, 20)
        # al activar "horario propio" se copia el límite de la zona (el horario de la zona rige desde siempre)
        PlantillaHorario.objects.filter(zona=self.zona).delete()
        crear_plantilla(self.zona, ['MAR'], [(T(8), T(12), 10, 45)])
        self.client.post(reverse('asistencia:editar_config', args=[ConfigAsistencia.objects.get(user=u).pk]),
                         {'user': u.pk, 'zona': self.zona.pk, 'personalizado': 'on', 'device_id': '',
                          'aplicar_desde': '2026-01-01'})
        self.assertEqual(BloqueHorario.objects.get(plantilla__user=u).max_retraso_minutos, 45)


class AcumuladoMensualTests(BaseAsistencia):
    def crear(self, u, fecha, hora, acum_seg, estado='TARDANZA'):
        return RegistroAsistencia.objects.create(
            user=u, tipo='ENTRADA', estado=estado, bloque='1', minutos_tardanza=(acum_seg + 600) // 60,
            segundos_tarde=acum_seg + 600, segundos_acumulables=acum_seg, fecha_hora=local(fecha, hora))

    def test_suma_solo_el_mes_y_hasta_la_fecha_indicada(self):
        u = crear_profesional('acu', zona=self.zona); otro = crear_profesional('acu2', zona=self.zona)
        self.crear(u, dt.date(2026, 9, 30), 8, 5940)                     # mes anterior: no cuenta
        self.crear(u, dt.date(2026, 10, 1), 8, 720)
        self.crear(u, dt.date(2026, 10, 5), 8, 900)
        self.crear(u, dt.date(2026, 10, 5), 14, 0, estado='PUNTUAL')     # puntual: no suma
        self.crear(u, dt.date(2026, 10, 20), 8, 2400)                    # posterior a la fecha de consulta
        self.crear(otro, dt.date(2026, 10, 2), 8, 420)
        acum = segundos_acumulados_mes(dt.date(2026, 10, 5))
        self.assertEqual(acum[u.pk], 1620)                               # 12:00 + 15:00 = 27:00
        self.assertEqual(acum[otro.pk], 420)
        self.assertEqual(segundos_acumulados_mes(dt.date(2026, 10, 31))[u.pk], 4020)

    def test_panel_muestra_acumulado_y_descuento_de_cada_profesional(self):
        u = crear_profesional('acu3', zona=self.zona)
        self.crear(u, dt.date(2026, 10, 1), 8, 1200); self.crear(u, dt.date(2026, 10, 2), 8, 1500)   # 20:00 + 25:00 = 45:00
        filas, _ = construir_panel(LUNES, local(LUNES, 20, 0))
        f = {x['user'].username: x for x in filas}['acu3']
        self.assertEqual((f['acum_seg'], f['descuento_dias']), (2700, 0))               # sin reglas: sin descuento
        crear_reglas()
        filas, _ = construir_panel(LUNES, local(LUNES, 20, 0))
        f = {x['user'].username: x for x in filas}['acu3']
        self.assertEqual(f['descuento_dias'], 0.5)                                       # 45:00 exactos: aún en el tramo de 30:01 a 45:00
        self.client.force_login(User.objects.create_superuser('rootacu', password='x'))
        with mock.patch('django.utils.timezone.now', return_value=local(LUNES, 20, 0)):
            r = self.client.get(reverse('asistencia:panel_admin'))
        self.assertContains(r, '45:00')
        self.assertContains(r, '0,5 día')

    def test_mi_asistencia_muestra_descuento_y_cuanto_falta(self):
        u = crear_profesional('acu4', zona=self.zona)
        hoy = timezone.localdate()
        self.crear(u, hoy, 8, 1200)                                                      # 20:00 acumulados
        self.client.force_login(u)
        url = reverse('asistencia:mi_asistencia')
        self.assertFalse(self.client.get(url).context['hay_reglas'])                     # sin reglas no se muestra nada
        crear_reglas()
        r = self.client.get(url)
        self.assertEqual((r.context['acum_seg'], r.context['descuento_dias'], r.context['faltan_seg']), (1200, 0, 601))
        self.assertContains(r, 'Con 10:01 min más de retraso aumentaría el descuento')
        self.crear(u, hoy, 14, 900)                                                      # 35:00 en total
        r = self.client.get(url)
        self.assertEqual((r.context['descuento_dias'], r.context['faltan_seg']), (0.5, 601))
        self.assertContains(r, 'Descuento por retraso: 0,5 día')
        r = self.client.get(url + '?mes=1&anio=2026')                                    # un mes pasado: sin «cuánto falta»
        self.assertIsNone(r.context['faltan_seg'])


# ══════════════════════════════════════════════════════════════════════════════
# INFORME MENSUAL (datos, PDF y descargas)
# ══════════════════════════════════════════════════════════════════════════════

import re
import os
from .informe_mensual import construir_informes_mensuales, fmt_dias, fmt_horas
from .informe_mensual_pdf import generar_informe_mensual_pdf

OCT = lambda d: dt.date(2026, 10, d)
AHORA_INFORME = local(OCT(10), 7, 0)          # sábado 10/oct 07:00: hasta el 9 evaluado; el 10 aún "por llegar"


def crear_prof(username, zona, apellido='Pérez', nombre=None, sucursal=None, control=OCT(1)):
    """Profesional con usuario enrolado y control de asistencia desde `control`."""
    from profesionales.models import Profesional
    u = crear_profesional(username, zona=zona)
    p = Profesional.objects.create(user=u, nombre=nombre or username.capitalize(),
                                   apellido=apellido, especialidad='Psicología')
    if sucursal:
        p.sucursales.add(sucursal)
    EnrolamientoFacial.objects.filter(user=u).update(fecha_enrolamiento=local(control, 8) if control else None)
    if control is None:
        EnrolamientoFacial.objects.filter(user=u).update(estado='pendiente')
    return p


def marca(user, fecha, hora, minuto, tipo, estado='PUNTUAL', bloque='', minutos=0, admin=None, tol=10, acum_seg=None):
    """
    `minutos` = minutos de retraso desde la hora de entrada. Lo que se acumula es lo que pasa de `tol`
    (o `acum_seg` si se indica). En estado PUNTUAL no hay retraso.
    """
    tarde = minutos * 60 if estado == 'TARDANZA' else 0
    acum = max(minutos - tol, 0) * 60 if estado == 'TARDANZA' else 0
    if acum_seg is not None:
        acum = acum_seg
    return RegistroAsistencia.objects.create(
        user=user, tipo=tipo, estado=estado, bloque=bloque, minutos_tardanza=minutos,
        segundos_tarde=tarde, segundos_acumulables=acum,
        fecha_hora=local(fecha, hora, minuto), registrado_por=admin)


def jornada(user, fecha, ent1=(8, 0, 'PUNTUAL', 0), sal1=(13, 0), ent2=(14, 0, 'PUNTUAL', 0), sal2=(18, 0)):
    """Marca una jornada partida (cualquiera de los 4 marcados puede omitirse con None)."""
    if ent1: marca(user, fecha, ent1[0], ent1[1], 'ENTRADA', ent1[2], '1', ent1[3])
    if sal1: marca(user, fecha, sal1[0], sal1[1], 'SALIDA', 'PUNTUAL', '1')
    if ent2: marca(user, fecha, ent2[0], ent2[1], 'ENTRADA', ent2[2], '2', ent2[3])
    if sal2: marca(user, fecha, sal2[0], sal2[1], 'SALIDA', 'PUNTUAL', '2')


class InformeMensualDatosTests(BaseAsistencia):
    """
    Octubre 2026 (horario de la zona: Lun-Vie partido 8-13 / 14-18, sábado 8-12). 'Hoy' = sáb 10/oct 07:00.
    Reglas: hasta 30 min sin descuento · 45 -> ½ día · 60 -> 1 día · 90 -> 2 días · más de 90 -> 3 días.
      Jue 1  puntual completo          Vie 2  retraso (llegó 25 min tarde: acumula 15)   Sáb 3  FALTA (1 bloque = día completo)
      Dom 4  sin horario               Lun 5  falta de la tarde (½)
      Mar 6  retraso 40 y 20 min tarde (acumula 30 + 10)                                  Mié 7  FALTA día completo
      Jue 8  feriado (libre)           Vie 9  mañana sin salida, falta tarde               Sáb 10 aún por llegar
    Retraso acumulado del mes = 15 + 30 + 10 = 55 min (tolerancia 10 min en cada ingreso).
    """

    def setUp(self):
        super().setUp()
        crear_reglas()
        self.p = crear_prof('inf', self.zona, apellido='Quispe', nombre='Ana')
        u = self.p.user
        jornada(u, OCT(1))
        jornada(u, OCT(2), ent1=(8, 25, 'TARDANZA', 25))
        jornada(u, OCT(5), ent2=None, sal2=None)
        jornada(u, OCT(6), ent1=(8, 40, 'TARDANZA', 40), ent2=(14, 20, 'TARDANZA', 20))
        FechaEspecial.objects.create(zona=self.zona, fecha=OCT(8), tipo_horario='libre', motivo='Feriado')
        jornada(u, OCT(9), sal1=None, ent2=None, sal2=None)
        self.inf = construir_informes_mensuales([self.p], 2026, 10, AHORA_INFORME)[0]
        self.d = {x.fecha.day: x for x in self.inf.dias}

    def test_estado_de_cada_dia(self):
        e = {n: self.d[n].estado for n in range(1, 11)}
        self.assertEqual(e, {1: 'puntual', 2: 'retraso', 3: 'falta', 4: 'sin_horario', 5: 'falta', 6: 'retraso',
                             7: 'falta', 8: 'libre', 9: 'falta', 10: 'pendiente'})
        self.assertEqual(self.d[11].estado, 'futuro')
        self.assertEqual(len(self.inf.dias), 31)

    def test_faltas_medio_dia_y_dia_completo(self):
        self.assertEqual((self.d[3].falta_dias, self.d[3].falta_texto), (1.0, 'Falta día completo'))   # sábado: 1 bloque
        self.assertEqual((self.d[5].falta_dias, self.d[5].falta_texto), (0.5, 'Falta medio día'))      # faltó la tarde
        self.assertEqual((self.d[7].falta_dias, self.d[7].falta_texto), (1.0, 'Falta día completo'))   # faltó los 2 bloques
        self.assertEqual((self.d[9].falta_dias, self.d[9].falta_texto), (0.5, 'Falta medio día'))
        self.assertEqual(self.d[1].falta_dias, 0)
        self.assertEqual((self.d[3].bloques_falta, self.d[5].bloques_falta, self.d[7].bloques_falta), ([1], [2], [1, 2]))

    def test_marcaciones_y_retraso_por_dia(self):
        self.assertEqual(self.d[1].pares, [('08:00', '13:00', False), ('14:00', '18:00', False)])
        self.assertEqual(self.d[6].pares, [('08:40', '13:00', True), ('14:20', '18:00', True)])
        self.assertEqual(self.d[6].retraso_seg, 2400)                       # (40-10) + (20-10) = 40 min
        self.assertEqual(self.d[2].retraso_seg, 900)                        # 25-10 = 15 min
        self.assertEqual(self.d[9].pares, [('08:00', None, False)])
        self.assertTrue(self.d[9].sin_salida)
        self.assertEqual(self.d[3].pares, [])

    def test_retraso_acumulado_y_descuento_acumulado_corren_dia_a_dia(self):
        acum = {n: self.d[n].acum_seg for n in (1, 2, 3, 5, 6, 7, 9)}
        self.assertEqual(acum, {1: 0, 2: 900, 3: 900, 5: 900, 6: 3300, 7: 3300, 9: 3300})
        # descuento acumulado = faltas + retraso (55 min cae en el tramo de 45:01 a 60:00 = 1 día)
        desc = {n: self.d[n].descuento_acum for n in (1, 2, 3, 5, 6, 7, 9)}
        self.assertEqual(desc, {1: 0, 2: 0, 3: 1.0, 5: 1.5, 6: 2.5, 7: 3.5, 9: 4.0})

    def test_resumen_del_mes(self):
        r = self.inf.resumen
        self.assertEqual(r['dias_con_horario'], 7)                       # 1,2,3,5,6,7,9 (el 10 no terminó)
        self.assertEqual(r['dias_completos'], 3)                         # 1, 2, 6
        self.assertEqual((r['dias_con_falta'], r['faltas_completas'], r['faltas_medias']), (4, 2, 2))
        self.assertEqual((r['tardanzas'], r['retraso_seg'], r['retraso_txt']), (3, 3300, '55:00'))
        self.assertEqual((r['desc_faltas'], r['desc_retraso'], r['desc_total']), (3.0, 1.0, 4.0))
        self.assertEqual(r['sin_salida'], 1)
        self.assertEqual(r['trabajado_min'], 540 + 515 + 300 + 480)      # el día 9 sin salida no suma
        self.assertEqual(r['esperado_min'], 6 * 540 + 240)               # 6 días partidos + el sábado 3
        self.assertEqual(r['entradas'], 8)                               # ingresos a bloques del horario

    def test_la_evaluacion_del_mes_sale_del_resumen(self):
        r = self.inf.resumen
        self.assertEqual((r['puntualidad']['estrellas'], r['puntualidad']['etiqueta']), (2.0, 'Mala'))   # 1 día de descuento
        self.assertEqual((r['asistencia']['nivel'], r['asistencia']['etiqueta']), ('rojo', 'Mala'))
        self.assertIn('55:00', r['puntualidad']['motivo'])
        self.assertIn('sin justificar', r['asistencia']['motivo'])
        self.assertTrue(r['alerta'])
        self.assertTrue(r['provisional'])                                # el mes aún no termina

    def test_el_ultimo_descuento_acumulado_coincide_con_el_total(self):
        self.assertEqual(self.d[10].descuento_acum, self.inf.resumen['desc_total'])
        self.assertEqual(self.d[9].descuento_acum, self.inf.resumen['desc_total'])
        self.assertEqual(self.d[11].descuento_acum, 0)                   # día futuro: sin dato

    def test_horario_de_cada_dia_y_feriado(self):
        self.assertEqual(self.d[1].horario, '08:00–13:00 · 14:00–18:00')
        self.assertEqual(self.d[3].horario, '08:00–12:00')               # sábado solo mañana
        self.assertEqual((self.d[8].horario, self.d[8].nota), ('Libre', 'Feriado'))

    def test_registro_manual_del_admin_cubre_el_bloque_y_quita_la_falta(self):
        admin = User.objects.create_superuser('admin_inf', password='x')
        marca(self.p.user, OCT(7), 8, 30, 'ENTRADA', 'TARDANZA', '1', 30, admin=admin)       # 30 tarde = 20 min acumulables
        marca(self.p.user, OCT(7), 13, 0, 'SALIDA', 'PUNTUAL', '1', admin=admin)
        inf = construir_informes_mensuales([self.p], 2026, 10, AHORA_INFORME)[0]
        d7 = {x.fecha.day: x for x in inf.dias}[7]
        self.assertEqual((d7.estado, d7.falta_dias), ('falta', 0.5))     # solo falta la tarde
        self.assertEqual(inf.resumen['retraso_seg'], 3300 + 1200)        # 75:00 -> tramo de 60:01 a 90:00 = 2 días
        self.assertEqual(inf.resumen['desc_retraso'], 2.0)

    def test_registros_ausente_del_cron_no_cambian_el_resultado(self):
        generar_ausentes(OCT(7), local(OCT(7), 19, 0), incluir_sin_enrolar=True)
        inf = construir_informes_mensuales([self.p], 2026, 10, AHORA_INFORME)[0]
        self.assertEqual(inf.resumen['desc_faltas'], 3.0)                 # las faltas se derivan del horario

    def test_sin_reglas_no_hay_descuento_por_retraso(self):
        ReglasAsistencia.objects.all().delete()
        inf = construir_informes_mensuales([self.p], 2026, 10, AHORA_INFORME)[0]
        r = inf.resumen
        self.assertEqual((r['desc_retraso'], r['hay_reglas'], r['desc_faltas'], r['desc_total']), (0, False, 3.0, 3.0))
        self.assertEqual(r['puntualidad']['estrellas'], 3.0)              # acumula retraso, sin reglas de descuento
        self.assertIn('No hay reglas de descuento', r['puntualidad']['motivo'])

    def test_tramos_personalizados(self):
        crear_reglas(tramos=[(60, 0)], resto=5)                           # 55 min < 60: sin descuento
        self.assertEqual(construir_informes_mensuales([self.p], 2026, 10, AHORA_INFORME)[0].resumen['desc_retraso'], 0)
        crear_reglas(tramos=[(10, 0.5)], resto=2)                         # 55 min > 10: el tramo «más allá»
        self.assertEqual(construir_informes_mensuales([self.p], 2026, 10, AHORA_INFORME)[0].resumen['desc_retraso'], 2.0)

    def test_horas_y_formatos(self):
        self.assertEqual(fmt_dias(0), '0'); self.assertEqual(fmt_dias(0.5), '0,5'); self.assertEqual(fmt_dias(2.0), '2')
        self.assertEqual(fmt_dias(1.5), '1,5'); self.assertEqual(fmt_dias(1 / 3), '0,33')
        self.assertEqual(fmt_horas(1835), '30 h 35 min')


class InformeMensualControlTests(BaseAsistencia):
    def test_los_dias_anteriores_al_control_no_generan_faltas(self):
        p = crear_prof('ctl', self.zona, control=OCT(7))                    # empezó a ser controlado el 7
        inf = construir_informes_mensuales([p], 2026, 10, AHORA_INFORME)[0]
        d = {x.fecha.day: x for x in inf.dias}
        self.assertEqual([d[n].estado for n in (1, 2, 3, 6)], ['sin_control'] * 4)
        self.assertEqual(d[7].estado, 'falta')
        self.assertEqual(inf.resumen['desc_faltas'], 3.0)                   # mié 7, jue 8 y vie 9 sin marcar: 1 día cada uno
        self.assertEqual(inf.control_desde, OCT(7))

    def test_sin_enrolar_ni_marcaciones_no_tiene_control(self):
        p = crear_prof('nuevo', self.zona, control=None)
        inf = construir_informes_mensuales([p], 2026, 10, AHORA_INFORME)[0]
        self.assertFalse(inf.resumen['hay_control'])
        self.assertTrue(all(x.estado in ('sin_control',) for x in inf.dias))
        self.assertEqual((inf.resumen['desc_total'], inf.resumen['dias_con_horario']), (0, 0))

    def test_una_marcacion_manual_inicia_el_control(self):
        p = crear_prof('manual', self.zona, control=None)
        admin = User.objects.create_superuser('adm_ctl', password='x')
        marca(p.user, OCT(6), 8, 0, 'ENTRADA', 'PUNTUAL', '1', admin=admin)
        inf = construir_informes_mensuales([p], 2026, 10, AHORA_INFORME)[0]
        self.assertEqual(inf.control_desde, OCT(6))
        d = {x.fecha.day: x for x in inf.dias}
        self.assertEqual((d[5].estado, d[6].estado), ('sin_control', 'falta'))

    def test_mes_pasado_se_evalua_completo_y_mes_futuro_no_genera_nada(self):
        p = crear_prof('mes', self.zona, control=dt.date(2026, 8, 1))
        inf = construir_informes_mensuales([p], 2026, 9, AHORA_INFORME)[0]       # septiembre completo
        self.assertTrue(all(x.estado != 'futuro' for x in inf.dias))
        self.assertEqual(inf.resumen['dias_con_horario'], 22 + 4)               # 22 laborables + 4 sábados
        inf = construir_informes_mensuales([p], 2026, 11, AHORA_INFORME)[0]
        self.assertTrue(all(x.estado == 'futuro' for x in inf.dias))
        self.assertEqual(inf.resumen['desc_total'], 0)

    def test_profesional_sin_usuario_se_omite_y_consultas_son_fijas(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from profesionales.models import Profesional
        Profesional.objects.create(nombre='Sin', apellido='Usuario', especialidad='X')
        uno = [crear_prof('q0', self.zona)]
        varios = uno + [crear_prof(f'q{i}', self.zona) for i in range(1, 7)]
        with CaptureQueriesContext(connection) as c1:
            construir_informes_mensuales(uno, 2026, 10, AHORA_INFORME)
        with CaptureQueriesContext(connection) as c7:
            r = construir_informes_mensuales(varios, 2026, 10, AHORA_INFORME)
        self.assertEqual(len(r), 7)
        self.assertEqual(len(c1), len(c7))                                      # no crece con la cantidad
        self.assertEqual(construir_informes_mensuales([], 2026, 10), [])


def paginas_pdf(pdf: bytes) -> int:
    return len(re.findall(rb'/Type /Page(?!s)', pdf))


class InformeMensualPdfTests(BaseAsistencia):
    def setUp(self):
        super().setUp()
        from servicios.models import Sucursal
        crear_reglas()
        self.suc = Sucursal.objects.create(nombre='Central', direccion='X')
        self.ps = [crear_prof(f'pdf{i}', self.zona, apellido=f'Apellido{i}', nombre=f'Nombre{i}', sucursal=self.suc)
                   for i in range(3)]
        jornada(self.ps[0].user, OCT(1), ent1=(8, 40, 'TARDANZA', 40))
        jornada(self.ps[1].user, OCT(1))

    def informes(self, ps=None):
        return construir_informes_mensuales(ps or self.ps, 2026, 10, AHORA_INFORME)

    def test_una_hoja_por_profesional(self):
        pdf = generar_informe_mensual_pdf(self.informes(self.ps[:1]), 'Profesional: Nombre0 Apellido0')
        self.assertTrue(pdf.startswith(b'%PDF'))
        self.assertEqual(paginas_pdf(pdf), 1)

    def test_varios_profesionales_llevan_hoja_de_resumen_mas_una_hoja_cada_uno(self):
        pdf = generar_informe_mensual_pdf(self.informes(), 'Sucursal: Central')
        self.assertEqual(paginas_pdf(pdf), 1 + 3)

    def test_el_resumen_se_pagina_segun_lo_que_ocupa_cada_profesional(self):
        from .informe_mensual_pdf import _paginar_resumen
        base = self.informes()[0]
        grupos = _paginar_resumen([base] * 40)
        self.assertGreaterEqual(len(grupos), 2)                                 # no caben 40 filas con sus motivos en una hoja
        self.assertEqual(sum(len(g) for g in grupos), 40)
        pdf = generar_informe_mensual_pdf([base] * 40, 'Global')
        self.assertEqual(paginas_pdf(pdf), len(grupos) + 40)

    def test_contenido_sin_montos_de_pago(self):
        pdf = generar_informe_mensual_pdf(self.informes(self.ps[:1]), 'Profesional: X', compress=False)
        for esperado in (b'DESCUENTO TOTAL DEL MES', b'Nombre0 Apellido0', b'Sucursal:', b'Central', b'TOTAL DEL MES',
                         b'RETRASO ACUMULADO', b'HORAS TRABAJADAS', b'Falta d', b'Retraso', b'montos de pago',
                         b'PUNTUALIDAD', b'ASISTENCIA', b'Regla del mes'):
            self.assertIn(esperado, pdf, esperado)                       # (la nota aclara que NO incluye montos)
        for prohibido in (b'Bs.', b'Bs ', b'sueldo', b'Sueldo', b'salario', b'Salario', b'a pagar', b'Total a'):
            self.assertNotIn(prohibido, pdf, prohibido)

    def test_sin_profesionales_genera_una_hoja_informativa(self):
        pdf = generar_informe_mensual_pdf([], 'Global', compress=False)
        self.assertEqual(paginas_pdf(pdf), 1)
        self.assertIn(b'No hay profesionales', pdf)

    def test_mes_con_31_dias_cabe_en_una_hoja_y_con_foto_ausente_usa_iniciales(self):
        p = crear_prof('largo', self.zona, apellido='ConUnApellidoMuyLargoQueNoCabeEnLaTarjetaDelInforme',
                       nombre='NombreTambienLargoParaProbarElRecorte', sucursal=self.suc)
        for d in range(1, 9):
            jornada(p.user, OCT(d))
        inf = construir_informes_mensuales([p], 2026, 10, local(OCT(31), 20, 0))
        pdf = generar_informe_mensual_pdf(inf, 'Profesional: largo')
        self.assertEqual(paginas_pdf(pdf), 1)

    def test_demo_visual(self):
        """Con SAVE_DEMO_PDF=1 deja un PDF de ejemplo en /tmp para revisarlo a ojo."""
        if not os.environ.get('SAVE_DEMO_PDF'):
            self.skipTest('solo con SAVE_DEMO_PDF=1')
        p = crear_prof('demo', self.zona, apellido='Quispe Mamani', nombre='Ana María', sucursal=self.suc)
        u = p.user
        jornada(u, OCT(1)); jornada(u, OCT(2), ent1=(8, 25, 'TARDANZA', 25)); jornada(u, OCT(5), ent2=None, sal2=None)
        jornada(u, OCT(6), ent1=(8, 40, 'TARDANZA', 40), ent2=(14, 20, 'TARDANZA', 20))
        FechaEspecial.objects.create(zona=self.zona, fecha=OCT(8), tipo_horario='libre', motivo='Feriado')
        jornada(u, OCT(9), sal1=None, ent2=None, sal2=None)
        inf = construir_informes_mensuales(self.ps + [p], 2026, 10, AHORA_INFORME)
        open('/tmp/informe_mensual_demo.pdf', 'wb').write(generar_informe_mensual_pdf(inf, 'Global (todas las sucursales)'))
        open('/tmp/informe_mensual_demo_uno.pdf', 'wb').write(generar_informe_mensual_pdf(inf[-1:], 'Profesional: Ana'))


class InformeMensualVistasTests(BaseAsistencia):
    def setUp(self):
        super().setUp()
        from servicios.models import Sucursal
        self.s1 = Sucursal.objects.create(nombre='Central', direccion='X')
        self.s2 = Sucursal.objects.create(nombre='Japón', direccion='Y')
        self.a = crear_prof('va', self.zona, apellido='Alvarez', nombre='Rosa', sucursal=self.s1)
        self.b = crear_prof('vb', self.zona, apellido='Berrios', nombre='Luis', sucursal=self.s2)
        self.admin = User.objects.create_superuser('adm_vistas', password='x')
        self.client.force_login(self.admin)
        self.url = reverse('asistencia:informe_mensual')
        self.pdf = reverse('asistencia:informe_mensual_pdf')

    def test_pagina_con_filtros_y_resumen(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Alvarez'); self.assertContains(r, 'Berrios')
        self.assertContains(r, 'Global (todos)'); self.assertContains(r, 'Sucursal Central'); self.assertContains(r, 'Sucursal Japón')
        self.assertEqual(len(r.context['informes']), 2)
        r = self.client.get(self.url, {'sucursal': self.s1.pk})
        self.assertEqual([i.profesional.pk for i in r.context['informes']], [self.a.pk])
        r = self.client.get(self.url, {'profesional': self.b.pk})
        self.assertEqual([i.profesional.pk for i in r.context['informes']], [self.b.pk])

    def test_descarga_global_por_sucursal_y_por_profesional(self):
        r = self.client.get(self.pdf)
        self.assertEqual(r.status_code, 200); self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertIn('attachment', r['Content-Disposition']); self.assertIn('global', r['Content-Disposition'])
        self.assertEqual(paginas_pdf(r.content), 1 + 2)                          # resumen + 2 profesionales
        r = self.client.get(self.pdf, {'sucursal': self.s1.pk})
        self.assertIn('sucursal-central', r['Content-Disposition']); self.assertEqual(paginas_pdf(r.content), 1)
        r = self.client.get(self.pdf, {'profesional': self.b.pk})
        self.assertIn('berrios-luis', r['Content-Disposition']); self.assertEqual(paginas_pdf(r.content), 1)

    def test_parametros_invalidos_o_futuros_usan_el_mes_actual(self):
        hoy = timezone.localdate()
        for q in ({'mes': '13'}, {'mes': 'x'}, {'anio': '99999'}, {'mes': '1', 'anio': str(hoy.year + 1)}, {'sucursal': 'zz'}, {'profesional': '-1'}):
            self.assertEqual(self.client.get(self.pdf, q).status_code, 200, q)
            self.assertEqual(self.client.get(self.url, q).status_code, 200, q)
        r = self.client.get(self.url, {'mes': '13'})
        self.assertEqual((r.context['mes'], r.context['anio']), (hoy.month, hoy.year))

    def test_solo_administradores(self):
        self.client.force_login(self.a.user)
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.assertEqual(self.client.get(self.pdf).status_code, 302)
        self.client.logout()
        self.assertEqual(self.client.get(self.pdf).status_code, 302)

    def test_el_profesional_descarga_su_propio_informe(self):
        self.client.force_login(self.a.user)
        r = self.client.get(reverse('asistencia:mi_informe_pdf'))
        self.assertEqual(r.status_code, 200); self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertEqual(paginas_pdf(r.content), 1)
        self.assertIn('mi_asistencia_', r['Content-Disposition'])
        self.assertContains(self.client.get(reverse('asistencia:mi_asistencia')), 'Descargar mi informe del mes')

    def test_un_usuario_sin_profesional_vinculado_no_puede_descargar(self):
        u = crear_profesional('huerfano', zona=self.zona)                         # profesional (rol) sin ficha Profesional
        self.client.force_login(u)
        r = self.client.get(reverse('asistencia:mi_informe_pdf'))
        self.assertRedirects(r, reverse('asistencia:mi_asistencia'))


# ══════════════════════════════════════════════════════════════════════════════
# VIGENCIAS: los cambios de horarios y reglas NO son retroactivos
# ══════════════════════════════════════════════════════════════════════════════

NOV = lambda d: dt.date(2026, 11, d)
SIEMPRE = dt.date(2000, 1, 1)


def datos_editar(plantilla, dias, deseados, desde, nombre=''):
    """POST para editar_plantilla: `deseados` = [(entrada, salida, tolerancia[, límite]), ...] ('HH:MM')."""
    existentes = list(plantilla.bloques.order_by('hora_entrada')) if plantilla.pk else []
    n = max(len(existentes), len(deseados))
    data = {'nombre': nombre, 'dias': dias, 'vigente_desde': desde, 'bloques-TOTAL_FORMS': n,
            'bloques-INITIAL_FORMS': len(existentes), 'bloques-MIN_NUM_FORMS': 0, 'bloques-MAX_NUM_FORMS': 4}
    for i in range(n):
        if i < len(existentes):
            data[f'bloques-{i}-id'] = existentes[i].pk
            data[f'bloques-{i}-plantilla'] = plantilla.pk
        if i < len(deseados):
            e, sal, tol, *lim = deseados[i]
            data.update({f'bloques-{i}-hora_entrada': e, f'bloques-{i}-hora_salida': sal,
                         f'bloques-{i}-tolerancia_minutos': tol,
                         f'bloques-{i}-max_retraso_minutos': lim[0] if lim else ''})
        else:
            data[f'bloques-{i}-DELETE'] = 'on'
    return data


class VigenciaHorariosTests(BaseAsistencia):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser('root_vig', password='x')
        self.client.force_login(self.admin)

    def editar(self, plantilla, dias, deseados, desde, nombre=''):
        return self.client.post(reverse('asistencia:editar_plantilla', args=[plantilla.pk]),
                                datos_editar(plantilla, dias, deseados, desde, nombre), follow=True)

    def test_la_resolucion_depende_de_la_fecha(self):
        u = crear_prof('res', self.zona).user
        self.p_semana.vigente_hasta = OCT(31); self.p_semana.save()
        nueva = crear_plantilla(self.zona, LUN_VIE, [(T(8), T(12), 5)])
        PlantillaHorario.objects.filter(pk=nueva.pk).update(vigente_desde=NOV(1))
        self.assertEqual(len(self.horario(u, OCT(30)).bloques), 2)           # viernes 30/oct: versión anterior
        self.assertEqual(len(self.horario(u, NOV(2)).bloques), 1)            # lunes 2/nov: versión nueva
        self.assertEqual(self.horario(u, NOV(2)).bloques[0].tolerancia, 5)

    def test_editar_con_fecha_posterior_crea_version_y_los_meses_pasados_no_cambian(self):
        crear_reglas()
        p = crear_prof('v1', self.zona, control=dt.date(2026, 9, 1))
        jornada(p.user, dt.date(2026, 9, 1), ent1=(8, 40, 'TARDANZA', 40))
        antes = construir_informes_mensuales([p], 2026, 9, AHORA_INFORME)[0].resumen
        antes_oct = construir_informes_mensuales([p], 2026, 10, AHORA_INFORME)[0].resumen

        # el admin cambia Lun-Vie a horario continuo 08:00-12:00 (tolerancia 5) DESDE el 1/nov
        r = self.editar(self.p_semana, LUN_VIE, [('08:00', '12:00', 5)], '2026-11-01')
        self.assertRedirects(r, reverse('asistencia:horarios'))
        self.assertTrue(any('Nueva versión' in str(m) for m in r.context['messages']))

        versiones = PlantillaHorario.objects.filter(zona=self.zona, user=None, dias=LUN_VIE).order_by('vigente_desde')
        self.assertEqual(versiones.count(), 2)
        vieja, nueva = versiones
        self.assertEqual((vieja.vigente_desde, vieja.vigente_hasta), (SIEMPRE, OCT(31)))
        self.assertEqual((nueva.vigente_desde, nueva.vigente_hasta), (NOV(1), None))
        self.assertEqual([(b.hora_entrada, b.hora_salida, b.tolerancia_minutos) for b in nueva.bloques.all()],
                         [(T(8), T(12), 5)])
        self.assertEqual(vieja.bloques.count(), 2)                                  # la versión anterior queda intacta

        self.assertEqual(len(self.horario(p.user, OCT(30)).bloques), 2)
        self.assertEqual(len(self.horario(p.user, NOV(2)).bloques), 1)
        # septiembre y octubre se calculan EXACTAMENTE igual que antes del cambio
        self.assertEqual(construir_informes_mensuales([p], 2026, 9, AHORA_INFORME)[0].resumen, antes)
        self.assertEqual(construir_informes_mensuales([p], 2026, 10, AHORA_INFORME)[0].resumen, antes_oct)

    def test_el_horario_nuevo_si_se_aplica_desde_su_fecha(self):
        p = crear_prof('v2', self.zona, control=dt.date(2026, 10, 1))
        self.editar(self.p_semana, LUN_VIE, [('08:00', '12:00', 5)], '2026-11-01')
        inf = construir_informes_mensuales([p], 2026, 11, local(NOV(30), 20, 0))[0]
        lunes = {d.fecha.day: d for d in inf.dias}[2]
        self.assertEqual(lunes.horario, '08:00–12:00')                              # ya con el horario nuevo

    def test_sin_cambios_de_dias_o_bloques_no_se_crea_version(self):
        r = self.editar(self.p_semana, LUN_VIE, [('08:00', '13:00', 10), ('14:00', '18:00', 15)], '2026-11-01',
                        nombre='Semana laboral')
        self.assertTrue(any('no se creó una versión' in str(m) for m in r.context['messages']))
        self.assertEqual(PlantillaHorario.objects.filter(zona=self.zona, dias=LUN_VIE).count(), 1)
        self.p_semana.refresh_from_db()
        self.assertEqual((self.p_semana.nombre, self.p_semana.vigente_hasta), ('Semana laboral', None))

    def test_cambiar_solo_la_tolerancia_o_el_limite_tambien_es_una_version(self):
        self.editar(self.p_semana, LUN_VIE, [('08:00', '13:00', 20, 90), ('14:00', '18:00', 15)], '2026-11-01')
        nueva = PlantillaHorario.objects.get(zona=self.zona, dias=LUN_VIE, vigente_desde=NOV(1))
        b1 = nueva.bloques.order_by('hora_entrada').first()
        self.assertEqual((b1.tolerancia_minutos, b1.max_retraso_minutos), (20, 90))
        u = crear_prof('v3', self.zona).user
        self.assertEqual(self.horario(u, OCT(30)).bloques[0].tolerancia, 10)         # antes: tolerancia 10 sin límite
        self.assertIsNone(self.horario(u, OCT(30)).bloques[0].max_retraso)
        self.assertEqual(self.horario(u, NOV(2)).bloques[0].max_retraso, 90)

    def test_fecha_igual_o_anterior_al_inicio_corrige_ese_mismo_horario(self):
        dom = crear_plantilla(self.zona, ['DOM'], [(T(8), T(12), 10)])
        PlantillaHorario.objects.filter(pk=dom.pk).update(vigente_desde=OCT(5))
        self.editar(dom, ['DOM'], [('09:00', '12:00', 10)], '2026-10-05')
        self.assertEqual(PlantillaHorario.objects.filter(dias=['DOM']).count(), 1)
        dom.refresh_from_db()
        self.assertEqual(dom.bloques.get().hora_entrada, T(9))
        self.editar(dom, ['DOM'], [('09:00', '12:00', 10)], '2026-09-01')           # fecha anterior: adelanta el inicio
        dom.refresh_from_db()
        self.assertEqual(dom.vigente_desde, dt.date(2026, 9, 1))
        self.assertEqual(PlantillaHorario.objects.filter(dias=['DOM']).count(), 1)

    def test_nueva_version_hereda_el_fin_de_la_anterior(self):
        self.p_semana.vigente_hasta = dt.date(2027, 6, 30); self.p_semana.save()
        self.editar(self.p_semana, LUN_VIE, [('08:00', '12:00', 5)], '2026-11-01')
        nueva = PlantillaHorario.objects.get(zona=self.zona, dias=LUN_VIE, vigente_desde=NOV(1))
        self.assertEqual(nueva.vigente_hasta, dt.date(2027, 6, 30))

    def test_el_solape_de_dias_solo_importa_si_las_fechas_se_cruzan(self):
        url = reverse('asistencia:nueva_plantilla', args=[self.zona.pk])
        def crear(desde):
            return self.client.post(url, datos_editar(PlantillaHorario(), ['SAB'], [('08:00', '10:00', 5)], desde))
        r = crear('2026-11-01')                                   # el sábado actual rige "desde siempre" y sin fin
        self.assertEqual(r.status_code, 200); self.assertContains(r, 'ya está en el horario')
        self.client.post(reverse('asistencia:eliminar_plantilla', args=[self.p_sabado.pk]), {'desde': '2026-11-01'})
        self.assertEqual(crear('2026-11-01').status_code, 302)    # el anterior terminó el 31/oct: ya no se cruzan
        self.assertEqual(PlantillaHorario.objects.filter(zona=self.zona, dias=['SAB']).count(), 2)
        u = crear_prof('v4', self.zona).user
        self.assertEqual(self.horario(u, OCT(24)).bloques[0].salida, T(12))          # sábado de octubre: versión vieja
        self.assertEqual(self.horario(u, NOV(7)).bloques[0].salida, T(10))           # sábado de noviembre: versión nueva

    def test_finalizar_conserva_el_pasado(self):
        u = crear_prof('v5', self.zona).user
        self.client.post(reverse('asistencia:eliminar_plantilla', args=[self.p_sabado.pk]), {'desde': '2026-11-01'})
        self.assertTrue(self.horario(u, OCT(24)).es_laborable)                       # sábado anterior al cierre
        self.assertFalse(self.horario(u, NOV(7)).es_laborable)                       # desde el 1/nov ya no hay sábado
        self.assertTrue(PlantillaHorario.objects.filter(pk=self.p_sabado.pk).exists())

    def test_no_se_puede_editar_un_horario_finalizado(self):
        self.p_sabado.vigente_hasta = timezone.localdate() - dt.timedelta(days=10); self.p_sabado.save()
        r = self.client.get(reverse('asistencia:editar_plantilla', args=[self.p_sabado.pk]), follow=True)
        self.assertRedirects(r, reverse('asistencia:horarios'))
        self.assertTrue(any('finalizó' in str(m) for m in r.context['messages']))

    def test_pantalla_de_horarios_muestra_programados_e_historial(self):
        hoy = timezone.localdate()
        self.p_sabado.vigente_hasta = hoy - dt.timedelta(days=10); self.p_sabado.save()
        prog = crear_plantilla(self.zona, ['DOM'], [(T(8), T(12), 10)])
        PlantillaHorario.objects.filter(pk=prog.pk).update(vigente_desde=hoy + dt.timedelta(days=20))
        r = self.client.get(reverse('asistencia:horarios'))
        self.assertContains(r, 'Programado')
        self.assertContains(r, 'Historial')
        z = [x for x in r.context['zonas'] if x.pk == self.zona.pk][0]
        self.assertEqual([p.pk for p in z.historial_zona], [self.p_sabado.pk])
        self.assertIn(prog.pk, [p.pk for p in z.plantillas_zona])
        self.assertIn('Domingo', z.dias_sin_horario)                                 # el domingo programado aún no rige

    def test_programar_un_cambio_a_futuro_no_cambia_hoy(self):
        u = crear_prof('v6', self.zona).user
        hoy = timezone.localdate()
        futuro = hoy + dt.timedelta(days=40)
        self.editar(self.p_semana, LUN_VIE, [('08:00', '12:00', 5)], futuro.isoformat())
        siguiente_lunes = hoy + dt.timedelta(days=(7 - hoy.weekday()) % 7 or 7)
        self.assertEqual(len(self.horario(u, siguiente_lunes).bloques), 2)           # aún rige el anterior
        marcable = self.marcar(u, 'ENTRADA', local(OCT(5), 8, 0))                     # el marcado de hoy usa lo vigente
        self.assertTrue(marcable[0])


class VigenciaHorarioPropioTests(BaseAsistencia):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser('root_prop', password='x')
        self.client.force_login(self.admin)
        self.p = crear_prof('prop', self.zona)
        self.u = self.p.user
        self.cfg = ConfigAsistencia.objects.get(user=self.u)

    def config(self, personalizado, desde):
        return self.client.post(reverse('asistencia:editar_config', args=[self.cfg.pk]), {
            'user': self.u.pk, 'zona': self.zona.pk, 'device_id': '', 'aplicar_desde': desde,
            **({'personalizado': 'on'} if personalizado else {})}, follow=True)

    def test_activar_horario_propio_desde_una_fecha(self):
        r = self.config(True, '2026-11-01')
        self.assertTrue(any('desde el 01/11/2026' in str(m) for m in r.context['messages']))
        per = self.cfg.periodos_propios.get()
        self.assertEqual((per.desde, per.hasta), (NOV(1), None))
        propias = PlantillaHorario.objects.filter(zona=self.zona, user=self.u)
        self.assertEqual(propias.count(), 2)
        self.assertTrue(all(p.vigente_desde == NOV(1) for p in propias))
        self.assertEqual(self.horario(self.u, OCT(30)).origen, 'zona')               # antes: el horario de la zona
        self.assertEqual(self.horario(self.u, NOV(2)).origen, 'personal')            # desde el 1/nov: el propio

    def test_editar_el_horario_propio_tambien_crea_versiones(self):
        self.config(True, '2026-11-01')
        propia = PlantillaHorario.objects.get(zona=self.zona, user=self.u, dias=LUN_VIE)
        self.client.post(reverse('asistencia:editar_plantilla', args=[propia.pk]),
                         datos_editar(propia, LUN_VIE, [('09:00', '15:00', 0)], '2026-11-16'))
        self.assertEqual(self.horario(self.u, NOV(10)).bloques[0].entrada, T(8))     # 10/nov: aún la primera versión propia
        self.assertEqual(self.horario(self.u, NOV(17)).bloques[0].entrada, T(9))     # 17/nov: la nueva

    def test_desactivar_horario_propio_desde_una_fecha_conserva_lo_anterior(self):
        self.config(True, '2026-11-01')
        self.config(False, '2026-12-01')
        self.cfg.refresh_from_db()
        self.assertFalse(self.cfg.personalizado)
        per = self.cfg.periodos_propios.get()
        self.assertEqual((per.desde, per.hasta), (NOV(1), dt.date(2026, 11, 30)))
        self.assertTrue(all(p.vigente_hasta == dt.date(2026, 11, 30)
                            for p in PlantillaHorario.objects.filter(zona=self.zona, user=self.u)))
        self.assertEqual(self.horario(self.u, NOV(10)).origen, 'personal')           # noviembre sigue con el propio
        self.assertEqual(self.horario(self.u, dt.date(2026, 12, 7)).origen, 'zona')  # desde el 1/dic vuelve la zona

    def test_reactivar_despues_conserva_el_periodo_anterior(self):
        self.config(True, '2026-11-01')
        self.config(False, '2026-12-01')
        self.config(True, '2027-01-04')
        self.assertEqual(self.cfg.periodos_propios.count(), 2)
        self.assertEqual(self.horario(self.u, NOV(10)).origen, 'personal')           # el periodo viejo sigue contando
        self.assertEqual(self.horario(self.u, dt.date(2026, 12, 7)).origen, 'zona')
        self.assertEqual(self.horario(self.u, dt.date(2027, 1, 11)).origen, 'personal')

    def test_activar_y_desactivar_el_mismo_dia_no_deja_rastros(self):
        self.config(True, '2026-11-01')
        self.config(False, '2026-11-01')
        self.assertEqual(self.cfg.periodos_propios.count(), 0)
        self.assertEqual(PlantillaHorario.objects.filter(zona=self.zona, user=self.u).count(), 0)

    def test_nueva_asignacion_con_horario_propio_desde_fecha(self):
        otro = crear_profesional('otro', zona=None)
        r = self.client.post(reverse('asistencia:asignaciones'), {
            'user': otro.pk, 'zona': self.zona.pk, 'personalizado': 'on', 'device_id': '', 'aplicar_desde': '2026-11-01'})
        self.assertRedirects(r, reverse('asistencia:asignaciones'))
        cfg = ConfigAsistencia.objects.get(user=otro)
        self.assertEqual(cfg.periodos_propios.get().desde, NOV(1))
        self.assertEqual(ResolvedorHorario(otro, self.zona, cfg, OCT(30)).resolver().origen, 'zona')
        self.assertEqual(ResolvedorHorario(otro, self.zona, cfg, NOV(2)).resolver().origen, 'personal')

    def test_marca_personalizado_sin_periodos_sigue_funcionando(self):
        """Compatibilidad: una asignación personalizada sin periodos registrados rige desde siempre."""
        ConfigAsistencia.objects.filter(pk=self.cfg.pk).update(personalizado=True)
        crear_plantilla(self.zona, ['LUN'], [(T(9), T(15), 0)], user=self.u)
        self.assertEqual(self.horario(self.u, LUNES).origen, 'personal')
        self.assertEqual(self.horario(self.u, NOV(2)).bloques[0].entrada, T(9))

    def test_la_migracion_de_datos_crea_el_periodo_de_los_horarios_propios_existentes(self):
        import importlib
        from django.apps import apps
        mig = importlib.import_module('asistencia.migrations.0011_vigencias_datos')
        ConfigAsistencia.objects.filter(pk=self.cfg.pk).update(personalizado=True)
        mig.crear_periodos(apps, None)
        mig.crear_periodos(apps, None)                                               # idempotente
        per = self.cfg.periodos_propios.get()
        self.assertEqual((per.desde, per.hasta), (SIEMPRE, None))


class VigenciaReglasTests(BaseAsistencia):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser('root_reg2', password='x')
        self.client.force_login(self.admin)
        self.hoy = timezone.localdate()
        crear_reglas(desde=SIEMPRE)                                                   # 30/45/60/90 min -> 0/½/1/2, resto 3
        crear_reglas(desde=NOV(1), tramos=[(20, 0), (40, 1)], resto=2)                # desde noviembre, más estricta

    def tardanza(self, u, fecha, acum_seg):
        return RegistroAsistencia.objects.create(
            user=u, tipo='ENTRADA', estado='TARDANZA', bloque='1', minutos_tardanza=(acum_seg + 600) // 60,
            segundos_tarde=acum_seg + 600, segundos_acumulables=acum_seg, fecha_hora=local(fecha, 8, 50))

    def test_cada_mes_usa_las_reglas_que_regian(self):
        self.assertEqual(ReglasAsistencia.para_mes(2026, 10).tramos_lista()[1], (2700, 0.5))
        self.assertEqual(ReglasAsistencia.para_mes(2026, 11).tramos_lista(), [(1200, 0), (2400, 1), (None, 2)])
        self.assertEqual(len(ReglasAsistencia.para_fecha(OCT(31)).tramos_lista()), 5)
        self.assertEqual(len(ReglasAsistencia.para_fecha(NOV(1)).tramos_lista()), 3)
        self.assertEqual(len(ReglasAsistencia.para_mes(2030, 1).tramos_lista()), 3)    # la última versión sigue rigiendo
        self.assertIsNone(ReglasAsistencia.para_fecha(dt.date(1999, 1, 1)))

    def test_el_informe_de_cada_mes_aplica_sus_propias_reglas(self):
        p = crear_prof('rg1', self.zona, control=OCT(1))
        self.tardanza(p.user, OCT(6), 3000); self.tardanza(p.user, NOV(3), 3000)       # 50 min acumulados en cada mes
        octubre = construir_informes_mensuales([p], 2026, 10, local(NOV(30), 20, 0))[0]
        noviembre = construir_informes_mensuales([p], 2026, 11, local(NOV(30), 20, 0))[0]
        self.assertNotEqual(octubre.tramos, noviembre.tramos)
        self.assertIn('hasta 20 min', noviembre.texto_regla)
        self.assertEqual(octubre.resumen['retraso_seg'], 3000)
        self.assertEqual(octubre.resumen['desc_retraso'], 1.0)       # 50 min con 30/45/60/90: de 45:01 a 60:00 = 1 día
        self.assertEqual(noviembre.resumen['desc_retraso'], 2.0)     # 50 min con 20/40: supera el último tope = 2 días

    def test_panel_y_mi_asistencia_usan_las_reglas_del_mes_consultado(self):
        u = crear_prof('rg2', self.zona, control=OCT(1)).user
        self.tardanza(u, OCT(6), 3000)
        filas, _ = construir_panel(OCT(20), local(OCT(20), 20, 0))
        self.assertEqual({f['user'].username: f['descuento_dias'] for f in filas}['rg2'], 1.0)    # reglas de octubre
        self.client.force_login(u)
        r = self.client.get(reverse('asistencia:mi_asistencia') + '?mes=10&anio=2026')
        self.assertEqual(r.context['descuento_dias'], 1.0)

    def test_un_cambio_para_el_mes_siguiente_no_toca_el_mes_en_curso_ni_los_pasados(self):
        siguiente = (self.hoy.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        vigente_antes = ReglasAsistencia.para_fecha(self.hoy)
        r = self.client.post(reverse('asistencia:reglas'),
                             datos_reglas([(15, 0), (30, 1)], 2, siguiente.month, siguiente.year), follow=True)
        self.assertTrue(any('los meses anteriores no cambian' in str(m) for m in r.context['messages']))
        self.assertEqual(ReglasAsistencia.para_fecha(self.hoy).pk, vigente_antes.pk)             # hoy sigue igual
        self.assertEqual(ReglasAsistencia.para_fecha(siguiente).tramos_lista(), [(900, 0), (1800, 1), (None, 2)])
        estados = {v.pk: v.estado for v in r.context['versiones']}
        self.assertEqual(estados[ReglasAsistencia.para_fecha(siguiente).pk], 'programada')

    def test_avisos_al_guardar_en_el_mes_en_curso_o_en_meses_pasados(self):
        pasado = self.client.post(reverse('asistencia:reglas'), datos_reglas([(25, 0)], 1, 1, 2026), follow=True)
        self.assertTrue(any('meses ya transcurridos' in str(m) for m in pasado.context['messages']))
        self.assertEqual(ReglasAsistencia.para_mes(2026, 1).tramos_lista(), [(1500, 0), (None, 1)])
        self.assertEqual(len(ReglasAsistencia.para_mes(2025, 12).tramos_lista()), 5)             # (la "de siempre")

    def test_guardar_con_la_misma_fecha_actualiza_sin_duplicar_versiones_ni_tramos(self):
        n = ReglasAsistencia.objects.count()
        self.client.post(reverse('asistencia:reglas'), datos_reglas([(50, 0)], 1, 11, 2026))
        self.assertEqual(ReglasAsistencia.objects.count(), n)
        version = ReglasAsistencia.para_mes(2026, 11)
        self.assertEqual(version.tramos_lista(), [(3000, 0), (None, 1)])
        self.assertEqual(version.tramos.count(), 2)                                              # los viejos se reemplazaron

    def test_solo_se_pueden_borrar_versiones_programadas(self):
        futura = crear_reglas(desde=dt.date(2027, 6, 1), tramos=[(10, 0)], resto=1)
        self.client.post(reverse('asistencia:eliminar_reglas', args=[futura.pk]), follow=True)
        self.assertFalse(ReglasAsistencia.objects.filter(pk=futura.pk).exists())
        self.assertFalse(TramoDescuento.objects.filter(regla_id=futura.pk).exists())              # sus tramos también
        pasada = ReglasAsistencia.para_mes(2026, 10)
        r = self.client.post(reverse('asistencia:eliminar_reglas', args=[pasada.pk]), follow=True)
        self.assertTrue(ReglasAsistencia.objects.filter(pk=pasada.pk).exists())
        self.assertTrue(any('historial' in str(m) for m in r.context['messages']))
        self.assertEqual(self.client.get(reverse('asistencia:eliminar_reglas', args=[pasada.pk])).status_code, 405)

    def test_pagina_lista_las_versiones_con_su_estado_y_sus_tramos(self):
        r = self.client.get(reverse('asistencia:reglas'))
        self.assertContains(r, 'Versiones de las reglas'); self.assertContains(r, 'Desde siempre')
        self.assertContains(r, 'hasta 30 min: sin descuento')
        self.assertEqual(len(r.context['versiones']), 2)


class NoRetroactividadTests(BaseAsistencia):
    """El escenario que antes cambiaba septiembre al editar horarios y reglas."""

    def test_editar_horarios_y_reglas_para_adelante_deja_igual_un_mes_pasado(self):
        admin = User.objects.create_superuser('root_nr', password='x')
        self.client.force_login(admin)
        crear_reglas()
        p = crear_prof('nr', self.zona, control=dt.date(2026, 9, 1))
        jornada(p.user, dt.date(2026, 9, 1), ent1=(8, 50, 'TARDANZA', 50))          # 40 min acumulables: tramo de 30:01 a 45:00
        antes = construir_informes_mensuales([p], 2026, 9, AHORA_INFORME)[0].resumen
        self.assertEqual((antes['desc_retraso'], antes['esperado_min']), (0.5, 12840))

        # El administrador cambia horarios (desde el 15/oct) y reglas (desde el mes siguiente)
        self.client.post(reverse('asistencia:editar_plantilla', args=[self.p_semana.pk]),
                         datos_editar(self.p_semana, LUN_VIE, [('08:00', '12:00', 5)], '2026-10-15'))
        self.client.post(reverse('asistencia:editar_plantilla', args=[self.p_sabado.pk]),
                         datos_editar(self.p_sabado, ['SAB'], [('08:00', '18:00', 5)], '2026-10-15'))
        siguiente = (timezone.localdate().replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        self.client.post(reverse('asistencia:reglas'), datos_reglas([(10, 1), (20, 2)], 3, siguiente.month, siguiente.year))

        despues = construir_informes_mensuales([p], 2026, 9, AHORA_INFORME)[0].resumen
        self.assertEqual(despues, antes)                                  # septiembre idéntico, campo por campo


class EjemploCambioDeHorarioATitularTests(BaseAsistencia):
    """
    Caso del administrador: el horario (hora de entrada) cambia en medio del mes y los minutos de retraso se
    calculan día a día con el horario de CADA día, contando solo lo que pasa de la tolerancia; luego se suman en
    el mes. La regla de descuento no cambia a mitad de mes: solo desde un mes completo.
    """

    def test_lunes_entrada_8_45_marca_9_00_y_martes_entrada_9_00_marca_9_12(self):
        PlantillaHorario.objects.all().delete()
        # Lunes 5/oct: entrada 08:45, tolerancia 10.   Desde el martes 6/oct: entrada 09:00, tolerancia 10.
        viejo = crear_plantilla(self.zona, LUN_VIE, [(T(8, 45), T(13), 10)])
        PlantillaHorario.objects.filter(pk=viejo.pk).update(vigente_hasta=OCT(5))
        nuevo = crear_plantilla(self.zona, LUN_VIE, [(T(9), T(13), 10)])
        PlantillaHorario.objects.filter(pk=nuevo.pk).update(vigente_desde=OCT(6))
        crear_reglas()
        p = crear_prof('cliente', self.zona, control=OCT(1))
        u = p.user

        ok, lunes, _ = self.marcar(u, 'ENTRADA', local(OCT(5), 9, 0))        # llegó 15 min después de las 08:45
        self.assertTrue(ok)
        self.assertEqual((lunes.estado, lunes.minutos_tardanza, lunes.segundos_tarde, lunes.segundos_acumulables),
                         ('TARDANZA', 15, 900, 300))                         # 15 min tarde - 10 de tolerancia = 5 min acumulables
        self.assertTrue(self.marcar(u, 'SALIDA', local(OCT(5), 13, 0))[0])
        ok, martes, _ = self.marcar(u, 'ENTRADA', local(OCT(6), 9, 12))      # llegó 12 min después de las 09:00
        self.assertTrue(ok)
        self.assertEqual((martes.estado, martes.minutos_tardanza, martes.segundos_acumulables), ('TARDANZA', 12, 120))
        self.assertTrue(self.marcar(u, 'SALIDA', local(OCT(6), 13, 0))[0])

        inf = construir_informes_mensuales([p], 2026, 10, local(OCT(7), 7, 0))[0]
        d = {x.fecha.day: x for x in inf.dias}
        self.assertEqual((d[5].retraso_seg, d[5].acum_seg), (300, 300))
        self.assertEqual((d[6].retraso_seg, d[6].acum_seg), (120, 420))      # 5:00 + 2:00 = 7:00 acumulados
        self.assertEqual((inf.resumen['retraso_seg'], inf.resumen['retraso_txt']), (420, '7:00'))
        self.assertEqual(d[5].horario, '08:45–13:00'); self.assertEqual(d[6].horario, '09:00–13:00')
        self.assertEqual(inf.resumen['desc_retraso'], 0)                     # 7 min < 30 min: todavía sin descuento
        self.assertEqual(inf.resumen['puntualidad']['estrellas'], 3.0)       # acumula retraso, sin descuento

    def test_dentro_de_la_tolerancia_con_el_horario_nuevo_no_acumula(self):
        PlantillaHorario.objects.all().delete()
        crear_plantilla(self.zona, LUN_VIE, [(T(9), T(13), 10)])
        u = crear_prof('tol2', self.zona, control=OCT(1)).user
        ok, r, _ = self.marcar(u, 'ENTRADA', local(OCT(6), 9, 10))           # justo en el límite de tolerancia
        self.assertTrue(ok)
        self.assertEqual((r.estado, r.minutos_tardanza, r.segundos_tarde, r.segundos_acumulables), ('PUNTUAL', 0, 600, 0))

    def test_la_regla_de_descuento_solo_cambia_desde_un_mes_completo(self):
        admin = User.objects.create_superuser('root_mes', password='x')
        self.client.force_login(admin)
        r = self.client.post(reverse('asistencia:reglas'), datos_reglas([(20, 0), (40, 1)], 2, 12, 2026))
        self.assertEqual(r.status_code, 302)
        version = ReglasAsistencia.objects.get(vigente_desde=dt.date(2026, 12, 1))     # siempre el día 1 del mes elegido
        self.assertEqual(version.tramos_lista(), [(1200, 0), (2400, 1), (None, 2)])

# ══════════════════════════════════════════════════════════════════════════════
# RETRASO: solo se acumula lo que pasa de la tolerancia (con segundos)
# ══════════════════════════════════════════════════════════════════════════════

class RetrasoDespuesDeLaToleranciaTests(BaseAsistencia):
    """Horario de la zona: Lun-Vie 08:00 (tolerancia 10) y 14:00 (tolerancia 15)."""

    def entrada(self, ahora, n=[0]):
        n[0] += 1
        u = crear_profesional(f'rt{n[0]}', zona=self.zona)
        ok, r, errores = self.marcar(u, 'ENTRADA', ahora)
        self.assertTrue(ok, errores)
        return r

    def campos(self, r):
        return (r.estado, r.minutos_tardanza, r.segundos_tarde, r.segundos_acumulables)

    def test_hasta_la_tolerancia_no_acumula_nada(self):
        self.assertEqual(self.campos(self.entrada(local_s(LUNES, 7, 55, 0))), ('PUNTUAL', 0, 0, 0))          # antes: 0 s tarde
        self.assertEqual(self.campos(self.entrada(local_s(LUNES, 8, 0, 0))), ('PUNTUAL', 0, 0, 0))           # a la hora
        self.assertEqual(self.campos(self.entrada(local_s(LUNES, 8, 7, 0))), ('PUNTUAL', 0, 420, 0))         # usó la tolerancia
        self.assertEqual(self.campos(self.entrada(local_s(LUNES, 8, 10, 0))), ('PUNTUAL', 0, 600, 0))        # justo en el límite

    def test_pasada_la_tolerancia_acumula_solo_el_excedente(self):
        self.assertEqual(self.campos(self.entrada(local_s(LUNES, 8, 10, 1))), ('TARDANZA', 10, 601, 1))      # 1 segundo
        self.assertEqual(self.campos(self.entrada(local_s(LUNES, 8, 10, 30))), ('TARDANZA', 10, 630, 30))
        # «si marca a los 11 minutos empezará a contarse 1 minuto»: 11:00 -> 60 s acumulables (no 660)
        self.assertEqual(self.campos(self.entrada(local_s(LUNES, 8, 11, 0))), ('TARDANZA', 11, 660, 60))
        self.assertEqual(self.campos(self.entrada(local_s(LUNES, 8, 25, 0))), ('TARDANZA', 25, 1500, 900))   # 15 min

    def test_cada_bloque_usa_su_propia_tolerancia(self):
        self.assertEqual(self.campos(self.entrada(local_s(LUNES, 14, 15, 0))), ('PUNTUAL', 0, 900, 0))       # tolerancia 15
        self.assertEqual(self.campos(self.entrada(local_s(LUNES, 14, 20, 0))), ('TARDANZA', 20, 1200, 300))  # 5 min acumulables

    def test_registro_manual_calcula_igual(self):
        admin = User.objects.create_superuser('adm_rt', password='x')
        u = crear_profesional('rtm', zona=self.zona)
        ok, r, _ = registrar_manual(u, 'ENTRADA', admin, ahora=local_s(LUNES, 8, 11, 0))
        self.assertTrue(ok)
        self.assertEqual(self.campos(r), ('TARDANZA', 11, 660, 60))

    def test_salida_y_reentrada_no_acumulan_retraso(self):
        u = crear_profesional('rts', zona=self.zona)
        self.marcar(u, 'ENTRADA', local_s(LUNES, 8, 0, 0)); self.marcar(u, 'SALIDA', local_s(LUNES, 10, 0, 0))
        ok, reentrada, _ = self.marcar(u, 'ENTRADA', local_s(LUNES, 11, 0, 0))
        self.assertTrue(ok)
        self.assertEqual(self.campos(reentrada), ('PUNTUAL', 0, 0, 0))
        self.assertEqual(RegistroAsistencia.objects.filter(user=u, tipo='SALIDA').get().segundos_acumulables, 0)

    def test_detalle_del_calculador(self):
        horario = self.horario(crear_prof('rtd', self.zona).user, LUNES)
        d = CalculadorEstado(horario, local_s(LUNES, 8, 11, 0)).detalle()
        self.assertEqual((d['estado'], d['bloque'], d['minutos'], d['segundos_tarde'], d['segundos_acumulables']),
                         ('TARDANZA', '1', 11, 660, 60))
        sin_horario = CalculadorEstado(HorarioDia(), local_s(DOMINGO, 9, 0, 0)).detalle()
        self.assertEqual((sin_horario['estado'], sin_horario['segundos_acumulables']), ('PUNTUAL', 0))
        self.assertEqual(CalculadorEstado(horario, local_s(LUNES, 8, 11, 0)).calcular(), ('TARDANZA', '1', 11))   # compat.


# ══════════════════════════════════════════════════════════════════════════════
# EVALUACIÓN: estrellas de puntualidad y semáforo de asistencia
# ══════════════════════════════════════════════════════════════════════════════

from .evaluacion import (
    NIVELES_PUNTUALIDAD, SEMAFORO, es_alerta, estrellas_para, evaluar_asistencia, evaluar_puntualidad,
)


class EvaluacionPuraTests(TestCase):
    def test_estrellas_segun_el_retraso_y_el_descuento(self):
        # (acumulado seg, días de descuento, usos de tolerancia) -> estrellas
        casos = [((0, 0, 0), 5.0), ((0, 0, 3), 4.0), ((60, 0, 0), 3.0), ((1800, 0, 2), 3.0),
                 ((2400, 0.5, 0), 2.5), ((3000, 1, 0), 2.0), ((4000, 2, 0), 1.0), ((6000, 3, 0), 0.0),
                 ((9000, 5, 0), 0.0), ((3000, 1.5, 0), 1.0)]
        for args, estrellas in casos:
            self.assertEqual(estrellas_para(*args), estrellas, args)

    def test_colores_y_etiquetas_de_cada_nivel(self):
        esperado = {5.0: ('Excelente', '#16a34a'), 4.0: ('Buena', '#84cc16'), 3.0: ('Regular', '#eab308'),
                    2.5: ('Regular (con descuento)', '#f59e0b'), 2.0: ('Mala', '#f97316'),
                    1.0: ('Muy mala', '#dc2626'), 0.0: ('Pésima', '#7c3aed')}
        for estrellas, (etiqueta, color) in esperado.items():
            self.assertEqual(NIVELES_PUNTUALIDAD[estrellas][:2], (etiqueta, color))
        self.assertEqual({k: v[1] for k, v in SEMAFORO.items()}, {'verde': '#16a34a', 'amarillo': '#eab308', 'rojo': '#dc2626'})

    def test_motivos_de_puntualidad(self):
        def ev(acum, desc, usos=0, max_tarde=0, reglas=True):
            return evaluar_puntualidad(10, usos, max_tarde, acum, desc, reglas, 1800 if reglas else None)
        self.assertIn('nunca usó su tolerancia', ev(0, 0)['motivo'])
        self.assertIn('Usó la tolerancia en 2 de 10', ev(0, 0, usos=2, max_tarde=420)['motivo'])
        self.assertIn('7:00', ev(0, 0, usos=2, max_tarde=420)['motivo'])
        m3 = ev(900, 0)['motivo']
        self.assertTrue('15:00' in m3 and 'empieza al pasar 30:00' in m3)
        self.assertIn('medio día de descuento', ev(2400, 0.5)['motivo'])
        self.assertIn('1 día de descuento', ev(3000, 1)['motivo'])
        self.assertIn('2 días de descuento', ev(4000, 2)['motivo'])
        self.assertIn('3 días de descuento', ev(6000, 3)['motivo'])
        self.assertIn('No hay reglas de descuento', ev(900, 0, reglas=False)['motivo'])

    def test_sin_ingresos_no_hay_evaluacion_de_puntualidad(self):
        self.assertIsNone(evaluar_puntualidad(0, 0, 0, 0, 0, True, 1800))

    def test_semaforo_de_asistencia(self):
        verde = evaluar_asistencia(10, 0, 0, 0, [], [])
        self.assertEqual((verde['nivel'], verde['etiqueta']), ('verde', 'Buena'))
        amarillo = evaluar_asistencia(10, 0, 1.5, 0, [], [(dt.date(2026, 10, 7), 'Certificado médico')])
        self.assertEqual((amarillo['nivel'], amarillo['etiqueta']), ('amarillo', 'Regular'))
        self.assertIn('07/10 (Certificado médico)', amarillo['motivo'])
        rojo = evaluar_asistencia(10, 1.5, 1, 1.5, [dt.date(2026, 10, 5), dt.date(2026, 10, 6)], [])
        self.assertEqual((rojo['nivel'], rojo['etiqueta']), ('rojo', 'Mala'))
        self.assertTrue('sin justificar' in rojo['motivo'] and '05/10' in rojo['motivo'] and 'Además' in rojo['motivo'])
        self.assertIsNone(evaluar_asistencia(0, 0, 0, 0, [], []))

    def test_provisional_y_alerta(self):
        self.assertIn('A la fecha', evaluar_puntualidad(5, 0, 0, 0, 0, True, 1800, provisional=True)['motivo'])
        buena = evaluar_puntualidad(5, 0, 0, 0, 0, True, 1800)
        mala = evaluar_puntualidad(5, 0, 0, 3000, 1, True, 1800)
        roja = evaluar_asistencia(5, 1, 0, 1, [dt.date(2026, 10, 5)], [])
        verde = evaluar_asistencia(5, 0, 0, 0, [], [])
        self.assertFalse(es_alerta(buena, verde))
        self.assertTrue(es_alerta(mala, verde))                 # 2 estrellas o menos
        self.assertTrue(es_alerta(buena, roja))                 # semáforo en rojo
        self.assertFalse(es_alerta(None, None))


class EvaluacionMensualTests(BaseAsistencia):
    """Estrellas y semáforo calculados a partir de las marcaciones reales del mes."""
    contador = [0]

    def prof(self, control=OCT(1)):
        self.contador[0] += 1
        return crear_prof(f'ev{self.contador[0]}', self.zona, control=control)

    def jornada_con_retraso(self, p, fecha, tarde_seg, acum_seg):
        u = p.user
        RegistroAsistencia.objects.create(
            user=u, tipo='ENTRADA', estado='TARDANZA' if acum_seg else 'PUNTUAL', bloque='1',
            minutos_tardanza=tarde_seg // 60 if acum_seg else 0, segundos_tarde=tarde_seg, segundos_acumulables=acum_seg,
            fecha_hora=local(fecha, 8, 0))
        marca(u, fecha, 13, 0, 'SALIDA', 'PUNTUAL', '1')
        marca(u, fecha, 14, 0, 'ENTRADA', 'PUNTUAL', '2')
        marca(u, fecha, 18, 0, 'SALIDA', 'PUNTUAL', '2')

    def evaluar(self, tarde_seg, acum_seg):
        crear_reglas()
        p = self.prof()
        self.jornada_con_retraso(p, OCT(1), tarde_seg, acum_seg)
        return construir_informes_mensuales([p], 2026, 10, local(OCT(1), 20, 0))[0].resumen

    def test_cinco_estrellas_siempre_a_la_hora_o_antes(self):
        r = self.evaluar(0, 0)
        self.assertEqual((r['puntualidad']['estrellas'], r['puntualidad']['etiqueta'], r['puntualidad']['color']),
                         (5.0, 'Excelente', '#16a34a'))
        self.assertIn('nunca usó su tolerancia', r['puntualidad']['motivo'])
        self.assertEqual(r['asistencia']['nivel'], 'verde')

    def test_cuatro_estrellas_uso_la_tolerancia_sin_acumular_retraso(self):
        r = self.evaluar(420, 0)
        self.assertEqual((r['puntualidad']['estrellas'], r['puntualidad']['etiqueta']), (4.0, 'Buena'))
        self.assertIn('7:00', r['puntualidad']['motivo'])
        self.assertEqual(r['usos_tolerancia'], 1)

    def test_tres_estrellas_acumula_retraso_sin_descuento(self):
        r = self.evaluar(1500, 900)
        self.assertEqual((r['puntualidad']['estrellas'], r['puntualidad']['etiqueta']), (3.0, 'Regular'))
        self.assertTrue('15:00' in r['puntualidad']['motivo'] and '30:00' in r['puntualidad']['motivo'])
        self.assertEqual(r['desc_retraso'], 0)

    def test_justo_30_minutos_acumulados_sigue_en_tres_estrellas(self):
        self.assertEqual(self.evaluar(2400, 1800)['puntualidad']['estrellas'], 3.0)       # 30:00 exactos: aún sin descuento

    def test_dos_y_media_estrellas_con_medio_dia_de_descuento(self):
        r = self.evaluar(3000, 2400)                                                       # 40 min acumulados
        self.assertEqual((r['puntualidad']['estrellas'], r['puntualidad']['etiqueta'], r['puntualidad']['color']),
                         (2.5, 'Regular (con descuento)', '#f59e0b'))
        self.assertIn('medio día de descuento', r['puntualidad']['motivo'])

    def test_dos_estrellas_con_un_dia_de_descuento(self):
        r = self.evaluar(3600, 3000)                                                       # 50 min
        self.assertEqual((r['puntualidad']['estrellas'], r['puntualidad']['etiqueta']), (2.0, 'Mala'))
        self.assertIn('1 día de descuento', r['puntualidad']['motivo'])
        self.assertTrue(r['alerta'])

    def test_una_estrella_con_dos_dias_de_descuento(self):
        r = self.evaluar(4600, 4000)                                                       # 66:40
        self.assertEqual((r['puntualidad']['estrellas'], r['puntualidad']['etiqueta'], r['puntualidad']['color']),
                         (1.0, 'Muy mala', '#dc2626'))

    def test_cero_estrellas_pesima_con_tres_dias_o_mas(self):
        r = self.evaluar(6600, 6000)                                                       # 100 min
        self.assertEqual((r['puntualidad']['estrellas'], r['puntualidad']['etiqueta'], r['puntualidad']['color']),
                         (0.0, 'Pésima', '#7c3aed'))
        self.assertEqual(r['desc_retraso'], 3.0)

    def test_sin_ingresos_no_hay_estrellas_y_las_reentradas_no_cuentan(self):
        crear_reglas()
        p = self.prof()
        inf = construir_informes_mensuales([p], 2026, 10, local(OCT(1), 20, 0))[0].resumen
        self.assertIsNone(inf['puntualidad'])                    # no marcó nada: no hay ingresos que evaluar
        marca(p.user, OCT(1), 8, 0, 'ENTRADA', 'PUNTUAL', '1')
        marca(p.user, OCT(1), 10, 0, 'SALIDA', 'PUNTUAL', '1')
        marca(p.user, OCT(1), 10, 30, 'ENTRADA', 'PUNTUAL', '', 0)                          # re-entrada (sin bloque): no cuenta
        inf = construir_informes_mensuales([p], 2026, 10, local(OCT(1), 20, 0))[0].resumen
        self.assertEqual(inf['entradas'], 1)

    def test_estado_en_tolerancia_en_el_dia(self):
        crear_reglas()
        p = self.prof()
        self.jornada_con_retraso(p, OCT(1), 420, 0)
        d1 = construir_informes_mensuales([p], 2026, 10, local(OCT(1), 20, 0))[0].dias[0]
        self.assertEqual((d1.estado, d1.retraso_seg), ('tolerancia', 0))


class SemaforoAsistenciaTests(BaseAsistencia):
    """Viernes... evaluamos solo el lunes 5/oct (jornada partida: 2 bloques)."""
    AHORA = local(OCT(5), 20, 0)
    contador = [0]

    def prof(self):
        self.contador[0] += 1
        return crear_prof(f'sm{self.contador[0]}', self.zona, control=OCT(5))

    def informe(self, p):
        inf = construir_informes_mensuales([p], 2026, 10, self.AHORA)[0]
        return inf, {x.fecha.day: x for x in inf.dias}[5]

    def permiso(self, p, bloque='', tipo='medico'):
        return PermisoAsistencia.objects.create(user=p.user, fecha=OCT(5), bloque=bloque, tipo=tipo,
                                                detalle='Certificado médico presentado por escrito')

    def test_verde_si_vino_todos_los_dias(self):
        p = self.prof(); jornada(p.user, OCT(5))
        inf, dia = self.informe(p)
        self.assertEqual(inf.resumen['asistencia']['nivel'], 'verde')
        self.assertEqual(dia.estado, 'puntual')

    def test_rojo_si_falto_sin_aviso(self):
        p = self.prof()
        inf, dia = self.informe(p)
        r = inf.resumen
        self.assertEqual((dia.estado, dia.falta_dias), ('falta', 1.0))
        self.assertEqual((r['asistencia']['nivel'], r['desc_faltas'], r['desc_total']), ('rojo', 1.0, 1.0))
        self.assertIn('sin justificar', r['asistencia']['motivo'])
        self.assertTrue(r['alerta'])

    def test_amarillo_si_falto_pero_tenia_permiso(self):
        p = self.prof(); self.permiso(p)
        inf, dia = self.informe(p)
        r = inf.resumen
        self.assertEqual((dia.estado, dia.falta_dias, dia.permiso_dias), ('permiso', 0.0, 1.0))
        self.assertEqual(dia.permiso_texto, 'Permiso: Certificado médico')
        self.assertEqual((r['asistencia']['nivel'], r['asistencia']['etiqueta']), ('amarillo', 'Regular'))
        self.assertEqual((r['desc_faltas'], r['faltas_justificadas'], r['desc_total'], r['dias_con_permiso']), (0, 1.0, 0, 1))
        self.assertIn('permiso justificado', r['asistencia']['motivo'])

    def test_permiso_solo_de_un_bloque(self):
        p = self.prof()
        marca(p.user, OCT(5), 8, 0, 'ENTRADA', 'PUNTUAL', '1'); marca(p.user, OCT(5), 13, 0, 'SALIDA', 'PUNTUAL', '1')
        self.permiso(p, bloque='2', tipo='autorizado')                                      # faltó la tarde, con permiso
        inf, dia = self.informe(p)
        self.assertEqual((dia.estado, dia.falta_dias, dia.permiso_dias), ('permiso', 0.0, 0.5))
        self.assertEqual(inf.resumen['asistencia']['nivel'], 'amarillo')
        self.assertEqual(dia.permiso_texto, 'Permiso: Permiso autorizado por escrito')

    def test_falta_parcialmente_justificada_sigue_en_rojo(self):
        p = self.prof(); self.permiso(p, bloque='1')                                        # justificado solo el bloque 1
        inf, dia = self.informe(p)
        self.assertEqual((dia.estado, dia.falta_dias, dia.permiso_dias, dia.bloques_falta), ('falta', 0.5, 0.5, [2]))
        r = inf.resumen
        self.assertEqual((r['asistencia']['nivel'], r['desc_faltas'], r['faltas_justificadas']), ('rojo', 0.5, 0.5))
        self.assertIn('Además tiene', r['asistencia']['motivo'])

    def test_un_permiso_de_todo_el_dia_no_pisa_los_marcados_hechos(self):
        p = self.prof(); jornada(p.user, OCT(5)); self.permiso(p)
        inf, dia = self.informe(p)
        self.assertEqual((dia.estado, dia.permiso_dias), ('puntual', 0.0))                  # vino: no hay nada que justificar
        self.assertEqual(inf.resumen['asistencia']['nivel'], 'verde')

    def test_el_permiso_no_afecta_al_retraso_ni_a_otros_dias(self):
        crear_reglas()
        p = self.prof(); self.permiso(p)
        inf = construir_informes_mensuales([p], 2026, 10, local(OCT(6), 20, 0))[0]
        d = {x.fecha.day: x for x in inf.dias}
        self.assertEqual((d[5].estado, d[6].estado), ('permiso', 'falta'))                  # el martes 6 sigue siendo falta
        self.assertEqual(inf.resumen['desc_faltas'], 1.0)


@override_settings(SESSION_COOKIE_AGE=60 * 60 * 24 * 365 * 5)
class PermisosJustificacionTests(BaseAsistencia):
    """Solo el administrador justifica, después de revisar el comprobante, y hasta el último día del mes."""
    AHORA = local(OCT(20), 10, 0)

    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser('root_perm', password='x')
        self.client.force_login(self.admin)
        self.p = crear_prof('perm', self.zona, control=OCT(1))
        self.url = reverse('asistencia:justificar_falta')

    def datos(self, fecha='2026-10-07', bloque='', detalle='Certificado médico del Dr. Pérez, reposo de un día',
              tipo='medico', **extra):
        return {'user': self.p.user.pk, 'fecha': fecha, 'bloque': bloque, 'tipo': tipo, 'detalle': detalle, **extra}

    def post(self, ahora=None, **kw):
        with mock.patch('django.utils.timezone.now', return_value=ahora or self.AHORA):
            return self.client.post(self.url, self.datos(**kw), follow=True)

    def mensajes(self, r):
        return [str(m) for m in r.context['messages']]

    def test_la_pantalla_lista_las_faltas_pendientes_con_su_plazo(self):
        with mock.patch('django.utils.timezone.now', return_value=self.AHORA):
            r = self.client.get(reverse('asistencia:justificaciones'), {'mes': 10, 'anio': 2026})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context['en_plazo'])
        self.assertEqual(r.context['plazo'], OCT(31))
        dias_pendientes = {dia.fecha.day for _inf, dia in r.context['pendientes']}
        self.assertTrue({1, 2, 3, 5, 6, 7, 8, 9}.issubset(dias_pendientes))               # todos los días con horario hasta hoy
        self.assertContains(r, 'Registrar permiso'); self.assertContains(r, 'hasta el <b>31/10/2026</b>')

    def test_justificar_un_dia_completo(self):
        r = self.post()
        self.assertTrue(any('Falta justificada' in m for m in self.mensajes(r)))
        pm = PermisoAsistencia.objects.get()
        self.assertEqual((pm.user, pm.fecha, pm.bloque, pm.tipo, pm.registrado_por), (self.p.user, OCT(7), '', 'medico', self.admin))
        inf = construir_informes_mensuales([self.p], 2026, 10, self.AHORA)[0]
        d7 = {x.fecha.day: x for x in inf.dias}[7]
        self.assertEqual((d7.estado, d7.falta_dias), ('permiso', 0.0))

    def test_justificar_un_bloque(self):
        jornada(self.p.user, OCT(7), ent2=None, sal2=None)                                 # vino en la mañana, faltó la tarde
        self.post(bloque='2')
        self.assertEqual(PermisoAsistencia.objects.get().bloque, '2')
        inf = construir_informes_mensuales([self.p], 2026, 10, self.AHORA)[0]
        self.assertEqual({x.fecha.day: x for x in inf.dias}[7].estado, 'permiso')

    def test_bloque_que_no_esta_en_falta_o_dia_que_no_es_falta(self):
        jornada(self.p.user, OCT(7), ent2=None, sal2=None)
        self.assertTrue(any('no figura como falta' in m for m in self.mensajes(self.post(bloque='1'))))
        self.assertTrue(any('no figura como falta' in m for m in self.mensajes(self.post(fecha='2026-10-04'))))   # domingo
        self.assertTrue(any('no figura como falta' in m for m in self.mensajes(self.post(fecha='2026-10-08', bloque='abc'))))
        self.assertEqual(PermisoAsistencia.objects.count(), 0)

    def test_el_detalle_del_justificativo_es_obligatorio(self):
        r = self.post(detalle='ok')
        self.assertTrue(any('justificativo' in m for m in self.mensajes(r)))
        self.assertEqual(PermisoAsistencia.objects.count(), 0)

    def test_plazo_hasta_el_ultimo_dia_del_mes_a_cualquier_hora(self):
        r = self.post(ahora=local(OCT(31), 23, 59))                                        # último día, casi medianoche: se acepta
        self.assertTrue(any('Falta justificada' in m for m in self.mensajes(r)))
        PermisoAsistencia.objects.all().delete()
        r = self.post(ahora=local(NOV(1), 0, 5))                                           # 1.º de noviembre: el plazo venció
        self.assertTrue(any('plazo' in m and '31/10/2026' in m for m in self.mensajes(r)))
        self.assertEqual(PermisoAsistencia.objects.count(), 0)

    def test_datos_invalidos(self):
        with mock.patch('django.utils.timezone.now', return_value=self.AHORA):
            r = self.client.post(self.url, {'user': 'x', 'fecha': 'no-es-fecha'}, follow=True)
            self.assertTrue(any('inválidos' in str(m) for m in r.context['messages']))
            r = self.client.post(self.url, self.datos() | {'user': 99999}, follow=True)
            self.assertTrue(any('No se encontró' in str(m) for m in r.context['messages']))
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_comprobante_adjunto(self):
        import tempfile
        from django.core.files.uploadedfile import SimpleUploadedFile
        with tempfile.TemporaryDirectory() as tmp, override_settings(MEDIA_ROOT=tmp):
            archivo = SimpleUploadedFile('certificado.pdf', b'%PDF-1.4 certificado de prueba', content_type='application/pdf')
            self.post(comprobante=archivo)
            pm = PermisoAsistencia.objects.get()
            self.assertTrue(pm.comprobante and pm.comprobante.name.endswith('.pdf'))
            self.assertEqual(pm.comprobante.read(), b'%PDF-1.4 certificado de prueba')
            with mock.patch('django.utils.timezone.now', return_value=self.AHORA):
                self.assertContains(self.client.get(reverse('asistencia:justificaciones'), {'mes': 10, 'anio': 2026}),
                                    'ver comprobante')

    def test_los_permisos_registrados_se_ven_en_la_pantalla(self):
        self.post()
        with mock.patch('django.utils.timezone.now', return_value=self.AHORA):
            r = self.client.get(reverse('asistencia:justificaciones'), {'mes': 10, 'anio': 2026})
        self.assertContains(r, 'Permisos registrados'); self.assertContains(r, 'Certificado médico del Dr. Pérez')
        self.assertEqual(len(r.context['permisos']), 1)
        self.assertTrue(r.context['permisos'][0].puede_quitar)

    def test_quitar_un_permiso_solo_dentro_del_plazo(self):
        self.post()
        pm = PermisoAsistencia.objects.get()
        with mock.patch('django.utils.timezone.now', return_value=local(NOV(2), 9, 0)):          # mes cerrado
            r = self.client.post(reverse('asistencia:quitar_permiso', args=[pm.pk]), follow=True)
        self.assertTrue(any('ya cerró' in str(m) for m in r.context['messages']))
        self.assertTrue(PermisoAsistencia.objects.filter(pk=pm.pk).exists())
        with mock.patch('django.utils.timezone.now', return_value=local(OCT(25), 9, 0)):        # dentro del plazo
            self.client.post(reverse('asistencia:quitar_permiso', args=[pm.pk]), follow=True)
        self.assertFalse(PermisoAsistencia.objects.filter(pk=pm.pk).exists())
        inf = construir_informes_mensuales([self.p], 2026, 10, self.AHORA)[0]
        self.assertEqual({x.fecha.day: x for x in inf.dias}[7].estado, 'falta')                # vuelve a descontar

    def test_solo_el_administrador(self):
        self.client.force_login(self.p.user)
        self.assertEqual(self.client.get(reverse('asistencia:justificaciones')).status_code, 302)
        self.assertEqual(self.client.post(self.url, self.datos()).status_code, 302)
        pm = PermisoAsistencia.objects.create(user=self.p.user, fecha=OCT(7), tipo='medico', detalle='justificativo escrito')
        self.client.post(reverse('asistencia:quitar_permiso', args=[pm.pk]))
        self.assertTrue(PermisoAsistencia.objects.filter(pk=pm.pk).exists())
        self.assertEqual(PermisoAsistencia.objects.count(), 1)


@override_settings(SESSION_COOKIE_AGE=60 * 60 * 24 * 365 * 5)
class EvaluacionVistasTests(BaseAsistencia):
    """El indicador visual aparece en el panel, en Mi asistencia, en el informe y en el PDF (con su motivo)."""
    AHORA = local(OCT(20), 10, 0)

    def setUp(self):
        super().setUp()
        from servicios.models import Sucursal
        crear_reglas()
        self.suc = Sucursal.objects.create(nombre='Central', direccion='X')
        self.bueno = crear_prof('bueno', self.zona, apellido='Bueno', nombre='Ana', sucursal=self.suc)
        for d in (1, 2, 5, 6, 7, 8, 9, 12, 13, 14, 15, 16, 19, 20):                      # lunes a viernes: jornada partida
            jornada(self.bueno.user, OCT(d))
        for d in (3, 10, 17):                                                            # sábados: un solo bloque (08:00-12:00)
            marca(self.bueno.user, OCT(d), 8, 0, 'ENTRADA', 'PUNTUAL', '1')
            marca(self.bueno.user, OCT(d), 12, 0, 'SALIDA', 'PUNTUAL', '1')
        self.malo = crear_prof('malo', self.zona, apellido='Malo', nombre='Luis', sucursal=self.suc)       # nunca marcó: faltas
        self.admin = User.objects.create_superuser('root_ev', password='x')
        self.client.force_login(self.admin)

    def test_el_panel_muestra_la_evaluacion_y_avisa_a_quien_conviene_llamar(self):
        with mock.patch('django.utils.timezone.now', return_value=self.AHORA):
            r = self.client.get(reverse('asistencia:panel_admin'))
        filas = {f['user'].username: f for f in r.context['datos']}
        self.assertEqual(filas['malo']['eval']['asistencia']['nivel'], 'rojo')
        self.assertEqual(filas['bueno']['eval']['puntualidad']['estrellas'], 5.0)
        self.assertEqual([a['user'].username for a in r.context['alertas']], ['malo'])
        self.assertContains(r, 'Conviene conversar con 1 profesional')
        self.assertContains(r, 'Evaluación del mes')

    def test_mi_asistencia_muestra_estrellas_semaforo_y_motivo(self):
        self.client.force_login(self.bueno.user)
        with mock.patch('django.utils.timezone.now', return_value=self.AHORA):
            r = self.client.get(reverse('asistencia:mi_asistencia'), {'mes': 10, 'anio': 2026})
        self.assertEqual(r.context['resumen']['puntualidad']['estrellas'], 5.0)
        self.assertContains(r, 'Puntualidad del mes'); self.assertContains(r, 'Asistencia del mes')
        self.assertContains(r, 'Excelente'); self.assertContains(r, 'nunca usó su tolerancia')
        self.assertContains(r, 'Asistió a todos los días con horario')

    def test_mi_asistencia_de_alguien_sin_ficha_de_profesional_no_falla(self):
        u = crear_profesional('sinficha', zona=self.zona)
        self.client.force_login(u)
        r = self.client.get(reverse('asistencia:mi_asistencia'))
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.context['resumen'])

    def test_la_pantalla_del_informe_muestra_estrellas_y_semaforo_con_el_motivo(self):
        with mock.patch('django.utils.timezone.now', return_value=self.AHORA):
            r = self.client.get(reverse('asistencia:informe_mensual'), {'mes': 10, 'anio': 2026})
        self.assertContains(r, 'Puntualidad'); self.assertContains(r, 'Asistencia')
        self.assertContains(r, 'nunca usó su tolerancia')                  # motivo del 5★
        self.assertContains(r, 'Faltó sin justificar')                     # motivo del semáforo rojo
        self.assertContains(r, '#dc2626')

    def test_el_pdf_trae_la_evaluacion_y_los_motivos(self):
        inf = construir_informes_mensuales([self.bueno, self.malo], 2026, 10, self.AHORA)
        pdf = generar_informe_mensual_pdf(inf[:1], 'Profesional: Ana Bueno', compress=False)
        for esperado in (b'EVALUACI', b'PUNTUALIDAD', b'Excelente', b'nunca us', b'Buena', b'Asisti'):
            self.assertIn(esperado, pdf, esperado)
        resumen = generar_informe_mensual_pdf(inf, 'Sucursal: Central', compress=False)
        self.assertIn(b'Puntualidad: ', resumen)                           # motivo de cada profesional en el resumen del centro
        self.assertIn(b'Asistencia: ', resumen)
        self.assertEqual(paginas_pdf(resumen), 1 + 2)

    def test_el_pdf_muestra_los_permisos(self):
        PermisoAsistencia.objects.create(user=self.malo.user, fecha=OCT(7), tipo='medico', detalle='Certificado médico firmado')
        inf = construir_informes_mensuales([self.malo], 2026, 10, self.AHORA)
        pdf = generar_informe_mensual_pdf(inf, 'Profesional: Luis Malo', compress=False)
        self.assertIn(b'Permiso: Certificado', pdf)
        self.assertIn(b'Permiso', pdf)


class MigracionRetrasoTests(BaseAsistencia):
    """La conversión de datos antiguos: el retraso ya no cuenta la tolerancia."""

    def convertir(self):
        import importlib
        from django.apps import apps
        importlib.import_module('asistencia.migrations.0013_retraso_tramos_datos').convertir(apps, None)

    def registro(self, user, fecha, hora, minuto, minutos, bloque='1', zona=True):
        return RegistroAsistencia.objects.create(
            user=user, zona=self.zona if zona else None, tipo='ENTRADA', estado='TARDANZA', bloque=bloque,
            minutos_tardanza=minutos, fecha_hora=local(fecha, hora, minuto))

    def test_los_registros_antiguos_se_convierten_con_la_tolerancia_de_su_bloque(self):
        u = crear_profesional('mig', zona=self.zona)
        a = self.registro(u, LUNES, 8, 40, 40)                       # bloque 1 (tolerancia 10) -> (40-10) min = 1800 s
        b = self.registro(u, LUNES, 14, 25, 25, bloque='2')          # bloque 2 (tolerancia 15) -> (25-15) min = 600 s
        c = self.registro(u, SABADO, 8, 20, 20)                      # sábado (tolerancia 5)    -> (20-5) min = 900 s
        d = self.registro(u, LUNES, 8, 30, 30, zona=False)           # sin zona: tolerancia por defecto 10 -> 1200 s
        self.convertir()
        for reg, tarde, acum in ((a, 2400, 1800), (b, 1500, 600), (c, 1200, 900), (d, 1800, 1200)):
            reg.refresh_from_db()
            self.assertEqual((reg.segundos_tarde, reg.segundos_acumulables), (tarde, acum))
            self.assertEqual(reg.minutos_tardanza * 60, tarde)       # minutos_tardanza (informativo) no cambia

    def test_usa_el_horario_propio_del_profesional_y_es_idempotente(self):
        u = crear_profesional('mig2', zona=self.zona)
        crear_plantilla(self.zona, ['LUN'], [(T(8), T(13), 0)], user=u)
        ConfigAsistencia.objects.filter(user=u).update(personalizado=True)
        r = self.registro(u, LUNES, 8, 20, 20)
        self.convertir(); self.convertir()
        r.refresh_from_db()
        self.assertEqual(r.segundos_acumulables, 1200)               # tolerancia 0 de su horario propio: 20 min completos


# ══════════════════════════════════════════════════════════════════════════════
# ASUETOS (saldo, uso, efecto neutro) y REGLAS POR ALCANCE
# ══════════════════════════════════════════════════════════════════════════════

from decimal import Decimal
from . import asuetos as asu
from .models import DerechoAsueto, UsoAsueto
from .services import ResolvedorReglas


class AsuetosBase(BaseAsistencia):
    AHORA = local(OCT(20), 10, 0)

    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser('root_asu', password='x')
        self.p = crear_prof('ana', self.zona, control=OCT(1))

    def derecho(self, dias='0.5', **kw):
        return DerechoAsueto.objects.create(user=self.p.user, motivo='Día de la Mujer 2026',
                                            dias=Decimal(dias), **kw)

    def informe(self):
        return construir_informes_mensuales([self.p], 2026, 10, self.AHORA)[0]

    def dia(self, n):
        return {d.fecha.day: d for d in self.informe().dias}[n]


class AsuetoNeutroTests(AsuetosBase):
    def test_medio_dia_de_asueto_no_es_falta_ni_descuento(self):
        # martes 6: marca solo la mañana; la tarde (bloque 2) la toma como asueto
        jornada(self.p.user, OCT(6), ent2=None, sal2=None)
        asu.registrar_uso(self.derecho(), OCT(6), '2', self.admin)
        d = self.dia(6)
        self.assertEqual(d.falta_dias, 0.0)
        self.assertEqual(d.bloques_falta, [])
        self.assertAlmostEqual(d.asueto_dias, 0.5)
        self.assertIn('Día de la Mujer', d.asueto_texto)
        self.assertEqual(d.estado, 'puntual')

    def test_sin_asueto_esa_tarde_si_es_falta(self):
        jornada(self.p.user, OCT(6), ent2=None, sal2=None)
        self.assertEqual(self.dia(6).bloques_falta, [2])

    def test_dia_completo_en_asueto_es_neutro_y_no_cuenta_como_dia_con_horario(self):
        base = self.informe().resumen['dias_con_horario']
        asu.registrar_uso(self.derecho('1'), OCT(7), '', self.admin)
        inf = self.informe()
        d = {x.fecha.day: x for x in inf.dias}[7]
        self.assertEqual((d.estado, d.falta_dias, d.asueto_dias), ('asueto', 0.0, 1.0))
        self.assertEqual(inf.resumen['dias_con_horario'], base - 1)
        self.assertEqual(inf.resumen['dias_con_asueto'], 1)
        self.assertEqual(inf.resumen['asueto_dias'], 1.0)

    def test_horas_esperadas_no_incluyen_el_bloque_en_asueto(self):
        antes = self.informe().resumen['esperado_min']
        asu.registrar_uso(self.derecho(), OCT(7), '1', self.admin)         # bloque 1: 08-13 = 300 min
        self.assertEqual(self.informe().resumen['esperado_min'], antes - 300)

    def test_generar_ausentes_no_crea_ausencia_en_bloque_con_asueto(self):
        self.derecho('1')
        asu.registrar_uso(DerechoAsueto.objects.get(), OCT(6), '', self.admin)
        generar_ausentes(OCT(6), ahora=local(OCT(6), 23, 0))
        self.assertFalse(RegistroAsistencia.objects.filter(user=self.p.user, estado='AUSENTE').exists())

    def test_registrar_asueto_borra_el_ausente_ya_generado(self):
        generar_ausentes(OCT(6), ahora=local(OCT(6), 23, 0))
        self.assertEqual(RegistroAsistencia.objects.filter(user=self.p.user, estado='AUSENTE').count(), 2)
        asu.registrar_uso(self.derecho('1'), OCT(6), '', self.admin)
        self.assertFalse(RegistroAsistencia.objects.filter(user=self.p.user, estado='AUSENTE').exists())

    def test_panel_muestra_asueto(self):
        asu.registrar_uso(self.derecho('1'), OCT(6), '', self.admin)
        filas, resumen = construir_panel(OCT(6), ahora=local(OCT(6), 20, 0))
        fila = next(f for f in filas if f['user'] == self.p.user)
        self.assertEqual(fila['estado_dia'], 'asueto')
        self.assertEqual(resumen['asuetos'], 1)
        self.assertEqual(resumen['ausentes'], 0)

    def test_anular_el_uso_devuelve_saldo_y_vuelve_la_falta(self):
        d = self.derecho('1')
        uso = asu.registrar_uso(d, OCT(7), '', self.admin)
        self.assertEqual(DerechoAsueto.objects.get(pk=d.pk).saldo, 0)
        uso.delete()
        self.assertEqual(DerechoAsueto.objects.get(pk=d.pk).saldo, 1)
        self.assertEqual(self.dia(7).bloques_falta, [1, 2])


class AsuetoSaldoTests(AsuetosBase):
    def test_no_permite_pasarse_del_saldo(self):
        d = self.derecho('0.5')
        asu.registrar_uso(d, OCT(6), '1', self.admin)
        with self.assertRaisesMessage(asu.AsuetoError, 'saldo'):
            asu.registrar_uso(DerechoAsueto.objects.get(pk=d.pk), OCT(7), '1', self.admin)

    def test_dia_completo_necesita_un_dia_de_saldo(self):
        with self.assertRaises(asu.AsuetoError):
            asu.registrar_uso(self.derecho('0.5'), OCT(6), '', self.admin)

    def test_varios_dias_se_registran_fecha_por_fecha(self):
        d = self.derecho('2')
        asu.registrar_uso(d, OCT(6), '', self.admin)
        asu.registrar_uso(DerechoAsueto.objects.get(pk=d.pk), OCT(7), '', self.admin)
        self.assertEqual(DerechoAsueto.objects.get(pk=d.pk).saldo, 0)

    def test_respeta_el_vencimiento(self):
        d = self.derecho('1', vence_el=OCT(5))
        with self.assertRaisesMessage(asu.AsuetoError, 'vence'):
            asu.registrar_uso(d, OCT(6), '', self.admin)

    def test_no_se_puede_en_un_domingo_sin_horario(self):
        with self.assertRaisesMessage(asu.AsuetoError, 'no es un día con horario'):
            asu.registrar_uso(self.derecho('1'), DOMINGO, '', self.admin)

    def test_no_se_solapan_dos_asuetos_el_mismo_dia(self):
        d = self.derecho('2')
        asu.registrar_uso(d, OCT(6), '', self.admin)
        with self.assertRaisesMessage(asu.AsuetoError, 'solapa'):
            asu.registrar_uso(DerechoAsueto.objects.get(pk=d.pk), OCT(6), '1', self.admin)

    def test_bloque_inexistente(self):
        with self.assertRaisesMessage(asu.AsuetoError, 'bloque 3'):
            asu.registrar_uso(self.derecho('1'), OCT(6), '3', self.admin)

    def test_sabado_con_un_solo_bloque_usa_el_dia_completo(self):
        uso = asu.registrar_uso(self.derecho('1'), SABADO, '1', self.admin)
        self.assertEqual((uso.bloque, uso.dias), ('', Decimal(1)))


class OtorgarAsuetoTests(AsuetosBase):
    def setUp(self):
        super().setUp()
        self.b = crear_prof('beto', self.zona, apellido='Ruiz', control=OCT(1))
        self.c = crear_prof('carla', self.zona, apellido='Soto', control=OCT(1))

    def test_todos(self):
        self.assertEqual({u.username for u in asu.destinatarios('todos')}, {'ana', 'beto', 'carla'})

    def test_elegidos(self):
        users = asu.destinatarios('elegidos', user_ids=[self.b.user.pk])
        self.assertEqual([u.username for u in users], ['beto'])

    def test_por_sucursal(self):
        from servicios.models import Sucursal
        suc = Sucursal.objects.create(nombre='Norte')
        self.c.sucursales.add(suc)
        self.assertEqual([u.username for u in asu.destinatarios('sucursal', sucursal_ids=[suc.pk])], ['carla'])

    def test_por_zona(self):
        self.assertEqual(len(asu.destinatarios('zona', zona_ids=[self.zona.pk])), 3)

    def test_otorgar_no_duplica(self):
        users = asu.destinatarios('elegidos', user_ids=[self.p.user.pk, self.c.user.pk])
        self.assertEqual(asu.otorgar(users, 0.5, 'Día de la Mujer', OCT(8)), (2, 0))
        self.assertEqual(asu.otorgar(users, 0.5, 'Día de la Mujer', OCT(8)), (0, 2))
        self.assertEqual(DerechoAsueto.objects.count(), 2)

    def test_motivo_obligatorio_y_dias_positivos(self):
        with self.assertRaises(asu.AsuetoError):
            asu.otorgar([self.p.user], 1, '  ')
        with self.assertRaises(asu.AsuetoError):
            asu.otorgar([self.p.user], 0, 'x')

    def test_saldos_por_usuario_ignora_vencidos(self):
        asu.otorgar([self.p.user], 1, 'a', OCT(1), vence_el=OCT(2))
        asu.otorgar([self.p.user], 1, 'b', OCT(1))
        s = asu.saldos_por_usuario([self.p.user.pk], hoy=OCT(10))
        self.assertEqual(s[self.p.user.pk]['disponible'], 1)


class AsuetosVistasTests(AsuetosBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)
        self.url = reverse('asistencia:asuetos')

    def test_pantalla_carga(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Otorgar asueto')

    def test_otorgar_medio_dia_a_todos(self):
        r = self.client.post(self.url, {
            'accion': 'otorgar', 'motivo': 'Día de la Mujer', 'duracion': '0.5',
            'otorgado_el': '2026-10-13', 'destino': 'todos'}, follow=True)
        self.assertEqual(DerechoAsueto.objects.get().dias, Decimal('0.5'))
        self.assertContains(r, 'Asueto otorgado a 1 profesional')

    def test_otorgar_varios_dias_a_elegidos(self):
        self.client.post(self.url, {
            'accion': 'otorgar', 'motivo': 'Vacaciones', 'duracion': 'varios', 'dias_varios': '3',
            'otorgado_el': '2026-10-13', 'destino': 'elegidos', 'profesionales': [self.p.user.pk]})
        self.assertEqual(DerechoAsueto.objects.get().dias, Decimal('3'))

    def test_varios_dias_exige_cantidad(self):
        r = self.client.post(self.url, {
            'accion': 'otorgar', 'motivo': 'Vacaciones', 'duracion': 'varios',
            'otorgado_el': '2026-10-13', 'destino': 'todos'})
        self.assertContains(r, 'Indica cuántos días')
        self.assertEqual(DerechoAsueto.objects.count(), 0)

    def test_otorgar_a_elegidos_sin_elegir_da_error(self):
        r = self.client.post(self.url, {
            'accion': 'otorgar', 'motivo': 'x', 'duracion': '1', 'otorgado_el': '2026-10-13',
            'destino': 'elegidos'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Elige al menos un profesional')
        self.assertEqual(DerechoAsueto.objects.count(), 0)

    def test_usar_desde_la_pantalla_y_error_de_saldo(self):
        d = self.derecho('0.5')
        r = self.client.post(self.url, {'accion': 'usar', 'derecho': d.pk, 'fecha': '2026-10-06', 'bloque': '1'}, follow=True)
        self.assertEqual(UsoAsueto.objects.count(), 1)
        r = self.client.post(self.url, {'accion': 'usar', 'derecho': d.pk, 'fecha': '2026-10-07', 'bloque': '1'})
        self.assertEqual(UsoAsueto.objects.count(), 1)           # el derecho ya no tiene saldo: no aparece / no se usa

    def test_anular_uso_y_eliminar_derecho(self):
        d = self.derecho('1')
        uso = asu.registrar_uso(d, OCT(6), '', self.admin)
        self.client.post(reverse('asistencia:eliminar_derecho_asueto', args=[d.pk]))
        self.assertTrue(DerechoAsueto.objects.filter(pk=d.pk).exists())          # tiene usos: no se borra
        self.client.post(reverse('asistencia:quitar_uso_asueto', args=[uso.pk]))
        self.client.post(reverse('asistencia:eliminar_derecho_asueto', args=[d.pk]))
        self.assertFalse(DerechoAsueto.objects.filter(pk=d.pk).exists())

    def test_solo_admin(self):
        self.client.logout()
        self.client.force_login(self.p.user)
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_mi_asistencia_muestra_el_saldo(self):
        self.derecho('0.5')
        self.client.logout(); self.client.force_login(self.p.user)
        r = self.client.get(reverse('asistencia:mi_asistencia'))
        self.assertContains(r, 'Mis asuetos')

    def test_pdf_con_asueto_se_genera(self):
        asu.registrar_uso(self.derecho('1'), OCT(6), '', self.admin)
        pdf = generar_informe_mensual_pdf([self.informe()], 'Test')
        self.assertTrue(pdf.startswith(b'%PDF'))


class ReglasPorAlcanceTests(BaseAsistencia):
    """Regla general + excepciones: gana profesional > sucursal > general; cada alcance con sus versiones."""

    def setUp(self):
        super().setUp()
        from servicios.models import Sucursal
        self.suc = Sucursal.objects.create(nombre='Norte')
        self.a = crear_prof('ana', self.zona, sucursal=self.suc)
        self.b = crear_prof('beto', self.zona)

    def regla(self, alcance='global', desde=None, tramos=((30, 0),), resto=1, hereda=False, **kw):
        r = ReglasAsistencia(vigente_desde=desde or dt.date(2000, 1, 1), alcance=alcance, hereda=hereda, **kw)
        r.save()
        r.tramos.all().delete()
        if not hereda:
            for h, d in tramos:
                TramoDescuento.objects.create(regla=r, hasta_minutos=h, dias=d)
            TramoDescuento.objects.create(regla=r, hasta_minutos=None, dias=resto)
        return r

    def tramos(self, prof, mes=10, anio=2026):
        return ResolvedorReglas(anio, mes).tramos(prof.user.pk, [s.pk for s in prof.sucursales.all()])

    def test_solo_general(self):
        self.regla()
        self.assertEqual(self.tramos(self.a), self.tramos(self.b))
        self.assertTrue(self.tramos(self.a))

    def test_sin_reglas_no_hay_descuento(self):
        self.assertEqual(self.tramos(self.a), [])

    def test_excepcion_de_sucursal(self):
        self.regla()
        self.regla('sucursal', sucursal=self.suc, tramos=((60, 0),), resto=2)
        self.assertEqual(self.tramos(self.a)[0][0], 3600)       # Ana (sucursal Norte) → 60 min
        self.assertEqual(self.tramos(self.b)[0][0], 1800)       # Beto sin sucursal → general

    def test_profesional_gana_a_sucursal(self):
        self.regla()
        self.regla('sucursal', sucursal=self.suc, tramos=((60, 0),), resto=2)
        self.regla('profesional', user=self.a.user, tramos=((90, 0),), resto=3)
        self.assertEqual(self.tramos(self.a)[0][0], 5400)

    def test_excepcion_sin_descuento(self):
        self.regla()
        self.regla('profesional', user=self.b.user, tramos=((0, 0),), resto=0)
        self.assertEqual(dias_descuento(7200, self.tramos(self.b)), 0)
        self.assertEqual(dias_descuento(7200, self.tramos(self.a)), 1)

    def test_excepcion_no_es_retroactiva(self):
        self.regla()
        self.regla('profesional', desde=OCT(1) + dt.timedelta(days=31), user=self.a.user, tramos=((90, 0),), resto=3)
        self.assertEqual(self.tramos(self.a, 10)[0][0], 1800)    # octubre sigue con la general
        self.assertEqual(self.tramos(self.a, 11)[0][0], 5400)    # desde noviembre rige la excepción

    def test_terminar_excepcion_vuelve_a_la_general(self):
        self.regla()
        self.regla('profesional', user=self.a.user, tramos=((90, 0),), resto=3)
        self.regla('profesional', desde=dt.date(2026, 11, 1), user=self.a.user, hereda=True)
        self.assertEqual(self.tramos(self.a, 10)[0][0], 5400)
        self.assertEqual(self.tramos(self.a, 11)[0][0], 1800)

    def test_informe_usa_la_regla_de_cada_profesional(self):
        self.regla()                                                    # general: >30 min → 1 día
        self.regla('profesional', user=self.b.user, tramos=((0, 0),), resto=0)
        for p in (self.a, self.b):                                      # 40 min de retraso acumulado cada uno
            marca(p.user, OCT(6), 8, 50, 'ENTRADA', 'TARDANZA', '1', 50, acum_seg=2400)
        inf = {i.profesional.pk: i for i in construir_informes_mensuales([self.a, self.b], 2026, 10, local(OCT(20), 10))}
        self.assertEqual(inf[self.a.pk].resumen['desc_retraso'], 1)
        self.assertEqual(inf[self.b.pk].resumen['desc_retraso'], 0)

    def test_pantalla_de_excepcion_guarda_en_su_alcance(self):
        admin = User.objects.create_superuser('root_reg', password='x')
        self.client.force_login(admin)
        self.regla()
        datos = datos_reglas([(60, 0)], 2, 11, 2026)
        datos.update({'alcance': 'profesional', 'profesional': self.a.user.pk})
        r = self.client.post(reverse('asistencia:reglas'), datos)
        self.assertEqual(r.status_code, 302)
        exc = ReglasAsistencia.objects.get(alcance='profesional')
        self.assertEqual((exc.user, exc.vigente_desde), (self.a.user, dt.date(2026, 11, 1)))
        self.assertEqual(ReglasAsistencia.objects.filter(alcance='global').count(), 1)     # la general no se tocó
        r = self.client.get(reverse('asistencia:reglas'), {'alcance': 'profesional', 'profesional': self.a.user.pk})
        self.assertContains(r, 'Estás editando la excepción')
        # terminar la excepción
        datos = datos_reglas([], 0, 12, 2026); datos.update({'alcance': 'profesional', 'profesional': self.a.user.pk, 'hereda': 'on'})
        self.client.post(reverse('asistencia:reglas'), datos)
        self.assertTrue(ReglasAsistencia.objects.get(alcance='profesional', vigente_desde=dt.date(2026, 12, 1)).hereda)

    def test_mi_asistencia_usa_su_regla(self):
        self.regla()
        self.regla('profesional', user=self.b.user, tramos=((90, 0),), resto=3)
        self.client.force_login(self.b.user)
        r = self.client.get(reverse('asistencia:mi_asistencia'))
        self.assertEqual(r.status_code, 200)
        self.assertIn('90', r.context['texto_regla'])


# ══════════════════════════════════════════════════════════════════════════════
# PERSONAL ACTIVO / INACTIVO
# ══════════════════════════════════════════════════════════════════════════════

class PersonalInactivoTests(AsuetosBase):
    """Un profesional dado de baja (Profesional.activo=False) sale de toda la asistencia y aparece en Inactivos."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)
        self.baja = crear_prof('beto', self.zona, control=OCT(1))
        self.baja.activo = False
        self.baja.save()

    def test_helper_separa_activos_e_inactivos(self):
        from .personal import profesionales_activos, profesionales_inactivos
        self.assertIn(self.p.user, profesionales_activos())
        self.assertNotIn(self.baja.user, profesionales_activos())
        self.assertIn(self.baja.user, profesionales_inactivos())
        self.assertNotIn(self.p.user, profesionales_inactivos())

    def test_usuario_desactivado_tambien_es_inactivo(self):
        from .personal import profesionales_activos, profesionales_inactivos
        self.p.user.is_active = False
        self.p.user.save()
        self.assertNotIn(self.p.user, profesionales_activos())
        self.assertIn(self.p.user, profesionales_inactivos())

    def test_panel_y_enrolamiento_solo_muestran_activos(self):
        for name in ('asistencia:panel_admin', 'asistencia:enrolamiento'):
            r = self.client.get(reverse(name))
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, self.p.user.get_full_name())
            self.assertNotContains(r, self.baja.user.get_full_name())

    def test_pestana_inactivos_lista_al_de_baja(self):
        r = self.client.get(reverse('asistencia:inactivos'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, self.baja.user.get_full_name())
        self.assertNotContains(r, self.p.user.get_full_name())

    def test_todas_las_pantallas_traen_la_pestana_inactivos(self):
        for name in ('panel_admin', 'zonas_gps', 'horarios', 'fechas_especiales', 'asignaciones',
                     'enrolamiento', 'permisos', 'reglas', 'justificaciones', 'asuetos', 'informe_mensual'):
            r = self.client.get(reverse(f'asistencia:{name}'))
            self.assertEqual(r.status_code, 200, name)
            self.assertContains(r, reverse('asistencia:inactivos'), msg_prefix=name)

    def test_asueto_a_todos_no_alcanza_a_inactivos(self):
        self.client.post(reverse('asistencia:asuetos'), {
            'accion': 'otorgar', 'motivo': 'Feriado', 'duracion': '0.5',
            'otorgado_el': '2026-10-13', 'destino': 'todos'})
        self.assertTrue(DerechoAsueto.objects.filter(user=self.p.user).exists())
        self.assertFalse(DerechoAsueto.objects.filter(user=self.baja.user).exists())

    def test_boton_registrar_asueto_tiene_fondo_propio(self):
        r = self.client.get(reverse('asistencia:asuetos'))
        self.assertContains(r, 'btn-registrar-asueto')


# ══════════════════════════════════════════════════════════════════════════════
# LA BAJA NO ES RETROACTIVA
# ══════════════════════════════════════════════════════════════════════════════

class BajaNoRetroactivaTests(AsuetosBase):
    """
    Dar de baja a un profesional no reescribe el pasado: sus informes y el panel de los días en que estuvo
    activo siguen mostrándolo y se le evalúa hasta su baja. Nunca se oculta una marcación.
    Octubre 2026: lunes 5, martes 6, miércoles 7, jueves 8, viernes 9.
    """

    def setUp(self):
        super().setUp()
        from profesionales.models import Profesional
        self.client.force_login(self.admin)
        # Beto trabaja 5, 6 y 7 de octubre y se le da de baja el 9 (rige hasta el 8)
        self.beto = crear_prof('beto', self.zona, apellido='Bravo', control=OCT(1))
        for d in (5, 6, 7):
            jornada(self.beto.user, OCT(d))
        Profesional.objects.filter(pk=self.beto.pk).update(activo=False, fecha_baja=OCT(9))
        self.beto.refresh_from_db()
        # Carla trabajó en septiembre y se le dio de baja el 23/09
        self.carla = crear_prof('carla', self.zona, apellido='Cortez', control=dt.date(2026, 9, 1))
        jornada(self.carla.user, dt.date(2026, 9, 22))
        Profesional.objects.filter(pk=self.carla.pk).update(activo=False, fecha_baja=dt.date(2026, 9, 23))
        self.carla.refresh_from_db()

    def informe_beto(self):
        return construir_informes_mensuales([self.beto], 2026, 10, self.AHORA)[0]

    def test_informe_conserva_el_pasado_y_corta_en_la_baja(self):
        inf = self.informe_beto()
        dias = {d.fecha.day: d.estado for d in inf.dias}
        self.assertEqual(inf.control_hasta, OCT(8))
        for n in (5, 6, 7):
            self.assertNotEqual(dias[n], 'sin_control', f'día {n}: sus marcaciones deben verse')
        self.assertNotIn(dias[8], ('sin_control', 'futuro'))      # el día previo a la baja sí se evalúa
        for n in (9, 12, 15, 20, 30):
            self.assertEqual(dias[n], 'sin_control', f'día {n}: ya estaba de baja, no genera faltas')

    def test_despues_de_la_baja_no_hay_faltas(self):
        faltas = [d.fecha.day for d in self.informe_beto().dias if d.bloques_falta]
        self.assertTrue(faltas, 'las faltas anteriores a la baja se conservan')
        self.assertTrue(all(n <= 8 for n in faltas), f'faltas después de la baja: {faltas}')

    def test_nunca_se_oculta_una_marcacion_posterior_a_la_baja(self):
        from profesionales.models import Profesional
        jornada(self.beto.user, OCT(12))                          # marcó el 12 aunque la baja es del 9
        Profesional.objects.filter(pk=self.beto.pk).update(fecha_baja=OCT(9))
        from .personal import fin_control_por_usuario
        self.assertEqual(fin_control_por_usuario([self.beto.user.pk])[self.beto.user.pk], OCT(12))
        dias = {d.fecha.day: d.estado for d in self.informe_beto().dias}
        self.assertNotEqual(dias[12], 'sin_control')

    def test_baja_sin_fecha_rige_la_ultima_marcacion(self):
        from profesionales.models import Profesional
        from .personal import fin_control_por_usuario
        Profesional.objects.filter(pk=self.beto.pk).update(fecha_baja=None)
        self.assertEqual(fin_control_por_usuario([self.beto.user.pk])[self.beto.user.pk], OCT(7))

    def test_baja_sin_fecha_ni_marcaciones_no_tiene_control(self):
        from profesionales.models import Profesional
        from .personal import fin_control_por_usuario
        nuevo = crear_prof('dora', self.zona, control=OCT(1))
        Profesional.objects.filter(pk=nuevo.pk).update(activo=False, fecha_baja=None)
        self.assertIsNone(fin_control_por_usuario([nuevo.user.pk])[nuevo.user.pk])

    def test_fecha_baja_se_completa_y_se_limpia_sola(self):
        from profesionales.models import Profesional
        p = Profesional.objects.get(pk=self.p.pk)
        p.activo = False
        p.save()
        self.assertEqual(p.fecha_baja, timezone.localdate())
        p.activo = True
        p.save()
        p.refresh_from_db()
        self.assertIsNone(p.fecha_baja)

    def test_periodo_incluye_a_quien_estaba_activo(self):
        from .personal import profesionales_en_periodo
        octubre = profesionales_en_periodo(OCT(1), OCT(31))
        septiembre = profesionales_en_periodo(dt.date(2026, 9, 1), dt.date(2026, 9, 30))
        self.assertIn(self.beto.user, octubre)
        self.assertNotIn(self.carla.user, octubre)                # su control terminó en septiembre
        self.assertIn(self.carla.user, septiembre)
        self.assertIn(self.beto.user, septiembre)                 # estuvo activo todo septiembre
        self.assertIn(self.p.user, octubre)

    def test_pantalla_informe_mensual_por_mes(self):
        url = reverse('asistencia:informe_mensual')
        octubre = self.client.get(url, {'mes': 10, 'anio': 2026})
        self.assertContains(octubre, self.beto.nombre_completo)
        self.assertNotContains(octubre, self.carla.nombre_completo)
        septiembre = self.client.get(url, {'mes': 9, 'anio': 2026})
        self.assertContains(septiembre, self.carla.nombre_completo)

    def test_pdf_del_informe_de_un_mes_pasado_incluye_al_inactivo(self):
        r = self.client.get(reverse('asistencia:informe_mensual_pdf'), {'mes': 9, 'anio': 2026})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')

    def test_panel_de_un_dia_pasado_muestra_a_quien_estaba_activo(self):
        url = reverse('asistencia:panel_admin')
        antes = self.client.get(url, {'fecha': '2026-10-06'})
        self.assertContains(antes, self.beto.user.get_full_name())
        hoy = self.client.get(url)
        self.assertNotContains(hoy, self.beto.user.get_full_name())

    def test_selector_de_justificaciones_lista_al_que_estuvo_activo_ese_mes(self):
        url = reverse('asistencia:justificaciones')
        self.assertContains(self.client.get(url, {'mes': 9, 'anio': 2026}), self.carla.apellido)
        self.assertNotContains(self.client.get(url, {'mes': 10, 'anio': 2026}), self.carla.apellido)
