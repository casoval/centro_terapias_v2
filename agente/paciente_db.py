"""
agente/paciente_db.py
Consultas de solo lectura a la base de datos para el Agente Paciente.
NUNCA modifica datos — EXCEPTO mensajes de chat para notificaciones.

CAMPOS EXCLUIDOS INTENCIONALMENTE (información interna/clínica):
  - Sesion.notas_sesion          (notas clínicas/evolución)
  - Sesion.observaciones         (observaciones internas del profesional)
  - Proyecto.observaciones       (notas internas del proyecto)
  - Proyecto.observaciones_informe
  - Mensualidad.observaciones
"""

import logging
from datetime import date, timedelta

log = logging.getLogger('agente')


def _normalizar_telefono(telefono: str) -> str:
    """
    Normaliza un número de teléfono a su forma canónica SIN prefijo de país.
    Resultado: XXXXXXXX (8 dígitos bolivianos, sin 591 ni +591).
    Maneja: +591XXXXXXXX, 591XXXXXXXX, XXXXXXXX, espacios, guiones, paréntesis.
    """
    tel = telefono.strip().replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
    if tel.startswith('+591'):
        tel = tel[4:]
    elif tel.startswith('591') and len(tel) > 9:
        tel = tel[3:]
    return tel


def _tel_variantes(telefono: str) -> list:
    """
    Genera todas las variantes de formato posibles para un número,
    cubriendo cómo puede estar guardado en la BD.
    Cubre: XXXXXXXX | 591XXXXXXXX | +591XXXXXXXX
    """
    base = _normalizar_telefono(telefono)
    if not base:
        return []
    return list(dict.fromkeys([base, f'591{base}', f'+591{base}']))


def buscar_paciente_y_tutor(telefono: str):
    """
    Busca el paciente por teléfono del tutor e indica cuál tutor escribió.

    Retorna:
      - (paciente, cual_tutor)  → tutor con UN solo hijo activo
      - ('multiples', lista)    → tutor con VARIOS hijos activos (lista de dicts)
      - (None, None)            → número desconocido o error de datos

    La lista de 'multiples' contiene dicts con:
      {'paciente': obj, 'cual_tutor': 'tutor_1'|'tutor_2'}
    """
    try:
        from pacientes.models import Paciente
        tel = _normalizar_telefono(telefono)

        if not tel or not tel.isdigit():
            log.warning(f'[PacienteDB] Teléfono con formato inválido rechazado: {telefono!r}')
            return None, None

        variantes = _tel_variantes(telefono)

        # Buscar en tutor_1 y tutor_2 con todas las variantes
        matches_t1 = list(
            Paciente.objects.filter(telefono_tutor__in=variantes, estado='activo').distinct()
        )
        matches_t2 = list(
            Paciente.objects.filter(telefono_tutor_2__in=variantes, estado='activo').distinct()
        )

        # Deduplicar por ID (por si aparece en ambas listas)
        vistos = set()
        todos = []
        for p in matches_t1:
            if p.id not in vistos:
                vistos.add(p.id)
                todos.append({'paciente': p, 'cual_tutor': 'tutor_1'})
        for p in matches_t2:
            if p.id not in vistos:
                vistos.add(p.id)
                todos.append({'paciente': p, 'cual_tutor': 'tutor_2'})

        if len(todos) == 0:
            return None, None

        if len(todos) == 1:
            return todos[0]['paciente'], todos[0]['cual_tutor']

        # Múltiples hijos — el llamador debe manejar la selección
        log.info(
            f'[PacienteDB] {tel} es tutor de {len(todos)} pacientes activos: '
            f'{[d["paciente"].id for d in todos]}'
        )
        return 'multiples', todos

    except Exception as e:
        log.error(f'[PacienteDB] Error buscando por teléfono {telefono}: {e}')
        return None, None


def buscar_paciente_por_id(paciente_id: int, telefono: str):
    """
    Verifica que el teléfono sea tutor del paciente con ese ID.
    Retorna (paciente, cual_tutor) o (None, None) si no corresponde.
    Usado para validar la selección guardada en SelectorPaciente.
    """
    try:
        from pacientes.models import Paciente
        variantes = _tel_variantes(telefono)

        paciente = Paciente.objects.filter(id=paciente_id, estado='activo').first()
        if not paciente:
            return None, None

        if paciente.telefono_tutor in variantes:
            return paciente, 'tutor_1'
        if getattr(paciente, 'telefono_tutor_2', None) and paciente.telefono_tutor_2 in variantes:
            return paciente, 'tutor_2'

        return None, None
    except Exception as e:
        log.error(f'[PacienteDB] Error en buscar_paciente_por_id: {e}')
        return None, None


def buscar_paciente_por_telefono(telefono: str):
    """Wrapper de compatibilidad. Retorna solo el paciente (o None)."""
    paciente, _ = buscar_paciente_y_tutor(telefono)
    return paciente


def get_info_basica(paciente) -> dict:
    try:
        edad = None
        if paciente.fecha_nacimiento:
            hoy = date.today()
            fn  = paciente.fecha_nacimiento
            edad = hoy.year - fn.year - ((hoy.month, hoy.day) < (fn.month, fn.day))
        return {
            'nombre':             paciente.nombre,
            'apellido':           paciente.apellido,
            'nombre_completo':    getattr(paciente, 'nombre_completo', f'{paciente.nombre} {paciente.apellido}'),
            'nombre_tutor':       paciente.nombre_tutor,
            'nombre_tutor_2':     getattr(paciente, 'nombre_tutor_2', None) or '',
            'telefono_tutor_2':   getattr(paciente, 'telefono_tutor_2', None) or '',
            'edad':               edad,
            'estado':             paciente.estado,
        }
    except Exception as e:
        log.error(f'[PacienteDB] Error get_info_basica: {e}')
        return {}


