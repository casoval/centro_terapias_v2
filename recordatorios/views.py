import time
import logging
import subprocess
import platform
import requests

from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════
# WHATSAPP
# ══════════════════════════════════════════════════════

@login_required
def logs_whatsapp(request):
    logs = []
    try:
        if platform.system() == 'Windows':
            logs = [{'texto': 'ℹ️ Los logs solo están disponibles en el servidor de producción.', 'tipo': 'info'}]
        else:
            resultado = subprocess.run(
                ['tail', '-n', '300', '/var/log/whatsapp-bot/out.log'],
                capture_output=True, text=True
            )
            for linea in reversed(resultado.stdout.strip().split('\n')):
                if linea.strip() and any(x in linea for x in ['✅', '❌', '🚀', '📱']):
                    logs.append({
                        'texto': linea.strip(),
                        'tipo': 'success' if '✅' in linea else 'error' if '❌' in linea else 'info'
                    })
    except Exception as e:
        logs = [{'texto': f'Error al leer logs: {str(e)}', 'tipo': 'error'}]

    return render(request, 'recordatorios/logs_whatsapp.html', {'logs': logs})


@login_required
def whatsapp_status(request):
    bot = request.GET.get('bot', 'japon')
    puerto = 3000 if bot == 'japon' else 3001
    try:
        res = requests.get(f'http://localhost:{puerto}/status', timeout=5)
        return JsonResponse(res.json())
    except Exception:
        return JsonResponse({'status': 'desconectado'})


@login_required
def whatsapp_qr(request):
    bot = request.GET.get('bot', 'japon')
    puerto = 3000 if bot == 'japon' else 3001
    try:
        res = requests.get(f'http://localhost:{puerto}/qr', timeout=5)
        return JsonResponse(res.json())
    except Exception:
        return JsonResponse({'qr': None, 'status': 'desconectado'})


@csrf_exempt
@login_required
def whatsapp_reconectar(request):
    if request.method == 'POST':
        import json as json_lib
        data = json_lib.loads(request.body)
        bot = data.get('bot', 'japon')
        subprocess.Popen(['pm2', 'restart', f'whatsapp-bot{"-camacho" if bot == "camacho" else ""}'])
        return JsonResponse({'ok': True})
    return JsonResponse({'ok': False})


# Archivos de pausa — uno por bot, persisten en disco entre sesiones
_PAUSA_FILES = {
    'japon':   '/var/log/whatsapp-bot/pausa-japon.flag',
    'camacho': '/var/log/whatsapp-bot/pausa-camacho.flag',
}


@csrf_exempt
@login_required
def whatsapp_pausa(request):
    """
    GET  ?bot=japon|camacho  → devuelve {bot, pausado: true|false}
    POST {bot, pausar: true|false} → activa o desactiva la pausa y notifica al bot Node.js
    """
    import json as json_lib
    from pathlib import Path

    if request.method == 'GET':
        bot = request.GET.get('bot', 'japon')
        flag = _PAUSA_FILES.get(bot)
        pausado = flag is not None and Path(flag).exists()
        return JsonResponse({'bot': bot, 'pausado': pausado})

    if request.method == 'POST':
        data = json_lib.loads(request.body)
        bot    = data.get('bot', 'japon')
        pausar = bool(data.get('pausar', True))
        flag   = _PAUSA_FILES.get(bot)

        if not flag:
            return JsonResponse({'ok': False, 'error': 'Bot desconocido'}, status=400)

        flag_path = Path(flag)

        try:
            if pausar:
                # Crear el archivo de bandera con timestamp y usuario
                flag_path.parent.mkdir(parents=True, exist_ok=True)
                flag_path.write_text(
                    f"pausado_por={request.user.username}\n"
                    f"fecha={timezone.localtime().strftime('%Y-%m-%d %H:%M:%S')}\n"
                )
            else:
                flag_path.unlink(missing_ok=True)
        except Exception as e:
            log.error(f"Error al {'crear' if pausar else 'eliminar'} flag de pausa para {bot}: {e}")
            return JsonResponse({'ok': False, 'error': str(e)}, status=500)

        # Notificar al bot Node.js vía su endpoint /pausa (si está disponible)
        puerto = 3000 if bot == 'japon' else 3001
        try:
            requests.post(
                f'http://localhost:{puerto}/pausa',
                json={'pausado': pausar},
                timeout=3,
            )
        except Exception:
            # El bot puede estar desconectado; el archivo flag es suficiente para cuando se reconecte
            pass

        accion = 'pausado' if pausar else 'reanudado'
        log.info(f"Bot {bot} {accion} por {request.user.username}")
        return JsonResponse({'ok': True, 'bot': bot, 'pausado': pausar})


