# 8. Propiedad: quién es dueño de cada valor

SCAR no tiene recolector de basura, y tampoco te pide liberar memoria a mano.
Lo logra con una regla: **cada valor tiene un solo dueño.** Cuando el dueño
deja de existir (termina la función o el bloque donde vive), el valor se
libera. El compilador sigue a cada dueño y sabe, en cada línea, quién es.

Este capítulo explica esa regla. Es la base del capítulo 9, donde la misma
idea hace que varias tareas puedan correr en paralelo sin pisarse.

## 8.1 Lo que se copia y lo que se mueve

Los números y los `bool` son chicos: se **copian** siempre. Darle un número a
otra variable deja dos números independientes.

Un struct, un `Vec`, un `Map` o un texto armado al correr (con `+`, con
`a_texto`, leído de un archivo) pueden ser grandes y tienen un dueño. Darlo a
otra variable lo **mueve**: el dueño pasa a ser la variable nueva, y la vieja
deja de servir.

```scar-error
struct Punto {
    x: i32
    y: i32
}

fn main() {
    let a = Punto { x: 1, y: 2 }
    let b = a
    print(a.x)
}
```

```
ERROR DE TIPO: uso de 'a' después de haber sido movida (...). Se movió en la línea 8 (línea 9)
```

¿Por qué no copiarlo y listo? Porque si `a` y `b` fueran el mismo objeto, al
mover uno (por ejemplo, meterlo en una lista, o mandarlo a otra tarea) el otro
quedaría apuntando a algo que ya no es suyo. Con un solo dueño eso no puede
pasar, y el compilador sabe exactamente cuándo liberar cada cosa.

Los textos escritos en el programa (`"hola"`) son una excepción cómoda: viven
mientras corre el programa, así que se pueden usar las veces que quieras.

## 8.2 Los structs se prestan

Pasar un struct a una función **no** lo mueve: la función lo recibe prestado
mientras dura la llamada, y después sigue siendo tuyo. Lo que la función
cambie adentro, se ve afuera (lo viste en el capítulo 4):

```scar
struct Cuenta {
    saldo: i64
}

fn cobrar_comision(c: Cuenta) {
    c.saldo = c.saldo - 500
}

fn main() {
    let c = Cuenta { saldo: 10000 }
    cobrar_comision(c)
    cobrar_comision(c)
    print(c.saldo)
}
```

```
9000
```

La excepción es una función que **se queda** con lo que recibe: lo guarda en
una lista, lo mete en otro struct o lo manda a otra tarea. Entonces ya no es un
préstamo, y el compilador lo trata como un movimiento en quien la llama. El
error dice por qué:

```scar-error
struct Pedido {
    numero: i32
}

fn encolar(cola: Vec<Pedido>, p: Pedido) {
    cola.push(p)
}

fn main() {
    let cola: Vec<Pedido> = vec_new()
    let p = Pedido { numero: 1 }
    encolar(cola, p)
    print(p.numero)
}
```

```
... Se movió en la línea 12: encolar() se queda con su parámetro 'p' porque guarda 'p' con .push() (línea 6) (línea 13)
```

## 8.3 Un `Vec` o un `Map` también se presta

Con las colecciones es igual: un `Vec` o un `Map` que le pasas a una función se
presta. La función puede leerlo, agrandarlo o cambiar sus elementos, y lo que
haga se ve afuera:

```scar
fn agregar(v: Vec<i32>, x: i32) {
    v.push(x)
}

fn contar(m: Map<str, i32>, palabra: str) {
    match m.get(palabra) {
        Some(n) => m.set(palabra, n + 1),
        None => m.set(palabra, 1),
    }
}

fn main() {
    let numeros: Vec<i32> = vec_new()
    agregar(numeros, 1)
    agregar(numeros, 2)
    print(numeros)
    let veces: Map<str, i32> = map_new()
    contar(veces, "hola")
    contar(veces, "hola")
    print(veces.get("hola"))
}
```

```
[1, 2]
Some(2)
```

También se presta un campo (`agregar(inv.items, 3)`), un elemento de una lista
de listas (`agregar(filas[0], 3)`) o una lista recién armada
(`agregar([1, 2], 3)`, que se libera al terminar la línea).

Lo que no se puede es pasar, en una misma llamada, una parte prestada y lo que la
contiene, si la función podría cambiarle el lugar a esa parte por el otro lado:

- una fila y su tabla (`f(filas[0], filas)`), si la función puede agrandar o
  cambiar la tabla: la fila vive dentro de ella, y al crecer la tabla se muda;
- un campo y su struct (`f(c.pesos, c)`), si la función puede **reasignar** ese
  campo (`c.pesos = ...`), directo o a través de otra función: lo que recibió como
  campo sería el valor de antes, que ya no está.

```scar-error
struct Capa {
    pesos: Vec<f64>
}

fn rehacer(c: Capa, p: Vec<f64>) -> f64 {
    c.pesos = [0.0, 0.0]
    return p.suma()
}

fn main() {
    let c = Capa { pesos: [1.0, 2.0] }
    print(rehacer(c, c.pesos))
}
```

```
... no se puede pasar 'c.pesos' y, en la misma llamada, lo que lo contiene a rehacer(): rehacer() puede reasignar 'c.pesos' por el otro argumento, y lo que recibió como 'c.pesos' quedaría mirando el objeto de antes. Hazlo en dos pasos (línea 12)
```

Todo lo demás sí se puede: que la función solo lea, que cambie números, que
agrande el campo (`c.pesos.push(x)` cambia lo de adentro, y eso se ve igual por
los dos lados), o pasar dos partes distintas del mismo dato (`f(c.pesos, c.sesgos)`,
`f(filas[0], filas[1])`).

