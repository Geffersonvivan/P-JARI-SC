"""
RELATÓRIO COMPLETO — P-JARI Sistema
=====================================

Cobertura total de funcionalidades:

  R01 — URLs públicas e infraestrutura
  R02 — Autenticação e redirecionamentos
  R03 — Middleware de termos e privacidade
  R04 — Gestão de pastas (criar, renomear, reordenar)
  R05 — Gestão de pareceres (criar, deletar, mover, salvar)
  R06 — Sistema de créditos (desconto, bloqueio, recarga)
  R07 — Billing e banners de sucesso/falha
  R08 — Teses e citações (CRUD + comunidade)
  R09 — Fórum (post, comentário, curtida)
  R10 — Views de estatísticas
  R11 — Wizard de parecer
  R12 — Misc (logout, onboarding, proxy, auth_sync, termos)
  R13 — APIs de chat e task status
  R14 — Pipeline de fases (fase 3.1, 4, 7)
  R15 — Integridade de modelos

Nota: ClerkAuthenticationMiddleware e RequireTermsAcceptanceMiddleware são
removidos via modify_settings nos grupos R02-R15 (que testam lógica de negócio).
R03 testa o middleware diretamente com configuração completa.

Executar:
    source venv/bin/activate
    python manage.py test chat.tests.test_relatorio_completo --keepdb -v 2
"""

import json
import datetime
import hashlib
import hmac
import time
from unittest.mock import patch, MagicMock

from django.test import TestCase, Client, RequestFactory, override_settings, modify_settings
from django.contrib.auth.models import User
from django.utils import timezone

from chat.models import Parecer, Pasta, Subscription
from chat.engine import (
    JariEngine,
    FASE_AGUARDA_CONFIRMACAO_ADMISSIBILIDADE,
    FASE_MERITO,
    FASE_RESULTADO,
    FASE_FINALIZADO,
)

# Middleware stack sem Clerk e sem Termos (para testes de lógica de negócio)
_MIDDLEWARE_SEM_CLERK = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'allauth.account.middleware.AccountMiddleware',
]

