// scarhttp.c — shim mínimo de HTTP(S) sobre libcurl para SCAR. Mismo espíritu que scarsdl.c: C hace solo lo que
// SCAR no puede hacer solo (TLS y HTTP); todo lo demás -- armar la URL, leer
// el JSON, interpretar los datos -- se hace en SCAR.
//
// La respuesta se guarda en un archivo y SCAR la lee con File.read_bytes():
// así el cuerpo puede traer cualquier byte (UTF-8, o un 0) y SCAR lo recorre
// por índice sin convertirlo a str.
//
//   extern "C" fn scar_http_a_archivo(url: str, cabeceras: str, ruta: str) -> i32 from "scarhttp"
//       GET de `url`; `cabeceras`: líneas "Nombre: valor" separadas por "\n"
//       ("" = ninguna). Devuelve el código HTTP (200, 404...) o -1 si no se
//       pudo hacer el pedido (sin red, DNS, TLS, timeout de 15 s); el
//       detalle queda en scar_http_error().
//   extern "C" fn scar_http_error() -> str from "scarhttp"
//   extern "C" fn scar_reloj_utc() -> f64 from "scarhttp"
//       segundos desde 1970-01-01 UTC (el reloj de pared; now() de SCAR es
//       monotónico y no sirve para fechas).
//   extern "C" fn scar_desfase_local() -> i32 from "scarhttp"
//       segundos al este de UTC de la hora local de la máquina (Chile: -10800
//       o -14400).
//   extern "C" fn scar_http_cancelar() -> i32 from "scarhttp"
//       corta los pedidos en curso (en a lo sumo ~1 s) y hace fallar los que
//       vengan después (-1, "cancelado"): para cerrar el programa sin esperar
//       el timeout de un servidor que no contesta.
//
// Apto para varios hilos a la vez (cada task con su pedido): curl_global_init
// una sola vez, un handle por pedido, sin señales, el error por hilo. Para
// eso el programa lo declara `extern lib "scarhttp" en_proceso`: en el worker
// aislado, todas las llamadas pasarían por un solo proceso, de a una.
//
// Compilar: gcc -shared -fPIC native/scarhttp.c -o libscarhttp.so -lcurl

#define _DEFAULT_SOURCE
#include <curl/curl.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static pthread_once_t g_curl_once = PTHREAD_ONCE_INIT;
static void iniciar_curl(void) { curl_global_init(CURL_GLOBAL_DEFAULT); }

// un mensaje por hilo: dos tasks pueden pedir a la vez
static __thread char g_error[256] = "";

const char *scar_http_error(void) { return g_error; }

static atomic_int g_cancelado = 0;

int scar_http_cancelar(void) {
    atomic_store(&g_cancelado, 1);
    return 0;
}

// curl la llama al menos una vez por segundo, también esperando respuesta:
// distinto de 0 corta el pedido (CURLE_ABORTED_BY_CALLBACK).
static int progreso(void *p, curl_off_t a, curl_off_t b, curl_off_t c, curl_off_t d) {
    (void)p; (void)a; (void)b; (void)c; (void)d;
    return atomic_load(&g_cancelado) ? 1 : 0;
}

static size_t escribir(void *ptr, size_t tam, size_t n, void *f) {
    return fwrite(ptr, tam, n, (FILE *)f);
}

