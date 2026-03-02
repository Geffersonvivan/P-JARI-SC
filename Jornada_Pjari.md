# Jornada P-JARI: Passo a Passo do Julgamento

A jornada de julgamento pelo sistema P-JARI segue um fluxo rigoroso dividido em 5 fases sequenciais. A inteligência artificial atua sob estrita legalidade, sem inferências, com base unicamente na documentação fornecida e validada pelo "RAG Inventário Normativo".

## 1. Fase 1: Coleta de Dados Iniciais

Nesta etapa preparatória, o sistema interage para obter dados estruturados e documentos processuais da autuação.

* **Identificação de Dados Essenciais:**
  * Data da sessão de julgamento.
  * Número do processo administrativo.
  * Número do SGPE (Sistema de Gestão de Processos Eletrônicos).
  * Prazo final definido para o protocolo do recurso JARI.
  * Data em que o recurso JARI foi protocolado.
  * Indicação exata das páginas onde se encontra a defesa do Recurso JARI.
* **Carregamento de Documentos:**
  * Upload dos documentos PDF fundamentais nomeados como: `"Autuação"` e `"Consolidado"`.

## 2. Fase 2: DIR (Diretriz de Integridade e Regularidade)

Fase de conferência para garantir que as informações inseridas manual ou previamente batem com os documentos oficiais.

* **Verificação de Legibilidade:** Garantir que os documentos são legíveis.
* **Confronto de Informações (Match 100%):** O sistema confronta as respostas fornecidas na Fase 1 (número do processo, datas, prazos, etc.) diretamente com os documentos anexados.
* **Validação do Usuário:** O sistema questiona ativamente o operador para confirmar com um 'ok' ou indicar qualquer divergência encontrada na conferência documental.

## 3. Fase 3: Admissibilidade e Prazos (Tempestividade, Prescrição e Decadência)

Fase crítica e de cálculo puramente técnico em que o sistema extrai todas as datas e verifica a viabilidade do recurso antes de analisar o mérito.

* **Mapeamento Temporal Exaustivo:**
  * Listagem obrigatória de todas as datas encontradas (Fase de Infração, Suspensão, Recursal, etc.) em formato de tabela, indicando a página de origem do documento. É expressamente proibido inferir datas não explícitas.
* **Aferição Normativa:** Consulta primeiro o "RAG Inventário Normativo" (para regras internas prioritárias) e depois consulta conhecimentos gerais do Perplexity, caso necessário.
* **Testes de Admissibilidade:**
  * **Tempestividade:** Verifica se a data de protocolo do recurso foi feita dentro do prazo legal. Se a data do protocolo for maior que o prazo final, o recurso é declarado "Intempestivo".
  * **Prescrição Punitiva (5 anos):** Avalia os prazos a cada marco interruptivo da infração. Se passar de 5 anos ininterruptos sem movimentação válida entre os marcos, é declarada a prescrição.
  * **Prescrição Intercorrente (3 anos):** Diferença de tempo entre o protocolo do recurso JARI e a data do julgamento. Se superior a 3 anos (1095 dias) de inatividade, está prescrito.
  * **Decadência:** Verifica se as notificações seguiram os prazos estipulados por lei (considerando janelas pandêmicas como a da COVID-19).
* **Resultado Final P1:** Exibição estruturada listando [SIM/NÃO] para Tempestivo, Prescrição Punitiva, Intercorrente e Decadência, exigindo nova validação do operador ('ok' ou divergência).

## 4. Fase 4: Análise das Teses Defensivas (Mérito)

Esta fase só prossegue caso a etapa anterior não aponte prescrição ou decadência. Na extinção punitiva, a análise desta etapa é anulada (prejudicada).

* **Memória do Sistema:** A IA carrega toda a análise da admissibilidade processada na Fase 3.
* **Extração e Cruzamento:**
  * O sistema lê integralmente a defesa (nas páginas previamente indicadas na Fase 1).
  * Identifica isoladamente todas as teses levantadas pelo requerente.
  * Cruza os argumentos com o comando da suprema hierarquia extraído do "RAG Inventário Normativo", analisando as provas.
* **Conclusão por Tese:** Define, com base estritamente normativo-documental, se cada tese é *acolhida* ou *não acolhida*, solicitando novamente a validação do operador ('ok' ou apontamento de divergência).

## 5. Fase 5: Redação do Parecer Técnico

Fase final responsável pela formulação estruturada do documento de forma jurídica limpa, sem criatividade e sem alucinações.

* **Contexto Final:** A IA retém toda a trilha das fases de Admissibilidade (Fase 3) e Escrutínio de Teses (Fase 4).
* **Geração Textual em Bloco Único:** A criação do parecer final exige rigor. É proibido o uso de emoticons, citações aos comandos internos da IA, e inferências próprias.
* **Estrutura Obrigatória do Parecer:**
    1. **Cabeçalho:** Informações do Processo (PA), SGPE, Recorrente, Relator, Data da Sessão e Resultado (DEFERIDO/INDEFERIDO).
    2. **Ementa:** Resumo direto contendo a infração, as teses, análise de tempo e resultado, citando normas de forma expressa e hierarquizada.
    3. **Relatório:** Uma síntese do histórico da autuação e das notificações até o envio à JARI.
    4. **Fundamentação Jurídica:**
        * **Admissibilidade:** Conclusão da análise temporal da Fase 3.
        * **Teses Defensivas:** Análise individualizada do mérito (caso o recurso seja tempestivo).
        * **Prescrição e Decadência:** Linhas do tempo calculadas.
        * **Materialidade:** Conferência dos campos do auto de infração.
        * **Garantias Processuais:** Observação aos prazos contratuais e ampla defesa.

---
*Nota: Este passo a passo reflete as diretrizes rigorosas do P-JARI para atuação neutra, rastreamento contínuo de documentos e aplicação estrita das normativas de trânsito vigentes no Brasil.*
