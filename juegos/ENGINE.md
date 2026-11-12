# Motor de juego en SCAR — raycaster estilo DOOM

Un motorcito 2.5D (raycaster) escrito en SCAR, compatible con Linux y Windows
(vía WSL). Inspirado en DOOM/Wolfenstein: mapas de grilla, paredes texturadas,
iluminación cálida, sprites y cielo. Pensado como proyecto personal, enfocado en
**rendimiento + estética**, no como motor genérico para terceros.

Archivo principal: [`paso5_mundo.scar`](paso5_mundo.scar).
Correr: `scar build juegos/paso5_mundo.scar -o juegos/paso5_mundo && ./juegos/paso5_mundo`
(o `python3 main.py juegos/paso5_mundo.scar` con el intérprete, más lento).

Controles: **W/S** adelante/atrás, **A/D** strafe, **ratón** girar y mirar arriba/abajo (clic dentro para
atraparlo, estilo FPS), **Q/E** girar con teclado (opcional), **Tab** suelta/atrapa
el cursor, **F11** pantalla completa, **ESC** o **X** salir. La ventana se puede
**maximizar / redimensionar** (con el cursor suelto): la resolución interna se
adapta sola (manteniendo el aspecto).

---

## Arquitectura de render (el camino que funciona)

El render va por un **buffer de píxeles de una sola subida**, que es el camino
rápido y sin artefactos:

1. Un `lienzo` en memoria (`Vec<i32>` ARGB, resolución interna **320×200**).
2. Bucle `while gui.abierta(ui)` — `gui` se encarga de `clear`/`present` cada cuadro.
3. Se repinta el buffer **entero** cada cuadro (cielo + paredes + piso + sprites).
4. `pantalla.mostrar_en(buf, 0, 0, ESC)` lo sube a la ventana en **una sola
   llamada de dibujo** (escala ×3 → ventana 960×600), vía `scar_sdl_pixeles` → SDL2.

Por columna de pantalla (320 rayos):
- **DDA**: el rayo salta celda a celda de la grilla hasta pegar una pared.
- **Distancia perpendicular** (corrige el "ojo de pez").
- **Textura**: el punto de impacto elige la columna de textura; cada píxel vertical
  muestrea su fila.
- **Cielo** arriba de la pared, **piso** debajo, todo en el mismo recorrido.
- Un **z-buffer** (distancia por columna) permite que las paredes tapen los sprites.

## Qué hay implementado

- **Raycaster DDA** caminable, con colisión por eje contra la grilla.
- **Paredes texturadas** con **varios materiales**: `#`/`1` = ladrillo, `2` =
  piedra con musgo (texturas generadas por código, 64×64).
- **Iluminación** por canal: ambiente frío tenue + **antorcha del jugador** (halo
  cálido que cae con la distancia) + **antorchas fijas** (luz naranja con caída y
  **parpadeo**). Caras N/S más oscuras para dar volumen.
- **Sprites**: llamas de antorcha como *billboards* (siempre te miran), con
  **z-buffer** (las paredes las tapan), **transparencia** y soporte (cuenco +
  palo) iluminado por el fuego. Ancladas a muros.
- **Cielo panorámico**: degradado + nubes procedurales que **derivan**; se
  desplaza al **girar** (muestreo por ángulo de visión). Solo se dibuja donde no
  hay pared.
- **Ciclo día/noche** (60 s: 30 día + 30 noche): el sol cruza el cielo y hay
  **sol direccional** (cada cara de pared se ilumina según su normal contra la
  dirección del sol). Fases: amanecer, mediodía, atardecer, anochecer y una franja
  corta de **noche cerrada**. El **cielo se tiñe** por hora (azul → navy → cálido
  en crepúsculo) con **disco/halo del sol** visible; el piso sigue la hora y las
  **antorchas pesan de noche**. La fase actual se rotula arriba a la izquierda.
