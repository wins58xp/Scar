# 5. Enums, `Option`, `Result` y errores

## 5.1 `enum`: un valor que es una de varias cosas

Un `enum` es un tipo cuyo valor es **una de varias variantes**. Cada variante
puede traer sus propios datos:

```scar
enum Forma {
    Circulo(f64)
    Rect(f64, f64)
    Nada
}

fn main() {
    let a = Circulo(2.0)
    let b = Rect(3.0, 4.0)
    let c = Nada
    print(a, b, c)
}
```

```
Circulo(2.0) Rect(3.0, 4.0) Nada
```

Una variante se crea con su nombre: como una llamada si trae datos, sin
paréntesis si no. Las variantes empiezan con mayúscula y se escriben sin el
nombre del enum delante, así que no se pueden repetir entre enums.

## 5.2 `match`: mirar qué variante es

`match` elige un brazo según la variante y le pone nombre a sus datos:

```scar
enum Forma {
    Circulo(f64)
    Rect(f64, f64)
    Nada
}

fn area(f: Forma) -> f64 {
    match f {
        Circulo(r) => {
            return 3.14159 * r * r
        }
        Rect(ancho, alto) => {
            return ancho * alto
        }
        Nada => {
            return 0.0
        }
    }
}

fn main() {
    print(area(Circulo(1.0)), area(Rect(3.0, 4.0)), area(Nada))
}
```

```
3.14159 12.0 0.0
```

Las reglas:

- **Tiene que cubrir todos los casos**, o terminar con `_ => ...`, el brazo
  para los que no se nombraron. Si falta uno, el compilador dice cuál. Así,
  cuando agregas una variante, el compilador te muestra cada `match` que hay
  que revisar.
- Un dato que no usas se escribe `_`: `Rect(ancho, _)`.
- Un brazo puede ser un bloque `{ ... }` o una sola expresión:
  `Nada => print("nada")`.

```scar-error
enum Semaforo {
    Rojo
    Amarillo
    Verde
}

fn main() {
    let s = Verde
    match s {
        Rojo => print("para")
        Verde => print("sigue")
    }
}
```

A ese `match` le falta `Amarillo`.

Un `match` también puede **dar un valor**: con `return match`, `x = match` o
`let x: T = match` (el `let` necesita el tipo escrito). Cada brazo es entonces
una expresión:

```scar
enum Forma {
    Circulo(f64)
    Rect(f64, f64)
    Nada
}

fn nombre(f: Forma) -> str {
    return match f {
        Circulo(_) => "círculo"
        Rect(_, _) => "rectángulo"
        Nada => "nada"
    }
}

fn main() {
    let r = Rect(3.0, 4.0)
    let ancho: f64 = match r {
        Rect(w, _) => w
        _ => 0.0
    }
    print(nombre(r), "de ancho", ancho)
}
```

```
rectángulo de ancho 3.0
```

## 5.3 `Option<T>`: puede que haya, puede que no

Muchas veces un valor puede no estar: el primer argumento del programa, el
elemento 10 de una lista que tiene 3, una clave en un diccionario. SCAR no
tiene `null`; para eso está `Option<T>`, que es `Some(valor)` o `None`:

```scar
fn buscar_par(desde: i32, hasta: i32) -> Option<i32> {
    for n in desde..hasta {
        if n % 2 == 0 {
            return Some(n)
        }
    }
    return None
}

fn main() {
    match buscar_par(5, 9) {
        Some(n) => print("el primer par es", n)
        None => print("no hay pares")
    }
    match buscar_par(7, 8) {
        Some(n) => print("el primer par es", n)
        None => print("no hay pares")
    }
}
```

```
el primer par es 6
no hay pares
```

Para mirarlo sin `match` hay métodos: `o.is_some()`, `o.is_none()`, y
`o.unwrap_or(valor)`, que da lo de adentro o `valor` si no hay nada (solo
para números y `bool`):

```scar
fn main() {
    let a: Option<i32> = Some(4)
    let b: Option<i32> = None
    print(a.is_some(), b.is_none(), a.unwrap_or(0), b.unwrap_or(0))
}
```

```
true true 4 0
```

Un tercer camino es `while let`, que repite mientras haya un `Some`. Lo vas
a usar mucho con listas y canales (capítulos 6 y 9):

