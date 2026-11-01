# 9. Tareas y regiones

Este es el capítulo que le da nombre a SCAR. Hasta acá todo corría en un solo
hilo, una línea después de otra. Ahora vas a lanzar **tareas** que corren al
mismo tiempo, en los núcleos de tu procesador, y vas a ver por qué en SCAR no
pueden pisarse entre ellas.

> **Una tarea y una región de memoria son la misma cosa.** Todo lo que una
> tarea crea es suyo, y cuando la tarea termina, se libera.

## 9.1 `task`, `spawn` y `join`

Una tarea se declara como una función, con `task` en vez de `fn`. `spawn` la
lanza y devuelve enseguida un *handle*; `.join()` espera a que termine y da lo
que devolvió:

```scar
task contar_primos(desde: i32, hasta: i32) -> i32 {
    let mut n = 0
    for x in desde..hasta {
        let mut primo = x > 1
        let mut d = 2
        while d * d <= x and primo {
            if x % d == 0 {
                primo = false
            }
            d = d + 1
        }
        if primo {
            n = n + 1
        }
    }
    return n
}

fn main() {
    let a = spawn contar_primos(0, 50000)
    let b = spawn contar_primos(50000, 100000)
    print("primos menores que 100000:", a.join() + b.join())
}
```

```
primos menores que 100000: 9592
```

Las dos mitades se cuentan en paralelo, cada una en su propio hilo. Mientras
tanto `main` sigue: recién `.join()` la hace esperar.

## 9.2 Cada tarea es dueña de su región

Todo lo que una tarea crea vive en su región, y la región es de esa tarea
sola. Cuando termina (porque devolvió, por un error, o porque la cancelaron),
lo que quede se libera. Lo que devuelve con `return` pasa a quien hizo
`join()`, así que el resultado sobrevive a la tarea que lo creó.

Lo que le pasas a `spawn` **se mueve** a la tarea, igual que con `let b = a`
(capítulo 8). Es la regla que impide que dos hilos toquen el mismo dato al
mismo tiempo:

```scar-error
struct Contador {
    valor: i32
}

task sumar_mucho(c: Contador) -> i32 {
    for i in 0..1000 {
        c.valor = c.valor + 1
    }
    return c.valor
}

fn main() {
    let c = Contador { valor: 0 }
    let t = spawn sumar_mucho(c)
    c.valor = 5
    print(t.join())
}
```

Si `spawn` prestara `c` como una función normal, `main` y la tarea cambiarían
el mismo contador a la vez desde dos hilos: una *condición de carrera*, el
error más difícil de encontrar en programas concurrentes. En SCAR no compila.
La forma correcta es que cada tarea tenga lo suyo y devuelva el resultado:

```scar
struct Contador {
    valor: i32
}

task sumar_mucho(c: Contador, veces: i32) -> i32 {
    for i in 0..veces {
        c.valor = c.valor + 1
    }
    return c.valor
}

fn main() {
    let t1 = spawn sumar_mucho(Contador { valor: 0 }, 1000)
    let t2 = spawn sumar_mucho(Contador { valor: 0 }, 2000)
    print("total:", t1.join() + t2.join())
}
```

```
total: 3000
```

## 9.3 Canales: hablar mientras se corre

`join` sirve para el resultado final. Para que dos tareas se pasen datos
**mientras** corren está `Chan<T>`, un canal: `send` mete un valor, `recv` lo
saca.

```scar
task producir(ch: Chan<i32>) -> i32 {
    for i in 1..6 {
        ch.send(i * i)
    }
    ch.close()
    return 0
}

task consumir(ch: Chan<i32>) -> i32 {
    let mut total = 0
    while let Some(v) = ch.recv() {
        total = total + v
    }
    return total
}

fn main() {
    let ch: Chan<i32> = chan_new()
    let p = spawn producir(ch)
    let c = spawn consumir(ch)
    p.join()
    print("suma de los cuadrados del 1 al 5:", c.join())
}
```

```
suma de los cuadrados del 1 al 5: 55
```

- `ch.send(x)` manda `x`. El valor **se mueve** por el canal: deja de ser de
  quien lo mandó y pasa a ser de quien lo recibe. Por eso un canal es seguro
  y compartir un struct no.
- `ch.recv()` espera hasta que llegue algo y da `Some(valor)`, o `None` cuando
  el canal está cerrado y vacío. De ahí el `while let`.