def get_sesiones_proximas(paciente, dias: int = 30) -> list:
    """
    Sesiones programadas en los próximos N días (default 30).
    Incluye tipo de sesión (normal / mensualidad / proyecto).
    Las sesiones de hoy que ya pasaron en horario se marcan como
    'ya_pasada_hoy' para que el agente no las trate como futuras.
    """
    try:
        from agenda.models import Sesion
        from datetime import datetime
        import pytz

        TZ_BOLIVIA = pytz.timezone('America/La_Paz')
        ahora_bo   = datetime.now(TZ_BOLIVIA)
        hoy        = ahora_bo.date()
        hora_ahora = ahora_bo.time()
        limite     = hoy + timedelta(days=dias)

        sesiones = Sesion.objects.filter(
            paciente=paciente, estado='programada',
            fecha__gte=hoy, fecha__lte=limite,
        ).select_related(
            'profesional', 'servicio', 'sucursal', 'mensualidad', 'proyecto'
        ).order_by('fecha', 'hora_inicio')

        resultado = []
        for s in sesiones:
            if s.mensualidad:
                tipo_sesion   = 'mensualidad'
                monto_display = None
            elif s.proyecto:
                tipo_sesion   = 'proyecto/evaluacion'
                monto_display = None
            else:
                tipo_sesion   = 'sesion_normal'
                monto_display = float(s.monto_cobrado) if s.monto_cobrado else 0

            # Sesiones de HOY cuya hora_fin ya pasó → marcar para que el agente
            # no las presente como "próximas" sino como ya ocurridas.
            ya_paso = False
            if s.fecha == hoy and s.hora_fin and s.hora_fin <= hora_ahora:
                ya_paso = True

            resultado.append({
                'id':             s.id,
                'fecha':          s.fecha.strftime('%d/%m/%Y'),
                'dia':            _nombre_dia(s.fecha.weekday()),
                'hora':           s.hora_inicio.strftime('%H:%M') if s.hora_inicio else '—',
                'hora_fin':       s.hora_fin.strftime('%H:%M') if s.hora_fin else '—',
                'duracion_min':   s.duracion_minutos,
                'servicio':       s.servicio.nombre if s.servicio else '—',
                'profesional':    f'{s.profesional.nombre} {s.profesional.apellido}' if s.profesional else '—',
                'profesional_id': s.profesional.id if s.profesional else None,
                'sucursal':       s.sucursal.nombre if s.sucursal else '—',
                'sucursal_id':    s.sucursal.id if s.sucursal else None,
                'tipo_sesion':    tipo_sesion,
                'monto':          monto_display,
                'ya_paso_hoy':    ya_paso,  # True si la hora de fin ya pasó hoy
                'mensualidad_id': s.mensualidad.id if s.mensualidad else None,
                'proyecto_id':    s.proyecto.id if s.proyecto else None,
            })
        return resultado
    except Exception as e:
        log.error(f'[PacienteDB] Error get_sesiones_proximas: {e}')
        return []


def get_sesiones_recientes(paciente, limite: int = 8) -> list:
    """
    Últimas N sesiones completadas/con estado final.
    Incluye tipo para que el agente sepa si el monto aplica.
    """
    try:
        from agenda.models import Sesion
        ESTADOS = {
            'realizada':         'Realizada',
            'realizada_retraso': 'Realizada con retraso',
            'permiso':           'Permiso',
            'falta':             'Falta sin aviso',
            'cancelada':         'Cancelada',
            'reprogramada':      'Reprogramada',
        }
        sesiones = Sesion.objects.filter(
            paciente=paciente,
            estado__in=list(ESTADOS.keys()),
        ).select_related(
            'profesional', 'servicio', 'sucursal', 'mensualidad', 'proyecto'
        ).order_by('-fecha', '-hora_inicio')[:limite]

        return [{
            'id':          s.id,
            'fecha':       s.fecha.strftime('%d/%m/%Y'),
            'dia':         _nombre_dia(s.fecha.weekday()),
            'hora':        s.hora_inicio.strftime('%H:%M') if s.hora_inicio else '—',
            'servicio':    s.servicio.nombre if s.servicio else '—',
            'profesional': f'{s.profesional.nombre} {s.profesional.apellido}' if s.profesional else '—',
            'sucursal':    s.sucursal.nombre if s.sucursal else '—',
            'estado':      ESTADOS.get(s.estado, s.estado),
            'tipo_sesion': 'mensualidad' if s.mensualidad else ('proyecto/evaluacion' if s.proyecto else 'sesion_normal'),
            'monto':       float(s.monto_cobrado) if (s.monto_cobrado and not s.mensualidad and not s.proyecto) else None,
            'minutos_retraso': s.minutos_retraso if s.estado == 'realizada_retraso' else None,
            'reprogramada_al': s.fecha_reprogramada.strftime('%d/%m/%Y') if s.fecha_reprogramada else None,
        } for s in sesiones]
    except Exception as e:
        log.error(f'[PacienteDB] Error get_sesiones_recientes: {e}')
        return []