- **Entrada WASD + ratón** estilo FPS: W/S avanzar, A/D strafe, el ratón gira
  (clic para atraparlo, Tab/ESC lo liberan), Q/E giran con teclado. Mover el
  ratón arriba/abajo inclina la vista corriendo el horizonte (con tope, para que
  no salga de la pantalla); las paredes no se deforman.
- **Ventana redimensionable / maximizable**: la resolución interna se deriva del
  tamaño real cada cuadro (`esc = ceil(ancho/360)`), así el ancho interno queda
  acotado (~320–360 px, costo estable), llena la ventana y respeta el aspecto;
  `buf`/`z-buffer` se rehacen solo cuando cambia el tamaño.
- **Contador de FPS** arriba a la derecha.

## Progresión (archivos de aprendizaje)

Cada paso aisló un problema; se conservan como referencia:

| Archivo | Qué introdujo |
|---|---|
| `paso1_degradado.scar` | Ventana + lienzo + blit. Primer píxel en pantalla. |
| `paso2_raycaster.scar` | Raycaster DDA con rects directos (`scar_sdl_draw_rect_color`). |
| `paso3_texturas.scar` | Paredes texturadas (run-length sobre rects). |
| `paso4_materiales.scar`| Varios materiales + tabla de tramos precalculada. |
| `paso5_mundo.scar` | **Camino de buffer de píxeles**: iluminación, sprites, cielo. El motor actual. |

---

## Lecciones aprendidas (cazabugs que costaron sangre)

Reglas duras del pipeline, para no repetir:

1. **Repintar TODO cada cuadro.** El buffer no se borra solo; lo que no repintes
   queda del cuadro anterior → "arrastre". `lienzo.rect` dibuja **solo el borde**;
   para rellenar usa `lienzo.rect_lleno` o `lienzo.limpiar`.
2. **Todo lo que escribas directo al buffer debe llevar alfa 255.** El color es
   ARGB (`0xAARRGGBB`). `rgb()` arma `0x00RRGGBB` (**alfa 0 = transparente** → se
   ve negro al blitear). Usa **`lienzo.color()`** (alfa 255) para cualquier píxel
   que vaya directo a `buf.pixeles.set`. (Esto nos tuvo con el cielo negro.)
3. **Camino de dibujo correcto = buffer de una sola subida.** Dibujar con miles
   de rects chicos (`scar_sdl_draw_rect_color`) es lento bajo **WSLg** (la capa
   gráfica de WSL). Un solo `scar_sdl_pixeles` por cuadro es órdenes de magnitud
   más rápido.
4. **Usar el bucle `gui.abierta(ui)`** (como `juegos/lost_world/`), que maneja
   `clear`/`present` bien. Fue la referencia que confirmó que el camino de píxeles
   no arrastra si se repinta todo.
5. **Colisión por eje** (mover X y Y por separado contra la grilla) evita quedar
   trabado en las esquinas.

## Notas de rendimiento

- El costo escala con el número de columnas (rayos). 320 columnas = nítido;
  bajar a 160–240 sube FPS si hace falta.
- El techo real está en el blit único; evitar volver al camino de rects.
- `scar build` (nativo) es el modo de juego; el intérprete sirve para probar
  lógica rápido (y para depurar headless con `SDL_VIDEODRIVER=dummy`
  `SCAR_SDL_MAX_FRAMES=N`).

## Cambios en el C nativo (opt-in, experimentos)

En `native/scarsdl.c` se agregaron dos opciones por variable de entorno, **sin
cambiar el comportamiento por defecto** (no afectan a `lost_world` ni al resto):

- `SCAR_SDL_VSYNC=1` → crea el renderer con `PRESENTVSYNC` (contra tearing).
- `SCAR_SDL_NOBLEND=1` → la textura de `scar_sdl_pixeles` se copia sin mezcla.

Resultaron **no necesarios** (el "arrastre" era el repintado del buffer, no SDL).
Decidir si se revierten o se dejan como opciones.

