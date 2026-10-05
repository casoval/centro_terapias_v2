#!/usr/bin/env bash
# Regenera static/css/tailwind.css. Ejecutar desde la raíz del proyecto cada vez
# que agregues clases de Tailwind nuevas a templates o JS.
# Requiere Node.js. Uso:  bash tools/build_tailwind.sh
set -euo pipefail
cd "$(dirname "$0")/.."
npx --yes tailwindcss@3.4.17 -c tailwind.config.js -i tools/tailwind-input.css -o static/css/tailwind.css --minify
mkdir -p staticfiles_collected/css
cp static/css/tailwind.css staticfiles_collected/css/tailwind.css
echo "OK: static/css/tailwind.css generado"