def get_cuenta_corriente(paciente) -> dict:
    """
    Retorna el resumen completo de la cuenta corriente.
    Incluye todos los campos relevantes de CuentaCorriente,
    equivalente a lo que el tutor ve en mi_cuenta.html.
    """
    try:
        from facturacion.models import CuentaCorriente
        cuenta = CuentaCorriente.objects.filter(paciente=paciente).first()
        if not cuenta:
            return {}

        saldo_actual = float(cuenta.saldo_actual or 0)
        saldo_real   = float(cuenta.saldo_real or 0)

        return {
            # Vista "Mi Cuenta" — resumen
            'consumo_total':              float(cuenta.total_consumido_actual or 0),
            'consumo_total_con_futuras':  float(cuenta.total_consumido_real or 0),
            'pagado_total':               float(cuenta.total_pagado or 0),
            'balance_final':              saldo_actual,   # positivo=crédito, negativo=deuda
            'balance_con_futuras':        saldo_real,

            # Crédito disponible (pagos adelantados sin consumir)
            'credito_disponible':         float(cuenta.pagos_adelantados or 0),
            'pagos_sin_asignar':          float(cuenta.pagos_sin_asignar or 0),

            # Desglose por categoría
            'total_sesiones':             float(cuenta.total_sesiones_normales_real or 0),
            'total_sesiones_programadas': float(cuenta.total_sesiones_programadas or 0),
            'total_mensualidades':        float(cuenta.total_mensualidades or 0),
            'total_proyectos':            float(cuenta.total_proyectos_real or 0),

            # Pagos por categoría
            'pagado_sesiones':            float(cuenta.pagos_sesiones or 0),
            'pagado_mensualidades':       float(cuenta.pagos_mensualidades or 0),
            'pagado_proyectos':           float(cuenta.pagos_proyectos or 0),
            'total_devoluciones':         float(cuenta.total_devoluciones or 0),

            # Contadores
            'sesiones_realizadas_pendientes':  cuenta.num_sesiones_realizadas_pendientes or 0,
            'sesiones_programadas_pendientes': cuenta.num_sesiones_programadas_pendientes or 0,
            'mensualidades_activas':           cuenta.num_mensualidades_activas or 0,
            'proyectos_activos':               cuenta.num_proyectos_activos or 0,

            # Derivados para compatibilidad con código anterior
            'saldo_actual':  saldo_actual,
            'deuda':         abs(saldo_actual) if saldo_actual < 0 else 0,
            'credito':       saldo_actual if saldo_actual > 0 else 0,
            'total_pagado':  float(cuenta.total_pagado or 0),
            'total_consumido': float(cuenta.total_consumido_actual or 0),
        }
    except Exception as e:
        log.error(f'[PacienteDB] Error get_cuenta_corriente: {e}')
        return {}


def get_deudas_detalle(paciente) -> dict:
    """
    Retorna el detalle completo de deudas igual a lo que ve el tutor
    en la página mis_deudas — sesiones, proyectos y mensualidades.
    """
    try:
        from agenda.models import Sesion
        from decimal import Decimal

        sesiones_deuda      = []
        proyectos_deuda     = []
        mensualidades_deuda = []

        total_sesiones      = Decimal('0')
        total_proyectos     = Decimal('0')
        total_mensualidades = Decimal('0')

        # ── Sesiones normales con deuda ──────────────────────────────────────
        from facturacion.models import Pago as PagoModel
        from django.db.models import Sum as SumAgg

        sesiones = Sesion.objects.filter(
            paciente=paciente,
            mensualidad__isnull=True,
            proyecto__isnull=True,
        ).select_related('servicio', 'profesional', 'sucursal').order_by('fecha')

        for s in sesiones:
            costo  = Decimal(str(s.monto_cobrado or 0))
            pagado_result = PagoModel.objects.filter(sesion=s, anulado=False).aggregate(total=SumAgg('monto'))
            pagado = Decimal(str(pagado_result['total'] or 0))
            saldo  = costo - pagado
            if saldo > 0:
                sesiones_deuda.append({
                    'id':          s.id,
                    'fecha':       s.fecha.strftime('%d/%m/%Y'),
                    'dia':         _nombre_dia(s.fecha.weekday()),
                    'descripcion': f"{s.servicio.nombre if s.servicio else '—'} con {s.profesional.nombre_completo if s.profesional else '—'}",
                    'estado':      s.get_estado_display() if hasattr(s, 'get_estado_display') else s.estado,
                    'sucursal':    s.sucursal.nombre if s.sucursal else '—',
                    'costo':       float(costo),
                    'pagado':      float(pagado),
                    'saldo':       float(saldo),
                    'es_futura':   s.fecha >= date.today(),
                })
                total_sesiones += saldo

        # ── Proyectos/Evaluaciones con deuda ─────────────────────────────────
        try:
            from agenda.models import Proyecto
            proyectos = Proyecto.objects.filter(paciente=paciente).order_by('fecha_inicio')
            for p in proyectos:
                costo  = Decimal(str(getattr(p, 'costo_total', None) or 0))
                pagado = Decimal(str(getattr(p, 'pagado_neto', None) or (costo - costo)))
                saldo  = Decimal(str(getattr(p, 'saldo_pendiente', None) or (costo - pagado)))
                if saldo > 0:
                    proyectos_deuda.append({
                        'codigo':      p.codigo,
                        'descripcion': p.nombre or 'Proyecto/Evaluacion',
                        'tipo':        p.get_tipo_display() if hasattr(p, 'get_tipo_display') else getattr(p, 'tipo', '—'),
                        'estado':      p.get_estado_display() if hasattr(p, 'get_estado_display') else getattr(p, 'estado', '—'),
                        'costo':       float(costo),
                        'pagado':      float(pagado),
                        'saldo':       float(saldo),
                    })
                    total_proyectos += saldo
        except Exception as exc:
            log.warning(f'[PacienteDB] Error procesando proyectos en deudas: {exc}')

        # ── Mensualidades con deuda ───────────────────────────────────────────
        try:
            from agenda.models import Mensualidad
            mensualidades = Mensualidad.objects.filter(paciente=paciente).order_by('-anio', '-mes')
            for m in mensualidades:
                costo  = Decimal(str(getattr(m, 'costo_mensual', None) or 0))
                pagado = Decimal(str(getattr(m, 'pagado_neto', None) or 0))
                saldo  = Decimal(str(getattr(m, 'saldo_pendiente', None) or (costo - pagado)))
                if saldo > 0:
                    periodo = getattr(m, 'periodo_display', None) or f"{m.mes}/{m.anio}"
                    mensualidades_deuda.append({
                        'codigo':      m.codigo,
                        'descripcion': periodo,
                        'estado':      m.get_estado_display() if hasattr(m, 'get_estado_display') else getattr(m, 'estado', '—'),
                        'costo':       float(costo),
                        'pagado':      float(pagado),
                        'saldo':       float(saldo),
                    })
                    total_mensualidades += saldo
        except Exception as exc:
            log.warning(f'[PacienteDB] Error procesando mensualidades en deudas: {exc}')

        total_general = total_sesiones + total_proyectos + total_mensualidades

        return {
            'total_general':       float(total_general),
            'total_sesiones':      float(total_sesiones),
            'total_proyectos':     float(total_proyectos),
            'total_mensualidades': float(total_mensualidades),
            'sesiones':            sesiones_deuda,
            'proyectos':           proyectos_deuda,
            'mensualidades':       mensualidades_deuda,
        }

    except Exception as e:
        log.error(f'[PacienteDB] Error get_deudas_detalle: {e}')
        return {}


