# 6. `Vec` y `Map`

SCAR trae dos colecciones: `Vec<T>`, una lista que crece, y `Map<K,V>`, un
diccionario de claves a valores. Las dos se usan con métodos (`.push`, `.get`,
`.set`...), sin una sintaxis especial.

## 6.1 `Vec<T>`: una lista

`[a, b, c]` arma una lista con esos elementos. El tipo de los elementos sale
del primero:

```scar
fn main() {
    let numeros = [10, 20, 30]
    let nombres = ["ana", "luis"]
    print(numeros, numeros.len())
    print(nombres)
}
```

```
[10, 20, 30] 3
["ana", "luis"]
```

(`print` muestra lo que hay dentro de una colección, de un `Some`/`Ok`/`Err` o de
un struct tal como se escribe en SCAR: los textos entre comillas dobles, para que
`["a, b"]` y `["a", "b"]` no se confundan, con `\"`, `\\` y `\n` escapados, y los
`bool` como `true`/`false`.)

Una lista vacía se arma con `vec_new()`. Como no tiene elementos de los que
sacar el tipo, se escribe en el `let`:

```scar
fn main() {
    let mut v: Vec<i32> = vec_new()
    v.push(5)
    v.push(8)
    v.push(13)
    print(v, "tiene", v.len(), "elementos")
}
```

```
[5, 8, 13] tiene 3 elementos
```

Los métodos de un `Vec`:

| Método           | Qué hace                                                        |
|------------------|-----------------------------------------------------------------|
| `v.push(x)`      | agrega `x` al final                                             |
| `v.len()`        | cuántos elementos hay                                           |
| `v[i]`           | el elemento `i` (desde 0): un panic si no existe (ver 6.2)       |
| `v.get(i)`       | el elemento `i` (desde 0), como `Option`: `None` si no existe   |
| `v.pop()`        | saca el último, como `Option`: `None` si está vacío             |
| `v.set(i, x)`    | pone `x` en el lugar `i`                                        |
| `v.replace(i, x)`| pone `x` en el lugar `i` y devuelve el que estaba               |
| `v.suma()`       | la suma de los elementos (un `Vec` de números)                  |
| `a.punto(b)`     | la suma de `a[i] * b[i]`, el producto punto (dos `Vec` iguales) |

## 6.2 Leer un elemento: `get` da un `Option`

`v.get(i)` nunca se sale de la lista: si `i` no existe, da `None`. Por eso
devuelve un `Option`, y lo de adentro se saca con `match` (o con
`unwrap_or` para un número):

```scar
fn main() {
    let precios = [1200, 990, 4500]
    print(precios.get(1))
    print(precios.get(7))
    print(precios.get(7).unwrap_or(0))
}
```

```
Some(990)
None
0
```

Para recorrer una lista se va por los índices:

```scar
fn main() {
    let notas = [6.5, 5.0, 7.0, 4.2]
    let mut suma = 0.0
    for i in 0..notas.len() {
        match notas.get(i) {
            Some(n) => {
                suma = suma + n
            }
            None => {}
        }
    }
    print("promedio:", suma / to_f64(notas.len()))
}
```

```
promedio: 5.675
```

`get` te deja **mirar** el elemento: si cambias lo que te da, la lista no
cambia. Un número o un `bool` se copia y puedes usarlo como quieras; un texto,
un struct o una lista que sale de `get` sigue siendo de la lista, así que no
puedes entregarlo a otro dueño (mandarlo por un canal, guardarlo en otra lista,
devolverlo). Para eso, sácalo de la lista con `pop` o `replace` (en un `Map`,
con `remove`); el capítulo 8 explica por qué. Para cambiar un elemento se usa
`set` o `replace`:

```scar
fn main() {
    let v = [1, 2, 3]
    v.set(0, 100)
    let viejo = v.replace(2, 300)
    print(v, "antes estaba", viejo)
}
```

```
[100, 2, 300] antes estaba 3
```

`set` y `replace` sí exigen que el lugar exista: un índice fuera de la lista es
un panic.

### `v[i]`: el elemento, sin `Option`

Cuando el índice tiene que existir (recorrer una lista de `0` a `len()`, por
ejemplo), `v[i]` da el elemento directo, y `v[i] = x` lo cambia. Un índice que no
existe es un panic, igual que en `set`: un índice malo es un error del programa,
no un caso que haya que manejar.

