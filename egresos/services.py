# egresos/services.py
# Servicios de negocio para la app de egresos del centro.

import calendar
import logging
from decimal import Decimal
from datetime import date

from django.db import transaction
from django.db.models import Sum, Q
from django.db.models.functions import Coalesce
from django.core.exceptions import ValidationError
from django.utils import timezone

logger = logging.getLogger(__name__)


class EgresoService:
    """
    Servicio para registrar, anular y consultar egresos del centro.
    Todo egreso genera un número EGR-XXXX como respaldo.
    """

    @staticmethod
    @transaction.atomic
    def registrar_egreso(
        user,
        categoria_id,
        fecha,
        concepto,
        monto,
        metodo_pago_id,
        proveedor_id=None,
        periodo_mes=None,
        periodo_anio=None,
        numero_transaccion='',
        numero_documento_proveedor='',
        observaciones='',
        sucursal_id=None,
        sesiones_ids=None,
    ):
        """
        Registra un egreso y genera su número EGR-XXXX.
        Dispara recálculo del ResumenFinanciero del mes correspondiente.

        Args:
            user:                         Usuario que registra
            categoria_id:                 ID de CategoriaEgreso
            fecha:                        date — fecha de pago
            concepto:                     str — descripción del gasto
            monto:                        Decimal — monto en Bs.
            metodo_pago_id:               ID de MetodoPago (de facturacion)
            proveedor_id:                 ID de Proveedor (opcional)
            periodo_mes:                  int 1-12 (default: mes de la fecha)
            periodo_anio:                 int (default: año de la fecha)
            numero_transaccion:           str — N° de transferencia/cheque
            numero_documento_proveedor:   str — N° factura del proveedor
            observaciones:                str
            sucursal_id:                  ID de Sucursal (opcional)
            sesiones_ids:                 list[int] — IDs de Sesion (solo honorarios)

        Returns:
            Egreso: instancia creada
        """
        from egresos.models import Egreso

        monto = Decimal(str(monto))
        if monto <= 0:
            raise ValidationError('El monto del egreso debe ser mayor a cero.')

        mes_periodo  = periodo_mes  or fecha.month
        anio_periodo = periodo_anio or fecha.year

        egreso = Egreso(
            categoria_id=categoria_id,
            proveedor_id=proveedor_id,
            fecha=fecha,
            concepto=concepto,
            monto=monto,
            metodo_pago_id=metodo_pago_id,
            periodo_mes=mes_periodo,
            periodo_anio=anio_periodo,
            numero_transaccion=numero_transaccion,
            numero_documento_proveedor=numero_documento_proveedor,
            observaciones=observaciones,
            sucursal_id=sucursal_id,
            registrado_por=user,
        )
        egreso.full_clean(exclude=['numero_egreso'])
        egreso.save()

        # Vincular sesiones si se trata de un pago de honorarios
        if sesiones_ids:
            from agenda.models import Sesion
            sesiones = Sesion.objects.filter(id__in=sesiones_ids)
            egreso.sesiones_cubiertas.set(sesiones)

        # Recalcular snapshot financiero del período
        ResumenFinancieroService.recalcular_mes(mes_periodo, anio_periodo)

        logger.info(
            f'Egreso {egreso.numero_egreso} registrado por {user} — '
            f'Bs.{monto} ({egreso.categoria})'
        )
        return egreso

    @staticmethod
    @transaction.atomic
    def anular_egreso(user, egreso_id, motivo):
        """
        Anula un egreso existente.
        Recalcula el ResumenFinanciero del mes afectado.

        Args:
            user:      Usuario que anula
            egreso_id: ID del Egreso
            motivo:    str — motivo obligatorio

        Returns:
            Egreso: instancia anulada
        """
        from egresos.models import Egreso

        if not motivo or not motivo.strip():
            raise ValidationError('Debe especificar el motivo de anulación.')

        egreso = Egreso.objects.select_for_update().get(id=egreso_id)

        if egreso.anulado:
            raise ValidationError(
                f'El egreso {egreso.numero_egreso} ya está anulado.'
            )

        egreso.anulado          = True
        egreso.motivo_anulacion = motivo.strip()
        egreso.anulado_por      = user
        egreso.fecha_anulacion  = timezone.now()
        egreso.save()

        # Recalcular snapshot del mes al que pertenecía el egreso
        ResumenFinancieroService.recalcular_mes(
            egreso.periodo_mes, egreso.periodo_anio
        )

        logger.info(
            f'Egreso {egreso.numero_egreso} ANULADO por {user} — motivo: {motivo}'
        )
        return egreso

    @staticmethod
    def get_egresos_proveedor(proveedor_id, fecha_inicio=None, fecha_fin=None):
        """
        Retorna todos los egresos de un proveedor, opcionalmente filtrados por rango.
        Útil para ver el historial de pagos a un profesional externo.
        """
        from egresos.models import Egreso

        qs = Egreso.objects.filter(
            proveedor_id=proveedor_id,
            anulado=False
        ).select_related('categoria', 'metodo_pago')

        if fecha_inicio:
            qs = qs.filter(fecha__gte=fecha_inicio)
        if fecha_fin:
            qs = qs.filter(fecha__lte=fecha_fin)

        return qs.order_by('-fecha')

    @staticmethod
    def get_honorarios_profesional(profesional_id, fecha_inicio=None, fecha_fin=None):
        """
        Retorna todos los egresos de honorarios vinculados a un profesional.
        Requiere que el Profesional tenga un Proveedor vinculado.
        """
        from egresos.models import Egreso, Proveedor

        try:
            proveedor = Proveedor.objects.get(profesional_id=profesional_id)
        except Proveedor.DoesNotExist:
            return Egreso.objects.none()

        return EgresoService.get_egresos_proveedor(
            proveedor.id, fecha_inicio, fecha_fin
        )