- `ch.close()` avisa que no va a llegar nada más.
- `ch.try_recv()` no espera: da `Some(v)` si hay algo en ese momento y `None`
  si no. Sirve para un loop que no puede quedarse parado, como una ventana que
  se redibuja.

Un mismo canal se puede pasar a varias tareas (un canal no se mueve: es el
caño, no el agua). `chan_new(10)` crea un canal con capacidad: si tiene 10
valores sin leer, `send` espera a que alguien lea. Así quien produce rápido no
llena la memoria.

## 9.4 Nadie sobrevive a quien lo creó

En SCAR, una tarea no puede quedar corriendo huérfana. Si quien la lanzó
termina antes que ella (normalmente o por un error), la tarea se **cancela**, y
con ella sus propias hijas, en cascada. Es lo que se llama *concurrencia
estructurada*: las tareas forman un árbol, y ninguna rama vive más que su
tronco.

```scar
task trabajar_para_siempre(n: i32) -> i32 {
    while true {
        sleep(0.01)
    }
    return n
}

fn main() {
    let t = spawn trabajar_para_siempre(1)
    sleep(0.05)
    print("main termina; la tarea se cancela sola")
}
```

```
main termina; la tarea se cancela sola
```

El programa termina: la tarea que corría para siempre se canceló cuando
`main` terminó.

## 9.5 Cuando algo falla adentro de una tarea

Un panic en una tarea **sube** por `join` hasta quien la espera, y cancela a
sus hermanas por el camino. Cada nivel deja una línea en la salida de
errores:

```scar-panic
task hija(n: i32) -> i32 {
    if n > 1 {
        panic("n demasiado grande")
    }
    return n
}

fn main() {
    print("antes")
    let t = spawn hija(5)
    print(t.join())
}
```

```
antes
[PANIC] la tarea 'hija' murió: n demasiado grande
[PANIC] main murió porque su hija 'hija' panickeó: n demasiado grande
```

Para un error esperable, la tarea devuelve un `Result` y quien hace `join`
decide qué hacer (capítulo 5).

## 9.6 Deadlocks

Un *deadlock* es cuando todas las tareas esperan algo que nadie va a hacer:
un `recv` de un canal vacío que nadie va a llenar, un `join` en círculo. SCAR
lleva la cuenta de las tareas vivas y de las que están esperando. Si **todas**
esperan y nada avanza, ninguna va a poder seguir, y en vez de colgarse el
programa termina con un panic que lo explica:

```scar-panic
fn main() {
    let ch: Chan<i32> = chan_new()
    print("espero algo que nunca llega...")
    let v = ch.recv()
    print(v)
}
```

```
espero algo que nunca llega...
[PANIC] main murió: deadlock: todas las tareas están esperando un canal o un join() y ninguna puede seguir (un send() a un canal lleno o un recv() de uno vacío que nadie va a llenar; ¿falta un ch.close() o una tarea que lea?)
```

Una tarea que duerme (`sleep`), lee de la red o hace cuentas no cuenta como
esperando, así que esto no da falsas alarmas.

## 9.7 Guardar un handle para después

El handle de `spawn` tiene tipo `Task<T, nombre_de_la_tarea>`. Se puede
guardar en un `Option`, en un struct o en un `Vec`, para lanzar la tarea cuando
haga falta y esperarla al final:

```scar
task cuadrado(n: i32) -> i32 {
    return n * n
}

fn main() {
    let tareas: Vec<Task<i32, cuadrado>> = vec_new()
    for i in 1..5 {
        tareas.push(spawn cuadrado(i))
    }
    let mut suma = 0
    while let Some(t) = tareas.pop() {
        suma = suma + t.join()
    }
    print("1 + 4 + 9 + 16 =", suma)
}
```

```
1 + 4 + 9 + 16 = 30
```

Lo que un handle no puede es **salir de la región que lanzó la tarea**: una
tarea no devuelve un handle ni lo manda por un canal, porque esa región va a
esperar o cancelar a sus hijas cuando termine.

## 9.8 Ejercicios

1. Reparte la suma de 1 a 10.000.000 entre 4 tareas y compara el tiempo con
   una sola (`now()` es un reloj en segundos: la resta de dos llamadas es el
   tiempo que pasó).
2. Escribe un productor que mande los 20 primeros pares por un canal y un
   consumidor que los sume.
3. Arma un *pool*: 3 tareas que leen números de un mismo canal y devuelven
   cuántos procesó cada una.
4. Escribe un programa con un deadlock a propósito: dos tareas que esperan
   cada una el canal de la otra.

El programa de este capítulo está en `ejemplos/09_tareas.scar`.
