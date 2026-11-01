// native/scarproc.c -- lanzar un programa y mirar si terminó, sin SDL (lib/editor y el IDE).
//
//   scar_proc_lanzar(args, salida, carpeta, anexar) -> pid
//        corre un programa por detrás, SIN shell: `args` son el programa y sus argumentos separados
//        por el carácter 0x1f (separador de unidad: no aparece en una ruta ni en un argumento
//        normal), y se lanza directo con execvp. Lo que escribe (salida y errores) va al archivo
//        `salida` (con anexar != 0 se agrega al final; si no, se reemplaza). Con `carpeta` no vacía,
//        el programa corre en esa carpeta. -1 si no pudo.
//   scar_proc_estado(pid) -> i32             -1 sigue corriendo; si terminó, su código de salida
//                                            (128 + señal si lo mataron). Cosecha el proceso: pedirlo
//                                            de nuevo después de terminar da -2.
//   scar_proc_matar(pid) -> i32              le manda SIGTERM a todo su grupo (y SIGKILL si no cede).
//   scar_proc_esperar(pid, ms) -> i32        espera hasta `ms` milisegundos a que termine.
//   scar_proc_mas_nuevo(a, b) -> i32         1 si el archivo `a` existe y es más nuevo que `b`.
//
// Sin shell en el medio (nada de `sh -c orden` armado como texto, donde un nombre de archivo mal
// citado podría meter otro comando): cada argumento llega tal cual al programa, sea cual sea su
// contenido.
//
// El programa lanzado no recibe entrada (stdin es /dev/null) y vive en su propio grupo de
// procesos, así que matarlo mata también lo que él haya lanzado (compilador -> binario).
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#define SCAR_PROC_SEP '\x1f'
#define SCAR_PROC_MAX_ARGS 256

// Escribe un mensaje en fd sin pasar por stdio (estamos en el hijo, después de fork).
static void escribir(int fd, const char *a, const char *b, const char *c) {
    const char *partes[3] = {a, b, c};
    for (int i = 0; i < 3; i++) {
        if (!partes[i]) continue;
        size_t n = strlen(partes[i]);
        while (n > 0) {
            ssize_t w = write(fd, partes[i], n);
            if (w <= 0) return;
            partes[i] += w;
            n -= (size_t)w;
        }
    }
}

int scar_proc_lanzar(const char *args, const char *salida, const char *carpeta, int anexar) {
    if (!args || !salida || !args[0]) return -1;
    // los argumentos se separan ANTES del fork (en el padre se puede usar malloc tranquilo)
    char *copia = strdup(args);
    if (!copia) return -1;
    char *argv[SCAR_PROC_MAX_ARGS + 1];
    int n = 0;
    char *p = copia;
    argv[n++] = p;
    for (; *p; p++) {
        if (*p == SCAR_PROC_SEP) {
            *p = '\0';
            if (n >= SCAR_PROC_MAX_ARGS) { free(copia); return -1; }
            argv[n++] = p + 1;
        }
    }
    argv[n] = NULL;
    if (argv[0][0] == '\0') { free(copia); return -1; }

    pid_t pid = fork();
    if (pid < 0) { free(copia); return -1; }
    if (pid == 0) {
        setpgid(0, 0);
        int flags = O_WRONLY | O_CREAT | (anexar ? O_APPEND : O_TRUNC);
        int fd = open(salida, flags, 0644);
        int nul = open("/dev/null", O_RDONLY);
        if (fd < 0 || nul < 0) _exit(127);
        dup2(nul, 0);
        dup2(fd, 1);
        dup2(fd, 2);
        close(fd);
        close(nul);
        if (carpeta && carpeta[0] && chdir(carpeta) != 0) {
            escribir(2, "no se pudo entrar a la carpeta ", carpeta, "\n");
            _exit(127);
        }
        execvp(argv[0], argv);
        escribir(2, "no se pudo ejecutar ", argv[0], ": ");
        escribir(2, strerror(errno), "\n", NULL);
        _exit(127);
    }
    free(copia);
    setpgid(pid, pid);  // por si el hijo todavía no lo hizo
    return (int)pid;
}

int scar_proc_estado(int pid) {
    int st = 0;
    pid_t r = waitpid((pid_t)pid, &st, WNOHANG);
    if (r == 0) return -1;
    if (r < 0) return -2;
    if (WIFEXITED(st)) return WEXITSTATUS(st);
    if (WIFSIGNALED(st)) return 128 + WTERMSIG(st);
    return -1;
}

static int sigue_vivo(int pid) {  // sin cosechar: el estado se pide después con scar_proc_estado
    return kill(-(pid_t)pid, 0) == 0;
}

int scar_proc_matar(int pid) {
    if (pid <= 1) return 1;
    kill(-(pid_t)pid, SIGTERM);
    for (int i = 0; i < 20; i++) {  // hasta 100 ms para que cierre solo
        if (!sigue_vivo(pid)) return 0;
        usleep(5000);
    }
    kill(-(pid_t)pid, SIGKILL);
    return 0;
}

// scar_proc_esperar(pid, ms) -> i32: espera hasta `ms` milisegundos a que termine; devuelve lo mismo que
// scar_proc_estado (-1 si sigue corriendo después de esperar). Sirve para órdenes cortas (un `ls`).
int scar_proc_esperar(int pid, int ms) {
    int r = scar_proc_estado(pid);
    int esperado = 0;
    while (r == -1 && esperado < ms) {
        usleep(2000);
        esperado += 2;
        r = scar_proc_estado(pid);
    }
    return r;
}

// scar_proc_mas_nuevo(a, b) -> i32: 1 si `a` existe y se modificó después que `b` (o `b` no existe);
// 0 si no. Lo que antes hacía `[ a -nt b ]` en el shell (¿el binario está al día con el .scar?).
int scar_proc_mas_nuevo(const char *a, const char *b) {
    struct stat sa, sb;
    if (!a || !b || stat(a, &sa) != 0) return 0;
    if (stat(b, &sb) != 0) return 1;
    if (sa.st_mtim.tv_sec != sb.st_mtim.tv_sec) return sa.st_mtim.tv_sec > sb.st_mtim.tv_sec;
    return sa.st_mtim.tv_nsec > sb.st_mtim.tv_nsec;
}