@login_required
def whatsapp_historial(request):
    import json
    historial_japon = []
    historial_camacho = []
    try:
        with open('/var/log/whatsapp-bot/historial-japon.json', 'r') as f:
            historial_japon = json.load(f)
    except Exception:
        pass
    try:
        with open('/var/log/whatsapp-bot/historial-camacho.json', 'r') as f:
            historial_camacho = json.load(f)
    except Exception:
        pass
    historial = historial_japon + historial_camacho
    historial.sort(key=lambda x: x.get('fecha', ''), reverse=True)
    historial = historial[:200]

    # ── Enriquecer con nombres desde la BD ──────────────────
    # Recopilar todos los teléfonos únicos del historial
    telefonos_raw = {item.get('telefono', '') for item in historial if item.get('telefono')}

    # Normalizar: generar variantes con y sin prefijo 591
    telefonos_buscar = set()
    for t in telefonos_raw:
        telefonos_buscar.add(t)
        if t.startswith('591') and len(t) > 3:
            telefonos_buscar.add(t[3:])   # sin prefijo
        elif len(t) == 8:
            telefonos_buscar.add(f'591{t}')  # con prefijo

    # Una sola consulta batch a la BD
    try:
        from pacientes.models import Paciente
        pacientes_qs = Paciente.objects.filter(
            telefono_tutor__in=telefonos_buscar
        ).values('telefono_tutor', 'nombre', 'apellido', 'nombre_tutor')
        # También buscar por teléfono secundario
        pacientes_qs2 = Paciente.objects.filter(
            telefono_tutor_2__in=telefonos_buscar
        ).values('telefono_tutor_2', 'nombre', 'apellido', 'nombre_tutor')

        # Construir lookup: telefono → {nombre_paciente, nombre_tutor}
        lookup = {}
        for p in pacientes_qs:
            datos = {
                'nombre_paciente_db': f"{p['nombre']} {p['apellido']}".strip(),
                'nombre_tutor_db': p['nombre_tutor'] or '',
            }
            lookup[p['telefono_tutor']] = datos
            # También indexar con/sin 591 para facilitar match
            t = p['telefono_tutor']
            if t.startswith('591'):
                lookup[t[3:]] = datos
            else:
                lookup[f'591{t}'] = datos
        for p in pacientes_qs2:
            datos = {
                'nombre_paciente_db': f"{p['nombre']} {p['apellido']}".strip(),
                'nombre_tutor_db': p['nombre_tutor'] or '',
            }
            lookup[p['telefono_tutor_2']] = datos
            t = p['telefono_tutor_2']
            if t.startswith('591'):
                lookup[t[3:]] = datos
            else:
                lookup[f'591{t}'] = datos
    except Exception:
        lookup = {}

    # Agregar nombres a cada item del historial
    for item in historial:
        tel = item.get('telefono', '')
        info = lookup.get(tel) or lookup.get(tel[3:] if tel.startswith('591') else f'591{tel}')
        if info:
            item['nombre_paciente_db'] = info['nombre_paciente_db']
            item['nombre_tutor_db']    = info['nombre_tutor_db']

    return JsonResponse(historial, safe=False)


def get_sucursal_principal(paciente):
    """Determina la sucursal principal del paciente según cantidad de sesiones."""
    from agenda.models import Sesion
    from django.db.models import Count

    resultado = Sesion.objects.filter(
        paciente=paciente
    ).values('sucursal_id', 'sucursal__nombre').annotate(
        total=Count('id')
    ).order_by('-total').first()

    if resultado:
        return resultado['sucursal_id'], resultado['sucursal__nombre']

    primera = paciente.sucursales.first()
    if primera:
        return primera.id, primera.nombre

    return 3, 'Suc. Japon'