Y la excepción es la misma que con los structs: si la función **se queda** con
la colección (la devuelve, la guarda en otra lista o en un struct, la manda a
otra tarea), la recibe movida, y quien la llama ya no la tiene:

```scar-error
fn guardar(todas: Vec<Vec<i32>>, v: Vec<i32>) {
    todas.push(v)
}

fn main() {
    let todas: Vec<Vec<i32>> = vec_new()
    let w = [1, 2, 3]
    guardar(todas, w)
    print(w)
}
```

```
... Se movió en la línea 8: guardar() se queda con su parámetro 'v' porque se lo pasa a .push(), que se queda con él (línea 2) (línea 9)
```

Dos casos reciben siempre la colección movida: una `task` (corre en otro hilo)
y una función genérica (`fn largo<T>(v: Vec<T>)`). Una función que guardas en
una variable (`let f = suma`) presta, como si la llamaras directo; por eso no
puedes guardar una que se queda con lo que recibe: el compilador te dice cuál
parámetro y por qué.

## 8.4 Devolver entrega

Una función que crea un valor y lo devuelve le entrega la propiedad a quien
la llamó:

```scar
fn lista_de(n: i32) -> Vec<i32> {
    let v: Vec<i32> = vec_new()
    for i in 0..n {
        v.push(i * i)
    }
    return v
}

fn main() {
    let cuadrados = lista_de(5)
    print(cuadrados)
}
```

```
[0, 1, 4, 9, 16]
```

`v` nació adentro de `lista_de`, pero no se libera al terminar la función: se
entregó con `return`, y su dueño ahora es `cuadrados`.

## 8.5 Las colecciones son dueñas de lo que guardan

`push` mueve el valor adentro de la lista, y `get` solo te lo deja mirar
(capítulo 6): lo que da sigue siendo de la lista, que es su única dueña, y por
eso no se puede mandar por un canal, guardar en otra colección ni devolver. Para
quedarte con un elemento, sácalo: `pop` toma el último, `replace` lo cambia por
otro y te lo devuelve (en un `Map`, `remove`). Desde ahí es tuyo:

```scar
struct Estacion {
    nombre: str
    lecturas: i32
}

fn main() {
    let estaciones: Vec<Estacion> = vec_new()
    estaciones.push(Estacion { nombre: "norte", lecturas: 0 })

    let e = estaciones.replace(0, Estacion { nombre: "", lecturas: 0 })
    e.lecturas = e.lecturas + 10
    estaciones.set(0, e)

    match estaciones.get(0) {
        Some(x) => print(x.nombre, x.lecturas)
        None => {}
    }
}
```

```
norte 10
```

## 8.6 Mover adentro de un loop

Un loop corre su cuerpo muchas veces. Si adentro mueves algo que se declaró
afuera, la segunda vuelta lo usaría ya movido. El compilador lo ve:

```scar-error
struct Dato {
    n: i32
}

fn main() {
    let lista: Vec<Dato> = vec_new()
    let d = Dato { n: 1 }
    for i in 0..3 {
        lista.push(d)
    }
}
```

```
ERROR DE TIPO: 'd' se mueve acá, adentro del loop de la línea 8, pero es de afuera: la vuelta siguiente lo volvería a usar ya movido. Se arregla moviéndolo una sola vez fuera del loop, guardando una copia, o dándole otro valor antes de usarlo en cada vuelta (línea 9)
```

Lo normal es crear el valor adentro, uno nuevo en cada vuelta:

```scar
struct Dato {
    n: i32
}

fn main() {
    let lista: Vec<Dato> = vec_new()
    for i in 0..3 {
        let d = Dato { n: i * 10 }
        lista.push(d)
    }
    print(lista.len())
}
```

```
3
```

También vale darle otro valor antes de volver a usarlo, o moverlo y salir del
loop en el mismo camino (`lista.push(d)` y `break`).

## 8.7 Cuándo se libera

No hay que hacer nada: el compilador libera cada valor cuando su dueño
termina.

- Una variable se libera al final del bloque donde se declaró (la función, el
  cuerpo de un `if`, una vuelta de un loop), salvo que se haya movido o
  devuelto.
- Lo que está dentro de una colección o de un struct se libera con ella.
- Un valor que reemplazas (`x = otro`) libera el que había.

Liberar no siempre significa devolverle la memoria al sistema operativo: en el
binario, lo que se libera queda en una lista del hilo y el próximo valor del
mismo tamaño lo reusa, que es mucho más rápido que pedir memoria nueva. La
lista tiene un tope, así que un programa que corre mucho no crece. Para ti no
cambia nada: cada valor se libera en el mismo momento de siempre.

Esto vale igual en el intérprete y en el binario. En el binario se puede
comprobar con las herramientas de C que detectan pérdidas de memoria
(AddressSanitizer): mientras se desarrolla SCAR, cada programa de prueba se
compila con ellas y tiene que dar cero pérdidas.

## 8.8 Ejercicios

1. Escribe un programa que mueva un struct a otra variable y lee el error.
   Después arréglalo usando solo la variable nueva.
2. Escribe una función que reciba un `Vec<i32>`, le agregue un elemento y lo
   devuelva. Después haz lo mismo con el `Vec` dentro de un struct prestado.
3. Escribe `fn copia(p: Punto) -> Punto` que arme un struct nuevo con los
   mismos campos. ¿Cuándo te sirve?
4. En el ejemplo de 8.6, agrega `break` después del `push` en el loop con `d`
   de afuera. ¿Lo acepta el compilador? ¿Por qué?

El programa de este capítulo está en `ejemplos/08_propiedad.scar`.
