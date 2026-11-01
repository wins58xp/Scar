# 3. Decidir y repetir

## 3.1 `if` y `else`

```scar
fn main() {
    let temperatura = 31
    if temperatura > 30 {
        print("hace calor")
    } else if temperatura < 10 {
        print("hace frío")
    } else {
        print("está agradable")
    }
}
```

```
hace calor
```

La condición tiene que ser un `bool`: SCAR no toma un número como verdadero o
falso. Las llaves son obligatorias, aunque la rama tenga una sola línea.

## 3.2 `if` como expresión

Un `if` también puede **dar un valor**: el de la última línea de la rama que
corre. Así no hace falta una variable `mut` que se asigna en cada rama:

```scar
fn main() {
    let n = 7
    let paridad = if n % 2 == 0 { "par" } else { "impar" }
    let grande = if n > 5 {
        let doble = n * 2
        doble + 1          # la rama vale esto
    } else {
        0
    }
    print(paridad, grande)
}
```

```
impar 15
```

Las reglas:

- **El `else` es obligatorio**: si no, ¿qué valdría cuando la condición es
  falsa?
- Cada rama termina en la expresión que da el valor. Antes puede tener otras
  líneas, que viven solo en esa rama.
- Las dos ramas dan el mismo tipo. Si una da un `i32` y la otra un `f64`,
  queda `f64`, como en una cuenta.
- Adentro de las ramas no va `return` ni `break`: el valor tiene que salir del
  `if`.

## 3.3 `while`

`while` repite mientras la condición sea verdadera:

```scar
fn main() {
    let mut total = 0
    let mut i = 1
    while i <= 100 {
        total = total + i
        i = i + 1
    }
    print("1 + 2 + ... + 100 =", total)
}
```

```
1 + 2 + ... + 100 = 5050
```

## 3.4 `for` y los rangos

`for` recorre un rango de enteros. `0..5` va de 0 a 4: **el último no se
incluye**.

```scar
fn main() {
    for i in 0..5 {
        print(i, "al cuadrado es", i * i)
    }
}
```

```
0 al cuadrado es 0
1 al cuadrado es 1
2 al cuadrado es 4
3 al cuadrado es 9
4 al cuadrado es 16
```

Los extremos pueden ser cualquier expresión entera (`for i in 1..n + 1`). Los
loops se anidan sin reglas especiales:

```scar
fn main() {
    for fila in 1..4 {
        let mut linea = ""
        for col in 1..4 {
            linea = linea + a_texto(fila * col) + " "
        }
        print(linea)
    }
}
```

```
1 2 3 
2 4 6 
3 6 9 
```

(`a_texto` convierte un número en texto; el capítulo 7 lo cuenta todo sobre
los textos.)

## 3.5 Salir antes: `break`

`break` termina el loop más interno y sigue con lo que viene después:

```scar
fn main() {
    let mut n = 1
    while true {
        if n * n > 50 {
            break
        }
        n = n + 1
    }
    print("el primer cuadrado mayor que 50 es", n * n)
}
```

```
el primer cuadrado mayor que 50 es 64
```

## 3.6 Saltar una vuelta: `continue`

`continue` deja lo que falta del cuerpo y pasa a la vuelta siguiente:

```scar
fn main() {
    for i in 1..11 {
        if i % 3 == 0 {
            continue       # se salta los múltiplos de 3
        }
        print(i)
    }
}
```

```
1
2
4
5
7
8
10
```

Un cuidado con `while`: el `continue` se salta también el `i = i + 1` del
final, y el loop no terminaría nunca. Avanza el contador antes del `continue`,
o usa un `for`.

`break` y `continue` fuera de un loop son un error:

```scar-error
fn main() {
    continue
}
```

## 3.7 Ejercicios

1. Imprime los números del 1 al 30, pero `"fizz"` en vez de los múltiplos de
   3, `"buzz"` en vez de los de 5, y `"fizzbuzz"` en los de los dos.
2. Con un `while`, encuentra el primer número cuyo cubo pasa de 10.000.
3. Imprime un triángulo de asteriscos de 5 líneas (`*`, `**`, `***`...).
4. Reescribe el ejercicio 1 usando un `if` que da un valor.

El programa de este capítulo está en `ejemplos/03_decidir_y_repetir.scar`.