def get_pagos_detalle(paciente, mes: int = None, anio: int = None, todos: bool = False) -> dict:
    """
    Historial de pagos filtrado por mes/año o todos.
    Por defecto retorna el mes actual.
    """
    try:
        from facturacion.models import Pago
        from decimal import Decimal

        hoy = date.today()
        if todos:
            pagos_qs = Pago.objects.filter(paciente=paciente, anulado=False)
        else:
            m = mes or hoy.month
            a = anio or hoy.year
            pagos_qs = Pago.objects.filter(
                paciente=paciente,
                anulado=False,
                fecha_pago__month=m,
                fecha_pago__year=a,
            )

        pagos_qs = pagos_qs.select_related('metodo_pago').order_by('-fecha_pago')

        pagos_lista        = []
        total_pagado       = Decimal('0')
        total_devoluciones = Decimal('0')

        for p in pagos_qs:
            monto        = Decimal(str(p.monto or 0))
            es_devolucion = monto < 0

            pagos_lista.append({
                'fecha':          p.fecha_pago.strftime('%d/%m/%Y') if p.fecha_pago else '—',
                'recibo':         p.numero_recibo or '—',
                'metodo':         p.metodo_pago.nombre if p.metodo_pago else '—',
                'concepto':       p.concepto or '—',
                'monto':          float(abs(monto)),
                'es_devolucion':  es_devolucion,
            })

            if es_devolucion:
                total_devoluciones += abs(monto)
            else:
                total_pagado += monto

        return {
            'pagos':               pagos_lista,
            'total_pagado':        float(total_pagado),
            'total_devoluciones':  float(total_devoluciones),
            'total_neto':          float(total_pagado - total_devoluciones),
            'cantidad':            len(pagos_lista),
        }

    except Exception as e:
        log.error(f'[PacienteDB] Error get_pagos_detalle: {e}')
        return {}


