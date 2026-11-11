# Temas da interface

O tema escuro usa superfícies de carvão quente e detalhes em areia. O claro
conserva o canvas claro, cartões brancos e ações em teal. Os dois são desenhados
separadamente em `static/themes.css`; não se obtém um invertendo as cores do outro.

## Referências consultadas em 11/11/2026

- [Linear — Features](https://linear.app/features): base quase preta, diferenças
  discretas entre superfícies e cor concentrada em poucos pontos.
- [Bear](https://bear.app/): material público de temas e leitura com tons de papel,
  texto bem hierarquizado e controles que deixam o conteúdo em primeiro plano.
- [Readwise Reader](https://readwise.io/read): organização da leitura e realces
  localizados. Sua base azul não foi adotada como paleta do RhythmMind.

Essas referências orientam relações de superfície, hierarquia e proporção; não
foram copiados layouts, imagens ou tokens oficiais de outros produtos.

## Papéis do escuro

| Papel | Cor |
| --- | --- |
| Canvas | `#11100f` |
| Cartões | `#1a1816` |
| Campo e superfície interna | `#171513` |
| Menu e diálogo elevados | `#24211e` |
| Título | `#eee7dd` |
| Texto | `#ded6cc` |
| Texto de apoio | `#b9aea2` |
| Ação e seleção | `#d2b591` |
| Hover e foco | `#e2c8a7` |
| Texto sobre ação | `#211b15` |
| Divisores decorativos | `#3e3832` |
| Contorno de controles | `#85796a` |

Os grandes planos permanecem escuros. O bege identifica ações, seleção, foco e
pequenos detalhes; usá-lo como fundo de todos os cartões clarearia novamente a
tela. A onda perde os halos luminosos e varia entre tons quentes discretos.
Suavizar brilhos reduz ainda mais a opacidade da onda, sem mudar o tema.

Temperatura cromática, luminância, saturação e área ocupada orientam essas
escolhas. Nenhuma cor representa uma emoção universal. Sucesso, aviso e erro
conservam diferenças semânticas e mensagens textuais, em vez de se tornarem todos
bege.

## Leitura e interação

A referência normativa é a [WCAG 2.2](https://www.w3.org/TR/WCAG22/), especialmente
contraste de texto (1.4.3), contraste necessário de componentes (1.4.11), uso de
cor (1.4.1), foco (2.4.7/2.4.11) e alvos (2.5.8). Texto comum precisa de 4,5:1;
texto grande, 3:1. O contorno necessário para identificar um controle precisa
de 3:1 contra cores adjacentes. Divisores decorativos têm papel diferente.

Como referência de cálculo, título/painel apresenta 14,42:1, apoio/painel 8,13:1
e texto escuro/botão areia 8,73:1. Transparências, estados e fundos compostos
exigem medição no navegador; esses três pares não certificam toda a aplicação.

Tema, movimento e suavização continuam independentes. Movimento reduzido e
alto contraste do dispositivo são respeitados. Não usar `forced-color-adjust:
none` para combater filtros de escurecimento do navegador.

## Manutenção e verificação

- Os tokens `--theme-*` e os overrides de componentes ficam no bloco Dark de
  `static/themes.css`. Os aliases antigos de auth/workspace são remapeados no
  body; defini-los apenas no html não substitui as declarações locais.
- `static/theme.js` e o meta inicial de `static/index.html` devem acompanhar o
  canvas (`#11100f`). O script no head aplica a preferência antes da pintura.
- A animação Dark usa keyframes quentes próprios. O Light conserva sua animação.
- Alterações devem ser verificadas no acesso, home, relato, revisão, escuta,
  diário, catálogo e diálogos, incluindo hover, foco e estados desabilitados.
- Rodar a suíte Python e `node --test tests/js/*.mjs`. O teste visual opcional
  `tests/browser/verify_theme_rendering.py` requer Playwright/Pillow de QA e
  verifica a pintura do canvas com um navegador local CDP, sem ler dados pessoais.

No Light, `only light` solicita que o navegador preserve a paleta autoral. Algumas
configurações forçadas de Auto Dark podem ignorar isso; o ajuste não deve
desativar recursos de acessibilidade para tentar vencer esse filtro.
