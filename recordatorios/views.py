import subprocess
import platform
from django.shortcuts import render
from django.contrib.admin.views.decorators import staff_member_required

@staff_member_required
def logs_whatsapp(request):
    logs = []
    try:
        if platform.system() == 'Windows':
            # En Windows, mostrar mensaje de que solo funciona en producción
            logs = [{'texto': 'ℹ️ Los logs solo están disponibles en el servidor de producción.', 'tipo': 'info'}]
        else:
            resultado = subprocess.run(
                ['tail', '-n', '300', '/root/.pm2/logs/whatsapp-bot-out.log'],
                capture_output=True, text=True
            )
            for linea in reversed(resultado.stdout.strip().split('\n')):
                if 'Mensaje enviado' in linea or 'Error' in linea or 'conectado' in linea:
                    logs.append({
                        'texto': linea,
                        'tipo': 'success' if '✅' in linea else 'error' if '❌' in linea else 'info'
                    })
    except Exception as e:
        logs = [{'texto': f'Error al leer logs: {str(e)}', 'tipo': 'error'}]

    return render(request, 'recordatorios/logs_whatsapp.html', {'logs': logs})