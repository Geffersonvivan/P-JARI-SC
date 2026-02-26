# Guia de Hospedagem para o P-JARI/SC

Como o **P-JARI/SC** é um sistema feito em Python (Django) que processa textos, se comunica constantemente com as APIs de IA (OpenAI, Perplexity, Vertex) e gera arquivos PDF, ele tem um perfil de consumo bem específico. Ele não exige um "supercomputador", mas precisa de uma base estável, porque requisições de IA costumam segurar a conexão aberta por alguns segundos enquanto o texto está sendo gerado.

## 1. O que o servidor vai precisar ter? (Hardware Ideal)

Para começar com folga, sem travamentos quando múltiplos membros julgadores estiverem usando ao mesmo tempo, recomendo a seguinte configuração base:

* **Memória RAM: Mínimo de 2GB (Recomendado 4GB).**
  * *Por que?* O servidor precisa rodar o Linux, o Banco de Dados (PostgreSQL), o motor do site (Gunicorn/Django) e sobrar espaço para processar a conversão daquele HTML complexo em PDF. Se tiver menos de 2GB, o servidor pode sufocar na hora de gerar um PDF pesado e derrubar o site por alguns segundos.
* **Processador (CPU): 2 vCPUs.**
  * *Por que?* Com 2 núcleos, enquanto um núcleo está "esperando" a resposta demorada da OpenAI para um usuário, o outro núcleo fica livre para navegar nas pastas e abrir arquivos para um segundo usuário simultaneamente.
* **Armazenamento: 30GB a 40GB SSD NVMe.**
  * *Por que?* O código em si não pesa quase nada (menos de 100MB). O espaço será usado pelo sistema operacional e, principalmente, pelo seu banco de dados crescendo com os históricos de chat, rascunhos salvos e, futuramente, caso passe a salvar PDFs no servidor. 40GB demora muito tempo para encher com texto.

## 2. Onde hospedar? (Minhas 3 Sugestões de Ouro)

Hoje em dia, nós fugimos de "hospedagem de site" tradicional (como HostGator cPanel) porque elas não rodam Python direito. Nós usamos soluções de nuvem modernas.

### Opção A: A Escolha Inteligente e Barata (Hetzner Cloud)

* **Perfil:** É a "queridinha" global dos desenvolvedores hoje. Eles entregam servidores extremamente potentes a preço de banana.
* **Vantagem:** O custo-benefício é imbatível. Um servidor que custaria $20 na Amazon, lá custa $4.
* **Plano Sugerido:** **CX22** (2 vCPUs Intel, 4GB RAM, 40GB NVMe).
* **Preço médio:** ~ **€ 4,50 / mês** (Cerca de R$ 25).
* **Curiosidade:** Os servidores ficam nos EUA ou Europa (ping de uns 100ms para o Brasil), o que num sistema de chat/documentos não faz diferença nenhuma na percepção humana.

### Opção B: A Escolha Clássica e Robusta (DigitalOcean ou Linode)

* **Perfil:** A provedora de "VPS (Servidor Virtual)" mais famosa do mundo. Tem muito tutorial na internet sobre como configurar Django nela.
* **Vantagem:** Muito fácil de gerenciar, sistema limpo, infraestrutura consolidada.
* **Plano Sugerido:** Droplet Basic (2 vCPUs, 2GB RAM, 60GB SSD).
* **Preço médio:** ~ **$ 12,00 / mês** (Cerca de R$ 60).

### Opção C: A "Mãos Livres" Zero Configuração (Railway.app ou Render.com)

* **Perfil:** São serviços de plataforma. Você não ganha um servidor em branco para configurar, você apenas conecta a sua conta do GitHub nelas e elas constroem e botam o site no ar sozinhas em 5 minutos.
* **Vantagem:** Você não tem que ser "Administrador de Redes Linux" nem configurar firewall. Fez uma modificação no código no seu PC, ele atualiza na nuvem sozinho.
* **Preço médio:** Elas cobram pelo uso exato. Para o P-JARI rodar tranquilo nelas junto de um banco PostgreSQL, você gastaria em torno de **$ 10 a $ 15 / mês**. (A Render até tem um plano free/grátis limitadíssimo se quiser só para mostrar o site de portfólio pra alguém de forma provisória).

## Meu Veredito para o P-JARI/SC

Se você quiser ter o site rodando de forma hiper profissional e barata, e quiser que eu mesmo (como IA) configure todo o Linux pra você do zero (instalando Nginx, PostgreSQL, Gunicorn, HTTPS com cadeado verde): compre um servidor "Linux Ubuntu 24.04" na **Hetzner (Plano CX22 de R$ 25)** ou na **DigitalOcean (Basic de R$ 30)**.

Se você estiver disposto a pagar alguns reais a mais só para não ter a dor de cabeça de configurar servidores e colocar o site no ar com 3 botões automáticos e ter certificado digital pronto na hora, hospede na **Railway.app**.
