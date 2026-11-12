# 10. Módulos y la librería estándar

## 10.1 Partir un programa en archivos

Cuando un programa crece, conviene repartirlo en varios archivos. Un archivo
trae a otro con `use "nombre"` al principio, y usa lo que declara con el
nombre del módulo delante.

`geo.scar`:

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

fn _cuadrado(x: f64) -> f64 {
    return x * x
}
```

`programa.scar`, en la misma carpeta:

```scar-nocheck
use "geo"

fn main() {
    let a = geo.Punto { x: 0.0, y: 0.0 }
    let b = geo.Punto { x: 3.0, y: 4.0 }
    print(geo.distancia(a, b))
}
```

```
scar run programa.scar
```

```
5.0
```

(Este bloque necesita `geo.scar` al lado, por eso el libro no lo prueba solo;
el ejemplo completo está en `ejemplos/10_modulos/`.)

Las reglas:

- `use "geo"` busca `geo.scar` **al lado del archivo** que lo pide, y si no está,
  en la librería estándar de SCAR. `use "util/geo"` busca en una subcarpeta;
  el nombre del módulo es la última parte (`geo`).
- Todo lo que declara un módulo se ve desde afuera, **salvo lo que empieza con
  `_`**: `geo._cuadrado` es un error. Así un módulo tiene sus funciones
  internas.
- Un módulo ve lo suyo y lo de los módulos que él trae, nunca lo de quien lo
  usa.
- Un módulo no tiene `main`: es una librería, no un programa.
- Cada módulo se carga una vez, aunque lo pidan varios. Si `a` trae a `b` y
  `b` trae a `a`, es un error que muestra el ciclo.
- Si tu programa se llama igual que un módulo de la librería estándar (por
  ejemplo `texto.scar` con `use "texto"`), se encontraría a sí mismo: el
  compilador te pide cambiarle el nombre.

## 10.2 La librería estándar

SCAR trae en `lib/` una librería estándar escrita en SCAR mismo. Se usa con
`use` como cualquier módulo:

| Módulo        | Para qué sirve |
|---------------|----------------|
| `texto`       | dividir, unir, buscar, reemplazar, recortar, mayúsculas, números con decimales |
| `colecciones` | pila, cola, mapas que se recorren, conjuntos, ordenar listas |
| `mate`        | vectores 2D/3D/4D, matrices 4×4, cuaterniones, números al azar |
| `algebra`     | matrices de cualquier tamaño: producto, inversa, sistemas de ecuaciones |
| `estadistica` | media, mediana, varianza, percentiles, correlación, regresión |
| `senal`       | FFT, filtros, ventanas, espectros |
| `fecha`       | fechas, horas, zonas horarias, diferencias entre fechas |
| `json`        | leer y escribir JSON |
| `csv`         | leer y escribir CSV |
| `config`      | archivos de configuración (INI, TOML y "clave valor") |
| `codigos`     | hexadecimal, base64, SHA-256, SHA-1, MD5, HMAC, UUID |
| `patron`      | expresiones regulares |
| `zlib`        | comprimir y descomprimir (DEFLATE) |
| `web`         | URLs y un cliente HTTP |
| `https`       | lo mismo que `web`, también para `https://` (necesita libcurl) |
| `grafos`      | grafos con pesos: recorridos, caminos más cortos, componentes |
| `lienzo`      | un buffer de píxeles para dibujar líneas, rectángulos, círculos, texto |
| `imagen`      | guardar y leer BMP y PNG |
| `colores`     | colores y espacios de color, paletas, mapas de color |
| `grafico`     | gráficos de líneas, barras e histogramas sobre un lienzo |
| `motor3d`     | 3D sin GPU sobre un lienzo |
| `audio`       | ondas, mezcla y archivos WAV |
| `fisica`      | cuerpos rígidos 2D para juegos |
| `animacion`   | curvas de suavizado para animar valores |
| `juego`       | bucle de juego, mapas de baldosas, cámara 2D |
| `neuronalgames` | redes neuronales chicas para juegos |
| `ansi`        | colores y estilos en la terminal |
| `prueba`      | un mini framework de pruebas |
| `gui`, `pantalla`, `parlante`, `tablero`, `buffer`, `editor` | interfaces gráficas y sonido (capítulo 15; necesitan SDL2) |

El apéndice B describe cada una con sus funciones.

## 10.3 Un vistazo: `colecciones`

`colecciones` completa lo que `Vec` y `Map` no traen: mapas que se recorren en
orden, pilas, colas y ordenar.

```scar
use "colecciones"

fn main() {
    let edades = colecciones.mapa(0)          # claves str, valores i32
    colecciones.poner(edades, "Ana", 31)
    colecciones.poner(edades, "Luis", 25)
    colecciones.poner(edades, "Eva", 28)
    for i in 0..colecciones.largo(edades) {
        print(colecciones.clave(edades, i), colecciones.valor(edades, i).unwrap_or(0))
    }
    print(colecciones.ordenar([5, 3, 9, 1]))
    print(colecciones.ordenar_textos(["pera", "ajo", "manzana"]))
}
```

```
Ana 31
Luis 25
Eva 28
[1, 3, 5, 9]
["ajo", "manzana", "pera"]
```

## 10.4 Probar tu código: `prueba`

`prueba` sirve para que un programa se pruebe a sí mismo. Cada afirmación
cuenta; si falla, dice qué se esperaba y qué salió, y sigue con las demás.
`terminar` imprime el resumen y da el código de salida (0 si todo pasó):

```scar
use "prueba"

fn doble(n: i32) -> i32 {
    return n * 2
}

fn main() -> i32 {
    let t = prueba.nueva("doble")
    prueba.afirmar_igual_i32(t, doble(2), 4, "doble de 2")
    prueba.afirmar_igual_i32(t, doble(-3), -6, "doble de un negativo")
    prueba.afirmar_cerca(t, sqrt(2.0) * sqrt(2.0), 2.0, 1e-12, "raíz al cuadrado")
    return prueba.terminar(t)
}
```

```
prueba doble: 3 pruebas, todas pasaron
```

## 10.5 Ejercicios

1. Pasa las funciones del ejemplo del capítulo 4 (`Producto`, `vender`) a un
   módulo `tienda.scar` y úsalo desde otro archivo.
2. Agrega a tu módulo una función que empiece con `_` y comprueba que no se
   puede llamar desde afuera.
3. Escribe pruebas con `prueba` para la función `es_primo` del capítulo 4.
4. Usa `estadistica` para calcular la media y la mediana de una lista de notas.

El ejemplo de este capítulo está en `ejemplos/10_modulos/`.