Cambio aplicado (no experimental): **mouse-look manual** para el giro con ratón. El
modo relativo de SDL es poco fiable en **WSLg / escritorios remotos**: o el cursor se
frena en el borde (los `xrel` dejan de llegar y la vista "sigue al puntero") o el
recentrado por warp mete un delta residual y la vista **gira sola**. Se agregaron dos
funciones que no usan modo relativo:

- `scar_sdl_mirar_on(si)`: oculta el cursor, confina la ventana y lo centra (0 libera).
- `scar_sdl_mirar_dx()`: devuelve el desplazamiento en X desde el centro de la ventana
  en este cuadro y vuelve a centrar el cursor. Con el ratón quieto da 0 (sin giro
  espurio). El motor hace `ang += dx * sens` (sumar gira a la derecha).
- `scar_sdl_mirar_dy()`: lo mismo en Y (negativo = arriba), medido en la última
  llamada a `scar_sdl_mirar_dx()`; se llama después de ella. El motor lo usa para
  inclinar la vista.

Requiere recompilar la lib tras tocar el C:
`cc -shared -fPIC -O2 native/scarsdl.c -o native/lib/libscarsdl.so $(sdl2-config --cflags --libs)`.

---

## Planes / roadmap

Corto plazo (sobre lo que ya hay):
- [ ] **Piso y techo texturados** (floor casting) — cierra el look.
- [x] **Tinte de cielo por hora del día** + ciclo día/noche con sol direccional
      (amanecer, atardecer, anochecer, noche). Falta: **noche estrellada**.
- [ ] **Enemigos**: sprites con movimiento/IA simple sobre el mismo z-buffer.
- [ ] **Minimapa** en una esquina.

Mediano plazo:
- [ ] **Puertas** y **sectores con altura** variable (más allá de grilla plana).
- [ ] **Sonido/música** con `lib/audio.scar` (pasos, fuego, ambiente).
- [ ] **Carga de mapas** desde archivo (no hardcodeados).

Largo plazo / a considerar:
- [ ] **Importar modelos** (`.obj` → `Malla` de `lib/motor3d.scar`) para props 3D.
- [~] **Build nativo en Windows** (MSYS2/MinGW) además de WSL — toolchain listo
      (ver abajo); falta probarlo con MinGW instalado. Evita los problemas de ratón
      de WSLg.
- [ ] Mundo más grande / "abierto": chunks de mapa, carga por zona.

## Build nativo en Windows (MSYS2/MinGW)

Evita WSLg (y sus rarezas de ratón). Pasos:

1. Instalar **MSYS2** (https://www.msys2.org) y, en su terminal:
   `pacman -S mingw-w64-x86_64-gcc mingw-w64-x86_64-SDL2`
2. Agregar `C:\msys64\mingw64\bin` al **PATH** de Windows (trae `gcc`, los headers
   de SDL2 y `SDL2.dll`). Abrir una consola nueva y verificar: `gcc --version`.
3. Compilar la librería nativa para Windows (produce `native/lib/scarsdl.dll` +
   `libscarsdl.dll.a`): `python construir_nativas.py scarsdl`
4. Compilar el juego: `python cli.py build juegos/paso5_mundo.scar -o juegos/paso5_mundo`
   → genera `juegos/paso5_mundo.exe` y copia `scarsdl.dll` al lado. Correr: `.\juegos\paso5_mundo.exe`

El build detecta la plataforma solo: en Windows usa `.dll`/`.exe`, sin `-rpath` ni
flags ELF, y copia los `.dll` nativos junto al `.exe` (SDL2.dll se toma del PATH).

## Dependencias

- SCAR (este repo) + `gcc`/`clang` para `scar build`.
- **SDL2** (`libsdl2-dev`) para la ventana y el dibujo.
- Librerías SCAR usadas: `lib/gui.scar`, `lib/lienzo.scar`, `lib/pantalla.scar`.
- Builtins: `sin`, `cos`, `sqrt`, `to_i32`, `to_f64`.