class ResumenFinancieroService:
    """
    Servicio para calcular y almacenar snapshots financieros mensuales del centro.

    El método principal es recalcular_mes(), que se llama automáticamente
    desde signals.py al crear/anular un Egreso o al registrar un Pago.

    get_resumen_rango() sirve para reportes de rangos arbitrarios (trimestre, año).
    """

    # Mapa tipo → campo en ResumenFinanciero
    TIPO_A_CAMPO = {
        'arriendo':          'egresos_arriendo',
        'servicios_basicos': 'egresos_servicios_basicos',
        'personal':          'egresos_personal',
        'honorarios':        'egresos_honorarios',
        'equipamiento':      'egresos_equipamiento',
        'mantenimiento':     'egresos_mantenimiento',
        'marketing':         'egresos_marketing',
        'impuesto':          'egresos_impuestos',
        'seguro':            'egresos_seguros',
        'capacitacion':      'egresos_capacitacion',
        'otro':              'egresos_otros',
    }

    @staticmethod
    def recalcular_mes(mes, anio, sucursal=None):
        """
        Recalcula y persiste el snapshot financiero de un mes.

        - sucursal=None  → resumen GLOBAL (todos los ingresos y egresos sin filtro)
        - sucursal=X     → resumen de la sucursal X:
            · Ingresos: pagos de sesiones/mensualidades/proyectos de esa sucursal
            · Egresos:  egresos con sucursal=X  +  honorarios cuyas sesiones
                        pertenecen a esa sucursal (PagoHonorario)
        """
        from egresos.models import Egreso, ResumenFinanciero
        from facturacion.models import Pago, Devolucion
        from django.db.models import Q as DQ

        fecha_inicio = date(anio, mes, 1)
        fecha_fin    = date(anio, mes, calendar.monthrange(anio, mes)[1])
        _excl = {'metodo_pago__nombre': 'Uso de Crédito'}

        sid = sucursal.id if sucursal else None

        # ── 1. INGRESOS ───────────────────────────────────────────────────────
        if sid is None:
            # Global: todos los pagos del mes
            pagos_base = Pago.objects.filter(
                fecha_pago__range=(fecha_inicio, fecha_fin),
                anulado=False,
            ).exclude(**_excl)

            ingresos_brutos = pagos_base.aggregate(
                t=Coalesce(Sum('monto'), Decimal('0'))
            )['t']

            total_devoluciones = Devolucion.objects.filter(
                fecha_devolucion__range=(fecha_inicio, fecha_fin)
            ).aggregate(t=Coalesce(Sum('monto'), Decimal('0')))['t']

        else:
            # Por sucursal: pagos vinculados a objetos de esa sucursal
            from facturacion.models import DetallePagoMasivo
            from agenda.models import Sesion as Ses, Mensualidad as Men, Proyecto as Pro

            q_pago = DQ(fecha_pago__range=(fecha_inicio, fecha_fin), anulado=False)

            # Sesiones directas de la sucursal
            p_ses = Pago.objects.filter(
                q_pago, sesion__sucursal_id=sid,
                sesion__proyecto__isnull=True,
                sesion__mensualidad__isnull=True,
            ).exclude(**_excl).aggregate(t=Coalesce(Sum('monto'), Decimal('0')))['t']

            p_ses_masivo = DetallePagoMasivo.objects.filter(
                tipo='sesion',
                sesion__sucursal_id=sid,
                sesion__proyecto__isnull=True,
                sesion__mensualidad__isnull=True,
                pago__fecha_pago__range=(fecha_inicio, fecha_fin),
                pago__anulado=False,
            ).exclude(pago__metodo_pago__nombre='Uso de Crédito').aggregate(
                t=Coalesce(Sum('monto'), Decimal('0'))
            )['t']

            # Mensualidades de la sucursal
            p_mens = Pago.objects.filter(
                q_pago, mensualidad__sucursal_id=sid,
            ).exclude(**_excl).aggregate(t=Coalesce(Sum('monto'), Decimal('0')))['t']

            p_mens_masivo = DetallePagoMasivo.objects.filter(
                tipo='mensualidad', mensualidad__sucursal_id=sid,
                pago__fecha_pago__range=(fecha_inicio, fecha_fin),
                pago__anulado=False,
            ).exclude(pago__metodo_pago__nombre='Uso de Crédito').aggregate(
                t=Coalesce(Sum('monto'), Decimal('0'))
            )['t']

            # Proyectos de la sucursal
            p_proy = Pago.objects.filter(
                q_pago, proyecto__sucursal_id=sid,
            ).exclude(**_excl).aggregate(t=Coalesce(Sum('monto'), Decimal('0')))['t']

            p_proy_masivo = DetallePagoMasivo.objects.filter(
                tipo='proyecto', proyecto__sucursal_id=sid,
                pago__fecha_pago__range=(fecha_inicio, fecha_fin),
                pago__anulado=False,
            ).exclude(pago__metodo_pago__nombre='Uso de Crédito').aggregate(
                t=Coalesce(Sum('monto'), Decimal('0'))
            )['t']

            ingresos_brutos = p_ses + p_ses_masivo + p_mens + p_mens_masivo + p_proy + p_proy_masivo

            # Devoluciones vinculadas a esta sucursal
            total_devoluciones = (
                Devolucion.objects.filter(
                    fecha_devolucion__range=(fecha_inicio, fecha_fin),
                    mensualidad__sucursal_id=sid,
                ).aggregate(t=Coalesce(Sum('monto'), Decimal('0')))['t']
                +
                Devolucion.objects.filter(
                    fecha_devolucion__range=(fecha_inicio, fecha_fin),
                    proyecto__sucursal_id=sid,
                ).aggregate(t=Coalesce(Sum('monto'), Decimal('0')))['t']
            )

        ingresos_netos = ingresos_brutos - total_devoluciones

        # ── 2.5. INGRESOS ADICIONALES (reembolsos, donaciones, etc.) ─────────
        from egresos.models import IngresoAdicional
        ing_adic_qs = IngresoAdicional.objects.filter(
            periodo_mes=mes,
            periodo_anio=anio,
            anulado=False,
        )
        if sid is not None:
            ing_adic_qs = ing_adic_qs.filter(sucursal_id=sid)
        ingresos_adicionales = ing_adic_qs.aggregate(
            t=Coalesce(Sum('monto'), Decimal('0'))
        )['t']

        # ── 2. EGRESOS por tipo ───────────────────────────────────────────────
        def _total_tipo(tipo_nombre):
            qs = Egreso.objects.filter(
                periodo_mes=mes,
                periodo_anio=anio,
                anulado=False,
                categoria__tipo=tipo_nombre,
            )
            if sid is not None:
                if tipo_nombre == 'honorarios':
                    # Honorarios de sucursal: PagoHonorario cuyas sesiones
                    # pertenecen a esta sucursal
                    from egresos.models import PagoHonorario
                    egreso_ids = PagoHonorario.objects.filter(
                        sesiones__sucursal_id=sid,
                        egreso__periodo_mes=mes,
                        egreso__periodo_anio=anio,
                        egreso__anulado=False,
                    ).values_list('egreso_id', flat=True).distinct()
                    return Egreso.objects.filter(
                        id__in=egreso_ids
                    ).aggregate(t=Coalesce(Sum('monto'), Decimal('0')))['t']
                else:
                    # Egresos normales: filtrar por sucursal del egreso
                    qs = qs.filter(sucursal_id=sid)
            return qs.aggregate(t=Coalesce(Sum('monto'), Decimal('0')))['t']

        eg_arriendo      = _total_tipo('arriendo')
        eg_servicios     = _total_tipo('servicios_basicos')
        eg_personal      = _total_tipo('personal')
        eg_honorarios    = _total_tipo('honorarios')
        eg_equipamiento  = _total_tipo('equipamiento')
        eg_mantenimiento = _total_tipo('mantenimiento')
        eg_marketing     = _total_tipo('marketing')
        eg_impuestos     = _total_tipo('impuesto')
        eg_seguros       = _total_tipo('seguro')
        eg_capacitacion  = _total_tipo('capacitacion')
        eg_otros         = _total_tipo('otro')

        total_egresos = (
            eg_arriendo + eg_servicios + eg_personal + eg_honorarios +
            eg_equipamiento + eg_mantenimiento + eg_marketing +
            eg_impuestos + eg_seguros + eg_capacitacion + eg_otros
        )

        # ── 3. RESULTADO ──────────────────────────────────────────────────────
        # resultado = ingresos de pacientes + ingresos adicionales - egresos
        resultado_neto = ingresos_netos + ingresos_adicionales - total_egresos
        margen_base = ingresos_netos + ingresos_adicionales
        margen = (
            (resultado_neto / margen_base * Decimal('100')).quantize(Decimal('0.01'))
            if margen_base > 0
            else Decimal('0')
        )

        # ── 4. PERSISTIR SNAPSHOT ─────────────────────────────────────────────
        ResumenFinanciero.objects.update_or_create(
            mes=mes,
            anio=anio,
            sucursal=sucursal,
            defaults={
                'ingresos_brutos':           ingresos_brutos,
                'total_devoluciones':        total_devoluciones,
                'ingresos_netos':            ingresos_netos,
                'ingresos_adicionales':      ingresos_adicionales,
                'egresos_arriendo':          eg_arriendo,
                'egresos_servicios_basicos': eg_servicios,
                'egresos_personal':          eg_personal,
                'egresos_honorarios':        eg_honorarios,
                'egresos_equipamiento':      eg_equipamiento,
                'egresos_mantenimiento':     eg_mantenimiento,
                'egresos_marketing':         eg_marketing,
                'egresos_impuestos':         eg_impuestos,
                'egresos_seguros':           eg_seguros,
                'egresos_capacitacion':      eg_capacitacion,
                'egresos_otros':             eg_otros,
                'total_egresos':             total_egresos,
                'resultado_neto':            resultado_neto,
                'margen_porcentaje':         margen,
            }
        )

        sufijo = f'sucursal={sucursal}' if sucursal else 'global'
        logger.info(
            f'ResumenFinanciero recalculado: {str(mes).zfill(2)}/{anio} [{sufijo}] — '
            f'Ingresos: Bs.{ingresos_netos} | Egresos: Bs.{total_egresos} | '
            f'Resultado: Bs.{resultado_neto}'
        )

    @staticmethod
    def get_resumen_rango(fecha_inicio, fecha_fin, sucursal=None):
        """
        Retorna el resumen financiero ACUMULADO para un rango arbitrario de fechas.
        Agrega los snapshots mensuales ya calculados.

        Args:
            fecha_inicio: date
            fecha_fin:    date
            sucursal:     Sucursal o None

        Returns:
            dict con totales acumulados del rango
        """
        from egresos.models import ResumenFinanciero

        filtro = Q(anio__gt=fecha_inicio.year) | Q(
            anio=fecha_inicio.year, mes__gte=fecha_inicio.month
        )
        filtro &= (
            Q(anio__lt=fecha_fin.year) | Q(
                anio=fecha_fin.year, mes__lte=fecha_fin.month
            )
        )

        qs = ResumenFinanciero.objects.filter(filtro, sucursal=sucursal)

        totales = qs.aggregate(
            ingresos_brutos=    Coalesce(Sum('ingresos_brutos'),           Decimal('0')),
            total_devoluciones= Coalesce(Sum('total_devoluciones'),        Decimal('0')),
            ingresos_netos=     Coalesce(Sum('ingresos_netos'),            Decimal('0')),
            eg_arriendo=        Coalesce(Sum('egresos_arriendo'),          Decimal('0')),
            eg_servicios=       Coalesce(Sum('egresos_servicios_basicos'), Decimal('0')),
            eg_personal=        Coalesce(Sum('egresos_personal'),          Decimal('0')),
            eg_honorarios=      Coalesce(Sum('egresos_honorarios'),        Decimal('0')),
            eg_equipamiento=    Coalesce(Sum('egresos_equipamiento'),      Decimal('0')),
            eg_mantenimiento=   Coalesce(Sum('egresos_mantenimiento'),     Decimal('0')),
            eg_marketing=       Coalesce(Sum('egresos_marketing'),         Decimal('0')),
            eg_impuestos=       Coalesce(Sum('egresos_impuestos'),         Decimal('0')),
            eg_seguros=         Coalesce(Sum('egresos_seguros'),           Decimal('0')),
            eg_capacitacion=    Coalesce(Sum('egresos_capacitacion'),      Decimal('0')),
            eg_otros=           Coalesce(Sum('egresos_otros'),             Decimal('0')),
            total_egresos=      Coalesce(Sum('total_egresos'),             Decimal('0')),
            resultado_neto=     Coalesce(Sum('resultado_neto'),            Decimal('0')),
        )

        # Calcular margen del rango completo
        ingresos_netos = totales['ingresos_netos']
        resultado_neto = totales['resultado_neto']
        totales['margen_porcentaje'] = (
            (resultado_neto / ingresos_netos * Decimal('100')).quantize(Decimal('0.01'))
            if ingresos_netos > 0
            else Decimal('0')
        )
        totales['es_rentable'] = resultado_neto >= 0
        totales['periodo'] = {'inicio': fecha_inicio, 'fin': fecha_fin}
        totales['meses'] = qs.count()

        return totales

    @staticmethod
    def recalcular_todos(anio=None):
        """
        Recalcula todos los ResumenFinanciero existentes.
        Si se pasa anio, solo recalcula ese año.
        Útil como acción de admin masiva o para corregir datos históricos.
        """
        from egresos.models import ResumenFinanciero

        qs = ResumenFinanciero.objects.all()
        if anio:
            qs = qs.filter(anio=anio)

        count = 0
        for resumen in qs:
            ResumenFinancieroService.recalcular_mes(
                resumen.mes, resumen.anio, resumen.sucursal
            )
            count += 1

        # También calcular meses con egresos que no tienen ResumenFinanciero aún
        from egresos.models import Egreso
        meses_con_egresos = (
            Egreso.objects
            .filter(anulado=False)
            .values_list('periodo_mes', 'periodo_anio')
            .distinct()
        )
        for mes, anio_e in meses_con_egresos:
            if not ResumenFinanciero.objects.filter(mes=mes, anio=anio_e).exists():
                ResumenFinancieroService.recalcular_mes(mes, anio_e)
                count += 1

        logger.info(f'recalcular_todos: {count} meses recalculados')
        return count