int scar_http_a_archivo(const char *url, const char *cabeceras, const char *ruta) {
    pthread_once(&g_curl_once, iniciar_curl);
    g_error[0] = 0;
    if (atomic_load(&g_cancelado)) {
        snprintf(g_error, sizeof g_error, "cancelado");
        return -1;
    }
    FILE *f = fopen(ruta, "wb");
    if (!f) {
        snprintf(g_error, sizeof g_error, "no se pudo escribir %s", ruta);
        return -1;
    }
    CURL *c = curl_easy_init();
    if (!c) {
        fclose(f);
        snprintf(g_error, sizeof g_error, "curl_easy_init falló");
        return -1;
    }
    struct curl_slist *lista = NULL;
    if (cabeceras && *cabeceras) {
        // strtok_r y no strtok: strtok guarda su posición en una variable
        // global, y dos tasks pidiendo a la vez (usgs_vivo y mar_vivo en
        // sismografo_vivo) se pisaban el recorrido (data race que vio TSan).
        char *copia = strdup(cabeceras), *resto = NULL;
        for (char *l = strtok_r(copia, "\n", &resto); l; l = strtok_r(NULL, "\n", &resto))
            if (*l) lista = curl_slist_append(lista, l);
        free(copia);
    }
    curl_easy_setopt(c, CURLOPT_URL, url);
    curl_easy_setopt(c, CURLOPT_HTTPHEADER, lista);
    curl_easy_setopt(c, CURLOPT_WRITEFUNCTION, escribir);
    curl_easy_setopt(c, CURLOPT_WRITEDATA, f);
    curl_easy_setopt(c, CURLOPT_TIMEOUT, 15L);
    curl_easy_setopt(c, CURLOPT_CONNECTTIMEOUT, 8L);
    curl_easy_setopt(c, CURLOPT_FOLLOWLOCATION, 1L);
    curl_easy_setopt(c, CURLOPT_NOSIGNAL, 1L);  // hilos: sin señales de timeout
    curl_easy_setopt(c, CURLOPT_NOPROGRESS, 0L);
    curl_easy_setopt(c, CURLOPT_XFERINFOFUNCTION, progreso);
    curl_easy_setopt(c, CURLOPT_USERAGENT, "sismografo-scar/1.0");
    // lo local nunca va por un proxy del entorno (HTTP_PROXY/HTTPS_PROXY)
    curl_easy_setopt(c, CURLOPT_NOPROXY, "localhost,127.0.0.1,::1");
    CURLcode r = curl_easy_perform(c);
    long codigo = 0;
    curl_easy_getinfo(c, CURLINFO_RESPONSE_CODE, &codigo);
    curl_slist_free_all(lista);
    curl_easy_cleanup(c);
    fclose(f);
    if (r == CURLE_ABORTED_BY_CALLBACK) {
        snprintf(g_error, sizeof g_error, "cancelado");
        return -1;
    }
    if (r != CURLE_OK) {
        snprintf(g_error, sizeof g_error, "%s", curl_easy_strerror(r));
        return -1;
    }
    return (int)codigo;
}

// ---- pedidos completos para lib/https.scar ----------------------------------------------------
// Un pedido con método, cabeceras y cuerpo cualquiera (bytes). Todo queda en buffers del hilo
// (como el error): el código HTTP vuelve como resultado, y la respuesta se retira con
// scar_http_largo / scar_http_copiar (el Vec lo crea SCAR del largo justo, C lo llena).
//
//   extern "C" fn scar_https_pedido(cuerpo: Vec<i32>, metodo: str, url: str, cabeceras: str,
//                                   redirecciones: i32, segundos: i32, ca: str) -> i32 from "scarhttp"
//       `cuerpo`: los bytes a mandar (vacío = sin cuerpo). `redirecciones`: cuántas seguir (0 =
//       ninguna; las sigue curl: 301/302/303 pasan a GET, 307/308 conservan método y cuerpo, y en
//       un cambio de servidor no se manda Authorization). `segundos`: tiempo máximo. `ca`: archivo
//       con los certificados de confianza ("" = los del sistema). El certificado y el nombre del
//       servidor SIEMPRE se verifican. Devuelve el código HTTP o -1 (detalle en scar_http_error()).
//   extern "C" fn scar_http_largo(que: i32) -> i32          // 0 cuerpo, 1 cabeceras de todos los saltos
//   extern "C" fn scar_http_copiar(destino: Vec<i32>, que: i32) -> i32   // llena `destino` (un byte por entero)
//   extern "C" fn scar_http_url_final() -> str                // la URL después de las redirecciones
//   extern "C" fn scar_http_error_conexion() -> i32           // 1 si el fallo fue no poder conectar (se puede repetir)

