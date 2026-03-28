import re

with open('venv/Alterações/index3.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Snippet 1: Head scripts
head_scripts = """
    <!-- Clerk Integration -->
    <script>
        window.clerkPublishableKey = "{{ CLERK_PUBLISHABLE_KEY }}";
    </script>
    <script async crossorigin="anonymous" data-clerk-publishable-key="{{ CLERK_PUBLISHABLE_KEY }}" src="https://cdn.jsdelivr.net/npm/@clerk/clerk-js@5/dist/clerk.browser.js" type="text/javascript"></script>

    <!-- LogRocket -->
    <script src="https://cdn.logr-in.com/LogRocket.min.js" crossorigin="anonymous"></script>
    <script>window.LogRocket && window.LogRocket.init('8ksywc/pjarisc');</script>
</head>
"""
content = content.replace("</head>", head_scripts)

# Snippet 2: Body scripts
body_scripts = """
    <!-- Auth & Clerk Scripts -->
    <script type="module">
        import { ptBR } from 'https://cdn.jsdelivr.net/npm/@clerk/localizations/dist/pt-BR.mjs';

        window.showLoginModal = function() {
            if (window.Clerk && window.Clerk.openSignIn) {
                window.Clerk.openSignIn({
                    forceRedirectUrl: '/auth-sync/',
                    signUpForceRedirectUrl: '/auth-sync/'
                });
            }
        };

        window.showSignUpModal = function() {
            if (window.Clerk && window.Clerk.openSignUp) {
                window.Clerk.openSignUp({
                    forceRedirectUrl: '/auth-sync/',
                    signInForceRedirectUrl: '/auth-sync/'
                });
            }
        };

        window.addEventListener('load', async function () {
            if (window.Clerk) {
                await window.Clerk.load({ localization: ptBR });
                
                if (window.location.hash.includes('sso-callback') || window.location.search.includes('sso-callback')) {
                    window.showLoginModal();
                    await window.Clerk.handleRedirectCallback();
                    window.location.href = "/app/";
                }

                if (window.Clerk.user) {
                    if (window.LogRocket) {
                        window.LogRocket.identify(window.Clerk.user.id, {
                            name: window.Clerk.user.fullName,
                            email: window.Clerk.user.primaryEmailAddress?.emailAddress
                        });
                    }
                    try {
                        const token = await window.Clerk.session.getToken();
                        if (token) {
                            document.cookie = `__session=${token}; path=/; max-age=3600; SameSite=Lax; Secure`;
                        }
                    } catch(e) {}
                    
                    const loginBtns = document.querySelectorAll("button[onclick*='showLoginModal'], a[href='#'][onclick*='showLoginModal']");
                    loginBtns.forEach(btn => {
                        btn.innerHTML = "Acessar P-JARI <i class='ph ph-arrow-right ml-2'></i>";
                        if(btn.tagName === 'BUTTON') {
                            btn.onclick = (e) => { e.preventDefault(); window.location.href = "/app/"; };
                        } else {
                            btn.onclick = (e) => { e.preventDefault(); window.location.href = "/app/"; };
                        }
                    });

                    const signupBtns = document.querySelectorAll("button[onclick*='showSignUpModal']");
                    signupBtns.forEach(btn => {
                        btn.innerHTML = "Acessar P-JARI <i class='ph ph-arrow-right ml-2'></i>";
                        btn.onclick = (e) => { e.preventDefault(); window.location.href = "/app/"; };
                    });
                }
            }
        });
    </script>
</body>
"""
content = content.replace("</body>", body_scripts)

# Add onclick to Header Button
content = content.replace(
    '<button class="glass-panel px-6 py-2 rounded-full text-sm font-semibold tracking-wide text-white flex items-center gap-2 hover:bg-white/5 hover:border-white/20 transition-colors">',
    '<button class="glass-panel px-6 py-2 rounded-full text-sm font-semibold tracking-wide text-white flex items-center gap-2 hover:bg-white/5 hover:border-white/20 transition-colors" onclick="showLoginModal(); return false;">'
)

# Add onclick to Footer Área do Cliente link
content = content.replace(
    '<a href="#" class="text-green-400/90 hover:text-green-300 transition-colors text-[14px] font-medium flex items-center gap-1 group">Área do Cliente <i class="ph-bold ph-arrow-up-right text-xs group-hover:translate-x-0.5 group-hover:-translate-y-0.5 transition-transform"></i></a>',
    '<a href="#" onclick="showLoginModal(); return false;" class="text-green-400/90 hover:text-green-300 transition-colors text-[14px] font-medium flex items-center gap-1 group">Área do Cliente <i class="ph-bold ph-arrow-up-right text-xs group-hover:translate-x-0.5 group-hover:-translate-y-0.5 transition-transform"></i></a>'
)

# Add onclick to Hero CTA (Quero testar)
content = content.replace(
    '<button class="shiny-cta px-8 py-4 rounded-full text-base font-semibold tracking-wide flex items-center gap-3 w-full sm:w-auto justify-center group animate-glow-pulse">',
    '<button class="shiny-cta px-8 py-4 rounded-full text-base font-semibold tracking-wide flex items-center gap-3 w-full sm:w-auto justify-center group animate-glow-pulse" onclick="showSignUpModal(); return false;">'
)


with open('templates/landing.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("landing.html atualizado.")
