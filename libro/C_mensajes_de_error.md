# Apéndice C. Mensajes de error comunes

SCAR revisa el programa entero antes de correrlo. Si encuentra un error, dice
en qué línea está, la muestra con una flecha y no ejecuta nada. Este apéndice
junta los mensajes que más vas a ver, qué los causa y cómo se arreglan. Los
mensajes aparecen igual con `scar check`, `scar run` y `scar build`.

## C.1 Antes de correr

### `variable no declarada: 'total'`

```scar-error
fn main() {
    print(total)
}
```

El nombre no existe en ese lugar: no tiene un `let` antes, está mal escrito, o
se declaró dentro de otro bloque (`{ }`) que ya se cerró. Cada variable vive
desde su `let` hasta el `}` del bloque donde nació (§2.1).

### `no se puede asignar a 'n': 'n' no es mut`

```scar-error
fn main() {
    let n = 1
    n = 2
}
```

```
ERROR DE TIPO: no se puede asignar a 'n': 'n' no es mut: declárala con 'let mut n = ...' (línea 3)
```

Una variable que cambia se declara con `let mut` (§2.1).

### `se anotó i32 pero el valor es de tipo f64`

```scar-error
fn main() {
    let x: i32 = 2.5
}
```

```
ERROR DE TIPO: 'x': se anotó i32 pero el valor es de tipo f64 (convierte con to_i32(...), que trunca hacia cero) (línea 2)
```

SCAR no convierte solo entre números cuando se puede perder algo: un `f64` no
pasa a `i32` sin que lo digas. El mensaje sugiere la conversión que hace falta
(§2.4).

### `la condición de 'if' debe ser bool`

```scar-error
fn main() {
    let x = 5
    if x {
        print("sí")
    }
}
```

Un número no es verdadero ni falso: escribe la comparación que quieres
(`if x != 0`).

### `'doble' espera 1 argumento(s), se dieron 2`

```scar-error
fn doble(x: i32) -> i32 {
    return x * 2
}

fn main() {
    print(doble(1, 2))
}
```

La llamada no coincide con la firma de la función.

### `puede llegar al final sin 'return'`

```scar-error
fn signo(n: i32) -> str {
    if n > 0 {
        return "positivo"
    }
}

fn main() {
    print(signo(3))
}
```

```
ERROR DE TIPO: 'signo' declara que devuelve str pero puede llegar al final sin 'return' (falta un 'return' al final, o un 'else' que también retorne) (línea 1)
```

Una función que devuelve algo tiene que devolverlo en **todos** los caminos.
Agrega el `return` que falta, o un `else`. Si ese camino es imposible, di por
qué con `panic(...)` (§5.6).

### `el match no cubre todas las variantes`

```scar-error
enum Color {
    Rojo
    Verde
    Azul
}

fn main() {
    let c = Color.Rojo
    match c {
        Rojo => print("rojo")
        Verde => print("verde")
    }
}
```

```
ERROR DE TIPO: el match no cubre todas las variantes de 'Color': falta Azul (agrega un brazo para cada una, o '_') (línea 9)
```

Un `match` tiene que decir qué hacer con cada variante: agrega el brazo que
falta, o `_ => ...` para "todas las demás" (§5.2).

### `'?' usado dentro de 'leer', que no devuelve Result`

```scar-error
fn leer() -> i32 {
    let n = int("42")?
    return n
}

fn main() {
    print(leer())
}
```

`?` devuelve el error a quien llamó, así que solo tiene sentido en una función
que devuelve `Result`. Cambia la firma a `-> Result<i32>` (y `return Ok(n)`), o
mira el `Result` con `match` ahí mismo (§5.5).

### `uso de 'p' después de haber sido movida`

```scar-error
struct Punto {
    x: f64
    y: f64
}

task mostrar(p: Punto) {
    print(p.x)
}

fn main() {
    let p = Punto { x: 1.0, y: 2.0 }
    let h = spawn mostrar(p)
    print(p.y)
    h.join()
}
```

