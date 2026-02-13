# facturacion/management/commands/validar_cuentas.py

from django.core.management.base import BaseCommand
from django.db.models import Q
from facturacion.models import CuentaCorriente
from facturacion.services import AccountService
from pacientes.models import Paciente
from decimal import Decimal
from colorama import init, Fore, Style

init(autoreset=True)


class Command(BaseCommand):
    help = 'Valida la consistencia de todas las cuentas corrientes'

    def add_arguments(self, parser):
        parser.add_argument(
            '--recalcular',
            action='store_true',
            help='Recalcular todas las cuentas antes de validar',
        )
        parser.add_argument(
            '--paciente-id',
            type=int,
            help='Validar solo un paciente específico',
        )
        parser.add_argument(
            '--solo-inconsistentes',
            action='store_true',
            help='Mostrar solo las cuentas con inconsistencias',
        )

    def handle(self, *args, **options):
        recalcular = options['recalcular']
        paciente_id = options.get('paciente_id')
        solo_inconsistentes = options['solo_inconsistentes']
        
        # Filtrar pacientes
        if paciente_id:
            pacientes = Paciente.objects.filter(id=paciente_id)
            if not pacientes.exists():
                self.stdout.write(
                    self.style.ERROR(f'❌ Paciente con ID {paciente_id} no encontrado')
                )
                return
        else:
            pacientes = Paciente.objects.filter(estado='activo')
        
        total = pacientes.count()
        inconsistentes = 0
        consistentes = 0
        errores = []
        
        self.stdout.write("\n" + "="*80)
        self.stdout.write(
            f"{Fore.CYAN}🔍 VALIDANDO {total} CUENTAS CORRIENTES{Style.RESET_ALL}"
        )
        if recalcular:
            self.stdout.write(
                f"{Fore.YELLOW}⚠️  Recalculando todas las cuentas primero...{Style.RESET_ALL}"
            )
        self.stdout.write("="*80 + "\n")
        
        for i, paciente in enumerate(pacientes, 1):
            try:
                # Recalcular si se solicitó
                if recalcular:
                    AccountService.update_balance(paciente)
                
                # Obtener cuenta
                try:
                    cuenta = paciente.cuenta_corriente
                except CuentaCorriente.DoesNotExist:
                    cuenta = AccountService.update_balance(paciente)
                
                # Validar consistencia
                diferencia = abs(cuenta.saldo_actual - cuenta.pagos_adelantados)
                es_consistente = diferencia <= Decimal('0.01')
                
                if es_consistente:
                    consistentes += 1
                    if not solo_inconsistentes:
                        self.stdout.write(
                            f"{Fore.GREEN}✅ [{i}/{total}] {paciente.nombre_completo:40} "
                            f"Saldo: Bs.{cuenta.saldo_actual:8.2f} "
                            f"= Crédito: Bs.{cuenta.pagos_adelantados:8.2f}{Style.RESET_ALL}"
                        )
                else:
                    inconsistentes += 1
                    self.stdout.write(
                        f"\n{Fore.RED}❌ [{i}/{total}] {paciente.nombre_completo}{Style.RESET_ALL}"
                    )
                    self.stdout.write(
                        f"   {Fore.YELLOW}Saldo Actual:{Style.RESET_ALL} Bs.{cuenta.saldo_actual:10.2f}"
                    )
                    self.stdout.write(
                        f"   {Fore.YELLOW}Crédito Disp:{Style.RESET_ALL} Bs.{cuenta.pagos_adelantados:10.2f}"
                    )
                    self.stdout.write(
                        f"   {Fore.RED}Diferencia:{Style.RESET_ALL}   Bs.{diferencia:10.2f}\n"
                    )
                    
                    # Mostrar desglose
                    self.stdout.write(f"   {Fore.CYAN}Desglose de Crédito:{Style.RESET_ALL}")
                    self.stdout.write(
                        f"     • Sin asignar:         Bs.{cuenta.pagos_sin_asignar:10.2f}"
                    )
                    self.stdout.write(
                        f"     • Sesiones programadas: Bs.{cuenta.pagos_sesiones_programadas:10.2f}"
                    )
                    self.stdout.write(
                        f"     • Proyectos planificados: Bs.{cuenta.pagos_proyectos_planificados:10.2f}"
                    )
                    self.stdout.write(
                        f"     • Uso de crédito:     Bs.{cuenta.uso_credito:10.2f}"
                    )
                    
                    self.stdout.write(f"\n   {Fore.CYAN}Balance General:{Style.RESET_ALL}")
                    self.stdout.write(
                        f"     • Consumido Actual:   Bs.{cuenta.total_consumido_actual:10.2f}"
                    )
                    self.stdout.write(
                        f"     • Total Pagado:       Bs.{cuenta.total_pagado:10.2f}"
                    )
                    self.stdout.write("")
                    
                    errores.append({
                        'paciente': paciente.nombre_completo,
                        'saldo': cuenta.saldo_actual,
                        'credito': cuenta.pagos_adelantados,
                        'diferencia': diferencia
                    })
            
            except Exception as e:
                self.stdout.write(
                    f"{Fore.RED}❌ Error procesando {paciente.nombre_completo}: {str(e)}{Style.RESET_ALL}"
                )
                errores.append({
                    'paciente': paciente.nombre_completo,
                    'error': str(e)
                })
        
        # Resumen final
        self.stdout.write("\n" + "="*80)
        self.stdout.write(f"{Fore.CYAN}📊 RESUMEN DE VALIDACIÓN{Style.RESET_ALL}")
        self.stdout.write("="*80)
        self.stdout.write(f"Total de cuentas validadas: {total}")
        self.stdout.write(
            f"{Fore.GREEN}✅ Consistentes: {consistentes}{Style.RESET_ALL}"
        )
        
        if inconsistentes > 0:
            self.stdout.write(
                f"{Fore.RED}❌ Inconsistentes: {inconsistentes}{Style.RESET_ALL}"
            )
            self.stdout.write(
                f"\n{Fore.YELLOW}⚠️  Se encontraron {inconsistentes} cuentas con inconsistencias.{Style.RESET_ALL}"
            )
            if not recalcular:
                self.stdout.write(
                    f"{Fore.CYAN}💡 Ejecuta con --recalcular para intentar corregirlas{Style.RESET_ALL}"
                )
        else:
            self.stdout.write(
                f"\n{Fore.GREEN}🎉 ¡Todas las cuentas son consistentes!{Style.RESET_ALL}"
            )
        
        self.stdout.write("="*80 + "\n")