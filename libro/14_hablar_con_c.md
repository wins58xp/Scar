# 14. Hablar con C (y con Python)

Ningún lenguaje vive aislado: hay décadas de librerías escritas en C para
comprimir, cifrar, dibujar o hablar con un aparato. SCAR las puede llamar
directamente, y al revés, un programa en C o en Python puede llamar a
funciones escritas en SCAR.

## 14.1 Llamar a una función de C: `extern fn`

Se declara la firma de la función, con `extern "C" fn`, y de qué librería
viene, con `from`:

```scar
extern "C" fn hypot(x: f64, y: f64) -> f64 from "m"
extern "C" fn getenv(nombre: str) -> Result<str>

fn main() {
    print(hypot(3.0, 4.0))
    match getenv("NO_EXISTE_ESTA_VARIABLE") {
        Ok(v) => print(v)
        Err(e) => print("no está:", e)
    }
}
```

```
5.0
no está: getenv devolvió NULL
```

- `from "m"` dice que `hypot` está en `libm` (en el compilador se convierte en
  `-lm`). Sin `from`, la función es de la librería estándar de C, que siempre
  está.
- Los tipos que cruzan son los números (`i32` como `int32_t`, `i64` como
  `int64_t`, `f64` como `double`), `bool`, `str` (como `const char*`), un struct
  de SCAR con campos numéricos (por valor) y, como parámetro, un `Vec` de
  números.
- Un `str` que devuelve C se copia: el programa tiene su propia copia, y C
  sigue siendo dueño del original.
- Si la función puede devolver `NULL`, se declara con `Result<str>`: el `NULL`
  llega como `Err`, nunca como un puntero roto.

## 14.2 Handles: `extern type` y `own`

Muchas librerías de C entregan un *handle*: un puntero opaco que se le
devuelve en cada llamada. Se declara con `extern type`, y `own` marca la
función que **se queda** con el handle (la que lo cierra):

```scar
extern type GzArchivo

extern "C" fn gzopen(ruta: str, modo: str) -> Result<GzArchivo> from "z"
extern "C" fn gzwrite(f: GzArchivo, datos: str, largo: i32) -> i32 from "z"
extern "C" fn gzclose(f: own GzArchivo) -> i32 from "z"

fn comprimir(ruta: str) -> Result<i32> {
    let f = gzopen(ruta, "wb")?
    gzwrite(f, "hola mundo\n", 11)
    gzclose(f)
    return Ok(0)
}

fn main() {
    print(comprimir("/tmp/scar_libro_14.gz"))
    print(comprimir("/no/existe/x.gz").is_err())
}
```

```
Ok(0)
true
```

Después de `gzclose(f)`, usar `f` es un error del compilador, igual que usar
una variable movida (capítulo 8): no hay forma de escribir en un archivo ya
cerrado ni de cerrarlo dos veces.

## 14.3 Un `Vec` hacia C

Un `Vec<i32>`, `Vec<i64>`, `Vec<f64>` o `Vec<bool>` como parámetro llega a C
como **dos** parámetros: un puntero a los elementos y la cantidad. C lo recibe
prestado durante la llamada, y lo que cambie en los elementos vuelve al `Vec`:

```c
// vec.c, compilado como libvec.so
#include <stdint.h>
int64_t sumar(const int32_t *d, int64_t n) {
    int64_t s = 0;
    for (int64_t i = 0; i < n; i++) s += d[i];
    return s;
}
void duplicar(int32_t *d, int64_t n) {
    for (int64_t i = 0; i < n; i++) d[i] *= 2;
}
```

```scar-nocheck
extern "C" fn sumar(v: Vec<i32>) -> i64 from "vec"
extern "C" fn duplicar(v: Vec<i32>) from "vec"

fn main() {
    let v = [1, 2, 3, 4, 5]
    print(sumar(v))
    duplicar(v)
    print(v)
}
```

```
15
[2, 4, 6, 8, 10]
```

(Este necesita `libvec.so`, por eso el libro no lo prueba solo.)

## 14.4 Si la librería de C se cae

Una librería de C puede tener un error y caerse (un *segfault*). Para que eso
no se lleve el programa entero, **por omisión las funciones `extern` corren en
un proceso aparte** (un *worker*), y cada llamada va y vuelve por un tubo. Si
la librería se cae, se cae ese proceso, y el programa lo recibe como un panic
con explicación.

El costo es pequeño (decenas de microsegundos por llamada). Hay casos en que
la librería tiene que correr dentro del programa: si recibe una función de
SCAR como *callback*, si recibe un struct por valor, o si se llama miles de
veces por segundo (una interfaz gráfica). Eso se declara con una línea:

```scar-nocheck
extern lib "scarsdl" en_proceso
```

Si falta y hace falta, el compilador lo dice. Dentro del proceso, el binario
sigue convirtiendo un crash de la librería en un panic, pero ya no hay
aislamiento: si la librería corrompe memoria sin caerse, es la del programa.

## 14.5 SCAR como librería: `export fn`

Al revés: una función marcada con `export` se puede llamar desde otro
lenguaje, compilando el programa como librería compartida.

`calculos.scar`:

```scar
export fn saludo(nombre: str) -> str {
    return "hola, " + nombre + "!"
}

export fn dividir(a: i32, b: i32) -> i32 {
    if b == 0 {
        panic("división por cero: " + a_texto(a) + " / 0")
    }
    return a / b
}
```

```
scar build --lib calculos.scar        # da libcalculos.so
```

Desde Python, con `ctypes`:

```python
import ctypes
lib = ctypes.CDLL("./libcalculos.so")
lib.scar_error.restype = ctypes.c_char_p
lib.scar_liberar_str.argtypes = [ctypes.c_void_p]

lib.dividir.argtypes = [ctypes.c_int32, ctypes.c_int32]
lib.dividir.restype = ctypes.c_int32
print(lib.dividir(9, 2))                        # 4
print(lib.dividir(9, 0), lib.scar_error().decode())   # 0 división por cero: 9 / 0

lib.saludo.argtypes = [ctypes.c_char_p]
lib.saludo.restype = ctypes.c_void_p
p = lib.saludo("Ana".encode())
print(ctypes.string_at(p).decode())             # hola, Ana!
lib.scar_liberar_str(p)
```

Las reglas:

- Cruzan los números, `bool`, `str`, un struct con campos numéricos y un `Vec`
  de números (como `{ datos, n }`). Adentro de la función vale todo el
  lenguaje.
- Un `str` que devuelve la librería es de quien llama, que lo suelta con
  `scar_liberar_str` (y un `Vec`, con `scar_liberar_vec`).
- **Un panic no termina el programa que cargó la librería**: la llamada
  devuelve 0 (o `NULL`) y `scar_error()` da el mensaje.
- Cada llamada es como un `main` chico: puede lanzar tareas y usar canales, y
  antes de volver espera o cancela las que lanzó. Se puede llamar desde varios
  hilos a la vez.

## 14.6 Ejercicios

1. Declara `extern "C" fn pow(b: f64, e: f64) -> f64 from "m"` y compárala con
   el `pow` incorporado de SCAR.
2. Escribe `getenv("HOME")` y muestra tu carpeta de usuario.
3. Exporta una función que reciba un `i64` y devuelva su factorial, y llámala
   desde Python.
4. Exporta una función que lance cuatro tareas y sume sus resultados; llámala
   desde Python y mide cuánto tarda.

El programa de este capítulo está en `ejemplos/14_hablar_con_c.scar`.