```scar
fn main() {
    let mut cuenta: Option<i32> = Some(3)
    while let Some(n) = cuenta {
        print("quedan", n)
        cuenta = if n > 1 { Some(n - 1) } else { None }
    }
}
```

```
quedan 3
quedan 2
quedan 1
```

## 5.4 `Result<T>`: funciona o dice por qué no

SCAR no tiene excepciones. Una función que puede fallar devuelve `Result<T>`:
`Ok(valor)` si salió bien, `Err(mensaje)` si no.

```scar
fn dividir(a: i32, b: i32) -> Result<i32> {
    if b == 0 {
        return Err("división por cero")
    }
    return Ok(a / b)
}

fn main() {
    match dividir(9, 3) {
        Ok(v) => print("resultado:", v)
        Err(e) => print("error:", e)
    }
    match dividir(7, 0) {
        Ok(v) => print("resultado:", v)
        Err(e) => print("error:", e)
    }
}
```

```
resultado: 3
error: división por cero
```

Igual que `Option`, se puede mirar sin `match`: `r.is_ok()`, `r.is_err()`,
`r.err()` (el mensaje, o `""` si es `Ok`) y `r.unwrap_or(valor)`.

## 5.5 El operador `?`

Revisar cada `Result` con un `match` se vuelve largo cuando una función llama a
varias que pueden fallar. El operador `?` hace la cuenta por ti: si lo de la
izquierda es `Ok(v)`, da `v` y sigue; si es `Err`, la función **devuelve ese
mismo error** en ese punto.

```scar
fn leer_puerto(texto: str) -> Result<i32> {
    let n = int(texto)?
    if n < 1 or n > 65535 {
        return Err("puerto fuera de rango")
    }
    return Ok(n)
}

fn probar(texto: str) {
    match leer_puerto(texto) {
        Ok(p) => print(texto, "-> puerto", p)
        Err(e) => print(texto, "-> error:", e)
    }
}

fn main() {
    probar("8080")
    probar("ochenta")
    probar("99999")
}
```

```
8080 -> puerto 8080
ochenta -> error: no se pudo convertir 'ochenta' a entero
99999 -> error: puerto fuera de rango
```

`int(texto)` convierte un texto a número y devuelve `Result<i32>`. `?` solo
se puede usar en una función que también devuelve `Result`, porque el error
tiene que tener adónde ir. `main` puede devolver `Result<i32>`: un `Err` ahí
termina el programa con código 1 y escribe el mensaje.

```scar
fn main() -> Result<i32> {
    let n = int("42")?
    print("el doble es", n * 2)
    return Ok(0)
}
```

```
el doble es 84
```

No hay un `unwrap()` que convierta un error en un cierre del programa sin
avisar: si tienes un `Result`, lo manejas con `match` o lo propagas con `?`, y
eso queda escrito en el código.

## 5.6 `panic`: lo que no debería pasar nunca

`Result` es para los errores que se esperan: un archivo que no existe, un dato
mal escrito. Para lo que tu programa da por **imposible** está `panic(mensaje)`:
detiene el programa y dice dónde.

```scar-panic
fn mes(n: i32) -> str {
    if n == 1 {
        return "enero"
    }
    if n == 2 {
        return "febrero"
    }
    panic("mes inválido: " + a_texto(n))
}

fn main() {
    print(mes(2))
    print(mes(13))
}
```

```
febrero
[PANIC] main murió: mes inválido: 13
```

La línea del `[PANIC]` va a la salida de errores, no a la normal, y es igual
con `scar run` y con el binario.

Lo mismo pasa con los errores que SCAR detecta al correr: dividir un entero
por cero, pasarse del rango de un número, pedir una posición que no existe en
una lista. El programa termina con código 1. En el capítulo 9 vas a ver qué
pasa cuando el panic ocurre en una tarea que corre en paralelo.

## 5.7 Ejercicios

1. Define `enum Moneda { Peso(i64)  Dolar(f64) }` y una función que pase
   cualquiera de las dos a pesos.
2. Escribe `fn raiz(x: f64) -> Result<f64>` que dé un error con un número
   negativo, y úsala con `?` desde otra función.
3. Escribe `fn primer_multiplo(n: i32, de: i32) -> Option<i32>` que busque el
   primer múltiplo de `de` mayor que `n` y menor que 1000.
4. Agrega una variante a un enum que ya tengas y mira qué `match` te marca el
   compilador.

El programa de este capítulo está en `ejemplos/05_enums_y_errores.scar`.
