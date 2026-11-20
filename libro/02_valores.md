# 2. Valores, variables y tipos

## 2.1 `let` y `let mut`

`let` le da nombre a un valor:

```scar
fn main() {
    let x = 5
    print("x =", x)
}
```

```
x = 5
```

Ese nombre es **inmutable**: no se le puede dar otro valor. Para poder
cambiarlo, se pide con `mut`:

```scar
fn main() {
    let mut total = 0
    total = total + 10
    total = total + 5
    print("total =", total)
}
```

```
total = 15
```

Que lo que cambia se vea en el código es una idea que recorre todo SCAR: en el
capítulo 9 vas a ver que lo mismo vale, a otra escala, para qué datos puede
tocar cada tarea.

Si te olvidas del `mut`, el compilador te avisa antes de correr nada:

```scar-error
fn main() {
    let x = 5
    x = 6
}
```

Los nombres que SCAR declara por ti tampoco se reasignan: los parámetros de
una función, la variable de un `for` y los datos que saca un `match`. Si
necesitas cambiar uno, cópialo primero a una variable tuya (`let mut k = n`).

## 2.2 Los tipos básicos

| Tipo   | Ejemplos              | Qué es                                       |
|--------|-----------------------|----------------------------------------------|
| `i32`  | `42`, `-7`            | entero de 32 bits: el entero de siempre      |
| `i64`  | `3000000000`          | entero de 64 bits, para lo que no cabe en un `i32` |
| `f64`  | `3.14`, `1e-5`        | número real (punto flotante de 64 bits)      |
| `f32`  | `let x: f32 = 0.5`    | número real de 32 bits: la mitad de memoria, unas 7 cifras |
| `u8`   | `let b: u8 = 200`     | un byte: entero de 0 a 255, sin signo        |
| `u32`  | `let c: u32 = 4000000000` | entero de 0 a 4.294.967.295, sin signo   |
| `u64`  | `let t: u64 = 5000000000` | entero de 0 a 18.446.744.073.709.551.615, sin signo |
| `i16`  | `let m: i16 = -12000`     | entero de -32.768 a 32.767               |
| `bool` | `true`, `false`       | verdadero o falso                            |
| `str`  | `"hola"`              | texto (capítulo 7)                           |

SCAR deduce el tipo del valor, así que casi nunca hace falta escribirlo. Cuando
quieres uno distinto del que deduciría, se anota después del nombre:

```scar
fn main() {
    let a = 5            # i32
    let b: i64 = 5       # i64
    let c: f64 = 5       # f64: el 5 se convierte solo
    let d = 2.5          # f64
    print(a, b, c, d)
}
```

```
5 5 5.0 2.5
```

## 2.3 Operadores

Aritméticos: `+ - * / %`. Entre dos enteros, `/` trunca hacia cero y `%` es el
resto; si uno de los dos es `f64`, la división es real:

```scar
fn main() {
    print(10 / 3)          # entre enteros, trunca
    print(10 % 3)          # el resto
    print(10.0 / 3.0)      # f64
    print(-7 / 2)          # trunca hacia cero
}
```

```
3
1
3.3333333333333335
-3
```

Comparaciones: `== != < > <= >=`. Lógicos, con palabras: `and`, `or`, `not`.

```scar
fn main() {
    let edad = 20
    let con_permiso = false
    print(edad >= 18 and not con_permiso)
    print(edad < 18 or con_permiso)
}
```

```
true
false
```

De bits, sobre enteros: `&` (y), `|` (o), `^` (o exclusivo), `<<` y `>>`
(corrimientos). Sirven para leer y armar formatos binarios:

```scar
fn main() {
    let palabra = 305419896          # 0x12345678
    print((palabra >> 24) & 255)     # el byte más alto
    print(palabra & 15)              # los 4 bits más bajos
    print(1 << 10)
}
```

```
18
8
1024
```

