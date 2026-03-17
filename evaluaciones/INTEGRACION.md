# 📦 App `evaluaciones` — Guía de integración

## 1. Copiar la carpeta

Copia la carpeta `evaluaciones/` en la raíz de tu proyecto
(al mismo nivel que `pacientes/`, `agenda/`, etc.)

## 2. Registrar en settings.py

En `INSTALLED_APPS`, agrega:

```python
'evaluaciones.apps.EvaluacionesConfig',
```

## 3. Registrar las URLs en config/urls.py

```python
from django.urls import path, include

urlpatterns = [
    # ... tus urls actuales ...
    path('evaluaciones/', include('evaluaciones.urls', namespace='evaluaciones')),
]
```

## 4. Instalar dependencias

```bash
pip install weasyprint
```

WeasyPrint requiere también algunas librerías del sistema:

### Ubuntu/Debian:
```bash
sudo apt-get install libpango-1.0-0 libpangoft2-1.0-0 libpangocairo-1.0-0 \
     libgdk-pixbuf2.0-0 libffi-dev shared-mime-info
```

### macOS (Homebrew):
```bash
brew install pango
```

## 5. Instalar HTMX en tu base.html

Agrega antes del cierre de `</body>`:

```html
<script src="https://unpkg.com/htmx.org@1.9.10"></script>
```

O con CDN de jsdelivr:
```html
<script src="https://cdn.jsdelivr.net/npm/htmx.org@1.9.10/dist/htmx.min.js"></script>
```

## 6. Crear migraciones

```bash
python manage.py makemigrations evaluaciones
python manage.py migrate
```

## 7. Verificar el modelo Paciente

La app `evaluaciones` referencia a `pacientes.Paciente`.
Asegúrate que tu modelo tenga al menos:
- `nombre` (o campo equivalente para búsqueda)
- `fecha_nacimiento` (para calcular edad en el informe)
- `get_genero_display` (para el informe PDF)

Si el campo se llama diferente, ajusta en:
- `models.py` → ForeignKey `'pacientes.Paciente'`
- `views.py` → búsqueda `Paciente.objects.filter(nombre__icontains=q)`
- `templates/evaluaciones/reports/pdf_template.html` → `{{ paciente.fecha_nacimiento }}`

## 8. Acceder a la app

```
/evaluaciones/                  → Dashboard
/evaluaciones/ados2/            → Lista ADOS-2
/evaluaciones/ados2/nueva/      → Nueva evaluación ADOS-2
/evaluaciones/adir/             → Lista ADI-R
/evaluaciones/adir/nueva/       → Nueva evaluación ADI-R
/evaluaciones/informes/         → Lista de informes
/evaluaciones/informes/nuevo/   → Crear informe
/evaluaciones/informes/<pk>/pdf/ → Descargar PDF
```

## Estructura de archivos generados

```
evaluaciones/
├── __init__.py
├── apps.py
├── models.py          ← Modelos ADOS-2, ADI-R, InformeEvaluacion
├── forms.py           ← Formularios por sección/módulo
├── views.py           ← Vistas con soporte HTMX
├── urls.py            ← Rutas
├── admin.py           ← Panel admin completo
├── migrations/
│   └── __init__.py
├── templates/
│   └── evaluaciones/
│       ├── dashboard.html
│       ├── ados2/
│       │   ├── lista.html        (pendiente crear)
│       │   ├── crear.html        (pendiente crear)
│       │   ├── items.html        ✅
│       │   ├── detalle.html      (pendiente crear)
│       │   └── partials/
│       │       └── puntuaciones.html  ✅
│       ├── adir/
│       │   └── partials/
│       │       └── algoritmo.html     ✅
│       └── reports/
│           ├── lista.html        (pendiente crear)
│           ├── crear.html        (pendiente crear)
│           ├── detalle.html      (pendiente crear)
│           └── pdf_template.html ✅
└── static/
    └── evaluaciones/
        └── css/
            └── pdf.css           (opcional, para WeasyPrint)
```

## Pendientes opcionales

- [ ] Templates lista/crear/detalle para ADOS-2, ADI-R e Informes
- [ ] Filtros por paciente, evaluador y fecha en los listados
- [ ] Exportar listado en Excel (openpyxl)
- [ ] Permisos por evaluador (cada uno ve solo sus evaluaciones)
- [ ] Logger de cambios en evaluaciones
