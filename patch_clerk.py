import os

DEST_FILE = "/Volumes/D/P-Jari/templates/landing.html"

with open(DEST_FILE, "r") as f:
    html = f.read()

# Replace inline onclicks with function calls
html = html.replace("if(window.Clerk) window.Clerk.openSignIn(); return false;", "showLoginModal(); return false;")
html = html.replace("if(window.Clerk) window.Clerk.openSignUp(); return false;", "showSignUpModal(); return false;")

# The script block to add
init_script = """
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
                    try {
                        const token = await window.Clerk.session.getToken();
                        if (token) {
                            document.cookie = `__session=${token}; path=/; max-age=3600; SameSite=Lax; Secure`;
                        }
                    } catch(e) {}
                    
                    const loginBtns = document.querySelectorAll("button[onclick*='showLoginModal']");
                    loginBtns.forEach(btn => {
                        btn.innerHTML = "Acessar App <i class='ph ph-arrow-right ml-2'></i>";
                        btn.onclick = (e) => { e.preventDefault(); window.location.href = "/app/"; };
                    });

                    const signupBtns = document.querySelectorAll("button[onclick*='showSignUpModal']");
                    signupBtns.forEach(btn => {
                        btn.innerHTML = "Acessar App <i class='ph ph-arrow-right ml-2'></i>";
                        btn.onclick = (e) => { e.preventDefault(); window.location.href = "/app/"; };
                    });
                }
            }
        });
    </script>
</body>
"""

html = html.replace("</body>", init_script)

with open(DEST_FILE, "w") as f:
    f.write(html)

print("Landing page patched with Clerk load script.")