```scar
fn main() {
    let mut notas = [6.5, 5.0, 7.0, 4.2]
    let mut suma = 0.0
    for i in 0..notas.len() {
        suma = suma + notas[i]
    }
    print("promedio:", suma / to_f64(notas.len()))
    notas[3] = notas[3] + 1.0
    print(notas)
}
```

```
promedio: 5.675
[6.5, 5.0, 7.0, 5.2]
```

En el binario, `v[i]` es tan rápido como en C: sin el `Option` de por medio, es un
acceso directo a la memoria. Es lo que conviene en los cálculos con muchos
números, como los del capítulo 17.

La lista tiene que estar en una variable o en un campo (`capa.pesos[i]`): para
indexar lo que devuelve una función, guárdalo primero con `let`.

### `v[i]` en una lista de structs o de listas: un lugar

En una lista de structs o de listas, `v[i]` no es un valor que se pueda sacar:
es un **lugar**, y se trabaja ahí mismo, sin copiar nada. Se leen y escriben sus
campos de números o `bool`, se indexan sus listas, y se llaman los métodos de
lista sobre él:

```scar
struct Neurona {
    pesos: Vec<f32>
    sesgo: f32
}

fn main() {
    let mut red: Vec<Neurona> = vec_new()
    red.push(Neurona { pesos: [0.5, -0.25], sesgo: 0.1 })
    red[0].sesgo = red[0].sesgo * 2.0
    red[0].pesos[1] = 0.75
    red[0].pesos.push(1.0)
    print(red[0].sesgo, red[0].pesos)

    let mut m: Vec<Vec<f32>> = vec_new()
    m.push([1.0, 2.0])
    m.push([3.0, 4.0])
    m[1][0] = m[0][1] * 10.0
    print(m, m[1].len(), m[0].punto(m[1]))
}
```

```
0.2 [0.5, 0.75, 1.0]
[[1.0, 2.0], [20.0, 4.0]] 2 28.0
```

Lo que no se puede es sacar el elemento sin decirlo: `let n = red[0]`, guardarlo
en otra lista, pasarlo a una función que se queda con él, o sacar un campo con
dueño (`let s = red[0].nombre`) son errores. Para eso está `get`, que da una
copia, y `replace`, que lo saca de verdad. Es la misma regla del capítulo 8: nada
cambia de dueño ni se copia sin que se escriba. A una función que solo lo
**presta** (lo lee o le cambia campos, sin guardarlo ni devolverlo) sí se le pasa:
`activar(red[0], x)`.

### Recorrer una lista: `for x in v`

`for x in v` da una vuelta por cada elemento, en orden. `x` es `v[i]`, con las
mismas reglas: en una lista de números o `bool` es una copia del elemento,
tomada al empezar la vuelta; en una lista de structs o de listas es el elemento
mismo, un lugar, y lo que se le cambia queda en la lista.

```scar
struct Neurona {
    pesos: Vec<f32>
    sesgo: f32
}

fn activar(n: Neurona, x: Vec<f32>) -> f32 {
    return n.pesos.punto(x) + n.sesgo
}

fn main() {
    let notas = [6.5, 5.0, 7.0, 4.2]
    let mut suma = 0.0
    for nota in notas {
        suma = suma + nota
    }
    print("promedio:", suma / to_f64(notas.len()))

    let red: Vec<Neurona> = [Neurona { pesos: [0.5, -0.25], sesgo: 0.1 },
                             Neurona { pesos: [1.0, 1.0], sesgo: 0.0 }]
    let x: Vec<f32> = [2.0, 4.0]
    for n in red {
        n.sesgo = n.sesgo + 0.5
        print(activar(n, x))
    }
    print(red[0].sesgo, red[1].sesgo)
}
```

```
promedio: 5.675
0.6
6.5
0.6 0.5
```

Se recorre lo mismo que se puede indexar: una variable, un campo
(`for w in capa.pesos`), una fila (`for x in m[i]`), un pedazo
(`for x in v[2..5]`) o lo que devuelve una función (`for x in leer()`). `break` y
`continue` funcionan como en cualquier bucle.

**Mientras dura el bucle, la lista no cambia de largo.** Agregarle o sacarle
elementos mientras se la recorre es el error clásico de casi todos los lenguajes
(saltarse un elemento, o leer memoria que ya se soltó); en SCAR es un error del
compilador:

```scar-error
fn main() {
    let mut v = [1, 2, 3]
    for x in v {
        if x == 2 {
            v.push(4)
        }
    }
}
```

```
ERROR DE TIPO: 'v' no puede cambiar de largo mientras se recorre con 'for x in v' (línea 3): acá se le hace .push(). Hazlo después del for, o recorre los índices ('for i in 0..v.len()') (línea 5)
```

Sus elementos sí se pueden cambiar (`v[0] = 9`, `n.sesgo = ...`), y después del
bucle la lista vuelve a ser libre. `x` no se reasigna (`x = 3` es un error): para
escribir los números de una lista, se recorren los índices,
`for i in 0..v.len() { v[i] = ... }`. Por ahora `for x in v` no recorre una lista
de textos (se recorren sus índices, con `get`) ni una lista de una función
genérica (capítulo 13).

### `suma` y `punto`

`v.suma()` suma los elementos de un `Vec` de números, y `a.punto(b)` suma
`a[i] * b[i]` (el *producto punto*, la cuenta de cada neurona de una red):

```scar
fn main() {
    let precios = [1200, 990, 4500]
    let pesos: Vec<f32> = [0.5, -0.25, 0.125]
    let x: Vec<f32> = [1.0, 2.0, 4.0]
    print(precios.suma(), pesos.punto(x))
}
```

```
6690 0.5
```

Con enteros, el resultado es la suma exacta, y un panic si no cabe en el tipo.
Con decimales, `suma` y `punto` no suman de a uno en orden: suman en 16 grupos a
la vez (el elemento `i` va al grupo `i % 16`) y al final juntan los grupos, siempre
de la misma manera. Así el procesador hace muchas sumas a la vez, y en el binario
un producto punto de un millón de `f32` es unas cinco veces más rápido que un loop.
Como ese orden es parte del lenguaje, el resultado es exactamente el mismo con
`scar run` y con `scar build`, en cualquier máquina. Puede diferir en el último
dígito del de un loop que suma en orden, porque al sumar decimales el orden
cambia el redondeo:

```scar
fn main() {
    let mut d: Vec<f64> = vec_new()
    for i in 0..37 {
        d.push(0.1)
    }
    let mut en_orden = 0.0
    for i in 0..d.len() {
        en_orden = en_orden + d[i]
    }
    print(d.suma(), en_orden)
}
```

```
3.7 3.700000000000002
```

`a.punto(b)` con largos distintos es un panic. Por ahora son para un `Vec` de
`i32`, `i64`, `f64` o `f32` (no de un `T` en una función genérica), y el `b` de
`punto` tiene que estar en una variable o en un campo.

### Pedazos: `v[a..b]`, y `acumular`

`v[a..b]` es el pedazo de una lista que va de la posición `a` (incluida) a la `b`
(sin incluir), **sin copiarlo**. Por ahora sirve para sumar o multiplicar una
parte: con `.suma()`, `.punto()` y `.acumular()`. Es justo lo que hace falta para
una matriz guardada fila por fila, donde cada fila es un pedazo:

```scar
fn main() {
    let w: Vec<f32> = [1.0, 2.0, 3.0, 0.5, 0.25, 0.125]
    let x: Vec<f32> = [2.0, 4.0, 8.0]
    for f in 0..2 {
        print("fila", f, ":", w[f * 3..f * 3 + 3].punto(x))
    }
}
```

```
fila 0 : 34.0
fila 1 : 3.0
```

`a.acumular(b, k)` le suma a cada `a[i]` el `b[i]` multiplicado por `k`, en su
lugar (`a` cambia). Es la cuenta de un paso de entrenamiento: los pesos más la
tasa por el gradiente. Funciona sobre la lista entera o sobre un pedazo, y si es
un pedazo lo que cambia es la lista original:

```scar
fn main() {
    let pesos: Vec<f32> = [1.0, 1.0, 1.0, 1.0]
    let gradiente: Vec<f32> = [0.5, -0.5, 1.0, 2.0]
    pesos.acumular(gradiente, -0.1)
    print(pesos)
    pesos[0..2].acumular(gradiente[2..4], 1.0)
    print(pesos)
}
```

```
[0.95, 1.05, 0.9, 0.8]
[1.95, 3.05, 0.9, 0.8]
```