#define SCAR_HTTP_MAX_RESP (256L * 1024 * 1024)

typedef struct { unsigned char *p; size_t n; int lleno; } Acum;
static __thread Acum g_cuerpo_r = {0}, g_cab_r = {0};
static __thread char g_url_final[2048] = "";
static __thread int g_err_conexion = 0;

static size_t acumular(void *ptr, size_t tam, size_t n, void *dest) {
    Acum *a = (Acum *)dest;
    size_t k = tam * n;
    if (a->n + k > (size_t)SCAR_HTTP_MAX_RESP) { a->lleno = 1; return 0; }
    unsigned char *q = realloc(a->p, a->n + k + 1);
    if (!q) { a->lleno = 1; return 0; }
    a->p = q;
    memcpy(a->p + a->n, ptr, k);
    a->n += k;
    return k;
}

static void vaciar(Acum *a) { free(a->p); a->p = NULL; a->n = 0; a->lleno = 0; }

#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wdeprecated-declarations"
int scar_https_pedido(const int32_t *cuerpo, int64_t ncuerpo, const char *metodo, const char *url,
                      const char *cabeceras, int redirecciones, int segundos, const char *ca) {
    pthread_once(&g_curl_once, iniciar_curl);
    g_error[0] = 0;
    g_url_final[0] = 0;
    g_err_conexion = 0;
    vaciar(&g_cuerpo_r);
    vaciar(&g_cab_r);
    if (atomic_load(&g_cancelado)) {
        snprintf(g_error, sizeof g_error, "cancelado");
        return -1;
    }
    CURL *c = curl_easy_init();
    if (!c) {
        snprintf(g_error, sizeof g_error, "curl_easy_init falló");
        return -1;
    }
    unsigned char *datos = NULL;
    if (ncuerpo > 0) {
        datos = malloc((size_t)ncuerpo);
        if (!datos) {
            curl_easy_cleanup(c);
            snprintf(g_error, sizeof g_error, "sin memoria para el cuerpo");
            return -1;
        }
        for (int64_t i = 0; i < ncuerpo; i++) datos[i] = (unsigned char)(cuerpo[i] & 255);
    }
    struct curl_slist *lista = NULL;
    if (cabeceras && *cabeceras) {
        char *copia = strdup(cabeceras), *resto = NULL;
        for (char *l = strtok_r(copia, "\n", &resto); l; l = strtok_r(NULL, "\n", &resto))
            if (*l) lista = curl_slist_append(lista, l);
        free(copia);
    }
    const char *m = (metodo && *metodo) ? metodo : "GET";
    curl_easy_setopt(c, CURLOPT_URL, url);
    if (strcmp(m, "HEAD") == 0) {
        curl_easy_setopt(c, CURLOPT_NOBODY, 1L);
    } else if (ncuerpo > 0 || strcmp(m, "POST") == 0 || strcmp(m, "PUT") == 0 || strcmp(m, "PATCH") == 0) {
        curl_easy_setopt(c, CURLOPT_POSTFIELDS, datos ? (char *)datos : "");
        curl_easy_setopt(c, CURLOPT_POSTFIELDSIZE_LARGE, (curl_off_t)(ncuerpo > 0 ? ncuerpo : 0));
        if (strcmp(m, "POST") != 0) curl_easy_setopt(c, CURLOPT_CUSTOMREQUEST, m);
    } else if (strcmp(m, "GET") != 0) {
        curl_easy_setopt(c, CURLOPT_CUSTOMREQUEST, m);
    }
    curl_easy_setopt(c, CURLOPT_HTTPHEADER, lista);
    curl_easy_setopt(c, CURLOPT_WRITEFUNCTION, acumular);
    curl_easy_setopt(c, CURLOPT_WRITEDATA, &g_cuerpo_r);
    curl_easy_setopt(c, CURLOPT_HEADERFUNCTION, acumular);
    curl_easy_setopt(c, CURLOPT_HEADERDATA, &g_cab_r);
    curl_easy_setopt(c, CURLOPT_TIMEOUT, (long)(segundos > 0 ? segundos : 30));
    curl_easy_setopt(c, CURLOPT_CONNECTTIMEOUT, 10L);
    curl_easy_setopt(c, CURLOPT_FOLLOWLOCATION, redirecciones > 0 ? 1L : 0L);
    curl_easy_setopt(c, CURLOPT_MAXREDIRS, (long)redirecciones);
    curl_easy_setopt(c, CURLOPT_POSTREDIR, 0L);  // 301/302/303 -> GET; 307/308 conservan el método
    curl_easy_setopt(c, CURLOPT_PROTOCOLS, (long)(CURLPROTO_HTTP | CURLPROTO_HTTPS));
    curl_easy_setopt(c, CURLOPT_REDIR_PROTOCOLS, (long)(CURLPROTO_HTTP | CURLPROTO_HTTPS));
    curl_easy_setopt(c, CURLOPT_ACCEPT_ENCODING, "");  // gzip/deflate/br si hay: curl los abre solo
    curl_easy_setopt(c, CURLOPT_NOSIGNAL, 1L);
    curl_easy_setopt(c, CURLOPT_NOPROGRESS, 0L);
    curl_easy_setopt(c, CURLOPT_XFERINFOFUNCTION, progreso);
    curl_easy_setopt(c, CURLOPT_USERAGENT, "scar-https/1.0");
    curl_easy_setopt(c, CURLOPT_SSL_VERIFYPEER, 1L);
    curl_easy_setopt(c, CURLOPT_SSL_VERIFYHOST, 2L);
    curl_easy_setopt(c, CURLOPT_NOPROXY, "localhost,127.0.0.1,::1");
    if (ca && *ca) curl_easy_setopt(c, CURLOPT_CAINFO, ca);
    CURLcode r = curl_easy_perform(c);
    long codigo = 0;
    curl_easy_getinfo(c, CURLINFO_RESPONSE_CODE, &codigo);
    char *fin = NULL;
    if (curl_easy_getinfo(c, CURLINFO_EFFECTIVE_URL, &fin) == CURLE_OK && fin)
        snprintf(g_url_final, sizeof g_url_final, "%s", fin);
    curl_slist_free_all(lista);
    curl_easy_cleanup(c);
    free(datos);
    if (r == CURLE_ABORTED_BY_CALLBACK) {
        snprintf(g_error, sizeof g_error, "cancelado");
        return -1;
    }
    if (g_cuerpo_r.lleno || g_cab_r.lleno) {
        snprintf(g_error, sizeof g_error, "la respuesta pasa del máximo (256 MB)");
        return -1;
    }
    if (r == CURLE_TOO_MANY_REDIRECTS) {  // el texto de curl cambia entre versiones: uno fijo
        snprintf(g_error, sizeof g_error, "demasiadas redirecciones (más de %d)", redirecciones);
        return -1;
    }
    if (r != CURLE_OK) {
        snprintf(g_error, sizeof g_error, "%s", curl_easy_strerror(r));
        if (r == CURLE_COULDNT_CONNECT || r == CURLE_COULDNT_RESOLVE_HOST) g_err_conexion = 1;
        return -1;
    }
    return (int)codigo;
}
#pragma GCC diagnostic pop

int scar_http_largo(int que) { return (int)(que == 0 ? g_cuerpo_r.n : g_cab_r.n); }

int scar_http_copiar(int32_t *destino, int64_t n, int que) {
    Acum *a = que == 0 ? &g_cuerpo_r : &g_cab_r;
    int64_t k = n < (int64_t)a->n ? n : (int64_t)a->n;
    for (int64_t i = 0; i < k; i++) destino[i] = a->p[i];
    return (int)k;
}

const char *scar_http_url_final(void) { return g_url_final; }
int scar_http_error_conexion(void) { return g_err_conexion; }

double scar_reloj_utc(void) {
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
}

int scar_desfase_local(void) {
    time_t ahora = time(NULL);
    struct tm local;
    localtime_r(&ahora, &local);
    return (int)local.tm_gmtoff;
}