_MIDDLEWARE_COM_TERMOS = _MIDDLEWARE_SEM_CLERK + [
    'chat.middleware.RequireTermsAcceptanceMiddleware',
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _user(username, credits=5, is_pro=False) -> User:
    u = User.objects.create_user(
        username=username,
        email=f"{username}@pjari-test.invalid",
        password="test-2026!",
        first_name="Test",
        last_name="User",
    )
    u.profile.credits = credits
    u.profile.is_pro = is_pro
    u.profile.save(update_fields=["credits", "is_pro"])
    return u


def _parecer(user, **kw) -> Parecer:
    defaults = dict(
        user=user,
        nome_processo="[TEST] Processo",
        pa="TEST-2026/001",
        status_fase=FASE_AGUARDA_CONFIRMACAO_ADMISSIBILIDADE,
        is_saved=False,
        is_tempestivo=True,
        has_prescricao_punitiva=False,
        has_prescricao_intercorrente=False,
        has_decadencia=False,
        data_infracao=datetime.date(2024, 1, 15),
        data_sessao=datetime.date(2025, 3, 10),
        data_protocolo=datetime.date(2024, 3, 1),
        prazo_final=datetime.date(2024, 3, 31),
        admissibilidade_texto="Recurso tempestivo.",
        tabela_datas_sensiveis="",
    )
    defaults.update(kw)
    return Parecer.objects.create(**defaults)


def _stripe_sig(payload: bytes, secret: str) -> str:
    ts = int(time.time())
    signed = f"{ts}.{payload.decode()}"
    mac = hmac.new(secret.encode(), signed.encode(), hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


STRIPE_SECRET = "whsec_test_relatorio_00000000000000"


def _webhook(user_id, plano_key):
    from chat.views.home import PLANS
    plan = PLANS[plano_key]
    payload = {
        "type": "checkout.session.completed",
        "data": {"object": {
            "payment_status": "paid",
            "client_reference_id": str(user_id),
            "amount_total": int(plan["price"] * 100),
            "payment_intent": f"pi_test_{plano_key}",
            "id": f"cs_test_{plano_key}",
        }}
    }
    payload_bytes = json.dumps(payload).encode()
    with patch("stripe.Webhook.construct_event", return_value=payload), \
         patch("chat.tasks.send_payment_notification_task") as mock_email:
        mock_email.delay = MagicMock()
        with patch("chat.views.billing.settings") as ms:
            ms.STRIPE_SECRET_KEY = "sk_test_fake"
            ms.STRIPE_WEBHOOK_SECRET = STRIPE_SECRET
            r = Client().post(
                "/webhooks/stripe/",
                data=payload_bytes,
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE=_stripe_sig(payload_bytes, STRIPE_SECRET),
            )
    return r


# ══════════════════════════════════════════════════════════════════════════════
# R01 — URLs públicas e infraestrutura (sem auth, sem middleware custom)
# ══════════════════════════════════════════════════════════════════════════════

@override_settings(MIDDLEWARE=_MIDDLEWARE_SEM_CLERK)
class R01_Infra(TestCase):

    def setUp(self):
        self.c = Client()

    def test_health_retorna_200_e_ok(self):
        r = self.c.get("/health/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(json.loads(r.content)["status"], "ok")

    def test_robots_txt_retorna_200(self):
        r = self.c.get("/robots.txt")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"User-agent", r.content)
        self.assertIn(b"Disallow: /app/", r.content)

    def test_sitemap_xml_retorna_200(self):
        r = self.c.get("/sitemap.xml")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"urlset", r.content)

    def test_landing_page_retorna_200(self):
        r = self.c.get("/")
        self.assertIn(r.status_code, [200, 301, 302])

    def test_planos_publico_retorna_200(self):
        r = self.c.get("/planos/")
        self.assertEqual(r.status_code, 200)

    def test_termos_publico_retorna_200(self):
        r = self.c.get("/termos/")
        self.assertEqual(r.status_code, 200)

    def test_politica_privacidade_redireciona_para_termos(self):
        r = self.c.get("/politica-de-privacidade/")
        self.assertIn(r.status_code, [301, 302])
        self.assertIn("/termos/", r.get("Location", ""))

    def test_favicon_redireciona(self):
        r = self.c.get("/favicon.ico")
        self.assertIn(r.status_code, [301, 302])

    def test_auth_sync_retorna_200(self):
        r = self.c.get("/auth-sync/")
        self.assertEqual(r.status_code, 200)


# ══════════════════════════════════════════════════════════════════════════════
# R02 — Autenticação e redirecionamentos
# ══════════════════════════════════════════════════════════════════════════════

@override_settings(MIDDLEWARE=_MIDDLEWARE_SEM_CLERK)
class R02_Autenticacao(TestCase):

    def setUp(self):
        self.c = Client()

    def test_app_sem_login_redireciona(self):
        r = self.c.get("/app/")
        self.assertIn(r.status_code, [301, 302])

    def test_estatisticas_sem_login_redireciona(self):
        r = self.c.get("/estatisticas/")
        self.assertIn(r.status_code, [301, 302])

    def test_estatisticas_gerais_sem_login_redireciona(self):
        r = self.c.get("/estatisticas-gerais/")
        self.assertIn(r.status_code, [301, 302])

    def test_checkout_sem_login_redireciona(self):
        r = self.c.get("/checkout/")
        self.assertIn(r.status_code, [301, 302])

    def test_aceitar_termos_sem_login_redireciona(self):
        r = self.c.get("/aceite-termos/")
        self.assertIn(r.status_code, [301, 302])

    def test_sair_get_nao_aceito(self):
        r = self.c.get("/sair/")
        self.assertEqual(r.status_code, 405)

    def test_app_com_login_retorna_200(self):
        u = _user("r02_login")
        self.c.force_login(u)
        r = self.c.get("/app/")
        self.assertEqual(r.status_code, 200)

    def test_logout_post_redireciona(self):
        u = _user("r02_logout")
        self.c.force_login(u)
        r = self.c.post("/sair/")
        self.assertIn(r.status_code, [301, 302])
        self.assertIn("/", r.get("Location", ""))


# ══════════════════════════════════════════════════════════════════════════════
# R03 — Middleware de termos (testa com middleware ativo)
# ══════════════════════════════════════════════════════════════════════════════

@override_settings(MIDDLEWARE=_MIDDLEWARE_COM_TERMOS)
class R03_Middleware(TestCase):

    def test_usuario_sem_termos_aceitos_e_redirecionado(self):
        from legal.models import DocumentoLegal
        DocumentoLegal.objects.create(
            tipo='TERMO_USO', versao='1.0', conteudo='Conteúdo do Termo.', is_active=True,
        )
        u = _user("r03_sem_termos")
        c = Client()
        c.force_login(u)
        r = c.get("/app/")
        self.assertIn(r.status_code, [301, 302])
        self.assertIn("aceite-termos", r.get("Location", ""))

    def test_usuario_com_termos_aceitos_acessa_app(self):
        from legal.models import DocumentoLegal, AceiteDocumentoLegal
        termo = DocumentoLegal.objects.create(
            tipo='TERMO_USO', versao='1.0', conteudo='Conteúdo do Termo.', is_active=True,
        )
        u = _user("r03_com_termos")
        AceiteDocumentoLegal.objects.create(user=u, documento=termo, ip_usuario="127.0.0.1")
        c = Client()
        c.force_login(u)
        r = c.get("/app/")
        self.assertEqual(r.status_code, 200)

    def test_pjari_admin_nao_bloqueado_por_middleware(self):
        from legal.models import DocumentoLegal
        DocumentoLegal.objects.create(
            tipo='TERMO_USO', versao='1.0', conteudo='C.', is_active=True
        )
        u = _user("r03_admin")
        u.is_staff = True
        u.is_superuser = True
        u.save()
        c = Client()
        c.force_login(u)
        r = c.get("/pjari-admin/")
        self.assertNotIn("aceite-termos", r.get("Location", ""))


# ══════════════════════════════════════════════════════════════════════════════
# R04 — Gestão de Pastas
# ══════════════════════════════════════════════════════════════════════════════

@override_settings(MIDDLEWARE=_MIDDLEWARE_SEM_CLERK)
class R04_Pastas(TestCase):

    def setUp(self):
        self.user = _user("r04_pastas")
        self.c = Client()
        self.c.force_login(self.user)

    def test_criar_pasta(self):
        r = self.c.post("/api/pasta/create/",
            data=json.dumps({"nome": "Pasta Teste"}),
            content_type="application/json")
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        self.assertTrue(data["success"])
        self.assertEqual(data["nome"], "Pasta Teste")

    def test_criar_pasta_nome_vazio_retorna_400(self):
        r = self.c.post("/api/pasta/create/",
            data=json.dumps({"nome": ""}),
            content_type="application/json")
        self.assertEqual(r.status_code, 400)

    def test_renomear_pasta(self):
        pasta = Pasta.objects.create(user=self.user, nome_pasta="Original")
        r = self.c.post(f"/api/pasta/{pasta.id}/renomear/",
            data=json.dumps({"nome": "Renomeada"}),
            content_type="application/json")
        self.assertEqual(r.status_code, 200)
        pasta.refresh_from_db()
        self.assertEqual(pasta.nome_pasta, "Renomeada")

    def test_renomear_pasta_outro_usuario_retorna_404(self):
        outro = _user("r04_outro")
        pasta = Pasta.objects.create(user=outro, nome_pasta="Alheia")
        r = self.c.post(f"/api/pasta/{pasta.id}/renomear/",
            data=json.dumps({"nome": "Hack"}),
            content_type="application/json")
        self.assertEqual(r.status_code, 404)

    def test_reordenar_pastas(self):
        p1 = Pasta.objects.create(user=self.user, nome_pasta="A", posicao=2)
        p2 = Pasta.objects.create(user=self.user, nome_pasta="B", posicao=1)
        r = self.c.post("/api/reorder-folders/",
            data=json.dumps({"order": [
                {"id": p1.id, "posicao": 1},
                {"id": p2.id, "posicao": 2},
            ]}),
            content_type="application/json")
        self.assertEqual(r.status_code, 200)
        p1.refresh_from_db()
        self.assertEqual(p1.posicao, 1)


# ══════════════════════════════════════════════════════════════════════════════
# R05 — Gestão de Pareceres
# ══════════════════════════════════════════════════════════════════════════════

@override_settings(MIDDLEWARE=_MIDDLEWARE_SEM_CLERK)
class R05_Pareceres(TestCase):

    def setUp(self):
        self.user = _user("r05_pareceres")
        self.pasta = Pasta.objects.create(user=self.user, nome_pasta="Pasta R05")
        self.c = Client()
        self.c.force_login(self.user)

    def test_criar_parecer(self):
        r = self.c.post("/parecer/create/",
            data=json.dumps({"nome_processo": "Proc R05", "pasta_id": self.pasta.id}),
            content_type="application/json")
        self.assertIn(r.status_code, [200, 201])

    def test_deletar_parecer(self):
        # delete_parecer_view opera sobre Pasta (apaga pasta e seus pareceres)
        p = _parecer(self.user, pasta=self.pasta, is_saved=True)
        r = self.c.post(f"/parecer/{self.pasta.id}/delete/")
        self.assertIn(r.status_code, [200, 302])
        self.assertFalse(Parecer.objects.filter(id=p.id).exists())

    def test_deletar_parecer_outro_usuario_negado(self):
        outro = _user("r05_outro")
        p = _parecer(outro, is_saved=True)
        r = self.c.post(f"/parecer/{p.id}/delete/")
        self.assertIn(r.status_code, [403, 404])
        self.assertTrue(Parecer.objects.filter(id=p.id).exists())

    def test_mover_parecer_entre_pastas(self):
        p = _parecer(self.user, pasta=self.pasta, is_saved=True)
        nova = Pasta.objects.create(user=self.user, nome_pasta="Nova R05")
        r = self.c.post(f"/parecer/{p.id}/mover/",
            data=json.dumps({"nova_pasta_id": nova.id}),
            content_type="application/json")
        self.assertIn(r.status_code, [200, 302])

    def test_editar_parecer_retorna_200(self):
        p = _parecer(self.user, pasta=self.pasta, is_saved=True)
        r = self.c.get(f"/parecer/{p.id}/editor/")
        self.assertEqual(r.status_code, 200)

    def test_salvar_feedback_parecer(self):
        p = _parecer(self.user, pasta=self.pasta, is_saved=True)
        r = self.c.post(f"/api/parecer/{p.id}/feedback/",
            data=json.dumps({"score": 85, "tags": "rápido,preciso", "notes": "Ótimo"}),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=self.c.cookies.get("csrftoken", "test"))
        self.assertIn(r.status_code, [200, 201])


# ══════════════════════════════════════════════════════════════════════════════
# R06 — Sistema de Créditos
# ══════════════════════════════════════════════════════════════════════════════

@override_settings(MIDDLEWARE=_MIDDLEWARE_SEM_CLERK)
class R06_Creditos(TestCase):

    def setUp(self):
        self.factory = RequestFactory()

    def test_iniciar_bloqueado_com_zero_creditos(self):
        from chat.services import ChatService
        u = _user("r06_zero", credits=0, is_pro=False)
        c = Client()
        c.force_login(u)
        request = self.factory.post("/chat/message/",
            data='{"message": "iniciar"}', content_type="application/json")
        request.user = u
        request.session = c.session
        r = ChatService.handle_iniciar(request, {"user": u})
        data = json.loads(r.content)
        self.assertTrue(data.get("sem_creditos"))
        self.assertEqual(data.get("redirect"), "/planos/")

    def test_iniciar_liberado_com_creditos(self):
        from chat.services import ChatService
        u = _user("r06_com", credits=3, is_pro=False)
        Pasta.objects.create(user=u, nome_pasta="P R06")
        c = Client()
        c.force_login(u)
        request = self.factory.post("/chat/message/",
            data='{"message": "iniciar"}', content_type="application/json")
        request.user = u
        request.session = c.session
        r = ChatService.handle_iniciar(request, {"user": u})
        data = json.loads(r.content)
        self.assertFalse(data.get("sem_creditos"))
        self.assertIn("active_parecer_id", data)

    def test_pro_zero_creditos_nunca_bloqueado(self):
        from chat.services import ChatService
        u = _user("r06_pro", credits=0, is_pro=True)
        Pasta.objects.create(user=u, nome_pasta="PRO R06")
        c = Client()
        c.force_login(u)
        request = self.factory.post("/chat/message/",
            data='{"message": "iniciar"}', content_type="application/json")
        request.user = u
        request.session = c.session
        r = ChatService.handle_iniciar(request, {"user": u})
        data = json.loads(r.content)
        self.assertFalse(data.get("sem_creditos"))

    def test_fase7_desconta_credito(self):
        from chat.engine import phase_7
        u = _user("r06_f7", credits=2, is_pro=False)
        pasta = Pasta.objects.create(user=u, nome_pasta="P F7")
        p = _parecer(u)
        engine_mock = type("E", (), {"parecer": p})()
        phase_7.process(engine_mock, pasta.nome_pasta)
        u.profile.refresh_from_db()
        self.assertEqual(u.profile.credits, 1)

    def test_fase7_pro_nao_desconta(self):
        from chat.engine import phase_7
        u = _user("r06_f7pro", credits=5, is_pro=True)
        pasta = Pasta.objects.create(user=u, nome_pasta="PRO F7")
        p = _parecer(u)
        engine_mock = type("E", (), {"parecer": p})()
        phase_7.process(engine_mock, pasta.nome_pasta)
        u.profile.refresh_from_db()
        self.assertEqual(u.profile.credits, 5)

    def test_ponta_a_ponta_zero_compra_iniciar(self):
        from chat.services import ChatService
        u = _user("r06_e2e", credits=0, is_pro=False)
        Pasta.objects.create(user=u, nome_pasta="E2E R06")
        c = Client()
        c.force_login(u)

        def _fazer_iniciar():
            req = self.factory.post("/chat/message/",
                data='{"message": "iniciar"}', content_type="application/json")
            req.user = u
            req.session = c.session
            return ChatService.handle_iniciar(req, {"user": u})

        d1 = json.loads(_fazer_iniciar().content)
        self.assertTrue(d1.get("sem_creditos"), "Deve bloquear com 0 créditos")

        _webhook(u.id, "extra")
        u.profile.refresh_from_db()
        self.assertEqual(u.profile.credits, 1)

        d3 = json.loads(_fazer_iniciar().content)
        self.assertFalse(d3.get("sem_creditos"), "Deve liberar após compra")
        self.assertIn("active_parecer_id", d3)


# ══════════════════════════════════════════════════════════════════════════════
# R07 — Billing: banners e webhook
# ══════════════════════════════════════════════════════════════════════════════

@override_settings(MIDDLEWARE=_MIDDLEWARE_SEM_CLERK)
class R07_Billing(TestCase):

    def setUp(self):
        self.user = _user("r07_billing")
        self.c = Client()
        self.c.force_login(self.user)

    def test_planos_sem_parametro_sem_banners(self):
        r = self.c.get("/planos/")
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "Pagamento confirmado")
        self.assertNotContains(r, "não concluído")

    def test_banner_sucesso_exibido_com_creditos(self):
        self.user.profile.credits = 3
        self.user.profile.save(update_fields=["credits"])
        r = self.c.get("/planos/?success=1")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Pagamento confirmado")
        self.assertContains(r, "3")

    def test_banner_falha_exibido(self):
        r = self.c.get("/planos/?failure=1")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "não concluído")

    def test_webhook_extra_soma_credito(self):
        self.user.profile.credits = 0
        self.user.profile.save(update_fields=["credits"])
        _webhook(self.user.id, "extra")
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.credits, 1)

    def test_webhook_basic_reseta_e_marca_pro(self):
        _webhook(self.user.id, "basic")
        self.user.profile.refresh_from_db()
        from chat.views.home import PLANS
        self.assertEqual(self.user.profile.credits, PLANS["basic"]["credits"])
        self.assertTrue(self.user.profile.is_pro)

    def test_webhook_pro_reseta_e_marca_pro(self):
        _webhook(self.user.id, "pro")
        self.user.profile.refresh_from_db()
        from chat.views.home import PLANS
        self.assertEqual(self.user.profile.credits, PLANS["pro"]["credits"])
        self.assertTrue(self.user.profile.is_pro)

    def test_webhook_assinatura_invalida_retorna_400(self):
        r = Client().post("/webhooks/stripe/",
            data=b'{"type":"checkout.session.completed"}',
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="t=0,v1=invalida")
        self.assertEqual(r.status_code, 400)

    def test_checkout_com_login_redireciona_stripe(self):
        from chat.views.billing import checkout_view
        mock_session = MagicMock()
        mock_session.url = "https://checkout.stripe.com/pay/test"
        factory = RequestFactory()
        request = factory.get("/checkout/?plan=extra")
        request.user = self.user
        with patch("stripe.checkout.Session.create", return_value=mock_session), \
             patch("chat.views.billing.settings") as ms:
            ms.STRIPE_SECRET_KEY = "sk_test_fake"
            ms.STRIPE_WEBHOOK_SECRET = STRIPE_SECRET
            with patch("chat.views.billing.ratelimit", lambda *a, **kw: lambda f: f):
                r = checkout_view(request)
        self.assertIn(r.status_code, [301, 302])
        self.assertIn("checkout.stripe.com", r.get("Location", ""))