Cada elemento de `acumular` se calcula por su cuenta, así que el binario hace
muchos a la vez y da exactamente lo mismo que `scar run`. Un pedazo fuera de la
lista (o al revés, con `a` mayor que `b`) es un panic, como `v[i]`; `acumular`
pide los dos del mismo largo y del mismo tipo de número.

Con enteros (`i32` o `i64`) sirve para juntar cuentas, por ejemplo dos
histogramas. Cada elemento se calcula exacto, y si el resultado no cabe en el
tipo es un panic que dice en qué posición:

```scar
fn main() {
    let total: Vec<i32> = [0, 0, 0]
    let mañana: Vec<i32> = [3, 0, 1]
    let tarde: Vec<i32> = [1, 2, 0]
    total.acumular(mañana, 1)
    total.acumular(tarde, 1)
    print(total)
    total.acumular(tarde, -1)
    print(total)
}
```

```
[4, 2, 1]
[3, 0, 1]
```

Para dejar toda una lista (o un pedazo) en un mismo valor está `v.llenar(x)`, por
ejemplo para poner en cero un gradiente antes de volver a calcularlo. El largo no
cambia, y el binario lo hace de una vez, sin revisar cada elemento:

```scar
fn main() {
    let gradiente: Vec<f32> = [0.5, -1.0, 2.0, 0.25]
    gradiente.llenar(0.0)
    print(gradiente)
    gradiente[1..3].llenar(9.5)
    print(gradiente)
}
```

```
[0.0, 0.0, 0.0, 0.0]
[0.0, 9.5, 9.5, 0.0]
```

`llenar` es para listas de números o de `bool`. El valor tiene que ser una lectura
simple (un número, una variable, una cuenta): si hay que llamar a una función para
calcularlo, se guarda antes en una variable.

Un pedazo también se le puede pasar a una función. Adentro es una lista como
cualquiera, y lo que la función escribe queda en la lista original:

```scar
fn relu(f: Vec<f32>) {
    for i in 0..f.len() {
        if f[i] < 0.0 {
            f[i] = 0.0
        }
    }
}

fn total(v: Vec<i32>) -> i32 {
    if v.len() <= 2 {
        return v.suma()
    }
    let m = v.len() / 2
    return total(v[0..m]) + total(v[m..v.len()])
}

fn main() {
    let w: Vec<f32> = [1.0, -2.0, 3.0, -4.0, 5.0, -6.0]
    relu(w[3..6])
    print(w)
    print(total([1, 2, 3, 4, 5, 6, 7]))
}
```

```
[1.0, -2.0, 3.0, 0.0, 5.0, 0.0]
28
```

La condición: la función no le puede cambiar el largo (nada de `push` ni `pop`
sobre ese parámetro, ni pasárselo a otra función que lo haga), porque un pedazo
es una ventana a la lista de otro, no una lista propia. Si lo intentas, el
compilador te dice dónde está el `push`. Por lo mismo, en una llamada no puedes
pasar un pedazo de `w` y también `w` a un parámetro donde la función podría
agrandarla.

Y un pedazo se puede guardar en una variable, con `let`. Sigue siendo una
ventana: lo que le escribes queda en la lista original.

```scar
fn main() {
    let w: Vec<f32> = [1.0, -2.0, 3.0, -4.0, 5.0, -6.0]
    for f in 0..2 {
        let fila = w[f * 3..f * 3 + 3]
        if fila[1] < 0.0 {
            fila[1] = 0.0
        }
        print("fila", f, ":", fila, "suma", fila.suma())
    }
    w.push(7.0)
    print(w)
}
```

```
fila 0 : [1.0, 0.0, 3.0] suma 4.0
fila 1 : [-4.0, 5.0, -6.0] suma -5.0
[1.0, 0.0, 3.0, -4.0, 5.0, -6.0, 7.0]
```

Con un pedazo guardado puedes hacer lo mismo que con una lista que no cambia de
largo: `fila[i]`, `fila[i] = x`, `len`, `get`, `suma`, `punto`, `acumular`,
imprimirlo, tomarle otro pedazo (`fila[0..2]`) y pasarlo a una función que no le
cambia el largo. Hay dos reglas, y el compilador las revisa:

- **El pedazo no es una lista propia.** No crece ni se achica (nada de `push` ni
  `pop`), no se guarda en otra lista ni en un struct, y no se manda a una tarea.
