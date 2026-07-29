from datetime import date, timedelta, datetime
from decimal import Decimal
from itertools import groupby
from django.db.models import Q, Count, Sum, F, OuterRef, Subquery, Case, When, Value, DecimalField
from django.db.models.functions import Coalesce
from django.db import transaction
import logging

from .models import Sesion
from pacientes.models import Paciente
from profesionales.models import Profesional
from servicios.models import Sucursal, TipoServicio

logger = logging.getLogger(__name__)

class CalendarService:

    @staticmethod
    def annotate_total_pagado(sesiones_qs):
        """
        ⚡ OPTIMIZACIÓN DE RENDIMIENTO
        Anota `total_pagado_sesion` (pagos directos + pagos masivos) sobre el
        QUERYSET completo en UNA sola consulta SQL, usando subqueries
        correlacionadas independientes (evita el "fan-out" que ocurriría si
        se sumaran ambas relaciones con JOIN en la misma anotación).

        Antes de esta optimización, cada sesión mostrada en el calendario
        (`sesion.pagado` en el template) disparaba 2 queries adicionales
        (una para pagos directos y otra para pagos masivos). Con 100-300
        sesiones visibles en una vista semanal/mensual, eso son 200-600
        queries extra solo para pintar la tabla.

        Al anotar aquí, la propiedad `Sesion.total_pagado` reutiliza este
        valor (ver `agenda/models.py`) y no vuelve a golpear la base de datos.

        NOTA IMPORTANTE: esto también corrige un bug previo donde el resumen
        de "Total pagado / Total pendiente" del calendario solo sumaba pagos
        directos y NO incluía pagos masivos (pagos que cubren varias sesiones
        con un solo recibo), subestimando lo realmente cobrado.
        """
        from facturacion.models import Pago, DetallePagoMasivo

        pagos_directos_sq = Pago.objects.filter(
            sesion=OuterRef('pk'), anulado=False
        ).order_by().values('sesion').annotate(
            total=Sum('monto')
        ).values('total')

        pagos_masivos_sq = DetallePagoMasivo.objects.filter(
            sesion=OuterRef('pk'), pago__anulado=False
        ).order_by().values('sesion').annotate(
            total=Sum('monto')
        ).values('total')

        return sesiones_qs.annotate(
            _pagos_directos_sesion=Coalesce(
                Subquery(pagos_directos_sq, output_field=DecimalField(max_digits=10, decimal_places=2)),
                Value(Decimal('0.00'), output_field=DecimalField(max_digits=10, decimal_places=2))
            ),
            _pagos_masivos_sesion=Coalesce(
                Subquery(pagos_masivos_sq, output_field=DecimalField(max_digits=10, decimal_places=2)),
                Value(Decimal('0.00'), output_field=DecimalField(max_digits=10, decimal_places=2))
            ),
            total_pagado_sesion=F('_pagos_directos_sesion') + F('_pagos_masivos_sesion')
        )

    @staticmethod
    def _marcar_sesiones_grupales(sesiones_lista):
        """
        Marca las sesiones que comparten exactamente la misma
        hora_inicio + servicio + profesional como 'grupales'.
        Agrega atributos temporales a cada objeto Sesion:
          es_grupal  : bool
          num_grupo  : int  (cuántos pacientes hay en ese slot)
          grupo_id   : str  (clave única del grupo, para agrupar visualmente en el template)
        """
        from collections import Counter
        clave = lambda s: (s.fecha, s.hora_inicio, s.servicio_id, s.profesional_id)
        conteos = Counter(clave(s) for s in sesiones_lista)
        for sesion in sesiones_lista:
            k = clave(sesion)
            sesion.es_grupal = conteos[k] > 1
            sesion.num_grupo = conteos[k]
            sesion.grupo_id = (
                f"{sesion.fecha.strftime('%Y%m%d')}"
                f"-{sesion.hora_inicio.strftime('%H%M')}"
                f"-{sesion.servicio_id}"
                f"-{sesion.profesional_id}"
            )

    @staticmethod
    def get_calendar_data(vista, fecha_base, sesiones):
        """
        Generate calendar structure based on view type.
        ✅ NUEVO: vista 'lista' no genera estructura especial
        """
        if vista == 'diaria':
            return CalendarService._generate_daily(fecha_base, sesiones)
        elif vista == 'mensual':
            return CalendarService._generate_monthly(fecha_base, sesiones)
        elif vista == 'lista':
            # Vista lista: marcar sesiones grupales para badge visual
            CalendarService._marcar_sesiones_grupales(list(sesiones))
            return {
                'sesiones': sesiones,
                'fecha': fecha_base,
                'tipo': 'lista'
            }
        else: # semanal
            dias_desde_lunes = fecha_base.weekday()
            fecha_inicio = fecha_base - timedelta(days=dias_desde_lunes)
            return CalendarService._generate_weekly(fecha_inicio, sesiones)

    @staticmethod
    def _generate_daily(fecha, sesiones):
        """
        ✅ CORREGIDO: Genera estructura diaria con sesiones agrupadas
        y cálculo de mostrar_linea_tarde (igual que vista semanal)
        """
        sesiones_dia = [s for s in sesiones if s.fecha == fecha]

        # ✅ Marcar sesiones grupales (mismo horario + servicio + profesional)
        CalendarService._marcar_sesiones_grupales(sesiones_dia)

        # Calcular si hay sesiones de mañana y tarde
        tiene_manana = any(s.hora_inicio.hour < 13 for s in sesiones_dia)
        tiene_tarde = any(s.hora_inicio.hour >= 13 for s in sesiones_dia)
        
        # Agrupar sesiones por hora
        sesiones_agrupadas = []
        if sesiones_dia:
            from itertools import groupby
            
            sesiones_ordenadas = sorted(sesiones_dia, key=lambda s: s.hora_inicio)
            
            grupos = []
            for hora, grupo_sesiones in groupby(sesiones_ordenadas, key=lambda s: s.hora_inicio.hour):
                grupos.append({
                    'hora': hora,
                    'sesiones': list(grupo_sesiones)
                })
            
            # ✅ CLAVE: Marcar SOLO el primer grupo >= 13 para mostrar la línea
            # SOLO si hay sesiones de mañana (tiene_manana = True)
            primer_tarde_encontrado = False
            for grupo in grupos:
                grupo['mostrar_linea_tarde'] = False
                if grupo['hora'] >= 13 and not primer_tarde_encontrado and tiene_manana:
                    grupo['mostrar_linea_tarde'] = True
                    primer_tarde_encontrado = True
            
            sesiones_agrupadas = grupos
        
        return {
            'fecha': fecha,
            'es_hoy': fecha == date.today(),
            'sesiones': sesiones_dia,
            'sesiones_agrupadas': sesiones_agrupadas,  # ✅ NUEVO
            'dia_nombre': fecha.strftime('%A'),
            'tiene_sesiones_manana': tiene_manana,  # ✅ NUEVO
            'tiene_sesiones_tarde': tiene_tarde,  # ✅ NUEVO
            'tipo': 'diaria'
        }

    @staticmethod
    def _generate_weekly(fecha_inicio, sesiones):
        dias = []
        for i in range(7):
            dia = fecha_inicio + timedelta(days=i)
            sesiones_dia = [s for s in sesiones if s.fecha == dia]

            # ✅ Marcar sesiones grupales (mismo horario + servicio + profesional)
            CalendarService._marcar_sesiones_grupales(sesiones_dia)

            # Optimization: Pre-calculate if morning/afternoon sessions exist
            tiene_manana = any(s.hora_inicio.hour < 13 for s in sesiones_dia)
            tiene_tarde = any(s.hora_inicio.hour >= 13 for s in sesiones_dia)
            
            sesiones_agrupadas = []
            if sesiones_dia:
                sesiones_ordenadas = sorted(sesiones_dia, key=lambda s: s.hora_inicio)
                
                grupos = []
                for hora, grupo_sesiones in groupby(sesiones_ordenadas, key=lambda s: s.hora_inicio.hour):
                    grupos.append({
                        'hora': hora,
                        'sesiones': list(grupo_sesiones)
                    })
                
                primer_tarde_encontrado = False
                for grupo in grupos:
                    grupo['mostrar_linea_tarde'] = False
                    if grupo['hora'] >= 13 and not primer_tarde_encontrado and tiene_manana:
                        grupo['mostrar_linea_tarde'] = True
                        primer_tarde_encontrado = True
                
                sesiones_agrupadas = grupos
            
            dias.append({
                'fecha': dia,
                'es_hoy': dia == date.today(),
                'sesiones': sesiones_dia,
                'sesiones_agrupadas': sesiones_agrupadas,
                'dia_nombre': dia.strftime('%A'),
                'dia_numero': dia.day,
                'tiene_sesiones_manana': tiene_manana,
                'tiene_sesiones_tarde': tiene_tarde,
            })
        return {'dias': dias, 'tipo': 'semanal'}

    @staticmethod
    def _generate_monthly(fecha_base, sesiones):
        primer_dia = fecha_base.replace(day=1)
        
        # Calcular último día del mes
        if fecha_base.month == 12:
            ultimo_dia = fecha_base.replace(day=31)
        else:
            ultimo_dia = (fecha_base.replace(month=fecha_base.month + 1, day=1) - timedelta(days=1))
        
        # ✅ CORRECCIÓN: Días del mes ANTERIOR para completar primera semana
        primer_dia_semana = primer_dia.weekday()  # 0=Lunes, 6=Domingo
        dias_mes_anterior = []
        
        if primer_dia_semana > 0:  # Si no empieza en Lunes
            for i in range(primer_dia_semana):
                dia = primer_dia - timedelta(days=primer_dia_semana - i)
                dias_mes_anterior.append({
                    'fecha': dia,
                    'es_otro_mes': True,
                    'es_hoy': False,
                    'sesiones': [],
                    'sesiones_agrupadas': [],
                    'dia_numero': dia.day,
                })
        
        # ✅ CORRECCIÓN: Días del mes ACTUAL
        dias_mes_actual = []
        for dia_num in range(1, ultimo_dia.day + 1):
            dia = fecha_base.replace(day=dia_num)
            sesiones_dia = [s for s in sesiones if s.fecha == dia]

            # ✅ Marcar sesiones grupales (mismo horario + servicio + profesional)
            CalendarService._marcar_sesiones_grupales(sesiones_dia)

            tiene_manana = any(s.hora_inicio.hour < 13 for s in sesiones_dia)
            
            sesiones_agrupadas = []
            if sesiones_dia:
                sesiones_ordenadas = sorted(sesiones_dia, key=lambda s: s.hora_inicio)
                grupos = []
                
                for hora, grupo_sesiones in groupby(sesiones_ordenadas, key=lambda s: s.hora_inicio.hour):
                    grupos.append({
                        'hora': hora,
                        'sesiones': list(grupo_sesiones)
                    })
                
                primer_tarde_encontrado = False
                for grupo in grupos:
                    grupo['mostrar_linea_tarde'] = False
                    if grupo['hora'] >= 13 and not primer_tarde_encontrado and tiene_manana:
                        grupo['mostrar_linea_tarde'] = True
                        primer_tarde_encontrado = True
                
                sesiones_agrupadas = grupos
            
            dias_mes_actual.append({
                'fecha': dia,
                'es_hoy': dia == date.today(),
                'es_otro_mes': False,
                'sesiones': sesiones_dia,
                'sesiones_agrupadas': sesiones_agrupadas,
                'dia_numero': dia_num,
            })
        
        # ✅ CORRECCIÓN: Combinar TODOS los días del mes anterior + actual
        todos_dias = dias_mes_anterior + dias_mes_actual
        
        # ✅ CORRECCIÓN: Dividir en semanas de 7 días
        semanas = []
        semana_actual = []
        
        for dia in todos_dias:
            semana_actual.append(dia)
            if len(semana_actual) == 7:
                semanas.append(semana_actual)
                semana_actual = []
        
        # ✅ CORRECCIÓN: Completar última semana si es necesaria
        if semana_actual:
            # Calcular cuántos días faltan para completar la semana
            dias_faltantes = 7 - len(semana_actual)
            
            # Agregar días del mes siguiente
            siguiente_dia = ultimo_dia + timedelta(days=1)
            for i in range(dias_faltantes):
                dia_siguiente = siguiente_dia + timedelta(days=i)
                semana_actual.append({
                    'fecha': dia_siguiente,
                    'es_otro_mes': True,
                    'es_hoy': False,
                    'sesiones': [],
                    'sesiones_agrupadas': [],
                    'dia_numero': dia_siguiente.day,
                })
            
            semanas.append(semana_actual)
        
        return {
            'semanas': semanas,
            'tipo': 'mensual',
            'mes_nombre': fecha_base.strftime('%B %Y'),
        }

    @staticmethod
    def get_filtered_sessions(
        fecha_inicio=None, fecha_fin=None, sucursales_usuario=None,
        sucursal_id=None, tipo_sesion=None, estado=None,
        paciente_id=None, profesional_id=None, servicio_id=None
    ):
        """
        Efficiently retrieve and filter sessions for the calendar.
        ✅ CORREGIDO: fecha_inicio y fecha_fin pueden ser None para vista lista sin límites
        """
        sesiones = Sesion.objects.select_related(
            'paciente', 'profesional', 'servicio', 'sucursal', 'proyecto', 'mensualidad'
        )
        
        # ✅ Filtro de fechas (opcional para vista lista)
        if fecha_inicio is not None and fecha_fin is not None:
            sesiones = sesiones.filter(fecha__gte=fecha_inicio, fecha__lte=fecha_fin)
        elif fecha_inicio is not None:
            sesiones = sesiones.filter(fecha__gte=fecha_inicio)
        elif fecha_fin is not None:
            sesiones = sesiones.filter(fecha__lte=fecha_fin)
        # Si ambos son None, no aplicar filtro de fecha (mostrar todo)
        
        # Sucursal permission filter
        if sucursales_usuario is not None:
            if sucursales_usuario.exists():
                sesiones = sesiones.filter(sucursal__in=sucursales_usuario)
            else:
                return Sesion.objects.none()
        
        # User filters
        if sucursal_id:
            sesiones = sesiones.filter(sucursal_id=sucursal_id)
        
        if tipo_sesion == 'normal':
            sesiones = sesiones.filter(proyecto__isnull=True, mensualidad__isnull=True)
        elif tipo_sesion == 'evaluacion':
            sesiones = sesiones.filter(proyecto__isnull=False)
        elif tipo_sesion == 'mensualidad':
            sesiones = sesiones.filter(mensualidad__isnull=False)
            
        if estado:
            sesiones = sesiones.filter(estado=estado)
        
        if paciente_id:
            sesiones = sesiones.filter(paciente_id=paciente_id)
            
        if profesional_id:
            sesiones = sesiones.filter(profesional_id=profesional_id)
            
        if servicio_id:
            sesiones = sesiones.filter(servicio_id=servicio_id)
            
        return sesiones.order_by('fecha', 'hora_inicio')


