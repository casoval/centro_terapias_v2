# -*- coding: utf-8 -*-
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Sum, Count, F
from django.core.paginator import Paginator
from django.http import JsonResponse, HttpResponse
from django.conf import settings
from django.utils import timezone
from io import BytesIO
import base64
import os
from decimal import Decimal
from datetime import date, datetime

from .models import CuentaCorriente, Pago, MetodoPago
from pacientes.models import Paciente
from agenda.models import Sesion, Proyecto

@login_required
def lista_cuentas_corrientes(request):
    """
    Lista de cuentas corrientes con paginación y filtros
    ✅ ACTUALIZADO: Usa balance_final y totales generales (sesiones + proyectos)
    """
    
    # Filtros
    buscar = request.GET.get('q', '').strip()
    estado = request.GET.get('estado', '')  # 'deudor', 'al_dia', 'a_favor'
    sucursal_id = request.GET.get('sucursal', '')
    
    # Query base: Pacientes activos con prefetch de sucursales
    pacientes = Paciente.objects.filter(
        estado='activo'
    ).select_related(
        'cuenta_corriente'
    ).prefetch_related(
        'sucursales'
    )
    
    # Filtro de búsqueda
    if buscar:
        pacientes = pacientes.filter(
            Q(nombre__icontains=buscar) | 
            Q(apellido__icontains=buscar) |
            Q(nombre_tutor__icontains=buscar)
        )
    
    # Filtro por sucursal
    if sucursal_id:
        pacientes = pacientes.filter(sucursales__id=sucursal_id)
    
    # Crear cuentas corrientes faltantes y actualizar saldos
    for paciente in pacientes:
        if not hasattr(paciente, 'cuenta_corriente'):
            CuentaCorriente.objects.create(paciente=paciente)
        # Actualizar saldo para tener datos frescos
        paciente.cuenta_corriente.actualizar_saldo()
    
    # ✅ FILTRO POR ESTADO USANDO BALANCE_FINAL
    if estado == 'deudor':
        pacientes = [p for p in pacientes if p.cuenta_corriente.balance_final < 0]
    elif estado == 'al_dia':
        pacientes = [p for p in pacientes if p.cuenta_corriente.balance_final == 0]
    elif estado == 'a_favor':
        pacientes = [p for p in pacientes if p.cuenta_corriente.balance_final > 0]
    
    # ✅ ORDENAR POR BALANCE_FINAL (deudores primero, con mayor deuda arriba)
    pacientes = sorted(
        pacientes, 
        key=lambda p: p.cuenta_corriente.balance_final
    )
    
    # Paginación (20 por página)
    paginator = Paginator(pacientes, 20)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    # ✅ ESTADÍSTICAS CORREGIDAS - Calculadas manualmente con balance_final
    total_consumido_general = Decimal('0.00')
    total_pagado_general = Decimal('0.00')
    total_balance = Decimal('0.00')
    deudores_count = 0
    al_dia_count = 0
    a_favor_count = 0
    total_debe = Decimal('0.00')
    total_favor = Decimal('0.00')
    
    # Recorrer TODAS las cuentas corrientes (no solo la página actual)
    todas_cuentas = CuentaCorriente.objects.select_related('paciente').filter(
        paciente__estado='activo'
    )
    
    for cuenta in todas_cuentas:
        # Sumar totales generales
        total_consumido_general += cuenta.total_consumo_general
        total_pagado_general += cuenta.total_pagado_general
        total_balance += cuenta.balance_final
        
        # Clasificar por balance_final
        if cuenta.balance_final < 0:
            deudores_count += 1
            total_debe += abs(cuenta.balance_final)
        elif cuenta.balance_final == 0:
            al_dia_count += 1
        else:
            a_favor_count += 1
            total_favor += cuenta.balance_final
    
    estadisticas = {
        'total_consumido': total_consumido_general,
        'total_pagado': total_pagado_general,
        'total_balance': total_balance,
        'deudores': deudores_count,
        'al_dia': al_dia_count,
        'a_favor': a_favor_count,
        'total_debe': total_debe,
        'total_favor': total_favor,
    }
    
    # Sucursales para filtro
    from servicios.models import Sucursal
    sucursales = Sucursal.objects.filter(activa=True)
    
    context = {
        'page_obj': page_obj,
        'estadisticas': estadisticas,
        'buscar': buscar,
        'estado': estado,
        'sucursal_id': sucursal_id,
        'sucursales': sucursales,
    }
    
    return render(request, 'facturacion/cuentas_corrientes.html', context)

@login_required
def detalle_cuenta_corriente(request, paciente_id):
    """
    Detalle completo de cuenta corriente de un paciente
    ✅ ACTUALIZADO: Incluye proyectos del paciente
    """
    
    paciente = get_object_or_404(
        Paciente.objects.select_related('cuenta_corriente'),
        id=paciente_id
    )
    
    # Crear cuenta corriente si no existe
    cuenta, created = CuentaCorriente.objects.get_or_create(paciente=paciente)
    if created:
        cuenta.actualizar_saldo()
    
    # ==================== SESIONES ====================
    sesiones = Sesion.objects.filter(
        paciente=paciente,
        estado__in=['realizada', 'realizada_retraso', 'falta']
    ).select_related(
        'servicio', 'profesional', 'sucursal'
    ).order_by('-fecha', '-hora_inicio')
    
    # Paginar sesiones (15 por página)
    paginator_sesiones = Paginator(sesiones, 15)
    page_sesiones = request.GET.get('page_sesiones', 1)
    sesiones_page = paginator_sesiones.get_page(page_sesiones)
    
    # ==================== PROYECTOS ✅ NUEVO ====================
    from agenda.models import Proyecto
    
    proyectos_paciente = Proyecto.objects.filter(
        paciente=paciente
    ).select_related(
        'servicio_base', 'profesional_responsable', 'sucursal'
    ).order_by('-fecha_inicio')
    
    # ==================== PAGOS VÁLIDOS ====================
    pagos_validos = Pago.objects.filter(
        paciente=paciente,
        anulado=False
    ).exclude(
        metodo_pago__nombre="Uso de Crédito"
    ).select_related(
        'metodo_pago', 'sesion', 'sesion__servicio', 'proyecto', 'registrado_por'
    ).order_by('-fecha_pago', '-fecha_registro')
    
    paginator_validos = Paginator(pagos_validos, 15)
    page_validos = request.GET.get('page_validos', 1)
    pagos_validos_page = paginator_validos.get_page(page_validos)
    
    # ==================== PAGOS CON CRÉDITO ====================
    pagos_credito = Pago.objects.filter(
        paciente=paciente,
        metodo_pago__nombre="Uso de Crédito",
        anulado=False
    ).select_related(
        'metodo_pago', 'sesion', 'sesion__servicio', 'registrado_por'
    ).order_by('-fecha_pago', '-fecha_registro')
    
    paginator_credito = Paginator(pagos_credito, 15)
    page_credito = request.GET.get('page_credito', 1)
    pagos_credito_page = paginator_credito.get_page(page_credito)
    
    # ==================== PAGOS ANULADOS ====================
    pagos_anulados = Pago.objects.filter(
        paciente=paciente,
        anulado=True
    ).select_related(
        'metodo_pago', 'sesion', 'sesion__servicio', 'proyecto', 
        'registrado_por', 'anulado_por'
    ).order_by('-fecha_anulacion')
    
    paginator_anulados = Paginator(pagos_anulados, 15)
    page_anulados = request.GET.get('page_anulados', 1)
    pagos_anulados_page = paginator_anulados.get_page(page_anulados)
    
    # ==================== ESTADÍSTICAS ====================
    stats = {
        'pagos_anulados': pagos_anulados.count(),
        'proyectos_activos': proyectos_paciente.filter(
            estado__in=['planificado', 'en_progreso']
        ).count(),
        'proyectos_finalizados': proyectos_paciente.filter(
            estado='finalizado'
        ).count(),
    }
    
    context = {
        'paciente': paciente,
        'cuenta': cuenta,
        'sesiones': sesiones_page,
        'proyectos_paciente': proyectos_paciente,  # ✅ NUEVO
        'pagos_validos': pagos_validos_page,
        'pagos_credito': pagos_credito_page,
        'pagos_anulados': pagos_anulados_page,
        'stats': stats,
    }
    return render(request, 'facturacion/detalle_cuenta.html', context)