def get_proyectos(paciente) -> list:
    """
    Todos los proyectos/evaluaciones del paciente.
    NO incluye observaciones ni notas clínicas internas.
    """
    try:
        from agenda.models import Proyecto
        proyectos = Proyecto.objects.filter(
            paciente=paciente,
        ).select_related(
            'servicio_base', 'profesional_responsable', 'sucursal'
        ).prefetch_related('sesiones').order_by('-fecha_inicio')

        ESTADOS_LABEL = {
            'programada':        'Programada',
            'realizada':         'Realizada',
            'realizada_retraso': 'Realizada con retraso',
            'falta':             'Falta sin aviso',
            'permiso':           'Permiso',
            'cancelada':         'Cancelada',
            'reprogramada':      'Reprogramada',
        }

        resultado = []
        for p in proyectos:
            sesiones = p.sesiones.select_related(
                'servicio', 'profesional'
            ).order_by('fecha', 'hora_inicio')
            conteo = {
                'total':         sesiones.count(),
                'programadas':   sesiones.filter(estado='programada').count(),
                'realizadas':    sesiones.filter(estado__in=['realizada', 'realizada_retraso']).count(),
                'con_retraso':   sesiones.filter(estado='realizada_retraso').count(),
                'permisos':      sesiones.filter(estado='permiso').count(),
                'faltas':        sesiones.filter(estado='falta').count(),
                'canceladas':    sesiones.filter(estado='cancelada').count(),
                'reprogramadas': sesiones.filter(estado='reprogramada').count(),
            }

            # Detalle individual de cada sesión del proyecto (sin notas ni observaciones)
            sesiones_detalle = []
            for s in sesiones:
                sesiones_detalle.append({
                    'fecha':      s.fecha.strftime('%d/%m/%Y'),
                    'dia':        _nombre_dia(s.fecha.weekday()),
                    'hora':       s.hora_inicio.strftime('%H:%M') if s.hora_inicio else '—',
                    'servicio':   s.servicio.nombre if s.servicio else '—',
                    'profesional': (
                        f"{s.profesional.nombre} {s.profesional.apellido}"
                        if s.profesional else '—'
                    ),
                    'estado':     ESTADOS_LABEL.get(s.estado, s.estado),
                    'minutos_retraso': s.minutos_retraso if s.estado == 'realizada_retraso' else None,
                })

            resultado.append({
                'codigo':             p.codigo,
                'nombre':             p.nombre,
                'tipo':               p.get_tipo_display(),
                'estado':             p.get_estado_display(),
                'servicio':           p.servicio_base.nombre if p.servicio_base else '—',
                'profesional':        f"{p.profesional_responsable.nombre} {p.profesional_responsable.apellido}" if p.profesional_responsable else '—',
                'sucursal':           p.sucursal.nombre if p.sucursal else '—',
                'fecha_inicio':       p.fecha_inicio.strftime('%d/%m/%Y'),
                'fecha_fin_est':      p.fecha_fin_estimada.strftime('%d/%m/%Y') if p.fecha_fin_estimada else '—',
                'fecha_fin_real':     p.fecha_fin_real.strftime('%d/%m/%Y') if p.fecha_fin_real else '—',
                'costo_total':        float(p.costo_total),
                'pagado':             float(p.pagado_neto),
                'saldo':              float(p.saldo_pendiente),
                'pagado_completo':    p.pagado_completo,
                'informe_entregado':  p.informe_entregado,
                'fecha_informe':      p.fecha_entrega_informe.strftime('%d/%m/%Y') if p.fecha_entrega_informe else '—',
                'tiene_informe_digital': bool(getattr(p, 'archivo_informe_drive_url', '')),
                'sesiones':           conteo,
                'sesiones_detalle':   sesiones_detalle,  # fechas individuales de cada sesión
            })
        return resultado
    except Exception as e:
        log.error(f'[PacienteDB] Error get_proyectos: {e}')
        return []


def get_mensualidades(paciente) -> list:
    """
    Todas las mensualidades del paciente con detalle completo.
    Incluye servicios, profesionales, sesiones por estado y pagos.
    NO incluye observaciones internas.
    """
    try:
        from agenda.models import Mensualidad
        mensualidades = Mensualidad.objects.filter(
            paciente=paciente,
        ).prefetch_related(
            'servicios_profesionales__servicio',
            'servicios_profesionales__profesional',
            'sesiones',
        ).select_related('sucursal').order_by('-anio', '-mes')

        ESTADOS_LABEL = {
            'programada':        'Programada',
            'realizada':         'Realizada',
            'realizada_retraso': 'Realizada con retraso',
            'falta':             'Falta sin aviso',
            'permiso':           'Permiso',
            'cancelada':         'Cancelada',
            'reprogramada':      'Reprogramada',
        }

        resultado = []
        for m in mensualidades:
            sesiones = m.sesiones.select_related(
                'servicio', 'profesional'
            ).order_by('fecha', 'hora_inicio')
            conteo = {
                'total':         sesiones.count(),
                'programadas':   sesiones.filter(estado='programada').count(),
                'realizadas':    sesiones.filter(estado__in=['realizada', 'realizada_retraso']).count(),
                'con_retraso':   sesiones.filter(estado='realizada_retraso').count(),
                'permisos':      sesiones.filter(estado='permiso').count(),
                'faltas':        sesiones.filter(estado='falta').count(),
                'canceladas':    sesiones.filter(estado='cancelada').count(),
                'reprogramadas': sesiones.filter(estado='reprogramada').count(),
            }

            # Detalle individual de cada sesión de la mensualidad (sin notas ni observaciones)
            sesiones_detalle = []
            for s in sesiones:
                sesiones_detalle.append({
                    'fecha':       s.fecha.strftime('%d/%m/%Y'),
                    'dia':         _nombre_dia(s.fecha.weekday()),
                    'hora':        s.hora_inicio.strftime('%H:%M') if s.hora_inicio else '—',
                    'servicio':    s.servicio.nombre if s.servicio else '—',
                    'profesional': (
                        f"{s.profesional.nombre} {s.profesional.apellido}"
                        if s.profesional else '—'
                    ),
                    'estado':      ESTADOS_LABEL.get(s.estado, s.estado),
                    'minutos_retraso': s.minutos_retraso if s.estado == 'realizada_retraso' else None,
                })

            servicios = []
            for sp in m.servicios_profesionales.select_related('servicio', 'profesional'):
                servicios.append(
                    f"{sp.servicio.nombre} con {sp.profesional.nombre} {sp.profesional.apellido}"
                )

            resultado.append({
                'codigo':           m.codigo,
                'periodo':          m.periodo_display,
                'mes':              m.mes,
                'anio':             m.anio,
                'estado':           m.get_estado_display(),
                'sucursal':         m.sucursal.nombre if m.sucursal else '—',
                'servicios':        servicios,
                'costo_mensual':    float(m.costo_mensual),
                'pagado':           float(m.pagado_neto),
                'saldo':            float(m.saldo_pendiente),
                'pagado_completo':  m.pagado_completo,
                'sesiones':         conteo,
                'sesiones_detalle': sesiones_detalle,  # fechas individuales de cada sesión
            })
        return resultado
    except Exception as e:
        log.error(f'[PacienteDB] Error get_mensualidades: {e}')
        return []


