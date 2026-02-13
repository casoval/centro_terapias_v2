# facturacion/management/commands/recalcular_cuentas.py

from django.core.management.base import BaseCommand
from facturacion.models import CuentaCorriente
from facturacion.services import AccountService
from pacientes.models import Paciente


class Command(BaseCommand):
    help = 'Recalcula todas las cuentas corrientes o una cuenta específica'

    def add_arguments(self, parser):
        parser.add_argument(
            '--paciente-id',
            type=int,
            help='ID de paciente específico (opcional)',
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Recalcular todas las cuentas',
        )

    def handle(self, *args, **options):
        if options['paciente_id']:
            # Recalcular solo un paciente
            try:
                paciente = Paciente.objects.get(id=options['paciente_id'])
                self.stdout.write(f'🔄 Recalculando cuenta de {paciente}...')
                
                cuenta = AccountService.update_balance(paciente)
                
                self.stdout.write(
                    self.style.SUCCESS(
                        f'✅ Cuenta actualizada:\n'
                        f'  - Consumido Real: Bs. {cuenta.total_consumido_real}\n'
                        f'  - Consumido Actual: Bs. {cuenta.total_consumido_actual}\n'
                        f'  - Total Pagado: Bs. {cuenta.total_pagado}\n'
                        f'  - Saldo Real: Bs. {cuenta.saldo_real}\n'
                        f'  - Saldo Actual: Bs. {cuenta.saldo_actual}'
                    )
                )
            except Paciente.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f'❌ Paciente con ID {options["paciente_id"]} no existe')
                )
        
        elif options['all']:
            # Recalcular todas
            self.stdout.write('🔄 Recalculando TODAS las cuentas corrientes...')
            self.stdout.write(self.style.WARNING('⚠️  Esto puede tardar varios minutos'))
            
            resultado = AccountService.recalcular_todas_las_cuentas()
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'\n✅ Recálculo completado:\n'
                    f'  - Total: {resultado["total"]} cuentas\n'
                    f'  - Exitosos: {resultado["exitosos"]}\n'
                    f'  - Errores: {len(resultado["errores"])}'
                )
            )
            
            if resultado['errores']:
                self.stdout.write(self.style.ERROR('\n❌ Errores encontrados:'))
                for error in resultado['errores'][:10]:  # Mostrar solo primeros 10
                    self.stdout.write(
                        f'  - Paciente {error["paciente_id"]} ({error["paciente_nombre"]}): '
                        f'{error["error"]}'
                    )
                
                if len(resultado['errores']) > 10:
                    self.stdout.write(
                        f'  ... y {len(resultado["errores"]) - 10} errores más'
                    )
        
        else:
            self.stdout.write(
                self.style.ERROR(
                    '❌ Debes especificar --paciente-id <ID> o --all'
                )
            )
            self.stdout.write('\nEjemplos de uso:')
            self.stdout.write('  python manage.py recalcular_cuentas --paciente-id 5')
            self.stdout.write('  python manage.py recalcular_cuentas --all')