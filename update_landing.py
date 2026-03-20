import os
import re

LOG_FILE = "/Users/geffersonvivan/.gemini/antigravity/brain/0622cdde-cb66-4767-81f0-6e2d50be4659/.system_generated/logs/overview.txt"
DEST_FILE = "/Volumes/D/P-Jari/templates/landing.html"

with open(LOG_FILE, "r") as f:
    logs = f.read()

# Find the last occurrence of <!DOCTYPE html>
start_idx = logs.rfind("<!DOCTYPE html>")
end_idx = logs.find("</html>", start_idx) + len("</html>")

html = logs[start_idx:end_idx]

# Inject Clerk script
clerk_script = """
    <script>
        window.clerkPublishableKey = "{{ CLERK_PUBLISHABLE_KEY }}";
    </script>
    <script async crossorigin="anonymous" data-clerk-publishable-key="{{ CLERK_PUBLISHABLE_KEY }}" src="https://cdn.jsdelivr.net/npm/@clerk/clerk-js@5/dist/clerk.browser.js" type="text/javascript"></script>
"""
html = html.replace("</head>", clerk_script + "\n</head>")

# Add onclick to login/signup buttons
login_texts = [
    "Área do Cliente",
    "Quero testar em um processo real",
    "Assinar Plano",
    "Comprar créditos"
]

# We will use regex to find <button ...> followed by some content that includes these texts, and inject onclick.
# Since it's tricky, let's just do a simple replacement on the exact button tags based on the provided HTML.

# 1. Área do Cliente
html = html.replace(
    '<button class="glass-panel px-6 py-2 rounded-full text-sm font-semibold tracking-wide text-white flex items-center gap-2 hover:bg-white/5 hover:border-white/20 transition-colors">',
    '<button class="glass-panel px-6 py-2 rounded-full text-sm font-semibold tracking-wide text-white flex items-center gap-2 hover:bg-white/5 hover:border-white/20 transition-colors" onclick="if(window.Clerk) window.Clerk.openSignIn(); return false;">'
)

# 2. Quero testar
html = html.replace(
    '<button class="shiny-cta px-8 py-4 rounded-full text-base font-semibold tracking-wide flex items-center gap-3 w-full sm:w-auto justify-center group animate-glow-pulse">',
    '<button class="shiny-cta px-8 py-4 rounded-full text-base font-semibold tracking-wide flex items-center gap-3 w-full sm:w-auto justify-center group animate-glow-pulse" onclick="if(window.Clerk) window.Clerk.openSignUp(); return false;">'
)

# 3. Assinar Plano Básico
html = html.replace(
    '<button class="relative w-full py-3.5 text-white font-medium text-[13px] bg-green-600 rounded-[11px] hover:bg-green-500 transition-colors z-10">\n                        Assinar Plano Básico',
    '<button class="relative w-full py-3.5 text-white font-medium text-[13px] bg-green-600 rounded-[11px] hover:bg-green-500 transition-colors z-10" onclick="if(window.Clerk) window.Clerk.openSignUp(); return false;">\n                        Assinar Plano Básico'
)

# 4. Assinar Plano Profissional
html = html.replace(
    '<button class="relative w-full py-3.5 text-white font-bold text-[13px] bg-green-500 rounded-[10px] flex justify-center items-center gap-2 hover:bg-green-400 transition-colors z-10">\n                            Assinar Plano Profissional',
    '<button class="relative w-full py-3.5 text-white font-bold text-[13px] bg-green-500 rounded-[10px] flex justify-center items-center gap-2 hover:bg-green-400 transition-colors z-10" onclick="if(window.Clerk) window.Clerk.openSignUp(); return false;">\n                            Assinar Plano Profissional'
)

# 5. Comprar créditos extras
html = html.replace(
    '<button class="relative w-full py-3.5 text-white font-medium text-[13px] bg-green-600 rounded-[11px] hover:bg-green-500 transition-colors z-10">\n                        Comprar créditos extras',
    '<button class="relative w-full py-3.5 text-white font-medium text-[13px] bg-green-600 rounded-[11px] hover:bg-green-500 transition-colors z-10" onclick="if(window.Clerk) window.Clerk.openSignUp(); return false;">\n                        Comprar créditos extras'
)

with open(DEST_FILE, "w") as f:
    f.write(html)

print("Landing page HTML updated successfully with Clerk integrations.")
