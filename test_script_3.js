
        // --- Agent Drawer Toggle removido ---

        // Reabilita o input e botão de envio após conclusão de SSE/Celery
        function enableInput() {
            const btnSend = document.getElementById('btn-send');
            const userInput = document.getElementById('user-input');
            if (btnSend) btnSend.disabled = false;
            if (userInput) userInput.disabled = false;
        }

        function showLoginModal() {
            document.getElementById('login-modal').classList.remove('hidden');
        }

        function closeLoginModal() {
            document.getElementById('login-modal').classList.add('hidden');
        }

        function showToast(message, type = 'error') {
            const colors = { error: 'bg-red-500', success: 'bg-green-500', info: 'bg-blue-500', warning: 'bg-amber-500' };
            const t = document.createElement('div');
            t.className = `fixed bottom-5 right-5 ${colors[type] || colors.error} text-white px-5 py-3 rounded-xl shadow-lg font-medium opacity-0 transition-opacity duration-300 z-[200] max-w-xs text-sm`;
            t.textContent = message;
            document.body.appendChild(t);
            requestAnimationFrame(() => t.classList.remove('opacity-0'));
            setTimeout(() => { t.classList.add('opacity-0'); setTimeout(() => t.remove(), 300); }, 4000);
        }

        function showConfirmDialog(message, onConfirm) {
            const overlay = document.createElement('div');
            overlay.className = 'fixed inset-0 bg-black/50 z-[300] flex items-center justify-center';
            overlay.innerHTML = `
                <div class="bg-white rounded-2xl shadow-xl p-7 max-w-sm mx-4 w-full">
                    <p class="text-gray-800 font-medium text-base mb-6 leading-snug">${message.replace(/</g,'&lt;')}</p>
                    <div class="flex gap-3 justify-end">
                        <button id="confirm-cancel" class="px-5 py-2 rounded-lg bg-gray-100 text-gray-700 hover:bg-gray-200 font-medium transition text-sm">Cancelar</button>
                        <button id="confirm-ok" class="px-5 py-2 rounded-lg bg-red-600 text-white hover:bg-red-700 font-medium transition text-sm">Confirmar</button>
                    </div>
                </div>`;
            document.body.appendChild(overlay);
            overlay.querySelector('#confirm-cancel').addEventListener('click', () => overlay.remove());
            overlay.querySelector('#confirm-ok').addEventListener('click', () => { overlay.remove(); onConfirm(); });
        }

        const isUserAuthenticated = "{{ request.user.is_authenticated|yesno:'true,false' }}" === "true";

        function iniciarNovoProcesso() {
            if (!isUserAuthenticated) {
                showLoginModal();
                return;
            }

            const footer = document.getElementById('chat-footer');
            if (footer) footer.classList.remove('hidden-home');
            
            // Limpa as referências do processo/pasta anterior para o backend entender que é uma requisição nova
            currentParecerId = null;
            currentPastaId = null;

            // Simular o envio da palavra "Iniciar"
            // Passa a palavra "Iniciar" com flag silenciosa (true)
            sendMessage(null, "Iniciar", true);
        }

        const sidebar = document.getElementById('sidebar');
        const btnOpenSidebar = document.getElementById('btn-open-sidebar');
        const headerTitle = document.getElementById('header-title');
        const userInput = document.getElementById('user-input');
        const messagesContainer = document.getElementById('messages-container');
        const folderContainer = document.getElementById('folder-container');
        const homeScreen = document.getElementById('home-screen');
        const chatWindow = document.getElementById('chat-window');

        const csrftoken = document.querySelector('[name=csrfmiddlewaretoken]').value;
        const fileUploadInput = document.getElementById('file-upload');
        const filePreviewContainer = document.getElementById('file-preview-container');
        let selectedFiles = [];

        // Trata a seleção de arquivos
        if (fileUploadInput) {
            fileUploadInput.addEventListener('change', (e) => {
                const files = Array.from(e.target.files);
                selectedFiles = selectedFiles.concat(files);
                renderFilePreview();
                fileUploadInput.value = ''; // Reseta para permitir selecionar o mesmo arquivo novamente
            });
        }

        function renderFilePreview() {
            if (!filePreviewContainer) return;
            filePreviewContainer.innerHTML = '';
            if (selectedFiles.length === 0) {
                filePreviewContainer.classList.add('hidden');
                return;
            }
            filePreviewContainer.classList.remove('hidden');

            selectedFiles.forEach((file, index) => {
                const badge = document.createElement('div');
                badge.className = "flex items-center gap-2 bg-green-50 text-green-700 text-xs px-3 py-1.5 rounded-full shadow-sm border border-green-100 max-w-[200px]";
                badge.innerHTML = `
                    <svg width="14" height="14" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path><polyline points="13 2 13 9 20 9"></polyline></svg>
                    <span class="truncate" title="${file.name}">${file.name}</span>
                    <button type="button" onclick="removeFile(${index})" class="text-green-400 hover:text-green-800 ml-1 font-bold focus:outline-none">×</button>
                `;
                filePreviewContainer.appendChild(badge);
            });
        }

        function removeFile(index) {
            selectedFiles.splice(index, 1);
            renderFilePreview();
        }

        function toggleSidebar() {
            const overlay = document.getElementById('sidebar-overlay');
            if (window.innerWidth < 768) {
                sidebar.classList.toggle('mobile-open');
                if (sidebar.classList.contains('mobile-open')) {
                    overlay.classList.remove('hidden');
                } else {
                    overlay.classList.add('hidden');
                }
            } else {
                sidebar.classList.toggle('sidebar-hidden');
                if (sidebar.classList.contains('sidebar-hidden')) {
                    btnOpenSidebar.classList.remove('md:hidden');
                    headerTitle.classList.remove('md:hidden');
                    document.getElementById('main-header').classList.remove('md:hidden');
                    document.getElementById('main-header').classList.add('md:flex');
                } else {
                    btnOpenSidebar.classList.add('md:hidden');
                    headerTitle.classList.add('md:hidden');
                    // Esconde o header apenas se o PDF também não estiver ativo
                    if (!pdfViewerActive) {
                        document.getElementById('main-header').classList.add('md:hidden');
                        document.getElementById('main-header').classList.remove('md:flex');
                    }
                }
            }
        }

        document.getElementById('btn-parecer').addEventListener('click', async () => {
            if (!isUserAuthenticated) {
                showLoginModal();
                return;
            }

            const name = prompt("Digite o nome ou número para esta pasta:");
            if (name && name.trim() !== "") {
                try {
                    const response = await fetch('/parecer/create/', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': csrftoken
                        },
                        body: JSON.stringify({ nome_processo: name.trim() })
                    });

                    if (response.ok) {
                        const data = await response.json();

                        if (data.requires_login) {
                            showLoginModal();
                            return;
                        }
                        if (data.requires_plan) {
                            window.location.href = '/planos/';
                            return;
                        }

                        // Atualiza a página para carregar a nova pasta perfeitamente
                        window.location.reload();
                    } else {
                        showToast('Erro ao criar parecer.');
                    }
                } catch (error) {
                    console.error('Erro:', error);
                    showToast('Erro ao criar parecer.');
                }
            }
        });

        async function deleteFolder(event, id) {
            if (event) event.stopPropagation();
            showConfirmDialog("Deseja mesmo apagar esta pasta e TODOS os seus projetos?", async () => {
                try {
                    const response = await fetch(`/parecer/${id}/delete/`, {
                        method: 'POST',
                        headers: {
                            'X-CSRFToken': csrftoken
                        }
                    });

                    if (response.ok) {
                        window.location.reload();
                    } else {
                        showToast('Erro ao excluir pasta.');
                    }
                } catch (error) {
                    console.error('Erro:', error);
                    showToast('Erro ao excluir pasta.');
                }
            });
        }

        async function deleteProjeto(event, id, pastaId) {
            if (event) event.stopPropagation();
            showConfirmDialog("Deseja mesmo apagar este projeto? Esta ação é irreversível.", async () => {
                try {
                    const response = await fetch(`/projeto/${id}/delete/`, {
                        method: 'POST',
                        headers: {
                            'X-CSRFToken': csrftoken
                        }
                    });

                    if (response.ok) {
                        window.location.reload();
                    } else {
                        showToast('Erro ao excluir projeto.');
                    }
                } catch (error) {
                    console.error('Erro:', error);
                    showToast('Erro ao excluir projeto.');
                }
            });
        }

        let currentPastaId = null;
        let currentParecerId = null;

        function toggleFolder(pastaId) {
            const container = document.getElementById(`projetos-${pastaId}`);
            if (container) {
                container.classList.toggle('hidden');
            }
            // Ao clicar na pasta apenas expandimos, mas podemos também invocar selectFolder se quisermos a tela de resumo da pasta
            selectFolder(pastaId, document.getElementById(`folder-${pastaId}`));
        }

        function selectFolder(id, element) {
            currentPastaId = id;
            currentParecerId = null;
            document.querySelectorAll('.folder-item').forEach(el => el.classList.remove('bg-white/10'));
            if (element) element.classList.add('bg-white/10');

            // Limpa chat
            messagesContainer.innerHTML = '';
            homeScreen.classList.add('hidden-home');
            document.getElementById('chat-footer').classList.remove('hidden-home');

            // Simula clique de inicialização do bot pro processo
            const welcomeDiv = document.createElement('div');
            welcomeDiv.className = "flex justify-start items-start gap-3 mt-4";
            welcomeDiv.innerHTML = `
                <div class="w-8 h-8 rounded-full bg-brand-accent/20 border border-brand-accent/30 shadow-[0_0_10px_rgba(34,197,94,0.2)] flex-shrink-0 flex items-center justify-center"><i class="ph-fill ph-scales text-brand-accent text-lg"></i></div>
                <div class="text-[#444746] leading-relaxed pt-1">Pasta selecionada. Carregando visão geral...</div>
            `;
            messagesContainer.appendChild(welcomeDiv);

            // Fetch histórico/resumo da pasta
            fetch('/chat/message/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrftoken
                },
                body: JSON.stringify({ message: 'RESUMO', pasta_id: currentPastaId })
            }).then(response => response.json())
                .then(data => {
                    if (data.reply) {
                        messagesContainer.innerHTML = '';
                        const rDiv = document.createElement('div');
                        rDiv.className = "flex justify-start items-start gap-3 mt-4";
                        rDiv.innerHTML = `
                          <div class="w-8 h-8 rounded-full bg-brand-accent/20 border border-brand-accent/30 shadow-[0_0_10px_rgba(34,197,94,0.2)] flex-shrink-0 flex items-center justify-center"><i class="ph-fill ph-scales text-brand-accent text-lg"></i></div>
                          <div class="text-gray-800 leading-relaxed pt-1">${formatMessage(data.reply)}</div>
                      `;
                        messagesContainer.appendChild(rDiv);
                        chatWindow.scrollTo({ top: chatWindow.scrollHeight, behavior: 'smooth' });
                    }
                }).catch(err => console.error(err));
        }

        function selectProjeto(projetoId, pastaId) {
            currentPastaId = pastaId;
            currentParecerId = projetoId;
            document.querySelectorAll('.folder-item').forEach(el => el.classList.remove('bg-[#e2e7ed]'));
            const element = document.getElementById(`folder-${pastaId}`);
            if (element) element.classList.add('bg-[#e2e7ed]');

            // Limpa chat
            messagesContainer.innerHTML = '';
            homeScreen.classList.add('hidden-home');
            document.getElementById('chat-footer').classList.remove('hidden-home');

            const welcomeDiv = document.createElement('div');
            welcomeDiv.className = "flex justify-start items-start gap-3 mt-4";
            welcomeDiv.innerHTML = `
                <div class="w-8 h-8 rounded-full bg-brand-accent/20 border border-brand-accent/30 shadow-[0_0_10px_rgba(34,197,94,0.2)] flex-shrink-0 flex items-center justify-center"><i class="ph-fill ph-scales text-brand-accent text-lg"></i></div>
                <div class="text-gray-800 leading-relaxed pt-1 animate-pulse">Carregando processo e buscando relatório na base...</div>
            `;
            messagesContainer.appendChild(welcomeDiv);

            // Fetch histórico/resumo do PROJETO individual
            fetch('/chat/message/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrftoken
                },
                body: JSON.stringify({ message: 'RESUMO_PROJETO', parecer_id: currentParecerId })
            }).then(response => response.json())
                .then(data => {
                    messagesContainer.innerHTML = '';
                    if (data.chat_history && data.chat_history.length > 0) {
                        data.chat_history.forEach(msg => {
                            if (msg.role === 'user') {
                                const userDiv = document.createElement('div');
                                userDiv.className = "flex justify-end mt-4";
                                userDiv.innerHTML = `<div class="bg-[#e9eef6] p-4 rounded-2xl max-w-[80%] text-[#1f1f1f] shadow-sm">${formatMessage(msg.content)}</div>`;
                                messagesContainer.appendChild(userDiv);
                            } else {
                                const rDiv = document.createElement('div');
                                rDiv.className = "flex justify-start items-start gap-3 mt-4 w-full";
                                rDiv.innerHTML = `
                                  <div class="w-8 h-8 rounded-full bg-brand-accent/20 border border-brand-accent/30 shadow-[0_0_10px_rgba(34,197,94,0.2)] flex-shrink-0 flex items-center justify-center"><i class="ph-fill ph-scales text-brand-accent text-lg"></i></div>
                                  <div class="text-[#444746] leading-relaxed pt-1 w-full">${formatMessage(msg.content)}</div>
                                `;
                                messagesContainer.appendChild(rDiv);
                            }
                        });
                        setTimeout(() => {
                            chatWindow.scrollTo({ top: chatWindow.scrollHeight, behavior: 'smooth' });
                        }, 100);
                    } else if (data.reply) {
                        const rDiv = document.createElement('div');
                        rDiv.className = "flex justify-start items-start gap-3 mt-4 w-full";
                        rDiv.innerHTML = `
                          <div class="w-8 h-8 rounded-full bg-brand-accent/20 border border-brand-accent/30 shadow-[0_0_10px_rgba(34,197,94,0.2)] flex-shrink-0 flex items-center justify-center"><i class="ph-fill ph-scales text-brand-accent text-lg"></i></div>
                          <div class="text-[#444746] leading-relaxed pt-1 w-full">${formatMessage(data.reply)}</div>
                        `;
                        messagesContainer.appendChild(rDiv);
                        setTimeout(() => {
                            chatWindow.scrollTo({ top: chatWindow.scrollHeight, behavior: 'smooth' });
                        }, 100);
                    }
                    
                    // Se o projeto já foi salvo e finalizado, não permite o usuário digitar mais nada no chat.
                    if (data.is_saved || data.status_fase >= 8) {
                        const footer = document.getElementById('chat-footer');
                        if (footer) footer.classList.add('hidden');
                    }
                        
                        // Atualiza as opções do Leitor de PDF e abre automaticamente se existir e se passou da fase 1
                        if (data.consolidado_url) {
                            pdfDocs.recurso = data.consolidado_url;
                            if (data.consolidado_name) document.getElementById('tab-recurso').innerText = data.consolidado_name;
                        } else {
                            pdfDocs.recurso = null;
                        }
                        
                        if (data.autuacao_url) {
                            pdfDocs.autuacao = data.autuacao_url;
                            if (data.autuacao_name) document.getElementById('tab-autuacao').innerText = data.autuacao_name;
                        } else {
                            pdfDocs.autuacao = null;
                        }
                        
                        // Na seleção do Histórico, o status sempre será > 1, então pode abrir e exibir o toggle button no Header
                        if (pdfDocs.recurso || pdfDocs.autuacao) {
                            btnTogglePdf.classList.remove('hidden');
                            btnTogglePdf.classList.add('md:flex');
                            document.getElementById('main-header').classList.remove('md:hidden');
                            document.getElementById('main-header').classList.add('md:flex');
                            togglePdfViewer(true);
                        } else {
                            btnTogglePdf.classList.add('hidden');
                            btnTogglePdf.classList.remove('md:flex');
                            document.getElementById('main-header').classList.remove('md:flex');
                            document.getElementById('main-header').classList.add('md:hidden');
                            togglePdfViewer(false);
                            document.getElementById('tab-recurso').innerText = "Defesa/Recurso";
                            document.getElementById('tab-autuacao').innerText = "Auto de Infração";
                        }
                        
                        // Atualiza as sugestões do Agente Lateral (Dynamic Context Chips)
                        if (window.updateAgentChips) {
                            window.updateAgentChips(currentParecerId, data.reply);
                        }
                }).catch(err => console.error(err));
        }

        function formatMessage(text) {
            // Configurar marked para abrir links em nova aba
            const renderer = new marked.Renderer();
            renderer.link = function (token) {
                // Suporte para versões antigas do marked (< v13) e novas (v13+)
                const href = typeof token === 'string' ? arguments[0] : token.href;
                const title = typeof token === 'string' ? arguments[1] : token.title;
                const text = typeof token === 'string' ? arguments[2] : token.text;

                return `<a href="${href}" target="_blank" rel="noopener noreferrer" class="text-green-600 hover:underline" ${title ? `title="${title}"` : ''}>${text}</a>`;
            };
            marked.setOptions({ renderer: renderer });

            // Usa a biblioteca marked para converter Markdown em HTML real
            let rawHtml = marked.parse(text);

            // Injeta botões interativos dinâmicos para a Fase 4 do JARI
            let hasDecisionButtons = false;
            rawHtml = rawHtml.replace(/\[DECISAO_TESE_(\d+)\]/g, function (match, teseNum, offset, string) {
                hasDecisionButtons = true;
                
                // Tenta extrair o título da tese (ex: "Tese 4 - Síntese da alegação:" ou "**Tese 4 – TEMPESTIVIDADE:**")
                // Vamos procurar o texto que vem logo após "Tese X - " ou "Tese X – " no contexto anterior à tag
                let teseNome = `Tese ${teseNum}`;
                
                // Regex para buscar o cabeçalho mais próximo antes desta decisão. 
                // Exemplo gerado pelo LLM: **Tese 4 – TEMPESTIVIDADE:** ou **Tese 4 - Síntese da alegação:**
                // Vamos tentar capturar a string que o LLM usou para dar nome à Tese X.
                const regexTitulo = new RegExp(`(?:\\\\*\\\\*|<strong|<b>|>\\\\s*)Tese\\\\s+${teseNum}\\\\s*[-–:]\\\\s*([^<\\\\*]+?)(?:\\\\*\\\\*|<\\\\/strong|<\\\\/b>|:)`, 'i');
                const contextBefore = string.substring(Math.max(0, offset - 1000), offset);
                const matchTitulo = contextBefore.match(regexTitulo);
                
                if (matchTitulo && matchTitulo[1]) {
                    const extractedName = matchTitulo[1].trim();
                    // Se o nome capturado for algo genérico como "Síntese da alegação", mantemos "Tese X" ou tentamos capturar antes
                    if (!extractedName.toLowerCase().includes('síntese')) {
                        teseNome = extractedName.toUpperCase();
                    } else {
                        teseNome = `TESE ${teseNum}`;
                    }
                } else {
                    teseNome = `TESE ${teseNum}`;
                }

                return `
                <div class="flex flex-col gap-2 mt-2 mb-4 p-4 sm:px-5 bg-white border border-[#e2e8f0] shadow-sm hover:shadow transition-shadow duration-300 rounded-xl tese-decision-block" data-tese="${teseNum}">
                    <div class="flex items-center gap-2 mb-1 pb-2 border-b border-gray-100">
                        <div class="w-6 h-6 rounded-full bg-blue-50 text-blue-600 flex items-center justify-center font-bold text-xs">${teseNum}</div>
                        <span class="font-semibold text-gray-800 text-sm">Decisão Exigida para ${teseNome}</span>
                    </div>
                    <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        <button onclick="window.selectTeseOption(this, ${teseNum}, 'a')" type="button" class="btn-tese-option group relative w-full flex items-center justify-between px-4 py-2 rounded-lg border border-slate-200 bg-slate-50 hover:bg-white hover:border-emerald-400 hover:shadow-sm text-slate-600 transition-all duration-300">
                            <div class="flex items-center gap-3">
                                <div class="w-7 h-7 rounded-full bg-white shadow-sm flex items-center justify-center group-hover:bg-emerald-50 transition-colors icon-container">
                                    <svg class="w-4 h-4 text-slate-400 group-hover:text-emerald-500 transition-colors svg-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7"></path></svg>
                                </div>
                                <span class="font-semibold tracking-wide text-xs group-hover:text-emerald-700 transition-colors">ACOLHER</span>
                            </div>
                            <div class="w-4 h-4 rounded-full border-2 border-slate-300 group-hover:border-emerald-400 transition-colors indicator flex items-center justify-center"></div>
                        </button>
                        
                        <button onclick="window.selectTeseOption(this, ${teseNum}, 'b')" type="button" class="btn-tese-option group relative w-full flex items-center justify-between px-4 py-2 rounded-lg border border-slate-200 bg-slate-50 hover:bg-white hover:border-rose-400 hover:shadow-sm text-slate-600 transition-all duration-300">
                             <div class="flex items-center gap-3">
                                <div class="w-7 h-7 rounded-full bg-white shadow-sm flex items-center justify-center group-hover:bg-rose-50 transition-colors icon-container">
                                    <svg class="w-4 h-4 text-slate-400 group-hover:text-rose-500 transition-colors svg-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M6 18L18 6M6 6l12 12"></path></svg>
                                </div>
                                <span class="font-semibold tracking-wide text-xs group-hover:text-rose-700 transition-colors">NÃO ACOLHER</span>
                            </div>
                            <div class="w-4 h-4 rounded-full border-2 border-slate-300 group-hover:border-rose-400 transition-colors indicator flex items-center justify-center"></div>
                        </button>
                    </div>
                </div>`;
            });

            // Injeta botões interativos para a Fase 3 (Admissibilidade)
            // Formato com resultado: [DECISAO_ADMISSIBILIDADE_PUNITIVA:NAO]
            // Formato legado (sem valor): [DECISAO_ADMISSIBILIDADE_PUNITIVA]
            rawHtml = rawHtml.replace(/\[DECISAO_ADMISSIBILIDADE_([A-ZÇÃÕ_]+)(?::([A-Z_]+))?\]/g, function (match, tipo, resultado) {
                hasDecisionButtons = true;

                // Normaliza o tipo (remove sufixo de fallback como SIM_OU_NAO)
                const tipoLimpo = tipo.replace(/_.*$/, '');

                let teseNome = tipoLimpo;
                if (tipoLimpo === 'TEMPESTIVIDADE') teseNome = 'TEMPESTIVIDADE';
                else if (tipoLimpo === 'PUNITIVA') teseNome = 'PRESCRIÇÃO PUNITIVA';
                else if (tipoLimpo === 'INTERCORRENTE') teseNome = 'PRESCRIÇÃO INTERCORRENTE';
                else if (tipoLimpo === 'DECADENCIA') teseNome = 'DECADÊNCIA';

                const teseIdAttr = `ADM_${tipoLimpo}`;

                // Determina labels contextuais com base no resultado técnico
                // resultado: 'SIM', 'NAO', 'NAO_SE_APLICA' ou undefined (fallback legado)
                const r = (resultado || '').toUpperCase();
                let labelA, labelB, subA, subB;

                if (r === 'SIM') {
                    // Resultado técnico: problema encontrado (ex: prescrição SIM, intempestividade NÃO=intempestivo)
                    labelA = 'CONFIRMAR';
                    subA   = 'Mantém: resultado técnico prevalece';
                    labelB = 'AFASTAR';
                    subB   = 'Inverte: resultado passa a NÃO';
                } else if (r === 'NAO') {
                    // Resultado técnico: sem problema (ex: prescrição NÃO, tempestivo SIM)
                    labelA = 'CONFIRMAR';
                    subA   = 'Mantém: resultado técnico prevalece';
                    labelB = 'CONVERTER PARA SIM';
                    subB   = 'Atenção: declara o problema como existente';
                } else if (r === 'NAO_SE_APLICA') {
                    labelA = 'CONFIRMAR';
                    subA   = 'Mantém: não se aplica (FILTRO 1)';
                    labelB = 'FORÇAR ANÁLISE';
                    subB   = 'Aviso: contraria a blindagem CETRAN/SC 381/2022';
                } else {
                    // Fallback legado: sem valor embutido
                    labelA = 'ACOLHER';
                    subA   = 'Mantém o resultado técnico';
                    labelB = 'NÃO ACOLHER';
                    subB   = 'Inverte o resultado técnico';
                }

                return `
                <div class="flex flex-col gap-2 mt-2 mb-4 p-4 sm:px-5 bg-white border border-[#e2e8f0] shadow-sm hover:shadow transition-shadow duration-300 rounded-xl tese-decision-block" data-tese="${teseIdAttr}">
                    <div class="flex items-center gap-2 mb-1 pb-2 border-b border-gray-100">
                        <div class="w-6 h-6 rounded-full bg-indigo-50 text-indigo-600 flex items-center justify-center font-bold text-xs"><svg fill="none" class="w-4 h-4" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg></div>
                        <span class="font-semibold text-gray-800 text-sm">Decisão sobre: ${teseNome}</span>
                    </div>
                    <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        <button onclick="window.selectTeseOption(this, '${teseIdAttr}', 'a')" type="button" class="btn-tese-option group relative w-full flex flex-col items-start px-4 py-3 rounded-lg border border-slate-200 bg-slate-50 hover:bg-white hover:border-emerald-400 hover:shadow-sm text-slate-600 transition-all duration-300">
                            <div class="flex items-center gap-3 w-full justify-between">
                                <div class="flex items-center gap-2">
                                    <div class="w-7 h-7 rounded-full bg-white shadow-sm flex items-center justify-center group-hover:bg-emerald-50 transition-colors icon-container flex-shrink-0">
                                        <svg class="w-4 h-4 text-slate-400 group-hover:text-emerald-500 transition-colors svg-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7"></path></svg>
                                    </div>
                                    <span class="font-semibold tracking-wide text-xs group-hover:text-emerald-700 transition-colors">${labelA}</span>
                                </div>
                                <div class="w-4 h-4 rounded-full border-2 border-slate-300 group-hover:border-emerald-400 transition-colors indicator flex items-center justify-center flex-shrink-0"></div>
                            </div>
                            <p class="text-xs text-slate-400 mt-1 ml-9 group-hover:text-emerald-600">${subA}</p>
                        </button>

                        <button onclick="window.selectTeseOption(this, '${teseIdAttr}', 'b')" type="button" class="btn-tese-option group relative w-full flex flex-col items-start px-4 py-3 rounded-lg border border-slate-200 bg-slate-50 hover:bg-white hover:border-rose-400 hover:shadow-sm text-slate-600 transition-all duration-300">
                            <div class="flex items-center gap-3 w-full justify-between">
                                <div class="flex items-center gap-2">
                                    <div class="w-7 h-7 rounded-full bg-white shadow-sm flex items-center justify-center group-hover:bg-rose-50 transition-colors icon-container flex-shrink-0">
                                        <svg class="w-4 h-4 text-slate-400 group-hover:text-rose-500 transition-colors svg-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M6 18L18 6M6 6l12 12"></path></svg>
                                    </div>
                                    <span class="font-semibold tracking-wide text-xs group-hover:text-rose-700 transition-colors">${labelB}</span>
                                </div>
                                <div class="w-4 h-4 rounded-full border-2 border-slate-300 group-hover:border-rose-400 transition-colors indicator flex items-center justify-center flex-shrink-0"></div>
                            </div>
                            <p class="text-xs text-slate-400 mt-1 ml-9 group-hover:text-rose-600">${subB}</p>
                        </button>
                    </div>
                </div>`;
            });

            if (hasDecisionButtons) {
                rawHtml += `
                <div class="mt-4 pt-4 border-t border-[#dde3ea] flex justify-center sm:justify-end">
                    <button onclick="window.submitTeseDecisions(this)" type="button" class="group relative overflow-hidden rounded-lg bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white font-medium py-2.5 px-6 shadow hover:shadow-md transition-all duration-300 flex items-center justify-center gap-2 transform hover:-translate-y-0.5 text-sm">
                        <span class="relative z-10 tracking-wide">Confirmar e Gerar Parecer</span>
                        <svg class="w-4 h-4 relative z-10 group-hover:translate-x-1 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M13 7l5 5m0 0l-5 5m5-5H6"></path></svg>
                    </button>
                </div>`;
            }

            // Injeta Formulário de Avaliação (NPS/Score)
            rawHtml = rawHtml.replace(/\[FEEDBACK_FORM\]/g, function () {
                return `
                <div id="feedback-container" class="bg-slate-800/80 border border-slate-700 p-5 rounded-2xl mb-6 shadow-sm relative overflow-hidden mt-6">
                    <div class="flex items-center gap-3 mb-4">
                        <div class="w-10 h-10 rounded-full bg-brand-accent/20 flex items-center justify-center text-brand-accent">
                            <i class="ph-fill ph-star text-xl"></i>
                        </div>
                        <div>
                            <h4 class="text-white font-bold text-base">Avalie o Parecer da IA</h4>
                            <p class="text-slate-400 text-xs mt-0.5">O quão preciso e útil foi este resultado?</p>
                        </div>
                    </div>
                    <div class="px-2 mb-6">
                        <div class="flex justify-between text-xs font-semibold text-slate-500 mb-2">
                            <span>0% (Refazer)</span>
                            <span id="feedback-score-display" class="text-brand-accent font-bold text-sm">100% (Perfeito)</span>
                        </div>
                        <input type="range" id="feedback-slider" min="0" max="100" value="100" step="10" class="w-full h-2 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-brand-accent" oninput="updateFeedbackUI(this.value)">
                    </div>
                    <div id="feedback-details" class="hidden flex-col gap-4 animate-fade-in mt-4 pt-4 border-t border-slate-700">
                        <p class="text-sm text-slate-300 font-medium">O que a IA deixou passar? (Opcional)</p>
                        <div class="flex flex-wrap gap-2" id="feedback-tags-container">
                            <button onclick="toggleFeedbackTag(this)" class="px-3 py-1.5 rounded-lg border border-slate-600 text-xs text-slate-400 hover:border-brand-accent hover:text-brand-accent transition-colors">Errou Data/Cálculo</button>
                            <button onclick="toggleFeedbackTag(this)" class="px-3 py-1.5 rounded-lg border border-slate-600 text-xs text-slate-400 hover:border-brand-accent hover:text-brand-accent transition-colors">Faltou Jurisprudência</button>
                            <button onclick="toggleFeedbackTag(this)" class="px-3 py-1.5 rounded-lg border border-slate-600 text-xs text-slate-400 hover:border-brand-accent hover:text-brand-accent transition-colors">Alucinou Fatos</button>
                            <button onclick="toggleFeedbackTag(this)" class="px-3 py-1.5 rounded-lg border border-slate-600 text-xs text-slate-400 hover:border-brand-accent hover:text-brand-accent transition-colors">Tom Inadequado</button>
                            <button onclick="toggleFeedbackTag(this)" class="px-3 py-1.5 rounded-lg border border-slate-600 text-xs text-slate-400 hover:border-brand-accent hover:text-brand-accent transition-colors">Outros</button>
                        </div>
                        <textarea id="feedback-notes" rows="2" class="w-full bg-slate-900 border border-slate-700 rounded-xl p-3 text-sm text-slate-200 focus:outline-none focus:border-brand-accent focus:ring-1 focus:ring-brand-accent/50 resize-none" placeholder="Detalhes (ex: Faltou citar o Artigo 281)..."></textarea>
                    </div>
                    <div class="mt-4 flex justify-end">
                        <button id="btn-submit-feedback" onclick="submitFeedback()" class="bg-brand-accent hover:bg-green-600 text-space-950 font-bold py-2.5 px-6 rounded-xl transition-colors shadow-lg shadow-green-500/20 text-sm flex items-center gap-2">
                            <i class="ph-bold ph-check"></i> Enviar Avaliação
                        </button>
                    </div>
                </div>
                `;
            });

            // Injeta cards de Pastas (Fase 7)
            // ── FASE1_CONFIRM: Formulário de confirmação do auto-preenchimento ──
            rawHtml = rawHtml.replace(/\[FASE1_CONFIRM:(.*?)\](?:<\/p>)?/gs, function (match, jsonStr) {
                let dados = {};
                try {
                    // marked.parse converte " em &quot; — desfaz antes do JSON.parse
                    const unescaped = jsonStr
                        .replace(/&quot;/g, '"')
                        .replace(/&#39;/g, "'")
                        .replace(/&amp;/g, '&')
                        .replace(/&lt;/g, '<')
                        .replace(/&gt;/g, '>');
                    dados = JSON.parse(unescaped);
                } catch(e) { console.error('FASE1_CONFIRM parse error:', e, jsonStr); }

                function confBadge(conf) {
                    if (conf === 'alta')  return '<span class="inline-flex items-center gap-1 text-[10px] font-bold text-emerald-600 bg-emerald-50 border border-emerald-200 rounded-full px-2 py-0.5"><svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"/></svg>Encontrado</span>';
                    if (conf === 'baixa') return '<span class="inline-flex items-center gap-1 text-[10px] font-bold text-amber-600 bg-amber-50 border border-amber-200 rounded-full px-2 py-0.5"><svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M12 9v4m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/></svg>Verificar</span>';
                    return '<span class="inline-flex items-center gap-1 text-[10px] font-bold text-gray-400 bg-gray-50 border border-gray-200 rounded-full px-2 py-0.5"><svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M6 18L18 6M6 6l12 12"/></svg>Não encontrado</span>';
                }

                function field(id, label, value, conf, type='text', placeholder='') {
                    const val = (value && value !== 'null') ? value : '';
                    const isAlert = conf === 'baixa' || conf === 'nulo';
                    const borderCls = conf === 'alta' ? 'border-emerald-200 focus:border-emerald-400' : conf === 'baixa' ? 'border-amber-200 focus:border-amber-400' : 'border-gray-200 focus:border-blue-400';
                    return `
                    <div class="flex flex-col gap-1">
                        <div class="flex items-center justify-between">
                            <label for="f1_${id}" class="text-xs font-semibold text-gray-600 uppercase tracking-wide">${label}</label>
                            ${confBadge(conf)}
                        </div>
                        <input id="f1_${id}" type="${type}" value="${val}" placeholder="${placeholder || 'Preencha manualmente'}"
                            class="w-full px-3 py-2 text-sm rounded-lg border ${borderCls} bg-white focus:outline-none focus:ring-2 focus:ring-blue-100 transition-colors ${isAlert ? 'font-medium' : ''}">
                    </div>`;
                }

                return `
                <div class="mt-3 mb-2 rounded-xl border border-blue-100 bg-white shadow-sm overflow-hidden">
                    <div class="flex items-center gap-2 px-4 py-3 bg-gradient-to-r from-blue-50 to-indigo-50 border-b border-blue-100">
                        <svg class="w-5 h-5 text-blue-500 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/></svg>
                        <div>
                            <p class="text-sm font-bold text-gray-800">Dados extraídos automaticamente</p>
                            <p class="text-xs text-gray-500">Revise, corrija se necessário e confirme para avançar.</p>
                        </div>
                    </div>
                    <div class="p-4 grid grid-cols-1 sm:grid-cols-2 gap-3" id="fase1-form-fields">
                        <div class="flex flex-col gap-1 sm:col-span-2">
                            <div class="flex items-center justify-between">
                                <label for="f1_data_sessao" class="text-xs font-semibold text-gray-600 uppercase tracking-wide">Data da Sessão</label>
                                <span class="inline-flex items-center gap-1 text-[10px] font-bold text-blue-600 bg-blue-50 border border-blue-200 rounded-full px-2 py-0.5">Preenchimento manual</span>
                            </div>
                            <input id="f1_data_sessao" type="text" placeholder="DD/MM/AAAA — obrigatório"
                                class="w-full px-3 py-2 text-sm rounded-lg border border-blue-200 focus:border-blue-400 bg-blue-50/30 focus:outline-none focus:ring-2 focus:ring-blue-100 transition-colors font-medium">
                        </div>
                        ${field('pa',             'Processo Administrativo (PA)', dados.pa,            dados.pa_conf,             'text', 'Ex: 2024/00123')}
                        ${field('sgpe',           'SGPE',                         dados.sgpe,          dados.sgpe_conf,           'text', 'Ex: 987654')}
                        ${field('recorrente',     'Recorrente',                   dados.recorrente,    dados.recorrente_conf,     'text', 'Nome completo')}
                        ${field('prazo_final',    'Prazo Final para Protocolo',   dados.prazo_final,   dados.prazo_final_conf,    'text', 'DD/MM/AAAA')}
                        ${field('data_protocolo', 'Data do Protocolo',            dados.data_protocolo,dados.data_protocolo_conf, 'text', 'DD/MM/AAAA')}
                        ${field('paginas_defesa', 'Páginas da Defesa',            dados.paginas_defesa,dados.paginas_defesa_conf, 'text', 'Ex: 15-24')}
                    </div>
                    <div class="px-4 pb-4 flex flex-col sm:flex-row gap-2">
                        <button onclick="window.confirmarFase1()" type="button"
                            class="flex-1 flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700 active:scale-[0.98] text-white text-sm font-bold py-2.5 px-6 rounded-lg transition-all shadow-sm">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7"/></svg>
                            Confirmar e Avançar
                        </button>
                    </div>
                </div>`;
            });

            // Função global para confirmar Fase 1
            if (typeof window.confirmarFase1 === 'undefined') {
                window.confirmarFase1 = function() {
                    const get = id => (document.getElementById('f1_' + id)?.value || '').trim();
                    const sessao = (document.getElementById('f1_data_sessao')?.value || '').trim();
                    if (!sessao) {
                        document.getElementById('f1_data_sessao').focus();
                        document.getElementById('f1_data_sessao').classList.add('border-red-400', 'bg-red-50');
                        return;
                    }
                    const payload = {
                        data_sessao:    sessao,
                        pa:             get('pa'),
                        sgpe:           get('sgpe'),
                        recorrente:     get('recorrente'),
                        prazo_final:    get('prazo_final'),
                        data_protocolo: get('data_protocolo'),
                        paginas_defesa: get('paginas_defesa'),
                    };
                    window.sendMessage(null, 'FASE1_CONFIRM:' + JSON.stringify(payload));
                };
            }

            rawHtml = rawHtml.replace(/\[FOLDER_SELECT:(.*?)\]/g, function (match, folderData) {
                const folders = folderData.split('|');
                let html = '<div class="flex flex-wrap gap-3 mt-4">';
                
                folders.forEach(f => {
                    const parts = f.split('::');
                    if (parts.length === 2) {
                        const idx = parts[0];
                        const name = parts[1];
                        
                        html += `
                        <button onclick="document.getElementById('feedback-container')?.remove(); window.sendMessage(null, '${idx}')" class="cursor-pointer group flex items-center gap-3 bg-white border border-gray-200 hover:border-blue-400 hover:bg-gray-50 py-3 px-5 rounded-xl transition-all duration-200 shadow-sm">
                            <i class="ph-fill ph-folder text-blue-500 text-xl opacity-80 group-hover:opacity-100 transition-opacity"></i>
                            <span class="text-sm font-semibold tracking-wide text-gray-700 group-hover:text-blue-700 transition-colors">${name}</span>
                        </button>`;
                    }
                });
                
                html += '</div>';
                return html;
            });

            // Adiciona classes do Tailwind para formatar as tabelas dinâmicas do Gemini
            // Para injetar Tailwind Typography (prose) precisaríamos do plugin, então aplicamos CSS base aos elementos gerados

            return `<div class="markdown-content space-y-3 prose max-w-none text-sm text-[#444746] leading-relaxed break-words">
                <style>
                    .markdown-content table { width: 100%; border-collapse: collapse; margin-top: 10px; margin-bottom: 10px; font-size: 13px; }
                    .markdown-content th, .markdown-content td { border: 1px solid #dde3ea; padding: 8px 12px; text-align: left; }
                    .markdown-content th { background-color: #eff3f9; font-weight: 600; color: #1f1f1f; }
                    .markdown-content tr:nth-child(even) { background-color: #fafbfc; }
                    .markdown-content ul { list-style-type: disc; padding-left: 20px; }
                    .markdown-content ol { list-style-type: decimal; padding-left: 20px; }
                    .markdown-content a:not(.bg-blue-600) { color: #2563eb; text-decoration: underline; font-weight: 500; }
                    .markdown-content a:not(.bg-blue-600):hover { color: #1e40af; }
                    .markdown-content strong { color: #1f1f1f; font-weight: 700; }
                    .markdown-content hr { border-color: #dde3ea; margin: 15px 0; }
                </style>
                ${rawHtml}
            </div>`;
        }

        function pollTaskStatus(taskId, msgId, parecerId, taskType) {
            if (activeEventSource) { activeEventSource.close(); activeEventSource = null; }
            const eventSource = new EventSource(`/chat/stream/${taskId}/?parecer_id=${parecerId || ''}`);
            activeEventSource = eventSource;
            let streamedMarkdown = "";
            let msgContainer = document.getElementById(`msg-${msgId}`);
            const spinnerLabel = taskType === 'FASE1' ? 'Analisando Documentos...' : 'Sintetizando Conhecimento...';

            if (msgContainer) {
                msgContainer.innerHTML = `
                    <div class="w-8 h-8 rounded-full bg-brand-accent/20 flex-shrink-0 flex items-center justify-center">
                        <i class="ph-fill ph-scales text-brand-accent text-lg"></i>
                    </div>
                    <div id="stream-content-${msgId}" class="text-[#444746] w-full bg-white p-6 rounded-2xl shadow-sm border border-gray-100 transition-all duration-300 min-h-[60px] flex flex-col items-center justify-center gap-4 mt-2">
                        <div class="w-full max-w-sm h-[3px] bg-slate-100 rounded-full overflow-hidden relative shadow-inner">
                            <div class="absolute top-0 bottom-0 w-1/2 bg-gradient-to-r from-transparent via-brand-accent to-transparent animate-shimmer-cylon"></div>
                        </div>
                        <div class="text-center text-brand-accent/80 text-[10px] uppercase tracking-widest animate-pulse font-bold mt-1">${spinnerLabel}</div>
                    </div>
                `;
            }

            eventSource.onmessage = function(event) {
                try {
                    const data = JSON.parse(event.data);
                    
                    if (data.status === 'CHUNK') {
                        streamedMarkdown += data.text;
                        const contentDiv = document.getElementById(`stream-content-${msgId}`);
                        if (contentDiv) {
                            contentDiv.innerHTML = formatMessage(streamedMarkdown);
                            chatWindow.scrollTo({ top: chatWindow.scrollHeight, behavior: 'auto' });
                        }
                    } else if (data.status === 'SUCCESS') {
                        eventSource.close(); activeEventSource = null;
                        if (msgContainer) {
                            if (taskType === 'FASE1') {
                                // Fase 1: estilo de mensagem normal do assistente (formulário interativo)
                                msgContainer.innerHTML = `
                                    <div class="w-8 h-8 rounded-full bg-brand-accent/20 border border-brand-accent/30 flex-shrink-0 flex items-center justify-center"><i class="ph-fill ph-scales text-brand-accent text-lg"></i></div>
                                    <div class="text-gray-800 leading-relaxed pt-1 w-full">${formatMessage(data.reply)}</div>
                                `;
                            } else {
                                // Fase 5: estilo de sucesso com verde e som
                                msgContainer.innerHTML = `
                                    <div class="w-8 h-8 rounded-full bg-green-500 shadow-md shadow-green-200 flex-shrink-0 flex items-center justify-center text-white font-bold text-sm">✓</div>
                                    <div class="text-[#444746] leading-relaxed pt-1 w-full bg-white p-6 rounded-2xl shadow-sm border border-green-200 transition-opacity duration-500">${formatMessage(data.reply)}</div>
                                `;
                                try {
                                    const audio = new Audio('data:audio/mp3;base64,//NExAAAAANIAAAAAExBTUUzLjEwMKqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq');
                                    audio.volume = 0.5;
                                    audio.play();
                                } catch (e) { }
                            }

                            chatWindow.scrollTo({ top: chatWindow.scrollHeight, behavior: 'smooth' });
                            
                            // Em caso de streaming bem sucedido é seguro deixar as atualizações de Fase prosseguirem como originalmente o FrontEnd fazia.
                            // O FrontEnd habilita o input se 'status_fase' vem na resposta, mas só dentro do submitMessage.
                            // Vamos habilitar de volta os inputs, por garantia.
                            const sDots = document.getElementById('status-dots');
                            if (sDots) sDots.classList.add('hidden');
                            if (typeof enableInput === "function") enableInput();
                        }
                    } else if (data.status === 'FAILURE') {
                        eventSource.close(); activeEventSource = null;
                        if (msgContainer) {
                            msgContainer.innerHTML = `
                                <div class="w-8 h-8 rounded-full bg-red-600 flex-shrink-0 flex items-center justify-center text-white text-[10px]">!</div>
                                <div class="text-red-500 leading-relaxed pt-1 w-full bg-red-50 p-4 rounded-lg border border-red-100 overflow-x-auto"><pre class="text-xs font-mono whitespace-pre-wrap">Falha no Processamento: ${data.error}</pre></div>
                            `;
                            chatWindow.scrollTo({ top: chatWindow.scrollHeight, behavior: 'smooth' });
                        }
                        document.getElementById('status-dots').classList.add('hidden');
                        if (typeof enableInput === "function") enableInput();
                    }
                } catch (e) {
                    console.error("Erro processando pacote SSE:", e);
                }
            };

            eventSource.onerror = function(err) {
                console.error("Erro no SSE EventSource:", err);
                eventSource.close(); activeEventSource = null;
                document.getElementById('status-dots').classList.add('hidden');
                if (typeof enableInput === "function") enableInput();
                // Substitui o spinner por mensagem de erro acionável
                let msgContainer = document.getElementById(`msg-${msgId}`);
                if (msgContainer) {
                    msgContainer.innerHTML = `
                        <div class="w-8 h-8 rounded-full bg-amber-500 flex-shrink-0 flex items-center justify-center text-white font-bold text-sm">!</div>
                        <div class="text-amber-800 leading-relaxed pt-1 w-full bg-amber-50 p-4 rounded-xl border border-amber-200">
                            <p class="font-semibold mb-1">Conexão interrompida</p>
                            <p class="text-sm">O servidor demorou mais do que o esperado ou a conexão caiu. O processamento pode ter continuado em segundo plano.</p>
                            <p class="text-sm mt-2">Recarregue a página para verificar o estado atual do processo.</p>
                        </div>`;
                    chatWindow.scrollTo({ top: chatWindow.scrollHeight, behavior: 'smooth' });
                }
            };
        }

        window.addEventListener('beforeunload', function() {
            if (activeEventSource) { activeEventSource.close(); activeEventSource = null; }
        });

        // Logica para o Modal de Citações / Tese
        function openCitacaoModal() {
            document.getElementById('citacaoModal').classList.remove('hidden');
            switchCitacaoTab('nova'); // Abre sempre na abinha de criar
        }

        function closeCitacaoModal() {
            document.getElementById('citacaoModal').classList.add('hidden');
            resetCitacaoForm();
        }

        function switchCitacaoTab(tab) {
            const btnNova = document.getElementById('tab-btn-nova');
            const btnLista = document.getElementById('tab-btn-lista');
            const contentNova = document.getElementById('tab-content-nova');
            const contentLista = document.getElementById('tab-content-lista');

            if (tab === 'nova') {
                btnNova.className = "px-4 py-1.5 text-sm font-medium rounded-md bg-slate-800 text-slate-100 shadow-sm transition-all";
                btnLista.className = "px-4 py-1.5 text-sm font-medium rounded-md text-slate-400 hover:text-slate-300 transition-all";
                contentNova.classList.remove('hidden');
                contentLista.classList.add('hidden');
            } else {
                btnLista.className = "px-4 py-1.5 text-sm font-medium rounded-md bg-slate-800 text-slate-100 shadow-sm transition-all";
                btnNova.className = "px-4 py-1.5 text-sm font-medium rounded-md text-slate-400 hover:text-slate-300 transition-all";
                contentLista.classList.remove('hidden');
                contentNova.classList.add('hidden');
            }
        }

        function resetCitacaoForm() {
            document.getElementById('formCitacao').reset();
            document.getElementById('citacao_id_edit').value = '';
            
            const isPub = document.getElementById('citacao_is_public');
            if (isPub) isPub.checked = true;
            
            document.getElementById('btnSubmitCitacao').innerHTML = 'Salvar Citação';
            document.getElementById('btnSubmitCitacao').disabled = false;
            document.getElementById('btnCancelarEdicao').classList.add('hidden');
            document.getElementById('btnFecharModalNova').classList.remove('hidden');
            document.getElementById('help-text-titulo').innerText = "Um título curto para acha-la rápido pela barra lateral.";
        }

        function editCitacao(id) {
            const titulo = document.getElementById(`tese-titulo-${id}`).innerText;
            const conteudo = document.getElementById(`tese-conteudo-${id}`).innerText;
            const cardEl = document.getElementById(`tese-card-${id}`);

            document.getElementById('citacao_id_edit').value = id;
            document.getElementById('citacao_titulo').value = titulo;
            document.getElementById('citacao_conteudo').value = conteudo;
            
            if (cardEl) {
                const isPubAttr = cardEl.getAttribute('data-is-public');
                const isPub = document.getElementById('citacao_is_public');
                if (isPub) isPub.checked = (isPubAttr === 'true');
            }

            document.getElementById('btnSubmitCitacao').innerHTML = 'Atualizar Citação';
            document.getElementById('btnCancelarEdicao').classList.remove('hidden');
            document.getElementById('btnFecharModalNova').classList.add('hidden');
            document.getElementById('help-text-titulo').innerText = "Editando a citação selecionada.";

            switchCitacaoTab('nova');
        }

        async function deleteCitacao(id) {
            showConfirmDialog("Tem certeza que deseja excluir permanentemente esta citação do seu banco?", async () => { await _deleteCitacaoConfirmed(id); });
        }
        async function _deleteCitacaoConfirmed(id) {
            try {
                const response = await fetch(`/api/citacao/${id}/delete/`, {
                    method: 'POST',
                    headers: { 'X-CSRFToken': csrftoken }
                });
                if (response.ok) {
                    const card = document.getElementById(`tese-card-${id}`);
                    if (card) {
                        card.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
                        card.style.opacity = '0';
                        card.style.transform = 'scale(0.95)';
                    }

                    const countSpan = document.getElementById('count-citacoes');
                    if (countSpan) {
                        let count = parseInt(countSpan.innerText) || 1;
                        countSpan.innerText = count - 1;
                        if (count - 1 === 0) {
                            setTimeout(() => { window.location.reload(); }, 300);
                            return;
                        }
                    }

                    setTimeout(() => {
                        if (card) card.remove();
                    }, 300);
                } else {
                    showToast('Erro ao excluir citação.');
                }
            } catch (e) {
                console.error(e);
                showToast('Erro de conexão ao excluir citação.');
            }
        }

        async function submitCitacao(event) {
            event.preventDefault();
            const form = document.getElementById('formCitacao');
            const btn = document.getElementById('btnSubmitCitacao');
            const editId = document.getElementById('citacao_id_edit').value;

            const formData = new FormData(form);
            const isEditing = editId !== "";
            const url = isEditing ? `/api/citacao/${editId}/edit/` : '/api/citacao/create/';

            btn.disabled = true;
            btn.innerHTML = '<svg class="animate-spin h-5 w-5 mr-3 inline" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg> ' + (isEditing ? 'Atualizando...' : 'Salvando...');

            try {
                const response = await fetch(url, {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': csrftoken
                    },
                    body: formData
                });

                if (response.ok) {
                    closeCitacaoModal();
                    // Sucesso visual
                    const successToast = document.createElement('div');
                    successToast.className = 'fixed bottom-5 right-5 bg-green-500 text-white px-6 py-3 rounded-xl shadow-lg font-medium opacity-0 transition-opacity duration-300 z-[100]';
                    successToast.innerHTML = isEditing ? '✏️ Citação atualizada com sucesso!' : '✅ Citação salva com sucesso!';
                    document.body.appendChild(successToast);

                    setTimeout(() => { successToast.classList.remove('opacity-0'); }, 100);
                    setTimeout(() => {
                        successToast.classList.add('opacity-0');
                        setTimeout(() => window.location.reload(), 300);
                    }, 1200);
                } else {
                    showToast('Erro ao processar citação. Tente novamente.');
                    btn.disabled = false;
                    btn.innerHTML = isEditing ? 'Atualizar Citação' : 'Salvar Citação';
                }
            } catch (error) {
                console.error('Erro na requisição:', error);
                showToast('Erro de conexão ao servidor.');
                btn.disabled = false;
                btn.innerHTML = isEditing ? 'Atualizar Citação' : 'Salvar Citação';
            }
        }

        let isSubmitting = false;
        let activeEventSource = null;

        async function sendMessage(e, programmaticText = null) {
            if (isSubmitting) return;
            if (e && typeof e.preventDefault === 'function') e.preventDefault();
            if (!isUserAuthenticated) {
                showLoginModal();
                return;
            }

            const text = programmaticText !== null ? programmaticText : userInput.value.trim();
            if (text === "" && selectedFiles.length === 0) return;

            const isIniciar = text.toLowerCase() === 'iniciar';

            // If there's no active Process (Parecer), the ONLY permitted action is to type "iniciar"
            if (!currentParecerId && !isIniciar) {
                if (selectedFiles.length > 0) {
                    showToast("Digite apenas 'iniciar' para criar a nova solicitação, depois anexe os arquivos.", 'warning');
                    // Optional: remove files to avoid confusion
                    selectedFiles = [];
                    updateFilePreview();
                } else {
                    showToast("Por favor, digite 'iniciar' para começar uma nova análise.", 'warning');
                }
                return;
            }

            // Remove o placeholder inicial de "Digite Iniciar..." assim que rodar
            userInput.placeholder = "Mensagem ou comando...";

            homeScreen.classList.add('hidden-home');
            document.getElementById('chat-footer').classList.remove('hidden-home');

            const userDiv = document.createElement('div');
            userDiv.className = "flex justify-end mt-4";
            
            let userContent = "";
            if (text) userContent += formatMessage(text);
            if (selectedFiles.length > 0) {
                userContent += `<div class="mt-2 text-xs font-semibold text-green-800 bg-green-100 px-3 py-1 rounded-md inline-block">📎 ${selectedFiles.length} arquivo(s) anexado(s)</div>`;
            }
            if(!userContent) userContent = "[Anexo]";
            
            if (!text.startsWith('FASE1_CONFIRM:') && !isSilent) {
                userDiv.innerHTML = `<div class="bg-[#e9eef6] p-4 rounded-2xl max-w-[80%] text-[#1f1f1f] shadow-sm">${userContent}</div>`;
                messagesContainer.appendChild(userDiv);
            }

            userInput.value = "";
            chatWindow.scrollTo({ top: chatWindow.scrollHeight, behavior: 'smooth' });

            const tempId = Date.now();
            const jariDiv = document.createElement('div');
            jariDiv.id = `msg-${tempId}`;
            jariDiv.className = "flex justify-start items-start gap-3 mt-4 w-full";
            if (!isIniciar && !isSilent) {
                jariDiv.innerHTML = `
                    <div class="w-8 h-8 rounded-full bg-brand-accent/20 flex-shrink-0 flex items-center justify-center">
                        <i class="ph-fill ph-scales text-brand-accent text-lg"></i>
                    </div>
                    <div class="text-gray-800 w-full bg-white p-6 rounded-2xl shadow-sm border border-gray-100 flex flex-col items-center justify-center gap-4 min-h-[60px]">
                        <div class="w-full max-w-sm h-[3px] bg-slate-100 rounded-full overflow-hidden relative shadow-inner">
                            <div class="absolute top-0 bottom-0 w-1/2 bg-gradient-to-r from-transparent via-brand-accent to-transparent animate-shimmer-cylon"></div>
                        </div>
                    </div>
                `;
            } else {
                jariDiv.innerHTML = `
                    <div class="w-8 h-8 rounded-full bg-brand-accent/20 border border-brand-accent/30 shadow-[0_0_10px_rgba(34,197,94,0.2)] flex-shrink-0 flex items-center justify-center"><i class="ph-fill ph-scales text-brand-accent text-lg pt-0.5"></i></div>
                    <div class="text-gray-800 leading-relaxed pt-1 w-full animate-pulse">Iniciando análise...</div>
                `;
            }
            messagesContainer.appendChild(jariDiv);
            chatWindow.scrollTo({ top: chatWindow.scrollHeight, behavior: 'smooth' });

            const btnSend = document.getElementById('btn-send');
            isSubmitting = true;
            if (btnSend) btnSend.disabled = true;

            try {
                // Prepara payload (JSON se só texto, FormData se tiver arquivos)
                let fetchOptions = {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': csrftoken
                    }
                };

                if (selectedFiles.length > 0) {
                    const formData = new FormData();
                    formData.append('message', text);
                    if (currentParecerId) formData.append('parecer_id', currentParecerId);
                    if (currentPastaId) formData.append('pasta_id', currentPastaId);

                    selectedFiles.forEach((file, index) => {
                        formData.append(`file_${index}`, file);
                    });

                    fetchOptions.body = formData;

                    // Limpa anexos da view após o envio
                    selectedFiles = [];
                    renderFilePreview();
                } else {
                    fetchOptions.headers['Content-Type'] = 'application/json';
                    fetchOptions.body = JSON.stringify({ message: text, parecer_id: currentParecerId, pasta_id: currentPastaId });
                }

                const response = await fetch('/chat/message/', fetchOptions);

                // Limpa anexos da interface imediatamente após disparo
                if (selectedFiles.length > 0) {
                    selectedFiles = [];
                    renderFilePreview();
                }

                if (response.ok) {
                    const data = await response.json();

                    if (data.requires_login) {
                        showLoginModal();
                        document.getElementById(`msg-${tempId}`).remove();
                        return;
                    }
                    if (data.requires_plan) {
                        window.location.href = '/planos/';
                        return;
                    }

                    if (data.is_processing && data.task_id) {
                        const msgContainer = document.getElementById(`msg-${tempId}`);
                        msgContainer.innerHTML = `
                            <div class="w-8 h-8 rounded-full bg-brand-accent/20 flex-shrink-0 flex items-center justify-center"><i class="ph-fill ph-scales text-brand-accent text-lg"></i></div>
                            <div class="text-[#444746] w-full bg-white p-6 rounded-2xl shadow-sm border border-gray-100 mt-2">
                                ${formatMessage(data.reply)}
                                <div class="mt-8 flex flex-col items-center justify-center gap-4 w-full">
                                    <div class="w-full max-w-sm h-[3px] bg-slate-100 rounded-full overflow-hidden relative shadow-inner">
                                        <div class="absolute top-0 bottom-0 w-1/2 bg-gradient-to-r from-transparent via-brand-accent to-transparent animate-shimmer-cylon"></div>
                                    </div>
                                    <div class="text-center text-brand-accent/80 text-[10px] uppercase tracking-widest animate-pulse font-bold" id="status-${data.task_id}">PENSANDO PROFUNDAMENTE...</div>
                                </div>
                            </div>
                        `;
                        chatWindow.scrollTo({ top: chatWindow.scrollHeight, behavior: 'smooth' });

                        // Carrega os PDFs na lateral imediatamente (mesma lógica do fluxo normal)
                        let shouldOpenPdfAsync = false;
                        if (data.consolidado_url) {
                            pdfDocs.recurso = data.consolidado_url;
                            if (data.consolidado_name) document.getElementById('tab-recurso').innerText = data.consolidado_name;
                            shouldOpenPdfAsync = true;
                        }
                        if (data.autuacao_url) {
                            pdfDocs.autuacao = data.autuacao_url;
                            if (data.autuacao_name) document.getElementById('tab-autuacao').innerText = data.autuacao_name;
                            shouldOpenPdfAsync = true;
                        }
                        if (data.ata_url) {
                            pdfDocs.ata = data.ata_url;
                            if (data.ata_name) document.getElementById('tab-ata').innerText = data.ata_name;
                            shouldOpenPdfAsync = true;
                        }
                        if (shouldOpenPdfAsync) {
                            if (btnTogglePdf) {
                                btnTogglePdf.classList.remove('hidden');
                                btnTogglePdf.classList.add('md:flex');
                            }
                            const mh = document.getElementById('main-header');
                            if (mh) {
                                mh.classList.remove('md:hidden');
                                mh.classList.add('md:flex');
                            }
                            if (!pdfViewerActive) togglePdfViewer(true);
                        }

                        pollTaskStatus(data.task_id, tempId, currentParecerId, data.task_type);
                        return;
                    }

                    // Se o backend criou um novo processo através do 'iniciar',
                    // guarda o ID mas NÃO CRIA VISUALMENTE NA BARRA LATERAL AINDA!
                    if (data.active_parecer_id) {
                        currentParecerId = data.active_parecer_id;
                    }

                    document.getElementById(`msg-${tempId}`).innerHTML = `
                        <div class="w-8 h-8 rounded-full bg-brand-accent/20 border border-brand-accent/30 shadow-[0_0_10px_rgba(34,197,94,0.2)] flex-shrink-0 flex items-center justify-center"><i class="ph-fill ph-scales text-brand-accent text-lg"></i></div>
                        <div class="text-gray-800 leading-relaxed pt-1 w-full">${formatMessage(data.reply)}</div>
                    `;

                    // Lógica para abrir/atualizar PDF e Nomes de Abas dinamicamente
                    let shouldOpenPdf = false;
                    
                    if (data.consolidado_url) {
                        pdfDocs.recurso = data.consolidado_url;
                        if (data.consolidado_name) {
                            document.getElementById('tab-recurso').innerText = data.consolidado_name;
                        }
                        shouldOpenPdf = true;
                    } else if (data.status_fase === 1) {
                        // Reset if we are initiating
                        pdfDocs.recurso = null;
                        document.getElementById('tab-recurso').innerText = "Defesa/Recurso";
                    }
                    
                    if (data.autuacao_url) {
                        pdfDocs.autuacao = data.autuacao_url;
                        if (data.autuacao_name) {
                            document.getElementById('tab-autuacao').innerText = data.autuacao_name;
                        }
                        shouldOpenPdf = true;
                    } else if (data.status_fase === 1) {
                        pdfDocs.autuacao = null;
                        document.getElementById('tab-autuacao').innerText = "Auto de Infração";
                    }

                    if (data.ata_url) {
                        pdfDocs.ata = data.ata_url;
                        if (data.ata_name) {
                            document.getElementById('tab-ata').innerText = data.ata_name;
                        }
                        shouldOpenPdf = true;
                    } else if (data.status_fase === 1) {
                        pdfDocs.ata = null;
                        document.getElementById('tab-ata').innerText = "Ata";
                    }

                    // Carregar o PDF na tela assim que os arquivos forem submetidos
                    if (shouldOpenPdf) {
                        if (btnTogglePdf) {
                            btnTogglePdf.classList.remove('hidden');
                            btnTogglePdf.classList.add('md:flex');
                        }
                        const mh = document.getElementById('main-header');
                        if (mh) {
                            mh.classList.remove('md:hidden');
                            mh.classList.add('md:flex');
                        }
                        
                        if (!pdfViewerActive) togglePdfViewer(true);
                    } else if (!shouldOpenPdf) {
                        if (btnTogglePdf) {
                            btnTogglePdf.classList.add('hidden');
                            btnTogglePdf.classList.remove('md:flex');
                        }
                        const mh = document.getElementById('main-header');
                        if (mh) {
                            mh.classList.remove('md:flex');
                            mh.classList.add('md:hidden');
                        }
                    }

                    // Se o processo chegou ao fim (salvo na pasta), mostra Toast e reinicia o layout
                    if (data.status_fase === 8) {
                        currentParecerId = null;

                        const toast = document.createElement('div');
                        toast.className = 'fixed top-10 left-1/2 transform -translate-x-1/2 bg-green-600 text-white px-6 py-4 rounded-xl shadow-2xl z-50 transition-opacity duration-500 font-medium flex items-center gap-3';
                        toast.innerHTML = '<svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg> <span>Parecer salvo com sucesso na pasta selecionada!</span>';
                        document.body.appendChild(toast);

                        setTimeout(() => {
                            toast.style.opacity = '0';
                            setTimeout(() => window.location.reload(), 500);
                        }, 2500);
                    } else if (currentParecerId) {
                        // Atualiza as sugestões do Agente Lateral (Dynamic Context Chips)
                        if (window.updateAgentChips) {
                            window.updateAgentChips(currentParecerId, data.reply || '');
                        }
                    }
                } else {
                    let errorMessage = "Erro ao processar mensagem.";
                    try {
                        const errorData = await response.json();
                        errorMessage = errorData.error || errorData.trace || errorMessage;
                        console.error("Backend Error:", errorData);
                    } catch (e) {
                        try {
                            const errorText = await response.text();
                            console.error("Backend HTML Error:", errorText);
                        } catch (e2) { }
                    }

                    document.getElementById(`msg-${tempId}`).innerHTML = `
                        <div class="w-8 h-8 rounded-full bg-red-600 flex-shrink-0 flex items-center justify-center text-white text-[10px]">!</div>
                        <div class="text-red-500 leading-relaxed pt-1 w-full overflow-x-auto"><pre class="text-xs font-mono whitespace-pre-wrap">${errorMessage}</pre></div>
                    `;
                }
            } catch (error) {
                console.error('Erro de Rede Exceção:', error);
                document.getElementById(`msg-${tempId}`).innerHTML = `
                    <div class="w-8 h-8 rounded-full bg-red-600 flex-shrink-0 flex items-center justify-center text-white text-[10px]">!</div>
                    <div class="text-red-500 leading-relaxed pt-1 w-full overflow-x-auto"><pre class="text-xs font-mono whitespace-pre-wrap">${error}</pre></div>
                `;
            } finally {
                isSubmitting = false;
                if (btnSend) btnSend.disabled = false;
            }
            chatWindow.scrollTo({ top: chatWindow.scrollHeight, behavior: 'smooth' });
        }

        document.getElementById('btn-send').addEventListener('click', sendMessage);
        userInput.addEventListener("keypress", (e) => {
            if (e.key === "Enter") sendMessage();
        });

        // --- Toggle Popover User Menu ---
        function toggleUserMenu() {
            const menu = document.getElementById('user-menu');
            if (menu.classList.contains('hidden')) {
                menu.classList.remove('hidden');
            } else {
                menu.classList.add('hidden');
            }
        }

        // Close user menu if clicked outside
        document.addEventListener('click', function (event) {
            const menu = document.getElementById('user-menu');
            const targetElement = event.target;

            if (menu && !menu.classList.contains('hidden')) {
                const isClickInsideMenu = menu.contains(targetElement);
                const isClickOnToggleInfo = targetElement.closest('button[onclick="toggleUserMenu()"]');

                if (!isClickInsideMenu && !isClickOnToggleInfo) {
                    menu.classList.add('hidden');
                }
            }
        });

        // --- Move Parecer Functions ---
        function openMoveModal(parecerId, currentPastaId) {
            document.getElementById('move-parecer-id').value = parecerId;
            document.getElementById('move-pasta-select').value = currentPastaId;

            document.querySelectorAll('.pasta-option').forEach(el => {
                el.classList.remove('border-green-500', 'bg-green-50', 'ring-2', 'ring-green-200');
                el.classList.add('border-slate-700');

                if (el.getAttribute('data-pasta-id') === currentPastaId) {
                    el.classList.remove('border-slate-700');
                    el.classList.add('border-green-500', 'bg-green-50', 'ring-2', 'ring-green-200');
                }
            });

            document.getElementById('move-modal').classList.remove('hidden');

            const selectedItem = document.querySelector(`.pasta-option[data-pasta-id="${currentPastaId}"]`);
            if (selectedItem) {
                setTimeout(() => selectedItem.scrollIntoView({ behavior: 'smooth', block: 'nearest' }), 50);
            }
        }

        function selectMovePasta(pastaId, element) {
            document.getElementById('move-pasta-select').value = pastaId;
            document.querySelectorAll('.pasta-option').forEach(el => {
                el.classList.remove('border-green-500', 'bg-green-50', 'ring-2', 'ring-green-200');
                el.classList.add('border-slate-700');
            });
            element.classList.remove('border-slate-700');
            element.classList.add('border-green-500', 'bg-green-50', 'ring-2', 'ring-green-200');
        }

        function closeMoveModal() {
            document.getElementById('move-modal').classList.add('hidden');
            document.getElementById('move-parecer-id').value = '';
        }

        async function submitMoveParecer() {
            const parecerId = document.getElementById('move-parecer-id').value;
            const novaPastaId = document.getElementById('move-pasta-select').value;

            if (!parecerId || !novaPastaId) return;

            try {
                const response = await fetch(`/parecer/${parecerId}/mover/`, {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': csrftoken,
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ nova_pasta_id: novaPastaId })
                });

                if (response.ok) {
                    closeMoveModal();
                    // Reload to update sidebar
                    window.location.reload();
                } else {
                    showToast('Erro ao mover o parecer.');
                }
            } catch (error) {
                console.error("Erro na movimentação: ", error);
            }
        }

        // --- Drag and Drop Folders (SortableJS) ---
        document.addEventListener('DOMContentLoaded', () => {
            const el = document.getElementById('sortable-folders');
            if (el && typeof Sortable !== 'undefined') {
                new Sortable(el, {
                    animation: 150,
                    ghostClass: 'bg-green-50', // Efeito na pasta sendo movida
                    handle: '.folder-item', // Apenas a barra da pasta é arrastável (não os projetos dentro)
                    onEnd: function () {
                        // Captura a nova ordem assim que o usuário solta o botão do mouse
                        const order = [];
                        document.querySelectorAll('#sortable-folders > .sortable-item').forEach((item, index) => {
                            order.push({
                                id: item.getAttribute('data-id'),
                                posicao: index + 1 // A ordem visual vira o número salvado no Banco (1, 2, 3...)
                            });
                        });

                        // Envia para o Backend salvar silenciosamente
                        fetch('/api/reorder-folders/', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                                'X-CSRFToken': csrftoken
                            },
                            body: JSON.stringify({ order: order })
                        })
                            .then(response => response.json())
                            .then(data => {
                                if (data.status !== 'success') {
                                    console.error('Erro ao salvar a ordem das pastas:', data.message);
                                }
                            })
                            .catch(err => console.error('Erro de requisição:', err));
                    }
                });
            }
        });

        // --- Funções Interativas do Chat (Menu de Teses) ---
        window.currentTeseDecisions = {};

        window.selectTeseOption = function (btn, teseNum, opcao) {
            // Salvar na memória
            window.currentTeseDecisions[teseNum] = opcao;

            // Atualizar UI
            const container = btn.closest('.tese-decision-block');
            container.classList.add('border-green-200', 'ring-1', 'ring-green-100');

            const buttons = container.querySelectorAll('button.btn-tese-option');
            buttons.forEach(b => {
                b.classList.remove('border-emerald-500', 'bg-emerald-50', 'text-emerald-800', 'border-rose-500', 'bg-rose-50', 'text-rose-800', 'shadow-md');
                b.classList.add('border-slate-100', 'bg-slate-900', 'text-slate-600');

                const iconContainer = b.querySelector('.icon-container');
                iconContainer.classList.remove('bg-emerald-500', 'bg-rose-500');
                iconContainer.classList.add('bg-slate-800');

                const svg = b.querySelector('.svg-icon');
                svg.classList.remove('text-white');
                svg.classList.add('text-slate-400');

                const indicator = b.querySelector('.indicator');
                indicator.classList.remove('border-emerald-500', 'bg-emerald-500', 'border-rose-500', 'bg-rose-500');
                indicator.classList.add('border-slate-300');
                indicator.innerHTML = '';
            });

            // Tick branco simples
            const checkSVG = `<svg class="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"></path></svg>`;

            if (opcao === 'a') {
                btn.classList.add('border-emerald-500', 'bg-emerald-50', 'text-emerald-800', 'shadow-md');
                btn.classList.remove('border-slate-100', 'bg-slate-900', 'text-slate-600');

                const iconContainer = btn.querySelector('.icon-container');
                iconContainer.classList.add('bg-emerald-500');
                iconContainer.classList.remove('bg-slate-800');

                const svg = btn.querySelector('.svg-icon');
                svg.classList.remove('text-slate-400');
                svg.classList.add('text-white');

                const indicator = btn.querySelector('.indicator');
                indicator.classList.remove('border-slate-300');
                indicator.classList.add('border-emerald-500', 'bg-emerald-500');
                indicator.innerHTML = checkSVG;
            } else {
                btn.classList.add('border-rose-500', 'bg-rose-50', 'text-rose-800', 'shadow-md');
                btn.classList.remove('border-slate-100', 'bg-slate-900', 'text-slate-600');

                const iconContainer = btn.querySelector('.icon-container');
                iconContainer.classList.add('bg-rose-500');
                iconContainer.classList.remove('bg-slate-800');

                const svg = btn.querySelector('.svg-icon');
                svg.classList.remove('text-slate-400');
                svg.classList.add('text-white');

                const indicator = btn.querySelector('.indicator');
                indicator.classList.remove('border-slate-300');
                indicator.classList.add('border-rose-500', 'bg-rose-500');
                indicator.innerHTML = checkSVG;
            }
        };

        window.submitTeseDecisions = function (btn) {
            const messageContainer = btn.closest('.markdown-content');
            const blocks = messageContainer.querySelectorAll('.tese-decision-block');
            const totalTeses = blocks.length;

            if (Object.keys(window.currentTeseDecisions).length < totalTeses) {
                showToast("Por favor, selecione uma opção para TODAS as teses antes de confirmar.", 'warning');
                return;
            }

            // Formatar a string de saída com quebras de linha e texto claro
            let choiceArray = [];
            for (const [key, value] of Object.entries(window.currentTeseDecisions)) {
                let suffix = '';
                if (value.toLowerCase() === 'a') {
                    suffix = 'Acolhida; ✔️';
                } else {
                    suffix = 'Não Acolhida; X';
                }

                if (String(key).startsWith('ADM_')) {
                    const admName = key.replace('ADM_', '');
                    choiceArray.push(`${admName} - ${suffix}`);
                } else {
                    choiceArray.push(`Tese ${key} – Síntese da alegação: ${suffix}`);
                }
            }
            // Usa '\n\n' (Markdown paragraph break duplo) para forçar quebra visual segura que não é apagada pelo DOM
            const finalString = choiceArray.join('\n\n');

            // Limpar memória
            window.currentTeseDecisions = {};

            // Ocultar apenas o botão de confirmar, para evitar duplo clique, mas mantém o painel inteiro visível
            if (btn) {
                btn.style.transition = 'opacity 0.3s ease';
                btn.style.opacity = '0';
                setTimeout(() => btn.remove(), 300);
            }
            
            // Travar os botões clicados (desabilitar interatividade)
            if (messageContainer) {
                messageContainer.style.pointerEvents = 'none';
                messageContainer.classList.add('opacity-80'); // Opcional: deixar as teses um pouco apagadas mas presentes
            }

            sendMessage(null, finalString);
        };

        // --- INÍCIO DO CÓDIGO DO SPLIT SCREEN (PDF VIEWER) ---
        let pdfDocs = { recurso: null, autuacao: null, ata: null };
        let pdfViewerActive = false;
        
        const splitContainer = document.getElementById('split-container');
        const pdfPanel = document.getElementById('pdf-split-panel');
        const chatPanel = document.getElementById('chat-split-panel');
        const resizer = document.getElementById('split-resizer');
        const pdfIframe = document.getElementById('pdf-iframe');
        const pdfPlaceholder = document.getElementById('pdf-placeholder');
        const btnTogglePdf = document.getElementById('btn-toggle-pdf');

        function togglePdfViewer(forceState = null) {
            pdfViewerActive = forceState !== null ? forceState : !pdfViewerActive;
            
            if (pdfViewerActive) {
                if(pdfPanel) {
                    pdfPanel.classList.remove('hidden');
                    pdfPanel.classList.add('flex');
                }
                if(resizer) {
                    resizer.classList.remove('hidden');
                    resizer.classList.add('flex');
                }
                
                // Em modo Split ativo: o chat deixa de ser flex-1 e passa pro width configurado,
                // enquanto o PDF se torna flex-1 (tela cheia/resto do espaço).
                if(chatPanel) {
                    chatPanel.classList.remove('flex-1');
                    chatPanel.style.maxWidth = '800px';
                    chatPanel.style.width = '45%';
                }
                
                // FECHA A SIDEBAR AO ABRIR O PDF AUTOMATICAMENTE (Se estiver aberta e em Desktop)
                if (window.innerWidth >= 768 && sidebar && !sidebar.classList.contains('sidebar-hidden')) {
                    toggleSidebar();
                }
                
                // Define Glassmorphism and Active Classes
                const inactiveClasses = ['bg-white/70', 'backdrop-blur-md', 'text-blue-700', 'hover:bg-white', 'border', 'border-white/50', 'shadow-lg', 'shadow-blue-500/10', 'hover:shadow-blue-500/20', 'hover:-translate-y-0.5', 'ring-1', 'ring-black/5'];
                const activeClasses = ['bg-blue-600', 'text-white', 'shadow-inner'];
                
                if (btnTogglePdf) {
                    btnTogglePdf.classList.remove(...inactiveClasses);
                    btnTogglePdf.classList.add(...activeClasses);
                }
                
                // Abre a primeira aba que tiver documento, com prioridade para Defesa/Recurso
                if (pdfDocs.recurso) {
                    switchPdfTab('recurso');
                } else if (pdfDocs.autuacao) {
                    switchPdfTab('autuacao');
                } else if (pdfDocs.ata) {
                    switchPdfTab('ata');
                } else {
                    // Fallback
                    switchPdfTab('recurso');
                }
            } else {
                if(pdfPanel) {
                    pdfPanel.classList.add('hidden');
                    pdfPanel.classList.remove('flex');
                }
                if(resizer) {
                    resizer.classList.add('hidden');
                    resizer.classList.remove('flex');
                }
                
                // Se fechou, o Chat volta a ser 100% via Layout do Tailwind nativo (flex-1 devolve comportamento fluido)
                if(chatPanel) {
                    chatPanel.classList.add('flex-1');
                    chatPanel.style.maxWidth = '';
                    chatPanel.style.width = '';
                }
                
                // Define Glassmorphism and Active Classes
                const inactiveClasses = ['bg-white/70', 'backdrop-blur-md', 'text-blue-700', 'hover:bg-white', 'border', 'border-white/50', 'shadow-lg', 'shadow-blue-500/10', 'hover:shadow-blue-500/20', 'hover:-translate-y-0.5', 'ring-1', 'ring-black/5'];
                const activeClasses = ['bg-blue-600', 'text-white', 'shadow-inner'];
                
                if(btnTogglePdf) {
                    btnTogglePdf.classList.remove(...activeClasses);
                    btnTogglePdf.classList.add(...inactiveClasses);
                }
            }
        }

        function switchPdfTab(tabName) {
            const btnRecurso = document.getElementById('tab-recurso');
            const btnAutuacao = document.getElementById('tab-autuacao');
            const btnAta = document.getElementById('tab-ata');
            
            // Define active and inactive logic for the new Segmented Control
            const activeClasses = ['bg-white', 'text-blue-700', 'font-semibold', 'shadow-sm', 'ring-1', 'ring-black/5'];
            const inactiveClasses = ['text-gray-500', 'hover:text-gray-700', 'font-medium', 'bg-transparent'];
            
            // Reset both tabs to inactive first
            if (btnRecurso) {
                btnRecurso.classList.remove(...activeClasses);
                btnRecurso.classList.add(...inactiveClasses);
            }
            if (btnAutuacao) {
                btnAutuacao.classList.remove(...activeClasses);
                btnAutuacao.classList.add(...inactiveClasses);
            }
            if(btnAta) {
                btnAta.classList.remove(...activeClasses);
                btnAta.classList.add(...inactiveClasses);
            }

            // Ocultar/Exibir abas se tiver/não tiver documento
            if (!pdfDocs.recurso) btnRecurso.classList.add('hidden'); else btnRecurso.classList.remove('hidden');
            if (!pdfDocs.autuacao) btnAutuacao.classList.add('hidden'); else btnAutuacao.classList.remove('hidden');
            if (btnAta) {
                 if (!pdfDocs.ata) btnAta.classList.add('hidden'); else btnAta.classList.remove('hidden');
            }

            if (tabName === 'recurso' && pdfDocs.recurso) {
                // Set Recurso as Active
                btnRecurso.classList.remove(...inactiveClasses);
                btnRecurso.classList.add(...activeClasses);
                
                pdfIframe.src = pdfDocs.recurso;
                pdfIframe.classList.remove('hidden');
                pdfPlaceholder.classList.add('hidden');
            } else if (tabName === 'autuacao' && pdfDocs.autuacao) {
                // Set Autuacao as Active
                btnAutuacao.classList.remove(...inactiveClasses);
                btnAutuacao.classList.add(...activeClasses);
                
                pdfIframe.src = pdfDocs.autuacao;
                pdfIframe.classList.remove('hidden');
                pdfPlaceholder.classList.add('hidden');
            } else if (tabName === 'ata' && pdfDocs.ata) {
                // Set Ata as Active
                if(btnAta) {
                    btnAta.classList.remove(...inactiveClasses);
                    btnAta.classList.add(...activeClasses);
                }
                
                pdfIframe.src = pdfDocs.ata;
                pdfIframe.classList.remove('hidden');
                pdfPlaceholder.classList.add('hidden');
            } else {
                pdfIframe.src = "";
                pdfIframe.classList.add('hidden');
                pdfPlaceholder.classList.remove('hidden');
            }
        }



        // --- Lógica de Arrastar (Resizer) ---
        let isResizing = false;
        
        if (resizer) {
            resizer.addEventListener('mousedown', (e) => {
                isResizing = true;
                document.body.style.cursor = 'col-resize';
                // Remove pointer events do iframe para ele não "roubar" o evento do mouse
                if (pdfIframe) pdfIframe.style.pointerEvents = 'none';
            });
        }

        document.addEventListener('mousemove', (e) => {
            if (!isResizing) return;
            const containerRect = splitContainer.getBoundingClientRect();
            
            // Agora manipulamos a largura do painel do CHAT (lado direito)
            // de modo inverso, e o PDF (flex-1) se ajusta automaticamente para tomar o resto
            let newChatWidth = containerRect.right - e.clientX;
            
            if (newChatWidth < containerRect.width * 0.25) newChatWidth = containerRect.width * 0.25;
            if (newChatWidth > containerRect.width * 0.8) newChatWidth = containerRect.width * 0.8;
            
            chatPanel.style.width = newChatWidth + 'px';
        });

        document.addEventListener('mouseup', () => {
            if (isResizing) {
                isResizing = false;
                document.body.style.cursor = '';
                if (pdfIframe) pdfIframe.style.pointerEvents = 'auto'; // Devolve para clicar no PDF
            }
        });

        // ================= Feedback UI Handlers =================
        function updateFeedbackUI(val) {
            const display = document.getElementById('feedback-score-display');
            const details = document.getElementById('feedback-details');
            
            if (val == 100) {
                display.innerText = '100% (Perfeito)';
                display.className = 'text-brand-accent font-bold text-sm';
                details.classList.add('hidden');
                details.classList.remove('flex');
            } else {
                display.innerText = val + '%';
                if (val >= 70) display.className = 'text-yellow-400 font-bold text-sm';
                else display.className = 'text-red-400 font-bold text-sm';
                
                details.classList.remove('hidden');
                details.classList.add('flex');
            }
        }

        function toggleFeedbackTag(btn) {
            btn.classList.toggle('bg-brand-accent/20');
            btn.classList.toggle('border-brand-accent');
            btn.classList.toggle('text-brand-accent');
            if (btn.hasAttribute('data-active')) {
                btn.removeAttribute('data-active');
            } else {
                btn.setAttribute('data-active', 'true');
            }
        }

        async function submitFeedback() {
            if (!currentParecerId) return;
            
            const btn = document.getElementById('btn-submit-feedback');
            btn.disabled = true;
            btn.innerHTML = '<i class="ph animate-spin ph-spinner"></i> Salvando...';
            
            const score = document.getElementById('feedback-slider').value;
            const notes = document.getElementById('feedback-notes') ? document.getElementById('feedback-notes').value : '';
            
            const tags = [];
            const tagBtns = document.querySelectorAll('#feedback-tags-container button[data-active="true"]');
            tagBtns.forEach(b => tags.push(b.innerText.trim()));
            
            try {
                const res = await fetch(`/api/parecer/${currentParecerId}/feedback/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': csrftoken
                    },
                    body: JSON.stringify({ score, tags, notes })
                });
                
                if (res.ok) {
                    const container = document.getElementById('feedback-container');
                    container.innerHTML = `
                        <div class="flex items-center gap-3 justify-center py-4">
                            <div class="w-10 h-10 rounded-full bg-green-500/20 flex items-center justify-center text-green-400">
                                <i class="ph-fill ph-check-circle text-2xl"></i>
                            </div>
                            <span class="text-green-400 font-semibold">Avaliação salva! Obrigado pelo feedback.</span>
                        </div>
                    `;
                } else {
                    showToast("Erro ao salvar avaliação.");
                    btn.disabled = false;
                    btn.innerHTML = '<i class="ph-bold ph-check"></i> Enviar Avaliação';
                }
            } catch (e) {
                console.error(e);
                showToast("Erro de conexão.");
                btn.disabled = false;
                btn.innerHTML = '<i class="ph-bold ph-check"></i> Enviar Avaliação';
            }
        }

    