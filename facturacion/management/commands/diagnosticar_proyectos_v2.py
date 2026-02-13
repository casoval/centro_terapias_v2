# facturacion/management/commands/diagnosticar_proyectos_v2.py

"""
Script de diagnóstico para proyectos con pagos parciales
✅ VERSIÓN 2: Ahora incluye DEVOLUCIONES en el cálculo
"""

from django.core.management.base import BaseCommand
from agenda.models import Proyecto
from facturacion.models import Pago, Devolucion
from django.db.models import Sum
from decimal import Decimal


class Command(BaseCommand):
    help = 'Diagnosticar proyectos con pagos parciales (incluye devoluciones)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--paciente-id',
            type=int,
            help='ID de paciente específico (opcional)',
        )
        parser.add_argument(
            '--proyecto-id',
            type=int,
            help='ID de proyecto específico (opcional)',
        )

    def handle(self, *args, **options):
        paciente_id = options.get('paciente_id')
        proyecto_id = options.get('proyecto_id')
        
        # Filtrar proyectos
        proyectos = Proyecto.objects.filter(
            estado__in=['planificado', 'en_progreso', 'finalizado', 'cancelado']
        )
        
        if paciente_id:
            proyectos = proyectos.filter(paciente_id=paciente_id)
        
        if proyecto_id:
            proyectos = proyectos.filter(id=proyecto_id)
        
        proyectos = proyectos.select_related('paciente').order_by('id')
        
        self.stdout.write("\n" + "="*100)
        self.stdout.write("🔍 DIAGNÓSTICO DE PROYECTOS CON PAGOS PARCIALES (V2 - CON DEVOLUCIONES)")
        self.stdout.write("="*100 + "\n")
        
        problemas_encontrados = 0
        proyectos_ok = 0
        
        for proyecto in proyectos:
            # ✅ CÁLCULO CORRECTO: Incluye devoluciones
            total_pagado = Pago.objects.filter(
                proyecto=proyecto,
                anulado=False
            ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
            
            # ✅ NUEVO: Calcular devoluciones
            total_devoluciones = Devolucion.objects.filter(
                proyecto=proyecto
            ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
            
            # ✅ CÁLCULO CORRECTO: Total neto = Pagado - Devoluciones
            total_neto = total_pagado - total_devoluciones
            
            # ✅ SALDO PENDIENTE: Costo - Neto pagado
            saldo_pendiente_calculado = proyecto.costo_total - total_neto
            
            # Obtener saldo_pendiente del modelo (propiedad)
            try:
                saldo_pendiente_modelo = proyecto.saldo_pendiente
            except:
                saldo_pendiente_modelo = None
            
            # Verificar si hay discrepancia
            tiene_problema = False
            if saldo_pendiente_modelo is None:
                tiene_problema = True
                problema = "⚠️ saldo_pendiente NO EXISTE como propiedad"
            elif abs(saldo_pendiente_calculado - saldo_pendiente_modelo) > Decimal('0.01'):
                tiene_problema = True
                problema = f"❌ DISCREPANCIA: Calculado={saldo_pendiente_calculado}, Modelo={saldo_pendiente_modelo}"
            
            if tiene_problema or saldo_pendiente_calculado > 0:
                self.stdout.write(
                    f"\n{'❌ PROBLEMA' if tiene_problema else '✅ OK'}: "
                    f"Proyecto #{proyecto.id} - {proyecto.nombre} ({proyecto.paciente.nombre_completo})"
                )
                self.stdout.write(f"   Estado: {proyecto.estado}")
                self.stdout.write(f"   Costo Total: Bs. {proyecto.costo_total:,.2f}")
                self.stdout.write(f"   Total Pagado (DB): Bs. {total_pagado:,.2f}")
                
                # ✅ MOSTRAR DEVOLUCIONES
                if total_devoluciones > 0:
                    self.stdout.write(self.style.WARNING(f"   Total Devoluciones: Bs. {total_devoluciones:,.2f}"))
                    self.stdout.write(f"   Neto Pagado (Pagado - Devoluciones): Bs. {total_neto:,.2f}")
                
                self.stdout.write(f"   Saldo Calculado: Bs. {saldo_pendiente_calculado:,.2f}")
                
                if saldo_pendiente_modelo is not None:
                    self.stdout.write(f"   Saldo Modelo: Bs. {saldo_pendiente_modelo:,.2f}")
                else:
                    self.stdout.write(f"   Saldo Modelo: ⚠️ NO DISPONIBLE")
                
                # Mostrar pagos
                pagos = Pago.objects.filter(
                    proyecto=proyecto,
                    anulado=False
                ).values_list('id', 'numero_recibo', 'fecha_pago', 'monto')
                
                if pagos:
                    self.stdout.write(f"   Pagos registrados:")
                    for pago_id, recibo, fecha, monto in pagos:
                        self.stdout.write(f"     • {recibo}: Bs. {monto:,.2f} ({fecha})")
                
                # ✅ MOSTRAR DEVOLUCIONES
                devoluciones = Devolucion.objects.filter(
                    proyecto=proyecto
                ).values_list('id', 'numero_devolucion', 'fecha_devolucion', 'monto', 'motivo')
                
                if devoluciones:
                    self.stdout.write(self.style.WARNING(f"   Devoluciones registradas:"))
                    for dev_id, num_dev, fecha, monto, motivo in devoluciones:
                        self.stdout.write(self.style.WARNING(
                            f"     • {num_dev}: Bs. {monto:,.2f} ({fecha}) - {motivo[:50]}"
                        ))
                
                if tiene_problema:
                    self.stdout.write(f"   {problema}")
                    problemas_encontrados += 1
                else:
                    proyectos_ok += 1
        
        # Resumen
        self.stdout.write("\n" + "="*100)
        self.stdout.write("📊 RESUMEN")
        self.stdout.write("="*100)
        self.stdout.write(f"Total proyectos analizados: {proyectos.count()}")
        self.stdout.write(self.style.SUCCESS(f"✅ Proyectos OK: {proyectos_ok}"))
        
        if problemas_encontrados > 0:
            self.stdout.write(self.style.ERROR(f"❌ Problemas encontrados: {problemas_encontrados}"))
            self.stdout.write("\n💡 POSIBLES SOLUCIONES:")
            self.stdout.write("1. Verificar que la propiedad 'saldo_pendiente' incluya devoluciones")
            self.stdout.write("2. La fórmula correcta es: saldo = costo_total - (total_pagado - total_devoluciones)")
            self.stdout.write("3. O simplificado: saldo = costo_total - total_pagado + total_devoluciones")
        else:
            self.stdout.write(self.style.SUCCESS("\n🎉 ¡No se encontraron problemas!"))
        
        self.stdout.write("="*100 + "\n")