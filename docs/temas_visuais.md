# Temas da interface

O tema escuro usa marinho profundo e acentos azuis dessaturados. O claro usa
papel/bege suave, cartões sem branco puro e ações azuis. Os dois são desenhados
separadamente em `static/themes.css`; não se obtém um invertendo as cores do outro.

## Referências consultadas em 11/11/2026

- [Linear — Features](https://linear.app/features): base quase preta, diferenças
  discretas entre superfícies e cor concentrada em poucos pontos.
- [Bear](https://bear.app/): material público de temas e leitura com tons de papel,
  texto bem hierarquizado e controles que deixam o conteúdo em primeiro plano.
- [Readwise Reader](https://readwise.io/read): organização da leitura e realces
  localizados, sem copiar a paleta do produto.

Essas referências orientam relações de superfície, hierarquia e proporção; não
foram copiados layouts, imagens ou tokens oficiais de outros produtos.

## Papéis dos temas

| Papel | Escuro (Oceano Noturno) | Claro (Névoa de Água e Sálvia) |
| --- | --- | --- |
| Canvas | `#08131c` | `#d7e8e6` |
| Cartões | `#0f1f2c` | `#e2f0ee` |
| Superfície interna | `#0b1822` | `#cadfdb` |
| Superfície elevada | `#152a3a` | `#eaf5f3` |
| Título | `#e6f2f5` | `#0f2930` |
| Texto | `#c6dce2` | `#1c3a43` |
| Texto de apoio | `#8fb0bc` | `#365660` |
| Ação e seleção | `#4cc9c0` | `#135d66` |
| Hover e foco | `#72dcd4` | `#0b464e` |
| Texto sobre ação | `#051b20` | `#f0faf8` |
| Divisores decorativos | `#1e3646` | `#acc6c4` |
| Contorno de controles | `#4d7888` | `#507680` |

No escuro, o azul aparece nas superfícies, na marca, nas ações e na onda, com
baixa saturação e sem halos. No claro, a luminância das grandes superfícies é
menor que a do branco puro: o fundo lembra papel e os cartões ficam próximos
desse tom. Ações azuis mantêm a identidade entre os temas. Suavizar brilhos reduz
a opacidade da onda nos dois, sem trocar o tema ou clarear a ilustração.

Temperatura cromática, luminância, saturação e área ocupada orientam essas
escolhas. Nenhuma cor representa uma emoção universal. Sucesso, aviso e erro
conservam diferenças semânticas e mensagens textuais.

## Leitura e interação

A referência normativa é a [WCAG 2.2](https://www.w3.org/TR/WCAG22/), especialmente
contraste de texto (1.4.3), contraste necessário de componentes (1.4.11), uso de
cor (1.4.1), foco (2.4.7/2.4.11) e alvos (2.5.8). Texto comum precisa de 4,5:1;
texto grande, 3:1. O contorno necessário para identificar um controle precisa
de 3:1 contra cores adjacentes. Divisores decorativos têm papel diferente.

Como referência de cálculo, texto/painel apresenta 11,41:1 no escuro e 7,37:1 no
claro; o texto escuro sobre a ação azul clara apresenta 7,71:1. Transparências,
estados e fundos compostos exigem medição no navegador; esses pares não
certificam toda a aplicação.

Tema, movimento e suavização continuam independentes. Movimento reduzido e
alto contraste do dispositivo são respeitados. Não usar `forced-color-adjust:
none` para combater filtros de escurecimento do navegador.

## Manutenção e verificação

- Os tokens `--theme-*` e os overrides de componentes ficam no bloco Dark de
  `static/themes.css`. Os aliases antigos de auth/workspace são remapeados no
  body; defini-los apenas no html não substitui as declarações locais.
- `static/theme.js` e o meta inicial de `static/index.html` devem acompanhar o
  canvas (`#0b1320` ou `#e7e2d8`). O script no head aplica a preferência antes da pintura.
- A animação Dark usa keyframes azuis próprios. O Light conserva sua animação.
- Alterações devem ser verificadas no acesso, home, relato, revisão, escuta,
  diário, catálogo e diálogos, incluindo hover, foco e estados desabilitados.
- Rodar a suíte Python e `node --test tests/js/*.mjs`. O teste visual opcional
  `tests/browser/verify_theme_rendering.py` requer Playwright/Pillow de QA e
  verifica a pintura do canvas com um navegador local CDP, sem ler dados pessoais.

No Light, `only light` solicita que o navegador preserve a paleta autoral. Algumas
configurações forçadas de Auto Dark podem ignorar isso; o ajuste não deve
desativar recursos de acessibilidade para tentar vencer esse filtro.
