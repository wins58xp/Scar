# 13. Genéricos y funciones como valor

## 13.1 Structs genéricos

Un struct puede tener un **parámetro de tipo**, `T`, que se decide al crearlo:

```scar
struct Caja<T> {
    valor: T
}

struct Par<T> {
    a: T
    b: T
}

fn main() {
    let numero = Caja { valor: 42 }
    let texto = Caja { valor: "hola" }
    let par = Par { a: 1.5, b: 2.5 }
    print(numero.valor, texto.valor, par.a + par.b)
}
```

```
42 hola 4.0
```

No se escribe `Caja<i32>`: SCAR deduce `T` de los valores. `numero` es una
`Caja<i32>` y `texto` una `Caja<str>`, y no se mezclan. En `Par<T>`, los dos
campos comparten `T`, así que `Par { a: 1, b: "no" }` es un error.

`T` puede ir dentro de otro tipo, como `Vec<T>`:

```scar
struct Pila<T> {
    items: Vec<T>
}

fn main() {
    let p = Pila { items: [10, 20] }
    p.items.push(30)
    print(p.items, p.items.len())
}
```

```
[10, 20, 30] 3
```

## 13.2 Funciones genéricas

Una función también puede tener parámetros de tipo. `T` se deduce de los
argumentos de cada llamada:

```scar
fn ultimo_o<T>(v: Vec<T>, si_no: T) -> T {
    match v.pop() {
        Some(x) => {
            return x
        }
        None => {
            return si_no
        }
    }
}

fn main() {
    print(ultimo_o([1, 2, 3], 0))
    print(ultimo_o(["a", "b"], "nada"))
    let vacia: Vec<f64> = vec_new()
    print(ultimo_o(vacia, 9.5))
}
```

```
3
b
9.5
```

Al compilar, cada combinación de tipos con que se llama la función genera su
propia versión en C (una para `i32`, otra para `str`...), así que un genérico
no cuesta nada en velocidad.

Sin más información, adentro de la función `T` es **opaco**: se puede recibir,
guardar y devolver, pero no sumar ni comparar con `<`, porque no se sabe qué
es.

## 13.3 `T: Numeric`

Para hacer cuentas con un `T`, se le pone el *bound* `Numeric`: entonces `T`
solo puede ser `i32`, `i64` o `f64`, y valen `+ - * /` y `< > <= >=`:

```scar
fn suma<T: Numeric>(v: Vec<T>, cero: T) -> T {
    let mut total = cero
    for i in 0..v.len() {
        total = total + v.get(i).unwrap_or(cero)
    }
    return total
}

fn mayor<T: Numeric>(a: T, b: T) -> T {
    if a > b {
        return a
    }
    return b
}

fn main() {
    print(suma([1, 2, 3], 0), suma([0.5, 0.25], 0.0))
    print(mayor(3, 8), mayor(2.5, -1.0))
}
```

```
6 0.75
8 2.5
```

Llamar `suma(["a"], "")` es un error: `str` no es `Numeric`.

## 13.4 Funciones como valor

Una función se puede guardar en una variable, pasar a otra función o poner en
un campo, como cualquier valor. Su tipo se escribe `fn(parámetros) -> retorno`,
y el nombre de una función sin paréntesis es su valor:

```scar
fn doble(x: i32) -> i32 {
    return x * 2
}

fn cuadrado(x: i32) -> i32 {
    return x * x
}

fn aplicar_a_todos(v: Vec<i32>, f: fn(i32) -> i32) -> Vec<i32> {
    let r: Vec<i32> = vec_new()
    for i in 0..v.len() {
        r.push(f(v.get(i).unwrap_or(0)))
    }
    return r
}

fn main() {
    print(aplicar_a_todos([1, 2, 3], doble))
    print(aplicar_a_todos([1, 2, 3], cuadrado))
    let f = cuadrado
    print(f(9))
}
```

```
[2, 4, 6]
[1, 4, 9]
81
```

Así se escriben las funciones que ordenan por un criterio, los botones de una
interfaz (capítulo 15) o los pasos de un algoritmo que se elige al correr.

Dos reglas:

- **Sin captura.** Solo valen funciones declaradas con `fn` en el nivel del
  archivo: no hay *closures*, así que una función no se lleva variables del
  lugar donde se escribió. Lo que necesite, lo recibe por parámetro.
- **Un contrato fijo.** Quien llama a una función guardada no sabe cuál es,
  así que el tipo `fn(...)` fija las reglas para todas: un struct que recibe se
  presta, y lo que devuelve es nuevo. Una función que no cumple eso (por
  ejemplo, una que devuelve el mismo struct que recibe) no se puede usar como
  valor, y el compilador lo dice.

## 13.5 Lo que todavía no se puede

- Un `enum` genérico (`enum Opcion<T>`).
- Un struct genérico con un `Vec` de **otro** struct genérico adentro
  (`struct Cinta<T> { nodos: Vec<Nodo<T>> }`).
- Bounds distintos de `Numeric`.

## 13.6 Ejercicios

1. Escribe `fn maximo<T: Numeric>(v: Vec<T>, si_vacio: T) -> T`.
2. Escribe `fn filtrar(v: Vec<i32>, f: fn(i32) -> bool) -> Vec<i32>` y úsala
   para quedarte con los pares.
3. Define `struct Rango<T: Numeric> { desde: T  hasta: T }` y una función que
   diga si un valor está adentro.
4. Usa `colecciones.ordenar_por` (capítulo 10) para ordenar una lista de
   structs por uno de sus campos.

El programa de este capítulo está en `ejemplos/13_genericos.scar`.
