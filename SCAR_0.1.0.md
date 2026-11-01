# SCAR 0.1.0 (alfa): qué trae y qué no

Es la primera versión pública. El lenguaje funciona y está probado: cada
programa de prueba se corre con el intérprete y compilado, y tiene que dar
exactamente la misma salida; la versión compilada se revisa además con
AddressSanitizer, UndefinedBehaviorSanitizer, LeakSanitizer y ThreadSanitizer.
Pero es un alfa: la sintaxis y la librería todavía pueden cambiar.

## Qué incluye

| Qué | Dónde se explica |
|---|---|
| Tipos `i32`, `i64`, `f64`, `bool`, `str`; `let` y `let mut` | [capítulo 2](libro/02_valores.md) |
| `if` (también como expresión), `while`, `for`, `break`, `continue` | [capítulo 3](libro/03_decidir_y_repetir.md) |
| Funciones y `struct` | [capítulo 4](libro/04_funciones_y_structs.md) |
| `enum` y `match`; `Option`, `Result`, el operador `?` y `panic` | [capítulo 5](libro/05_enums_y_errores.md) |
| `Vec<T>`, `Map<K,V>` y literales `[a, b, c]` | [capítulo 6](libro/06_vec_y_map.md) |
| Texto en UTF-8 (`len` cuenta caracteres, no bytes) | [capítulo 7](libro/07_texto.md) |
| Propiedad: cada valor tiene un dueño, sin recolector y sin liberar a mano | [capítulo 8](libro/08_propiedad.md) |
| Tareas y regiones: `task`, `spawn`, `join`, `Chan<T>`, cancelación, panics en cascada, detección de deadlocks | [capítulo 9](libro/09_tareas.md) |
| Módulos (`use`) y la librería estándar (35 librerías) | [capítulo 10](libro/10_modulos.md), [apéndice B](libro/B_libreria_estandar.md) |
| Archivos, TCP, HTTP y HTTPS | [capítulo 11](libro/11_archivos_y_red.md) |
| Compilar a binario nativo (vía C) | [capítulo 12](libro/12_compilar.md) |
| Genéricos (`struct<T>`, `fn<T>`, el bound `Numeric`) y funciones como valor | [capítulo 13](libro/13_genericos.md) |
| Llamar a C (`extern`) y ser llamado desde C o Python (`scar build --lib`) | [capítulo 14](libro/14_hablar_con_c.md) |
| Interfaces gráficas (`gui`, sobre SDL2) | [capítulo 15](libro/15_interfaces.md) |
| `scar fmt`, `scar check`, `scar lsp` (para editores) y la librería `prueba` | [capítulo 16](libro/16_herramientas.md) |
| IA nativa: derivadas automáticas (`autodiff`), regiones cognitivas, `inject_chan`, redes neuronales | [capítulo 17](libro/17_ia_nativa.md) |

## Límites conocidos

- **Una lista de tareas lleva el nombre de la tarea en su tipo.** El handle de
  `spawn t(...)` es de tipo `Task<i32, t>`, así que una lista de ellos se
  declara `let v: Vec<Task<i32, t>> = vec_new()`; un `Vec<Task<i32>>` a secas no
  acepta handles.
- **`join()` sin avance.** Si un `join()` espera y ninguna tarea avanza durante 8
  segundos, termina en panic (deadlock). Una tarea que sigue trabajando no lo
  dispara. Se ajusta con `SCAR_JOIN_TIMEOUT` o `--join-timeout`.
- **Solo `str` se indexa con `[...]`.** Un `Vec` se lee con `get(i)`, que da un
  `Option`.
- **Bounds de tipo:** el único es `Numeric` (`i32`, `i64`, `f64`); no se pueden
  definir bounds propios.
- **Structs genéricos en el compilador:** algunos tipos de campo dentro de un
  struct genérico todavía no compilan a binario (el intérprete los corre); el
  mensaje lo dice.
- **Sin `;`:** cada sentencia va en su propia línea. Un `;` es un error que lo
  explica, a propósito: el `;` queda libre para el futuro.
- **Un `panic` no se atrapa:** termina la tarea (y en cascada a sus hijas). Los
  errores que se esperan van en `Result`.

## Idioma

Las palabras clave y las funciones incorporadas están en inglés (`fn`, `task`,
`while`, `print`, `len`…). Los mensajes del compilador, el libro, la librería
estándar y los ejemplos están en español.

## Plataforma

- **Probado:** Linux x86_64, con Python 3.12 o más nuevo y gcc o clang.
- **No probado:** macOS y Windows. No quiere decir que no funcione, solo que
  todavía nadie lo comprobó.

## Opcional

- **SDL2:** para las interfaces gráficas (`gui`, `pantalla`, `parlante`). Sin
  SDL2, todo lo demás funciona; un programa que lo usa dice qué instalar.
- **libcurl:** para HTTPS (`https`). HTTP sin cifrar (`web`) no la necesita.
- **numpy, scipy y matplotlib:** solo para algunas pruebas de la librería
  estándar, que se saltan con un aviso si faltan.

`./instalar.sh` dice qué tienes y qué falta, y compila lo que se pueda con lo
que hay.
