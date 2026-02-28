# Jornada do Processo de Parecer - Motor P-JARI/SC

Este documento detalha minuciosamente, passo a passo, como o motor inteligente JARI (no arquivo `chat/jari_engine.py` e `chat/integrations.py`) processa a solicitação do usuário, desde as primeiras interações até a tela de apresentação do Parecer Final e auditoria de blindagem.

---

### Passo 1: Início da Jornada e Criação do Projeto

O usuário digita "**iniciar**" no chat.
O sistema de backend intercepta essa palavra e:

- Checa se o usuário tem limite de créditos ou se está logado.
- Caso esteja autorizado, cria no banco de dados um objeto `Parecer` (um projeto de parecer "Rascunho") com `status_fase = 1`.

### Passo 2: Coleta e Identificação (Fase 1)

O motor entra em modo de coleta obrigatória e sequencial. Ele não avança para a próxima pergunta se o dado não for validado.

- O motor apresenta a **Pergunta 1**: Solicita a **Data da Sessão de Julgamento**. O formato precisa ser exatamente `DD/MM/AAAA`. Se o usuário digitar algo diferente (ex: "10 de maio"), o sistema acusa erro e repete a pergunta.
- Validadas as datas, ele pede o **PA**.
- Pede o **SGPE**.
- Pede o **Prazo Final** do Protocolo (`DD/MM/AAAA`).
- Pede a **Data do Protocolo** do Recurso (`DD/MM/AAAA`).
- Pede as **Páginas da Defesa** (ex: "15 a 24").
- Por fim, o motor exibe a opção de fazer o upload em PDF da Autuação e Consolidado.
  - *Detalhe Técnico:* O usuário anexa no clipe e diz "ok". O frontend submete o arquivo multipart/form-data. O servidor salva o arquivo físico temporariamente na pasta `media/uploads` e anexa os caminhos aos campos no banco de dados do projeto.

### Passo 3: Diretriz de Integridade (Fase 2)

Após a coleta completa de dados e anexos, o status do motor avança para `status_fase = 2`.

- O sistema apresenta na tela um mega resumo de tudo que foi coletado até ali listado.
- Pede a confirmação do usuário: Apenas as palavras "**ok**" ou "**corrigir**".
- Se o usuário digitar "corrigir", o sistema apaga os 7 atributos do banco de dados desse projeto, deleta os PDFs anexados, zera a `status_fase` para 1, e recomeça a perguntar.
- Se digitar "ok", o motor avança silenciosamente para a `Fase 3` e engatilha em background o processo de Avaliação de Prazos (Passo 4).

### Passo 4: Geração da Tabela de Admissibilidade P1 (Fase 3 e 31)

Ao assumir o processamento da `Fase 3`, o motor Python (via `JariEngine.run_phase_3()`) solicita à classe `GeminiClient` do arquivo de integrações que elabore o **Relatório de Admissibilidade**.

- A Inteligência Artificial Gemini 2.0 (Google) recebe todo o contexto extraído e também recebe os arquivos PDFs enviados nativamente (File API) para análise integral das páginas.
- Ela extrai as datas de expedição das notificações, infração e confere infrações de recursos para gerar uma verificação completa: Tempestividade, Prescrição Punitiva, Decadência e a Prescrição Intercorrente (calculando especificamente a diferença em dias corridos entre a Data da Sessão de Julgamento P1 e o Protocolo do Recurso P5).
- O motor salva esse grande texto de tabela no banco (`admissibilidade_texto`) e passa imediatamente para a **Fase 31**.
- Na interface `Fase 31`, o Motor escreve na tela a tabela recém gerada e espera uma resposta: "**ok**" para concordar com o cálculo do LLM, ou "**divergência**".

### Passo 5: Heurística da Admissibilidade e Filtro de Mérito (Salto Condicional)

Se o usuário digitou "**ok**" na Fase 31, o sistema avalia antes de avançar se vale a pena analisar teses complexas:

- O motor usa uma leitura de código local (Expressão Regular - regex) para ler estruturalmente a Tabela gerada pela Inteligência artificial.
- Se a inteligência concluiu explicitamente no bloco de Admissibilidade termos como *"Conclusão: Intempestivo"*, *"Decadência"*, ou *"Ocorrência de Prescrição"*, o motor interrompe o fluxo normal.
- Ele envia um alerta na tela: *"⚠️ Mérito Prejudicado pela Admissibilidade Negativa..."* e injeta no código um título de Tese fixo: **"MÉRITO PREJUDICADO"**. Desse ponto, o motor pula **diretamente para o Passo 8 (Fase 5)** para gerar um Parecer de dispensa, **sem perguntar por teses.**
- Se estiver tudo Tempestivo e sem Prescrição, o motor vai tranquilamente para a Fase 4.

