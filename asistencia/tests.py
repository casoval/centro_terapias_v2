import datetime as dt
import json
from unittest import mock

import numpy as np
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    BloqueFechaEspecial, BloqueHorario, ConfigAsistencia, EnrolamientoFacial, FechaEspecial,
    PermisoReenrolamiento, PlantillaHorario, RegistroAsistencia, ZonaAsistencia,
)
from .services import (
    CalculadorEstado, ErrorEnrolamiento, HorarioDia, ResolvedorHorario, ValidadorAsistencia,
    calcular_estado_dia, construir_panel, generar_ausentes, procesar_enrolamiento,
    registrar_manual, registros_validos_del_dia,
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
    for i, (e, s, tol) in enumerate(bloques, start=1):
        BloqueHorario.objects.create(plantilla=p, orden=i, hora_entrada=e, hora_salida=s, tolerancia_minutos=tol)
    return p


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

        with self.assertNumQueries(6):                 # fijo, no crece con la cantidad de profesionales
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
            'nombre': 'Semana', 'dias': LUN_VIE,
            'bloques-TOTAL_FORMS': 3, 'bloques-INITIAL_FORMS': 0, 'bloques-MIN_NUM_FORMS': 0, 'bloques-MAX_NUM_FORMS': 4,
            'bloques-0-hora_entrada': '08:00', 'bloques-0-hora_salida': '13:00', 'bloques-0-tolerancia_minutos': 10,
            'bloques-1-hora_entrada': '14:00', 'bloques-1-hora_salida': '18:00', 'bloques-1-tolerancia_minutos': 15,
            'bloques-2-hora_entrada': '', 'bloques-2-hora_salida': '', 'bloques-2-tolerancia_minutos': 10,
        })
        self.assertRedirects(r, reverse('asistencia:horarios'))
        # Sábado continuo
        r = self.client.post(url, {
            'nombre': 'Sábado', 'dias': ['SAB'],
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
        data = {'nombre': '', 'dias': dias, 'bloques-TOTAL_FORMS': len(bloques),
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

    def test_editar_y_eliminar_plantilla(self):
        url = reverse('asistencia:editar_plantilla', args=[self.p_sabado.pk])
        self.assertContains(self.client.get(url), 'Sábado')
        r = self.client.post(reverse('asistencia:eliminar_plantilla', args=[self.p_sabado.pk]))
        self.assertRedirects(r, reverse('asistencia:horarios'))
        self.assertFalse(PlantillaHorario.objects.filter(pk=self.p_sabado.pk).exists())

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
                                              fecha_hora=local(LUNES, hora))
        RegistroAsistencia.objects.create(user=self.u, tipo='ENTRADA', estado='AUSENTE', bloque='1',
                                          fecha_hora=local(LUNES + dt.timedelta(days=1), 13))
        r = self.client.get(reverse('asistencia:mi_asistencia') + '?mes=10&anio=2026')
        self.assertEqual((r.context['presentes'], r.context['tardanzas'], r.context['ausentes'],
                          r.context['minutos_acum']), (1, 1, 1, 20))

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
