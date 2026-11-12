// scarsdl.c — la capa delgada sobre SDL2 que usan las librerías gráficas y de
// sonido de SCAR (lib/gui, lib/pantalla, lib/parlante...). SCAR solo ve
// funciones extern "C" con firmas planas: enteros, str, y un puntero opaco
// para la ventana (`extern type SDLWindow`). Ningún struct de SDL cruza por
// valor: SDL_Event o SDL_Rect quedan enteros de este lado.
//
// Botones: scar_sdl_on_click() registra un rectángulo y un valor fn de SCAR
// (fn(i32, i32)) que C llama directo cuando un click cae adentro. El
// hit-test vive en scar_sdl_poll_event(): un click fuera de todo botón
// registrado sigue devolviendo el código 1, para el programa que hace su
// propio hit-test.
//
// Una sola ventana viva a la vez: la ventana y el renderer son estáticos del
// módulo. Para varias, el handle opaco tendría que apuntar a un struct propio
// {SDL_Window*, SDL_Renderer*} en vez de ser el SDL_Window* mismo.

#ifdef _WIN32
// En Windows el `main` lo pone el C generado por SCAR, no la SDL2main: sin esto
// SDL redefine `main` a `SDL_main` y pide enlazar -lSDL2main.
#define SDL_MAIN_HANDLED
#endif
#include <SDL2/SDL.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "scarfuente.h"
#include "scarfuente_mono.h"

// Corridas sin nadie mirando (CI, pruebas) -- ningún programa
// cambia por esto, todo se controla con variables de entorno:
//   SDL_VIDEODRIVER=dummy  (de SDL) ventana sin pantalla; el renderer cae
//                          al de software (ver scar_sdl_create_window).
//   SCAR_SDL_MAX_FRAMES=N  después de N scar_sdl_present(), poll_event()
//                          devuelve 2 (cierre de ventana) una vez por frame
//                          y 0 hasta el próximo present: el programa termina
//                          solo, por su camino normal, y un loop que drena
//                          eventos hasta el 0 no queda girando para siempre.
//   SCAR_SDL_CAPTURE=a.bmp el frame N se guarda en a.bmp antes de
//                          mostrarse (para verificar lo que se dibujó).
static long g_max_frames = -1;   // -1 = sin límite
static long g_frames = 0;
static const char *g_captura = NULL;
static int g_cierre_entregado = 0;  // ya se devolvió el 2 de este frame

static void cargar_guion(const char *ruta);

static void leer_entorno(void) {
    const char *m = getenv("SCAR_SDL_MAX_FRAMES");
    g_max_frames = (m && *m) ? strtol(m, NULL, 10) : -1;
    g_frames = 0;
    const char *c = getenv("SCAR_SDL_CAPTURE");
    g_captura = (c && *c) ? c : NULL;
    const char *gu = getenv("SCAR_SDL_GUION");
    if (gu && *gu) cargar_guion(gu);
}

static int limite_alcanzado(void) {
    return g_max_frames >= 0 && g_frames >= g_max_frames;
}

// El tipo C exacto que emite el compilador (_fn_c_type) para
// `fn(i32, i32) -> void` del lado de SCAR -- mismo layout, así que un
// puntero recibido acá se puede invocar tal cual, sin ningún cast ni
// wrapper de por medio (C ya resuelve la aplicación de un puntero a
// función igual que la de un nombre de función).
typedef void (*ScarClickHandler)(int, int);

// Registro fijo de botones: cada uno es un rectángulo + el handler a
// invocar cuando un click cae adentro. Capacidad chica a propósito, como
// "una sola ventana viva": la disposición de muchos controles la hace
// lib/gui en SCAR, no este registro.
#define SCAR_MAX_BUTTONS 8
static struct {
    int x, y, w, h;
    ScarClickHandler handler;
} g_buttons[SCAR_MAX_BUTTONS];
static int g_n_buttons = 0;

// scar_sdl_on_click(x, y, w, h, handler) -> i32 (0 = registrado ok,
// 1 = registro lleno). Debe llamarse ANTES de entrar al loop de eventos
// (una vez por botón, no por frame) -- scar_sdl_poll_event() consulta
// este registro en cada click que detecta.
int scar_sdl_on_click(int x, int y, int w, int h, ScarClickHandler handler) {
    if (g_n_buttons >= SCAR_MAX_BUTTONS) return 1;
    g_buttons[g_n_buttons].x = x;
    g_buttons[g_n_buttons].y = y;
    g_buttons[g_n_buttons].w = w;
    g_buttons[g_n_buttons].h = h;
    g_buttons[g_n_buttons].handler = handler;
    g_n_buttons++;
    return 0;
}

static SDL_Window   *g_win = NULL;
static SDL_Renderer *g_ren = NULL;
static SDL_Texture *g_tex_px = NULL;    // la de scar_sdl_pixeles (al final)
static int g_tex_w = 0, g_tex_h = 0;
static SDL_AudioDeviceID g_audio = 0;   // el de scar_sdl_sonar (al final)
static int g_audio_canales = 0, g_audio_tasa = 0;

static void soltar_audio(void) {
    if (g_audio != 0) { SDL_CloseAudioDevice(g_audio); g_audio = 0; }
    g_audio_canales = g_audio_tasa = 0;
}

// scar_sdl_init() -> i32 (0 = ok, !=0 = error; el detalle de SDL_GetError()
// va a stderr).
int scar_sdl_init(void) {
#ifdef _WIN32
    SDL_SetMainReady();   // con SDL_MAIN_HANDLED: avisamos que el main ya corre
#endif
    if (SDL_Init(SDL_INIT_VIDEO) != 0) {
        fprintf(stderr, "scar_sdl_init: %s\n", SDL_GetError());
        return 1;
    }
    leer_entorno();
    g_n_buttons = 0;  // Limpia el registro de botones de una
                       // corrida anterior en el mismo proceso (defensivo,
                       // el milestone mínimo nunca llama scar_sdl_init()
                       // dos veces en la práctica).
    return 0;
}

