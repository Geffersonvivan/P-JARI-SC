Oportunidades de melhoria — Layout e UX

  🔴 Crítico (afeta uso direto)

  1. Nenhuma confirmação antes de excluir processos
  O ícone de lixeira na sidebar exclui o processo instantaneamente, sem modal de confirmação. Um clique acidental é
  irreversível.

  2. Nenhum feedback visual ao selecionar um projeto
  Ao clicar num processo na sidebar, não há highlight, spinner, nem cor diferente para indicar qual está ativo. O
  usuário não sabe o que está selecionado.

  3. Editor de parecer não avisa sobre mudanças não salvas
  Se o julgador edita o TinyMCE e fecha a aba, perde tudo sem aviso. Falta um beforeunload com "Você tem alterações não
  salvas."

  4. Botões de exportação sem estado de carregamento
  "Exportar PDF" e "Exportar Word" no editor não desabilitam nem mostram spinner após clique. Usuários clicam várias  
  vezes achando que não funcionou.

  5. data_infracao extraída por posição, não por rótulo
  Se o Gemini inserir uma data extra no topo da tabela Fase 2, datas_processadas[0] deixa de ser a infração — todos os
  cálculos matemáticos ficam errados silenciosamente. (Já reportado como bug de sistema, mas visível ao usuário como
  resultado incorreto sem aviso.)

  ---
  🟡 Médio (prejudica experiência)

  1. Sidebar sem destaque do item atual (home.html)
  Ao abrir uma pasta, não há indicador visual de qual está expandida. Com 10+ pastas, o julgador perde a referência de  
  onde está.

  2. Tooltips de projetos transbordam a tela em mobile
  Os tooltips de 260px na sidebar são absolute left-4 top-8. Em telas de 375px com sidebar de 280px, o tooltip
  ultrapassa a borda da tela à direita.

  3. Split-view PDF/chat não empilha em mobile
  O painel split (flex-row) não tem override flex-col para telas pequenas. Em celular, o PDF e o chat ficam lado a lado
  inutilizáveis.

  4. Card "Pro" com scale-105 quebra o alinhamento do grid (planos.html)
  Em 1024px, o card Pro fica 5% maior e desalinha o grid. O destaque deveria ser feito com borda colorida ou sombra, não
   com escala.

  5. Dois sets de tabs no editor causam confusão hierárquica
  "Agente JARI / Teses" (Master Tabs) e dentro de Teses "Minhas Teses / Comunidade" (Sub-Tabs) têm visual idêntico. O
  julgador não percebe que são níveis diferentes.

  6. FAQ da página de planos começa 100% fechado
  O item mais importante ("Preciso assinar?") está oculto. Pelo menos 1–2 itens deveriam abrir por padrão.

  7. Área do Agente JARI no editor não tem exemplos de uso
  O painel do agente exibe apenas um emoji e "Como posso ajudar?". Sem exemplos de prompts, o julgador não descobre o
  que pode pedir.

  8. Painel PDF sem botão visível no desktop
  "Visualizar Processo" aparece só no header mobile. No desktop não há forma óbvia de abrir o painel PDF — o botão está
  escondido ou ausente.

  ---
  🟢 Baixo (polimento e manutenção)

  1. Navbar inexistente no mobile da landing page
  Os links de navegação usam hidden md:flex. Em celular não há hambúrguer, não há menu — os usuários não conseguem
  navegar pelas seções.

  2. Animação animate-glow-pulse sem prefers-reduced-motion
  Para usuários com sensibilidade vestibular, animações pulsantes podem causar desconforto. Falta a media query @media
  (prefers-reduced-motion: reduce).

  3. Z-indices mágicos espalhados
  z-10, z-40, z-50, z-[100], z-[120] sem escala central. Qualquer novo modal ou tooltip pode gerar conflito de
  sobreposição difícil de depurar.

  4. Markup de cards duplicado 5+ vezes
  Os cards de pasta, processo, tese e plano têm estrutura quase idêntica copiada manualmente. Deveriam ser macros Jinja2
   ou componentes reutilizáveis.

  5. Tailwind config duplicada em múltiplos templates
  O bloco tailwind.config (cores, keyframes, plugins) está repetido em home.html e landing.html. Deveria estar num único
   arquivo CSS compilado.

  6. Sem estado vazio com ação nos tooltips de pasta vazia
  "Vazia" aparece como texto puro. Deveria ser um estado vazio com ícone e botão "+ Criar processo".

  7. Texto gradiente sem fallback de contraste
  -webkit-background-clip: text em títulos da landing e planos pode falhar o WCAG AA em alguns browsers/OS. Falta uma
  cor sólida como fallback.

  ---
  Resumo de prioridades

  ┌──────────────┬────────────┬─────────────────────────────────────────────────────────────────────────┐
  │  Prioridade  │ Quantidade │                                Exemplos                                 │
  ├──────────────┼────────────┼─────────────────────────────────────────────────────────────────────────┤
  │ 🔴 Crítico   │ 5          │ Excluir sem confirmação, seleção sem feedback, perda de dados no editor │
  ├──────────────┼────────────┼─────────────────────────────────────────────────────────────────────────┤
  │ 🟡 Médio     │ 8          │ Sidebar sem destaque, tooltips overflow, tabs confusas, FAQ fechado     │
  ├──────────────┼────────────┼─────────────────────────────────────────────────────────────────────────┤
  │ 🟢 Polimento │ 6          │ Animações, z-index, duplicação de markup, navbar mobile                 │
  └──────────────┴────────────┴─────────────────────────────────────────────────────────────────────────┘