def get_sesiones_completo(paciente, mes: int = None, anio: int = None, todos: bool = False) -> dict:
    """
    Historial completo de sesiones del paciente con conteo por estado.
    Filtra por mes/año o trae todas.
    NO incluye notas clínicas ni observaciones internas.
    Incluye tipo de sesión para mostrar monto correctamente.
    """
    try:
        from agenda.models import Sesion

        hoy = date.today()
        if todos:
            sesiones_qs = Sesion.objects.filter(paciente=paciente)
        else:
            m = mes or hoy.month
            a = anio or hoy.year
            sesiones_qs = Sesion.objects.filter(
                paciente=paciente,
                fecha__month=m,
                fecha__year=a,
            )

        sesiones_qs = sesiones_qs.select_related(
            'servicio', 'profesional', 'sucursal', 'mensualidad', 'proyecto'
        ).order_by('-fecha', '-hora_inicio')

        ESTADOS_LABEL = {
            'programada':        'Programada',
            'realizada':         'Realizada',
            'realizada_retraso': 'Realizada con retraso',
            'falta':             'Falta sin aviso',
            'permiso':           'Permiso',
            'cancelada':         'Cancelada',
            'reprogramada':      'Reprogramada',
        }

        lista  = []
        conteo = {k: 0 for k in ESTADOS_LABEL}

        for s in sesiones_qs:
            conteo[s.estado] = conteo.get(s.estado, 0) + 1
            es_mensualidad = bool(s.mensualidad)
            es_proyecto    = bool(s.proyecto)

            item = {
                'id':          s.id,
                'fecha':       s.fecha.strftime('%d/%m/%Y'),
                'dia':         _nombre_dia(s.fecha.weekday()),
                'hora':        s.hora_inicio.strftime('%H:%M') if s.hora_inicio else '—',
                'servicio':    s.servicio.nombre if s.servicio else '—',
                'profesional': f"{s.profesional.nombre} {s.profesional.apellido}" if s.profesional else '—',
                'sucursal':    s.sucursal.nombre if s.sucursal else '—',
                'estado':      ESTADOS_LABEL.get(s.estado, s.estado),
                'tipo_sesion': 'mensualidad' if es_mensualidad else ('proyecto/evaluacion' if es_proyecto else 'sesion_normal'),
                # Monto solo si es sesión individual (no mensualidad ni proyecto)
                'monto':       float(s.monto_cobrado or 0) if (not es_mensualidad and not es_proyecto) else None,
                'minutos_retraso':    s.minutos_retraso if s.estado == 'realizada_retraso' else None,
                'fecha_reprogramada': s.fecha_reprogramada.strftime('%d/%m/%Y') if s.fecha_reprogramada else None,
            }
            lista.append(item)

        return {
            'sesiones': lista,
            'conteo':   conteo,
            'total':    len(lista),
        }
    except Exception as e:
        log.error(f'[PacienteDB] Error get_sesiones_completo: {e}')
        return {}


def get_pagos_recientes(paciente, limite: int = 5) -> list:
    try:
        from facturacion.models import Pago
        pagos = Pago.objects.filter(
            paciente=paciente, anulado=False,
        ).select_related('metodo_pago').order_by('-fecha_pago')[:limite]
        return [{
            'fecha':    p.fecha_pago.strftime('%d/%m/%Y') if p.fecha_pago else '—',
            'monto':    float(p.monto or 0),
            'metodo':   p.metodo_pago.nombre if p.metodo_pago else '—',
            'concepto': p.concepto or '—',
            'recibo':   p.numero_recibo or '—',
        } for p in pagos]
    except Exception as e:
        log.error(f'[PacienteDB] Error get_pagos_recientes: {e}')
        return []


def get_profesionales_del_paciente(paciente) -> list:
    """
    Profesionales que atienden o han atendido al paciente,
    con estadísticas de sesiones equivalentes a mis_profesionales.html.
    """
    try:
        from agenda.models import Sesion
        from django.db.models import Count, Q

        # Obtener todos los profesionales únicos
        profs_raw = Sesion.objects.filter(
            paciente=paciente,
            estado__in=['programada', 'realizada', 'realizada_retraso', 'permiso', 'falta', 'cancelada'],
        ).select_related('profesional', 'servicio').values(
            'profesional__id',
            'profesional__nombre',
            'profesional__apellido',
            'profesional__especialidad',
            'profesional__user_id',
            'servicio__nombre',
        ).distinct()

        # Agrupar por profesional
        prof_map  = {}
        serv_map  = {}  # servicios por profesional
        for row in profs_raw:
            pid = row['profesional__id']
            if not pid:
                continue
            if pid not in prof_map:
                prof_map[pid] = {
                    'id':          pid,
                    'user_id':     row['profesional__user_id'],
                    'nombre':      f"{row['profesional__nombre']} {row['profesional__apellido']}",
                    'especialidad': row['profesional__especialidad'] or '—',
                }
                serv_map[pid] = set()
            if row['servicio__nombre']:
                serv_map[pid].add(row['servicio__nombre'])

        resultado = []
        for pid, prof in prof_map.items():
            # Contar sesiones totales y realizadas (igual que mis_profesionales.html)
            total_sesiones = Sesion.objects.filter(
                paciente=paciente,
                profesional_id=pid,
            ).count()

            sesiones_realizadas = Sesion.objects.filter(
                paciente=paciente,
                profesional_id=pid,
                estado__in=['realizada', 'realizada_retraso'],
            ).count()

            # Próxima sesión con este profesional
            proxima = Sesion.objects.filter(
                paciente=paciente,
                profesional_id=pid,
                estado='programada',
                fecha__gte=date.today(),
            ).order_by('fecha', 'hora_inicio').first()

            resultado.append({
                'id':                pid,
                'user_id':           prof['user_id'],
                'nombre':            prof['nombre'],
                'especialidad':      prof['especialidad'],
                'servicios':         sorted(serv_map[pid]),
                'total_sesiones':    total_sesiones,
                'sesiones_realizadas': sesiones_realizadas,
                'proxima_sesion':    {
                    'fecha': proxima.fecha.strftime('%d/%m/%Y'),
                    'hora':  proxima.hora_inicio.strftime('%H:%M') if proxima.hora_inicio else '—',
                    'servicio': proxima.servicio.nombre if proxima.servicio else '—',
                    'sucursal': proxima.sucursal.nombre if proxima.sucursal else '—',
                } if proxima else None,
            })

        return resultado
    except Exception as e:
        log.error(f'[PacienteDB] Error get_profesionales_del_paciente: {e}')
        return []