// scar_sdl_create_window(w, h) -> SDLWindow (void* opaco en SCAR).
// Devuelve NULL en error -- el chequeo de NULL queda del lado de SCAR
// igual que gzopen()/Result<GzFile> (ver test_ffi_gzip.scar), aunque acá
// todavía devolvemos el puntero crudo, no Result<SDLWindow>: el milestone
// mínimo no lo necesita, se puede sumar después con el mismo patrón.
void *scar_sdl_create_window(int w, int h) {
    g_win = SDL_CreateWindow("SCAR GUI", SDL_WINDOWPOS_CENTERED,
                             SDL_WINDOWPOS_CENTERED, w, h, SDL_WINDOW_SHOWN);
    if (!g_win) {
        fprintf(stderr, "scar_sdl_create_window: %s\n", SDL_GetError());
        return NULL;
    }
    SDL_StartTextInput();  // lo que se escribe llega como texto (scar_sdl_escrito)
    Uint32 flags_ren = SDL_RENDERER_ACCELERATED;
    if (getenv("SCAR_SDL_VSYNC")) flags_ren |= SDL_RENDERER_PRESENTVSYNC;  // opt-in: evita tearing
    g_ren = SDL_CreateRenderer(g_win, -1, flags_ren);
    if (!g_ren) {
        // sin aceleración (SDL_VIDEODRIVER=dummy, escritorio remoto...):
        // el renderer de software dibuja exactamente lo mismo
        g_ren = SDL_CreateRenderer(g_win, -1, SDL_RENDERER_SOFTWARE);
    }
    if (g_ren) SDL_SetRenderDrawBlendMode(g_ren, SDL_BLENDMODE_BLEND);  // el alfa de los colores se respeta
    if (!g_ren) {
        fprintf(stderr, "scar_sdl_create_window (renderer): %s\n", SDL_GetError());
        SDL_DestroyWindow(g_win);
        g_win = NULL;
        return NULL;
    }
    return (void *)g_win;
}

// Ultimo click registrado -- consultado por scar_sdl_mouse_x()/_y() luego
// de que scar_sdl_poll_event() devuelva 1. Estado simple a proposito: el
// milestone minimo no necesita mas que "donde fue el ultimo click".
static int g_last_x = 0;
static int g_last_y = 0;

// scar_sdl_poll_event() -> i32: drena UN evento de la cola de SDL por
// llamada (igual que SDL_PollEvent) y lo traduce a un codigo chico:
//   0 = no hay nada pendiente (llamar de nuevo el proximo frame)
//   1 = click de mouse SIN botón registrado en esas coordenadas --
//       coords en _mouse_x()/_mouse_y(), mismo camino que siempre para
//       quien quiera seguir haciendo su propio hit-test en SCAR (ver
//       62_gui_boton.scar)
//   2 = pedido de cierre de ventana (SDL_QUIT, o click en la X)
//   3 = cualquier otro evento (tecla, resize, etc. -- ignorado por ahora)
//   4 = click de mouse que SÍ cayó dentro de un botón registrado con
//       scar_sdl_on_click() -- el handler YA fue invocado acá adentro,
//       antes de devolver el código (callback real, no
//       polling); SCAR no tiene que hacer nada más con este evento.
// SCAR drena la cola llamando esto en loop hasta que devuelva 0, dentro
// de su propio loop de frame -- sin necesitar SDL_Event como tipo.
int scar_sdl_poll_event(void) {
    SDL_Event e;
    if (limite_alcanzado()) {
        if (g_cierre_entregado) return 0;
        g_cierre_entregado = 1;
        return 2;
    }
    if (!SDL_PollEvent(&e)) return 0;
    if (e.type == SDL_QUIT) return 2;
    if (e.type == SDL_MOUSEBUTTONDOWN && e.button.button == SDL_BUTTON_LEFT) {
        g_last_x = e.button.x;
        g_last_y = e.button.y;
        // hit-test contra el registro de botones ANTES de
        // devolver el código de siempre -- si cae adentro de alguno,
        // invocar su handler acá mismo (callback real, ver typedef
        // ScarClickHandler más arriba) y devolver 4 en vez de 1. Se
        // prueba en orden de registro y se para en el primer match
        // (mismo criterio simple que ya usaba SCAR a mano en
        // 62_gui_boton.scar, solo que ahora lo hace C).
        for (int i = 0; i < g_n_buttons; i++) {
            if (g_last_x >= g_buttons[i].x && g_last_x <= g_buttons[i].x + g_buttons[i].w &&
                g_last_y >= g_buttons[i].y && g_last_y <= g_buttons[i].y + g_buttons[i].h) {
                g_buttons[i].handler(g_last_x, g_last_y);
                return 4;
            }
        }
        return 1;
    }
    return 3;
}

// scar_sdl_key_down(scancode) -> i32: 1 si la tecla esta apretada ahora
// mismo, 0 si no. Nueva (Pong): consulta el estado del teclado de SDL en
// vez de traducir eventos, asi SCAR puede preguntar "esta apretada la W?"
// cada cuadro sin llevar la cuenta de los eventos de subir/bajar tecla.
// `scancode` es un SDL_Scancode (W=26, S=22, flecha arriba=82, abajo=81,
// P=19, R=21, 1=30, 2=31, espacio=44, ESC=41). El estado se actualiza
// cuando se drenan los eventos con scar_sdl_poll_event(), asi que SCAR
// debe llamar a poll_event() en cada cuadro (como ya hace).
static unsigned char g_abajo_guion[SDL_NUM_SCANCODES];  // teclas que el guion mantiene apretadas
int scar_sdl_key_down(int scancode) {
    int n = 0;
    const Uint8 *k = SDL_GetKeyboardState(&n);
    if (scancode >= 0 && scancode < SDL_NUM_SCANCODES && g_abajo_guion[scancode]) return 1;
    if (!k || scancode < 0 || scancode >= n) return 0;
    return k[scancode] ? 1 : 0;
}

// scar_sdl_ticks() -> i32: milisegundos desde que arrancó SDL (da la vuelta a los ~24 días; quien
// la usa resta dos lecturas, que sigue andando con la vuelta). Para el bucle a paso fijo de lib/juego.
int scar_sdl_ticks(void) { return (int)(SDL_GetTicks() & 0x7fffffffu); }

int scar_sdl_mouse_x(void) { return g_last_x; }
int scar_sdl_mouse_y(void) { return g_last_y; }

// Color de fondo para scar_sdl_clear(): gris (30,30,30,255) hasta que
// alguien llame a scar_sdl_set_clear_color().
static Uint8 g_clear_r = 30, g_clear_g = 30, g_clear_b = 30, g_clear_a = 255;

// scar_sdl_clear() -> i32: limpia el frame al color de fondo configurado
// (gris por defecto, ver g_clear_* arriba).
int scar_sdl_clear(void) {
    if (!g_ren) return 0;  // la ventana ya se cerró (un programa que cierra en medio del cuadro)
    SDL_SetRenderDrawColor(g_ren, g_clear_r, g_clear_g, g_clear_b, g_clear_a);
    SDL_RenderClear(g_ren);
    return 0;
}