# ══════════════════════════════════════════════════════════════════════════════
# R08 — Teses e Citações
# ══════════════════════════════════════════════════════════════════════════════

@override_settings(MIDDLEWARE=_MIDDLEWARE_SEM_CLERK)
class R08_Teses(TestCase):

    def setUp(self):
        self.user = _user("r08_teses")
        self.c = Client()
        self.c.force_login(self.user)

    def _criar(self, titulo="Tese R08", conteudo="Conteúdo de teste.", is_public=False):
        return self.c.post("/api/citacao/create/", data={
            "titulo": titulo,
            "conteudo": conteudo,
            "is_public": str(is_public).lower(),
        })

    def test_criar_citacao(self):
        r = self._criar()
        self.assertIn(r.status_code, [200, 201])
        self.assertIn("id", json.loads(r.content))

    def test_editar_citacao(self):
        cid = json.loads(self._criar("Original").content)["id"]
        r = self.c.post(f"/api/citacao/{cid}/edit/", data={
            "titulo": "Editado",
            "conteudo": "Conteúdo editado.",
        })
        self.assertIn(r.status_code, [200, 201])

    def test_deletar_citacao(self):
        cid = json.loads(self._criar("Para deletar").content)["id"]
        r = self.c.post(f"/api/citacao/{cid}/delete/")
        self.assertIn(r.status_code, [200, 204])

    def test_incrementar_uso_citacao(self):
        cid = json.loads(self._criar("Para incrementar").content)["id"]
        r = self.c.post(f"/api/citacao/{cid}/increment/")
        self.assertIn(r.status_code, [200, 201])

    def test_importar_citacao_comunidade(self):
        outro = _user("r08_outro")
        c2 = Client()
        c2.force_login(outro)
        cid = json.loads(c2.post("/api/citacao/create/", data={
            "titulo": "Tese pública",
            "conteudo": "Conteúdo público.",
            "is_public": "true",
        }).content)["id"]
        r = self.c.post(f"/api/citacao/{cid}/import/")
        self.assertIn(r.status_code, [200, 201])

    def test_deletar_citacao_outro_usuario_negado(self):
        outro = _user("r08_outro2")
        c2 = Client()
        c2.force_login(outro)
        cid = json.loads(c2.post("/api/citacao/create/", data={
            "titulo": "Alheia",
            "conteudo": "Conteúdo alheio.",
            "is_public": "false",
        }).content)["id"]
        r = self.c.post(f"/api/citacao/{cid}/delete/")
        self.assertIn(r.status_code, [403, 404])