- **Mientras usas el pedazo, la lista no cambia de largo.** Desde el `let`
  hasta la última línea que nombra al pedazo, a la lista original no le puedes
  hacer `push` ni `pop`, ni moverla, ni pasarla a una función que lo haga.
  Después de esa última línea, sí: en el ejemplo, `w.push(7.0)` vale porque
  `fila` ya no se usa.

```scar-error
fn main() {
    let v = [1, 2, 3]
    let p = v[0..2]
    v.push(4)
    print(p)
}
```

El error dice qué pedazo sigue en uso y en qué línea se tomó. Si necesitas el
pedazo después de agrandar la lista, tómalo de nuevo (`let p = v[0..2]` otra
vez, después del `push`).

Un pedazo declarado con `let mut` puede pasar a mirar **otro** pedazo: de la
misma lista, de otra, o de sí mismo. Es lo que hace una búsqueda binaria, que
achica su pedazo a la mitad en cada vuelta sin copiar nada:

```scar
fn esta(v: Vec<i32>, x: i32) -> bool {
    let mut p = v[0..v.len()]
    while p.len() > 1 {
        let m = p.len() / 2
        if p[m] > x {
            p = p[0..m]
        } else {
            p = p[m..p.len()]
        }
    }
    return p.len() == 1 and p[0] == x
}

fn main() {
    let orden = [1, 3, 5, 7, 9, 11, 13]
    print(esta(orden, 7), esta(orden, 8))
}
```

```
true false
```

A un pedazo solo se le asigna otro pedazo (`p = w[a..b]`, `p = q`), nunca una
lista propia, porque nadie la soltaría. Y mientras lo usas, **ninguna** de las
listas que miró o puede mirar cambia de largo: el compilador las cuida todas,
desde el `let` hasta la última línea que nombra al pedazo. Las listas que
un pedazo mira tienen que estar declaradas antes que él.

Una función puede **devolver un pedazo de lo que recibe**. No hay nada que
anotar: el compilador mira la función y sabe de qué parámetro es el pedazo, y
en quien la llama el resultado es un pedazo de la lista que se le pasó, con las
mismas reglas.

```scar
fn sin_bordes(v: Vec<f64>) -> Vec<f64> {
    return v[1..v.len() - 1]
}

fn main() {
    let datos = [9.0, 1.0, 2.0, 3.0, 9.0]
    let centro = sin_bordes(datos)
    centro[0] = 5.0
    print(centro, centro.suma())
    print(datos)
    datos.push(4.0)
}
```

```
[5.0, 2.0, 3.0] 10.0
[9.0, 5.0, 2.0, 3.0, 9.0]
```

`centro` mira adentro de `datos`: lo que se le escribe queda en `datos`, y
`datos.push(4.0)` vale recién después de la última línea que usa `centro`. Tres
cosas que el compilador pide:

- Una función devuelve **siempre pedazos o siempre una lista propia**, no a veces
  una cosa y a veces la otra: quien recibe el resultado tiene que saber si le toca
  soltarlo.
- El pedazo es de algo que llegó por un **parámetro**. Un pedazo de una lista
  creada adentro de la función no sirve: esa lista deja de existir al volver.
- El resultado se guarda (`let p = f(v)`), se le asigna a un pedazo `let mut`, se
  recorre (`for x in f(v)`), se devuelve, o se usa directo (`print(f(v))`,
  `f(v).suma()`, `g(f(v))`). Directo vale donde se evalúa una sola vez y antes
  que cualquier otra llamada de la sentencia; a la derecha de un `and`/`or` o en
  la condición de un `while`, primero el `let`.

Un pedazo también se puede **guardar adentro de un struct o de una lista**. Es
la forma de tener una red entera con sus capas mirando un solo `Vec` de pesos,
sin copiar ninguno: lo que una capa escribe queda en ese `Vec`.

```scar
struct Capa {
    w: Vec<f64>
    sesgo: f64
}

fn activar(c: Capa, x: Vec<f64>) -> f64 {
    return c.w.punto(x) + c.sesgo
}

fn bajar(c: Capa, paso: f64) {
    for i in 0..c.w.len() {
        c.w[i] = c.w[i] - paso
    }
}

fn main() {
    let pesos = [0.5, 1.0, 2.0, 4.0, 3.0, 3.0]
    let red: Vec<Capa> = vec_new()
    for k in 0..3 {
        red.push(Capa { w: pesos[k * 2..k * 2 + 2], sesgo: 0.0 })
    }
    for capa in red {
        bajar(capa, 0.5)
        print(activar(capa, [1.0, 1.0]))
    }
    print(pesos)
}
```

