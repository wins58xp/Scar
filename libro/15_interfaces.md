# 15. Interfaces gráficas con `gui`

La librería `gui` abre una ventana con botones, campos de texto, listas y
gráficos. Tú dices **qué** hay en la ventana; ella lo acomoda, lo dibuja y te
cuenta qué hizo la persona. No hay coordenadas ni callbacks.

Necesita SDL2. Si no lo tienes, instálalo y vuelve a correr `./instalar.sh`
(capítulo 1):

```
sudo apt install libsdl2-dev
./instalar.sh
```

## 15.1 Un primer programa

```scar-check
use "gui"

fn main() {
    let ui = gui.ventana("Contador", 360, 200)
    let mut n = 0
    while gui.abierta(ui) {
        gui.titulo(ui, "Contador")
        gui.texto(ui, "Vas en " + a_texto(n))
        if gui.boton(ui, "Sumar uno") {
            n = n + 1
        }
    }
}
```

- `gui.ventana(título, ancho, alto)` abre la ventana y devuelve `ui`, el estado
  de la interfaz, que se le pasa a cada pieza.
- `while gui.abierta(ui)` es el loop de la interfaz: **cada vuelta es un
  cuadro**. Muestra el cuadro anterior, lee lo que pasó (clics, teclas) y
  empieza uno nuevo. Cuando la persona cierra la ventana, da `false`.
- Cada pieza va debajo de la anterior.
- `gui.boton` contesta en el momento, con un `bool`: `true` en el cuadro en que
  se le hizo clic. Por eso el contador vive en una variable normal del
  programa.

## 15.2 Las piezas

| Pieza | Qué hace |
|---|---|
| `gui.titulo(ui, s)`, `gui.subtitulo(ui, s)` | texto grande o mediano |
| `gui.texto(ui, s)`, `gui.texto_tenue(ui, s)` | texto normal, o chico y gris |
| `gui.parrafo(ui, s)` | un texto largo, partido en líneas para que quepa |
| `gui.etiqueta(ui, s, color)` | un texto sobre un rectángulo de color |
| `gui.boton(ui, s) -> bool` | `true` en el cuadro del clic |
| `gui.casilla(ui, s, marcada) -> bool` | una casilla; devuelve si queda marcada |
| `gui.campo(ui, etiqueta, valor) -> str` | un campo de texto |
| `gui.deslizador(ui, etiqueta, valor, min, max) -> f64` | una perilla que se arrastra |
| `gui.opciones(ui, "Rojo\|Verde\|Azul", elegida) -> i32` | una de varias |
| `gui.pestanas(ui, "Uno\|Dos", elegida) -> i32` | una barra de pestañas |
| `gui.lista(ui, lista, elegida, filas) -> i32` | una lista larga con rueda y barra |
| `gui.tabla(ui, tabla) -> i32` | filas y columnas alineadas |
| `gui.barras(ui, serie, alto)`, `gui.lineas(ui, serie, alto)` | gráficos |
| `gui.progreso(ui, fraccion)` | una barra de `0.0` a `1.0` |
| `gui.separador(ui)`, `gui.espacio(ui, px)` | una línea, un hueco |
| `gui.lienzo(ui, alto)` | un rectángulo para dibujar a mano (15.6) |

Las piezas que cambian un valor siguen la misma forma: **reciben el valor
actual y devuelven el nuevo**, y el programa lo guarda. El valor es del
programa, así que se puede cambiar desde otro lado (un botón "Reiniciar") y la
pieza lo muestra en el cuadro siguiente:

```scar-check
use "gui"

fn main() {
    let ui = gui.ventana("Datos", 420, 320)
    let mut nombre = ""
    let mut avisar = false
    let mut volumen = 0.5
    while gui.abierta(ui) {
        nombre = gui.campo(ui, "Nombre", nombre)
        avisar = gui.casilla(ui, "Avisarme por correo", avisar)
        volumen = gui.deslizador(ui, "Volumen", volumen, 0.0, 1.0)
        if gui.boton(ui, "Reiniciar") {
            nombre = ""
            volumen = 0.5
        }
        gui.texto_tenue(ui, "Hola, " + nombre)
    }
}
```

## 15.3 Lado a lado: filas y columnas

Lo que va entre `gui.fila` y `gui.fin_fila` se pone de izquierda a derecha.
Para grupos de piezas lado a lado (una lista a la izquierda, el detalle a la
derecha) están las columnas:

```scar-check
use "gui"

fn main() {
    let ui = gui.ventana("Lado a lado", 640, 360)
    let ciudades = gui.lista_nueva()
    gui.lista_agregar(ciudades, "Arica")
    gui.lista_agregar(ciudades, "Santiago")
    gui.lista_agregar(ciudades, "Punta Arenas")
    let mut elegida = -1
    while gui.abierta(ui) {
        gui.fila(ui)
        if gui.boton(ui, "Guardar") {
            print("guardado")
        }
        if gui.boton(ui, "Salir") {
            gui.cerrar(ui)
        }
        gui.fin_fila(ui)

        gui.columna(ui, 220)               # 220 píxeles de ancho
        elegida = gui.lista(ui, ciudades, elegida, 8)
        gui.columna(ui, 0)                 # lo que queda a la derecha
        gui.subtitulo(ui, "Detalle")
        gui.texto(ui, "Fila elegida: " + a_texto(elegida))
        gui.fin_columnas(ui)
    }
}
```

