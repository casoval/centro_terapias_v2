// Configuración para generar static/css/tailwind.css (ver OPTIMIZACIONES_RENDIMIENTO.md).
// Reemplaza al <script src="https://cdn.tailwindcss.com"> que compila CSS en el navegador.
module.exports = {
  content: [
    './templates/**/*.html',
    './*/templates/**/*.html',
    './*/*.py',
    './static/**/*.js',
  ],
  theme: { extend: {} },
  plugins: [],
}