```
0.5
5.0
5.0
[0.0, 0.5, 1.5, 3.5, 2.5, 2.5]
```

La variable que guarda un pedazo (`red`, y cada capa adentro) sigue las reglas
del pedazo. Mientras se usa, la lista mirada no cambia de largo:

```scar-error
struct Capa {
    w: Vec<f64>
    sesgo: f64
}

fn main() {
    let pesos = [0.5, 1.0, 2.0, 4.0]
    let capa = Capa { w: pesos[0..2], sesgo: 0.0 }
    pesos.push(9.0)
    print(capa.w)
}
```

```
ERROR DE TIPO: 'pesos' no puede cambiar de largo mientras se usa 'capa', que guarda un pedazo de él (línea 8): acá se le hace .push(). Usa 'capa' solo antes de esta línea (línea 9)
```

Y lo que guarda un pedazo **vive en la función que lo arma**:

- Se presta a funciones que leen o que escriben sus números (`activar`,
  `bajar`), también a las que lo recorren con `for`. No a una que podría
  agrandar algo de adentro o quedarse con él.
- No se manda a una tarea ni por un canal, y no se guarda en algo que llegó por
  un parámetro: el pedazo podría seguir ahí cuando la lista que mira ya no
  exista.
- Se guarda con un literal (`Capa { w: v[a..b] }`), con `lista.push(...)` o
  asignando el campo (`c.w = v[a..b]`), y la lista mirada tiene que estar
  declarada antes que quien guarda el pedazo.
- Una copia con `get` es propia: ya no mira la lista original.

Sí se puede **devolver**, si los pedazos que guarda son de algo que llegó por un
parámetro. Así se escribe una función que arma una capa, o la red entera, sobre
la lista de pesos de quien la llama; el compilador deduce qué guarda lo devuelto,
y quien lo recibe sigue las mismas reglas que si lo hubiera armado ahí:

```scar
struct Capa {
    w: Vec<f64>
    sesgo: f64
}

fn capa(pesos: Vec<f64>, desde: i32, n: i32) -> Capa {
    return Capa { w: pesos[desde..desde + n], sesgo: 0.0 }
}

fn armar(pesos: Vec<f64>, por_capa: i32) -> Vec<Capa> {
    let red: Vec<Capa> = vec_new()
    let mut desde = 0
    while desde + por_capa <= pesos.len() {
        red.push(capa(pesos, desde, por_capa))
        desde = desde + por_capa
    }
    return red
}

fn main() {
    let pesos = [0.5, 1.0, 2.0, 4.0, 3.0, 3.0]
    let red = armar(pesos, 2)
    for c in red {
        c.w[0] = 0.0
    }
    print(red.len(), pesos)
    print(capa(pesos, 4, 2).w.suma())
}
```

```
3 [0.0, 1.0, 0.0, 4.0, 0.0, 3.0]
3.0
```

Se devuelve entero (`return c`, `return Capa { ... }`), no una parte (`return
c.w` sacaría el pedazo como si fuera una lista propia), y no un pedazo de una
lista creada adentro de la función.

Un pedazo también puede ser de una lista de structs, de textos o de listas. Es
la misma ventana: `capas[1..3]` son esas capas de la lista original, no copias.

```scar
struct Capa {
    pesos: Vec<f64>
    usos: i32
}

fn marcar(cs: Vec<Capa>) {
    for i in 0..cs.len() {
        cs[i].usos = cs[i].usos + 1
    }
}

fn main() {
    let red: Vec<Capa> = []
    for i in 0..4 {
        red.push(Capa { pesos: [1.0, 2.0], usos: 0 })
    }
    marcar(red[1..3])
    let ultimas = red[2..4]
    ultimas[0].pesos.push(3.0)
    ultimas.set(1, Capa { pesos: [], usos: 9 })
    for i in 0..red.len() {
        print(red[i].usos, red[i].pesos)
    }
}
```

```
0 [1.0, 2.0]
1 [1.0, 2.0]
1 [1.0, 2.0, 3.0]
9 []
```