@csrf_exempt
@login_required
def whatsapp_envio_masivo(request):
    if request.method != 'POST':
        return JsonResponse({'ok': False})

    import json as json_lib
    data = json_lib.loads(request.body)
    mensaje = data.get('mensaje', '').strip()
    sucursal_filtro = data.get('sucursal', 'todas')
    destinatarios = data.get('destinatarios', 'semana')

    if destinatarios not in ('deudores', 'mensualidades_semana') and not mensaje:
        return JsonResponse({'error': 'Mensaje vacío'}, status=400)

    from agenda.models import Sesion
    from pacientes.models import Paciente
    from django.utils import timezone
    from datetime import timedelta

    tutores = {}

    if destinatarios == 'semana':
        hoy = timezone.localdate()
        lunes = hoy - timedelta(days=hoy.weekday())
        domingo = lunes + timedelta(days=6)
        sesiones = Sesion.objects.filter(
            fecha__range=[lunes, domingo],
            estado='programada',
        ).select_related('paciente', 'sucursal')
        for sesion in sesiones:
            paciente = sesion.paciente
            telefono = paciente.telefono_tutor
            sucursal_id = sesion.sucursal.id
            if not telefono:
                continue
            if sucursal_filtro == 'japon' and sucursal_id != 3:
                continue
            if sucursal_filtro == 'camacho' and sucursal_id != 4:
                continue
            if telefono not in tutores:
                tutores[telefono] = {
                    'telefono': telefono,
                    'tutor_nombre': paciente.nombre_tutor,
                    'paciente_nombre': paciente.nombre_completo,
                    'sucursal_id': sucursal_id,
                    'sucursal': sesion.sucursal.nombre,
                    'mensaje': mensaje,
                }

    elif destinatarios == 'hoy':
        hoy = timezone.localdate()
        sesiones = Sesion.objects.filter(
            fecha=hoy,
            estado='programada',
        ).select_related('paciente', 'sucursal')
        for sesion in sesiones:
            paciente = sesion.paciente
            telefono = paciente.telefono_tutor
            sucursal_id = sesion.sucursal.id
            if not telefono:
                continue
            if sucursal_filtro == 'japon' and sucursal_id != 3:
                continue
            if sucursal_filtro == 'camacho' and sucursal_id != 4:
                continue
            if telefono not in tutores:
                tutores[telefono] = {
                    'telefono': telefono,
                    'tutor_nombre': paciente.nombre_tutor,
                    'paciente_nombre': paciente.nombre_completo,
                    'sucursal_id': sucursal_id,
                    'sucursal': sesion.sucursal.nombre,
                    'mensaje': mensaje,
                }

    elif destinatarios == 'manana':
        manana = timezone.localdate() + timedelta(days=1)
        sesiones = Sesion.objects.filter(
            fecha=manana,
            estado='programada',
        ).select_related('paciente', 'sucursal')
        for sesion in sesiones:
            paciente = sesion.paciente
            telefono = paciente.telefono_tutor
            sucursal_id = sesion.sucursal.id
            if not telefono:
                continue
            if sucursal_filtro == 'japon' and sucursal_id != 3:
                continue
            if sucursal_filtro == 'camacho' and sucursal_id != 4:
                continue
            if telefono not in tutores:
                tutores[telefono] = {
                    'telefono': telefono,
                    'tutor_nombre': paciente.nombre_tutor,
                    'paciente_nombre': paciente.nombre_completo,
                    'sucursal_id': sucursal_id,
                    'sucursal': sesion.sucursal.nombre,
                    'mensaje': mensaje,
                }

    elif destinatarios == 'todos':
        pacientes = Paciente.objects.filter(estado='activo')
        if sucursal_filtro == 'japon':
            pacientes = pacientes.filter(sucursales__id=3)
        elif sucursal_filtro == 'camacho':
            pacientes = pacientes.filter(sucursales__id=4)
        for paciente in pacientes:
            telefono = paciente.telefono_tutor
            if not telefono:
                continue
            sucursal_id, sucursal_nombre = get_sucursal_principal(paciente)
            if sucursal_filtro == 'japon':
                sucursal_id, sucursal_nombre = 3, 'Suc. Japon'
            elif sucursal_filtro == 'camacho':
                sucursal_id, sucursal_nombre = 4, 'Suc. Camacho'
            if telefono not in tutores:
                tutores[telefono] = {
                    'telefono': telefono,
                    'tutor_nombre': paciente.nombre_tutor,
                    'paciente_nombre': paciente.nombre_completo,
                    'sucursal_id': sucursal_id,
                    'sucursal': sucursal_nombre,
                    'mensaje': mensaje,
                }

    elif destinatarios == 'todos_incluido_inactivos':
        pacientes = Paciente.objects.all()
        if sucursal_filtro == 'japon':
            pacientes = pacientes.filter(sucursales__id=3)
        elif sucursal_filtro == 'camacho':
            pacientes = pacientes.filter(sucursales__id=4)
        for paciente in pacientes:
            telefono = paciente.telefono_tutor
            if not telefono:
                continue
            sucursal_id, sucursal_nombre = get_sucursal_principal(paciente)
            if sucursal_filtro == 'japon':
                sucursal_id, sucursal_nombre = 3, 'Suc. Japon'
            elif sucursal_filtro == 'camacho':
                sucursal_id, sucursal_nombre = 4, 'Suc. Camacho'
            if telefono not in tutores:
                tutores[telefono] = {
                    'telefono': telefono,
                    'tutor_nombre': paciente.nombre_tutor,
                    'paciente_nombre': paciente.nombre_completo,
                    'sucursal_id': sucursal_id,
                    'sucursal': sucursal_nombre,
                    'mensaje': mensaje,
                }

    elif destinatarios == 'mensualidades_semana':
        from agenda.models import Sesion as SesionLocal
        DIAS_LOCAL  = ['Lunes','Martes','Miércoles','Jueves','Viernes','Sábado','Domingo']
        MESES_LOCAL = ['enero','febrero','marzo','abril','mayo','junio','julio','agosto',
                       'septiembre','octubre','noviembre','diciembre']

        hoy     = timezone.localdate()
        lunes   = hoy + timedelta(days=(7 - hoy.weekday()))  # próximo lunes
        domingo = lunes + timedelta(days=6)

        sesiones_mens = SesionLocal.objects.filter(
            fecha__range=[lunes, domingo],
            estado='programada',
            mensualidad__isnull=False,
        ).select_related('paciente', 'profesional', 'servicio', 'sucursal', 'mensualidad'
        ).order_by('fecha', 'hora_inicio')

        if sucursal_filtro == 'japon':
            sesiones_mens = sesiones_mens.filter(sucursal_id=3)
        elif sucursal_filtro == 'camacho':
            sesiones_mens = sesiones_mens.filter(sucursal_id=4)

        grupos = {}
        for sesion in sesiones_mens:
            paciente = sesion.paciente
            telefono = paciente.telefono_tutor
            if not telefono:
                continue
            sucursal_id, sucursal_nombre = get_sucursal_principal(paciente)
            if telefono not in grupos:
                grupos[telefono] = {
                    'telefono':        telefono,
                    'tutor_nombre':    paciente.nombre_tutor,
                    'paciente_nombre': paciente.nombre_tutor,
                    'sucursal_id':     sucursal_id,
                    'sucursal':        sesion.sucursal.nombre,
                    'sesiones':        [],
                }
            grupos[telefono]['sesiones'].append({
                'paciente_nombre': paciente.nombre_completo,
                'dia':             DIAS_LOCAL[sesion.fecha.weekday()],
                'fecha':           f"{sesion.fecha.day} de {MESES_LOCAL[sesion.fecha.month - 1]}",
                'hora_inicio':     sesion.hora_inicio.strftime('%H:%M'),
                'servicio':        sesion.servicio.nombre,
            })

        for telefono, tutor in grupos.items():
            # Agrupar sesiones por paciente
            pacientes_dict = {}
            for s in tutor['sesiones']:
                nombre = s['paciente_nombre']
                if nombre not in pacientes_dict:
                    pacientes_dict[nombre] = []
                pacientes_dict[nombre].append(s)

            bloques = []
            for nombre_paciente, sesiones_paciente in pacientes_dict.items():
                lineas_paciente = "\n".join([
                    f"  • {s['dia']} {s['fecha']}: {s['servicio']} a las {s['hora_inicio']}"
                    for s in sesiones_paciente
                ])
                bloques.append(f"*{nombre_paciente}:*\n{lineas_paciente}")

            cuerpo = "\n\n".join(bloques)
            tutor['mensaje'] = (
                f"👋 Hola! Le recordamos los horarios de la próxima semana en {tutor['sucursal']}:\n\n"
                f"{cuerpo}\n\n¡Hasta pronto! 😊 neuromisael.com"
            )
            tutores[telefono] = tutor

    elif destinatarios == 'deudores':
        from facturacion.models import CuentaCorriente

        cuentas = CuentaCorriente.objects.filter(
            paciente__estado='activo',
            saldo_real__lt=-1,
        ).select_related('paciente').prefetch_related('paciente__sucursales')

        deudores_agrupados = {}
        for cuenta in cuentas:
            paciente = cuenta.paciente
            telefono = paciente.telefono_tutor
            if not telefono:
                continue

            sucursal_id, sucursal_nombre = get_sucursal_principal(paciente)

            if sucursal_filtro == 'japon' and sucursal_id != 3:
                continue
            if sucursal_filtro == 'camacho' and sucursal_id != 4:
                continue

            deuda = abs(cuenta.saldo_real)

            if telefono not in deudores_agrupados:
                deudores_agrupados[telefono] = {
                    'tutor_nombre': paciente.nombre_tutor,
                    'tutor_telefono': telefono,
                    'sucursal': sucursal_nombre,
                    'sucursal_id': sucursal_id,
                    'pacientes': []
                }
            deudores_agrupados[telefono]['pacientes'].append({
                'nombre': paciente.nombre_completo,
                'deuda': deuda,
            })

        for telefono, tutor in deudores_agrupados.items():
            pacientes_deuda = tutor['pacientes']
            sucursal = tutor['sucursal']
            nombre_tutor = tutor['tutor_nombre'] or 'estimado tutor/a'

            if len(pacientes_deuda) == 1:
                p = pacientes_deuda[0]
                detalle = f"*{p['nombre']}* presenta un saldo pendiente de *Bs. {int(p['deuda'])}*"
            else:
                lineas = "\n".join([f"• {p['nombre']}: Bs. {int(p['deuda'])}" for p in pacientes_deuda])
                detalle = f"los siguientes pacientes presentan saldo pendiente:\n{lineas}"

            mensaje_tutor = (
                f"👋 Hola, *{nombre_tutor}*! Esperamos que se encuentre muy bien. 😊\n\n"
                f"Le contactamos desde *{sucursal}* para informarle cordialmente que {detalle}.\n\n"
                f"💡 Para revisar el detalle de pagos, sesiones y deudas de forma rápida y sencilla, puede ingresar a su cuenta en nuestra página web: *neuromisael.com*\n\n"
                f"Si tiene alguna consulta que la página web no pueda resolver, le invitamos a apersonarse directamente a nuestras oficinas, donde nuestro equipo le atenderá con mucho gusto. 🙏\n\n"
                f"¡Gracias por su confianza y comprensión!"
            )

            tutores[telefono] = {
                'telefono': telefono,
                'tutor_nombre': tutor['tutor_nombre'],
                'paciente_nombre': tutor['tutor_nombre'],
                'sucursal_id': tutor['sucursal_id'],
                'sucursal': sucursal,
                'mensaje': mensaje_tutor,
            }

    import requests as req_lib
    enviados = 0
    errores = 0
    for tutor in tutores.values():
        puerto = 3000 if tutor['sucursal_id'] == 3 else 3001
        try:
            req_lib.post(
                f'http://localhost:{puerto}/send',
                json={
                    'telefono': tutor['telefono'],
                    'mensaje': tutor['mensaje'],
                    'paciente': tutor['paciente_nombre'],
                    'sucursal': tutor['sucursal'],
                    'delay_type': 'largo' if destinatarios == 'deudores' else 'corto',
                    'tipo': 'recordatorio',
                },
                timeout=5
            )
            enviados += 1
            # ── Guardar en historial del panel de conversaciones ──────────
            try:
                from agente.models import ConversacionAgente
                tel = tutor['telefono']
                tel_completo = f'591{tel}' if not tel.startswith('591') else tel
                # Mapear el tipo de destinatario a una etiqueta descriptiva
                tipo_label_map = {
                    'deudores':                'recordatorio-deuda',
                    'semana':                  'recordatorio-semana',
                    'hoy':                     'recordatorio-cita',
                    'manana':                  'recordatorio-cita',
                    'todos':                   'recordatorio-masivo',
                    'todos_incluido_inactivos': 'recordatorio-masivo',
                    'mensualidades_semana':    'recordatorio-mensualidades',
                }
                tipo_label = tipo_label_map.get(destinatarios, f'recordatorio-{destinatarios}')
                ConversacionAgente.objects.create(
                    agente       = 'paciente',
                    telefono     = tel_completo,
                    rol          = 'assistant',
                    contenido    = tutor['mensaje'],
                    modelo_usado = tipo_label,
                )
            except Exception:
                pass
        except Exception:
            errores += 1

    return JsonResponse({'ok': True, 'enviados': enviados, 'errores': errores})