`>>` conserva el signo (`-16 >> 2` es `-4`), y correr un número negativo de
posiciones o más que sus bits (31 en un `i32`, 63 en un `i64`) es un error en
tiempo de ejecución. Los operadores de bits ligan más fuerte que las
comparaciones: `a & 1 == 1` se lee `(a & 1) == 1`.

## 2.4 Entre números: qué se convierte solo y qué no

La regla es simple: **se convierte solo lo que no puede perder nada.**

- Un `i32` pasa solo a `i64` o a `f64` donde hace falta: `7 + 0.5` es `7.5`,
  sumar un `i32` con un `i64` da un `i64`.
- Lo que puede perder algo se pide a mano: `to_i32(x)` (de `f64` o `i64`, trunca
  hacia cero), `to_i64(x)` y `to_f64(n)`.

```scar
fn main() {
    print(to_i32(3.99))              # trunca hacia cero
    print(to_i32(-3.99))
    print(to_f64(7) / to_f64(2))     # para que la división no trunque
    print(7 / 2)
}
```

```
3
-3
3.5
3
```

`i64` y `f64` no se mezclan solos: un `f64` guarda enteros exactos solo hasta
2⁵³, así que pasar un `i64` grande a `f64` puede perder precisión.

```scar
fn main() {
    let poblacion: i64 = 8000000000
    print(poblacion * 3)
    let n = 5
    print(poblacion + n)                  # el i32 se amplía solo
    print(to_i32(poblacion / 1000000))
}
```

```
24000000000
8000000005
8000
```

### `f32`: decimales de 32 bits

Un `f64` ocupa 8 bytes. Cuando hay millones de números (los pesos de una red
neuronal, las muestras de un audio, los vértices de un modelo), está `f32`:
ocupa la mitad, guarda unas 7 cifras en vez de 16, y es el formato de las GPU
y de casi todas las librerías de IA.

```scar
fn main() {
    let a: f32 = 0.1
    let b: f32 = 0.2
    print(a + b)                        # en f32
    print(0.1 + 0.2)                    # en f64
    print(a * 3, a / 3.0, a < 0.5)
    let ancho: f64 = a                  # un f32 pasa solo a f64
    print(ancho)
    print(to_f32(7), to_f32(2.5))
}
```

```
0.3
0.30000000000000004
0.3 0.033333335 true
0.10000000149011612
7.0 2.5
```

Las reglas son las mismas de los otros números:

- Un número escrito toma el tipo que se espera: `let a: f32 = 0.1` guarda el
  `f32` más cercano a 0,1. También en una cuenta: en `a * 3` y en `a < 0.5`,
  con `a` un `f32`, el `3` y el `0.5` son `f32`. Uno entero tiene que caber
  exacto (un `f32` guarda enteros exactos solo hasta 16777216).
- Un `f32` pasa solo a `f64`, porque no se pierde nada. Una cuenta entre un
  `f32` y un `f64` da `f64`.
- Al revés hay que pedirlo: `to_f32(x)` redondea un `f64` al `f32` más
  cercano, y también convierte un entero. Un `f32` y una variable entera no se
  mezclan solos: `a + n` con `n` un `i32` es un error, y se escribe
  `a + to_f32(n)`.
- `to_i32(x)` y `to_i64(x)` de un `f32` truncan hacia cero, y `to_f64(x)` lo
  amplía.

Cada cuenta se redondea a 32 bits, igual en el intérprete y en el binario, y
`print` muestra las cifras que tiene un `f32`: `0.1`, no
`0.10000000149011612`. Un `f32` va en todo lo que guarda números: campos de
un struct, `Vec<f32>`, `Map`, `Option`, `Result`, canales y funciones
genéricas con `Numeric` (capítulo 13), y cruza a C como `float` en una
`extern fn` (capítulo 14).

Si te equivocas, el compilador te dice qué conversión escribir:

```scar-error
fn main() {
    let x: i32 = 2.5
}
```

### `u8`: bytes

Un archivo binario, un paquete de red o un píxel (3 o 4 bytes: rojo, verde,
azul y transparencia) son bytes: números de 0 a 255. Para eso está `u8`, un
entero sin signo de un byte. Un `Vec<u8>` ocupa un byte por elemento, la cuarta
parte que un `Vec<i32>`.