// scar_sdl_set_clear_color(r, g, b, a) -> i32: cambia el color que usa
// scar_sdl_clear() en las llamadas siguientes. Sin llamarla, el gris.
int scar_sdl_set_clear_color(int r, int g, int b, int a) {
    g_clear_r = (Uint8)r;
    g_clear_g = (Uint8)g;
    g_clear_b = (Uint8)b;
    g_clear_a = (Uint8)a;
    return 0;
}

// scar_sdl_draw_rect(x, y, w, h) -> i32: el "boton" es esto -- un
// rectangulo solido. SCAR es dueno de decidir donde y compara contra
// mouse_x()/mouse_y() para saber si el click cayo adentro; no hay
// concepto de "widget" del lado de C. El color es fijo (azul acero).
int scar_sdl_draw_rect(int x, int y, int w, int h) {
    if (!g_ren) return 0;
    SDL_Rect r = { x, y, w, h };
    SDL_SetRenderDrawColor(g_ren, 70, 130, 180, 255);
    SDL_RenderFillRect(g_ren, &r);
    return 0;
}

// scar_sdl_draw_rect_color(x, y, w, h, r, g, b, a) -> i32: como draw_rect(),
// con el color de cada llamada (no toca g_clear_*).
int scar_sdl_draw_rect_color(int x, int y, int w, int h,
                              int r, int g, int b, int a) {
    if (!g_ren) return 0;
    SDL_Rect rect = { x, y, w, h };
    SDL_SetRenderDrawColor(g_ren, (Uint8)r, (Uint8)g, (Uint8)b, (Uint8)a);
    SDL_RenderFillRect(g_ren, &rect);
    return 0;
}

// Guarda lo dibujado en el frame actual (antes de present: después, el
// contenido del buffer queda indefinido para SDL).
static void capturar_frame(const char *ruta) {
    int w = 0, h = 0;
    if (!g_ren || SDL_GetRendererOutputSize(g_ren, &w, &h) != 0 || w <= 0 || h <= 0) return;
    SDL_Surface *s = SDL_CreateRGBSurfaceWithFormat(0, w, h, 32, SDL_PIXELFORMAT_ARGB8888);
    if (!s) return;
    if (SDL_RenderReadPixels(g_ren, NULL, SDL_PIXELFORMAT_ARGB8888, s->pixels, s->pitch) == 0) {
        if (SDL_SaveBMP(s, ruta) != 0)
            fprintf(stderr, "scar_sdl: no se pudo guardar %s: %s\n", ruta, SDL_GetError());
    } else {
        fprintf(stderr, "scar_sdl: no se pudo leer el frame: %s\n", SDL_GetError());
    }
    SDL_FreeSurface(s);
}

int scar_sdl_present(void) {
    g_frames++;
    g_cierre_entregado = 0;
    if (g_captura && g_max_frames >= 0 && g_frames == g_max_frames) capturar_frame(g_captura);
    if (g_ren) SDL_RenderPresent(g_ren);
    return 0;
}

// scar_sdl_delay(ms) -> i32: sleep de frame (evita el loop de polling a
// 100% CPU). No es parte de SDL_Delay expuesto sin envolver por las
// mismas razones que el resto de esta lista: mantener a SCAR sin ver
// ningun tipo de SDL, ni siquiera uno tan chico como Uint32.
int scar_sdl_delay(int ms) {
    SDL_Delay((Uint32)ms);
    return 0;
}

// scar_sdl_destroy_window(win) -> i32: contraparte de create_window, para
// usar con `own SDLWindow` en la firma extern (mismo patron que
// gzclose(own GzFile) en test_ffi_gzip.scar) -- SCAR no puede volver a
// usar el handle despues de esto, el checker ya lo exige.
static void soltar_atlas(void);

int scar_sdl_destroy_window(void *win) {
    (void)win; // hoy es siempre g_win (una sola ventana viva, ver arriba)
    soltar_atlas();
    if (g_tex_px) { SDL_DestroyTexture(g_tex_px); g_tex_px = NULL; g_tex_w = g_tex_h = 0; }
    if (g_ren) { SDL_DestroyRenderer(g_ren); g_ren = NULL; }
    if (g_win) { SDL_DestroyWindow(g_win); g_win = NULL; }
    return 0;
}

int scar_sdl_quit(void) {
    soltar_audio();
    SDL_Quit();
    return 0;
}


// ===========================================================================
// Texto, dibujo y entrada por cuadro, para la
// librería gráfica de SCAR (lib/gui.scar). Todo con firmas planas (i32 y
// str), como el resto de este archivo. Las funciones de arriba siguen
// iguales: los juegos y los ejemplos 62/88/89/95 no cambian.
// ===========================================================================

// ---- texto -----------------------------------------------------------------
// La fuente viene rasterizada en scarfuente.h (pruebas/gen_fuente.py): no hace
// falta SDL_ttf ni una fuente instalada. Por tamaño se arma, la primera vez que
// se dibuja, una textura con todos los glifos en blanco y su alfa; cada letra
// es un pedazo de esa textura pintado con el color pedido.

static SDL_Texture *g_atlas[SCAR_FUENTE_NTAMANOS];
static int g_atlas_x[SCAR_FUENTE_NTAMANOS][SCAR_FUENTE_NGLIFOS];
// la fuente de ancho fijo (scarfuente_mono.h), para el texto de los editores de código
static SDL_Texture *g_atlas_m[SCAR_MONO_NTAMANOS];
static int g_atlas_x_m[SCAR_MONO_NTAMANOS][SCAR_FUENTE_NGLIFOS];
static int g_indice[256];      // código < 256 -> glifo (-1 si no hay)
static int g_indice_listo = 0;

static void armar_indice(void) {
    if (g_indice_listo) return;
    for (int i = 0; i < 256; i++) g_indice[i] = -1;
    const ScarGlifo *gs = scar_fuentes[0].glifos;
    for (int i = 0; i < SCAR_FUENTE_NGLIFOS; i++)
        if (gs[i].cp < 256) g_indice[gs[i].cp] = i;
    g_indice_listo = 1;
}

static int glifo_de(uint32_t cp) {
    armar_indice();
    if (cp < 256 && g_indice[cp] >= 0) return g_indice[cp];
    if (cp >= 256) {  // los pocos de más allá de Latin-1 (€, –, “...), después de los 256
        for (int i = 0; i < SCAR_FUENTE_NGLIFOS; i++)
            if (scar_fuentes[0].glifos[i].cp == cp) return i;
    }
    return g_indice['?'];
}

