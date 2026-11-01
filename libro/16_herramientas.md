# 16. Herramientas: formato, editor y pruebas

## 16.1 `scar fmt`

`scar fmt` arregla la sangría de un archivo: 4 espacios por nivel de llaves,
con el estilo de todos los ejemplos de este libro.

```
scar fmt programa.scar            # muestra el resultado, sin tocar el archivo
scar fmt programa.scar --write    # lo guarda en el archivo (o -w)
scar fmt programa.scar --check    # no muestra nada; sale con 1 si falta formatear
```

`fmt` solo cambia la sangría: no toca los espacios dentro de una línea, no
parte ni junta líneas, y deja los comentarios como están. Así nunca cambia lo
que hace el programa.

```scar
fn main() {
for i in 0..3 {
if i > 0 {
print(i)
}
}
}
```

Con `scar fmt` queda:

```scar
fn main() {
    for i in 0..3 {
        if i > 0 {
            print(i)
        }
    }
}
```

`--check` sirve para un script o una integración continua: falla si alguien
subió código sin formatear.

## 16.2 `scar check`

`scar check` revisa uno o varios archivos sin correrlos, y termina con 1 si
alguno tiene errores:

```
scar check *.scar
```

Es lo que conviene correr antes de compartir código, o en un script que
revise un proyecto entero.

## 16.3 Tu editor: `scar lsp`

SCAR trae un servidor de lenguaje (LSP), el protocolo que usan casi todos los
editores modernos (VS Code, Neovim, Helix, Emacs, Zed, Kate...) para hablar con
las herramientas de un lenguaje. Con él, el editor:

- marca los errores **mientras escribes**, con el mismo mensaje que daría
  `scar check`, sin guardar el archivo;
- **completa** nombres: palabras del lenguaje, tus funciones y structs, las
  variables visibles en ese punto, y los campos y métodos al escribir un `.`.

El editor lanza `scar lsp` y le habla por la entrada y salida estándar. Cómo
se configura depende del editor. En **Neovim** (0.11 o más nuevo):

```lua
vim.filetype.add({ extension = { scar = "scar" } })
vim.lsp.config("scar", { cmd = { "scar", "lsp" }, filetypes = { "scar" } })
vim.lsp.enable("scar")
```

En **Helix**, en `languages.toml`:

```toml
[language-server.scar]
command = "scar"
args = ["lsp"]

[[language]]
name = "scar"
scope = "source.scar"
file-types = ["scar"]
comment-token = "#"
language-servers = ["scar"]
```

En **VS Code** hace falta una extensión que conecte un servidor genérico (por
ejemplo, una de las que se buscan como "generic LSP client"), con el comando
`scar lsp` para los archivos `.scar`.

## 16.4 Probar tu código

La librería `prueba` (capítulo 10) sirve para que un programa se pruebe a sí
mismo: cada afirmación cuenta, y `prueba.terminar` da el código de salida (0
si todo pasó). Así un script puede correr todas tus pruebas y saber si algo
falló:

```
for f in pruebas/*.scar; do scar run "$f" || echo "FALLÓ: $f"; done
```

Una buena costumbre en SCAR es probar las dos formas de correr: si un
programa da distinto con `scar run` que compilado, eso es un error del
lenguaje, y vale la pena reportarlo.

## 16.5 Ejercicios

1. Desordena la sangría de un ejemplo del libro y arréglala con `scar fmt -w`.
2. Configura tu editor con `scar lsp` y escribe un error a propósito: mira
   cómo aparece mientras escribes.
3. Escribe un archivo de pruebas con `prueba` para el ejemplo del capítulo 6 y
   haz que una prueba falle a propósito. ¿Qué código de salida da?

El programa de este capítulo está en `ejemplos/16_herramientas.scar`.
