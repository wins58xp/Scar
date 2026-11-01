# Código y datos de terceros

SCAR se distribuye bajo la licencia MIT (ver `LICENSE`). Incluye estas piezas
de otros autores, cada una con su propia licencia:

## Ryu

`native/ryu/scar_ryu_d2d.h`: el algoritmo Ryu para escribir un `f64` como el
texto más corto que vuelve exactamente al mismo número.

- Autor: Ulf Adams, 2018 — https://github.com/ulfjack/ryu
- Licencia: Apache-2.0 o Boost Software License 1.0, a elección. Los textos
  están en `native/ryu/LICENSE-Apache2` y `native/ryu/LICENSE-Boost`.

## Fuentes DejaVu

`native/scarfuente.h` y `native/scarfuente_mono.h`: los caracteres de DejaVu
Sans y DejaVu Sans Mono, ya dibujados en píxeles, que usa la interfaz gráfica.

- https://dejavu-fonts.github.io/
- Licencia: la de Bitstream Vera Fonts (Copyright (c) 2003 Bitstream, Inc.),
  que permite usarlas, copiarlas y redistribuirlas; los cambios de DejaVu son
  de dominio público. El aviso completo va al principio de cada archivo; el
  texto entero está en https://dejavu-fonts.github.io/License.html

## Tablas de colores

`lib/colores.scar` trae tablas de colores tomadas de Matplotlib, para dar los
mismos colores que esa librería:

- las paletas `set1`, `set2`, `set3`, `dark2`, `paired`, `accent`, `pastel1`,
  `pastel2` y los mapas `rdbu`, `spectral`, `ylgnbu` y `greys` son de
  ColorBrewer (Cynthia Brewer, Mark Harrower y The Pennsylvania State
  University), bajo la licencia Apache-2.0;
- los mapas `viridis`, `magma`, `inferno` y `plasma` (Stéfan van der Walt y
  Nathaniel Smith) son de dominio público (CC0);
- el mapa `turbo` (Google LLC) está bajo la licencia Apache-2.0;
- `tab10`, `tab20`, `cividis`, `coolwarm` y `hot` vienen de Matplotlib, bajo la
  licencia de Matplotlib (estilo BSD, https://matplotlib.org/stable/project/license.html).

Los 148 nombres de color de CSS y la paleta de Okabe e Ito son datos publicados
(la especificación de CSS de W3C y Okabe & Ito, 2008).
