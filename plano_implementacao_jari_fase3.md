# Implementação do Limite de 2 Julgamentos e Login "Genspark Style"

O objetivo é permitir que o usuário experimente a plataforma sem login (progressive profiling), criando até 2 processos/pareceres. Ao atingir o limite, um modal de login moderno estilo Genspark será exibido.

## User Review Required

> [!WARNING]
> Para permitir o uso anônimo, será necessário alterar o banco de dados (remover a obrigatoriedade do usuário atrelado à Pasta/Parecer e adicionar uma chave de sessão). Isso exigirá rodar migrações.
> Como você mencionou "somente dizer sem implementar" sobre o Google/Microsoft e "ok seguimos com essa implementação" sobre o limite, **meu foco será no limite funcional e no design do modal, sendo os links sociais apenas visuais (placeholders) por enquanto.**

---

## Proposed Changes

### Database Layer

A atual arquitetura obriga todo `Parecer` e `Pasta` a ter um `User`.

#### [MODIFY] chat/models.py

- Tornar o campo `user` opcional (`null=True, blank=True`) nas models `Pasta` e `Parecer`.
- Adicionar o campo `session_key` (`CharField(max_length=40, null=True, blank=True)`) para rastrear criações de usuários não logados.

---

### Backend Logic

Precisamos remover a restrição isolada do login e incluir a lógica de contagem.

#### [MODIFY] chat/views.py

- Remover o `@login_required` das funções `home_view`, `chat_message_view` e `create_parecer_view`.
- Na função `home_view`:
  - Se o usuário estiver logado, carrega os dados normalmente.
  - Se for anônimo, carrega os dados com base na `request.session.session_key` (e cria a sessão se não existir).
- Na função `chat_message_view`:
  - Se for anônimo e a ação for iniciar um novo processo (mensagem 'iniciar' ou novo projeto), conta quantos `Pareceres` aquela sessão já criou.
  - Se o limite de **2 julgamentos** for atingido, retorna um JSON estrito: `{'requires_login': True}` ao invés da reposta da IA.
- Na hora de salvar processos/pastas, associar ao `user` se logado, ou à `session_key` se anônimo.

---

### Frontend & UI

O frontend precisa reagir ao bloqueio e exibir uma interface limpa.

#### [MODIFY] templates/home.html

- Ajustar os templates que dependem do nome do usuário (ex: "Olá {{ request.user.first_name }}") para "Olá," ou "Olá Visitante," se deslogado.
- Adicionar no JavaScript a verificação de `data.requires_login`. Se for `True`, bloqueia a interface e dispara o modal.
- Criar o Modal de Login:
  - Fundo com `backdrop-blur-sm` (Glassmorphism).
  - Texto chamativo: "Crie uma conta para salvar seus projetos e continuar analisando."
  - Botões grandes e limpos: "Continuar com Google", "Continuar com Microsoft".
  - Opção secundária para login com e-mail.

---

## Verification Plan

### Automated Tests

- Não há testes automatizados detalhados configurados para este fluxo.

### Manual Verification

1. Acessar o sistema em aba anônima (sem estar logado).
2. O sistema deve carregar e permitir a digitação de "iniciar".
3. Deve ser possível criar o primeiro Parecer (julgamento 1).
4. Deve ser possível criar o segundo Parecer (julgamento 2).
5. Ao tentar iniciar o terceiro Parecer, a tela de chat não prosseguirá e um Modal bonito e moderno aparecerá exigindo o login.
6. Testar o layout do Modal.

- Manually run sequence tests by starting an anonymous session and validating the judgment counter behavior.
- Validate rendering logic for buttons in the header vs the sidebar.

---

# Pricing Page & Subscription Upgrade Implementation

The goal is to implement a new "Plans / Pricing" page inspired by Genspark.ai's structure, allowing users to purchase credits/subscriptions to bypass the initial trial limits. We will also add a "Ver Plano ➔" button (matching the provided screenshot) to direct users there.

## Proposed Changes

### 1. Frontend: Sidebar / User Menu

We need to integrate the "Ver Plano" button shown in the screenshot for authenticated users.

#### [MODIFY] [home.html](file:///Volumes/D/P-Jari/templates/home.html)

- Add the user profile block (Avatar, Name, Email) to the sidebar or a settings modal.
- Below the user info, add the prominent dark-themed button `Ver Plano ➔` (`bg-gray-800 text-white` with a purple arrow `bg-purple-500`).

### 2. Frontend: Pricing Page (Genspark Style)

#### [NEW] [pricing.html](file:///Volumes/D/P-Jari/templates/pricing.html)

- Create a dedicated Tailwind HTML page showcasing subscription tiers (e.g., Free, Pro, Premium).
- The design will feature cards with pricing, feature lists, and clear CTA buttons ("Assinar", "Começar Grátis").
- Include a toggle for Monthly vs Annual billing (aesthetic for now, or functional if requested).

### 3. Backend: Routing & Views

#### [MODIFY] [views.py](file:///Volumes/D/P-Jari/chat/views.py)

- Create a simple `pricing_view(request)` that renders `pricing.html`.

#### [MODIFY] [urls.py](file:///Volumes/D/P-Jari/chat/urls.py)

- Add the route `path('pricing/', views.pricing_view, name='pricing')`.

## Verification Plan

### Automated Tests

- Basic route testing to ensure `/pricing/` returns a 200 HTTP status code.

### Manual Verification

- Navigate to the sidebar, click "Ver Plano", and verify it redirects correctly to `/pricing/`.
- Ensure the aesthetic of `pricing.html` feels premium and aligns with the Genspark.ai inspiration.

---

# Payment Gateway Integration (Mercado Pago)