```scar
fn main() {
    let rojo: u8 = 200
    print(rojo + 55, rojo / 3, rojo >> 4, rojo & 15)
    let total: i32 = rojo               # un u8 pasa solo a i32
    print(total * 1000)
    print(to_u8(65), to_u8(99.9))
    print(suma_ciclica(rojo, 100), resta_ciclica(to_u8(3), 5))
    let pixel: Vec<u8> = [255, 128, 0, 255]
    print(pixel, pixel.len())
}
```

```
255 66 12 8
200000
65 99
44 254
[255, 128, 0, 255] 4
```

Las reglas son las de los otros enteros:

- Un número escrito toma el tipo que se espera (`let rojo: u8 = 200`) o el del
  `u8` que tiene al lado (`rojo + 55`). Tiene que caber: `let b: u8 = 300` es un
  error del compilador.
- Una cuenta entre dos `u8` da `u8`. Pasarse de 255, o bajar de 0 al restar, es
  un **panic**, igual que pasarse del máximo de un `i32`. Cuando lo que quieres
  es dar la vuelta (un contador de un byte, un hash), se pide con
  `suma_ciclica`, `resta_ciclica` y `mult_ciclica`: `suma_ciclica(200, 100)` es
  44 y `resta_ciclica(3, 5)` es 254.
- Un `u8` pasa solo a `i32`, `i64`, `f32` y `f64`, porque siempre cabe. Al revés
  hay que pedirlo: `to_u8(x)` deja igual un entero de 0 a 255, trunca un
  decimal hacia cero, y es un panic si no cabe.
- Los bits: `&`, `|` y `^` como siempre; `<<` descarta lo que sale por arriba
  (`200 << 1` es 144) y `>>` rellena con ceros.
- Un `u8` no tiene signo, así que `-b` es un error. Para el negativo se
  convierte antes: `-to_i32(b)`.

Un `u8` va en todo lo que guarda números (structs, `Vec<u8>`, `Map`, `Option`,
`Result`, canales, funciones genéricas con `Numeric`) y cruza a C como
`uint8_t` (capítulo 14). Los bytes de un archivo o de una conexión se leen
directo en un `Vec<u8>` con `.read_u8(n)` (capítulo 11).

Un `i32` no pasa solo a `u8`, porque podría no caber; el compilador lo dice y
sugiere `to_u8`:

```scar-error
fn main() {
    let n = 300
    let b: u8 = n
}
```

### `u32`: colores, hashes y números al azar

Un color ARGB (alfa, rojo, verde, azul: un byte cada uno), un CRC, un hash o el
estado de un generador de números al azar son 32 bits sin signo: `u32`, de 0 a
4.294.967.295. Las reglas son las de `u8`:

- Un número escrito toma el tipo `u32` donde se espera uno o al lado de uno, y
  tiene que caber.
- Pasarse del máximo, o bajar de 0, es un panic. Las cíclicas dan la vuelta, que
  es justo lo que necesita un hash.
- Un `u8` pasa solo a `u32`, y un `u32` pasa solo a `i64` y a `f64`. **No** pasa
  solo a `i32` (de 2.147.483.648 para arriba no cabe) ni a `f32` (perdería
  cifras): se convierte con `to_i32(x)` o `to_f32(x)`. Al revés, `to_u32(x)`.
- Un `u32` con un `i32` en la misma cuenta es un error: ninguno cabe entero en el
  otro. El compilador propone pasar los dos a `i64`.
- Los bits: `<<` descarta lo que sale por arriba y `>>` rellena con ceros, de 0 a
  31 lugares.

```scar
fn main() {
    let color: u32 = 4294934528            # 0xFFFF8000: alfa 255, naranja
    let rojo = (color >> 16) & 255
    print(color, rojo, color & 16777215)
    let grande: i64 = color                # un u32 pasa solo a i64 y a f64
    print(grande * 2)
    let mut h: u32 = 2166136261            # el hash FNV-1a de "hola"
    let texto: Vec<u8> = [104, 111, 108, 97]
    for b in texto {
        h = mult_ciclica(h ^ b, 16777619)
    }
    print(h)
}
```