class ProyectoMensualidadService:
    """
    Servicio para gestionar proyectos y mensualidades
    ✅ MEJORADO: Incluye ajuste opcional para estado cancelado
    """

    @staticmethod
    def cachear_pagos_en_lista(instancias, tipo='proyecto'):
        """
        ⚡ OPTIMIZACIÓN: precalcula `total_pagado` y `total_devoluciones` para
        una lista YA CARGADA de Proyectos o Mensualidades (por ejemplo, la
        página actual de un listado paginado) en solo 3 queries EN TOTAL,
        en vez de hasta 3 queries POR CADA fila.

        Esto es lo que hacía lento (aunque de forma acotada, porque estas
        listas ya paginan a 20 por página) a `lista_proyectos` y
        `lista_mensualidades`: el template llama a `proyecto.pagado_completo`
        / `mensualidad.pagado_completo`, que internamente consulta
        total_pagado (2 queries) y total_devoluciones (1 query) por fila.

        Los resultados se guardan como `_total_pagado_cache` /
        `_total_devoluciones_cache` en cada instancia; las propiedades
        `total_pagado` / `total_devoluciones` del modelo (ver
        agenda/models.py) las reutilizan automáticamente si ya existen,
        sin volver a consultar la base de datos.

        Args:
            instancias: iterable de Proyecto o Mensualidad (se materializa
                        a lista si todavía no lo está, p. ej. page_obj.object_list)
            tipo: 'proyecto' o 'mensualidad' (debe coincidir con el nombre
                  del FK en Pago/DetallePagoMasivo/Devolucion)
        """
        from facturacion.models import Pago, DetallePagoMasivo, Devolucion

        instancias = list(instancias)
        if not instancias:
            return instancias

        ids = [obj.id for obj in instancias]
        filtro_id = f'{tipo}_id__in'

        # 1) Pagos directos, agrupados por instancia (1 query)
        pagos_directos = Pago.objects.filter(
            **{filtro_id: ids}, anulado=False
        ).values(tipo).annotate(total=Sum('monto'))
        mapa_directos = {row[tipo]: row['total'] for row in pagos_directos}

        # 2) Pagos masivos, agrupados por instancia (1 query)
        pagos_masivos = DetallePagoMasivo.objects.filter(
            **{filtro_id: ids}, tipo=tipo, pago__anulado=False
        ).values(tipo).annotate(total=Sum('monto'))
        mapa_masivos = {row[tipo]: row['total'] for row in pagos_masivos}

        # 3) Devoluciones, agrupadas por instancia (1 query)
        devoluciones = Devolucion.objects.filter(
            **{filtro_id: ids}
        ).values(tipo).annotate(total=Sum('monto'))
        mapa_devoluciones = {row[tipo]: row['total'] for row in devoluciones}

        for obj in instancias:
            directo = mapa_directos.get(obj.id) or Decimal('0.00')
            masivo = mapa_masivos.get(obj.id) or Decimal('0.00')
            obj._total_pagado_cache = directo + masivo
            obj._total_devoluciones_cache = mapa_devoluciones.get(obj.id) or Decimal('0.00')

        return instancias
    
    @staticmethod
    def ajustar_costo_al_finalizar(instancia, tipo='proyecto', forzar_ajuste=True):
        """
        Ajusta el costo de un proyecto/mensualidad al marcarlo como finalizado/completado
        ✅ MEJORADO: Ahora acepta parámetro forzar_ajuste para preview
        
        Args:
            instancia: Instancia de Proyecto o Mensualidad
            tipo: 'proyecto' o 'mensualidad'
            forzar_ajuste: Si True, guarda el cambio. Si False, solo calcula
            
        Returns:
            dict con:
                - success: bool
                - ajustado: bool (si hubo cambio de costo)
                - costo_anterior: Decimal
                - costo_nuevo: Decimal  
                - total_pagado: Decimal
                - total_devoluciones: Decimal
                - mensaje: str
                - tiene_sesiones_programadas: bool
        """
        from decimal import Decimal
        from facturacion.models import Pago, Devolucion
        
        # Verificar sesiones programadas
        sesiones_programadas = instancia.sesiones.filter(estado='programada').count()
        
        if sesiones_programadas > 0:
            return {
                'success': False,
                'tiene_sesiones_programadas': True,
                'num_sesiones_programadas': sesiones_programadas,
                'mensaje': f'No se puede finalizar porque tiene {sesiones_programadas} sesión(es) programada(s). Cancela o realiza las sesiones primero.'
            }
        
        # Calcular pagado neto
        if tipo == 'proyecto':
            total_pagado = Pago.objects.filter(
                proyecto=instancia,
                anulado=False
            ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
            
            total_devoluciones = Devolucion.objects.filter(
                proyecto=instancia
            ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
            
            costo_anterior = instancia.costo_total
            campo_costo = 'costo_total'
            
        else:  # mensualidad
            total_pagado = Pago.objects.filter(
                mensualidad=instancia,
                anulado=False
            ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
            
            total_devoluciones = Devolucion.objects.filter(
                mensualidad=instancia
            ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
            
            costo_anterior = instancia.costo_mensual
            campo_costo = 'costo_mensual'
        
        # Calcular nuevo costo (pagado neto)
        pagado_neto = total_pagado - total_devoluciones
        
        # ✅ MEJORADO: Solo actualizar si hay diferencia y se fuerza el ajuste
        if costo_anterior != pagado_neto and forzar_ajuste:
            setattr(instancia, campo_costo, pagado_neto)
            instancia.save(update_fields=[campo_costo])
            
            mensaje = f'✅ Costo ajustado de Bs. {costo_anterior} a Bs. {pagado_neto} (Pagado: {total_pagado} - Devoluciones: {total_devoluciones})'
            ajustado = True
        elif costo_anterior != pagado_neto and not forzar_ajuste:
            mensaje = f'📊 Se ajustaría el costo de Bs. {costo_anterior} a Bs. {pagado_neto}'
            ajustado = True
        else:
            mensaje = 'El costo ya coincide con el pagado neto. No se requiere ajuste.'
            ajustado = False
        
        return {
            'success': True,
            'ajustado': ajustado,
            'tiene_sesiones_programadas': False,
            'costo_anterior': costo_anterior,
            'costo_nuevo': pagado_neto,
            'total_pagado': total_pagado,
            'total_devoluciones': total_devoluciones,
            'mensaje': mensaje
        }
    
    @staticmethod
    def validar_cambio_estado(instancia, nuevo_estado, tipo='proyecto'):
        """
        Valida si se puede cambiar el estado
        ✅ MEJORADO: Ahora incluye estados cancelado/cancelada
        
        Args:
            instancia: Instancia de Proyecto o Mensualidad
            nuevo_estado: Nuevo estado deseado
            tipo: 'proyecto' o 'mensualidad'
            
        Returns:
            dict con success, num_sesiones_programadas y mensaje
        """
        # ✅ MODIFICADO: Agregado cancelado/cancelada a estados que requieren validación
        estados_finales = ['finalizado', 'completada', 'cancelado', 'cancelada']
        
        if nuevo_estado in estados_finales:
            sesiones_programadas = instancia.sesiones.filter(estado='programada').count()
            
            if sesiones_programadas > 0:
                return {
                    'success': False,
                    'num_sesiones_programadas': sesiones_programadas,
                    'mensaje': f'No se puede marcar como {nuevo_estado} porque tiene {sesiones_programadas} sesión(es) programada(s)'
                }
        
        return {
            'success': True,
            'num_sesiones_programadas': 0,
            'mensaje': 'OK'
        }
    
    @staticmethod
    @transaction.atomic
    def cambiar_estado_con_ajuste(instancia, nuevo_estado, ajustar_costo, usuario, tipo='proyecto'):
        """
        ✅ NUEVO: Cambiar estado con opción de ajustar costo
        
        Args:
            instancia: Proyecto o Mensualidad
            nuevo_estado: Estado al que cambiar
            ajustar_costo: Boolean - si se debe ajustar el costo
            usuario: Usuario que realiza el cambio
            tipo: 'proyecto' o 'mensualidad'
        
        Returns:
            dict con resultado de la operación
        """
        
        # 1. Validar cambio de estado
        validacion = ProyectoMensualidadService.validar_cambio_estado(
            instancia, nuevo_estado, tipo
        )
        
        if not validacion['success']:
            return {
                'success': False,
                'error': validacion['mensaje'],
                'tiene_sesiones_programadas': True,
                'num_sesiones_programadas': validacion['num_sesiones_programadas']
            }
        
        # 2. Ajustar costo si se solicitó
        ajuste_info = {'ajustado': False}
        
        if ajustar_costo:
            ajuste_info = ProyectoMensualidadService.ajustar_costo_al_finalizar(
                instancia, tipo, forzar_ajuste=True
            )
        
        # 3. Cambiar estado
        instancia.estado = nuevo_estado
        
        # 4. Actualizar campos de control
        if tipo == 'proyecto':
            instancia.modificado_por = usuario
            
            # Si es finalizado, establecer fecha_fin_real
            if nuevo_estado == 'finalizado' and not instancia.fecha_fin_real:
                instancia.fecha_fin_real = date.today()
        else:
            instancia.modificada_por = usuario
        
        instancia.save()
        
        # 5. Retornar resultado
        estado_display = instancia.get_estado_display()
        
        mensaje_base = f"Estado actualizado a: {estado_display}"
        
        if ajuste_info.get('ajustado'):
            mensaje_completo = f"{mensaje_base}. {ajuste_info['mensaje']}"
        else:
            mensaje_completo = mensaje_base
        
        return {
            'success': True,
            'ajuste_realizado': ajuste_info.get('ajustado', False),
            'costo_anterior': float(ajuste_info.get('costo_anterior', 0)),
            'costo_nuevo': float(ajuste_info.get('costo_nuevo', 0)),
            'total_pagado': float(ajuste_info.get('total_pagado', 0)),
            'total_devoluciones': float(ajuste_info.get('total_devoluciones', 0)),
            'mensaje': mensaje_completo
        }
    
    @staticmethod
    def obtener_datos_para_confirmacion(instancia, nuevo_estado, tipo='proyecto'):
        """
        ✅ NUEVO: Obtener datos necesarios para mostrar modal de confirmación
        cuando se cambia a estado cancelado
        
        Args:
            instancia: Proyecto o Mensualidad
            nuevo_estado: Estado al que se quiere cambiar
            tipo: 'proyecto' o 'mensualidad'
        
        Returns:
            dict con información para el modal
        """
        
        campo_costo = 'costo_total' if tipo == 'proyecto' else 'costo_mensual'
        costo_actual = getattr(instancia, campo_costo)
        
        total_pagado = instancia.total_pagado
        total_devoluciones = instancia.total_devoluciones
        pagado_neto = total_pagado - total_devoluciones
        
        # Calcular si habría cambio
        habria_ajuste = costo_actual != pagado_neto
        
        return {
            'requiere_confirmacion': nuevo_estado in ['cancelado', 'cancelada'],
            'costo_actual': float(costo_actual),
            'total_pagado': float(total_pagado),
            'total_devoluciones': float(total_devoluciones),
            'pagado_neto': float(pagado_neto),
            'habria_ajuste': habria_ajuste,
            'diferencia': float(costo_actual - pagado_neto),
            'estado_nuevo': nuevo_estado,
            'tipo': tipo
        }