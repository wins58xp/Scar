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
| `v.get(i)`       | el elemento `i` (desde 0), como `Option`: `None` si no existe   |
| `v.pop()`        | saca el último, como `Option`: `None` si está vacío             |
| `v.set(i, x)`    | pone `x` en el lugar `i`                                        |
| `v.replace(i, x)`| pone `x` en el lugar `i` y devuelve el que estaba               |

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
    for i in 0..lista.len() {
        match lista.get(i) {
            Some(t) => {
                let marca = if t.hecha { "[x]" } else { "[ ]" }
                print(marca, t.titulo)
            }
            None => {}
        }
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

Las claves pueden ser `i32`, `i64`, `f64`, `str` o `bool`. Un `Map` recuerda el
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
