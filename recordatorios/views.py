import subprocess
import platform
import requests
from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required


@staff_member_required
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
                if linea.strip():
                    logs.append({
                        'texto': linea.strip(),
                        'tipo': 'success' if '✅' in linea else 'error' if '❌' in linea else 'info'
                    })
    except Exception as e:
        logs = [{'texto': f'Error al leer logs: {str(e)}', 'tipo': 'error'}]

    return render(request, 'recordatorios/logs_whatsapp.html', {'logs': logs})


@login_required
def whatsapp_status(request):
    try:
        res = requests.get('http://localhost:3000/status', timeout=5)
        return JsonResponse(res.json())
    except Exception:
        return JsonResponse({'status': 'desconectado'})


@login_required
def whatsapp_qr(request):
    try:
        res = requests.get('http://localhost:3000/qr', timeout=5)
        return JsonResponse(res.json())
    except Exception:
        return JsonResponse({'qr': None, 'status': 'desconectado'})


@login_required
def whatsapp_reconectar(request):
    if request.method == 'POST':
        subprocess.Popen(['pm2', 'restart', 'whatsapp-bot'])
        return JsonResponse({'ok': True})
    return JsonResponse({'ok': False})