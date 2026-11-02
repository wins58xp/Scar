# Cambios

## Sin publicar

Nada todavía.

## 0.1.1

Arreglos y velocidad; el lenguaje no cambia: todo programa que corría en 0.1.0
corre igual.

- **Arreglo:** `scar check` aceptaba tipos que no existen (`Vec<NoExiste>`,
  `Option<Optoin<i32>>`): el intérprete los corría y `scar build` recién fallaba
  al generar C. Ahora es un error de tipo, que sugiere el nombre parecido
  (`¿quisiste decir 'Option'?`).
- **Rendimiento: canales mucho más rápidos.** Una tarea que espera un mensaje
  (o lugar en un canal lleno) prueba unos microsegundos si llega antes de
  dormirse, porque dormir y despertar un hilo cuesta mucho más; mientras
  espera mira un aviso del canal, sin tomar su candado, para no estorbar al
  que manda. Un canal de números, textos o listas además reusa los nodos de
  su cola en vez de pedir memoria por cada mensaje. Medido en un procesador
  de 12 núcleos, contra 0.1.0 y en la misma sesión:

  | prueba | 0.1.0 | 0.1.1 |
  |---|---|---|
  | ida y vuelta entre dos tareas | 8.1 µs | 0.26 µs (31 veces más rápido) |
  | flujo por un canal acotado | 6.8 M msj/s | 11.6 M msj/s (+71 %) |
  | flujo por un canal sin límite | 7.0 M msj/s | 8.9 M msj/s (+28 %) |
  | varias tareas mandando a una | 0.60 M msj/s | 0.86 M msj/s (+43 %) |
  | un grupo de trabajadores | 0.57 M msj/s | 0.74 M msj/s (+29 %) |
  | anillo de tareas | 4.8 µs por salto | igual |
  | mensajes con texto (structs) | 2.69 M msj/s | 2.61 M msj/s (−3 %) |

  El −3 % es el precio de esperar despierto: cuando el que manda es el lento,
  las dos tareas están en núcleos distintos y nadie espera respuesta, el
  receptor se lleva cada mensaje apenas llega en vez de juntar varios. En el
  mismo núcleo esa prueba sale 70 % más rápida. El giro se adapta solo en cada
  canal, no gira si hay más tareas que núcleos, y se ajusta o apaga con la
  variable de entorno `SCAR_GIRO` (máximo en microsegundos; `0` lo apaga y
  vuelve casi a la conducta de 0.1.0).
- **Pruebas:** `./pruebas/correr.sh` también revisa 44 programas que rompen
  una regla del lenguaje (mover dos veces, compartir memoria entre tareas,
  tipos que no existen...): `scar check` tiene que rechazarlos, con el mensaje
  correcto.

## 0.1.0 — alfa

Primera versión pública.

- El lenguaje: tipos `i32`, `i64`, `f64`, `bool`, `str`; `struct`, `enum` y
  `match`; `Option`, `Result` y el operador `?`; `Vec`, `Map` y literales
  `[a, b, c]`; `if` como expresión, `while`, `for`, `break`, `continue`;
  genéricos (`struct<T>`, `fn<T>`) y funciones como valor; módulos con `use`.
- Tareas y regiones: `task`, `spawn`, `join`, canales `Chan<T>`, cancelación y
  panics en cascada, detección de deadlocks; una tarea es dueña de su memoria y
  la libera al terminar, sin recolector de basura.
- Dos maneras de correr, con la misma salida: `scar run` (intérprete) y
  `scar build` (compila a C y a un binario nativo).
- Interoperar con C (`extern`) y exportar una librería que se llama desde C o
  Python (`scar build --lib`).
- Herramientas: `scar fmt`, `scar check` y un servidor LSP para editores.
- La librería estándar (`lib/`): 35 librerías, entre ellas texto, colecciones,
  JSON, CSV, fechas, matemática y álgebra, señales, gráficos, interfaces
  gráficas (`gui`, con SDL2), web y HTTPS, derivadas automáticas (`autodiff`) y
  redes neuronales.
- El libro de SCAR (`libro/`), con 17 capítulos y un programa por capítulo en
  `ejemplos/`.

Qué incluye y qué no, en detalle: `SCAR_0.1.0.md`.