// El siguiente carácter de un texto UTF-8; avanza *p. Un byte que no forma un
// carácter válido cuenta como uno y se dibuja como '?'.
static uint32_t siguiente_cp(const unsigned char **p) {
    const unsigned char *s = *p;
    uint32_t c = s[0];
    int n = c < 0x80 ? 1 : (c & 0xE0) == 0xC0 ? 2 : (c & 0xF0) == 0xE0 ? 3 : (c & 0xF8) == 0xF0 ? 4 : 0;
    if (n == 0) { *p = s + 1; return '?'; }
    if (n == 1) { *p = s + 1; return c; }
    uint32_t cp = c & (0x7F >> n);
    for (int i = 1; i < n; i++) {
        if ((s[i] & 0xC0) != 0x80) { *p = s + 1; return '?'; }
        cp = (cp << 6) | (s[i] & 0x3F);
    }
    *p = s + n;
    return cp;
}

// Una fuente (la normal o la de ancho fijo): sus tamaños, y su textura de glifos por tamaño.
typedef struct {
    const ScarFuente *f;
    int n;
    SDL_Texture **atlas;
    int (*atlas_x)[SCAR_FUENTE_NGLIFOS];
} Fuente;

static Fuente fuente_normal(void) {
    Fuente r = { scar_fuentes, SCAR_FUENTE_NTAMANOS, g_atlas, g_atlas_x };
    return r;
}

static Fuente fuente_mono(void) {
    Fuente r = { scar_fuentes_mono, SCAR_MONO_NTAMANOS, g_atlas_m, g_atlas_x_m };
    return r;
}

static int tamano_en(const Fuente *fu, int tam) {  // el tamaño disponible más cercano
    int mejor = 0;
    for (int i = 1; i < fu->n; i++)
        if (abs(fu->f[i].tam - tam) < abs(fu->f[mejor].tam - tam)) mejor = i;
    return mejor;
}

static SDL_Texture *atlas_en(const Fuente *fu, int t) {
    if (fu->atlas[t] || !g_ren) return fu->atlas[t];
    const ScarFuente *f = &fu->f[t];
    int ancho = 1, alto = 1;
    for (int i = 0; i < SCAR_FUENTE_NGLIFOS; i++) {
        fu->atlas_x[t][i] = ancho;
        ancho += f->glifos[i].w + 1;
        if (f->glifos[i].h > alto) alto = f->glifos[i].h;
    }
    SDL_Surface *sup = SDL_CreateRGBSurfaceWithFormat(0, ancho, alto, 32, SDL_PIXELFORMAT_ARGB8888);
    if (!sup) return NULL;
    SDL_FillRect(sup, NULL, 0x00FFFFFF);
    for (int i = 0; i < SCAR_FUENTE_NGLIFOS; i++) {
        const ScarGlifo *g = &f->glifos[i];
        for (int y = 0; y < g->h; y++)
            for (int x = 0; x < g->w; x++) {
                uint32_t k = g->pos + (uint32_t)(y * g->w + x);
                uint32_t a = (f->alfa[k / 2] >> ((k & 1) * 4)) & 15;
                uint32_t *px = (uint32_t *)((uint8_t *)sup->pixels + y * sup->pitch) + fu->atlas_x[t][i] + x;
                *px = ((a * 17) << 24) | 0x00FFFFFF;
            }
    }
    fu->atlas[t] = SDL_CreateTextureFromSurface(g_ren, sup);
    SDL_FreeSurface(sup);
    if (fu->atlas[t]) SDL_SetTextureBlendMode(fu->atlas[t], SDL_BLENDMODE_BLEND);
    return fu->atlas[t];
}

static void soltar_atlas(void) {
    for (int i = 0; i < SCAR_FUENTE_NTAMANOS; i++)
        if (g_atlas[i]) { SDL_DestroyTexture(g_atlas[i]); g_atlas[i] = NULL; }
    for (int i = 0; i < SCAR_MONO_NTAMANOS; i++)
        if (g_atlas_m[i]) { SDL_DestroyTexture(g_atlas_m[i]); g_atlas_m[i] = NULL; }
}

static int ancho_en(const Fuente *fu, const char *s, int tam) {
    const ScarFuente *f = &fu->f[tamano_en(fu, tam)];
    const unsigned char *p = (const unsigned char *)s;
    int ancho = 0;
    while (p && *p) ancho += f->glifos[glifo_de(siguiente_cp(&p))].avance;
    return ancho;
}

static int texto_en(const Fuente *fu, int x, int y, const char *s, int tam, int r, int g, int b, int a) {
    int t = tamano_en(fu, tam);
    const ScarFuente *f = &fu->f[t];
    SDL_Texture *tx = atlas_en(fu, t);
    if (tx) {
        SDL_SetTextureColorMod(tx, (Uint8)r, (Uint8)g, (Uint8)b);
        SDL_SetTextureAlphaMod(tx, (Uint8)a);
    }
    const unsigned char *p = (const unsigned char *)s;
    int cx = x;
    while (p && *p) {
        int i = glifo_de(siguiente_cp(&p));
        const ScarGlifo *gl = &f->glifos[i];
        if (tx && gl->w && gl->h) {
            SDL_Rect desde = { fu->atlas_x[t][i], 0, gl->w, gl->h };
            SDL_Rect hacia = { cx + gl->dx, y + gl->dy, gl->w, gl->h };
            SDL_RenderCopy(g_ren, tx, &desde, &hacia);
        }
        cx += gl->avance;
    }
    return cx - x;
}

// scar_sdl_texto_ancho(s, tam) -> i32: cuántos píxeles ocupa `s` a lo ancho.
int scar_sdl_texto_ancho(const char *s, int tam) {
    Fuente fu = fuente_normal();
    return ancho_en(&fu, s, tam);
}

// scar_sdl_texto_alto(tam) -> i32: el alto de una línea de texto.
int scar_sdl_texto_alto(int tam) {
    Fuente fu = fuente_normal();
    return fu.f[tamano_en(&fu, tam)].alto;
}

// scar_sdl_texto(x, y, s, tam, r, g, b, a) -> i32: dibuja `s` con la esquina
// de arriba a la izquierda de la línea en (x, y); devuelve el ancho dibujado.
// Un '\n' no cambia de línea (eso lo decide quien dibuja).
int scar_sdl_texto(int x, int y, const char *s, int tam, int r, int g, int b, int a) {
    Fuente fu = fuente_normal();
    return texto_en(&fu, x, y, s, tam, r, g, b, a);
}