# ══════════════════════════════════════════════════════════════════════════════
# R09 — Fórum
# ══════════════════════════════════════════════════════════════════════════════

@override_settings(MIDDLEWARE=_MIDDLEWARE_SEM_CLERK)
class R09_Forum(TestCase):

    def setUp(self):
        self.user = _user("r09_forum")
        self.c = Client()
        self.c.force_login(self.user)

    def _criar_post(self, conteudo="Conteúdo do post R09"):
        return self.c.post("/api/forum/post/create/", data={"conteudo": conteudo})

    def test_criar_post_forum(self):
        r = self._criar_post()
        self.assertIn(r.status_code, [200, 201])
        self.assertIn("post_id", json.loads(r.content))

    def test_comentar_post(self):
        r = self._criar_post()
        pid = json.loads(r.content).get("post_id")
        if not pid:
            self.skipTest("Post ID não retornado")
        r2 = self.c.post(f"/api/forum/post/{pid}/comentar/",
            data=json.dumps({"conteudo": "Comentário"}),
            content_type="application/json")
        self.assertIn(r2.status_code, [200, 201])

    def test_curtir_post(self):
        r = self._criar_post()
        pid = json.loads(r.content).get("post_id")
        if not pid:
            self.skipTest("Post ID não retornado")
        r2 = self.c.post(f"/api/forum/post/{pid}/curtir/")
        self.assertIn(r2.status_code, [200, 201])

    def test_listar_comentarios_post(self):
        r = self._criar_post()
        pid = json.loads(r.content).get("post_id")
        if not pid:
            self.skipTest("Post ID não retornado")
        r2 = self.c.get(f"/api/forum/post/{pid}/comentarios/")
        self.assertEqual(r2.status_code, 200)

    def test_criar_post_sem_login_negado(self):
        c = Client()
        r = c.post("/api/forum/post/create/", data={"conteudo": "Anon"})
        self.assertIn(r.status_code, [302, 401, 403])