# ══════════════════════════════════════════════════════
# BACKUP
# ══════════════════════════════════════════════════════

@login_required
def backup_monitor(request):
    """Vista principal del monitor de respaldos."""
    from recordatorios.models import RegistroBackup
    from django.core.paginator import Paginator

    exitosos = RegistroBackup.objects.filter(exitoso=True).count()
    fallidos = RegistroBackup.objects.filter(exitoso=False).count()
    ultimo   = RegistroBackup.objects.first()

    stats = {
        'total':          RegistroBackup.objects.count(),
        'exitosos':       exitosos,
        'fallidos':       fallidos,
        'ultimo_fecha':   ultimo.fecha.strftime('%d/%m/%Y %H:%M') if ultimo else None,
        'ultimo_tipo':    ultimo.get_tipo_display() if ultimo else None,
        'ultimo_tamanio': ultimo.tamanio_mb if ultimo else None,
    }

    paginator = Paginator(RegistroBackup.objects.all(), 50)
    page_number = request.GET.get('page', 1)
    backups = paginator.get_page(page_number)

    return render(request, 'recordatorios/backup_monitor.html', {
        'backups': backups,
        'stats':   stats,
    })


@login_required
def backup_ejecutar(request):
    """Lanza un backup manual y registra el resultado."""
    if request.method != 'POST':
        return redirect('recordatorios:backup_monitor')

    from recordatorios.models import RegistroBackup
    import sys
    import os
    from pathlib import Path
    from dotenv import load_dotenv
    load_dotenv()

    script  = Path(__file__).resolve().parent.parent / 'backup_db.py'
    inicio  = time.time()
    registro = RegistroBackup(tipo='manual')

    try:
        resultado = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True, timeout=300
        )
        duracion = round(time.time() - inicio, 1)

        if resultado.returncode == 0:
            tamanio = ''
            for linea in resultado.stdout.splitlines():
                if 'Tamaño:' in linea:
                    tamanio = linea.split('Tamaño:')[-1].strip()
                    break
            registro.exitoso           = True
            registro.tamanio_mb        = tamanio
            registro.duracion_segundos = duracion
            registro.destinatarios     = os.environ.get('BACKUP_EMAIL_DESTINO', '')
            registro.save()
            messages.success(request, f'✅ Respaldo completado en {duracion}s y enviado por correo.')
            log.info(f"Backup manual exitoso. Duración: {duracion}s")
        else:
            registro.exitoso       = False
            registro.mensaje_error = resultado.stderr[:500]
            registro.save()
            messages.error(request, '❌ Error al generar el respaldo. Revisa los logs.')
            log.error(f"Backup manual fallido: {resultado.stderr[:300]}")

    except subprocess.TimeoutExpired:
        registro.exitoso       = False
        registro.mensaje_error = 'Timeout: el proceso tardó más de 5 minutos.'
        registro.save()
        messages.error(request, '❌ El respaldo tardó demasiado y fue cancelado.')

    except Exception as e:
        registro.exitoso       = False
        registro.mensaje_error = str(e)
        registro.save()
        messages.error(request, f'❌ Error inesperado: {e}')
        log.exception("Error en backup manual")

    return redirect('recordatorios:backup_monitor')