// Lo mismo con la fuente de ancho fijo (tamaños 13, 16 y 20): cada carácter ocupa el mismo ancho,
// para que las columnas de un texto de código queden alineadas.
int scar_sdl_texto_mono_ancho(const char *s, int tam) {
    Fuente fu = fuente_mono();
    return ancho_en(&fu, s, tam);
}

int scar_sdl_texto_mono_alto(int tam) {
    Fuente fu = fuente_mono();
    return fu.f[tamano_en(&fu, tam)].alto;
}

int scar_sdl_texto_mono(int x, int y, const char *s, int tam, int r, int g, int b, int a) {
    Fuente fu = fuente_mono();
    return texto_en(&fu, x, y, s, tam, r, g, b, a);
}

// ---- dibujo ------------------------------------------------------------------

int scar_sdl_titulo(const char *t) {
    if (g_win) SDL_SetWindowTitle(g_win, t ? t : "");
    return 0;
}

// Un rectángulo sin relleno, de `grosor` píxeles hacia adentro.
int scar_sdl_borde(int x, int y, int w, int h, int grosor, int r, int g, int b, int a) {
    if (!g_ren || w <= 0 || h <= 0) return 0;
    SDL_SetRenderDrawColor(g_ren, (Uint8)r, (Uint8)g, (Uint8)b, (Uint8)a);
    for (int i = 0; i < grosor && 2 * i < w && 2 * i < h; i++) {
        SDL_Rect rc = { x + i, y + i, w - 2 * i, h - 2 * i };
        SDL_RenderDrawRect(g_ren, &rc);
    }
    return 0;
}

int scar_sdl_linea(int x1, int y1, int x2, int y2, int r, int g, int b, int a) {
    if (!g_ren) return 0;
    SDL_SetRenderDrawColor(g_ren, (Uint8)r, (Uint8)g, (Uint8)b, (Uint8)a);
    SDL_RenderDrawLine(g_ren, x1, y1, x2, y2);
    return 0;
}

// Un círculo relleno (para casillas redondas, puntos de un gráfico).
int scar_sdl_circulo(int cx, int cy, int radio, int r, int g, int b, int a) {
    if (!g_ren || radio <= 0) return 0;
    SDL_SetRenderDrawColor(g_ren, (Uint8)r, (Uint8)g, (Uint8)b, (Uint8)a);
    for (int dy = -radio; dy <= radio; dy++) {
        int dx = 0;
        while ((dx + 1) * (dx + 1) + dy * dy <= radio * radio) dx++;
        SDL_RenderDrawLine(g_ren, cx - dx, cy + dy, cx + dx, cy + dy);
    }
    return 0;
}

// Lo que se dibuje después queda adentro de este rectángulo (una lista que se
// desplaza). scar_sdl_sin_recorte() vuelve a toda la ventana.
int scar_sdl_recorte(int x, int y, int w, int h) {
    if (!g_ren) return 0;
    SDL_Rect rc = { x, y, w < 0 ? 0 : w, h < 0 ? 0 : h };
    SDL_RenderSetClipRect(g_ren, &rc);
    return 0;
}

int scar_sdl_sin_recorte(void) {
    if (g_ren) SDL_RenderSetClipRect(g_ren, NULL);
    return 0;
}

// ---- entrada por cuadro ------------------------------------------------------
// scar_sdl_eventos() procesa TODO lo que pasó desde el cuadro anterior y deja
// el estado para consultarlo durante el cuadro: dónde está el ratón, si se
// apretó o soltó su botón en este cuadro, la rueda, qué teclas se pulsaron y
// qué texto se escribió. Así un programa pregunta "¿se hizo clic acá?" sin
// llevar la cuenta de los eventos.

static int g_rx = 0, g_ry = 0, g_r_abajo = 0, g_r_clic = 0, g_r_soltado = 0, g_rueda = 0;
// Cuánto se movió el ratón en este cuadro (para mirar en primera
// persona): suma de los xrel/yrel de los eventos, sirve también con el cursor
// atrapado (scar_sdl_raton_atrapar), donde la posición absoluta no cambia.
static int g_dx = 0, g_dy = 0;
static unsigned char g_pulsadas[SDL_NUM_SCANCODES];
static char g_escrito[512];

static void agregar_escrito(const char *t) {
    size_t n = strlen(g_escrito), m = strlen(t);
    if (n + m < sizeof g_escrito) memcpy(g_escrito + n, t, m + 1);
}

// Guion de entrada (SCAR_SDL_GUION=archivo), para probar una interfaz sin
// nadie que la use: cada línea es "CUADRO acción ...", y la acción pasa en
// ese cuadro (el número de scar_sdl_present() hechos antes). Acciones:
//   mover X Y      el ratón va a (X, Y)
//   clic X Y       va a (X, Y), aprieta y suelta el botón en ese cuadro
//   apretar X Y    va a (X, Y) y aprieta (sin soltar: para arrastrar)
//   soltar         suelta el botón
//   escribe TEXTO  lo que sigue al espacio (hasta el fin de la línea, con
//                  sus espacios) se escribió
//   tecla N        se pulsó la tecla de scancode N (Enter=40, Borrar=42,
//                  Tab=43, Esc=41, flechas: der=79 izq=80 abajo=81 arriba=82)
//   rueda N        la rueda se movió N (positivo = hacia arriba)
//   mirar DX DY    el ratón se movió DX, DY en este cuadro (scar_sdl_raton_dx/dy)
//   tamano W H     la ventana pasa a medir W x H (como si la persona la
//                  agrandara o achicara con el borde)
//   abajo N       el guion mantiene apretada la tecla de scancode N (la ve scar_sdl_key_down)
//   arriba N      y la suelta
//   mods N         quedan apretadas las teclas modificadoras N (1 Mayús, 2 Ctrl, 4 Alt, sumadas)
//                  hasta otro `mods`; con `mods 0` se sueltan
//   cerrar         se pidió cerrar la ventana
// Las líneas vacías y las que empiezan con '#' no cuentan.
#define SCAR_MAX_GUION 512
static struct { long cuadro; char accion[16]; int a, b; char texto[128]; } g_guion[SCAR_MAX_GUION];
static int g_n_guion = 0;
static int g_mods_guion = 0;  // modificadoras que el guion mantiene apretadas

