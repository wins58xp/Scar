# Cambios

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