```
4294934528 255 16744448
8589869056
2999341463
```

### `u64`: hashes de 64 bits, identificadores y tamaños de archivo

Un hash de 64 bits, un identificador, el tamaño de un archivo grande o el
estado de un generador como splitmix64 son 64 bits sin signo: `u64`, de 0 a
18.446.744.073.709.551.615. Las reglas son las de `u8` y `u32`, con una
diferencia: no hay un entero más ancho donde quepa entero.

- Un número escrito toma el tipo `u64` donde se espera uno o al lado de uno. Uno
  que no cabe en un `i64` (de 9.223.372.036.854.775.808 para arriba) ya es `u64`
  sin anotarlo.
- Pasarse del máximo, o bajar de 0, es un panic. Las cíclicas dan la vuelta.
- Un `u8` y un `u32` pasan solos a `u64`. Un `u64` **no** pasa solo a nada: ni a
  `i64` (la mitad de arriba no cabe) ni a `f64` (guarda enteros exactos solo hasta
  2^53). Se convierte con `to_i64(x)` o `to_f64(x)`; al revés, `to_u64(x)`.
- Un `u64` con un `i32` o un `i64` en la misma cuenta es un error, y no hay un
  tipo donde quepan los dos: el compilador propone pasar uno al tipo del otro.
- Los bits: `<<` descarta lo que sale por arriba y `>>` rellena con ceros, de 0 a
  63 lugares.

```scar
fn main() {
    let tope: u64 = 18446744073709551615   # el máximo: 0xFFFFFFFFFFFFFFFF
    let mitad = 9223372036854775808        # no cabe en un i64: ya es u64
    print(tope - mitad, mitad >> 62)
    let tamano: u64 = 5000000000           # un archivo de 5 GB
    let bloques: u32 = 4096
    print(tamano / bloques)                # un u32 pasa solo a u64
    let mut h: u64 = 14695981039346656037  # el hash FNV-1a de 64 bits de "hola"
    let texto: Vec<u8> = [104, 111, 108, 97]
    for b in texto {
        h = mult_ciclica(h ^ b, 1099511628211)
    }
    print(h)
    print(to_i64(tamano) * -1)             # a un i64, revisado: es un panic si no cabe
}
```

```
9223372036854775807 2
1220703
4623503348185510199
-5000000000
```

### `i16`: muestras de audio y sensores

Una muestra de un WAV normal es un entero de 16 bits con signo, y muchos
sensores entregan lo mismo: `i16`, de -32.768 a 32.767. Las reglas son las de
`i32` en un rango más chico.

- Un número escrito toma el tipo `i16` donde se espera uno o al lado de uno.
- Pasarse del rango es un panic, también negar el mínimo (`-x` con x = -32768)
  o dividirlo por -1, que no tienen un `i16` positivo, y `abs` del mínimo.
- Un `u8` pasa solo a `i16`, e `i16` pasa solo a `i32`, `i64`, `f32` y `f64`.
  Al revés, `to_i16(x)`. Un `i16` no pasa solo a un sin signo (podría ser
  negativo): `to_u8(x)`, que revisa.
- Los bits: `<<` descarta lo que sale por arriba (puede cambiar el signo) y `>>`
  conserva el signo, de 0 a 15 lugares.
- No hay cíclicas: son para los sin signo. Para una cuenta que puede pasarse del
  rango (sumar muchas muestras, una ganancia), se pasa a `i32` antes.

```scar
fn main() {
    let muestra: i16 = -32768              # el mínimo: el pico negativo de un WAV
    let byte: u8 = 200
    let x: i16 = byte                      # un u8 pasa solo a i16
    print(muestra + 1, x * -100, muestra >> 8)
    let suma: i32 = to_i32(muestra) * 2    # para pasarse del rango, a i32 antes
    print(suma, abs(to_i16(-300)), to_i16(1234.9))
    let onda: Vec<i16> = [1000, -2000, 3000, -4000]
    print(onda.suma(), onda.len(), onda[1..3].suma())
}
```