static void cargar_guion(const char *ruta) {
    FILE *f = fopen(ruta, "r");
    g_n_guion = 0;
    if (!f) { fprintf(stderr, "scar_sdl: no se pudo abrir el guion %s\n", ruta); return; }
    char linea[256];
    while (fgets(linea, sizeof linea, f) && g_n_guion < SCAR_MAX_GUION) {
        linea[strcspn(linea, "\r\n")] = 0;
        char *p = linea;
        while (*p == ' ' || *p == '\t') p++;
        if (!*p || *p == '#') continue;
        long cuadro; char accion[16]; int usados = 0;
        if (sscanf(p, "%ld %15s%n", &cuadro, accion, &usados) < 2) {
            fprintf(stderr, "scar_sdl: línea de guion mal escrita: %s\n", linea);
            continue;
        }
        g_guion[g_n_guion].cuadro = cuadro;
        snprintf(g_guion[g_n_guion].accion, sizeof g_guion[g_n_guion].accion, "%s", accion);
        g_guion[g_n_guion].a = g_guion[g_n_guion].b = 0;
        g_guion[g_n_guion].texto[0] = 0;
        if (p[usados] == ' ') usados++;  // un solo espacio separa: el resto es el texto, tal cual
        if (strcmp(accion, "escribe") == 0)
            snprintf(g_guion[g_n_guion].texto, sizeof g_guion[g_n_guion].texto, "%s", p + usados);
        else
            sscanf(p + usados, "%d %d", &g_guion[g_n_guion].a, &g_guion[g_n_guion].b);
        g_n_guion++;
    }
    fclose(f);
}

static int aplicar_guion(void) {  // devuelve 1 si el guion pide cerrar
    int cerrar = 0;
    for (int i = 0; i < g_n_guion; i++) {
        if (g_guion[i].cuadro != g_frames) continue;
        const char *ac = g_guion[i].accion;
        if (!strcmp(ac, "mover") || !strcmp(ac, "clic") || !strcmp(ac, "apretar")) {
            g_rx = g_guion[i].a; g_ry = g_guion[i].b;
        }
        if (!strcmp(ac, "clic")) { g_r_clic = 1; g_r_soltado = 1; g_r_abajo = 0; }
        else if (!strcmp(ac, "apretar")) { g_r_clic = 1; g_r_abajo = 1; }
        else if (!strcmp(ac, "soltar")) { g_r_soltado = 1; g_r_abajo = 0; }
        else if (!strcmp(ac, "escribe")) agregar_escrito(g_guion[i].texto);
        else if (!strcmp(ac, "tecla")) {
            if (g_guion[i].a >= 0 && g_guion[i].a < SDL_NUM_SCANCODES) g_pulsadas[g_guion[i].a] = 1;
        }
        else if (!strcmp(ac, "abajo")) {      // el guion mantiene apretada la tecla `a`
            if (g_guion[i].a >= 0 && g_guion[i].a < SDL_NUM_SCANCODES) g_abajo_guion[g_guion[i].a] = 1;
        }
        else if (!strcmp(ac, "arriba")) {     // y la suelta
            if (g_guion[i].a >= 0 && g_guion[i].a < SDL_NUM_SCANCODES) g_abajo_guion[g_guion[i].a] = 0;
        }
        else if (!strcmp(ac, "rueda")) g_rueda += g_guion[i].a;
        else if (!strcmp(ac, "mirar")) { g_dx += g_guion[i].a; g_dy += g_guion[i].b; }
        else if (!strcmp(ac, "mods")) g_mods_guion = g_guion[i].a;
        else if (!strcmp(ac, "tamano")) {
            if (g_win && g_guion[i].a > 0 && g_guion[i].b > 0) SDL_SetWindowSize(g_win, g_guion[i].a, g_guion[i].b);
        }
        else if (!strcmp(ac, "cerrar")) cerrar = 1;
    }
    return cerrar;
}

// scar_sdl_eventos() -> i32: 0 si no pasó nada que cierre; 2 si la persona pidió cerrar la ventana
// (la X, o la acción "cerrar" del guion: el programa todavía puede preguntar si guardar); 1 si se
// llegó a SCAR_SDL_MAX_FRAMES (un cierre forzado: no hay a quién preguntar). Se llama una vez al
// principio de cada cuadro.
int scar_sdl_eventos(void) {
    g_r_clic = g_r_soltado = 0;
    g_rueda = 0;
    g_dx = g_dy = 0;
    memset(g_pulsadas, 0, sizeof g_pulsadas);
    g_escrito[0] = 0;
    int cerrar = 0;
    SDL_Event e;
    while (SDL_PollEvent(&e)) {
        switch (e.type) {
        case SDL_QUIT: cerrar = 2; break;
        case SDL_MOUSEMOTION:
            g_rx = e.motion.x; g_ry = e.motion.y;
            g_dx += e.motion.xrel; g_dy += e.motion.yrel;
            break;
        case SDL_MOUSEBUTTONDOWN:
            if (e.button.button == SDL_BUTTON_LEFT) {
                g_rx = e.button.x; g_ry = e.button.y; g_r_clic = 1; g_r_abajo = 1;
            }
            break;
        case SDL_MOUSEBUTTONUP:
            if (e.button.button == SDL_BUTTON_LEFT) {
                g_rx = e.button.x; g_ry = e.button.y; g_r_soltado = 1; g_r_abajo = 0;
            }
            break;
        case SDL_MOUSEWHEEL: g_rueda += e.wheel.y; break;
        case SDL_KEYDOWN:
            if (e.key.keysym.scancode < SDL_NUM_SCANCODES) g_pulsadas[e.key.keysym.scancode] = 1;
            break;
        case SDL_TEXTINPUT: agregar_escrito(e.text.text); break;
        default: break;
        }
    }
    if (aplicar_guion()) cerrar = 2;
    if (limite_alcanzado()) cerrar = 1;
    return cerrar;
}

int scar_sdl_raton_x(void) { return g_rx; }
int scar_sdl_raton_y(void) { return g_ry; }
int scar_sdl_raton_abajo(void) { return g_r_abajo; }      // el botón está apretado
int scar_sdl_raton_clic(void) { return g_r_clic; }        // se apretó en este cuadro
int scar_sdl_raton_soltado(void) { return g_r_soltado; }  // se soltó en este cuadro
int scar_sdl_rueda(void) { return g_rueda; }
int scar_sdl_raton_dx(void) { return g_dx; }              // cuánto se movió en este cuadro
int scar_sdl_raton_dy(void) { return g_dy; }
// scar_sdl_raton_atrapar(1): el cursor se oculta y queda atrapado en la ventana, y el
// ratón solo informa movimiento relativo (scar_sdl_raton_dx/dy), como en un juego en
// primera persona; scar_sdl_raton_atrapar(0) lo suelta. Devuelve 0 si se pudo.
int scar_sdl_raton_atrapar(int si) {
    return SDL_SetRelativeMouseMode(si ? SDL_TRUE : SDL_FALSE);
}