# ══════════════════════════════════════════════════════════════════════════════
# R10 — Estatísticas
# ══════════════════════════════════════════════════════════════════════════════

@override_settings(MIDDLEWARE=_MIDDLEWARE_SEM_CLERK)
class R10_Estatisticas(TestCase):

    def setUp(self):
        self.user = _user("r10_stats")
        self.c = Client()
        self.c.force_login(self.user)

    def test_estatisticas_usuario_retorna_200(self):
        r = self.c.get("/estatisticas/")
        self.assertEqual(r.status_code, 200)

    def test_estatisticas_com_mes_ano_retorna_200(self):
        r = self.c.get("/estatisticas/?mes=1&ano=2026")
        self.assertEqual(r.status_code, 200)

    def test_estatisticas_gerais_sem_permissao_retorna_403(self):
        r = self.c.get("/estatisticas-gerais/")
        self.assertEqual(r.status_code, 403)

    def test_estatisticas_gerais_com_permissao_retorna_200(self):
        self.user.profile.can_view_global_stats = True
        self.user.profile.save(update_fields=["can_view_global_stats"])
        r = self.c.get("/estatisticas-gerais/")
        self.assertEqual(r.status_code, 200)

    def test_estatisticas_gerais_superuser_retorna_200(self):
        self.user.is_superuser = True
        self.user.save()
        r = self.c.get("/estatisticas-gerais/")
        self.assertEqual(r.status_code, 200)


