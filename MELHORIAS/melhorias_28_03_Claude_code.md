Arquitetura e Confiabilidade

  1. Structured Output nas chamadas LLM
  Hoje o sistema usa regex para extrair campos como TIPO_PENALIDADE:, TEM_FLAGRANTE:, RECORRENTE: da resposta textual do
   Gemini. Se o modelo reformatar a saída levemente, o parsing falha silenciosamente. Usar response_schema (Gemini) ou  
  tool_use (Anthropic) força o modelo a retornar JSON estruturado — elimina toda a camada de regex frágil.

  2. Fallback entre LLMs com circuit breaker
  Se Gemini estiver fora, o sistema trava. Se Anthropic não estiver configurado, retorna placeholder. Falta uma
  estratégia explícita: Gemini primário → Anthropic fallback (ou vice-versa) com timeout e retry controlado por fase.

  3. data_infracao tem fallback errado
  jari_engine.py:505: se nenhuma data for extraída da tabela, o código usa self.parecer.data_protocolo como data da
  infração. Isso é matematicamente errado — data do protocolo é sempre posterior à infração. O fallback correto seria
  bloquear e pedir reenvio dos documentos.

  4. Extração de datas por posição é frágil
  datas_processadas[0] = infração, datas_processadas[1] = notificação. Se o Gemini inserir uma data extra no topo da
  tabela (ex: data da sessão no cabeçalho), todos os cálculos da Fase 3 ficam errados. A extração deveria ser por rótulo
   (Data da Infração:, Data da Notificação:), não por posição.

  ---
  Qualidade dos Cálculos

  1. Marcos interruptivos não são validados
  Qualquer data entre infração e sessão vira marco interruptivo da prescrição punitiva. Na prática, uma data de
  protocolo interno, despacho administrativo ou autuação acessória pode reiniciar indevidamente o prazo de 5 anos. O
  Gemini deveria classificar cada data com um tipo e só datas de tipo [notificacao, decisao, impugnacao] deveriam ser
  aceitas como marcos.

  2. Suspensão por pontuação não é tratada
  logica_jari.md §201: para suspensão por acúmulo de pontos, o marco inicial da prescrição é o dia seguinte à
  totalização. O sistema não captura essa data na Fase 1 e assume data_infracao. Casos de suspensão por pontos recebem  
  cálculo errado silenciosamente.

  3. COVID discount hardcoded e sem transparência
  Os 256 dias estão como constante mágica. Deveria ser INICIO_COVID = date(2020, 3, 20) e FIM_COVID = date(2020, 11, 30)
   com o cálculo explícito (FIM_COVID - INICIO_COVID).days, deixando a origem do número rastreável.

  ---
  Robustez da Fase 2 (Extração de Documentos)

  1. PDF ilegível não tem tratamento de qualidade
  Se o PDF for digitalizado (imagem sem OCR), o PyMuPDF extrai texto vazio e o Gemini trabalha com contexto nulo. O
  sistema deveria detectar PDFs com menos de N caracteres extraídos e avisar explicitamente o julgador antes de
  prosseguir.

  2. Sem validação de consistência após extração
  Após a Fase 2, o sistema aceita qualquer tabela que o Gemini gerar. Não há checagem se data_infracao <
  data_notificacao < data_sessao. Inversões de data (erros do LLM) passam silenciosamente para os cálculos matemáticos.

  ---
  Testabilidade e Observabilidade

  1. Sem testes de integração das fases
  Os 44 testes cobrem unidades isoladas. Não existe um teste que rode o fluxo completo Fase 1 → 2 → 3 → 31 → 5 → 6 com  
  dados reais mockados. Uma regressão entre fases (ex: campo salvo errado no save()) não seria capturada.

  2. Sem rastreabilidade do motivo de cada resultado
  Quando o parecer sai DEFERIDO por decadência, não há log estruturado dizendo: "decadencia=True por FILTRO 3,
  marco=data_conclusao_multa=15/03/2022, dias=192". Diagnóstico de erros depende de ler o texto do parecer gerado pelo  
  LLM.

  3. blindagem_score sem baseline
  O score de 0–100 é calculado por deduções arbitrárias mas não há histórico de distribuição. Não dá para saber se um
  score 70 é bom ou ruim para o conjunto de pareceres daquela JARI.

  ---
  UX e Fluxo do Julgador

  1. Sem possibilidade de voltar de fase
  Se o julgador percebe na Fase 31 que informou uma data errada na Fase 1, não há como voltar. O sistema só avança. Um  
  botão "Reiniciar do início" ou "Corrigir data" seria suficiente.

  2. Fase 2 não destaca datas suspeitas para o julgador
  A tabela de datas é exibida como markdown puro. Datas com POSSÍVEL (1)/(2) ou NÃO LOCALIZADO deveriam ser visualmente
  destacadas (cor diferente no frontend) para forçar atenção antes do 'ok'.

  3. Ausência de preview do parecer antes da Fase 6
  O julgador só vê o parecer depois da auditoria. Seria útil um preview editável antes do blindagem, permitindo corrigir
   erros factuais (nome errado, número de PA) sem precisar refazer todo o fluxo.

  ---
  Segurança e Operação

  1. Upload de PDFs sem validação de conteúdo
  O sistema valida extensão mas não valida se o arquivo é realmente um PDF (magic bytes). Um arquivo malicioso renomeado
   como .pdf passa pela checagem atual.

  2. Sem limite de tamanho por fase no histórico de chat
  tabela_datas_sensiveis, admissibilidade_texto, tese, analise_tese_texto são concatenados nos prompts sem limite. Em
  processos com muitas páginas, o contexto pode estourar o limite de tokens da API silenciosamente, com a resposta sendo
   truncada.

  3. ANTHROPIC_API_KEY ausência bloqueia produção sem fallback
  Hoje retorna erro explícito (fix desta sessão), mas deveria ter fallback automático para Gemini quando Anthropic está
  indisponível, já que Gemini já tem validate_and_generate_parecer implementado.

  ---
  Prioridades sugeridas

  ┌────────────────────────────────────┬───────────────────────────────────┐
  │             Prioridade             │               Itens               │
  ├────────────────────────────────────┼───────────────────────────────────┤
  │ 🔴 Alta (afeta resultado jurídico) │ 4, 5, 6                           │
  ├────────────────────────────────────┼───────────────────────────────────┤
  │ 🟡 Média (afeta confiabilidade)    │ 1, 2, 3, 8, 9, 18                 │
  ├────────────────────────────────────┼───────────────────────────────────┤
  │ 🟢 Baixa (melhoria de qualidade)   │ 7, 10, 11, 12, 13, 14, 15, 16, 17 │
  └────────────────────────────────────┴───────────────────────────────────┘
