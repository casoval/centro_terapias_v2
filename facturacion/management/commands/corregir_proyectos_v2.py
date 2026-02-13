# facturacion/management/commands/corregir_proyectos_v2.py

"""
Script para corregir automáticamente problemas con proyectos antiguos
✅ VERSIÓN 2: Ahora considera DEVOLUCIONES en el cálculo
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum
from agenda.models import Proyecto
from facturacion.models import Pago, Devolucion
from facturacion.services import AccountService
from decimal import Decimal


class Command(BaseCommand):
    help = 'Corregir proyectos con pagos/devoluciones (V2 - incluye devoluciones)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Mostrar qué se haría sin hacer cambios',
        )
        parser.add_argument(
            '--paciente-id',
            type=int,
            help='ID de paciente específico (opcional)',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        paciente_id = options.get('paciente_id')
        
        self.stdout.write("\n" + "="*100)
        if dry_run:
            self.stdout.write("🔍 MODO DRY-RUN: Solo mostrando cambios, sin aplicar")
        else:
            self.stdout.write("⚠️ MODO REAL: Los cambios se aplicarán a la base de datos")
        self.stdout.write("="*100 + "\n")
        
        # Filtrar proyectos
        proyectos = Proyecto.objects.all()
        
        if paciente_id:
            proyectos = proyectos.filter(paciente_id=paciente_id)
        
        total_proyectos = proyectos.count()
        proyectos_corregidos = 0
        errores = []
        
        self.stdout.write(f"📦 Analizando {total_proyectos} proyectos...\n")
        
        for i, proyecto in enumerate(proyectos, 1):
            try:
                # ✅ Calcular pagos actuales
                total_pagado = Pago.objects.filter(
                    proyecto=proyecto,
                    anulado=False
                ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
                
                # ✅ Calcular devoluciones
                total_devoluciones = Devolucion.objects.filter(
                    proyecto=proyecto
                ).aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
                
                # ✅ Calcular neto (pagado - devoluciones)
                total_neto = total_pagado - total_devoluciones
                
                # ✅ Calcular saldo pendiente
                saldo_pendiente = proyecto.costo_total - total_neto
                
                # Determinar si el proyecto necesita corrección
                necesita_correccion = False
                cambios = []
                
                # Verificación 1: Proyecto con pagos parciales en estado incorrecto
                if total_neto > 0 and saldo_pendiente > Decimal('0.01'):
                    # Tiene pagos parciales (neto), debería estar 'en_progreso'
                    if proyecto.estado not in ['en_progreso', 'finalizado']:
                        necesita_correccion = True
                        cambios.append(
                            f"Estado '{proyecto.estado}' → 'en_progreso' "
                            f"(tiene pagos netos parciales: Bs. {total_neto})"
                        )
                        if not dry_run:
                            proyecto.estado = 'en_progreso'
                
                # Verificación 2: Proyecto completamente pagado (neto >= costo)
                elif saldo_pendiente <= Decimal('0.01') and total_neto >= proyecto.costo_total:
                    # Está completamente pagado (neto)
                    if proyecto.estado == 'en_progreso':
                        necesita_correccion = True
                        cambios.append(
                            f"Estado 'en_progreso' → 'finalizado' "
                            f"(completamente pagado neto: Bs. {total_neto} de Bs. {proyecto.costo_total})"
                        )
                        if not dry_run:
                            proyecto.estado = 'finalizado'
                
                # Verificación 3: Proyecto sin pagos netos
                elif total_neto <= Decimal('0.01'):
                    # No tiene pagos netos, debería estar 'planificado' o 'en_progreso'
                    if proyecto.estado == 'finalizado':
                        necesita_correccion = True
                        cambios.append(
                            f"Estado 'finalizado' → 'en_progreso' "
                            f"(pagos netos insuficientes: Bs. {total_neto})"
                        )
                        if not dry_run:
                            proyecto.estado = 'en_progreso'
                
                # Mostrar si necesita corrección
                if necesita_correccion:
                    proyectos_corregidos += 1
                    
                    self.stdout.write(f"\n{'─'*100}")
                    self.stdout.write(
                        f"{'🔧 CORRIGIENDO' if not dry_run else '🔍 DETECTADO'} "
                        f"[{i}/{total_proyectos}]: Proyecto #{proyecto.id} - {proyecto.nombre}"
                    )
                    self.stdout.write(f"{'─'*100}")
                    self.stdout.write(f"  Paciente: {proyecto.paciente.nombre_completo}")
                    self.stdout.write(f"  Costo Total: Bs. {proyecto.costo_total:,.2f}")
                    self.stdout.write(f"  Total Pagado: Bs. {total_pagado:,.2f}")
                    
                    if total_devoluciones > 0:
                        self.stdout.write(self.style.WARNING(
                            f"  Total Devoluciones: Bs. {total_devoluciones:,.2f}"
                        ))
                        self.stdout.write(f"  Neto (Pagado - Devoluciones): Bs. {total_neto:,.2f}")
                    
                    self.stdout.write(f"  Saldo Pendiente: Bs. {saldo_pendiente:,.2f}")
                    
                    # Contar pagos y devoluciones
                    num_pagos = Pago.objects.filter(
                        proyecto=proyecto, anulado=False
                    ).count()
                    num_devs = Devolucion.objects.filter(proyecto=proyecto).count()
                    
                    self.stdout.write(
                        f"  Registros: {num_pagos} pago(s), {num_devs} devolución(es)"
                    )
                    
                    for cambio in cambios:
                        if dry_run:
                            self.stdout.write(self.style.WARNING(f"  📝 {cambio}"))
                        else:
                            self.stdout.write(self.style.SUCCESS(f"  ✅ {cambio}"))
                    
                    # Guardar cambios si no es dry-run
                    if not dry_run:
                        with transaction.atomic():
                            proyecto.save()
                            # Recalcular cuenta del paciente
                            AccountService.update_balance(proyecto.paciente)
                        
                        self.stdout.write(self.style.SUCCESS(
                            "  💾 Cambios guardados y cuenta recalculada"
                        ))
                
                # Mostrar progreso cada 10 proyectos
                elif i % 10 == 0:
                    self.stdout.write(f"  ⏳ Procesados {i}/{total_proyectos}...")
            
            except Exception as e:
                errores.append({
                    'proyecto_id': proyecto.id,
                    'proyecto_nombre': proyecto.nombre,
                    'error': str(e)
                })
                self.stdout.write(self.style.ERROR(
                    f"\n❌ Error en Proyecto #{proyecto.id}: {str(e)}"
                ))
        
        # Resumen final
        self.stdout.write("\n" + "="*100)
        self.stdout.write("📊 RESUMEN DE CORRECCIÓN")
        self.stdout.write("="*100)
        self.stdout.write(f"Total proyectos analizados: {total_proyectos}")
        
        if dry_run:
            self.stdout.write(self.style.WARNING(
                f"🔍 Proyectos que necesitan corrección: {proyectos_corregidos}"
            ))
            self.stdout.write(
                "\n💡 Para aplicar los cambios, ejecuta el comando sin --dry-run"
            )
        else:
            self.stdout.write(self.style.SUCCESS(
                f"✅ Proyectos corregidos: {proyectos_corregidos}"
            ))
        
        if errores:
            self.stdout.write(self.style.ERROR(
                f"\n❌ Errores encontrados: {len(errores)}"
            ))
            for error in errores[:5]:
                self.stdout.write(
                    f"  - Proyecto #{error['proyecto_id']} ({error['proyecto_nombre']}): "
                    f"{error['error']}"
                )
            if len(errores) > 5:
                self.stdout.write(f"  ... y {len(errores) - 5} errores más")
        else:
            self.stdout.write(self.style.SUCCESS("\n✅ Sin errores"))
        
        self.stdout.write("="*100 + "\n")
        
        # Instrucciones finales
        if not dry_run and proyectos_corregidos > 0:
            self.stdout.write("\n📋 PRÓXIMOS PASOS:")
            self.stdout.write("1. Verifica en la interfaz web que los proyectos ahora aparecen correctamente")
            self.stdout.write("2. Ejecuta: python manage.py validar_cuentas --solo-inconsistentes")
            self.stdout.write("3. Si hay inconsistencias, ejecuta: python manage.py forzar_recalculo")