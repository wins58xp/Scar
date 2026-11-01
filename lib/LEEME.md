# lib/: la librería estándar de SCAR

Los módulos de esta carpeta se traen con `use` desde cualquier programa, sin
configurar nada: `use "gui"` busca primero `gui.scar` al lado del programa y,
si no está, acá (capítulo 10 del libro).

Cada módulo es un `.scar` sin `main`, escrito en SCAR. Lo que declara se usa con
su nombre adelante (`gui.boton(...)`); lo que empieza con `_` es privado del
módulo. El comentario del principio de cada archivo explica cómo usarlo, con
ejemplos.

- La lista completa, con la firma de cada función: el apéndice B del libro,
  [`libro/B_libreria_estandar.md`](../libro/B_libreria_estandar.md), que se
  genera desde estos archivos.
- Las pruebas: en [`pruebas/`](../pruebas/). Cada librería tiene su
  `pruebas/lib_<nombre>.scar` (se prueba a sí misma con la librería `prueba`) y,
  la mayoría, un `pruebas/test_<nombre>_python.py` que compara sus resultados
  con los de Python. `./pruebas/correr.sh` las corre todas.