Un valor tiene un solo dueño. Al pasarlo a una tarea, guardarlo en una lista o
darlo a otra variable, se **mueve**, y el dueño anterior ya no lo puede usar.
Es la regla que impide que dos tareas toquen el mismo dato (capítulos 8 y 9).
Usa el valor antes de moverlo, o mueve una copia (un struct nuevo con los
mismos campos).

### `no se puede mover 's': es un préstamo de .get()`

```scar-error
fn main() {
    let v: Vec<str> = ["a", "b"]
    while let Some(s) = v.get(0) {
        let w: Vec<str> = vec_new()
        w.push(s)
    }
}
```

Lo que da `get` sigue siendo de la lista: se puede mirar, pero no darlo a otro
dueño. Para guardarlo en otro lado, sácalo del contenedor: de un `Vec` con `pop`
o `replace`, de un `Map` con `remove` (§6.2 y §8.5).

### `'for' recorre un rango de enteros`

```scar-error
fn main() {
    let v = [1, 2, 3]
    for x in v {
        print(x)
    }
}
```

`for` solo recorre rangos (`for i in 0..n`). Una lista se recorre por sus
índices, `for i in 0..v.len()` con `v.get(i)`, o se vacía con
`while let Some(x) = v.pop()` (§6.2 y §6.3).

### `en SCAR no se usa ';'`

```scar-error
fn main() {
    let a = 1;
}
```

```
ERROR DE SINTAXIS: en SCAR no se usa ';' (línea 2): cada sentencia va en su propia línea. Saca el ';' y, si había algo después, pásalo a la línea siguiente
```

Cada sentencia va en su propia línea, sin `;`.

### `no encontré el módulo 'nada'`

```scar-error
use "nada"

fn main() {
}
```

`use "x"` busca `x.scar` al lado de tu archivo y después en la librería
estándar (`lib/`). Revisa el nombre, y que el archivo esté en la misma carpeta
(capítulo 10). Si tu programa se llama igual que una librería (`fecha.scar` con
`use "fecha"`), se encuentra a sí mismo primero: cámbiale el nombre.

## C.2 Mientras corre

Estos errores no se pueden ver antes de correr, porque dependen de los datos.
El programa termina con un **panic**: un mensaje que empieza con `[PANIC]`, y
código de salida 1. En una tarea, el panic cancela a sus hijas y llega a quien
la espera con `join` (§9.5).

### Desborde de un entero

```scar-panic
fn main() {
    let mut n = 2147483647
    n = n + 1
    print(n)
}
```

```
[PANIC] main murió: desbordamiento de i32: 2147483647 + 1
```

Un `i32` va de -2147483648 a 2147483647. SCAR no deja que una cuenta dé la
vuelta en silencio: para números más grandes usa `i64` (§2.5).

### División por cero

```scar-panic
fn main() {
    let a = 10
    let b = a - 10
    print(a / b)
}
```

```
[PANIC] main murió: división por cero (10 / 0)
```

Entre enteros, dividir por cero es un error. Con `f64` no: da `inf` o `nan`.

### Índice fuera de rango

```scar-panic
fn main() {
    let s = "hola"
    print(s[10])
}
```

```
[PANIC] main murió: índice fuera de rango: 10 (longitud 4)
```

Revisa el largo antes con `len(s)`. Para un `Vec`, `get(i)` no falla: da un
`Option` (§6.2).

### Deadlock

```scar-panic
fn main() {
    let c: Chan<i32> = chan_new()
    let v = c.recv()
    print(v.is_some())
}
```

```
[PANIC] main murió: deadlock: todas las tareas están esperando un canal o un join() y ninguna puede seguir (un send() a un canal lleno o un recv() de uno vacío que nadie va a llenar; ¿falta un ch.close() o una tarea que lea?)
```

Todas las tareas están esperando algo que ninguna va a hacer. SCAR lo detecta y
termina con un mensaje, en vez de quedarse colgado para siempre. Casi siempre
falta un `close()` en un canal, o una tarea que lea (§9.6).
