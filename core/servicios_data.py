# core/servicios_data.py
"""
Contenido de las páginas públicas "Nuestros Servicios".

Cada entrada define una página SEO independiente (/nuestros-servicios/<slug>/)
para servicios que antes solo aparecían mencionados de paso en la landing
(fisioterapia, kinesiología, psicología infantojuvenil, psicopedagogía,
apoyo escolar, etc.) y que por eso no posicionaban en Google frente a
búsquedas específicas como "fisioterapia para niños Potosí" o
"kinesiología infantil Bolivia".

Para agregar un nuevo servicio, solo hay que añadir una entrada más a
SERVICIOS_PUBLICOS: la vista, la plantilla, el sitemap y los enlaces
"relacionados" se generan solos a partir de este diccionario.
"""

from collections import OrderedDict

SERVICIOS_PUBLICOS = OrderedDict([

    ("fisioterapia-kinesiologia-infantil-potosi", {
        "slug": "fisioterapia-kinesiologia-infantil-potosi",
        "icono": "🤸",
        "nombre": "Fisioterapia y Kinesiología Infantil",
        "nombre_corto": "Fisioterapia y Kinesiología",
        "color": "azul",

        "title_tag": "Fisioterapia y Kinesiología Infantil en Potosí | Centro Misael",
        "meta_description": (
            "Fisioterapia y kinesiología infantil en Potosí, Bolivia. Tratamos "
            "displasia de cadera, tortícolis congénita, retraso psicomotor y "
            "alteraciones del tono muscular en niños y niñas. Agenda tu evaluación."
        ),
        "h1": "Fisioterapia y Kinesiología Infantil en Potosí, Bolivia",

        "intro": (
            "En el Centro Misael, la fisioterapia y la kinesiología infantil "
            "acompañan el desarrollo motor de niños y niñas desde los primeros "
            "meses de vida hasta la adolescencia. En Bolivia, \"fisioterapia\" y "
            "\"kinesiología\" se usan como sinónimos, y nuestro equipo combina "
            "ambos enfoques para evaluar, tratar y hacer seguimiento de "
            "dificultades motoras congénitas o adquiridas, en coordinación con "
            "el pediatra u ortopedista de cada niño."
        ),

        "para_quien": (
            "Bebés, niños y adolescentes con dificultades de movimiento, "
            "coordinación o desarrollo motor, y familias que buscan un "
            "diagnóstico temprano en Potosí o que viajan desde otras ciudades "
            "de Bolivia para una evaluación especializada."
        ),

        "condiciones": [
            "Displasia de cadera (luxación congénita de cadera)",
            "Tortícolis congénita",
            "Retraso psicomotor",
            "Hipotonía e hipertonía muscular",
            "Pie plano y pie equino varo",
            "Plagiocefalia (cabeza aplanada del bebé)",
            "Parálisis cerebral infantil",
            "Recuperación motora post-quirúrgica o post-ortopédica",
        ],

        "como_es_sesion": (
            "Empezamos con una evaluación del desarrollo motor del niño o niña. "
            "A partir de ahí armamos un plan de ejercicio terapéutico "
            "individual, con técnicas de movilización, estiramiento y "
            "fortalecimiento adaptadas a su edad, y enseñamos a la familia "
            "ejercicios para reforzar en casa entre sesión y sesión."
        ),

        "faqs": [
            {
                "q": "¿Qué diferencia hay entre fisioterapia y kinesiología infantil?",
                "a": (
                    "En la práctica, ninguna: en Bolivia ambos términos se usan "
                    "para referirse a la rehabilitación física mediante ejercicio "
                    "terapéutico, movilizaciones y técnicas manuales. En el Centro "
                    "Misael nuestro equipo está formado en los dos enfoques."
                ),
            },
            {
                "q": "¿Atienden displasia de cadera en bebés?",
                "a": (
                    "Sí. Evaluamos y acompañamos el tratamiento de displasia de "
                    "cadera en bebés y niños pequeños en Potosí, trabajando junto "
                    "al pediatra o traumatólogo que sigue el caso."
                ),
            },
            {
                "q": "¿Desde qué edad puede empezar un niño fisioterapia?",
                "a": (
                    "Podemos evaluar desde los primeros meses de vida. Cuanto "
                    "antes se detecta una alteración motora, mejor suele ser la "
                    "respuesta al tratamiento."
                ),
            },
            {
                "q": "¿Cuántas sesiones se necesitan?",
                "a": (
                    "Depende de cada caso. Tras la evaluación inicial te damos "
                    "un plan orientativo de frecuencia y duración del tratamiento."
                ),
            },
        ],

        "relacionados": [
            "psicologia-infantojuvenil-potosi",
            "psicopedagogia-apoyo-escolar-potosi",
        ],
    }),

    ("psicologia-infantojuvenil-potosi", {
        "slug": "psicologia-infantojuvenil-potosi",
        "icono": "🧠",
        "nombre": "Psicología Infantojuvenil",
        "nombre_corto": "Psicología Infantojuvenil",
        "color": "morado",

        "title_tag": "Psicología Infantojuvenil en Potosí, Bolivia | Centro Misael",
        "meta_description": (
            "Psicología infantojuvenil en Potosí, Bolivia. Acompañamiento "
            "emocional, conductual y familiar para niños, niñas y "
            "adolescentes: ansiedad, conducta, autoestima y adaptación "
            "escolar. Agenda tu cita."
        ),
        "h1": "Psicología Infantojuvenil en Potosí, Bolivia",

        "intro": (
            "La psicología infantojuvenil del Centro Misael acompaña a niños, "
            "niñas y adolescentes en su desarrollo emocional y conductual, con "
            "sesiones adaptadas a cada edad y trabajo cercano con la familia. "
            "Atendemos tanto dificultades puntuales como acompañamiento a "
            "largo plazo dentro de procesos de neurodesarrollo (TEA, TDAH y "
            "otras condiciones)."
        ),

        "para_quien": (
            "Niños desde primera infancia y adolescentes hasta los 17-18 años, "
            "más orientación a padres y cuidadores, en Potosí y otras "
            "ciudades de Bolivia."
        ),

        "condiciones": [
            "Ansiedad infantil y juvenil",
            "Manejo de conducta y berrinches",
            "Autoestima y regulación emocional",
            "Duelo y cambios familiares (separación, mudanza, pérdidas)",
            "Acompañamiento emocional en TEA y TDAH",
            "Dificultades de adaptación escolar",
            "Habilidades sociales",
        ],

        "como_es_sesion": (
            "Iniciamos con una evaluación psicológica para entender qué está "
            "pasando y qué necesita el niño o adolescente. Las sesiones usan "
            "juego, dibujo o conversación según la edad, e incluyen "
            "orientación a los padres y, cuando hace falta, coordinación con "
            "el colegio."
        ),

        "faqs": [
            {
                "q": "¿A qué edad puede empezar terapia psicológica un niño?",
                "a": (
                    "Podemos atender desde la primera infancia; la forma de "
                    "trabajar (juego, dibujo, conversación) se adapta a la edad "
                    "de cada niño o niña."
                ),
            },
            {
                "q": "¿También trabajan con adolescentes?",
                "a": (
                    "Sí. \"Infantojuvenil\" incluye niños y adolescentes hasta "
                    "los 17-18 años, con un enfoque adaptado a cada etapa del "
                    "desarrollo."
                ),
            },
            {
                "q": "¿Los padres participan en el proceso?",
                "a": (
                    "En la mayoría de los casos sí: incluimos orientación a "
                    "padres o cuidadores como parte del tratamiento, no solo "
                    "sesiones con el niño."
                ),
            },
        ],

        "relacionados": [
            "psicopedagogia-apoyo-escolar-potosi",
            "fisioterapia-kinesiologia-infantil-potosi",
        ],
    }),

    ("psicopedagogia-apoyo-escolar-potosi", {
        "slug": "psicopedagogia-apoyo-escolar-potosi",
        "icono": "📚",
        "nombre": "Psicopedagogía y Apoyo Escolar",
        "nombre_corto": "Psicopedagogía y Apoyo Escolar",
        "color": "verde",

        "title_tag": "Psicopedagogía y Apoyo Escolar en Potosí | Centro Misael",
        "meta_description": (
            "Psicopedagogía y apoyo escolar en Potosí, Bolivia. Ayudamos a "
            "niños con dificultades de lectura, escritura y matemáticas, y "
            "con refuerzo académico personalizado. Agenda una evaluación."
        ),
        "h1": "Psicopedagogía y Apoyo Escolar para Niños en Potosí",

        "intro": (
            "Si tu hijo o hija está atrasado con la escuela, le cuesta leer, "
            "escribir o seguir el ritmo de sus compañeros, en el Centro "
            "Misael trabajamos la psicopedagogía y el apoyo escolar como dos "
            "caminos complementarios: entender el origen de la dificultad y, "
            "al mismo tiempo, reforzar el contenido del colegio."
        ),

        "para_quien": (
            "Niños y niñas en edad escolar de Potosí con dificultades de "
            "aprendizaje, bajo rendimiento académico o necesidad de refuerzo "
            "con las tareas y materias del colegio."
        ),

        "condiciones": [
            "Dificultades de lectura y escritura (dislexia, disgrafía)",
            "Dificultades en matemáticas (discalculia)",
            "Bajo rendimiento académico",
            "Dificultades de atención relacionadas al rendimiento escolar",
            "Hábitos y técnicas de estudio",
            "Adaptación escolar en niños con TEA o TDAH",
        ],

        "como_es_sesion": (
            "Partimos de una evaluación psicopedagógica para identificar el "
            "origen de la dificultad. Con eso armamos un plan de intervención "
            "individual, reforzamos lectoescritura o matemáticas según el "
            "caso, y coordinamos con el colegio del niño cuando la familia lo "
            "autoriza."
        ),

        "faqs": [
            {
                "q": "¿Qué diferencia hay entre psicopedagogía y apoyo escolar?",
                "a": (
                    "La psicopedagogía evalúa y trata la causa de una "
                    "dificultad de aprendizaje (por qué a un niño le cuesta "
                    "leer, escribir o calcular). El apoyo escolar es el "
                    "refuerzo académico del contenido del colegio. En el "
                    "Centro Misael ofrecemos ambos, muchas veces combinados."
                ),
            },
            {
                "q": "¿Mi hijo necesita apoyo escolar o psicopedagogía?",
                "a": (
                    "Lo definimos juntos con una evaluación inicial: si la "
                    "dificultad es puntual con una materia, suele bastar el "
                    "apoyo escolar; si hay una dificultad de base (por "
                    "ejemplo, dislexia), recomendamos psicopedagogía."
                ),
            },
            {
                "q": "¿Trabajan directamente con el colegio de mi hijo?",
                "a": (
                    "Cuando la familia lo autoriza, coordinamos con el "
                    "colegio o los profesores para alinear estrategias entre "
                    "la escuela y las sesiones."
                ),
            },
        ],

        "relacionados": [
            "psicologia-infantojuvenil-potosi",
            "fisioterapia-kinesiologia-infantil-potosi",
        ],
    }),

    ("terapia-lenguaje-fonoaudiologia-potosi", {
        "slug": "terapia-lenguaje-fonoaudiologia-potosi",
        "icono": "🗣️",
        "nombre": "Fonoaudiología y Terapia del Lenguaje Infantil",
        "nombre_corto": "Fonoaudiología",
        "color": "verde",

        "title_tag": "Fonoaudiología y Terapia del Lenguaje Infantil en Potosí",
        "meta_description": (
            "Fonoaudiología y terapia del lenguaje infantil en Potosí, Bolivia. "
            "Tratamos retraso del habla, tartamudez, dislalia y dificultades de "
            "deglución en niños y niñas. Agenda una evaluación."
        ),
        "h1": "Fonoaudiología y Terapia del Lenguaje Infantil en Potosí, Bolivia",

        "intro": (
            "La fonoaudiología del Centro Misael evalúa y trata la comunicación, "
            "el habla, el lenguaje y la deglución en niños y niñas de Potosí, "
            "desde los primeros años hasta la adolescencia, con un plan "
            "adaptado a cada dificultad."
        ),

        "para_quien": (
            "Niños y niñas que tardan en hablar, que no se les entiende bien, "
            "que tartamudean, o que tienen dificultades para comer o tragar de "
            "forma segura."
        ),

        "condiciones": [
            "Retraso del habla y del lenguaje",
            "Dislalia (dificultad para pronunciar ciertos sonidos)",
            "Tartamudez",
            "Dificultades de deglución (disfagia infantil)",
            "Comunicación y lenguaje en niños con TEA o TDAH",
            "Dificultades de comunicación no verbal",
        ],

        "como_es_sesion": (
            "Evaluamos cómo se comunica el niño o niña (comprensión, "
            "expresión, pronunciación, deglución) y armamos un plan de "
            "sesiones con juego y ejercicios específicos, con pautas claras "
            "para reforzar en casa."
        ),

        "faqs": [
            {
                "q": "¿A qué edad debería hablar mi hijo o hija?",
                "a": (
                    "Cada niño tiene su propio ritmo, pero si a los 2 años no "
                    "dice palabras sueltas o a los 3 no arma frases cortas, "
                    "conviene una evaluación para descartar un retraso del "
                    "lenguaje."
                ),
            },
            {
                "q": "¿Tratan la tartamudez en niños?",
                "a": (
                    "Sí, evaluamos y tratamos la tartamudez infantil con "
                    "técnicas específicas y acompañamiento a la familia sobre "
                    "cómo apoyar al niño en casa."
                ),
            },
            {
                "q": "¿Qué relación tiene la fonoaudiología con el autismo o el TDAH?",
                "a": (
                    "Muchos niños con TEA o TDAH tienen también dificultades "
                    "de comunicación o pragmática del lenguaje; la "
                    "fonoaudiología trabaja en conjunto con el resto del "
                    "equipo en esos casos."
                ),
            },
        ],

        "relacionados": [
            "terapia-ocupacional-infantil-potosi",
            "estimulacion-temprana-potosi",
        ],
    }),

    ("terapia-ocupacional-infantil-potosi", {
        "slug": "terapia-ocupacional-infantil-potosi",
        "icono": "✋",
        "nombre": "Terapia Ocupacional Infantil",
        "nombre_corto": "Terapia Ocupacional",
        "color": "verde",

        "title_tag": "Terapia Ocupacional Infantil en Potosí, Bolivia",
        "meta_description": (
            "Terapia ocupacional infantil en Potosí, Bolivia. Trabajamos "
            "motricidad fina, integración sensorial y autonomía en la vida "
            "diaria de niños y niñas. Agenda una evaluación."
        ),
        "h1": "Terapia Ocupacional Infantil en Potosí, Bolivia",

        "intro": (
            "La terapia ocupacional infantil ayuda a que cada niño y niña "
            "gane independencia en su día a día: comer solo, vestirse, "
            "escribir, jugar y participar en la escuela, trabajando la "
            "motricidad fina y el procesamiento sensorial."
        ),

        "para_quien": (
            "Niños y niñas con dificultades de motricidad fina, "
            "procesamiento sensorial, o que necesitan apoyo para ganar "
            "autonomía en tareas cotidianas."
        ),

        "condiciones": [
            "Dificultades de motricidad fina (agarre del lápiz, abrochar botones, usar cubiertos)",
            "Trastorno de procesamiento o integración sensorial",
            "Dificultades de autonomía en actividades diarias (vestirse, comer, higiene)",
            "Coordinación viso-manual",
            "Dispraxia (dificultad para planificar movimientos)",
        ],

        "como_es_sesion": (
            "Evaluamos motricidad fina, procesamiento sensorial y autonomía "
            "en actividades cotidianas, y trabajamos con juego terapéutico y "
            "actividades funcionales adaptadas a la edad e intereses del "
            "niño o niña."
        ),

        "faqs": [
            {
                "q": "¿Qué es la integración sensorial?",
                "a": (
                    "Es la forma en que el cerebro organiza la información "
                    "que recibe de los sentidos (tacto, movimiento, sonido, "
                    "etc.). Cuando ese procesamiento no funciona bien, el "
                    "niño puede sobre-reaccionar o sub-reaccionar a "
                    "estímulos cotidianos."
                ),
            },
            {
                "q": "¿A qué edad puede empezar terapia ocupacional?",
                "a": (
                    "Podemos evaluar desde la primera infancia; muchas veces "
                    "se trabaja en paralelo con estimulación temprana en los "
                    "más pequeños."
                ),
            },
        ],

        "relacionados": [
            "psicomotricidad-infantil-potosi",
            "terapia-lenguaje-fonoaudiologia-potosi",
        ],
    }),

    ("estimulacion-temprana-potosi", {
        "slug": "estimulacion-temprana-potosi",
        "icono": "🌱",
        "nombre": "Estimulación Temprana",
        "nombre_corto": "Estimulación Temprana",
        "color": "naranja",

        "title_tag": "Estimulación Temprana para Bebés en Potosí, Bolivia",
        "meta_description": (
            "Estimulación temprana para bebés y niños pequeños en Potosí, "
            "Bolivia. Apoyo en desarrollo motor, cognitivo y sensorial desde "
            "los primeros meses de vida. Agenda una evaluación."
        ),
        "h1": "Estimulación Temprana para Bebés en Potosí, Bolivia",

        "intro": (
            "La estimulación temprana acompaña el desarrollo de bebés y "
            "niños pequeños desde los primeros meses de vida, potenciando "
            "las áreas motora, cognitiva, sensorial y de lenguaje en la "
            "etapa donde el cerebro tiene mayor capacidad de cambio."
        ),

        "para_quien": (
            "Bebés y niños de 0 a 3 años, incluyendo quienes nacieron "
            "prematuros o con bajo peso, y familias que quieren un "
            "seguimiento cercano del desarrollo desde el inicio."
        ),

        "condiciones": [
            "Seguimiento de bebés prematuros o con bajo peso al nacer",
            "Retraso en hitos del desarrollo (sostener la cabeza, sentarse, caminar)",
            "Apoyo al desarrollo cognitivo, motor y sensorial temprano",
            "Prevención en bebés con factores de riesgo neurológico",
        ],

        "como_es_sesion": (
            "Evaluamos el desarrollo del bebé o niño pequeño y proponemos "
            "actividades de juego y estimulación sensoriomotriz adaptadas a "
            "su edad, enseñando a la familia cómo continuar la estimulación "
            "en casa."
        ),

        "faqs": [
            {
                "q": "¿Desde qué edad se puede empezar estimulación temprana?",
                "a": (
                    "Desde los primeros meses de vida. Cuanto antes se "
                    "acompaña el desarrollo, mejor se aprovecha la etapa de "
                    "mayor plasticidad del cerebro."
                ),
            },
            {
                "q": "¿Es solo para bebés con algún diagnóstico?",
                "a": (
                    "No. También acompañamos a familias que simplemente "
                    "quieren potenciar el desarrollo de su bebé o hacer un "
                    "seguimiento cercano, con o sin factores de riesgo."
                ),
            },
        ],

        "relacionados": [
            "fisioterapia-kinesiologia-infantil-potosi",
            "psicomotricidad-infantil-potosi",
        ],
    }),

    ("psicomotricidad-infantil-potosi", {
        "slug": "psicomotricidad-infantil-potosi",
        "icono": "🤸",
        "nombre": "Psicomotricidad Infantil",
        "nombre_corto": "Psicomotricidad",
        "color": "naranja",

        "title_tag": "Psicomotricidad Infantil en Potosí, Bolivia",
        "meta_description": (
            "Psicomotricidad infantil en Potosí, Bolivia. Trabajamos "
            "equilibrio, coordinación, esquema corporal y habilidades "
            "motrices globales en niños y niñas. Agenda una evaluación."
        ),
        "h1": "Psicomotricidad Infantil en Potosí, Bolivia",

        "intro": (
            "La psicomotricidad trabaja el cuerpo en movimiento: equilibrio, "
            "coordinación, esquema corporal y lateralidad, como base para "
            "que el niño o niña se desenvuelva con seguridad en el juego, el "
            "deporte y el aula."
        ),

        "para_quien": (
            "Niños y niñas con torpeza motora, dificultades de equilibrio o "
            "coordinación, o que tienen problemas para seguir el ritmo de "
            "juegos y actividades físicas de su edad."
        ),

        "condiciones": [
            "Dificultades de equilibrio y coordinación",
            "Alteraciones del esquema corporal y la lateralidad",
            "Torpeza motora (caídas frecuentes, choca con objetos)",
            "Dificultades en el juego motor y actividades deportivas",
        ],

        "como_es_sesion": (
            "A través de circuitos y juegos motores, trabajamos equilibrio, "
            "coordinación y esquema corporal, adaptando cada sesión al nivel "
            "y la edad del niño o niña."
        ),

        "faqs": [
            {
                "q": "¿En qué se diferencia de la fisioterapia?",
                "a": (
                    "La fisioterapia suele tratar una condición motora "
                    "específica (por ejemplo, displasia de cadera); la "
                    "psicomotricidad trabaja de forma más global el cuerpo, "
                    "el movimiento y su relación con el aprendizaje y el "
                    "juego."
                ),
            },
        ],

        "relacionados": [
            "terapia-ocupacional-infantil-potosi",
            "fisioterapia-kinesiologia-infantil-potosi",
        ],
    }),

    ("neuropsicologia-infantil-potosi", {
        "slug": "neuropsicologia-infantil-potosi",
        "icono": "🧠",
        "nombre": "Neuropsicología Infantil",
        "nombre_corto": "Neuropsicología",
        "color": "amarillo",

        "title_tag": "Neuropsicología Infantil en Potosí, Bolivia",
        "meta_description": (
            "Neuropsicología infantil en Potosí, Bolivia. Evaluación de "
            "atención, memoria y funciones ejecutivas en niños con TDAH o "
            "dificultades de aprendizaje. Agenda una evaluación."
        ),
        "h1": "Neuropsicología Infantil en Potosí, Bolivia",

        "intro": (
            "La neuropsicología infantil evalúa cómo funcionan la atención, "
            "la memoria y las funciones ejecutivas de un niño o niña, para "
            "entender el origen de dificultades de aprendizaje, conducta o "
            "atención y orientar el tratamiento."
        ),

        "para_quien": (
            "Niños y niñas con sospecha de TDAH, dificultades de aprendizaje "
            "de base neurológica, o que necesitan una evaluación cognitiva "
            "completa para orientar su tratamiento o su plan escolar."
        ),

        "condiciones": [
            "Dificultades de atención y memoria",
            "Funciones ejecutivas: planificación, organización, autorregulación",
            "Evaluación neuropsicológica en TDAH",
            "Dificultades de aprendizaje de base neurológica",
            "Secuelas cognitivas tras una lesión o enfermedad",
        ],

        "como_es_sesion": (
            "Aplicamos pruebas neuropsicológicas estandarizadas para medir "
            "atención, memoria y funciones ejecutivas, y entregamos un "
            "informe con recomendaciones claras para la familia y, si hace "
            "falta, para el colegio."
        ),

        "faqs": [
            {
                "q": "¿En qué se diferencia de una evaluación psicológica general?",
                "a": (
                    "La neuropsicológica se enfoca específicamente en "
                    "funciones cognitivas medibles (atención, memoria, "
                    "funciones ejecutivas) con pruebas estandarizadas, útil "
                    "sobre todo ante sospecha de TDAH o dificultades de "
                    "aprendizaje."
                ),
            },
            {
                "q": "¿Sirve el informe para presentarlo en el colegio?",
                "a": (
                    "Sí, el informe incluye recomendaciones prácticas que se "
                    "pueden compartir con el colegio para adaptar apoyos "
                    "dentro del aula."
                ),
            },
        ],

        "relacionados": [
            "psicologia-infantojuvenil-potosi",
            "psicopedagogia-apoyo-escolar-potosi",
        ],
    }),

    ("hidroterapia-infantil-potosi", {
        "slug": "hidroterapia-infantil-potosi",
        "icono": "💧",
        "nombre": "Hidroterapia Infantil",
        "nombre_corto": "Hidroterapia",
        "color": "azul",

        "title_tag": "Hidroterapia Infantil en Potosí, Bolivia",
        "meta_description": (
            "Hidroterapia infantil en Potosí, Bolivia. Terapia en agua para "
            "mejorar tono muscular, coordinación y regulación sensorial en "
            "niños y niñas, en un entorno seguro. Agenda una sesión."
        ),
        "h1": "Hidroterapia Infantil en Potosí, Bolivia",

        "intro": (
            "La hidroterapia usa las propiedades del agua (menor gravedad, "
            "resistencia suave, calidez) para trabajar tono muscular, "
            "coordinación y relajación en niños y niñas, en un entorno "
            "seguro y muy motivador para ellos."
        ),

        "para_quien": (
            "Niños y niñas con hipotonía o hipertonía muscular, "
            "dificultades de coordinación, hipersensibilidad sensorial, o "
            "que se benefician de un espacio calmante para trabajar "
            "regulación emocional."
        ),

        "condiciones": [
            "Hipotonía e hipertonía muscular",
            "Dificultades de coordinación motora",
            "Hipersensibilidad o hiposensibilidad sensorial",
            "Regulación emocional a través del juego en el agua",
            "Apoyo en rehabilitación motora post-lesión",
        ],

        "como_es_sesion": (
            "Las sesiones se hacen en una piscina climatizada y segura, con "
            "ejercicios y juego terapéutico en el agua adaptados al objetivo "
            "motor o sensorial de cada niño o niña."
        ),

        "faqs": [
            {
                "q": "¿Mi hijo necesita saber nadar para hacer hidroterapia?",
                "a": (
                    "No. La hidroterapia no es una clase de natación: el "
                    "terapeuta acompaña al niño dentro del agua en todo "
                    "momento con fines terapéuticos, no deportivos."
                ),
            },
            {
                "q": "¿Para qué edades es la hidroterapia?",
                "a": (
                    "Se puede adaptar a distintas edades, desde primera "
                    "infancia hasta adolescencia, según el objetivo "
                    "terapéutico."
                ),
            },
        ],

        "relacionados": [
            "fisioterapia-kinesiologia-infantil-potosi",
            "psicomotricidad-infantil-potosi",
        ],
    }),

    ("evaluacion-autismo-ados2-adir-potosi", {
        "slug": "evaluacion-autismo-ados2-adir-potosi",
        "icono": "📋",
        "nombre": "Evaluación de Autismo (ADOS-2 y ADI-R)",
        "nombre_corto": "Evaluación de Autismo",
        "color": "rojo",

        "title_tag": "Evaluación de Autismo ADOS-2 y ADI-R en Potosí",
        "meta_description": (
            "Evaluación diagnóstica de autismo (TEA) con ADOS-2 y ADI-R en "
            "Potosí, Bolivia. Protocolos gold standard internacional, con "
            "evaluación multidisciplinaria. Agenda una cita."
        ),
        "h1": "Evaluación de Autismo (ADOS-2 y ADI-R) en Potosí, Bolivia",

        "intro": (
            "Para un diagnóstico confiable de Trastorno del Espectro Autista "
            "(TEA), usamos ADOS-2 y ADI-R, los protocolos gold standard "
            "reconocidos internacionalmente, junto con una evaluación "
            "multidisciplinaria que da una mirada completa del niño o niña."
        ),

        "para_quien": (
            "Familias en Potosí u otras ciudades de Bolivia que buscan un "
            "diagnóstico claro ante señales de autismo en su hijo o hija, o "
            "que necesitan confirmar o descartar un diagnóstico previo."
        ),

        "condiciones": [
            "ADOS-2: observación estructurada del niño o niña en distintas actividades",
            "ADI-R: entrevista diagnóstica a los padres sobre historial de desarrollo",
            "Evaluación integral multidisciplinaria (médica, psicológica, del lenguaje)",
            "Informe diagnóstico con recomendaciones de tratamiento",
        ],

        "como_es_sesion": (
            "El proceso combina observación directa del niño o niña (ADOS-2), "
            "entrevista con los padres o cuidadores (ADI-R) y, según el caso, "
            "evaluaciones complementarias de otras áreas, para llegar a un "
            "diagnóstico y un plan de intervención claro."
        ),

        "faqs": [
            {
                "q": "¿Qué es el ADOS-2?",
                "a": (
                    "Es un protocolo de observación estructurada, considerado "
                    "gold standard internacional para la evaluación "
                    "diagnóstica del autismo."
                ),
            },
            {
                "q": "¿Qué es el ADI-R y en qué se diferencia del ADOS-2?",
                "a": (
                    "El ADI-R es una entrevista diagnóstica a los padres "
                    "sobre el historial de desarrollo del niño, mientras que "
                    "el ADOS-2 se basa en la observación directa. Suelen "
                    "usarse juntos para un diagnóstico más completo."
                ),
            },
            {
                "q": "¿Cuánto dura el proceso de evaluación?",
                "a": (
                    "Varía según el caso; en la primera cita te explicamos "
                    "los pasos y tiempos estimados del proceso diagnóstico."
                ),
            },
        ],

        "relacionados": [
            "neuropsicologia-infantil-potosi",
            "psicologia-infantojuvenil-potosi",
        ],
    }),

])