// ---- mouse-look manual y robusto (sirve donde el modo relativo "crudo" falla) ---
// El modo relativo de SDL es poco fiable en WSLg / escritorios remotos: o el cursor
// se frena en el borde (xrel deja de llegar) o el recentrado por warp mete un delta
// residual y la vista gira sola. Este camino no usa modo relativo: oculta el cursor,
// confina la ventana y centra el puntero; cada cuadro scar_sdl_mirar_dx() devuelve
// el desplazamiento en X desde el centro y vuelve a centrar. Si el ratón no se mueve,
// el delta es 0: no hay giro espurio.
//
// scar_sdl_mirar_on(si) -> i32: 1 activa (oculta cursor, confina, centra); 0 libera.
int scar_sdl_mirar_on(int si) {
    if (!g_win) return 1;
    SDL_ShowCursor(si ? SDL_DISABLE : SDL_ENABLE);
    SDL_SetWindowGrab(g_win, si ? SDL_TRUE : SDL_FALSE);
    if (si) {
        int w = 0, h = 0;
        SDL_GetWindowSize(g_win, &w, &h);
        SDL_WarpMouseInWindow(g_win, w / 2, h / 2);
    }
    return 0;
}

// scar_sdl_mirar_dx() -> i32: píxeles que se movió el cursor en X desde el centro de
// la ventana en este cuadro; además lo recentra. (Con scar_sdl_mirar_on(1) activo.)
static int g_mirar_dy = 0;
int scar_sdl_mirar_dx(void) {
    if (!g_win) return 0;
    int w = 0, h = 0;
    SDL_GetWindowSize(g_win, &w, &h);
    int mx = 0, my = 0;
    SDL_GetMouseState(&mx, &my);
    int dx = mx - w / 2;
    g_mirar_dy = my - h / 2;
    SDL_WarpMouseInWindow(g_win, w / 2, h / 2);
    return dx;
}

// scar_sdl_mirar_dy() -> i32: lo mismo en Y (negativo = hacia arriba), medido en la
// última llamada a scar_sdl_mirar_dx(), que es la que recentra: se llama después de ella.
int scar_sdl_mirar_dy(void) {
    int dy = g_mirar_dy;
    g_mirar_dy = 0;
    return dy;
}
int scar_sdl_tecla(int scancode) {                        // se pulsó en este cuadro
    return (scancode >= 0 && scancode < SDL_NUM_SCANCODES) ? g_pulsadas[scancode] : 0;
}
const char *scar_sdl_escrito(void) { return g_escrito; }  // texto escrito en este cuadro

// scar_sdl_mods() -> i32: las teclas modificadoras apretadas ahora, sumadas: 1 Mayús, 2 Ctrl, 4 Alt
// (para Mayús+flecha, Ctrl+C...). Con un guion, se suman las que el guion mantiene (`mods N`).
int scar_sdl_mods(void) {
    int m = SDL_GetModState(), r = g_mods_guion;
    if (m & KMOD_SHIFT) r |= 1;
    if (m & KMOD_CTRL) r |= 2;
    if (m & KMOD_ALT) r |= 4;
    return r;
}

// scar_sdl_portapapeles() -> str: el texto del portapapeles del sistema ("" si no hay).
const char *scar_sdl_portapapeles(void) {
    static char *buf = NULL;
    if (buf) SDL_free(buf);
    buf = SDL_GetClipboardText();
    return buf ? buf : "";
}

// scar_sdl_copiar(texto) -> i32: deja `texto` en el portapapeles del sistema (0 si pudo).
int scar_sdl_copiar(const char *t) {
    return SDL_SetClipboardText(t ? t : "") == 0 ? 0 : 1;
}

// ---- ventana sin handle --------------------------------------------
// La librería gráfica (lib/gui.scar) no guarda el handle de la ventana: hay
// una sola viva a la vez (ver arriba), así que abrir y cerrar son dos llamadas.

// scar_sdl_abrir(ancho, alto, titulo) -> i32: 0 si la ventana quedó abierta.
// La ventana se puede agrandar y achicar con el borde: la
// librería pregunta cada cuadro cuánto mide (scar_sdl_ancho / scar_sdl_alto).
int scar_sdl_abrir(int ancho, int alto, const char *titulo) {
    if (scar_sdl_init() != 0) return 1;
    if (!scar_sdl_create_window(ancho, alto)) { SDL_Quit(); return 1; }
    scar_sdl_titulo(titulo);
    SDL_SetWindowResizable(g_win, SDL_TRUE);
    SDL_SetWindowMinimumSize(g_win, 320, 240);
    return 0;
}

// scar_sdl_ancho() / scar_sdl_alto() -> i32: lo que mide ahora el área de
// dibujo, en píxeles (cambia si la persona agranda la ventana).
int scar_sdl_ancho(void) {
    int w = 0, h = 0;
    if (!g_ren || SDL_GetRendererOutputSize(g_ren, &w, &h) != 0) return 0;
    return w;
}

int scar_sdl_alto(void) {
    int w = 0, h = 0;
    if (!g_ren || SDL_GetRendererOutputSize(g_ren, &w, &h) != 0) return 0;
    return h;
}

// scar_sdl_pantalla_completa(si) -> i32: con 1 la ventana ocupa toda la pantalla (sin cambiar la
// resolución del monitor, así entra y sale al instante); con 0 vuelve a ser una ventana. 0 si se
// pudo. El tamaño nuevo se lee como siempre con scar_sdl_ancho/alto.
int scar_sdl_pantalla_completa(int si) {
    if (!g_win) return 1;
    return SDL_SetWindowFullscreen(g_win, si ? SDL_WINDOW_FULLSCREEN_DESKTOP : 0) == 0 ? 0 : 1;
}

// scar_sdl_cerrar() -> i32: cierra la ventana y SDL.
int scar_sdl_cerrar(void) {
    scar_sdl_destroy_window(g_win);
    soltar_audio();
    SDL_Quit();
    return 0;
}

