# facturacion/management/commands/forzar_recalculo.py

"""
Comando para forzar el recálculo inmediato de todas las cuentas corrientes

Uso:
    python manage.py forzar_recalculo                    # Todas las cuentas
    python manage.py forzar_recalculo --paciente-id 5    # Solo un paciente
    python manage.py forzar_recalculo --verbose          # Con detalles
"""

from django.core.management.base import BaseCommand
from facturacion.services import AccountService
from pacientes.models import Paciente
from decimal import Decimal


class Command(BaseCommand):
    help = 'Forzar recálculo inmediato de cuentas corrientes (útil después de eliminar datos)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--paciente-id',
            type=int,
            help='ID de paciente específico (opcional)',
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Mostrar detalles de cada cuenta',
        )

    def handle(self, *args, **options):
        paciente_id = options.get('paciente_id')
        verbose = options.get('verbose', False)
        
        if paciente_id:
            # Recalcular solo un paciente
            try:
                paciente = Paciente.objects.get(id=paciente_id)
                self.stdout.write(f'\n🔄 Recalculando cuenta de {paciente}...')
                
                cuenta = AccountService.update_balance(paciente)
                
                self.stdout.write(
                    self.style.SUCCESS(
                        f'\n✅ Cuenta actualizada:\n'
                        f'  📊 ESTADO ACTUAL:\n'
                        f'    - Total Consumido: Bs. {cuenta.total_consumido_actual:,.2f}\n'
                        f'    - Total Pagado: Bs. {cuenta.total_pagado:,.2f}\n'
                        f'    - Saldo Actual: Bs. {cuenta.saldo_actual:,.2f}\n'
                        f'\n  🔮 PROYECCIÓN:\n'
                        f'    - Total Proyectado: Bs. {cuenta.total_consumido_real:,.2f}\n'
                        f'    - Saldo Proyectado: Bs. {cuenta.saldo_real:,.2f}\n'
                        f'\n  💰 CRÉDITO:\n'
                        f'    - Crédito Disponible: Bs. {cuenta.pagos_adelantados:,.2f}\n'
                    )
                )
            except Paciente.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f'❌ Paciente con ID {paciente_id} no existe')
                )
                return
        
        else:
            # Recalcular todas las cuentas
            pacientes = Paciente.objects.filter(estado='activo')
            total = pacientes.count()
            
            self.stdout.write('\n' + '='*80)
            self.stdout.write(f'🔄 FORZANDO RECÁLCULO DE {total} CUENTAS CORRIENTES')
            self.stdout.write('='*80 + '\n')
            
            exitosos = 0
            errores = 0
            
            for i, paciente in enumerate(pacientes, 1):
                try:
                    cuenta = AccountService.update_balance(paciente)
                    exitosos += 1
                    
                    if verbose:
                        self.stdout.write(
                            f'✅ [{i}/{total}] {paciente.nombre_completo:40} '
                            f'Consumido: {cuenta.total_consumido_actual:8.2f} | '
                            f'Pagado: {cuenta.total_pagado:8.2f} | '
                            f'Saldo: {cuenta.saldo_actual:8.2f}'
                        )
                    elif i % 10 == 0:
                        self.stdout.write(f'   Procesados: {i}/{total}...')
                
                except Exception as e:
                    errores += 1
                    self.stdout.write(
                        self.style.ERROR(
                            f'❌ Error en {paciente.nombre_completo}: {str(e)}'
                        )
                    )
            
            # Resumen final
            self.stdout.write('\n' + '='*80)
            self.stdout.write('📊 RESUMEN DEL RECÁLCULO')
            self.stdout.write('='*80)
            self.stdout.write(f'Total de cuentas: {total}')
            self.stdout.write(self.style.SUCCESS(f'✅ Exitosos: {exitosos}'))
            
            if errores > 0:
                self.stdout.write(self.style.ERROR(f'❌ Errores: {errores}'))
            else:
                self.stdout.write(self.style.SUCCESS('\n🎉 ¡Todas las cuentas recalculadas correctamente!'))
            
            self.stdout.write('='*80 + '\n')