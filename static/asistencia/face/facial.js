/**
 * Reconocimiento facial en el navegador (face-api.js, servido desde /static).
 * Convierte un rostro en un descriptor de 128 números. El servidor compara
 * descriptores (distancia euclidiana); la imagen NO se usa para identificar.
 *
 *   await FaceAsistencia.cargarModelos(urlModelos);
 *   const r = await FaceAsistencia.leer(videoOCanvas);
 *   if (r.ok) enviar(r.descriptor)   // Array de 128 floats
 *   else mostrar(r.motivo)
 */
window.FaceAsistencia = (function () {
  let promesaModelos = null;

  function cargarModelos(urlBase) {
    if (!window.faceapi) return Promise.reject(new Error('face-api.js no se cargó'));
    if (!promesaModelos) {
      promesaModelos = (async () => {
        await faceapi.tf.ready();
        await Promise.all([
          faceapi.nets.tinyFaceDetector.loadFromUri(urlBase),
          faceapi.nets.faceLandmark68Net.loadFromUri(urlBase),
          faceapi.nets.faceRecognitionNet.loadFromUri(urlBase),
        ]);
      })().catch(err => { promesaModelos = null; throw err; });
    }
    return promesaModelos;
  }

  async function leer(entrada) {
    const opciones = new faceapi.TinyFaceDetectorOptions({ inputSize: 416, scoreThreshold: 0.5 });
    const rostros = await faceapi.detectAllFaces(entrada, opciones).withFaceLandmarks().withFaceDescriptors();
    if (rostros.length === 0) return { ok: false, motivo: 'No se detecta ningún rostro. Mira a la cámara con buena luz.' };
    if (rostros.length > 1) return { ok: false, motivo: 'Se detectan varios rostros. Debes estar solo frente a la cámara.' };
    const r = rostros[0];
    const ancho = entrada.videoWidth || entrada.width || 1;
    if (r.detection.box.width / ancho < 0.22) return { ok: false, motivo: 'Acércate un poco más a la cámara.' };
    return { ok: true, descriptor: Array.from(r.descriptor), confianza: r.detection.score };
  }

  return { cargarModelos, leer };
})();
