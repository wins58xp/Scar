# 7. Texto

Un `str` es texto en UTF-8: puede tener tildes, eñes, emojis o cualquier
carácter. Todo lo que cuenta posiciones en SCAR cuenta **caracteres**, no
bytes.

## 7.1 Escribir textos

Un texto va entre comillas dobles. Adentro, `\"` es una comilla, `\\` una barra
invertida, `\n` un salto de línea y `\t` un tabulador:

```scar
fn main() {
    print("dijo \"hola\" y se fue")
    print("C:\\datos\\archivo.txt")
    print("primera\nsegunda")
}
```

```
dijo "hola" y se fue
C:\datos\archivo.txt
primera
segunda
```

## 7.2 Juntar textos

`+` junta dos textos. Para armar uno por partes, una variable `mut` que va
creciendo:

```scar
fn saludo(nombre: str) -> str {
    return "hola, " + nombre + "!"
}

fn main() {
    print(saludo("mundo"))
    let mut barra = "["
    for i in 0..5 {
        barra = barra + "#"
    }
    print(barra + "]")
}
```

```
hola, mundo!
[#####]
```

`+` solo junta textos con textos. Para meter un número (o un `bool`) está
`a_texto(x)`, que da el mismo texto que imprimiría `print`:

```scar
fn main() {
    let n = 42
    let precio = 19.5
    print("n = " + a_texto(n) + ", precio = " + a_texto(precio) + ", listo: " + a_texto(true))
}
```

```
n = 42, precio = 19.5, listo: true
```

Al revés, `int(s)` lee un número entero de un texto. Como el texto puede no
ser un número, devuelve un `Result` (capítulo 5); `int64(s)` es lo mismo para
`i64`:

```scar
fn main() {
    print(int("17").unwrap_or(0), int(" -4 ").unwrap_or(0), int("hola").is_err())
}
```

```
17 -4 true
```

## 7.3 Largo y caracteres

`len(s)` (o `s.len()`) es la cantidad de caracteres, y `s[i]` es el carácter
de la posición `i`, contando desde 0, como un texto de un carácter:

```scar
fn main() {
    let s = "año"
    print(len(s), s[0], s[1], s[2])
    for i in 0..len(s) {
        print(i, s[i])
    }
}
```

```
3 a ñ o
0 a
1 ñ
2 o
```

Una posición que no existe (negativa, o igual o mayor que el largo) es un
panic:

```scar-panic
fn main() {
    let s = "hola"
    print(s[4])
}
```

`ord(c)` da el código Unicode de un carácter, y `chr(n)` el carácter de un
código:

```scar
fn main() {
    print(ord("A"), ord("ñ"), chr(8364), chr(65))
}
```

```
65 241 € A
```

## 7.4 Preguntarle cosas a un texto

```scar
fn main() {
    let s = "hola mundo"
    print(s.contains("mundo"), s.starts_with("hola"), s.ends_with("hola"))
    print(s == "hola mundo", s != "chao")
}
```

```
true true false
true true
```

`==` y `!=` comparan textos. Para ordenar textos alfabéticamente está
`colecciones.ordenar_textos` (capítulo 10).

## 7.5 La librería `texto`

Para dividir, buscar, reemplazar, pasar a mayúsculas, recortar espacios o
mostrar un número con decimales fijos, está la librería `texto`. Se trae con
`use "texto"` al principio del archivo, y sus funciones se llaman con
`texto.` delante (el capítulo 10 explica los módulos):

```scar
use "texto"

fn main() {
    let linea = "  manzana,pera,uva  "
    let frutas = texto.dividir(texto.recortar(linea), ",")
    print(frutas, frutas.len())
    print(texto.mayusculas("ñandú"), texto.reemplazar("a-b-c", "-", "+"))
    print(texto.buscar("hola mundo", "mundo"), texto.decimales(3.14159, 2))
    print(texto.unir(["a", "b", "c"], " / "))
}
```

```
["manzana", "pera", "uva"] 3
ÑANDÚ a+b+c
5 3.14
a / b / c
```

La lista completa está en el apéndice B.

## 7.6 Ejercicios

1. Escribe `fn invertir(s: str) -> str` usando `s[i]` y `+`.
2. Cuenta cuántas vocales tiene un texto.
3. Escribe `fn es_palindromo(s: str) -> bool` (prueba con `"reconocer"`).
4. Lee una lista de números separados por coma (`"4,8,15,16,23,42"`) con
   `texto.dividir` e `int`, y suma los que se puedan leer.

El programa de este capítulo está en `ejemplos/07_texto.scar`.