## 15.4 Pestañas

`gui.pestanas` dibuja la barra y devuelve cuál está elegida; lo que se muestra
debajo lo decide el programa con ese número:

```scar-check
use "gui"

fn main() {
    let ui = gui.ventana("Pestañas", 480, 300)
    let mut pestana = 0
    while gui.abierta(ui) {
        pestana = gui.pestanas(ui, "Resumen|Ajustes", pestana)
        if pestana == 0 {
            gui.texto(ui, "Todo en orden.")
            if gui.boton(ui, "Ir a Ajustes") {
                pestana = 1
            }
        } else {
            gui.texto(ui, "Acá van los ajustes.")
        }
    }
}
```

## 15.5 Colores y gráficos

`gui.oscuro(ui)` cambia al tema oscuro y `gui.claro(ui)` vuelve al claro. Los
colores del tema son campos de `ui`: `ui.c_texto`, `ui.c_tenue`, `ui.c_acento`,
y para avisos `ui.c_bien` (verde), `ui.c_aviso` (ámbar) y `ui.c_mal` (rojo).
Usándolos, un programa se ve bien con los dos temas.

Un gráfico dibuja una `gui.Serie`, una lista de números. La serie es un
struct, así que pasarla a `gui.barras` es un préstamo (capítulo 8): el programa
la sigue teniendo y le puede agregar valores en cada cuadro:

```scar-check
use "gui"

fn main() {
    let ui = gui.ventana("Ventas", 520, 360)
    gui.oscuro(ui)
    let ventas = gui.serie()
    gui.agregar(ventas, 120.0)
    gui.agregar(ventas, 95.5)
    gui.agregar(ventas, 143.0)
    while gui.abierta(ui) {
        gui.etiqueta(ui, "EN ALZA", ui.c_bien)
        gui.barras(ui, ventas, 120)
        gui.lineas(ui, ventas, 120)
        if gui.boton(ui, "Agregar un día") {
            gui.agregar(ventas, 100.0 + rand() * 60.0)
        }
    }
}
```

## 15.6 Dibujar a mano

`gui.lienzo` reserva un rectángulo y devuelve dónde quedó (`z.x`, `z.y`,
`z.ancho`, `z.alto`). Adentro se dibuja con `gui.pintar` (un rectángulo lleno),
`gui.trazo` (una línea) y `gui.rotular` (un texto):

```scar-check
use "gui"

fn main() {
    let ui = gui.ventana("Onda", 600, 260)
    while gui.abierta(ui) {
        let z = gui.lienzo(ui, 160)
        let medio = z.y + z.alto / 2
        gui.trazo(ui, z.x, medio, z.x + z.ancho, medio, ui.c_tenue)
        for c in 0..z.ancho {
            let v = to_i32(sin(to_f64(c) / 12.0) * 50.0)
            gui.pintar(ui, z.x + c, medio - max(v, 0), 1, abs(v) + 1, ui.c_acento)
        }
        gui.rotular(ui, z.x + 8, z.y + 6, "seno", 13, ui.c_tenue)
    }
}
```

`gui.clic_en(ui, x, y, ancho, alto)` dice si hubo un clic en un rectángulo, y
`gui.rueda(ui)` cuánto se movió la rueda del ratón: con eso una pieza hecha a
mano responde al ratón.

## 15.7 El teclado

`gui.tecla(ui, codigo)` dice si se pulsó una tecla en este cuadro:
`if gui.tecla(ui, 44) { pausa = not pausa }` (Espacio). Los códigos son los de
SDL: Espacio 44, Enter 40, Esc 41, Tab 43, flechas 79 a 82, A a Z del 4 al 29.
Mientras un campo de texto tiene el foco, las teclas son para el campo.

## 15.8 Probar una interfaz sin nadie que la use

Una interfaz también se puede probar sin pantalla, con tres variables de
entorno:

- `SDL_VIDEODRIVER=dummy`: la ventana existe, pero no se muestra.
- `SCAR_SDL_MAX_FRAMES=N`: después de N cuadros, `gui.abierta` da `false`.
- `SCAR_SDL_GUION=archivo`: lo que "hace" la persona, cuadro por cuadro.

```
# cuadro acción
1 clic 50 100
5 escribe  Pérez
6 tecla 40
10 rueda -2
```

El programa imprime lo que pasó, y se compara con lo esperado (y entre el
intérprete y el binario, que dan lo mismo). `SCAR_SDL_CAPTURE=a.bmp` guarda el
último cuadro como imagen, para mirarlo.

## 15.9 Más allá

Sobre `gui` hay más librerías (apéndice B): `pantalla` muestra en la ventana un
lienzo dibujado en memoria (con `lienzo`, `imagen` o `motor3d`), `parlante` hace
sonar audio, `tablero` arma tableros de control con indicadores, y `editor` es
un editor de texto completo.

## 15.10 Ejercicios

1. Haz una calculadora con dos campos, cuatro botones (`+ - × ÷`) y el
   resultado.
2. Una lista de tareas: un campo para escribir, un botón "Agregar" y una lista;
   al elegir una fila, un botón "Borrar".
3. Un reloj que muestre los segundos desde que se abrió la ventana, con
   `now()`.
4. Dibuja en un lienzo un gráfico de la función `x²` entre -10 y 10.

El programa de este capítulo está en `ejemplos/15_interfaces.scar`.