@login_required
def registrar_pago(request):
    """
    Registrar pago con soporte para:
    - Pago 100% efectivo (genera recibo normal)
    - Pago mixto (crédito + efectivo, genera recibo solo por efectivo)
    - Pago 100% crédito (sin recibo físico)
    - ✅ NUEVO: Checkbox "Pago Completo" para ajustar precio y saldar deuda.
    - ✅ CORREGIDO: Permite monto 0 si se usa solo crédito o si es "Pago Completo"
    
    Soporta 3 tipos: sesión, proyecto, adelantado
    """
    
    if request.method == 'POST':
        try:
            from django.db import transaction
            
            # Identificar tipo de pago
            tipo_pago = request.POST.get('tipo_pago')
            
            # ✅ NUEVO: Capturar checkbox de pago completo
            es_pago_completo = request.POST.get('pago_completo') == 'on'
            
            # Obtener datos comunes
            raw_credito = request.POST.get('monto_credito', '').strip()
            raw_monto = request.POST.get('monto', '').strip()
            
            monto_credito = Decimal(raw_credito if raw_credito else '0')
            monto_adicional = Decimal(raw_monto if raw_monto else '0')
            
            # Calcular monto total que se está pagando en este momento
            monto_aportado_ahora = monto_credito + monto_adicional
            
            usar_credito = request.POST.get('usar_credito') == 'on'

            metodo_pago_id = request.POST.get('metodo_pago')
            fecha_pago_str = request.POST.get('fecha_pago')
            observaciones = request.POST.get('observaciones', '')
            numero_transaccion = request.POST.get('numero_transaccion', '')
            
            # Validaciones básicas
            if not fecha_pago_str:
                messages.error(request, '❌ Debes especificar la fecha de pago')
                return redirect('facturacion:registrar_pago')
            
            # ✅ VALIDACIÓN CORREGIDA: Permitir monto 0 en casos específicos
            if monto_aportado_ahora <= 0:
                # CASO 1: Es sesión gratuita (monto_cobrado = 0)
                if tipo_pago == 'sesion':
                    sesion_id = request.POST.get('sesion_id')
                    if sesion_id:
                        sesion = Sesion.objects.get(id=sesion_id)
                        if sesion.monto_cobrado == 0:
                            # ✅ PERMITIR: Sesión gratuita
                            pass
                        elif es_pago_completo:
                            # ✅ PERMITIR: Pago completo con monto 0 (ajuste de precio)
                            pass
                        else:
                            # ❌ RECHAZAR: Sesión con deuda pero sin monto
                            messages.error(request, '❌ Debes especificar un monto a pagar')
                            return redirect('facturacion:registrar_pago')
                    else:
                        messages.error(request, '❌ Debes especificar un monto a pagar')
                        return redirect('facturacion:registrar_pago')
                
                # CASO 2: Es proyecto con "Pago Completo"
                elif tipo_pago == 'proyecto' and es_pago_completo:
                    # ✅ PERMITIR: Ajuste de precio de proyecto a 0
                    pass
                
                # CASO 3: Rechazar otros casos
                else:
                    messages.error(request, '❌ Debes especificar un monto a pagar')
                    return redirect('facturacion:registrar_pago')

            # Si hay monto adicional, debe haber método
            if monto_adicional > 0 and not metodo_pago_id:
                messages.error(request, '❌ Debes seleccionar un método de pago')
                return redirect('facturacion:registrar_pago')
            
            fecha_pago = datetime.strptime(fecha_pago_str, '%Y-%m-%d').date()
            metodo_pago = MetodoPago.objects.get(id=metodo_pago_id) if metodo_pago_id else None
            
            # ========== CASO 1: PAGO DE SESIÓN ==========
            if tipo_pago == 'sesion':
                sesion_id = request.POST.get('sesion_id')
                if not sesion_id:
                    messages.error(request, '❌ Debes seleccionar una sesión')
                    return redirect('facturacion:registrar_pago')
                
                sesion = Sesion.objects.get(id=sesion_id)
                paciente = sesion.paciente
                
                # Validar crédito disponible
                cuenta, _ = CuentaCorriente.objects.get_or_create(paciente=paciente)
                cuenta.actualizar_saldo()
                
                if usar_credito and monto_credito > 0:
                    if cuenta.saldo < monto_credito:
                        messages.error(
                            request,
                            f'❌ Crédito insuficiente. Disponible: Bs. {cuenta.saldo}'
                        )
                        return redirect('facturacion:registrar_pago')
                
                # 🔒 TRANSACCIÓN ATÓMICA
                with transaction.atomic():
                    
                    # 🔥 LÓGICA DE PAGO COMPLETO (AJUSTE DE PRECIO)
                    if es_pago_completo:
                        # 1. Calcular cuánto se había pagado ANTES de este pago
                        pagado_previo = sesion.pagos.filter(anulado=False).exclude(
                            metodo_pago__nombre="Uso de Crédito"
                        ).aggregate(Sum('monto'))['monto__sum'] or Decimal('0.00')
                        
                        # 2. Calcular el NUEVO costo total de la sesión
                        # Costo final = Lo que ya pagó + Lo que paga hoy (crédito + efectivo)
                        nuevo_costo_real = pagado_previo + monto_aportado_ahora
                        
                        # 3. Si el costo cambia, actualizamos la sesión
                        if sesion.monto_cobrado != nuevo_costo_real:
                            monto_original = sesion.monto_cobrado
                            sesion.monto_cobrado = nuevo_costo_real
                            
                            # Agregar nota automática
                            nota_ajuste = f"\n[{date.today()}] Ajuste por 'Pago Completo': Cobro modificado de {monto_original} a {nuevo_costo_real}."
                            sesion.observaciones = (sesion.observaciones or "") + nota_ajuste
                            sesion.save()

                    recibos_generados = []
                    
                    # 1️⃣ Pago con CRÉDITO (si aplica)
                    if usar_credito and monto_credito > 0:
                        metodo_credito, _ = MetodoPago.objects.get_or_create(
                            nombre="Uso de Crédito",
                            defaults={
                                'descripcion': 'Aplicación de saldo a favor',
                                'activo': True
                            }
                        )
                        
                        Pago.objects.create(
                            paciente=paciente,
                            sesion=sesion,
                            fecha_pago=fecha_pago,
                            monto=monto_credito,
                            metodo_pago=metodo_credito,
                            concepto=f"Uso de crédito - Sesión {sesion.fecha} - {sesion.servicio.nombre}",
                            observaciones=f"Aplicación de saldo a favor\n{observaciones}",
                            registrado_por=request.user,
                            numero_recibo=f"CREDITO-{fecha_pago.strftime('%Y%m%d')}-{sesion.id}"
                        )
                    
                    # 2️⃣ Pago ADICIONAL (efectivo/otro) - GENERA RECIBO REAL
                    pago_adicional = None
                    if monto_adicional > 0:
                        pago_adicional = Pago.objects.create(
                            paciente=paciente,
                            sesion=sesion,
                            fecha_pago=fecha_pago,
                            monto=monto_adicional,
                            metodo_pago=metodo_pago,
                            concepto=f"Pago sesión {sesion.fecha} - {sesion.servicio.nombre}",
                            observaciones=observaciones,
                            numero_transaccion=numero_transaccion,
                            registrado_por=request.user
                        )
                        recibos_generados.append(pago_adicional.numero_recibo)
                    
                    # Actualizar cuenta
                    cuenta.actualizar_saldo()
                    
                    # 🆕 PREPARAR RESPUESTA CON DATOS DEL PAGO
                    msg_extra = " (Precio ajustado para saldar)" if es_pago_completo else ""
                    
                    # Determinar si se generó recibo físico
                    genero_recibo = monto_adicional > 0
                    numero_recibo = recibos_generados[0] if recibos_generados else None
                    
                    # Construir mensaje
                    if usar_credito and monto_adicional > 0:
                        tipo_pago_display = "Mixto"
                        mensaje = f'Pago mixto registrado{msg_extra}'
                        detalle = f'Crédito: Bs. {monto_credito} + Efectivo: Bs. {monto_adicional}'
                    elif usar_credito:
                        tipo_pago_display = "100% Crédito"
                        mensaje = f'Pago aplicado con crédito{msg_extra}'
                        detalle = f'Monto: Bs. {monto_credito}'
                        genero_recibo = False
                    else:
                        tipo_pago_display = "Efectivo"
                        mensaje = f'Pago registrado{msg_extra}'
                        detalle = f'Monto: Bs. {monto_adicional}'
                    
                    # Info adicional
                    info_estado = 'Sesión PAGADA' if sesion.pagado else f'Falta: Bs. {sesion.saldo_pendiente}'
                    
                    # 🆕 ALMACENAR EN SESSION para mostrar en modal
                    request.session['pago_exitoso'] = {
                        'tipo': tipo_pago_display,
                        'mensaje': mensaje,
                        'detalle': detalle,
                        'total': float(monto_aportado_ahora),
                        'paciente': paciente.nombre_completo,
                        'concepto': f"Sesión {sesion.fecha} - {sesion.servicio.nombre}",
                        'info_estado': info_estado,
                        'genero_recibo': genero_recibo,
                        'numero_recibo': numero_recibo,
                        'pago_id': pago_adicional.id if pago_adicional else None,
                    }
                    
                    return redirect('facturacion:confirmacion_pago')
            
            # ========== CASO 2: PAGO DE PROYECTO ==========
            elif tipo_pago == 'proyecto':
                proyecto_id = request.POST.get('proyecto_id')
                if not proyecto_id:
                    messages.error(request, '❌ Debes seleccionar un proyecto')
                    return redirect('facturacion:registrar_pago')
                
                proyecto = Proyecto.objects.get(id=proyecto_id)
                paciente = proyecto.paciente
                
                # Validar crédito
                cuenta, _ = CuentaCorriente.objects.get_or_create(paciente=paciente)
                cuenta.actualizar_saldo()
                
                if usar_credito and monto_credito > 0:
                    if cuenta.saldo < monto_credito:
                        messages.error(
                            request,
                            f'❌ Crédito insuficiente. Disponible: Bs. {cuenta.saldo}'
                        )
                        return redirect('facturacion:registrar_pago')
                
                with transaction.atomic():
                    
                    # 🔥 LÓGICA DE PAGO COMPLETO PARA PROYECTO
                    if es_pago_completo:
                        pagado_previo = proyecto.pagos.filter(anulado=False).exclude(
                            metodo_pago__nombre="Uso de Crédito"
                        ).aggregate(Sum('monto'))['monto__sum'] or Decimal('0.00')
                        
                        nuevo_costo_real = pagado_previo + monto_aportado_ahora
                        
                        if proyecto.costo_total != nuevo_costo_real:
                            proyecto.costo_total = nuevo_costo_real
                            proyecto.save()
                    
                    recibos_generados = []
                    
                    # Pago con crédito
                    if usar_credito and monto_credito > 0:
                        metodo_credito, _ = MetodoPago.objects.get_or_create(
                            nombre="Uso de Crédito",
                            defaults={'descripcion': 'Aplicación de saldo a favor', 'activo': True}
                        )
                        
                        Pago.objects.create(
                            paciente=paciente,
                            proyecto=proyecto,
                            fecha_pago=fecha_pago,
                            monto=monto_credito,
                            metodo_pago=metodo_credito,
                            concepto=f"Uso de crédito - Proyecto {proyecto.codigo}",
                            observaciones=f"Aplicación de saldo a favor\n{observaciones}",
                            registrado_por=request.user,
                            numero_recibo=f"CREDITO-{fecha_pago.strftime('%Y%m%d')}-P{proyecto.id}"
                        )
                    
                    # Pago adicional
                    pago_adicional = None
                    if monto_adicional > 0:
                        pago_adicional = Pago.objects.create(
                            paciente=paciente,
                            proyecto=proyecto,
                            fecha_pago=fecha_pago,
                            monto=monto_adicional,
                            metodo_pago=metodo_pago,
                            concepto=f"Pago proyecto {proyecto.codigo} - {proyecto.nombre}",
                            observaciones=observaciones,
                            numero_transaccion=numero_transaccion,
                            registrado_por=request.user
                        )
                        recibos_generados.append(pago_adicional.numero_recibo)
                    
                    cuenta.actualizar_saldo()
                    
                    # 🆕 PREPARAR RESPUESTA
                    msg_extra = " (Proyecto saldado)" if es_pago_completo else ""
                    genero_recibo = monto_adicional > 0
                    numero_recibo = recibos_generados[0] if recibos_generados else None
                    
                    if usar_credito and monto_adicional > 0:
                        tipo_pago_display = "Mixto"
                        mensaje = f'Pago mixto{msg_extra}'
                        detalle = f'Crédito: Bs. {monto_credito} + Efectivo: Bs. {monto_adicional}'
                    elif usar_credito:
                        tipo_pago_display = "100% Crédito"
                        mensaje = f'Pago aplicado con crédito{msg_extra}'
                        detalle = f'Monto: Bs. {monto_credito}'
                        genero_recibo = False
                    else:
                        tipo_pago_display = "Efectivo"
                        mensaje = f'Pago registrado{msg_extra}'
                        detalle = f'Monto: Bs. {monto_adicional}'
                    
                    info_estado = 'Proyecto PAGADO COMPLETO' if proyecto.pagado_completo else f'Falta: Bs. {proyecto.saldo_pendiente}'
                    
                    request.session['pago_exitoso'] = {
                        'tipo': tipo_pago_display,
                        'mensaje': mensaje,
                        'detalle': detalle,
                        'total': float(monto_aportado_ahora),
                        'paciente': paciente.nombre_completo,
                        'concepto': f"Proyecto {proyecto.codigo} - {proyecto.nombre}",
                        'info_estado': info_estado,
                        'genero_recibo': genero_recibo,
                        'numero_recibo': numero_recibo,
                        'pago_id': pago_adicional.id if pago_adicional else None,
                    }
                    
                    return redirect('facturacion:confirmacion_pago')
            
            # ========== CASO 3: PAGO ADELANTADO ==========
            elif tipo_pago == 'adelantado':
                paciente_id = request.POST.get('paciente_adelantado')
                if not paciente_id:
                    messages.error(request, '❌ Debes seleccionar un paciente')
                    return redirect('facturacion:registrar_pago')
                
                # SOLO efectivo (no se puede usar crédito para pago adelantado)
                if not metodo_pago_id or monto_adicional <= 0:
                    messages.error(request, '❌ Debes especificar método y monto')
                    return redirect('facturacion:registrar_pago')
                
                paciente = Paciente.objects.get(id=paciente_id)
                
                with transaction.atomic():
                    pago = Pago.objects.create(
                        paciente=paciente,
                        sesion=None,
                        proyecto=None,
                        fecha_pago=fecha_pago,
                        monto=monto_adicional,
                        metodo_pago=metodo_pago,
                        concepto=f"Pago adelantado - {paciente.nombre_completo}",
                        observaciones=observaciones,
                        numero_transaccion=numero_transaccion,
                        registrado_por=request.user
                    )
                    
                    cuenta, _ = CuentaCorriente.objects.get_or_create(paciente=paciente)
                    cuenta.actualizar_saldo()
                
                # 🆕 PREPARAR RESPUESTA
                request.session['pago_exitoso'] = {
                    'tipo': 'Adelantado',
                    'mensaje': 'Pago adelantado registrado',
                    'detalle': f'Monto: Bs. {monto_adicional}',
                    'total': float(monto_adicional),
                    'paciente': paciente.nombre_completo,
                    'concepto': 'Depósito a crédito / billetera',
                    'info_estado': f'Nuevo crédito disponible: Bs. {cuenta.saldo}',
                    'genero_recibo': True,
                    'numero_recibo': pago.numero_recibo,
                    'pago_id': pago.id,
                }
                
                return redirect('facturacion:confirmacion_pago')
            
            else:
                messages.error(request, '❌ Tipo de pago no válido')
                return redirect('facturacion:registrar_pago')
        
        except Exception as e:
            messages.error(request, f'❌ Error: {str(e)}')
            import traceback
            print(traceback.format_exc())
            return redirect('facturacion:registrar_pago')
    
    # ========== GET - MOSTRAR FORMULARIO ==========
    metodos_pago = MetodoPago.objects.filter(activo=True).exclude(
        nombre__in=["Crédito/Saldo a favor", "Uso de Crédito"]
    )
    
    pacientes_lista = Paciente.objects.filter(estado='activo').order_by('apellido', 'nombre')
    
    # Detectar parámetros
    sesion_id = request.GET.get('sesion')
    paciente_id = request.GET.get('paciente')
    proyecto_id = request.GET.get('proyecto')
    
    sesion = None
    paciente = None
    proyecto = None
    modo = None
    credito_disponible = Decimal('0.00')
    monto_sugerido = Decimal('0.00')
    
    # CASO 1: Proyecto
    if proyecto_id:
        proyecto = get_object_or_404(
            Proyecto.objects.select_related('paciente', 'servicio_base'),
            id=proyecto_id
        )
        paciente = proyecto.paciente
        modo = 'proyecto'
        monto_sugerido = proyecto.saldo_pendiente
        
        cuenta, _ = CuentaCorriente.objects.get_or_create(paciente=paciente)
        cuenta.actualizar_saldo()
        credito_disponible = cuenta.saldo if cuenta.saldo > 0 else Decimal('0.00')
    
    # CASO 2: Sesión
    elif sesion_id:
        sesion = get_object_or_404(
            Sesion.objects.select_related('paciente', 'servicio', 'profesional'),
            id=sesion_id
        )
        paciente = sesion.paciente
        modo = 'sesion'
        monto_sugerido = sesion.saldo_pendiente
        
        cuenta, _ = CuentaCorriente.objects.get_or_create(paciente=paciente)
        cuenta.actualizar_saldo()
        credito_disponible = cuenta.saldo if cuenta.saldo > 0 else Decimal('0.00')
    
    # CASO 3: Adelantado
    elif paciente_id:
        paciente = get_object_or_404(Paciente, id=paciente_id)
        modo = 'adelantado'
        
        cuenta, _ = CuentaCorriente.objects.get_or_create(paciente=paciente)
        cuenta.actualizar_saldo()
        credito_disponible = cuenta.saldo if cuenta.saldo > 0 else Decimal('0.00')
    
    # CASO 4: Selector
    else:
        modo = 'selector'
    
    context = {
        'metodos_pago': metodos_pago,
        'sesion': sesion,
        'paciente': paciente,
        'proyecto': proyecto,
        'modo': modo,
        'credito_disponible': credito_disponible,
        'monto_sugerido': monto_sugerido,
        'fecha_hoy': date.today(),
        'pacientes_lista': pacientes_lista,
    }
    
    return render(request, 'facturacion/registrar_pago.html', context)

@login_required
def confirmacion_pago(request):
    """
    🆕 NUEVA VISTA: Mostrar modal de confirmación de pago exitoso
    """
    
    # Obtener datos de la sesión
    datos_pago = request.session.get('pago_exitoso')
    
    if not datos_pago:
        messages.error(request, '❌ No hay datos de pago para mostrar')
        return redirect('facturacion:cuentas_corrientes')
    
    # Limpiar sesión después de obtener datos
    del request.session['pago_exitoso']
    
    context = {
        'datos_pago': datos_pago,
    }
    
    return render(request, 'facturacion/confirmacion_pago.html', context)

