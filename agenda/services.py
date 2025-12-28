from datetime import date, timedelta, datetime
from itertools import groupby
from django.db.models import Q, Count, Sum, F, OuterRef, Subquery, Case, When, Value, DecimalField
from django.db.models.functions import Coalesce

from .models import Sesion
from pacientes.models import Paciente
from profesionales.models import Profesional
from servicios.models import Sucursal, TipoServicio

class CalendarService:
    @staticmethod
    def get_calendar_data(vista, fecha_base, sesiones):
        """
        Generate calendar structure based on view type.
        """
        if vista == 'diaria':
            return CalendarService._generate_daily(fecha_base, sesiones)
        elif vista == 'mensual':
            return CalendarService._generate_monthly(fecha_base, sesiones)
        elif vista == 'lista':
            return None
        else: # semanal
            dias_desde_lunes = fecha_base.weekday()
            fecha_inicio = fecha_base - timedelta(days=dias_desde_lunes)
            return CalendarService._generate_weekly(fecha_inicio, sesiones)

    @staticmethod
    def _generate_daily(fecha, sesiones):
        sesiones_dia = [s for s in sesiones if s.fecha == fecha]
        return {
            'fecha': fecha,
            'es_hoy': fecha == date.today(),
            'sesiones': sesiones_dia,
            'dia_nombre': fecha.strftime('%A'),
            'tipo': 'diaria'
        }

    @staticmethod
    def _generate_weekly(fecha_inicio, sesiones):
        dias = []
        for i in range(7):
            dia = fecha_inicio + timedelta(days=i)
            sesiones_dia = [s for s in sesiones if s.fecha == dia]
            
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
        
        if fecha_base.month == 12:
            ultimo_dia = fecha_base.replace(day=31)
        else:
            ultimo_dia = (fecha_base.replace(month=fecha_base.month + 1) - timedelta(days=1))
        
        primer_dia_semana = primer_dia.weekday()
        dias_mes_anterior = []
        if primer_dia_semana > 0:
            for i in range(primer_dia_semana):
                dia = primer_dia - timedelta(days=primer_dia_semana - i)
                dias_mes_anterior.append({
                    'fecha': dia,
                    'es_otro_mes': True,
                    'sesiones': [],
                    'sesiones_agrupadas': [],
                })
        
        dias_mes_actual = []
        for dia_num in range(1, ultimo_dia.day + 1):
            dia = fecha_base.replace(day=dia_num)
            sesiones_dia = [s for s in sesiones if s.fecha == dia]
            
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
        
        todos_dias = dias_mes_anterior + dias_mes_actual
        semanas = []
        semana_actual = []
        
        for dia in todos_dias:
            semana_actual.append(dia)
            if len(semana_actual) == 7:
                semanas.append(semana_actual)
                semana_actual = []
        
        if semana_actual:
            while len(semana_actual) < 7:
                semana_actual.append({
                    'fecha': None,
                    'es_otro_mes': True,
                    'sesiones': [],
                    'sesiones_agrupadas': [],
                })
            semanas.append(semana_actual)
        
        return {
            'semanas': semanas,
            'tipo': 'mensual',
            'mes_nombre': fecha_base.strftime('%B %Y'),
        }

    @staticmethod
    def get_filtered_sessions(
        fecha_inicio, fecha_fin, sucursales_usuario,
        sucursal_id=None, tipo_sesion=None, estado=None,
        paciente_id=None, profesional_id=None, servicio_id=None
    ):
        """
        Efficiently retrieve and filter sessions for the calendar.
        """
        sesiones = Sesion.objects.select_related(
            'paciente', 'profesional', 'servicio', 'sucursal', 'proyecto'
        ).filter(
            fecha__gte=fecha_inicio,
            fecha__lte=fecha_fin
        )
        
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
            sesiones = sesiones.filter(proyecto__isnull=True)
        elif tipo_sesion == 'evaluacion':
            sesiones = sesiones.filter(proyecto__isnull=False)
            
        if estado:
            sesiones = sesiones.filter(estado=estado)
        
        if paciente_id:
            sesiones = sesiones.filter(paciente_id=paciente_id)
            
        if profesional_id:
            sesiones = sesiones.filter(profesional_id=profesional_id)
            
        if servicio_id:
            sesiones = sesiones.filter(servicio_id=servicio_id)
            
        return sesiones.order_by('fecha', 'hora_inicio')
