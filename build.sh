(
echo #!/usr/bin/env bash
echo # Script de build para Render.com
echo set -o errexit
echo.
echo echo "Instalando dependencias..."
echo pip install -r requirements.txt
echo.
echo echo "Recolectando archivos estaticos..."
echo python manage.py collectstatic --no-input
echo.
echo echo "Ejecutando migraciones..."
echo python manage.py migrate
echo.
echo echo "Build completado!"
) > build.sh