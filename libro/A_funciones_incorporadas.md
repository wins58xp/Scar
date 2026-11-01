# Apéndice A. Funciones incorporadas

Estas son las funciones que el lenguaje trae sin declarar nada: 38, las mismas
en el intérprete y en el binario. Los métodos (de `Vec`, `Map`, `str`, `Chan`,
`File`…) no están acá: se describen en el capítulo de cada tipo.

**Los nombres están reservados.** Ninguno de estos 38 nombres puede usarse para
algo que se pueda llamar: una `fn`, una `task`, una `extern fn`, o un parámetro o
variable de tipo `fn`. El compilador lo rechaza:

```scar-error
fn len(x: i32) -> i32 {
    return x
}

fn main() {
    print(len(3))
}
```

```
ERROR DE TIPO: 'len' es una función builtin: una fn no puede llamarse así (elige otro nombre) (línea 1)
```

Una variable común con uno de estos nombres sí está permitida (`let len = 3`),
porque no se puede llamar: `len` es la variable y `len(...)` es la función.

Fuera de estos nombres, cualquiera sirve, también uno que en C ya es otra cosa:
una variable `printf`, un struct `FILE` con un campo `int`. El compilador nunca
escribe tus nombres tal cual en el C que genera, así que no chocan con nada de C.

`print(...)` no está en la lista porque no es una función: es una palabra del
lenguaje, que acepta cualquier cantidad de valores de cualquier tipo.

## A.1 Números

| Función | Qué hace |
|---|---|
| `sqrt(x: f64) -> f64` | raíz cuadrada; de un negativo da `nan` |
| `sin`, `cos`, `tan`, `atan` `(x: f64) -> f64` | trigonometría, en radianes |
| `exp(x: f64) -> f64` | e elevado a x; si no entra, `inf` |
| `ln(x: f64) -> f64` | logaritmo natural; `ln(0.0)` es `-inf`, de un negativo `nan` |
| `log10(x: f64) -> f64` | logaritmo en base 10 (mismas reglas que `ln`) |
| `pow(x: f64, y: f64) -> f64` | x elevado a y |
| `floor(x: f64) -> f64` | redondea hacia abajo: `floor(-2.5)` es `-3.0` |
| `abs(x) -> el tipo de x` | valor absoluto; de un entero es exacto, y el del entero más chico (que no tiene positivo) es un panic |
| `min(a, b)`, `max(a, b)` | el menor / mayor; el tipo sigue la regla de una suma (`i32` con `i64` da `i64`); con NaN devuelven el primero |
| `to_i32(x) -> i32` | de un `f64`, trunca hacia cero (`3.99` → 3, `-3.99` → -3); de un `i64`, lo deja igual; `nan` o un valor que no entra en `i32` es un panic |
| `to_i64(x) -> i64` | de un `i32`, siempre cabe; de un `f64`, trunca hacia cero; `nan` o un valor que no entra es un panic |
| `to_f64(n) -> f64` | convierte un `i32` o un `i64` a `f64` (un `i64` de más de 2^53 puede perder precisión) |
| `rand() -> f64` | número al azar en [0, 1), el mismo generador en los dos backends |
| `seed(n: i32)` | fija la semilla de `rand()` de la tarea actual (las tareas que cree después derivan la suya de esta) |

Todas siguen las reglas de `f64` (IEEE 754): un resultado fuera de rango es
`inf` o `nan`, no un error. Los operadores están en §2.3 y las conversiones en
§2.4.

## A.2 Texto

| Función | Qué hace |
|---|---|
| `len(s: str) -> i32` | cantidad de caracteres (no de bytes): `len("ñandú")` es 5 |
| `a_texto(x) -> str` | un `i32`, `i64`, `f64`, `bool` o `str` como texto, igual que lo imprime `print`: `a_texto(2.5)` es `"2.5"` |
| `chr(n: i32) -> str` | el carácter de código Unicode `n`: `chr(8364)` es `"€"` (§7.3) |
| `ord(s: str) -> i32` | el código del primer carácter: `ord("€")` es 8364 |
| `int(s: str) -> Result<i32>` | texto a entero: `Ok(42)`, o `Err(...)` si no es un número; acepta espacios al principio y al final y un signo; fuera de `i32` es `Err` |
| `int64(s: str) -> Result<i64>` | lo mismo, con el rango de `i64` |

## A.3 El programa y el tiempo

| Función | Qué hace |
|---|---|
| `arg(i: i32) -> Option<str>` | el argumento número `i` del programa, desde 0 (§1.6) |
| `now() -> f64` | segundos de un reloj monotónico: sirve para restar dos lecturas y medir una duración, no como fecha |
| `sleep(s: f64)` | espera `s` segundos (admite fracciones); si la tarea se cancela, se despierta |
| `panic(m: str)` | termina la tarea con el mensaje `m`, en cascada hasta `main` (código de salida 1); cuenta como salida para "todos los caminos terminan en `return`" (§5.6) |

## A.4 Colecciones y canales

| Función | Qué hace |
|---|---|
| `vec_new() -> Vec<T>`, `vec_new(cap)` | un `Vec` vacío; `cap` reserva lugar de antemano (capítulo 6) |
| `map_new() -> Map<K,V>` | un `Map` vacío (§6.5) |
| `chan_new() -> Chan<T>`, `chan_new(cap)` | un canal; con `cap > 0`, `send()` espera si está lleno (§9.3) |
| `inject_chan(t, c) -> Result<()>` | entrega un canal a una `task` que ya está corriendo (§17.4) |
| `accept_chan() -> Option<Chan<T>>` | dentro de esa `task`, recoge el canal sin esperar (§17.4) |

Estas cinco no tienen argumentos de los que se pueda deducir `T`: el tipo sale
de lo que espera el lugar donde se usan: la anotación del `let`
(`let v: Vec<str> = vec_new()`), el campo de struct al que se asignan o el
parámetro que las recibe. Si nada lo dice, `T` es `i32`. Un `Vec` con valores
conocidos se arma más corto con un literal: `[1, 2, 3]` (§6.1).

## A.5 Entrada y salida

| Función | Qué hace |
|---|---|
| `file_open(ruta: str, modo: str) -> Result<File>` | abre un archivo (§11.1) |
| `tcp_connect(host: str, puerto: i32) -> Result<Socket>` | conexión TCP (§11.3) |
| `tcp_listen(puerto: i32) -> Result<Listener>` | escucha en un puerto TCP (§11.3) |
| `pipe_new() -> Pipe` | un pipe del sistema operativo, con un extremo para escribir y otro para leer |
| `read_pipe(fd: i32) -> Result<str>` | lee de un pipe, con su propio límite de tiempo (§11.4); un descriptor que el programa no tiene es un panic |