// ---- píxeles de SCAR ---------------------------------------------------------
// scar_sdl_pixeles(datos, n, ancho, alto, x, y, escala) -> i32: dibuja un
// buffer de ancho x alto píxeles ARGB (un int32 por píxel, 0xAARRGGBB, fila por
// fila: el Vec<i32> de un lib/lienzo) con la esquina en (x, y), cada píxel
// como un cuadrado de escala x escala, mezclado por su alfa. En SCAR el Vec es
// un solo parámetro (`datos: Vec<i32>`): llega como puntero + largo, prestado
// durante la llamada. Usa una textura que se guarda entre cuadros y se rehace
// si cambia el tamaño. 0 si dibujó; 1 si el buffer es más chico que ancho x
// alto, o no hay ventana.
int scar_sdl_pixeles(const int32_t *datos, int64_t n, int ancho, int alto, int x, int y, int escala) {
    if (!g_ren || ancho <= 0 || alto <= 0 || n < (int64_t)ancho * (int64_t)alto) return 1;
    if (escala < 1) escala = 1;
    if (!g_tex_px || g_tex_w != ancho || g_tex_h != alto) {
        if (g_tex_px) SDL_DestroyTexture(g_tex_px);
        g_tex_px = SDL_CreateTexture(g_ren, SDL_PIXELFORMAT_ARGB8888, SDL_TEXTUREACCESS_STREAMING, ancho, alto);
        if (!g_tex_px) return 1;
        SDL_SetTextureBlendMode(g_tex_px, getenv("SCAR_SDL_NOBLEND") ? SDL_BLENDMODE_NONE : SDL_BLENDMODE_BLEND);
        g_tex_w = ancho;
        g_tex_h = alto;
    }
    if (SDL_UpdateTexture(g_tex_px, NULL, datos, ancho * 4) != 0) return 1;
    SDL_Rect dst = { x, y, ancho * escala, alto * escala };
    return SDL_RenderCopy(g_ren, g_tex_px, NULL, &dst) == 0 ? 0 : 1;
}

// scar_sdl_pixeles_ajustado(datos, n, ancho, alto, x, y, w, h) -> i32: como scar_sdl_pixeles, pero
// el buffer se estira a w x h píxeles de la ventana (cualquier tamaño, no solo múltiplos enteros):
// para que un juego llene la ventana o la pantalla completa sin cortarse. Agrandando se ve con
// píxeles nítidos; achicando, suavizado. 0 si dibujó.
int scar_sdl_pixeles_ajustado(const int32_t *datos, int64_t n, int ancho, int alto, int x, int y, int w, int h) {
    if (!g_ren || ancho <= 0 || alto <= 0 || w <= 0 || h <= 0 || n < (int64_t)ancho * (int64_t)alto) return 1;
    if (!g_tex_px || g_tex_w != ancho || g_tex_h != alto) {
        if (g_tex_px) SDL_DestroyTexture(g_tex_px);
        g_tex_px = SDL_CreateTexture(g_ren, SDL_PIXELFORMAT_ARGB8888, SDL_TEXTUREACCESS_STREAMING, ancho, alto);
        if (!g_tex_px) return 1;
        SDL_SetTextureBlendMode(g_tex_px, getenv("SCAR_SDL_NOBLEND") ? SDL_BLENDMODE_NONE : SDL_BLENDMODE_BLEND);
        g_tex_w = ancho;
        g_tex_h = alto;
    }
#if SDL_VERSION_ATLEAST(2, 0, 12)
    SDL_SetTextureScaleMode(g_tex_px, (w >= ancho && h >= alto) ? SDL_ScaleModeNearest : SDL_ScaleModeLinear);
#endif
    if (SDL_UpdateTexture(g_tex_px, NULL, datos, ancho * 4) != 0) return 1;
    SDL_Rect dst = { x, y, w, h };
    return SDL_RenderCopy(g_ren, g_tex_px, NULL, &dst) == 0 ? 0 : 1;
}

// ---- sonido de SCAR ----------------------------------------------------------
// scar_sdl_sonar(muestras, n, canales, tasa) -> i32: pone en la cola del
// parlante n muestras f64 entre -1 y 1 (los canales intercalados: el Vec<f64>
// de un audio.Sonido) y vuelve enseguida; suenan mientras el programa sigue.
// Abre el parlante la primera vez (y otra vez si cambian los canales o la
// tasa). 0 si quedó en la cola; 1 si no hay parlante (sin SDL de audio, o en
// una máquina sin sonido).
int scar_sdl_sonar(const double *m, int64_t n, int canales, int tasa) {
    static int sin_parlante = 0;   // si no se pudo abrir una vez, no se insiste
    if (canales < 1 || canales > 8 || tasa < 1000 || n < 0 || sin_parlante) return 1;
    if (!SDL_WasInit(SDL_INIT_AUDIO) && SDL_InitSubSystem(SDL_INIT_AUDIO) != 0) { sin_parlante = 1; return 1; }
    if (g_audio == 0 || g_audio_canales != canales || g_audio_tasa != tasa) {
        if (g_audio != 0) SDL_CloseAudioDevice(g_audio);
        SDL_AudioSpec quiero;
        SDL_zero(quiero);
        quiero.freq = tasa;
        quiero.format = AUDIO_F32SYS;
        quiero.channels = (Uint8)canales;
        quiero.samples = 1024;   // buffer corto: menos retardo (importa para el piano)
        g_audio = SDL_OpenAudioDevice(NULL, 0, &quiero, NULL, 0);
        if (g_audio == 0) { sin_parlante = 1; return 1; }
        g_audio_canales = canales;
        g_audio_tasa = tasa;
        SDL_PauseAudioDevice(g_audio, 0);
    }
    float buf[4096];
    int64_t i = 0;
    while (i < n) {
        int k = 0;
        for (; k < 4096 && i < n; k++, i++) {
            double x = m[i];
            buf[k] = (float)(x > 1.0 ? 1.0 : (x < -1.0 ? -1.0 : x));
        }
        if (SDL_QueueAudio(g_audio, buf, (Uint32)(k * sizeof(float))) != 0) return 1;
    }
    return 0;
}

// scar_sdl_sonando() -> i32: cuántas muestras quedan por sonar (0 si ya
// terminó, o si no hay parlante).
int scar_sdl_sonando(void) {
    if (g_audio == 0) return 0;
    return (int)(SDL_GetQueuedAudioSize(g_audio) / sizeof(float));
}

// scar_sdl_callar() -> i32: corta lo que está sonando y vacía la cola.
int scar_sdl_callar(void) {
    if (g_audio != 0) SDL_ClearQueuedAudio(g_audio);
    return 0;
}
