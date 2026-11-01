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

## 8.3 Un `Vec` o un `Map` se entrega

Con las colecciones es al revés: un `Vec` o un `Map` que le pasas directo a una
función **se mueve** a la función. Si la necesitas de vuelta, la función la
devuelve:

```scar
fn agregar(v: Vec<i32>, x: i32) -> Vec<i32> {
    v.push(x)
    return v
}

fn main() {
    let mut numeros: Vec<i32> = vec_new()
    numeros = agregar(numeros, 1)
    numeros = agregar(numeros, 2)
    print(numeros)
}
```

```
[1, 2]
```

Usarla después de pasarla, sin recibirla de vuelta, es un error:

```scar-error
fn largo(v: Vec<i32>) -> i32 {
    return v.len()
}

fn main() {
    let w = [1, 2, 3]
    print(largo(w))
    print(w)
}
```

Si una colección tiene que viajar prestada, va dentro de un struct: el struct
se presta, y la lista con él.

```scar
struct Inventario {
    items: Vec<str>
}

fn agregar_item(inv: Inventario, nombre: str) {
    inv.items.push(nombre)
}

fn main() {
    let inv = Inventario { items: vec_new() }
    agregar_item(inv, "martillo")
    agregar_item(inv, "llave")
    print(inv.items)
}
```

```
['martillo', 'llave']
```

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