### Passo 6: Oitiva das Teses da Defesa (Fase 4)

Se for Tempestivo:

- O sistema pede objetivamente: *"descreva em poucas palavras a tese principal de defesa..."*.
- O Assessor digita as alegações (Ex: Falta de sinalização no local ou erro de aferição do radar) e o sistema salva isso como a `tese` oficial do banco.

### Passo 7: Análise Contextual das Teses (Fase 41)

O texto da tese recém fornecido viaja para as funções cognitivas do motor em formato *"cross-check"* em três etapas:

1. **Vertex AI Search (Inventário Normativo/Jurisprudencial):** É acionada antecipadamente para vasculhar nos arquivos indexados oficiais da JARI se já existe jurisprudência pacificada interna sobre aquela exata tese.
2. **Perplexity AI:** Na sequência, é acionada com a tese e requisita uma pesquisa complementar na Web global e resoluções do CONTRAN.
3. **Gemini 2.0:** Recebe a Tese, a leitura dos PDFs reais de processo, o retorno cirúrgico jurisdicional prioritário do Vertex e o retorno global do Perplexity.

- A IA do Gemini tenta formar um Veredito Prévio e justificar *"Sendo assim, sugiro: CONCLUSÃO: NÃO ACOLHIDA / ACOLHIDA"*.
- Esse bloco textual vai para a tela (na etapa código `Fase 41`) e o sistema pausa de novo. *"Confirme ok ou desconsidere"*. Ao dar "ok", o motor vai para a Fase de Construção.

### Passo 8: Geração do Bloco Único de Parecer (Fase 5)

O sistema tem autorização final. No método de construção global da IA (`validate_and_generate_parecer`), ele passa uma instrução severa (Diretrizes Estritas), **carregando o histórico total processual das Fases 3 e 4**:

- A IA recebe a Memória Cumulativa do Processo (Textos de Admissibilidade da Fase 3 e Análise Prévia da Fase 41), além dos achados fixados do Vertex/Perplexity e os dados que serão impressos: PROCESSO, SGPE, RECORRENTE (Documento "Autuação" linha "Interessado"), RELATOR (Nome e Sobrenome de quem está logado no sistema) e a DATA.
- E principalmente a matriz Anti-Alucinação: se as ferramentas não fornecem amparo normativo/documental para uma alegação esdrúxula, ela obrigatoriamente preencherá: *"NÃO LOCALIZADO nos documentos anexados (Doc/Pág)."*
- O bloco gerado (que vai desde o Ementa até a Fundamentação Numérica 5 - Garantias, obedecendo regras da Fase 5 do projeto) é mantido em memória do servidor.

### Passo 9: Limpeza de Arquivos Locais Táticos (Otimização)

Nesse exato instante (entre a F5 e F7), após terminar todas as análises de PDFs e não precisar mais das IA lendo as centenas de páginas processuais, uma instrução em python da view apaga fisicamente do servidor (HD/Media) os PDFs salvos para que não sobrecarreguem nossa nuvem no Railway ou servidor de upload com arquivos inservíveis, além de varrer os nomes da base de dados do projeto.

### Passo 10: Salvamento Consciente (Fase 7)

O sistema então envia pra tela a lista final: *"Selecione qual pasta você quer salvar"*.

- O motor lista `1. Outros` e as pastas dinâmicas do usuário que já foram criadas ali no painel esquerdo. O usuário digita "2" e aperta Enter e ele encerra a categorização.

### Passo 11: A Apresentação Final (Fase 8)

Nesta fase (que é tecnicamente uma mensagem de finalização), o sistema renderiza tudo formatado na tela de chat: o Parecer Bloco Único junto com a mensagem "Salvo com sucesso na Pasta escolhida".
Nesse exato instante do frontend, se a resposta foi dada com "fase: 8" o navegador entende a solicitação e exibe um Toast (alerta flutuante) verde no topo e faz dois gatilhos:

1. `location.reload()` para a barra lateral puxar os dados mais novos do banco e aparecer o processo guardado e mapeado lá para consulta eterna.
2. A tela abre com o seu novo processo mostrando o resultado. Se houver discrepância por formatação ou desejo do usuário, ele pode a qualquer momento abrir o "Editor" nativo do sistema do PARECER FINAL, formatando num editor rico, usando as variáveis predefinidas para transformar num documento PDF no final.