```
-32767 -20000 -128
-65536 300 1234
-2000 4 1000
```

## 2.5 Cuando un número no cabe

SCAR no deja que un número se dé vuelta en silencio. Pasarse del máximo de un
`i32`, de un `i64`, de un `i16`, de un `u8`, de un `u32` o de un `u64`, dividir un entero por cero, o `to_i32` de un valor que no
cabe, es un **panic**: el programa se detiene y dice dónde y por qué (el
capítulo 5 lo explica). Un número escrito que no cabe en ningún entero ni en
un `f64` es un error del compilador, no un número cortado.

Con `f64` las reglas son las de IEEE 754, iguales en el intérprete y en el
binario: `1.0 / 0.0` es `inf`, `0.0 / 0.0` es `nan`, `sqrt(-1.0)` es `nan`.

## 2.6 Cómo se escriben los números

- Sin punto: un entero. Es `i32` si cabe; si no, `i64`; y si tampoco (de
  9.223.372.036.854.775.808 a 18.446.744.073.709.551.615), `u64`.
- Con punto o con exponente: `f64`. El exponente es como en Python o C:
  `1e-5`, `2.5E3`, `6.02e+23`.
- En hexadecimal, con `0x` adelante: `0xFF`, `0xEDB88320`. Las cifras son 0-9 y
  las letras a-f, en mayúscula o minúscula. Vale lo mismo que el decimal y sigue
  sus reglas: el tipo sale de dónde va, y si no cabe es un error
  (`let a: i32 = 0xFFFFFFFF` no se vuelve -1). Es lo natural para máscaras de
  bits, colores y las constantes de un hash o un CRC.

```scar
fn main() {
    print(0xFF, 0x1A, 0xff == 255)
    let color: u32 = 0xFFFF8000
    print(color & 0x00FFFFFF)
}
```

```
255 26 true
16744448
```

Un hexadecimal se imprime en decimal, como cualquier número.

```scar
fn main() {
    print(1e-5)
    print(2.5E3)
    print(1e3 / 8.0)
}
```

```
1e-05
2500.0
125.0
```

## 2.7 Funciones matemáticas

Sobre `f64`: `sin`, `cos`, `tan`, `atan`, `exp`, `ln` (logaritmo natural),
`log10`, `pow(b, e)`, `sqrt` y `floor`. Un `f32` entra solo y el resultado es
un `f64` (se vuelve con `to_f32`, como en `to_f32(sqrt(x))`). Sobre cualquier
número: `abs`, `min` y `max` (`abs(-3)` es el entero `3`). Dan exactamente lo mismo en el intérprete y
en el binario.

```scar
fn main() {
    print(sqrt(2.0))
    print(pow(2.0, 10.0))
    print(abs(-3), min(4, 9), max(2.5, 1.0))
}
```

```
1.4142135623730951
1024.0
3 4 2.5
```

La lista completa de funciones incorporadas está en el apéndice A.

## 2.8 El orden en que se evalúa

Siempre de izquierda a derecha: los argumentos de una llamada, los dos lados
de un operador y los campos de un struct, en el orden en que están escritos.
Lo mismo en el intérprete y en el binario, así que un programa nunca depende
de con qué lo corras.

## 2.9 Ejercicios

1. Calcula cuántos segundos tiene un año. ¿Cabe en un `i32`? ¿Y los
   milisegundos?
2. Escribe `let x: i32 = 2147483647` y después `print(x + 1)`. ¿Qué pasa?
3. Convierte 100 grados Fahrenheit a Celsius (`(f - 32) * 5 / 9`) con `i32` y
   con `f64`. ¿Por qué dan distinto?
4. Usa `&` y `>>` para separar los tres bytes de un color `0xFF8800`
   (`16746496`): rojo, verde y azul.

El programa de este capítulo está en `ejemplos/02_valores.scar`.
