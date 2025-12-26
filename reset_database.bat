@echo off
chcp 65001 >nul
echo ================================================
echo    REINICIAR BASE DE DATOS DESDE CERO
echo ================================================
echo.
echo ⚠️  ADVERTENCIA: Esto borrará TODOS los datos
echo.
pause

echo.
echo [1/6] Borrando base de datos antigua...
if exist db.sqlite3 (
    del db.sqlite3
    echo ✅ db.sqlite3 eliminado
) else (
    echo ℹ️  No existe db.sqlite3
)
echo.

echo [2/6] Borrando migraciones antiguas...
if exist agenda\migrations\0*.py (
    del /Q agenda\migrations\0*.py
    echo ✅ Migraciones de agenda eliminadas
)
if exist facturacion\migrations\0*.py (
    del /Q facturacion\migrations\0*.py
    echo ✅ Migraciones de facturacion eliminadas
)
if exist pacientes\migrations\0*.py (
    del /Q pacientes\migrations\0*.py
    echo ✅ Migraciones de pacientes eliminadas
)
if exist servicios\migrations\0*.py (
    del /Q servicios\migrations\0*.py
    echo ✅ Migraciones de servicios eliminadas
)
if exist profesionales\migrations\0*.py (
    del /Q profesionales\migrations\0*.py
    echo ✅ Migraciones de profesionales eliminadas
)
echo.

echo [3/6] Creando migraciones nuevas...
python manage.py makemigrations
echo.

echo [4/6] Aplicando migraciones (creando tablas)...
python manage.py migrate
echo.

echo [5/6] Creando superusuario...
echo.
echo 👤 Ingresa los datos del administrador:
python manage.py createsuperuser
echo.

echo [6/6] Creando métodos de pago...
python manage.py shell -c "from facturacion.models import MetodoPago; MetodoPago.objects.create(nombre='Efectivo', activo=True); MetodoPago.objects.create(nombre='Transferencia', activo=True); MetodoPago.objects.create(nombre='Tarjeta', activo=True); MetodoPago.objects.create(nombre='QR', activo=True); print('✅ 4 métodos de pago creados')"
echo.

echo ================================================
echo ✅ BASE DE DATOS REINICIADA EXITOSAMENTE
echo ================================================
echo.
echo 📋 Próximos pasos:
echo 1. Iniciar servidor: python manage.py runserver
echo 2. Ir a: http://127.0.0.1:8000/admin/
echo 3. Login con el usuario que acabas de crear
echo.
pause