# ✅ NUEVA: API para cargar proyectos de un paciente (AJAX)
@login_required
def api_proyectos_paciente(request, paciente_id):
    """
    API: Obtener proyectos con saldo pendiente de un paciente
    """
    try:
        from agenda.models import Proyecto
        
        proyectos = Proyecto.objects.filter(
            paciente_id=paciente_id,
            estado__in=['planificado', 'en_progreso']
        ).select_related('servicio_base')
        
        # Filtrar solo los que tienen saldo pendiente
        proyectos_pendientes = [
            {
                'id': p.id,
                'codigo': p.codigo,
                'nombre': p.nombre,
                'costo_total': float(p.costo_total),
                'total_pagado': float(p.total_pagado),
                'saldo_pendiente': float(p.saldo_pendiente),
                'tipo': p.get_tipo_display(),
            }
            for p in proyectos if p.saldo_pendiente > 0
        ]
        
        return JsonResponse({
            'success': True,
            'proyectos': proyectos_pendientes
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=400)

@login_required
def marcar_sesion_pagada(request, sesion_id):
    """
    Marcar sesión como pagada (rápido desde lista)
    OPTIMIZADO: HTMX response
    """
    
    if request.method == 'POST':
        try:
            sesion = get_object_or_404(Sesion, id=sesion_id)
            
            # Marcar como pagada
            sesion.pagado = True
            sesion.fecha_pago = date.today()
            sesion.save()
            
            # Actualizar cuenta corriente
            cuenta, created = CuentaCorriente.objects.get_or_create(paciente=sesion.paciente)
            cuenta.actualizar_saldo()
            
            messages.success(request, f'✅ Sesión marcada como pagada')
            
            # Retornar fragmento actualizado (HTMX)
            return render(request, 'facturacion/partials/sesion_row.html', {
                'sesion': sesion
            })
            
        except Exception as e:
            messages.error(request, f'❌ Error: {str(e)}')
            return redirect('facturacion:detalle_cuenta', paciente_id=sesion.paciente.id)
    
    return redirect('facturacion:cuentas_corrientes')


# ============= APIs AJAX/HTMX =============

@login_required
def buscar_pacientes_ajax(request):
    """
    API: Buscar pacientes para autocomplete
    OPTIMIZADO: Solo campos necesarios
    """
    
    q = request.GET.get('q', '').strip()
    
    if len(q) < 2:
        return JsonResponse({'pacientes': []})
    
    pacientes = Paciente.objects.filter(
        Q(nombre__icontains=q) | 
        Q(apellido__icontains=q) |
        Q(nombre_tutor__icontains=q),
        estado='activo'
    ).values('id', 'nombre', 'apellido')[:10]
    
    return JsonResponse({
        'pacientes': list(pacientes)
    })


@login_required
def sesiones_pendientes_ajax(request, paciente_id):
    """
    API: Obtener sesiones pendientes de pago de un paciente
    OPTIMIZADO: HTMX partial
    """
    
    paciente = get_object_or_404(Paciente, id=paciente_id)
    
    sesiones = Sesion.objects.filter(
        paciente=paciente,
        pagado=False,
        estado__in=['realizada', 'realizada_retraso', 'falta']
    ).select_related('servicio').order_by('-fecha')[:20]
    
    return render(request, 'facturacion/partials/sesiones_pendientes.html', {
        'sesiones': sesiones,
        'paciente': paciente,
    })


# ==================== FASE 2: PAGOS MASIVOS ====================

@login_required
def pagos_masivos(request):
    """
    Vista para pagar múltiples sesiones Y PROYECTOS a la vez
    ✅ OPCIÓN B: 
    - Proyectos con saldo pendiente (1 fila por proyecto)
    - Sesiones normales sin proyecto con saldo pendiente
    - Sesiones DE proyecto NO aparecen (se pagan a nivel proyecto)
    """
    
    # Paso 1: Seleccionar paciente
    paciente_id = request.GET.get('paciente')
    paciente = None
    sesiones_pendientes = []
    proyectos_pendientes = []
    
    if paciente_id:
        paciente = get_object_or_404(
            Paciente.objects.select_related('cuenta_corriente'),
            id=paciente_id
        )
        
        # ✅ 1. OBTENER PROYECTOS CON SALDO PENDIENTE
        proyectos_pendientes = Proyecto.objects.filter(
            paciente=paciente,
            estado__in=['planificado', 'en_progreso']
        ).select_related(
            'servicio_base', 'profesional_responsable', 'sucursal'
        ).order_by('-fecha_inicio')
        
        # Filtrar solo los que tienen saldo pendiente
        proyectos_pendientes = [p for p in proyectos_pendientes if p.saldo_pendiente > 0]
        
        # ✅ 2. OBTENER SESIONES NORMALES (SIN PROYECTO) CON SALDO PENDIENTE
        sesiones_pendientes = Sesion.objects.filter(
            paciente=paciente,
            estado__in=['realizada', 'realizada_retraso', 'falta'],
            proyecto__isnull=True,  # ✅ CRÍTICO: Solo sesiones SIN proyecto
            monto_cobrado__gt=0
        ).select_related(
            'servicio', 'profesional', 'sucursal'
        ).order_by('-fecha', '-hora_inicio')
        
        # Filtrar solo las que tienen saldo pendiente
        sesiones_pendientes = [s for s in sesiones_pendientes if s.saldo_pendiente > 0]
        
        # ✅ 3. CALCULAR DEUDA TOTAL (Sesiones + Proyectos)
        deuda_sesiones = paciente.cuenta_corriente.deuda_pendiente
        deuda_proyectos = sum(p.saldo_pendiente for p in proyectos_pendientes)
        paciente.deuda_total_display = deuda_sesiones + deuda_proyectos
    
    # ✅ Pacientes con DEUDA (proyectos o sesiones sin pagar)
    pacientes_activos = Paciente.objects.filter(
        estado='activo'
    ).select_related('cuenta_corriente')
    
    pacientes_con_deuda = []
    for p in pacientes_activos:
        cuenta, created = CuentaCorriente.objects.get_or_create(paciente=p)
        
        # Verificar si tiene deuda pendiente O proyectos pendientes
        tiene_deuda_sesiones = cuenta.deuda_pendiente > 0
        
        proyectos_con_saldo = Proyecto.objects.filter(
            paciente=p,
            estado__in=['planificado', 'en_progreso']
        )
        tiene_proyectos_pendientes = any(
            pr.saldo_pendiente > 0 for pr in proyectos_con_saldo
        )
        
        if tiene_deuda_sesiones or tiene_proyectos_pendientes:
            pacientes_con_deuda.append(p)
    
    # Ordenar por mayor deuda
    pacientes_con_deuda.sort(key=lambda p: p.cuenta_corriente.deuda_pendiente, reverse=True)
    pacientes_con_deuda = pacientes_con_deuda[:50]
    
    # Métodos de pago
    metodos_pago = MetodoPago.objects.filter(activo=True)
    
    context = {
        'paciente': paciente,
        'sesiones_pendientes': sesiones_pendientes,
        'proyectos_pendientes': proyectos_pendientes,  # ✅ NUEVO
        'deuda_proyectos': sum(p.saldo_pendiente for p in proyectos_pendientes) if proyectos_pendientes else Decimal('0.00'),  # ✅ NUEVO
        'pacientes_con_deuda': pacientes_con_deuda,
        'metodos_pago': metodos_pago,
        'fecha_hoy': date.today(),
    }
    
    return render(request, 'facturacion/pagos_masivos.html', context)

@login_required
def procesar_pagos_masivos(request):
    """
    Procesar pago masivo de múltiples sesiones Y PROYECTOS
    ✅ ACTUALIZADO: Soporta proyectos y sesiones en el mismo pago
    ✅ NUEVO: Redirige a confirmación de pago
    """
    
    if request.method != 'POST':
        return redirect('facturacion:pagos_masivos')
    
    try:
        from django.db import transaction
        
        # Datos del formulario
        paciente_id = request.POST.get('paciente_id')
        sesiones_ids = request.POST.getlist('sesiones_ids')
        proyectos_ids = request.POST.getlist('proyectos_ids')
        metodo_pago_id = request.POST.get('metodo_pago')
        fecha_pago_str = request.POST.get('fecha_pago')
        observaciones = request.POST.get('observaciones', '')
        
        # Validaciones
        if not all([paciente_id, metodo_pago_id, fecha_pago_str]):
            messages.error(request, '❌ Faltan datos obligatorios')
            return redirect('facturacion:pagos_masivos')
        
        if not sesiones_ids and not proyectos_ids:
            messages.error(request, '❌ Debes seleccionar al menos una sesión o proyecto')
            return redirect('facturacion:pagos_masivos')
        
        fecha_pago = datetime.strptime(fecha_pago_str, '%Y-%m-%d').date()
        paciente = Paciente.objects.get(id=paciente_id)
        metodo_pago = MetodoPago.objects.get(id=metodo_pago_id)
        
        # Obtener sesiones seleccionadas
        sesiones = Sesion.objects.filter(
            id__in=sesiones_ids,
            paciente=paciente
        ).select_related('servicio') if sesiones_ids else []
        
        # Obtener proyectos seleccionados
        proyectos = Proyecto.objects.filter(
            id__in=proyectos_ids,
            paciente=paciente
        ).select_related('servicio_base') if proyectos_ids else []
        
        # CALCULAR TOTAL Y PREPARAR AJUSTES
        items_ajustados = []
        total_pago = Decimal('0.00')
        
        # Procesar SESIONES
        for sesion in sesiones:
            monto_personalizado_key = f'monto_personalizado_sesion_{sesion.id}'
            monto_personalizado = request.POST.get(monto_personalizado_key)
            
            if monto_personalizado:
                monto_pagar = Decimal(monto_personalizado)
                es_pago_completo = True
            else:
                monto_pagar = sesion.saldo_pendiente
                es_pago_completo = True
            
            if monto_pagar <= 0:
                messages.error(
                    request, 
                    f'❌ Monto inválido para sesión {sesion.fecha}: Bs. {monto_pagar}'
                )
                return redirect('facturacion:pagos_masivos')
            
            items_ajustados.append({
                'tipo': 'sesion',
                'objeto': sesion,
                'monto_pagar': monto_pagar,
                'es_pago_completo': es_pago_completo,
                'tiene_monto_personalizado': bool(monto_personalizado)
            })
            
            total_pago += monto_pagar
        
        # Procesar PROYECTOS
        for proyecto in proyectos:
            monto_personalizado_key = f'monto_personalizado_proyecto_{proyecto.id}'
            monto_personalizado = request.POST.get(monto_personalizado_key)
            
            if monto_personalizado:
                monto_pagar = Decimal(monto_personalizado)
                es_pago_completo = True
            else:
                monto_pagar = proyecto.saldo_pendiente
                es_pago_completo = True
            
            if monto_pagar <= 0:
                messages.error(
                    request,
                    f'❌ Monto inválido para proyecto {proyecto.codigo}: Bs. {monto_pagar}'
                )
                return redirect('facturacion:pagos_masivos')
            
            items_ajustados.append({
                'tipo': 'proyecto',
                'objeto': proyecto,
                'monto_pagar': monto_pagar,
                'es_pago_completo': es_pago_completo,
                'tiene_monto_personalizado': bool(monto_personalizado)
            })
            
            total_pago += monto_pagar
        
        if total_pago <= 0:
            messages.error(request, '❌ El total a pagar debe ser mayor a 0')
            return redirect('facturacion:pagos_masivos')
        
        # 🔒 TRANSACCIÓN ATÓMICA
        with transaction.atomic():
            # GENERAR UN SOLO NÚMERO DE RECIBO
            ultimo_pago = Pago.objects.filter(
                numero_recibo__startswith='REC-'
            ).order_by('-numero_recibo').first()
            
            if ultimo_pago:
                try:
                    ultimo_numero = int(ultimo_pago.numero_recibo.split('-')[1])
                    nuevo_numero = ultimo_numero + 1
                except (ValueError, IndexError):
                    nuevo_numero = (Pago.objects.count() + 1)
            else:
                nuevo_numero = 1
            
            numero_recibo_compartido = f"REC-{nuevo_numero:04d}"
            
            # 📝 PREPARAR CONCEPTO
            descripcion_items = []
            for item in items_ajustados[:3]:
                if item['tipo'] == 'sesion':
                    s = item['objeto']
                    descripcion_items.append(f"{s.fecha.strftime('%d/%m')} {s.servicio.nombre[:20]}")
                else:  # proyecto
                    p = item['objeto']
                    descripcion_items.append(f"📦 {p.codigo}")
            
            concepto_items = ', '.join(descripcion_items)
            if len(items_ajustados) > 3:
                concepto_items += f" (+{len(items_ajustados) - 3} más)"
            
            # 💾 CREAR PAGOS INDIVIDUALES
            primer_pago_id = None
            
            for ajuste in items_ajustados:
                tipo = ajuste['tipo']
                objeto = ajuste['objeto']
                monto_pagar = ajuste['monto_pagar']
                tiene_monto_personalizado = ajuste['tiene_monto_personalizado']
                
                if tipo == 'sesion':
                    sesion = objeto
                    
                    # Ajustar monto_cobrado si es personalizado
                    if tiene_monto_personalizado:
                        monto_original = sesion.monto_cobrado
                        nuevo_monto_cobrado = sesion.total_pagado + monto_pagar
                        
                        if nuevo_monto_cobrado != sesion.monto_cobrado:
                            sesion.monto_cobrado = nuevo_monto_cobrado
                            nota_ajuste = f"\n[{fecha_pago}] Monto ajustado de Bs. {monto_original} a Bs. {nuevo_monto_cobrado} en pago masivo"
                            sesion.observaciones = (sesion.observaciones or "") + nota_ajuste
                    
                    # Crear pago vinculado a sesión
                    pago_creado = Pago.objects.create(
                        paciente=paciente,
                        sesion=sesion,
                        proyecto=None,
                        fecha_pago=fecha_pago,
                        monto=monto_pagar,
                        metodo_pago=metodo_pago,
                        concepto=f"Pago masivo {numero_recibo_compartido} - Sesión {sesion.fecha} - {sesion.servicio.nombre}",
                        observaciones=f"Parte del pago masivo de {len(items_ajustados)} ítems\n{observaciones}" if observaciones else f"Parte del pago masivo de {len(items_ajustados)} ítems",
                        registrado_por=request.user,
                        numero_recibo=numero_recibo_compartido
                    )
                    
                    if not primer_pago_id:
                        primer_pago_id = pago_creado.id
                    
                    sesion.save()
                
                else:  # tipo == 'proyecto'
                    proyecto = objeto
                    
                    # Ajustar costo_total si es personalizado
                    if tiene_monto_personalizado:
                        costo_original = proyecto.costo_total
                        nuevo_costo = proyecto.total_pagado + monto_pagar
                        
                        if nuevo_costo != proyecto.costo_total:
                            proyecto.costo_total = nuevo_costo
                            proyecto.observaciones = (proyecto.observaciones or "") + f"\n[{fecha_pago}] Costo ajustado de Bs. {costo_original} a Bs. {nuevo_costo} en pago masivo"
                    
                    # Crear pago vinculado a proyecto
                    pago_creado = Pago.objects.create(
                        paciente=paciente,
                        sesion=None,
                        proyecto=proyecto,
                        fecha_pago=fecha_pago,
                        monto=monto_pagar,
                        metodo_pago=metodo_pago,
                        concepto=f"Pago masivo {numero_recibo_compartido} - Proyecto {proyecto.codigo} - {proyecto.nombre}",
                        observaciones=f"Parte del pago masivo de {len(items_ajustados)} ítems\n{observaciones}" if observaciones else f"Parte del pago masivo de {len(items_ajustados)} ítems",
                        registrado_por=request.user,
                        numero_recibo=numero_recibo_compartido
                    )
                    
                    if not primer_pago_id:
                        primer_pago_id = pago_creado.id
                    
                    proyecto.save()
            
            # Actualizar cuenta corriente
            cuenta, created = CuentaCorriente.objects.get_or_create(paciente=paciente)
            cuenta.actualizar_saldo()
        
        # 🆕 PREPARAR DATOS PARA CONFIRMACIÓN
        sesiones_count = sum(1 for i in items_ajustados if i['tipo'] == 'sesion')
        proyectos_count = sum(1 for i in items_ajustados if i['tipo'] == 'proyecto')
        
        mensaje_detalle = []
        if sesiones_count > 0:
            mensaje_detalle.append(f"{sesiones_count} sesión(es)")
        if proyectos_count > 0:
            mensaje_detalle.append(f"{proyectos_count} proyecto(s)")
        
        # Construir concepto detallado
        concepto_completo = f"Pago masivo: {concepto_items}"
        
        # Información de estado
        info_estado = f"{' y '.join(mensaje_detalle)} procesados correctamente"
        
        # 🆕 ALMACENAR EN SESSION para mostrar en confirmación
        request.session['pago_exitoso'] = {
            'tipo': 'Pago Masivo',
            'mensaje': f'Pago masivo registrado exitosamente',
            'detalle': f'{" y ".join(mensaje_detalle)} pagados',
            'total': float(total_pago),
            'paciente': paciente.nombre_completo,
            'concepto': concepto_completo,
            'info_estado': info_estado,
            'genero_recibo': True,
            'numero_recibo': numero_recibo_compartido,
            'pago_id': primer_pago_id,
        }
        
        return redirect('facturacion:confirmacion_pago')
        
    except Exception as e:
        messages.error(request, f'❌ Error al procesar pago masivo: {str(e)}')
        import traceback
        print(traceback.format_exc())
        return redirect('facturacion:pagos_masivos')

# ==================== HISTORIAL DE PAGOS ====================

@login_required
def historial_pagos(request):
    """
    Historial completo de pagos con filtros
    ✅ ACTUALIZADO: Estadísticas mejoradas separando pagos válidos y crédito
    """
    
    # Filtros
    buscar = request.GET.get('q', '').strip()
    metodo_id = request.GET.get('metodo', '')
    fecha_desde = request.GET.get('fecha_desde', '')
    fecha_hasta = request.GET.get('fecha_hasta', '')
    
    # Query base - OPTIMIZADO
    pagos = Pago.objects.select_related(
        'paciente', 'metodo_pago', 'registrado_por', 'sesion__servicio'
    ).filter(
        anulado=False
    ).order_by('-fecha_pago', '-fecha_registro')
    
    # Filtro de búsqueda por paciente
    if buscar:
        pagos = pagos.filter(
            Q(paciente__nombre__icontains=buscar) |
            Q(paciente__apellido__icontains=buscar) |
            Q(numero_recibo__icontains=buscar)
        )
    
    # Filtro por método de pago
    if metodo_id:
        pagos = pagos.filter(metodo_pago_id=metodo_id)
    
    # Filtro por rango de fechas
    if fecha_desde:
        try:
            fecha_desde_obj = datetime.strptime(fecha_desde, '%Y-%m-%d').date()
            pagos = pagos.filter(fecha_pago__gte=fecha_desde_obj)
        except:
            pass
    
    if fecha_hasta:
        try:
            fecha_hasta_obj = datetime.strptime(fecha_hasta, '%Y-%m-%d').date()
            pagos = pagos.filter(fecha_pago__lte=fecha_hasta_obj)
        except:
            pass
    
    # ✅ ESTADÍSTICAS MEJORADAS
    # Total de pagos (todos)
    total_pagos = pagos.count()
    
    # Total pagos válidos (sin crédito)
    pagos_validos = pagos.exclude(metodo_pago__nombre="Uso de Crédito")
    total_pagos_validos = pagos_validos.count()
    
    # Total pagos al crédito
    pagos_credito = pagos.filter(metodo_pago__nombre="Uso de Crédito")
    total_pagos_credito = pagos_credito.count()
    
    # Montos totales
    monto_total = pagos.aggregate(Sum('monto'))['monto__sum'] or Decimal('0.00')
    monto_pagos_validos = pagos_validos.aggregate(Sum('monto'))['monto__sum'] or Decimal('0.00')
    monto_pagos_credito = pagos_credito.aggregate(Sum('monto'))['monto__sum'] or Decimal('0.00')
    
    stats = {
        # Contadores
        'total_pagos': total_pagos,
        'total_pagos_validos': total_pagos_validos,
        'total_pagos_credito': total_pagos_credito,
        
        # Montos
        'monto_total': monto_total,
        'monto_pagos_validos': monto_pagos_validos,
        'monto_pagos_credito': monto_pagos_credito,
    }
    
    # Paginación (25 por página)
    paginator = Paginator(pagos, 25)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    
    # Métodos de pago para filtro
    metodos_pago = MetodoPago.objects.filter(activo=True)
    
    context = {
        'page_obj': page_obj,
        'stats': stats,
        'buscar': buscar,
        'metodo_id': metodo_id,
        'fecha_desde': fecha_desde,
        'fecha_hasta': fecha_hasta,
        'metodos_pago': metodos_pago,
    }
    
    return render(request, 'facturacion/historial_pagos.html', context)

# ==================== RECIBOS PDF ====================

def encontrar_logo():
    """
    Buscar logo en múltiples ubicaciones posibles
    Funciona tanto en desarrollo como en producción
    """
    posibles_rutas = [
        os.path.join(settings.BASE_DIR, 'core', 'static', 'img', 'logo_misael.png'),
        os.path.join(settings.STATIC_ROOT, 'img', 'logo_misael.png'),
        os.path.join(settings.BASE_DIR, 'static', 'img', 'logo_misael.png'),
    ]
    
    if hasattr(settings, 'STATICFILES_DIRS'):
        for static_dir in settings.STATICFILES_DIRS:
            ruta_adicional = os.path.join(static_dir, 'img', 'logo_misael.png')
            posibles_rutas.append(ruta_adicional)
    
    for ruta in posibles_rutas:
        if os.path.exists(ruta):
            return ruta
    
    return None

@login_required
def generar_recibo_pdf(request, pago_id):
    """
    Generar recibo en PDF
    """
    
    pago = get_object_or_404(
        Pago.objects.select_related(
            'paciente', 'metodo_pago', 'registrado_por', 'sesion__servicio'
        ),
        id=pago_id
    )
    
    # Validación: NO permitir generar PDF para pagos con crédito
    if pago.metodo_pago.nombre == "Uso de Crédito":
        messages.warning(
            request,
            '⚠️ Los pagos realizados con crédito no generan recibo físico. '
            'El recibo se generó cuando se hizo el pago adelantado original.'
        )
        return redirect('facturacion:historial_pagos')
    
    try:
        from xhtml2pdf import pisa
        
        # Buscar todos los pagos con el mismo número de recibo
        pagos_relacionados = Pago.objects.filter(
            numero_recibo=pago.numero_recibo,
            anulado=False
        ).select_related(
            'sesion__servicio', 'sesion__profesional', 'sesion__sucursal',
            'proyecto'
        ).order_by('sesion__fecha')
        
        total_recibo = sum(p.monto for p in pagos_relacionados)
        
        # Cargar logo como Base64
        logo_base64 = None
        logo_path = encontrar_logo()
        
        if logo_path and os.path.exists(logo_path):
            try:
                with open(logo_path, 'rb') as logo_file:
                    logo_data = logo_file.read()
                    logo_base64 = base64.b64encode(logo_data).decode('utf-8')
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f'Error al cargar logo: {str(e)}')
        
        # Renderizar template HTML
        html_string = render(request, 'facturacion/recibo_pdf.html', {
            'pago': pago,
            'pagos_relacionados': pagos_relacionados,
            'total_recibo': total_recibo,
            'es_pago_masivo': pagos_relacionados.count() > 1,
            'para_pdf': True,
            'logo_base64': logo_base64,
        }).content.decode('utf-8')
        
        # Crear buffer para el PDF
        result = BytesIO()
        
        # Convertir HTML a PDF
        pdf = pisa.pisaDocument(
            BytesIO(html_string.encode("UTF-8")), 
            result,
            encoding='UTF-8'
        )
        
        if pdf.err:
            raise Exception(f"Error en la generación del PDF: código {pdf.err}")
        
        # Preparar respuesta
        result.seek(0)
        response = HttpResponse(result.read(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="recibo_{pago.numero_recibo}.pdf"'
        
        return response
        
    except ImportError:
        messages.warning(
            request, 
            '⚠️ PDF no disponible temporalmente. Mostrando versión para imprimir.'
        )
        
        pagos_relacionados = Pago.objects.filter(
            numero_recibo=pago.numero_recibo,
            anulado=False
        ).select_related('sesion__servicio', 'proyecto').order_by('sesion__fecha')
        
        total_recibo = sum(p.monto for p in pagos_relacionados)
        
        logo_base64 = None
        logo_path = encontrar_logo()
        if logo_path and os.path.exists(logo_path):
            try:
                with open(logo_path, 'rb') as logo_file:
                    logo_data = logo_file.read()
                    logo_base64 = base64.b64encode(logo_data).decode('utf-8')
            except:
                pass
        
        return render(request, 'facturacion/recibo_pdf.html', {
            'pago': pago,
            'pagos_relacionados': pagos_relacionados,
            'total_recibo': total_recibo,
            'es_pago_masivo': pagos_relacionados.count() > 1,
            'para_impresion': True,
            'logo_base64': logo_base64,
        })
        
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f'Error generando PDF para pago {pago_id}: {str(e)}')
        
        messages.error(request, '❌ Error al generar PDF. Intenta nuevamente.')
        return redirect('facturacion:historial_pagos')
# ==================== ANULAR PAGOS ====================

@login_required
def anular_pago(request, pago_id):
    """
    Anular un pago (con auditoría)
    OPTIMIZADO: Modal HTMX
    """
    
    pago = get_object_or_404(Pago, id=pago_id)
    
    if request.method == 'POST':
        try:
            from django.db import transaction
            
            motivo = request.POST.get('motivo', '').strip()
            
            if not motivo:
                messages.error(request, '❌ Debes especificar un motivo')
                return redirect('facturacion:historial_pagos')
            
            # 🔒 TRANSACCIÓN ATÓMICA
            with transaction.atomic():
                # Anular pago
                pago.anular(request.user, motivo)
            
            messages.success(request, f'✅ Pago {pago.numero_recibo} anulado correctamente')
            return redirect('facturacion:historial_pagos')
            
        except Exception as e:
            messages.error(request, f'❌ Error al anular pago: {str(e)}')
            return redirect('facturacion:historial_pagos')
    
    # GET - Modal de confirmación
    return render(request, 'facturacion/partials/anular_pago_modal.html', {
        'pago': pago
    })


# ==================== FASE 3: REPORTES ====================

@login_required
def dashboard_reportes(request):
    """
    Dashboard de reportes - punto de entrada
    OPTIMIZADO: Vista simple con enlaces
    """
    return render(request, 'facturacion/reportes/dashboard.html')

@login_required
def reporte_paciente(request):
    """
    Reporte detallado por paciente - CORREGIDO
    ✅ Usa anotaciones en lugar del campo 'pagado' eliminado
    """
    
    paciente_id = request.GET.get('paciente')
    fecha_desde = request.GET.get('fecha_desde', '')
    fecha_hasta = request.GET.get('fecha_hasta', '')
    
    paciente = None
    datos = None
    grafico_data = None
    
    if paciente_id:
        from datetime import datetime, timedelta
        
        paciente = get_object_or_404(
            Paciente.objects.select_related('cuenta_corriente'),
            id=paciente_id
        )
        
        # Rango de fechas (por defecto: Últimos 6 meses)
        if fecha_desde and fecha_hasta:
            fecha_desde_obj = datetime.strptime(fecha_desde, '%Y-%m-%d').date()
            fecha_hasta_obj = datetime.strptime(fecha_hasta, '%Y-%m-%d').date()
        else:
            fecha_hasta_obj = date.today()
            fecha_desde_obj = fecha_hasta_obj - timedelta(days=180)
            fecha_desde = fecha_desde_obj.strftime('%Y-%m-%d')
            fecha_hasta = fecha_hasta_obj.strftime('%Y-%m-%d')
        
        # Query base
        sesiones = Sesion.objects.filter(
            paciente=paciente,
            fecha__gte=fecha_desde_obj,
            fecha__lte=fecha_hasta_obj
        ).select_related('servicio', 'profesional', 'sucursal', 'proyecto')
        
        # ✅ Anotar total_pagado en cada sesión
        sesiones = sesiones.annotate(
            total_pagado_sesion=Sum('pagos__monto', filter=Q(pagos__anulado=False))
        )
        
        # Estadísticas generales
        stats = sesiones.aggregate(
            total_sesiones=Count('id'),
            realizadas=Count('id', filter=Q(estado='realizada')),
            retrasos=Count('id', filter=Q(estado='realizada_retraso')),
            faltas=Count('id', filter=Q(estado='falta')),
            permisos=Count('id', filter=Q(estado='permiso')),
            canceladas=Count('id', filter=Q(estado='cancelada')),
            reprogramadas=Count('id', filter=Q(estado='reprogramada')),
            total_cobrado=Sum('monto_cobrado'),
        )
        
        # Calcular pagos manualmente
        sesiones_list = list(sesiones)
        
        total_pagado = sum(
            s.total_pagado_sesion or Decimal('0.00') 
            for s in sesiones_list
        )
        
        sesiones_pagadas = sum(
            1 for s in sesiones_list 
            if s.monto_cobrado > 0 and 
               (s.total_pagado_sesion or Decimal('0.00')) >= s.monto_cobrado
        )
        
        sesiones_pendientes = sum(
            1 for s in sesiones_list 
            if s.monto_cobrado > 0 and 
               (s.total_pagado_sesion or Decimal('0.00')) < s.monto_cobrado
        )
        
        stats['total_pagado'] = total_pagado
        stats['sesiones_pagadas'] = sesiones_pagadas
        stats['sesiones_pendientes'] = sesiones_pendientes
        stats['saldo_pendiente'] = (stats['total_cobrado'] or Decimal('0.00')) - total_pagado
        
        # Calcular tasa de asistencia
        sesiones_efectivas = stats['realizadas'] + stats['retrasos']
        sesiones_programadas = stats['total_sesiones'] - stats['canceladas'] - stats['permisos']
        tasa_asistencia = (sesiones_efectivas / sesiones_programadas * 100) if sesiones_programadas > 0 else 0
        
        # Tasa de pago
        total_con_cobro = sum(1 for s in sesiones_list if s.monto_cobrado > 0)
        tasa_pago = (sesiones_pagadas / total_con_cobro * 100) if total_con_cobro > 0 else 0
        
        # Por servicio
        por_servicio = sesiones.values(
            'servicio__nombre', 'servicio__color'
        ).annotate(
            cantidad=Count('id'),
            monto_total=Sum('monto_cobrado'),
            sesiones_realizadas=Count('id', filter=Q(estado__in=['realizada', 'realizada_retraso'])),
            sesiones_falta=Count('id', filter=Q(estado='falta'))
        ).order_by('-cantidad')
        
        # Por profesional
        por_profesional = sesiones.filter(
            estado__in=['realizada', 'realizada_retraso']
        ).values(
            'profesional__nombre', 'profesional__apellido'
        ).annotate(
            cantidad=Count('id'),
            monto_total=Sum('monto_cobrado')
        ).order_by('-cantidad')
        
        # Por sucursal
        por_sucursal = sesiones.values(
            'sucursal__nombre'
        ).annotate(
            cantidad=Count('id'),
            realizadas=Count('id', filter=Q(estado='realizada'))
        ).order_by('-cantidad')
        
        # Por mes (para gráfico)
        from django.db.models.functions import TruncMonth
        por_mes = sesiones.annotate(
            mes=TruncMonth('fecha')
        ).values('mes').annotate(
            total=Count('id'),
            realizadas=Count('id', filter=Q(estado='realizada')),
            retrasos=Count('id', filter=Q(estado='realizada_retraso')),
            faltas=Count('id', filter=Q(estado='falta')),
            monto_generado=Sum('monto_cobrado')
        ).order_by('mes')
        
        # Preparar datos para gráfico
        grafico_data = {
            'labels': [m['mes'].strftime('%b %Y') for m in por_mes],
            'realizadas': [m['realizadas'] for m in por_mes],
            'faltas': [m['faltas'] for m in por_mes],
            'retrasos': [m['retrasos'] for m in por_mes],
            'monto': [float(m['monto_generado'] or 0) for m in por_mes],
        }
        
        # Proyectos del paciente
        proyectos_paciente = Proyecto.objects.filter(
            paciente=paciente
        ).select_related('servicio_base', 'profesional_responsable')
        
        proyectos_stats = {
            'total': proyectos_paciente.count(),
            'activos': proyectos_paciente.filter(estado__in=['planificado', 'en_progreso']).count(),
            'finalizados': proyectos_paciente.filter(estado='finalizado').count(),
            'monto_total': proyectos_paciente.aggregate(Sum('costo_total'))['costo_total__sum'] or Decimal('0.00'),
        }
        
        datos = {
            'stats': stats,
            'tasa_asistencia': round(tasa_asistencia, 1),
            'tasa_pago': round(tasa_pago, 1),
            'por_servicio': por_servicio,
            'por_profesional': por_profesional,
            'por_sucursal': por_sucursal,
            'proyectos_stats': proyectos_stats,
            'proyectos': proyectos_paciente[:5],
            'sesiones_recientes': sesiones.order_by('-fecha', '-hora_inicio')[:15],
        }
    
    # Lista de pacientes para selector
    pacientes = Paciente.objects.filter(estado='activo').order_by('apellido', 'nombre')
    
    context = {
        'paciente': paciente,
        'datos': datos,
        'grafico_data': grafico_data,
        'pacientes': pacientes,
        'fecha_desde': fecha_desde,
        'fecha_hasta': fecha_hasta,
    }
    
    return render(request, 'facturacion/reportes/paciente.html', context)

@login_required
def reporte_asistencia(request):
    """
    Reporte de asistencia y cumplimiento - MEJORADO
    ✅ Análisis completo de comportamiento
    """
    
    from datetime import datetime, timedelta
    
    tipo = request.GET.get('tipo', 'general')
    entidad_id = request.GET.get('entidad_id', '')
    fecha_desde = request.GET.get('fecha_desde', '')
    fecha_hasta = request.GET.get('fecha_hasta', '')
    
    # Rango de fechas (últimos 3 meses por defecto)
    if fecha_desde and fecha_hasta:
        fecha_desde_obj = datetime.strptime(fecha_desde, '%Y-%m-%d').date()
        fecha_hasta_obj = datetime.strptime(fecha_hasta, '%Y-%m-%d').date()
    else:
        fecha_hasta_obj = date.today()
        fecha_desde_obj = fecha_hasta_obj - timedelta(days=90)
        fecha_desde = fecha_desde_obj.strftime('%Y-%m-%d')
        fecha_hasta = fecha_hasta_obj.strftime('%Y-%m-%d')
    
    # Query base
    sesiones = Sesion.objects.filter(
        fecha__gte=fecha_desde_obj,
        fecha__lte=fecha_hasta_obj
    ).select_related('paciente', 'servicio', 'profesional', 'sucursal')
    
    # Filtros según tipo
    entidad = None
    if tipo == 'paciente' and entidad_id:
        entidad = Paciente.objects.get(id=entidad_id)
        sesiones = sesiones.filter(paciente=entidad)
    elif tipo == 'profesional' and entidad_id:
        from profesionales.models import Profesional
        entidad = Profesional.objects.get(id=entidad_id)
        sesiones = sesiones.filter(profesional=entidad)
    
    # Estadísticas de asistencia
    stats = sesiones.aggregate(
        total=Count('id'),
        programadas=Count('id', filter=Q(estado='programada')),
        realizadas=Count('id', filter=Q(estado='realizada')),
        retrasos=Count('id', filter=Q(estado='realizada_retraso')),
        faltas=Count('id', filter=Q(estado='falta')),
        permisos=Count('id', filter=Q(estado='permiso')),
        canceladas=Count('id', filter=Q(estado='cancelada')),
    )
    
    # Calcular tasas
    sesiones_efectivas = stats['realizadas'] + stats['retrasos']
    sesiones_programadas = stats['total'] - stats['canceladas'] - stats['permisos']
    
    tasas = {
        'asistencia': (sesiones_efectivas / sesiones_programadas * 100) if sesiones_programadas > 0 else 0,
        'faltas': (stats['faltas'] / sesiones_programadas * 100) if sesiones_programadas > 0 else 0,
        'puntualidad': (stats['realizadas'] / sesiones_efectivas * 100) if sesiones_efectivas > 0 else 0,
        'cancelaciones': (stats['canceladas'] / stats['total'] * 100) if stats['total'] > 0 else 0,
    }
    
    # Ranking de asistencia (si es reporte general)
    ranking = []
    if tipo == 'general':
        pacientes_con_sesiones = Paciente.objects.filter(
            estado='activo',
            sesiones__fecha__gte=fecha_desde_obj,
            sesiones__fecha__lte=fecha_hasta_obj
        ).annotate(
            total=Count('sesiones'),
            realizadas=Count('sesiones', filter=Q(sesiones__estado__in=['realizada', 'realizada_retraso'])),
            faltas=Count('sesiones', filter=Q(sesiones__estado='falta')),
            retrasos=Count('sesiones', filter=Q(sesiones__estado='realizada_retraso'))
        ).filter(total__gte=3)
        
        ranking_data = []
        for p in pacientes_con_sesiones:
            tasa = (p.realizadas / p.total * 100) if p.total > 0 else 0
            ranking_data.append({
                'id': p.id,
                'nombre_completo': p.nombre_completo,
                'total': p.total,
                'realizadas': p.realizadas,
                'faltas': p.faltas,
                'retrasos': p.retrasos,
                'tasa': round(tasa, 1)
            })
        
        ranking = sorted(ranking_data, key=lambda x: x['tasa'], reverse=True)[:15]
    
    # Peores asistentes (opcional)
    peores_asistencia = []
    if tipo == 'general':
        pacientes_problematicos = Paciente.objects.filter(
            estado='activo',
            sesiones__fecha__gte=fecha_desde_obj,
            sesiones__fecha__lte=fecha_hasta_obj
        ).annotate(
            total=Count('sesiones'),
            faltas=Count('sesiones', filter=Q(sesiones__estado='falta')),
            realizadas=Count('sesiones', filter=Q(sesiones__estado__in=['realizada', 'realizada_retraso']))
        ).filter(total__gte=3, faltas__gt=0)
        
        peores_data = []
        for p in pacientes_problematicos:
            tasa_faltas = (p.faltas / p.total * 100) if p.total > 0 else 0
            if tasa_faltas > 20:  # Más del 20% de faltas
                peores_data.append({
                    'id': p.id,
                    'nombre_completo': p.nombre_completo,
                    'total': p.total,
                    'faltas': p.faltas,
                    'realizadas': p.realizadas,
                    'tasa_faltas': round(tasa_faltas, 1)
                })
        
        peores_asistencia = sorted(peores_data, key=lambda x: x['tasa_faltas'], reverse=True)[:10]
    
    # Por día de la semana
    from django.db.models.functions import ExtractWeekDay
    por_dia_semana = sesiones.annotate(
        dia_semana=ExtractWeekDay('fecha')
    ).values('dia_semana').annotate(
        total=Count('id'),
        realizadas=Count('id', filter=Q(estado='realizada')),
        faltas=Count('id', filter=Q(estado='falta'))
    ).order_by('dia_semana')
    
    dias_nombres = {1: 'Domingo', 2: 'Lunes', 3: 'Martes', 4: 'Miércoles', 
                   5: 'Jueves', 6: 'Viernes', 7: 'Sábado'}
    for dia in por_dia_semana:
        dia['nombre'] = dias_nombres.get(dia['dia_semana'], 'N/A')
    
    # Por servicio
    por_servicio = sesiones.values(
        'servicio__nombre'
    ).annotate(
        total=Count('id'),
        realizadas=Count('id', filter=Q(estado='realizada')),
        faltas=Count('id', filter=Q(estado='falta'))
    ).order_by('-total')
    
    # Evolución mensual
    from django.db.models.functions import TruncMonth
    por_mes = sesiones.annotate(
        mes=TruncMonth('fecha')
    ).values('mes').annotate(
        total=Count('id'),
        realizadas=Count('id', filter=Q(estado='realizada')),
        retrasos=Count('id', filter=Q(estado='realizada_retraso')),
        faltas=Count('id', filter=Q(estado='falta'))
    ).order_by('mes')
    
    grafico_data = {
        'labels': [m['mes'].strftime('%b %Y') for m in por_mes],
        'realizadas': [m['realizadas'] for m in por_mes],
        'retrasos': [m['retrasos'] for m in por_mes],
        'faltas': [m['faltas'] for m in por_mes],
    }
    
    # Listas para filtros
    pacientes = Paciente.objects.filter(estado='activo').order_by('apellido', 'nombre')
    
    from profesionales.models import Profesional
    profesionales = Profesional.objects.filter(activo=True).order_by('apellido', 'nombre')
    
    context = {
        'tipo': tipo,
        'entidad': entidad,
        'stats': stats,
        'tasas': tasas,
        'ranking': ranking,
        'peores_asistencia': peores_asistencia,
        'por_dia_semana': por_dia_semana,
        'por_servicio': por_servicio,
        'grafico_data': grafico_data,
        'pacientes': pacientes,
        'profesionales': profesionales,
        'fecha_desde': fecha_desde,
        'fecha_hasta': fecha_hasta,
    }

    return render(request, 'facturacion/reportes/asistencia.html', context)
           

@login_required
def reporte_profesional(request):
    """
    Reporte detallado por profesional - MEJORADO
    ✅ Estadísticas completas de desempeño
    """
    
    from profesionales.models import Profesional
    
    profesional_id = request.GET.get('profesional')
    sucursal_id = request.GET.get('sucursal', '')
    fecha_desde = request.GET.get('fecha_desde', '')
    fecha_hasta = request.GET.get('fecha_hasta', '')
    
    profesional = None
    datos = None
    grafico_data = None
    
    if profesional_id:
        from datetime import datetime, timedelta
        
        profesional = get_object_or_404(Profesional, id=profesional_id)
        
        # Rango de fechas (por defecto: últimos 3 meses)
        if fecha_desde and fecha_hasta:
            fecha_desde_obj = datetime.strptime(fecha_desde, '%Y-%m-%d').date()
            fecha_hasta_obj = datetime.strptime(fecha_hasta, '%Y-%m-%d').date()
        else:
            fecha_hasta_obj = date.today()
            fecha_desde_obj = fecha_hasta_obj - timedelta(days=90)
            fecha_desde = fecha_desde_obj.strftime('%Y-%m-%d')
            fecha_hasta = fecha_hasta_obj.strftime('%Y-%m-%d')
        
        # Query base
        sesiones = Sesion.objects.filter(
            profesional=profesional,
            fecha__gte=fecha_desde_obj,
            fecha__lte=fecha_hasta_obj
        )
        
        # Filtro por sucursal
        if sucursal_id:
            sesiones = sesiones.filter(sucursal_id=sucursal_id)
        
        sesiones = sesiones.select_related('paciente', 'servicio', 'sucursal', 'proyecto')
        
        # Estadísticas
        stats = sesiones.aggregate(
            total_sesiones=Count('id'),
            programadas=Count('id', filter=Q(estado='programada')),
            realizadas=Count('id', filter=Q(estado='realizada')),
            retrasos=Count('id', filter=Q(estado='realizada_retraso')),
            faltas=Count('id', filter=Q(estado='falta')),
            canceladas=Count('id', filter=Q(estado='cancelada')),
            total_generado=Sum('monto_cobrado', filter=Q(estado__in=['realizada', 'realizada_retraso'])),
            pacientes_unicos=Count('paciente', distinct=True),
            total_horas=Sum('duracion_minutos', filter=Q(estado__in=['realizada', 'realizada_retraso']))
        )
        
        # Convertir minutos a horas
        stats['total_horas_decimal'] = (stats['total_horas'] or 0) / 60
        
        # Calcular tasas
        sesiones_efectivas = (stats['realizadas'] or 0) + (stats['retrasos'] or 0)
        total_programado = stats['total_sesiones'] - (stats['canceladas'] or 0)
        
        tasa_cumplimiento = (sesiones_efectivas / total_programado * 100) if total_programado > 0 else 0
        tasa_puntualidad = ((stats['realizadas'] or 0) / sesiones_efectivas * 100) if sesiones_efectivas > 0 else 0
        
        stats['tasa_cumplimiento'] = round(tasa_cumplimiento, 1)
        stats['tasa_puntualidad'] = round(tasa_puntualidad, 1)
        stats['ingreso_por_hora'] = (stats['total_generado'] or Decimal('0.00')) / Decimal(str(stats['total_horas_decimal'])) if stats['total_horas_decimal'] > 0 else Decimal('0.00')
        
        # Por servicio
        por_servicio = sesiones.values(
            'servicio__nombre', 'servicio__color'
        ).annotate(
            cantidad=Count('id'),
            realizadas=Count('id', filter=Q(estado__in=['realizada', 'realizada_retraso'])),
            ingresos=Sum('monto_cobrado', filter=Q(estado__in=['realizada', 'realizada_retraso'])),
            horas_total=Sum('duracion_minutos', filter=Q(estado__in=['realizada', 'realizada_retraso']))
        ).order_by('-cantidad')
        
        # Agregar horas decimales
        for servicio in por_servicio:
            servicio['horas_decimal'] = (servicio['horas_total'] or 0) / 60
        
        # Por sucursal
        por_sucursal = sesiones.values(
            'sucursal__nombre'
        ).annotate(
            cantidad=Count('id'),
            realizadas=Count('id', filter=Q(estado='realizada')),
            ingresos=Sum('monto_cobrado', filter=Q(estado__in=['realizada', 'realizada_retraso']))
        ).order_by('-cantidad')
        
        # Top pacientes atendidos
        top_pacientes = sesiones.values(
            'paciente__nombre', 'paciente__apellido', 'paciente__id'
        ).annotate(
            sesiones=Count('id'),
            realizadas=Count('id', filter=Q(estado__in=['realizada', 'realizada_retraso'])),
            faltas=Count('id', filter=Q(estado='falta'))
        ).order_by('-sesiones')[:10]
        
        # Por día de la semana
        from django.db.models.functions import ExtractWeekDay
        por_dia_semana = sesiones.annotate(
            dia_semana=ExtractWeekDay('fecha')
        ).values('dia_semana').annotate(
            cantidad=Count('id'),
            realizadas=Count('id', filter=Q(estado='realizada'))
        ).order_by('dia_semana')
        
        # Mapear días
        dias_nombres = {1: 'Domingo', 2: 'Lunes', 3: 'Martes', 4: 'Miércoles', 
                       5: 'Jueves', 6: 'Viernes', 7: 'Sábado'}
        for dia in por_dia_semana:
            dia['nombre'] = dias_nombres.get(dia['dia_semana'], 'N/A')
        
        # Por mes (gráfico)
        from django.db.models.functions import TruncMonth
        por_mes = sesiones.annotate(
            mes=TruncMonth('fecha')
        ).values('mes').annotate(
            cantidad=Count('id'),
            realizadas=Count('id', filter=Q(estado='realizada')),
            ingresos=Sum('monto_cobrado', filter=Q(estado__in=['realizada', 'realizada_retraso']))
        ).order_by('mes')
        
        grafico_data = {
            'labels': [m['mes'].strftime('%b %Y') for m in por_mes],
            'sesiones': [m['cantidad'] for m in por_mes],
            'realizadas': [m['realizadas'] for m in por_mes],
            'ingresos': [float(m['ingresos'] or 0) for m in por_mes],
        }
        
        datos = {
            'stats': stats,
            'por_servicio': por_servicio,
            'por_sucursal': por_sucursal,
            'top_pacientes': top_pacientes,
            'por_dia_semana': por_dia_semana,
        }
    
    # Listas para filtros
    profesionales = Profesional.objects.filter(activo=True).order_by('apellido', 'nombre')
    
    from servicios.models import Sucursal
    sucursales = Sucursal.objects.filter(activa=True)
    
    context = {
        'profesional': profesional,
        'datos': datos,
        'grafico_data': grafico_data,
        'profesionales': profesionales,
        'sucursales': sucursales,
        'sucursal_id': sucursal_id,
        'fecha_desde': fecha_desde,
        'fecha_hasta': fecha_hasta,
    }
    
    return render(request, 'facturacion/reportes/profesional.html', context)


@login_required
def reporte_sucursal(request):
    """
    Reporte detallado por sucursal - MEJORADO
    ✅ Comparativas y estadísticas completas
    """
    
    from servicios.models import Sucursal
    
    sucursal_id = request.GET.get('sucursal')
    fecha_desde = request.GET.get('fecha_desde', '')
    fecha_hasta = request.GET.get('fecha_hasta', '')
    
    sucursal = None
    datos = None
    comparativa = []
    grafico_data = None
    
    if sucursal_id:
        from datetime import datetime, timedelta
        
        sucursal = get_object_or_404(Sucursal, id=sucursal_id)
        
        # Rango de fechas
        if fecha_desde and fecha_hasta:
            fecha_desde_obj = datetime.strptime(fecha_desde, '%Y-%m-%d').date()
            fecha_hasta_obj = datetime.strptime(fecha_hasta, '%Y-%m-%d').date()
        else:
            fecha_hasta_obj = date.today()
            fecha_desde_obj = fecha_hasta_obj - timedelta(days=90)
            fecha_desde = fecha_desde_obj.strftime('%Y-%m-%d')
            fecha_hasta = fecha_hasta_obj.strftime('%Y-%m-%d')
        
        # Query base
        sesiones = Sesion.objects.filter(
            sucursal=sucursal,
            fecha__gte=fecha_desde_obj,
            fecha__lte=fecha_hasta_obj
        ).select_related('paciente', 'servicio', 'profesional')
        
        # Estadísticas
        stats = sesiones.aggregate(
            total_sesiones=Count('id'),
            realizadas=Count('id', filter=Q(estado='realizada')),
            retrasos=Count('id', filter=Q(estado='realizada_retraso')),
            faltas=Count('id', filter=Q(estado='falta')),
            canceladas=Count('id', filter=Q(estado='cancelada')),
            ingresos_total=Sum('monto_cobrado', filter=Q(estado__in=['realizada', 'realizada_retraso'])),
            profesionales_activos=Count('profesional', distinct=True),
            pacientes_activos=Count('paciente', distinct=True),
            total_horas=Sum('duracion_minutos', filter=Q(estado__in=['realizada', 'realizada_retraso']))
        )
        
        stats['total_horas_decimal'] = (stats['total_horas'] or 0) / 60
        
        # Tasas
        sesiones_efectivas = (stats['realizadas'] or 0) + (stats['retrasos'] or 0)
        total_prog = stats['total_sesiones'] - (stats['canceladas'] or 0)
        tasa_ocupacion = (sesiones_efectivas / total_prog * 100) if total_prog > 0 else 0
        stats['tasa_ocupacion'] = round(tasa_ocupacion, 1)
        
        # Ingreso promedio por sesión
        stats['ingreso_promedio'] = (stats['ingresos_total'] or Decimal('0.00')) / sesiones_efectivas if sesiones_efectivas > 0 else Decimal('0.00')
        
        # Por servicio
        por_servicio = sesiones.values(
            'servicio__nombre', 'servicio__color'
        ).annotate(
            cantidad=Count('id'),
            realizadas=Count('id', filter=Q(estado='realizada')),
            ingresos=Sum('monto_cobrado', filter=Q(estado__in=['realizada', 'realizada_retraso']))
        ).order_by('-cantidad')
        
        # Top profesionales
        top_profesionales = sesiones.values(
            'profesional__nombre', 'profesional__apellido', 'profesional__id'
        ).annotate(
            sesiones=Count('id'),
            realizadas=Count('id', filter=Q(estado='realizada')),
            ingresos=Sum('monto_cobrado', filter=Q(estado__in=['realizada', 'realizada_retraso']))
        ).order_by('-sesiones')[:10]
        
        # Top pacientes
        top_pacientes = sesiones.values(
            'paciente__nombre', 'paciente__apellido'
        ).annotate(
            sesiones=Count('id'),
            realizadas=Count('id', filter=Q(estado='realizada'))
        ).order_by('-sesiones')[:10]
        
        # Por mes
        from django.db.models.functions import TruncMonth
        por_mes = sesiones.annotate(
            mes=TruncMonth('fecha')
        ).values('mes').annotate(
            total=Count('id'),
            realizadas=Count('id', filter=Q(estado='realizada')),
            ingresos=Sum('monto_cobrado', filter=Q(estado__in=['realizada', 'realizada_retraso']))
        ).order_by('mes')
        
        grafico_data = {
            'labels': [m['mes'].strftime('%b %Y') for m in por_mes],
            'sesiones': [m['total'] for m in por_mes],
            'realizadas': [m['realizadas'] for m in por_mes],
            'ingresos': [float(m['ingresos'] or 0) for m in por_mes],
        }
        
        datos = {
            'stats': stats,
            'por_servicio': por_servicio,
            'top_profesionales': top_profesionales,
            'top_pacientes': top_pacientes,
        }
        
        # Comparativa con otras sucursales
        todas_sucursales = Sucursal.objects.filter(activa=True)
        
        comparativa_data = []
        for suc in todas_sucursales:
            suc_sesiones = Sesion.objects.filter(
                sucursal=suc,
                fecha__gte=fecha_desde_obj,
                fecha__lte=fecha_hasta_obj
            )
            
            suc_stats = suc_sesiones.aggregate(
                sesiones=Count('id'),
                realizadas=Count('id', filter=Q(estado='realizada')),
                ingresos=Sum('monto_cobrado', filter=Q(estado__in=['realizada', 'realizada_retraso']))
            )
            
            comparativa_data.append({
                'id': suc.id,
                'nombre': suc.nombre,
                'sesiones': suc_stats['sesiones'] or 0,
                'realizadas': suc_stats['realizadas'] or 0,
                'ingresos': suc_stats['ingresos'] or Decimal('0.00'),
                'es_actual': suc.id == sucursal.id
            })
        
        comparativa = sorted(comparativa_data, key=lambda x: x['sesiones'], reverse=True)
    
    # Lista de sucursales
    sucursales = Sucursal.objects.filter(activa=True)
    
    context = {
        'sucursal': sucursal,
        'datos': datos,
        'comparativa': comparativa,
        'grafico_data': grafico_data,
        'sucursales': sucursales,
        'fecha_desde': fecha_desde,
        'fecha_hasta': fecha_hasta,
    }
    
    return render(request, 'facturacion/reportes/sucursal.html', context)

@login_required
def reporte_financiero(request):
    """
    Reporte financiero completo - MEJORADO
    ✅ Incluye: sesiones, proyectos, créditos, métodos de pago, cierre de caja
    """
    
    from datetime import datetime, timedelta
    from servicios.models import Sucursal
    from agenda.models import Proyecto
    
    sucursal_id = request.GET.get('sucursal', '')
    fecha_desde = request.GET.get('fecha_desde', '')
    fecha_hasta = request.GET.get('fecha_hasta', '')
    vista = request.GET.get('vista', 'mensual')  # mensual o diaria
    
    # Rango de fechas
    if fecha_desde and fecha_hasta:
        fecha_desde_obj = datetime.strptime(fecha_desde, '%Y-%m-%d').date()
        fecha_hasta_obj = datetime.strptime(fecha_hasta, '%Y-%m-%d').date()
    else:
        fecha_hasta_obj = date.today()
        if vista == 'diaria':
            fecha_desde_obj = fecha_hasta_obj
        else:
            fecha_desde_obj = fecha_hasta_obj.replace(day=1)
        fecha_desde = fecha_desde_obj.strftime('%Y-%m-%d')
        fecha_hasta = fecha_hasta_obj.strftime('%Y-%m-%d')
    
    # ==================== SESIONES ====================
    sesiones = Sesion.objects.filter(
        fecha__gte=fecha_desde_obj,
        fecha__lte=fecha_hasta_obj
    ).select_related('paciente', 'servicio', 'profesional', 'sucursal')
    
    # ==================== PROYECTOS ====================
    proyectos = Proyecto.objects.filter(
        fecha_inicio__gte=fecha_desde_obj,
        fecha_inicio__lte=fecha_hasta_obj
    ).select_related('paciente', 'servicio_base', 'profesional_responsable', 'sucursal')
    
    # ==================== PAGOS ====================
    pagos = Pago.objects.filter(
        fecha_pago__gte=fecha_desde_obj,
        fecha_pago__lte=fecha_hasta_obj,
        anulado=False
    ).select_related('paciente', 'metodo_pago', 'sesion', 'proyecto')
    
    # Filtro por sucursal
    if sucursal_id:
        sesiones = sesiones.filter(sucursal_id=sucursal_id)
        proyectos = proyectos.filter(sucursal_id=sucursal_id)
        pagos = pagos.filter(
            Q(sesion__sucursal_id=sucursal_id) | 
            Q(proyecto__sucursal_id=sucursal_id) |
            Q(sesion__isnull=True, proyecto__isnull=True, paciente__sucursales__id=sucursal_id)
        )
    
    # ==================== INGRESOS POR SESIONES ====================
    sesiones_realizadas = sesiones.filter(estado__in=['realizada', 'realizada_retraso'])
    
    ingresos_sesiones = {
        'total_generado': sesiones_realizadas.aggregate(Sum('monto_cobrado'))['monto_cobrado__sum'] or Decimal('0.00'),
        'cantidad_sesiones': sesiones_realizadas.count(),
    }
    
    # Calcular pagado en sesiones
    pagos_sesiones = pagos.filter(sesion__isnull=False).exclude(metodo_pago__nombre="Uso de Crédito")
    ingresos_sesiones['total_cobrado'] = pagos_sesiones.aggregate(Sum('monto'))['monto__sum'] or Decimal('0.00')
    ingresos_sesiones['total_pendiente'] = ingresos_sesiones['total_generado'] - ingresos_sesiones['total_cobrado']
    
    # ==================== INGRESOS POR PROYECTOS ====================
    ingresos_proyectos = {
        'total_generado': proyectos.aggregate(Sum('costo_total'))['costo_total__sum'] or Decimal('0.00'),
        'cantidad_proyectos': proyectos.count(),
        'proyectos_activos': proyectos.filter(estado__in=['planificado', 'en_progreso']).count(),
        'proyectos_finalizados': proyectos.filter(estado='finalizado').count(),
    }
    
    # Calcular pagado en proyectos
    pagos_proyectos = pagos.filter(proyecto__isnull=False).exclude(metodo_pago__nombre="Uso de Crédito")
    ingresos_proyectos['total_cobrado'] = pagos_proyectos.aggregate(Sum('monto'))['monto__sum'] or Decimal('0.00')
    ingresos_proyectos['total_pendiente'] = ingresos_proyectos['total_generado'] - ingresos_proyectos['total_cobrado']
    
    # ==================== MOVIMIENTO DE CRÉDITOS ====================
    # Pagos adelantados (generan crédito)
    pagos_adelantados = pagos.filter(
        sesion__isnull=True,
        proyecto__isnull=True
    ).exclude(metodo_pago__nombre="Uso de Crédito")
    
    creditos_generados = pagos_adelantados.aggregate(Sum('monto'))['monto__sum'] or Decimal('0.00')
    
    # Uso de crédito
    pagos_con_credito = Pago.objects.filter(
        fecha_pago__gte=fecha_desde_obj,
        fecha_pago__lte=fecha_hasta_obj,
        metodo_pago__nombre="Uso de Crédito",
        anulado=False
    )
    
    creditos_utilizados = pagos_con_credito.aggregate(Sum('monto'))['monto__sum'] or Decimal('0.00')
    
    movimiento_creditos = {
        'generados': creditos_generados,
        'generados_cantidad': pagos_adelantados.count(),
        'utilizados': creditos_utilizados,
        'utilizados_cantidad': pagos_con_credito.count(),
        'saldo_neto': creditos_generados - creditos_utilizados,
    }
    
    # ==================== TOTALES GENERALES ====================
    ingresos = {
        'total_generado': ingresos_sesiones['total_generado'] + ingresos_proyectos['total_generado'],
        'total_cobrado': ingresos_sesiones['total_cobrado'] + ingresos_proyectos['total_cobrado'] + creditos_generados,
        'total_pendiente': ingresos_sesiones['total_pendiente'] + ingresos_proyectos['total_pendiente'],
        'sesiones': ingresos_sesiones,
        'proyectos': ingresos_proyectos,
        'creditos': movimiento_creditos,
    }
    
    # Calcular promedios
    total_items = ingresos_sesiones['cantidad_sesiones'] + ingresos_proyectos['cantidad_proyectos']
    ingresos['promedio_por_item'] = ingresos['total_generado'] / total_items if total_items > 0 else Decimal('0.00')
    ingresos['tasa_cobranza'] = (ingresos['total_cobrado'] / ingresos['total_generado'] * 100) if ingresos['total_generado'] > 0 else 0
    
    # ==================== POR MÉTODO DE PAGO ====================
    por_metodo = pagos.exclude(metodo_pago__nombre="Uso de Crédito").values(
        'metodo_pago__nombre'
    ).annotate(
        cantidad=Count('id'),
        monto=Sum('monto')
    ).order_by('-monto')
    
    # ==================== POR SERVICIO ====================
    # Sesiones
    por_servicio_sesiones = sesiones_realizadas.values(
        'servicio__nombre', 'servicio__color'
    ).annotate(
        sesiones=Count('id'),
        ingresos=Sum('monto_cobrado')
    )
    
    # Proyectos
    por_servicio_proyectos = proyectos.values(
        'servicio_base__nombre', 'servicio_base__color'
    ).annotate(
        proyectos=Count('id'),
        ingresos=Sum('costo_total')
    )
    
    # Combinar servicios
    servicios_dict = {}
    
    for s in por_servicio_sesiones:
        nombre = s['servicio__nombre']
        servicios_dict[nombre] = {
            'nombre': nombre,
            'color': s['servicio__color'],
            'sesiones': s['sesiones'],
            'proyectos': 0,
            'ingresos': s['ingresos'] or Decimal('0.00')
        }
    
    for p in por_servicio_proyectos:
        nombre = p['servicio_base__nombre']
        if nombre in servicios_dict:
            servicios_dict[nombre]['proyectos'] = p['proyectos']
            servicios_dict[nombre]['ingresos'] += p['ingresos'] or Decimal('0.00')
        else:
            servicios_dict[nombre] = {
                'nombre': nombre,
                'color': p['servicio_base__color'],
                'sesiones': 0,
                'proyectos': p['proyectos'],
                'ingresos': p['ingresos'] or Decimal('0.00')
            }
    
    por_servicio = sorted(servicios_dict.values(), key=lambda x: x['ingresos'], reverse=True)[:10]
    
    # ==================== CIERRE DE CAJA DIARIO ====================
    cierre_diario = None
    
    if vista == 'diaria':
        pagos_dia = pagos.filter(fecha_pago=fecha_desde_obj)
        
        # Total cobrado (sin crédito)
        pagos_dia_validos = pagos_dia.exclude(metodo_pago__nombre="Uso de Crédito")
        
        cierre_diario = {
            'fecha': fecha_desde_obj,
            'fecha_formato': fecha_desde_obj.strftime('%d de %B de %Y'),
            'dia_semana': ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo'][fecha_desde_obj.weekday()],
            
            # Pagos totales
            'pagos_total': pagos_dia_validos.count(),
            'monto_total': pagos_dia_validos.aggregate(Sum('monto'))['monto__sum'] or Decimal('0.00'),
            
            # Detalle por método
            'por_metodo': pagos_dia_validos.values('metodo_pago__nombre').annotate(
                cantidad=Count('id'),
                monto=Sum('monto')
            ).order_by('-monto'),
            
            # Sesiones del día
            'sesiones_realizadas': sesiones.filter(
                fecha=fecha_desde_obj,
                estado__in=['realizada', 'realizada_retraso']
            ).count(),
            'monto_generado_sesiones': sesiones.filter(
                fecha=fecha_desde_obj,
                estado__in=['realizada', 'realizada_retraso']
            ).aggregate(Sum('monto_cobrado'))['monto_cobrado__sum'] or Decimal('0.00'),
            
            # Proyectos del día
            'proyectos_iniciados': proyectos.filter(fecha_inicio=fecha_desde_obj).count(),
            'monto_proyectos': proyectos.filter(fecha_inicio=fecha_desde_obj).aggregate(Sum('costo_total'))['costo_total__sum'] or Decimal('0.00'),
            
            # Créditos del día
            'creditos_generados': pagos_dia.filter(sesion__isnull=True, proyecto__isnull=True).exclude(metodo_pago__nombre="Uso de Crédito").aggregate(Sum('monto'))['monto__sum'] or Decimal('0.00'),
            'creditos_utilizados': pagos_dia.filter(metodo_pago__nombre="Uso de Crédito").aggregate(Sum('monto'))['monto__sum'] or Decimal('0.00'),
        }
        
        # Efectivo esperado
        cierre_diario['efectivo_esperado'] = pagos_dia_validos.filter(
            metodo_pago__nombre__in=['Efectivo', 'efectivo']
        ).aggregate(Sum('monto'))['monto__sum'] or Decimal('0.00')
        
        # Detalle COMPLETO de pagos del día (agrupados por recibo para pagos masivos)
        pagos_detalle_raw = pagos_dia_validos.select_related(
            'paciente', 'metodo_pago', 'sesion__servicio', 'proyecto', 'registrado_por'
        ).order_by('numero_recibo', '-monto')
        
        # Agrupar pagos por recibo
        pagos_agrupados = {}
        for pago in pagos_detalle_raw:
            recibo = pago.numero_recibo
            if recibo not in pagos_agrupados:
                pagos_agrupados[recibo] = {
                    'recibo': recibo,
                    'paciente': pago.paciente,
                    'metodo_pago': pago.metodo_pago,
                    'registrado_por': pago.registrado_por,
                    'fecha_registro': pago.fecha_registro,
                    'observaciones': pago.observaciones,
                    'numero_transaccion': pago.numero_transaccion,
                    'pagos': [],
                    'total': Decimal('0.00'),
                    'sesiones_count': 0,
                    'proyectos_count': 0,
                    'adelantados_count': 0,
                }
            
            pagos_agrupados[recibo]['pagos'].append(pago)
            pagos_agrupados[recibo]['total'] += pago.monto
            
            # Contar tipos
            if pago.sesion:
                pagos_agrupados[recibo]['sesiones_count'] += 1
            elif pago.proyecto:
                pagos_agrupados[recibo]['proyectos_count'] += 1
            else:
                pagos_agrupados[recibo]['adelantados_count'] += 1
        
        # Marcar como masivos si tienen más de 1 pago
        for recibo_data in pagos_agrupados.values():
            recibo_data['es_masivo'] = len(recibo_data['pagos']) > 1
        
        cierre_diario['pagos_agrupados'] = list(pagos_agrupados.values())
        
        # Estadísticas adicionales del día
        cierre_diario['estadisticas'] = {
            # Pacientes atendidos
            'pacientes_unicos': sesiones.filter(
                fecha=fecha_desde_obj,
                estado__in=['realizada', 'realizada_retraso']
            ).values('paciente').distinct().count(),
            
            # Por profesional
            'por_profesional': sesiones.filter(
                fecha=fecha_desde_obj,
                estado__in=['realizada', 'realizada_retraso']
            ).values('profesional__nombre', 'profesional__apellido').annotate(
                sesiones=Count('id'),
                ingresos=Sum('monto_cobrado')
            ).order_by('-sesiones'),
            
            # Por servicio
            'por_servicio': sesiones.filter(
                fecha=fecha_desde_obj,
                estado__in=['realizada', 'realizada_retraso']
            ).values('servicio__nombre', 'servicio__color').annotate(
                cantidad=Count('id'),
                ingresos=Sum('monto_cobrado')
            ).order_by('-cantidad'),
            
            # Asistencia del día
            'programadas_dia': sesiones.filter(fecha=fecha_desde_obj, estado='programada').count(),
            'retrasos_dia': sesiones.filter(fecha=fecha_desde_obj, estado='realizada_retraso').count(),
            'faltas_dia': sesiones.filter(fecha=fecha_desde_obj, estado='falta').count(),
            'canceladas_dia': sesiones.filter(fecha=fecha_desde_obj, estado='cancelada').count(),
            
            # Promedio ticket del día
            'ticket_promedio': (pagos_dia_validos.aggregate(Sum('monto'))['monto__sum'] or Decimal('0.00')) / pagos_dia_validos.count() if pagos_dia_validos.count() > 0 else Decimal('0.00'),
            
            # Horas trabajadas
            'horas_trabajadas': (sesiones.filter(
                fecha=fecha_desde_obj,
                estado__in=['realizada', 'realizada_retraso']
            ).aggregate(Sum('duracion_minutos'))['duracion_minutos__sum'] or 0) / 60,
            
            # Ingreso por hora
            'ingreso_por_hora': Decimal('0.00'),
        }
        
        # Calcular ingreso por hora
        if cierre_diario['estadisticas']['horas_trabajadas'] > 0:
            cierre_diario['estadisticas']['ingreso_por_hora'] = cierre_diario['monto_generado_sesiones'] / Decimal(str(cierre_diario['estadisticas']['horas_trabajadas']))
        
        # Comparativa con días anteriores (últimos 7 días)
        comparativa_dias = []
        for i in range(1, 8):
            dia_anterior = fecha_desde_obj - timedelta(days=i)
            
            sesiones_dia_ant = sesiones.filter(
                fecha=dia_anterior,
                estado__in=['realizada', 'realizada_retraso']
            ).aggregate(
                cantidad=Count('id'),
                ingresos=Sum('monto_cobrado')
            )
            
            pagos_dia_ant = pagos.filter(
                fecha_pago=dia_anterior
            ).exclude(metodo_pago__nombre="Uso de Crédito").aggregate(
                cobrado=Sum('monto')
            )
            
            comparativa_dias.append({
                'fecha': dia_anterior,
                'dia_semana': ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'][dia_anterior.weekday()],
                'sesiones': sesiones_dia_ant['cantidad'] or 0,
                'ingresos': sesiones_dia_ant['ingresos'] or Decimal('0.00'),
                'cobrado': pagos_dia_ant['cobrado'] or Decimal('0.00'),
            })
        
        cierre_diario['comparativa_dias'] = list(reversed(comparativa_dias))
    
    # ==================== GRÁFICO DE EVOLUCIÓN ====================
    from django.db.models.functions import TruncMonth
    
    fecha_grafico_desde = fecha_hasta_obj - timedelta(days=180)
    
    por_mes = Sesion.objects.filter(
        fecha__gte=fecha_grafico_desde,
        fecha__lte=fecha_hasta_obj,
        estado__in=['realizada', 'realizada_retraso']
    ).annotate(
        mes=TruncMonth('fecha')
    ).values('mes').annotate(
        sesiones=Count('id'),
        ingresos_sesiones=Sum('monto_cobrado')
    ).order_by('mes')
    
    # Agregar proyectos al gráfico
    proyectos_mes = Proyecto.objects.filter(
        fecha_inicio__gte=fecha_grafico_desde,
        fecha_inicio__lte=fecha_hasta_obj
    ).annotate(
        mes=TruncMonth('fecha_inicio')
    ).values('mes').annotate(
        proyectos=Count('id'),
        ingresos_proyectos=Sum('costo_total')
    ).order_by('mes')
    
    # Combinar datos del gráfico
    meses_dict = {}
    
    for m in por_mes:
        mes_str = m['mes'].strftime('%b %Y')
        meses_dict[mes_str] = {
            'sesiones': m['sesiones'],
            'proyectos': 0,
            'ingresos': float(m['ingresos_sesiones'] or 0)
        }
    
    for p in proyectos_mes:
        mes_str = p['mes'].strftime('%b %Y')
        if mes_str in meses_dict:
            meses_dict[mes_str]['proyectos'] = p['proyectos']
            meses_dict[mes_str]['ingresos'] += float(p['ingresos_proyectos'] or 0)
        else:
            meses_dict[mes_str] = {
                'sesiones': 0,
                'proyectos': p['proyectos'],
                'ingresos': float(p['ingresos_proyectos'] or 0)
            }
    
    grafico_data = {
        'labels': list(meses_dict.keys()),
        'sesiones': [meses_dict[k]['sesiones'] for k in meses_dict.keys()],
        'proyectos': [meses_dict[k]['proyectos'] for k in meses_dict.keys()],
        'ingresos': [meses_dict[k]['ingresos'] for k in meses_dict.keys()],
    }
    
    # ==================== TOP PACIENTES ====================
    # Por mayor consumo
    top_pacientes = Paciente.objects.filter(
        Q(sesiones__fecha__gte=fecha_desde_obj, sesiones__fecha__lte=fecha_hasta_obj) |
        Q(proyectos__fecha_inicio__gte=fecha_desde_obj, proyectos__fecha_inicio__lte=fecha_hasta_obj)
    ).annotate(
        sesiones_count=Count('sesiones', filter=Q(sesiones__estado__in=['realizada', 'realizada_retraso'])),
        proyectos_count=Count('proyectos'),
        total_consumido=Sum('sesiones__monto_cobrado', filter=Q(sesiones__estado__in=['realizada', 'realizada_retraso'])) + Sum('proyectos__costo_total')
    ).order_by('-total_consumido')[:10]
    
    # Lista de sucursales para filtro
    sucursales = Sucursal.objects.filter(activa=True)
    
    context = {
        'ingresos': ingresos,
        'por_metodo': por_metodo,
        'por_servicio': por_servicio,
        'grafico_data': grafico_data,
        'cierre_diario': cierre_diario,
        'top_pacientes': top_pacientes,
        'vista': vista,
        'sucursal_id': sucursal_id,
        'sucursales': sucursales,
        'fecha_desde': fecha_desde,
        'fecha_hasta': fecha_hasta,
    }
    
    return render(request, 'facturacion/reportes/financiero.html', context)

@login_required
def exportar_excel(request):
    """
    Exportar datos a Excel
    OPTIMIZADO: Usa openpyxl
    """
    
    tipo = request.GET.get('tipo', 'cuentas')  # cuentas, pagos, sesiones
    
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
        from io import BytesIO
        
        wb = Workbook()
        ws = wb.active
        
        # Header style
        header_fill = PatternFill(start_color="2563EB", end_color="2563EB", fill_type="solid")
        header_font = Font(color="FFFFFF", bold=True)
        
        if tipo == 'cuentas':
            ws.title = "Cuentas Corrientes"
            
            # Headers
            headers = ['Paciente', 'Tutor', 'Teléfono', 'Consumido', 'Pagado', 'Saldo', 'Estado']
            ws.append(headers)
            
            for cell in ws[1]:
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal='center')
            
            # Data
            pacientes = Paciente.objects.filter(
                estado='activo'
            ).select_related('cuenta_corriente').order_by('apellido', 'nombre')
            
            for p in pacientes:
                cuenta = p.cuenta_corriente if hasattr(p, 'cuenta_corriente') else None
                saldo = cuenta.saldo if cuenta else 0
                
                estado = 'DEBE' if saldo < 0 else ('A FAVOR' if saldo > 0 else 'AL DÍA')
                
                ws.append([
                    p.nombre_completo,
                    p.nombre_tutor,
                    p.telefono_tutor,
                    float(cuenta.total_consumido if cuenta else 0),
                    float(cuenta.total_pagado if cuenta else 0),
                    float(saldo),
                    estado
                ])
        
        elif tipo == 'pagos':
            ws.title = "Historial Pagos"
            
            headers = ['Recibo', 'Fecha', 'Paciente', 'Concepto', 'Método', 'Monto']
            ws.append(headers)
            
            for cell in ws[1]:
                cell.fill = header_fill
                cell.font = header_font
            
            pagos = Pago.objects.filter(
                anulado=False
            ).select_related('paciente', 'metodo_pago').order_by('-fecha_pago')[:500]
            
            for pago in pagos:
                ws.append([
                    pago.numero_recibo,
                    pago.fecha_pago.strftime('%d/%m/%Y'),
                    pago.paciente.nombre_completo,
                    pago.concepto[:50],
                    pago.metodo_pago.nombre,
                    float(pago.monto)
                ])
        
        # Ajustar anchos
        for column in ws.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(cell.value)
                except:
                    pass
            adjusted_width = min(max_length + 2, 50)
            ws.column_dimensions[column_letter].width = adjusted_width
        
        # Generar archivo
        output = BytesIO()
        wb.save(output)
        output.seek(0)
        
        response = HttpResponse(
            output.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="reporte_{tipo}_{date.today()}.xlsx"'
        
        return response
        
    except ImportError:
        messages.error(request, '❌ openpyxl no está instalado')
        return redirect('facturacion:dashboard_reportes')
    except Exception as e:
        messages.error(request, f'❌ Error al exportar: {str(e)}')
        return redirect('facturacion:dashboard_reportes')
    
# Agregar estas vistas al archivo facturacion/views.py

@login_required
def api_detalle_sesion(request, sesion_id):
    """
    API: Obtener detalles completos de una sesión (para modal)
    """
    from agenda.models import Sesion
    
    sesion = get_object_or_404(
        Sesion.objects.select_related(
            'paciente', 'servicio', 'profesional', 'sucursal', 'proyecto'
        ),
        id=sesion_id
    )
    
    # Obtener pagos asociados
    pagos = sesion.pagos.filter(anulado=False).select_related(
        'metodo_pago', 'registrado_por'
    ).order_by('-fecha_pago')
    
    return render(request, 'facturacion/partials/detalle_sesion.html', {
        'sesion': sesion,
        'pagos': pagos,
    })


@login_required
def api_detalle_pago(request, pago_id):
    """
    API: Obtener detalles completos de un pago (para modal)
    """
    pago = get_object_or_404(
        Pago.objects.select_related(
            'paciente', 'metodo_pago', 'sesion__servicio', 
            'sesion__profesional', 'sesion__sucursal',
            'proyecto', 'registrado_por', 'anulado_por'
        ),
        id=pago_id
    )
    
    return render(request, 'facturacion/partials/detalle_pago.html', {
        'pago': pago,
    })

# ==================== LIMPIAR PAGOS ANULADOS ====================

from django.contrib.admin.views.decorators import staff_member_required

@staff_member_required
def limpiar_pagos_anulados(request):
    """
    Vista para que administradores limpien pagos anulados
    Solo accesible para staff
    """
    
    if request.method == 'POST':
        try:
            from django.db import transaction
            
            # Obtener parámetros
            dias = int(request.POST.get('dias', 0))
            
            # Filtrar pagos anulados
            pagos_anulados = Pago.objects.filter(anulado=True)
            
            # Filtrar por antigüedad
            if dias > 0:
                from datetime import datetime, timedelta
                fecha_limite = datetime.now() - timedelta(days=dias)
                pagos_anulados = pagos_anulados.filter(fecha_anulacion__lt=fecha_limite)
            
            total = pagos_anulados.count()
            
            if total == 0:
                messages.warning(request, '⚠️ No hay pagos anulados para eliminar con los filtros seleccionados')
                return redirect('facturacion:limpiar_pagos_anulados')
            
            # Transacción atómica
            with transaction.atomic():
                # Obtener pacientes afectados
                pacientes_ids = set(pagos_anulados.values_list('paciente_id', flat=True))
                
                # Eliminar pagos
                eliminados, detalle = pagos_anulados.delete()
                
                # Recalcular cuentas corrientes
                cuentas_actualizadas = 0
                for paciente_id in pacientes_ids:
                    try:
                        cuenta = CuentaCorriente.objects.get(paciente_id=paciente_id)
                        cuenta.actualizar_saldo()
                        cuentas_actualizadas += 1
                    except CuentaCorriente.DoesNotExist:
                        pass
                
                messages.success(
                    request,
                    f'✅ {eliminados} pagos anulados eliminados correctamente. '
                    f'{cuentas_actualizadas} cuentas corrientes actualizadas.'
                )
                
                return redirect('facturacion:historial_pagos')
                
        except Exception as e:
            messages.error(request, f'❌ Error al eliminar pagos: {str(e)}')
            return redirect('facturacion:limpiar_pagos_anulados')
    
    # GET - Mostrar formulario
    from datetime import datetime, timedelta
    
    # Estadísticas de pagos anulados
    total_anulados = Pago.objects.filter(anulado=True).count()
    
    # Por antigüedad
    hoy = datetime.now()
    stats_antiguedad = {
        'ultima_semana': Pago.objects.filter(
            anulado=True,
            fecha_anulacion__gte=hoy - timedelta(days=7)
        ).count(),
        'ultimo_mes': Pago.objects.filter(
            anulado=True,
            fecha_anulacion__gte=hoy - timedelta(days=30)
        ).count(),
        'mas_3_meses': Pago.objects.filter(
            anulado=True,
            fecha_anulacion__lt=hoy - timedelta(days=90)
        ).count(),
    }
    
    # Monto total en pagos anulados
    monto_total = Pago.objects.filter(
        anulado=True
    ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
    
    # Últimos pagos anulados
    ultimos_anulados = Pago.objects.filter(
        anulado=True
    ).select_related(
        'paciente', 'metodo_pago', 'anulado_por'
    ).order_by('-fecha_anulacion')[:20]
    
    context = {
        'total_anulados': total_anulados,
        'stats_antiguedad': stats_antiguedad,
        'monto_total': monto_total,
        'ultimos_anulados': ultimos_anulados,
    }
    
    return render(request, 'facturacion/limpiar_pagos_anulados.html', context)