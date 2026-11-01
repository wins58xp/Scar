# 12. Compilar a binario nativo

Hasta ahora casi todo lo corriste con `scar run`, el intérprete. Para un
programa terminado, o uno que tiene que ser rápido, está `scar build`: traduce
el programa a C y lo compila a un binario nativo de tu sistema.

## 12.1 `scar build`

```
scar build primos.scar -o primos
./primos
```

`build` hace, en orden:

1. Junta el programa con sus módulos (capítulo 10).
2. Revisa los tipos con el **mismo** verificador que usa `scar run`. Si hay un
   error, para ahí: no se genera ni una línea de C.
3. Genera el C del programa y le pide al compilador de C que lo compile.

El `.c` queda al lado del binario (`primos.c`), por si quieres mirarlo. Sin
`-o`, el binario se llama como el archivo, sin `.scar`.

## 12.2 Lo mismo, mucho más rápido

El intérprete y el binario corren **el mismo lenguaje** y dan **la misma
salida**, carácter por carácter: los mismos números (también los decimales de
un `f64`), los mismos panics, el mismo código de salida. Lo que cambia es la
velocidad:

```scar-check
fn fib(n: i32) -> i32 {
    if n < 2 {
        return n
    }
    return fib(n - 1) + fib(n - 2)
}

fn main() {
    let t0 = now()
    print("fib(27) =", fib(27))
    print("tardó", to_i32((now() - t0) * 1000.0), "ms")
}
```

Con `scar run`, este programa tarda unos segundos; compilado, menos de un
milisegundo. En cálculos numéricos el binario anda a la par de un programa
escrito en C a mano.

Cada `task` del binario es un hilo de verdad del sistema, con la misma
cancelación y los mismos límites de tiempo que en el intérprete.

## 12.3 Cómo se sabe que los dos dan lo mismo

No se confía en que "debería": se mide. Mientras se desarrolla SCAR, cada
programa de prueba (cientos) se corre en los dos y se compara su salida línea
por línea; además se compila con AddressSanitizer, UndefinedBehaviorSanitizer
y LeakSanitizer (cero errores y cero bytes perdidos), y los que usan tareas,
con ThreadSanitizer. Un generador de programas al azar produce miles de
programas más, los corre en los dos y avisa si difieren en un solo carácter.
Los ejemplos de este libro pasan por lo mismo.

## 12.4 Ajustes

`scar build` elige solo:

- Si hay `clang`, lo usa con `-O3 -flto -march=native` (el binario más rápido
  para *tu* procesador); si no, `cc -O2`.
- Siempre con las defensas de siempre de un compilador de C (canario de pila,
  `_FORTIFY_SOURCE`, binario PIE).

Con variables de entorno se puede cambiar:

| Variable             | Qué hace |
|----------------------|----------|
| `SCAR_CC=gcc`        | usa ese compilador de C |
| `SCAR_CC_NATIVE=0`   | sin `-march=native`: el binario corre en otras máquinas con el mismo sistema |
| `SCAR_CC_HARDEN=0`   | sin las defensas (un poco más rápido; `max` las sube) |
| `SCAR_JOIN_TIMEOUT=n`| cuántos segundos espera un `join` antes de dar un panic (8 por omisión) |

```
SCAR_CC_NATIVE=0 scar build primos.scar -o primos
```

## 12.5 Si falta algo

Sin compilador de C, `build` lo dice y deja el C hecho:

```
----- ERROR DE COMPILACIÓN: no hay compilador de C ('cc' no está en el PATH): instala gcc (sudo apt install gcc) o clang. El C generado quedó en primos.c -----
```

Si el programa usa una librería del sistema que no está (por ejemplo SDL2 para
la interfaz gráfica), el mensaje dice cuál y cómo instalarla.

## 12.6 Ejercicios

1. Compila el ejemplo del capítulo 9 (`ejemplos/09_tareas.scar`) y compara su
   salida con la de `scar run`.
2. Mide con `now()` cuánto tarda contar los primos menores que un millón en
   el intérprete y en el binario.
3. Abre el `.c` que deja `build` y busca tu función `main`.

El programa de este capítulo está en `ejemplos/12_compilar.scar`.
