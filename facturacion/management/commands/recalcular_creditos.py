from django.core.management.base import BaseCommand
from django.db.models import Sum
from facturacion.models import CuentaCorriente, Pago
from pacientes.models import Paciente
from decimal import Decimal

class Command(BaseCommand):
    help = 'Recalcular créditos de todos los pacientes'

    def add_arguments(self, parser):
        parser.add_argument(
            '--verificar',
            action='store_true',
            help='Solo verificar sin actualizar',
        )
        parser.add_argument(
            '--paciente',
            type=int,
            help='ID de un paciente específico',
        )

    def handle(self, *args, **options):
        solo_verificar = options['verificar']
        paciente_id = options.get('paciente')
        
        # Filtrar pacientes
        if paciente_id:
            pacientes = Paciente.objects.filter(id=paciente_id)
            if not pacientes.exists():
                self.stdout.write(self.style.ERROR(f'❌ Paciente con ID {paciente_id} no encontrado'))
                return
        else:
            pacientes = Paciente.objects.filter(estado='activo')
        
        total = pacientes.count()
        inconsistentes = 0
        actualizados = 0
        
        self.stdout.write(f"\n{'🔍 VERIFICANDO' if solo_verificar else '🔄 RECALCULANDO'} {total} pacientes...\n")
        self.stdout.write("="*80 + "\n")
        
        for paciente in pacientes:
            cuenta, _ = CuentaCorriente.objects.get_or_create(paciente=paciente)
            
            # ✅ CORREGIDO: Calcular manualmente con nombre correcto
            # 🔧 FIX adicional: uso_credito solo cuenta lo que sigue ligado a
            # una sesión/proyecto/mensualidad real (ver nota en
            # AccountService.update_balance).
            pagos_adelantados = Pago.objects.filter(
                paciente=paciente,
                anulado=False,
                sesion__isnull=True,
                proyecto__isnull=True
            ).exclude(
                metodo_pago__nombre="Uso de Crédito"  # ✅ Nombre correcto
            ).aggregate(Sum('monto'))['monto__sum'] or Decimal('0.00')
            
            uso_credito = Pago.objects.filter(
                paciente=paciente,
                anulado=False,
                metodo_pago__nombre="Uso de Crédito"  # ✅ Nombre correcto
            ).exclude(
                sesion__isnull=True, proyecto__isnull=True, mensualidad__isnull=True,
                detalles_masivos__isnull=True
            ).aggregate(Sum('monto'))['monto__sum'] or Decimal('0.00')
            
            credito_calculado = pagos_adelantados - uso_credito
            
            if solo_verificar:
                if abs(cuenta.saldo - credito_calculado) > Decimal('0.01'):
                    inconsistentes += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"⚠️  {paciente.nombre_completo}:\n"
                            f"   En BD: Bs.{cuenta.saldo} | "
                            f"Calculado: Bs.{credito_calculado}\n"
                            f"   Diferencia: Bs.{cuenta.saldo - credito_calculado}\n"
                        )
                    )
            else:
                saldo_anterior = cuenta.saldo
                cuenta.actualizar_saldo()
                
                if abs(saldo_anterior - cuenta.saldo) > Decimal('0.01'):
                    actualizados += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"✅ {paciente.nombre_completo}: "
                            f"Bs.{saldo_anterior} → Bs.{cuenta.saldo}"
                        )
                    )
        
        self.stdout.write("\n" + "="*80)
        
        if solo_verificar:
            if inconsistentes == 0:
                self.stdout.write(self.style.SUCCESS(f"\n✅ Todo correcto - 0 inconsistencias\n"))
            else:
                self.stdout.write(self.style.WARNING(f"\n⚠️  {inconsistentes} inconsistencias encontradas\n"))
                self.stdout.write("Ejecuta sin --verificar para corregir\n")
        else:
            if actualizados == 0:
                self.stdout.write(self.style.SUCCESS(f"\n✅ Todas las cuentas ya estaban correctas\n"))
            else:
                self.stdout.write(self.style.SUCCESS(f"\n✅ {actualizados} de {total} cuentas actualizadas correctamente\n"))