def get_conteo_sesiones_mes_actual(paciente) -> dict:
    """
    Conteo rápido de estados de sesión en el mes actual.
    Útil para responder preguntas como "¿cuántas faltas tuve este mes?".
    """
    try:
        from agenda.models import Sesion
        hoy = date.today()
        sesiones = Sesion.objects.filter(
            paciente=paciente,
            fecha__month=hoy.month,
            fecha__year=hoy.year,
        )
        return {
            'mes':          hoy.month,
            'anio':         hoy.year,
            'programadas':  sesiones.filter(estado='programada').count(),
            'realizadas':   sesiones.filter(estado__in=['realizada', 'realizada_retraso']).count(),
            'permisos':     sesiones.filter(estado='permiso').count(),
            'faltas':       sesiones.filter(estado='falta').count(),
            'canceladas':   sesiones.filter(estado='cancelada').count(),
            'reprogramadas':sesiones.filter(estado='reprogramada').count(),
            'total':        sesiones.count(),
        }
    except Exception as e:
        log.error(f'[PacienteDB] Error get_conteo_sesiones_mes_actual: {e}')
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# NOTIFICACIONES — via chat del Asistente IA
# ─────────────────────────────────────────────────────────────────────────────

def _extraer_sesion_id(detalle: str) -> int:
    import re
    match = re.search(r'sesion_id:(\d+)', detalle)
    return int(match.group(1)) if match else 0


def _get_profesional_sesion(detalle: str, paciente) -> list:
    """
    Obtiene el profesional usando el sesion_id incluido en el detalle.
    Fallback: sesión más próxima del paciente.
    """
    from agenda.models import Sesion

    usuarios   = []
    sesion_id  = _extraer_sesion_id(detalle)

    if sesion_id:
        try:
            sesion = Sesion.objects.select_related('profesional__user').get(
                id=sesion_id, paciente=paciente
            )
            if sesion.profesional and sesion.profesional.user:
                usuarios.append(sesion.profesional.user)
                return usuarios
        except Sesion.DoesNotExist:
            log.warning(f'[PacienteDB] Sesion ID {sesion_id} no encontrada para paciente {paciente.id}')

    primera = Sesion.objects.filter(
        paciente=paciente,
        estado='programada',
        fecha__gte=date.today(),
    ).select_related('profesional__user').order_by('fecha', 'hora_inicio').first()

    if primera and primera.profesional and primera.profesional.user:
        usuarios.append(primera.profesional.user)
        log.info(f'[PacienteDB] Fallback: profesional de sesión más próxima (id={primera.id})')

    return usuarios


def _get_usuarios_a_notificar(paciente, detalle: str = '') -> list:
    """
    Profesional de la sesión + recepcionistas de la sucursal + gerentes + admins.
    """
    from django.contrib.auth.models import User

    usuarios = []
    vistos   = set()

    def agregar(user):
        if user and user.id not in vistos:
            vistos.add(user.id)
            usuarios.append(user)

    try:
        for u in _get_profesional_sesion(detalle, paciente):
            agregar(u)
    except Exception as e:
        log.error(f'[PacienteDB] Error obteniendo profesional sesión: {e}')

    try:
        sucursales = paciente.sucursales.all()
        for u in User.objects.filter(
            perfil__rol='recepcionista',
            perfil__sucursales__in=sucursales,
            is_active=True,
        ).distinct():
            agregar(u)
    except Exception as e:
        log.error(f'[PacienteDB] Error obteniendo recepcionistas: {e}')

    try:
        sucursales = paciente.sucursales.all()
        for u in User.objects.filter(
            perfil__rol='gerente',
            perfil__sucursales__in=sucursales,
            is_active=True,
        ).distinct():
            agregar(u)
    except Exception as e:
        log.error(f'[PacienteDB] Error obteniendo gerentes: {e}')

    try:
        for u in User.objects.filter(is_superuser=True, is_active=True):
            agregar(u)
    except Exception as e:
        log.error(f'[PacienteDB] Error obteniendo admins: {e}')

    return usuarios