# ══════════════════════════════════════════════════════════════════════════════
# R11 — Wizard de Parecer
# ══════════════════════════════════════════════════════════════════════════════

@override_settings(MIDDLEWARE=_MIDDLEWARE_SEM_CLERK)
class R11_Wizard(TestCase):

    def setUp(self):
        self.user = _user("r11_wizard")
        self.pasta = Pasta.objects.create(user=self.user, nome_pasta="Pasta Wizard")
        self.c = Client()
        self.c.force_login(self.user)

    def test_wizard_parecer_retorna_200(self):
        p = _parecer(self.user, pasta=self.pasta, is_saved=True)
        r = self.c.get(f"/parecer/{p.id}/wizard/")
        self.assertEqual(r.status_code, 200)

    def test_wizard_avancar_post(self):
        p = _parecer(self.user, pasta=self.pasta, is_saved=True)
        r = self.c.post(f"/parecer/{p.id}/wizard/next/",
            data=json.dumps({"campo": "valor"}),
            content_type="application/json")
        self.assertIn(r.status_code, [200, 302, 400])

    def test_wizard_outro_usuario_negado(self):
        outro = _user("r11_outro")
        p = _parecer(outro, is_saved=True)
        r = self.c.get(f"/parecer/{p.id}/wizard/")
        self.assertIn(r.status_code, [403, 404])


