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

Si te equivocas, el compilador te dice qué conversión escribir:

```scar-error
fn main() {
    let x: i32 = 2.5
}
```

## 2.5 Cuando un número no cabe

SCAR no deja que un número se dé vuelta en silencio. Pasarse del máximo de un
`i32` o de un `i64`, dividir un entero por cero, o `to_i32` de un valor que no
cabe, es un **panic**: el programa se detiene y dice dónde y por qué (el
capítulo 5 lo explica). Un número escrito que no cabe en ningún entero ni en
un `f64` es un error del compilador, no un número cortado.

Con `f64` las reglas son las de IEEE 754, iguales en el intérprete y en el
binario: `1.0 / 0.0` es `inf`, `0.0 / 0.0` es `nan`, `sqrt(-1.0)` es `nan`.

## 2.6 Cómo se escriben los números

- Sin punto: un entero. Es `i32` si cabe y si no, `i64`.
- Con punto o con exponente: `f64`. El exponente es como en Python o C:
  `1e-5`, `2.5E3`, `6.02e+23`.

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
`log10`, `pow(b, e)`, `sqrt` y `floor`. Sobre cualquier número: `abs`, `min` y
`max` (`abs(-3)` es el entero `3`). Dan exactamente lo mismo en el intérprete y
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