Con una lista de listas, `m[1..3]` son dos filas de la matriz, y a cada fila le
puedes tomar a su vez un pedazo (`filas[0][0..2]`). Acá hay una regla más, que
sale de las dos de arriba: un pedazo guardado es **otro nombre** de un trozo de
la lista. Si `filas` es `m[1..3]`, entonces `filas[0]` es la fila `m[1]`, y el
compilador lo sabe. Mientras usas un pedazo de esa fila, la fila no cambia de
largo ni se cambia por otra, la nombres como la nombres:

```scar-error
fn main() {
    let m: Vec<Vec<f64>> = [[1.0, 2.0], [3.0]]
    let filas = m[0..2]
    let trozo = m[0][0..1]
    filas[0].push(9.0)
    print(trozo)
}
```

Un pedazo puede ser de listas de números, `bool`, textos, structs comunes u
otras listas de esas cosas.

## 6.3 Vaciar una lista con `while let`

`v.pop()` saca el último elemento y lo devuelve en un `Some`; cuando la lista
queda vacía, da `None`. Con `while let` eso es un loop que termina solo:

```scar
fn main() {
    let mut pila = ["primero", "segundo", "tercero"]
    while let Some(x) = pila.pop() {
        print("saco", x)
    }
    print("quedan", pila.len())
}
```

```
saco tercero
saco segundo
saco primero
quedan 0
```

## 6.4 Listas de structs

Un `Vec` puede guardar cualquier tipo, también structs:

```scar
struct Tarea {
    titulo: str
    hecha: bool
}

fn main() {
    let lista: Vec<Tarea> = vec_new()
    lista.push(Tarea { titulo: "comprar pan", hecha: true })
    lista.push(Tarea { titulo: "llamar al banco", hecha: false })
    for t in lista {
        let marca = if t.hecha { "[x]" } else { "[ ]" }
        print(marca, t.titulo)
    }
}
```

```
[x] comprar pan
[ ] llamar al banco
```

Meter un struct en una lista con `push` lo **mueve** adentro: la variable de
antes deja de servir, porque ahora el dueño es la lista. El capítulo 8 explica
por qué.

## 6.5 `Map<K,V>`: un diccionario

Un `Map` guarda pares clave → valor. Se crea con `map_new()`, con los tipos
escritos en el `let`:

```scar
fn main() {
    let mut stock: Map<str, i32> = map_new()
    stock.set("manzana", 10)
    stock.set("banana", 5)
    stock.set("pera", 8)
    print(stock, stock.len())
    print(stock.get("banana"), stock.get("kiwi"))
}
```

```
{"manzana": 10, "banana": 5, "pera": 8} 3
Some(5) None
```

| Método         | Qué hace                                                       |
|----------------|----------------------------------------------------------------|
| `m.set(k, v)`  | guarda `v` en la clave `k` (si ya estaba, la reemplaza)        |
| `m.get(k)`     | el valor de `k`, como `Option`                                 |
| `m.remove(k)`  | saca `k` y devuelve su valor, como `Option`                    |
| `m.len()`      | cuántas claves hay                                             |

Las claves pueden ser `i32`, `i64`, `f64`, `f32`, `str` o `bool`. Un `Map` recuerda el
orden en que se agregaron las claves, y `print` lo muestra en ese orden.

```scar
fn main() {
    let mut votos: Map<str, i32> = map_new()
    let papeletas = ["sí", "no", "sí", "sí", "no"]
    for i in 0..papeletas.len() {
        match papeletas.get(i) {
            Some(p) => {
                votos.set(p, votos.get(p).unwrap_or(0) + 1)
            }
            None => {}
        }
    }
    print(votos)
    print("quitado:", votos.remove("no"), "quedan", votos.len())
}
```

```
{"sí": 3, "no": 2}
quitado: Some(2) quedan 1
```

Para recorrer todas las claves de un `Map`, ordenar listas y otras
colecciones (pila, cola, conjunto), está la librería `colecciones` (capítulo
10).

## 6.6 Ejercicios

1. Escribe `fn maximo(v: Vec<i32>) -> Option<i32>` que dé `None` para una
   lista vacía.
2. Invierte una lista usando `pop` y `push` sobre otra.
3. Cuenta cuántas veces aparece cada letra en `["a", "b", "a", "c", "a"]`
   con un `Map<str, i32>`.
4. Haz una lista de compras con structs `Item { nombre: str  precio: i64 }` e
   imprime el total.

El programa de este capítulo está en `ejemplos/06_vec_y_map.scar`.