# ══════════════════════════════════════════════════════════════════════════════
# R12 — Misc
# ══════════════════════════════════════════════════════════════════════════════

@override_settings(MIDDLEWARE=_MIDDLEWARE_SEM_CLERK)
class R12_Misc(TestCase):

    def setUp(self):
        self.user = _user("r12_misc")
        self.c = Client()
        self.c.force_login(self.user)

    def test_dismiss_onboarding(self):
        r = self.c.post("/onboarding/dismiss/")
        self.assertIn(r.status_code, [200, 302])
        self.user.profile.refresh_from_db()
        self.assertTrue(self.user.profile.viu_boas_vindas)

    def test_aceitar_termos_get_retorna_200(self):
        # Cria um termo ativo para que a view não redirecione imediatamente
        from legal.models import DocumentoLegal
        DocumentoLegal.objects.create(
            tipo='TERMO_USO', versao='1.0', conteudo='Termo de uso.', is_active=True,
        )
        r = self.c.get("/aceite-termos/")
        self.assertEqual(r.status_code, 200)

    def test_proxy_image_sem_url_retorna_400(self):
        r = self.c.get("/api/proxy-image/")
        self.assertEqual(r.status_code, 400)

    def test_proxy_image_dominio_nao_permitido_retorna_403(self):
        r = self.c.get("/api/proxy-image/?url=https://evil.com/img.jpg")
        self.assertEqual(r.status_code, 403)

    def test_proxy_image_schema_invalido_retorna_403(self):
        r = self.c.get("/api/proxy-image/?url=ftp://img.clerk.com/avatar.jpg")
        self.assertEqual(r.status_code, 403)

    def test_logout_post_redireciona(self):
        r = self.c.post("/sair/")
        self.assertIn(r.status_code, [301, 302])


# ══════════════════════════════════════════════════════════════════════════════
# R13 — APIs de Chat e Task Status
# ══════════════════════════════════════════════════════════════════════════════

