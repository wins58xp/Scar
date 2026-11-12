# 1. Instalar y primer programa

SCAR es un lenguaje de programación con una idea central: **una tarea
concurrente y una región de memoria son la misma cosa.** Cuando una tarea
termina, todo lo que creó se libera solo, sin recolector de basura y sin que
tengas que escribir código para liberar memoria. Este libro te lleva desde el
primer programa hasta tareas que trabajan en paralelo, interfaces gráficas y
redes neuronales, siempre con programas que puedes copiar y correr.

No hace falta saber otro lenguaje, aunque si conoces Rust, Go o Python vas a
reconocer varias ideas.

## 1.1 Instalar

SCAR necesita Python 3.12 o más nuevo, y un compilador de C (gcc o clang) para
compilar programas a binario. En la carpeta de SCAR:

```
./instalar.sh
```

`instalar.sh` revisa que esté todo, dice qué falta si algo falta, y deja el
comando `scar` disponible desde cualquier carpeta. No instala nada del sistema
por su cuenta ni pide contraseña. Para comprobarlo:

```
scar --version
```

```
scar 0.2.0
```

Las interfaces gráficas (capítulo 15) necesitan además SDL2, y las conexiones
HTTPS necesitan libcurl. Si las quieres, instálalas y vuelve a correr
`./instalar.sh`; en Debian o Ubuntu:

```
sudo apt install libsdl2-dev libcurl4-openssl-dev
```

## 1.2 Hola, SCAR

Guarda esto en un archivo `hola.scar`:

```scar
fn main() {
    print("Hola, SCAR")
}
```

Y córrelo:

```
scar run hola.scar
```

```
Hola, SCAR
```

Las tres piezas:

- `fn` declara una función. `main` es la función por la que empieza todo
  programa.
- `()` dice que `main` no recibe nada.
- `print(...)` imprime sus argumentos en una línea, separados por un espacio.

```scar
fn main() {
    print("suma:", 2 + 2)
    print("varios valores:", 1, 2, 3)
}
```

```
suma: 4
varios valores: 1 2 3
```

**Cada sentencia va en su propia línea, sin `;`.** El fin de la línea termina
la sentencia. Si por costumbre escribes un `;`, el compilador te dice que lo
saques. Así todo el código SCAR se escribe de una sola manera.

## 1.3 Comentarios

Un comentario empieza con `#` y llega hasta el fin de la línea:

```scar
# Esto es un comentario.
fn main() {
    print("el programa empieza acá")   # esto también
}
```

## 1.4 Dos maneras de correr un programa

SCAR tiene un **intérprete** y un **compilador**. Los dos corren todo el
lenguaje y dan la misma salida.

- `scar run hola.scar` usa el intérprete: corre al instante, sin pasos
  intermedios. Es lo que vas a usar casi siempre mientras aprendes.
- `scar build hola.scar` traduce el programa a C y lo compila a un binario
  nativo, que corre mucho más rápido (capítulo 12):

```
scar build hola.scar -o hola
./hola
```

```
Hola, SCAR
```

Y un tercer comando, `scar check`, solo revisa el programa sin correrlo:

```
scar check hola.scar
```

```
hola.scar: sin errores de tipo
```

## 1.5 El primer error, a propósito

SCAR revisa los tipos de todo el programa **antes** de correr una sola línea.
Prueba esto:

```scar-error
fn main() {
    print("esto nunca se imprime")
    let n: i32 = "esto no es un número"
    print(n)
}
```

```
hola.scar: ERROR DE TIPO: 'n': se anotó i32 pero el valor es de tipo str (línea 3)
    2 |     print("esto nunca se imprime")
  > 3 |     let n: i32 = "esto no es un número"
            ^
    4 |     print(n)
----- 1 error(es) de tipo en hola.scar. No se ejecuta. -----
```

El primer `print` no llega a imprimirse: el programa no se ejecuta. Es un
patrón que vas a ver en todo el libro: SCAR prefiere avisar temprano, con la
línea exacta, antes que dejar que un error aparezca más tarde y en otro lado.

## 1.6 Argumentos y código de salida

Un programa recibe lo que le escribes en la línea de comandos con `arg(i)`,
contando desde 0. `arg(i)` puede no tener nada (si no le pasaste tantos), así
que no devuelve un texto sino un `Option<str>`: `Some(texto)` o `None`. Con
`match` miras cuál de los dos es (los capítulos 3 y 5 lo explican en detalle):

```scar
fn main() -> i32 {
    match arg(0) {
        Some(nombre) => {
            print("Hola,", nombre)
            return 0
        }
        None => {
            print("falta el nombre")
            return 2
        }
    }
}
```

Con `scar run`, lo que va después de `--` es para el programa; el binario lo
recibe directo:

```
scar run saludo.scar -- Ana
scar build saludo.scar -o saludo
./saludo Ana
```

```
Hola, Ana
```

`main` puede no devolver nada (el programa termina con código 0) o devolver un
`i32`, que es el **código de salida**: lo que ve la terminal o un script para
saber si el programa terminó bien. Por convención, 0 es "todo bien" y
cualquier otro número, "algo falló".

## 1.7 Ejercicios

1. Haz que `hola.scar` salude con tu nombre usando un segundo argumento de
   `print`.
2. Escribe un programa que imprima el resultado de `+`, `-` y `*` sobre dos
   números, en tres líneas.
3. Agrega a propósito un `;` al final de una línea y lee lo que dice el
   compilador.
4. Corre `saludo.scar` sin argumentos y mira el código de salida con
   `echo $?`.

El programa completo de este capítulo está en `ejemplos/01_hola.scar`.