def _get_usuarios_sin_profesional(paciente) -> list:
    """Recepcionistas + gerentes de la sucursal + admins. Sin profesionales."""
    from django.contrib.auth.models import User

    usuarios = []
    vistos   = set()

    def agregar(user):
        if user and user.id not in vistos:
            vistos.add(user.id)
            usuarios.append(user)

    try:
        sucursales = paciente.sucursales.all()
        for u in User.objects.filter(
            perfil__rol__in=['recepcionista', 'gerente'],
            perfil__sucursales__in=sucursales,
            is_active=True,
        ).distinct():
            agregar(u)
    except Exception as e:
        log.error(f'[PacienteDB] Error obteniendo recep/gerentes: {e}')

    try:
        for u in User.objects.filter(is_superuser=True, is_active=True):
            agregar(u)
    except Exception as e:
        log.error(f'[PacienteDB] Error obteniendo admins: {e}')

    return usuarios


def _enviar_notificacion_via_ia(destinatario, contenido: str) -> bool:
    """
    Envía la notificación al chat del Asistente IA del destinatario.
    """
    try:
        from chat.models import Conversacion, Mensaje, NotificacionChat
        from chat.ia_agent import get_o_crear_usuario_ia
        from django.db.models import Q

        usuario_ia = get_o_crear_usuario_ia()

        conv = Conversacion.objects.filter(
            Q(usuario_1=destinatario, usuario_2=usuario_ia) |
            Q(usuario_1=usuario_ia, usuario_2=destinatario)
        ).first()

        if not conv:
            conv = Conversacion.objects.create(
                usuario_1=usuario_ia,
                usuario_2=destinatario,
            )

        msg = Mensaje.objects.create(
            conversacion=conv,
            remitente=usuario_ia,
            contenido=contenido,
        )
        NotificacionChat.objects.create(
            usuario=destinatario,
            conversacion=conv,
            mensaje=msg,
        )
        conv.save()
        return True
    except Exception as e:
        log.error(f'[PacienteDB] Error enviando notif IA a {destinatario}: {e}')
        return False


def notificar_solicitud(paciente, tipo: str, detalle: str) -> int:
    """
    Notifica via chat del Asistente IA según el tipo de solicitud.
    Retorna el número de usuarios notificados.
    """
    TITULOS = {
        'permiso':              '📋 SOLICITUD DE PERMISO',
        'cancelacion':          '🚫 SOLICITUD DE CANCELACION',
        'reprogramacion':       '🔄 SOLICITUD DE REPROGRAMACION',
        'peticion_profesional': '⚡ PETICION AL PROFESIONAL',
        'peticion_centro':      '📩 PETICION AL CENTRO',
        'aviso_pago':           '💰 AVISO DE PAGO',
    }

    mensaje = (
        f"{TITULOS.get(tipo, '📩 SOLICITUD')}\n"
        f"Paciente: {paciente.nombre} {paciente.apellido}\n"
        f"Tutor: {paciente.nombre_tutor} — Tel: {paciente.telefono_tutor}\n"
        f"Detalle: {detalle}\n"
        f"Recibido por WhatsApp — requiere accion manual en el sistema"
    )

    if tipo in ('peticion_centro', 'aviso_pago'):
        usuarios = _get_usuarios_sin_profesional(paciente)
    else:
        usuarios = _get_usuarios_a_notificar(paciente, detalle)

    notificados = 0
    for usuario in usuarios:
        if _enviar_notificacion_via_ia(usuario, mensaje):
            notificados += 1
            log.info(f'[PacienteDB] Notificado via IA: {usuario.get_full_name() or usuario.username}')

    log.info(f'[PacienteDB] {tipo} para {paciente.nombre} — {notificados} usuarios notificados')
    return notificados


def notificar_solicitud_publico(telefono: str, tipo: str, detalle: str) -> int:
    """
    Notifica una solicitud de un usuario PÚBLICO (no registrado como paciente).
    """
    from django.contrib.auth.models import User

    TITULOS = {
        'solicitud_visita': '📅 NUEVO CONTACTO — Solicita visitar el centro',
        'caso_urgente':     '🚨 CONSULTA URGENTE — Canal WhatsApp Público',
    }

    mensaje = (
        f"{TITULOS.get(tipo, '📩 CONTACTO PÚBLICO')}\n"
        f"Teléfono: {telefono}\n"
        f"Detalle: {detalle}\n"
        f"Recibido por WhatsApp (canal público) — requiere seguimiento manual"
    )

    usuarios = []
    vistos   = set()

    def agregar(user):
        if user and user.id not in vistos:
            vistos.add(user.id)
            usuarios.append(user)

    try:
        for u in User.objects.filter(
            perfil__rol__in=['recepcionista', 'gerente'],
            is_active=True,
        ).distinct():
            agregar(u)
    except Exception as e:
        log.error(f'[PacienteDB] Error obteniendo recep/gerentes (público): {e}')

    try:
        for u in User.objects.filter(is_superuser=True, is_active=True):
            agregar(u)
    except Exception as e:
        log.error(f'[PacienteDB] Error obteniendo admins (público): {e}')

    notificados = 0
    for usuario in usuarios:
        if _enviar_notificacion_via_ia(usuario, mensaje):
            notificados += 1

    log.info(f'[PacienteDB] {tipo} público ({telefono}) — {notificados} usuarios notificados')
    return notificados


# ─────────────────────────────────────────────────────────────────────────────
# UTILIDADES
# ─────────────────────────────────────────────────────────────────────────────

def _nombre_dia(weekday: int) -> str:
    dias = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
    return dias[weekday] if 0 <= weekday <= 6 else '—'