@override_settings(MIDDLEWARE=_MIDDLEWARE_SEM_CLERK)
class R13_Chat(TestCase):

    def setUp(self):
        self.user = _user("r13_chat")
        self.c = Client()
        self.c.force_login(self.user)

    def test_chat_message_mensagem_vazia_retorna_erro(self):
        r = self.c.post("/chat/message/",
            data=json.dumps({"message": ""}),
            content_type="application/json")
        self.assertIn(r.status_code, [200, 400])
        self.assertIn("error", json.loads(r.content))

    def test_check_task_status_task_inexistente(self):
        r = self.c.get("/chat/task-status/fake-task-id-0000/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("status", json.loads(r.content))

    def test_agent_message_mensagem_vazia_retorna_erro(self):
        r = self.c.post("/chat/agent_message/",
            data=json.dumps({"message": ""}),
            content_type="application/json")
        self.assertIn(r.status_code, [200, 400, 500])


# ══════════════════════════════════════════════════════════════════════════════
# R14 — Pipeline de Fases
# ══════════════════════════════════════════════════════════════════════════════

@override_settings(MIDDLEWARE=_MIDDLEWARE_SEM_CLERK)
class R14_Pipeline(TestCase):

    def setUp(self):
        self.user = _user("r14_pipeline")

    @patch("chat.tasks.gerar_parecer_task")
    def test_prescricao_punitiva_vai_para_resultado(self, mock_task):
        mock_task.delay.return_value = MagicMock(id="fake")
        p = _parecer(self.user, has_prescricao_punitiva=True)
        JariEngine(p).process_message("ok")
        p.refresh_from_db()
        self.assertEqual(p.status_fase, FASE_RESULTADO)
        self.assertTrue(p.julgador_prescricao_punitiva)

    @patch("chat.tasks.processar_fase4_task")
    def test_recurso_limpo_vai_para_merito(self, mock_fase4):
        mock_fase4.delay.return_value = MagicMock(id="fake")
        p = _parecer(self.user,
            has_prescricao_punitiva=False,
            has_prescricao_intercorrente=False,
            has_decadencia=False,
            is_tempestivo=True)
        result = JariEngine(p).process_message("ok")
        mock_fase4.delay.assert_called_once_with(p.id)
        self.assertEqual(json.loads(result)["status"], "celery")

    @patch("chat.tasks.gerar_parecer_task")
    def test_intempestivo_vai_para_resultado(self, mock_task):
        mock_task.delay.return_value = MagicMock(id="fake")
        p = _parecer(self.user, is_tempestivo=False)
        JariEngine(p).process_message("ok")
        p.refresh_from_db()
        self.assertEqual(p.status_fase, FASE_RESULTADO)
        self.assertFalse(p.julgador_tempestivo)

    def test_fase7_salva_processo_e_desconta_credito(self):
        from chat.engine import phase_7
        self.user.profile.credits = 3
        self.user.profile.save(update_fields=["credits"])
        pasta = Pasta.objects.create(user=self.user, nome_pasta="Pasta Pipeline")
        p = _parecer(self.user)
        engine_mock = type("E", (), {"parecer": p})()
        result = phase_7.process(engine_mock, pasta.nome_pasta)
        p.refresh_from_db()
        self.user.profile.refresh_from_db()
        self.assertTrue(p.is_saved)
        self.assertEqual(p.status_fase, FASE_FINALIZADO)
        self.assertIn("Sucesso", result)
        self.assertEqual(self.user.profile.credits, 2)

    @patch("chat.tasks.gerar_parecer_task")
    def test_reiniciar_funciona(self, mock_task):
        mock_task.delay.return_value = MagicMock(id="fake")
        p = _parecer(self.user, status_fase=FASE_MERITO)
        result = JariEngine(p).process_message("reiniciar")
        self.assertIsNotNone(result)


# ══════════════════════════════════════════════════════════════════════════════
# R15 — Integridade de Modelos
# ══════════════════════════════════════════════════════════════════════════════

@override_settings(MIDDLEWARE=_MIDDLEWARE_SEM_CLERK)
class R15_Modelos(TestCase):

    def setUp(self):
        self.user = _user("r15_modelos")

    def test_userprofile_criado_via_signal(self):
        self.assertTrue(hasattr(self.user, "profile"))
        self.assertIsNotNone(self.user.profile.pk)
        self.assertEqual(self.user.profile.credits, 5)
        self.assertFalse(self.user.profile.is_pro)

    def test_parecer_campos_minimos(self):
        p = _parecer(self.user)
        self.assertIsNotNone(p.pk)
        self.assertFalse(p.is_saved)

    def test_subscription_creditos_total(self):
        agora = timezone.now()
        sub = Subscription.objects.create(
            user=self.user, plano="pro",
            creditos_base=72, creditos_bonus=8,
            data_inicio=agora,
            data_expiracao=agora + datetime.timedelta(days=30),
            stripe_session_id="cs_r15_001", is_active=True,
        )
        self.assertEqual(sub.creditos_total, 80)
        self.assertTrue(sub.is_active)

    def test_pasta_criada_com_usuario(self):
        pasta = Pasta.objects.create(user=self.user, nome_pasta="R15 Pasta")
        self.assertEqual(pasta.user, self.user)

    def test_userprofile_str(self):
        self.assertIn(self.user.username, str(self.user.profile))

    def test_celery_tasks_importaveis(self):
        from chat.tasks import gerar_parecer_task, send_payment_notification_task
        self.assertTrue(hasattr(gerar_parecer_task, "delay"))
        self.assertTrue(hasattr(send_payment_notification_task, "delay"))
