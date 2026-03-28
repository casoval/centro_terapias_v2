# recordatorios/api.py
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.utils import timezone
from datetime import timedelta
from agenda.models import Sesion
from facturacion.models import CuentaCorriente
from decimal import Decimal


@api_view(['GET'])
def citas_manana(request):
    manana = timezone.localdate() + timedelta(days=1)
    
    sesiones = Sesion.objects.filter(
        fecha=manana,
        estado='programada'
    ).select_related('paciente', 'profesional', 'servicio', 'sucursal')
    
    data = []
    for sesion in sesiones:
        paciente = sesion.paciente
        data.append({
            'paciente_nombre': paciente.nombre_completo,
            'paciente_edad': paciente.edad,
            'tutor_nombre': paciente.nombre_tutor,
            'tutor_telefono': paciente.telefono_tutor,
            'tutor_email': paciente.email_tutor or '',
            'tutor2_nombre': paciente.nombre_tutor_2 or '',
            'tutor2_telefono': paciente.telefono_tutor_2 or '',
            'fecha': str(sesion.fecha),
            'hora_inicio': str(sesion.hora_inicio),
            'hora_fin': str(sesion.hora_fin),
            'servicio': sesion.servicio.nombre,
            'profesional': f"{sesion.profesional.nombre} {sesion.profesional.apellido}",
            'sucursal': sesion.sucursal.nombre,
        })
    
    return Response({
        'fecha_consulta': str(manana),
        'total_sesiones': len(data),
        'sesiones': data
    })


@api_view(['GET'])
def deudas_pendientes(request):
    """
    Retorna pacientes activos con deuda pendiente.
    Usa saldo_real (proyección total), es negativo cuando hay deuda.
    """
    cuentas = CuentaCorriente.objects.filter(
        paciente__estado='activo',
        saldo_real__lt=0
    ).select_related('paciente').order_by('saldo_real')  # mayor deuda primero

    data = []
    for cuenta in cuentas:
        paciente = cuenta.paciente
        deuda = abs(cuenta.saldo_real)
        data.append({
            'paciente_nombre': paciente.nombre_completo,
            'tutor_nombre': paciente.nombre_tutor,
            'tutor_telefono': paciente.telefono_tutor,
            'tutor_email': paciente.email_tutor or '',
            'saldo_pendiente': str(deuda),
            'total_consumido': str(cuenta.total_consumido_real),
            'total_pagado': str(cuenta.total_pagado),
        })

    return Response({
        'total_pacientes_con_deuda': len(data),
        'deudas': data
    })