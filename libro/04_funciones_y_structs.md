# 4. Funciones y structs

## 4.1 Funciones

Una función tiene un nombre, parámetros con su tipo y, si devuelve algo, el
tipo de lo que devuelve después de `->`:

```scar
fn area_rectangulo(ancho: f64, alto: f64) -> f64 {
    return ancho * alto
}

fn saludar(nombre: str) {
    print("Hola,", nombre)
}

fn main() {
    print(area_rectangulo(3.0, 4.5))
    saludar("Ana")
}
```

```
13.5
Hola, Ana
```

El valor se devuelve siempre con `return`. Una función puede estar escrita
antes o después de donde se usa: el orden en el archivo no importa.

**Todos los caminos tienen que terminar en `return`.** Si hay una forma de
llegar al final sin devolver nada, el compilador lo dice:

```scar-error
fn signo(n: i32) -> str {
    if n > 0 {
        return "positivo"
    } else if n < 0 {
        return "negativo"
    }
}
```

Le falta el caso `n == 0`. Cuentan como salida un `return`, un `if`/`else`
cuyas ramas salen todas, un `while true` sin `break` y un `panic(...)`
(capítulo 5).

Una función se puede llamar a sí misma:

```scar
fn factorial(n: i64) -> i64 {
    if n <= 1 {
        return 1
    }
    return n * factorial(n - 1)
}

fn main() {
    print(factorial(20))
}
```

```
2432902008176640000
```

## 4.2 `struct`: juntar datos

Un `struct` agrupa varios valores con nombre en un tipo nuevo. Los campos van
uno por línea, sin coma:

```scar
struct Punto {
    x: f64
    y: f64
}

fn distancia(a: Punto, b: Punto) -> f64 {
    let dx = a.x - b.x
    let dy = a.y - b.y
    return sqrt(dx * dx + dy * dy)
}

fn main() {
    let origen = Punto { x: 0.0, y: 0.0 }
    let p = Punto { x: 3.0, y: 4.0 }
    print("distancia:", distancia(origen, p))
    print("p está en", p.x, p.y)
}
```

```
distancia: 5.0
p está en 3.0 4.0
```

Al crear un struct van todos los campos, en cualquier orden. Un campo puede
ser de cualquier tipo, también otro struct:

```scar
struct Punto {
    x: f64
    y: f64
}

struct Rectangulo {
    esquina: Punto
    ancho: f64
    alto: f64
}

fn main() {
    let r = Rectangulo { esquina: Punto { x: 1.0, y: 2.0 }, ancho: 10.0, alto: 5.0 }
    print("esquina:", r.esquina.x, r.esquina.y, "área:", r.ancho * r.alto)
}
```

```
esquina: 1.0 2.0 área: 50.0
```

## 4.3 Cambiar un campo

Los campos se cambian con `=`. No hace falta `mut`: `mut` dice si el nombre
puede pasar a ser **otro** struct, no si se puede cambiar lo de adentro.

```scar
struct Contador {
    nombre: str
    cuenta: i32
}

fn main() {
    let c = Contador { nombre: "visitas", cuenta: 0 }
    c.cuenta = c.cuenta + 1
    c.cuenta = c.cuenta + 1
    print(c.nombre, c.cuenta)
}
```

```
visitas 2
```

## 4.4 Pasar un struct a una función

Una función que recibe un struct lo recibe **prestado**: trabaja sobre el
mismo struct que tiene quien la llama, sin copiarlo. Lo que cambie adentro, se
ve afuera:

```scar
struct Cuenta {
    saldo: i64
}

fn depositar(c: Cuenta, monto: i64) {
    c.saldo = c.saldo + monto
}

fn main() {
    let mia = Cuenta { saldo: 100 }
    depositar(mia, 50)
    depositar(mia, 25)
    print("saldo:", mia.saldo)
}
```

```
saldo: 175
```

Así se escriben en SCAR las operaciones sobre un tipo: funciones que reciben
el struct como primer parámetro. Cuando una función **se queda** con el
struct (por ejemplo, lo guarda en una lista), ya no es un préstamo: el
capítulo 8 explica esa diferencia, que es la base de cómo SCAR maneja la
memoria.

## 4.5 Devolver un struct

Una función puede crear un struct y devolverlo. Quien la llama pasa a ser su
dueño:

```scar
struct Punto {
    x: f64
    y: f64
}

fn punto_medio(a: Punto, b: Punto) -> Punto {
    return Punto { x: (a.x + b.x) / 2.0, y: (a.y + b.y) / 2.0 }
}

fn main() {
    let m = punto_medio(Punto { x: 0.0, y: 0.0 }, Punto { x: 4.0, y: 2.0 })
    print(m.x, m.y)
}
```

```
2.0 1.0
```

## 4.6 Ejercicios

1. Escribe `fn es_primo(n: i32) -> bool` y úsala para imprimir los primos
   menores que 50.
2. Define `struct Fraccion { num: i32  den: i32 }` y una función
   `sumar(a, b) -> Fraccion`.
3. Escribe `fn mover(p: Punto, dx: f64, dy: f64)` que cambie el punto que
   recibe, y comprueba que el cambio se ve afuera.
4. Escribe una función recursiva que calcule el n-ésimo número de Fibonacci.
   ¿Hasta qué `n` cabe en un `i32`? ¿Y en un `i64`?

El programa de este capítulo está en `ejemplos/04_funciones_y_structs.scar`.
