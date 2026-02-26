# Lógica de Execução - Motor P-JARI (jari_engine.py)

A lógica estabelecida no **Workflow: System P-JARI** está sendo estritamente seguida no motor do aplicativo, com clara separação de responsabilidades entre coleta, validação humana, operações matemáticas e análise com Inteligência Artificial.

Abaixo o fluxo passo a passo de como o motor executa as regras sob os panos:

### FASE 1: Coleta e Identificação (F1)

**O que acontece:** O sistema aborda o usuário de forma sequencial solicitando os dados primários do processo. Ele não avança para o próximo dado até que o atual tenha sido validado e salvo no banco de dados.

- **Passo a passo:**
  1. Pergunta **Data da Sessão**. Se errar o formato, alerta e pede novamente.
  2. Pergunta o **Número do PA**.
  3. Pergunta o **Número do SGPE**.
  4. Pergunta o **Prazo Final** estipulado para o protocolo.
  5. Pergunta a **Data do Protocolo** realizada.
  6. Pergunta as **Páginas da Defesa**.
  7. Solicita o envio/referência dos **Arquivos PDF**.
- **Regra do Workflow Cumprida:** Solicitação progressiva e validação de datas.

### FASE 2: Diretriz de Integridade (DIR)

**O que acontece:** Um momento de parada ("Double Check" humano).

- **Passo a passo:**
   O motor imprime todos os dados coletados lado a lado na tela e aguarda uma instrução binária do assessor:
  - Se o assessor digitar **'ok'**, o motor trava essas informações e autoriza a entrada na Fase 3.
  - Se digitar **'corrigir'**, o motor apaga todo o rascunho temporário do banco de dados e reinicia do Passo 1 da Fase 1, evitando que lixo seja processado nas próximas etapas.

### FASE 3: Admissibilidade e Prazos (P1)

1) Fase 3 - P1—TEMPESTIVIDADE/PRESCRIÇÃO/DECADÊNCIA

REGRA SUPREMA F3
Ante qualquer conclusão, sistema DEVE:
Listar em forma de tabela TODAS datas encontradas verificadas em looping infinito até extrair todas, passo a passo (Fase da Infração/autuação, Fase Processo de Suspensão, Fase Recursal JARI e demais)
Indicar origem documental (Página) cada data
Não inferir datas ausentes
Não completar lacunas temporais
Datas perguntas F1
Se qualquer data obrigatória não for localizada:
“Data não localizada”

Após a aferição de datas, acessar “Inventário Normativo DRIVE” e "Perplexity” para avaliar regras.  

A) TEMPESTIVIDADE (Lei nº 9.503/1997 ART. 285)
Se data final interposição recurso JARI (pergunta 4) ultrapassar data final protocolo recurso (PERGUNTA 5) declarar “Recurso Intempestivo".
Obs: prescrição/decadência por serem matéria de ordem pública, prevalecem sobre intempestividade.

B) PRESCRIÇÃO PUNITIVA—5 ANOS (Lei 9.873/99)
Prazo fixo: 5 anos (1825 dias) ≤ “1825” nunca declarar prescrição punitiva
Marcos que zeram prazo:
Infração→AIT→NA→Defesa→Julg.Defesa/NP→Recurso JARI→Julg.JARI→Perguntas 4 e 5 F3
Cada marco reinicia a contagem

C) PRESCRIÇÃO INTERCORRENTE-3 ANOS (Lei 9.873/99)

Data inicial: protocolo recurso JARI (Pergunta 5)
Data final: julgamento JARI (Pergunta 4)
Total_Dias = diferença em dias corridos entre data pergunta 4 e 5
Se Total_Dias > 1095 → intercorrente configurada
Se Total_Dias ≤ 1095 → não

D) DECADÊNCIA
Antes 12/04/21→Lei 9.873
12/04/21 a 22/10/21→180/360 dias
Após 22/10/21→180/360 da conclusão
COVID (Res.782)→-256 dias quando cabível
TRAVA:
Identificar data da infração
Classificar faixa temporal
Justificar regra aplicada
Indicar incidência COVID

RESULTADO FINAL P1
Tempestivo:[SIM/NÃO]
Punitiva:[SIM/NÃO]
Intercorrente:[SIM/NÃO]
Decadência:[SIM/NÃO]
Perguntar: Confirme ‘ok’ ou indique divergência

### FASE 4: Teses e Validação Cruzada

**O que acontece:** Preparatório para a dupla checagem via IA.

- **Passo a passo:** (Apenas se o P1 foi favorável).
  1. O sistema pede ao assessor que descreva a tese de defesa principal.
  2. Aciona o `perplexity_result = perplexity.search_tese(tese)`. A IA externa faz buscas para encontrar precedentes ou jurisprudência (limitadas a sites gov/sc).
  3. Aciona `vertex_result = vertex.search_documents(tese)`. Extrai fragmentos do próprio **Inventário Normativo DRIVE local**.

### FASE 5 e 6: Parecer Técnico e Auditoria de Blindagem

**O que acontece:** Geração do documento e revisão.

- **Passo a passo:**
  1. O motor compila os resultados do Perplexity e do Vertex e submete à API central no `validate_and_generate_parecer`.
  2. A IA central estrutura a resposta, priorizando o material do Vertex sobre o Perplexity (Regra de Conflito).
  3. (Fase 6) A integração ativa o `calculate_blindagem(parecer_text)` apenas com o texto gerado para ter seu "score" de probabilidade de reforma medido, retornando o Índice de Blindagem (Ex: 95%).

### FASE 7 e 8: Arquivamento

**O que acontece:** Organização do trabalho na aplicação web.

- O sistema lista no chat suas Pastas de Trabalho (ex: "Outros", "Abril").
- O assessor seleciona um número de pasta e o parecer é finalizado (`is_saved = True`), exibido na tela e disponibilizado na barra lateral.