The next step in making P-JARI a true SaaS is integrating a payment gateway to handle subscriptions. We will use **Mercado Pago** due to its ease of setup in Brazil, Instant PIX support, and simple webhook architecture.

## Proposed Changes

### Database Layer

#### [MODIFY] chat/models.py

- Create a `UserProfile` model linked to `User` via `OneToOneField`.
- Add fields: `is_pro` (BooleanField, default=False), `credits` (IntegerField, default=0), `mp_customer_id` (CharField), and `subscription_status` (CharField).

### Backend Logic

#### [NEW / MODIFY] chat/views.py

- **Checkout View:** A new view triggered when the user clicks "Assinar" in `planos.html`. It makes an API call to Mercado Pago to generate a Secure Checkout URL, and redirects the user.
- **Webhook Receiver:** A `require_POST` view (e.g., `/webhooks/mercadopago/`) that Mercado Pago pings in the background when a payment is approved.
- When an `approved` webhook is received, the system finds the user session and upgrades them: `user.profile.is_pro = True`, granting unlimited features.

### Frontend Integration

#### [MODIFY] templates/planos.html

- Change the `href` of the "Assinar Agora" / "Assinar Premium" buttons to point to the new Django checkout view.

## Verification Plan

1. Start the Django dev server with Ngrok to expose a public URL to Mercado Pago.
2. Click "Assinar" and be redirected to a Mercado Pago test checkout page.
3. Make a test payment using a Sandbox credit card or test PIX.
4. Verify the Ngrok terminal receives the webhook request.
5. Check Django admin or user UI to ensure the profile upgraded to PRO automatically!

---

# Atualização da Lógica do Motor JARI (Fase 3 em diante)

A pedido, vamos realizar uma revisão total do fluxo a partir da Fase 3, de acordo com o workflow `jari-logic` proposto. A ideia é consolidar a matemática rígida (Dias corridos, bissextos) e garantir a formatação correta do Parecer Final na Fase 5.

## User Review Required

> [!IMPORTANT]
> **Data da Infração Faltante na Fase 1:**
> O workflow estipula que na Fase 3 o motor deve calcular a Prescrição Punitiva matematicamente (>= 1825 dias considerando bissextos). A lógica atual em `jari_math.py` exige a `data_infracao` e a `data_sessao` para calcular esse intervalo. No entanto, a Coleta de Dados da Fase 1 não está pedindo a **Data da Infração** ao usuário. Se quisermos que o cálculo seja feito via código (e não pela IA), **precisaremos adicionar a pergunta "Qual a Data da Infração?" na Fase 1** e salvar no banco de dados. Você aprova a inclusão dessa pergunta?

> [!NOTE]
> **Automação da Fase 4 (Extração de Tese):**
> O workflow diz: *"Identificar teses no 'Consolidado' (pág. informada)"*. Hoje, o motor pergunta abertamente qual é a tese para o usuário digitar. Como o upload e processamento nativo de PDFs ainda será implementado no futuro, vou atualizar para que a UI continue pedindo a tese ao usuário, mas adaptando o texto para simular o extrator: *"Teses identificadas no Consolidado nas páginas [X]. Confirme o escopo da tese principal:"*. Isso garante que o resto do fluxo de Perplexity e Gemini respeite a regra que o workflow propõe para o futuro.

## Proposed Changes

### Database Layer

Precisaremos incluir um novo campo para calcular o gap de prazo da Punibilidade.

#### [MODIFY] chat/models.py

- Adicionar no modelo `Parecer` o campo: `data_infracao = models.DateField(blank=True, null=True)`.

---

### Backend Logic

Refatoração do cérebro matemático.

#### [MODIFY] chat/jari_engine.py

- **Fase 1:** Adicionar um novo passo sequencial de coleta: *"Por favor, informe a Data da Infração (DD/MM/AAAA)"*.
- **Fase 2 (Diretriz de Integridade):** Exibir a Data da Infração no espelho para o assessor dar o 'ok'.
- **Fase 3 (Matemática):**
  - Adicionar a checagem que já existe em JariMath, mas não estava conectada: `JariMath.check_prescription_punitiva(self.parecer.data_infracao, self.parecer.data_sessao)`.
  - Se der Prescrição Punitiva OU Intercorrente OU Intempestiva -> Encerrar mérito (Prejudicado) e mandar para a Fase 5 gerar o indeferimento direto.
- **Fase 4 (Validação Cruzada):**
  - Mudar o prompt de entrada. Em vez de perguntar a tese pura e limpa, perguntaremos o escopo confirmado simulando o extrator do Consolidado.

#### [MODIFY] chat/integrations.py

- Refinar o `GeminiClient` para impor o bloco de texto fixo determinado na **Fase 5**.
  - O prompt `system_instruction` será reforçado para exigir rigorosamente as tags: `**PARECER JARI**`, `**RESULTADO:** [DEFERIDO/INDEFERIDO]`, `**EMENTA**`, `**RELATÓRIO**`, `**FUNDAMENTAÇÃO JURÍDICA**`.
  - Instruiremos o Gemini explicitamente sobre as variáveis matemáticas que deram no output da Fase 3.

## Verification Plan

### Automated Tests

- Atualizar `test_jari_math.py` para garantir a contabilidade estrita de 1826 dias na Punitiva.

### Manual Verification

1. Fazer um julgamento do zero.
2. Responder a "Data da Infração" como exatos 6 anos atrás da "Data da Sessão".
3. Confirme que o sistema pula a validação de mérito e sugere Indeferimento por Prescrição.
4. Confira com datas normais se a IA constrói o PDF exatamente nos 5 blocos fixos na Fase 5.
