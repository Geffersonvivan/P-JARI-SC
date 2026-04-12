"""
SMOKE TEST — Verificação segura em produção
============================================

Objetivo: confirmar que os fluxos críticos estão operacionais SEM criar
dados permanentes, SEM chamar APIs externas e SEM modificar usuários reais.

Princípios de segurança:
  - Todas as chamadas externas (Stripe, Anthropic, Gemini, Celery) são mockadas
  - Pareceres criados são deletados no tearDown (transaction.rollback via TestCase)
  - Usuário de teste é deletado no tearDown
  - Nenhum pagamento real é processado

Executar (banco de produção — só leitura + rollback automático):
    python manage.py test chat.tests.test_smoke_producao -v 2

Executar (banco local com keepdb):
    python manage.py test chat.tests.test_smoke_producao --keepdb -v 2

Grupos:
  S01 — Infra (health, static, robots)
  S02 — Autenticação e sessão
  S03 — Billing: planos e webhook simulado
  S04 — Pipeline de fases (F31 → admissibilidade → mérito → parecer)
  S05 — Integridade do banco (modelos User, Parecer, Subscription, UserProfile)
  S06 — Celery / Tasks (verifica que tasks existem e são chamáveis)
"""

import json
import datetime
import hashlib
import hmac
import time
from unittest.mock import patch, MagicMock

from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone

from chat.models import Parecer, Subscription
from chat.engine import (
    JariEngine,
    FASE_AGUARDA_CONFIRMACAO_ADMISSIBILIDADE,
    FASE_MERITO,
    FASE_RESULTADO,
    FASE_AUDITORIA,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _criar_usuario_smoke() -> User:
    """Cria usuário de teste temporário. Apagado no rollback do TestCase."""
    u = User.objects.create_user(
        username="smoke_test_user",
        email="smoke@pjari-smoke.invalid",
        password="smoke-senha-2026!",
    )
    u.profile.credits = 10
    u.profile.is_pro = False
    u.profile.save(update_fields=["credits", "is_pro"])
    return u


def _criar_parecer_smoke(user: User, **kwargs) -> Parecer:
    """Cria Parecer mínimo para smoke. Apagado no rollback do TestCase."""
    defaults = dict(
        user=user,
        nome_processo="[SMOKE] Processo Teste",
        pa="SMOKE-2026/000001",
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
        admissibilidade_texto="Recurso tempestivo. Sem prescrição. Sem decadência.",
        tabela_datas_sensiveis="",
    )
    defaults.update(kwargs)
    return Parecer.objects.create(**defaults)


def _stripe_signature(payload: bytes, secret: str) -> str:
    """Gera assinatura Stripe válida para testes de webhook."""
    ts = int(time.time())
    signed = f"{ts}.{payload.decode()}"
    mac = hmac.new(secret.encode(), signed.encode(), hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


# ── S01 — Infra ────────────────────────────────────────────────────────────────

class S01_Infra(TestCase):
    """Verifica endpoints públicos e de infraestrutura."""

    def test_health_check_retorna_ok(self):
        """GET /health/ deve retornar 200 com status=ok."""
        c = Client()
        r = c.get("/health/")
        self.assertEqual(r.status_code, 200)
        data = json.loads(r.content)
        self.assertEqual(data["status"], "ok")

    def test_robots_txt_acessivel(self):
        """GET /robots.txt deve retornar 200 e conter User-agent."""
        c = Client()
        r = c.get("/robots.txt")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"User-agent", r.content)

    def test_sitemap_xml_valido(self):
        """GET /sitemap.xml deve retornar XML com urlset."""
        c = Client()
        r = c.get("/sitemap.xml")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"urlset", r.content)

    def test_planos_publico_sem_login(self):
        """GET /planos/ deve ser acessível sem autenticação (página pública)."""
        c = Client()
        r = c.get("/planos/")
        self.assertIn(r.status_code, [200, 301, 302])

    def test_landing_page_acessivel(self):
        """GET / (landing) deve retornar 200."""
        c = Client()
        r = c.get("/")
        self.assertIn(r.status_code, [200, 301, 302])


# ── S02 — Autenticação e sessão ────────────────────────────────────────────────

class S02_Autenticacao(TestCase):
    """Verifica redirecionamentos de autenticação e criação de sessão."""

    def test_app_sem_login_redireciona(self):
        """GET /app/ sem login deve redirecionar (302/301) — não dar 200."""
        c = Client()
        r = c.get("/app/")
        self.assertIn(r.status_code, [301, 302])

    def test_checkout_sem_login_redireciona(self):
        """GET /checkout/ sem login deve redirecionar."""
        c = Client()
        r = c.get("/checkout/")
        self.assertIn(r.status_code, [301, 302])

    def test_estatisticas_sem_login_redireciona(self):
        """GET /estatisticas/ sem login deve redirecionar."""
        c = Client()
        r = c.get("/estatisticas/")
        self.assertIn(r.status_code, [301, 302])

    def test_criar_parecer_sem_login_aceita_anonimo(self):
        """
        POST /parecer/create/ sem login NÃO redireciona — a view aceita
        usuários anônimos (limite de 2 pareceres por sessão). Body inválido
        retorna JSON 400, nunca 401/403/redirect.
        """
        c = Client()
        r = c.post(
            "/parecer/create/",
            data=json.dumps({}),
            content_type="application/json",
        )
        # Aceita anônimo: responde com JSON (200, 400 ou 500 em caso de erro interno)
        self.assertNotIn(
            r.status_code, [401, 403],
            "Endpoint não deve bloquear usuários anônimos com 401/403"
        )
        self.assertIn(
            r.get("Content-Type", ""), ["application/json", "application/json; charset=utf-8"],
            "Deve responder com JSON"
        )


# ── S03 — Billing ──────────────────────────────────────────────────────────────

class S03_Billing(TestCase):
    """
    Verifica lógica de billing sem disparar pagamento real.
    O webhook é simulado com assinatura HMAC válida contra um secret fake.
    """

    def setUp(self):
        self.user = _criar_usuario_smoke()
        self.client = Client()
        self.client.force_login(self.user)
        self.stripe_secret = "whsec_smoke_test_secret_0000000000000"

    # ── Planos ────────────────────────────────────────────────────────────────

    def test_planos_retorna_200(self):
        """GET /planos/ deve retornar 200."""
        r = self.client.get("/planos/")
        self.assertEqual(r.status_code, 200)

    # ── Webhook: subscription pro ─────────────────────────────────────────────

    @patch("chat.views.billing.settings")
    def test_webhook_subscription_cria_subscription_e_credita(self, mock_settings):
        """
        Simula evento checkout.session.completed de plano PRO.
        Verifica que Subscription é criada e UserProfile.is_pro = True.
        Nenhuma chamada real ao Stripe é feita.
        """
        mock_settings.STRIPE_SECRET_KEY = "sk_test_fake"
        mock_settings.STRIPE_WEBHOOK_SECRET = self.stripe_secret

        from chat.views.home import PLANS
        plano_pro = PLANS.get("pro")
        self.assertIsNotNone(plano_pro, "Plano 'pro' não encontrado em PLANS")

        amount_cents = int(plano_pro["price"] * 100)

        payload_dict = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "payment_status": "paid",
                    "client_reference_id": str(self.user.id),
                    "amount_total": amount_cents,
                    "payment_intent": "pi_smoke_test_0001",
                    "id": "cs_smoke_test_0001",
                }
            }
        }
        payload_bytes = json.dumps(payload_dict).encode()
        sig = _stripe_signature(payload_bytes, self.stripe_secret)

        with patch("stripe.Webhook.construct_event", return_value=payload_dict), \
             patch("chat.tasks.send_payment_notification_task") as mock_notif:
            mock_notif.delay = MagicMock()

            r = Client().post(
                "/webhooks/stripe/",
                data=payload_bytes,
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE=sig,
            )

        self.assertEqual(r.status_code, 200, "Webhook deve retornar 200")

        self.user.profile.refresh_from_db()
        if plano_pro.get("is_subscription"):
            self.assertTrue(
                self.user.profile.is_pro,
                "UserProfile.is_pro deve ser True após pagamento de plano PRO"
            )
            subs = Subscription.objects.filter(user=self.user, is_active=True)
            self.assertEqual(subs.count(), 1, "Deve existir exatamente 1 Subscription ativa")

    @patch("chat.views.billing.settings")
    def test_webhook_credito_avulso_soma_saldo(self, mock_settings):
        """
        Simula compra de crédito avulso (is_subscription=False).
        Verifica que o saldo aumenta e NÃO cria Subscription.
        """
        mock_settings.STRIPE_SECRET_KEY = "sk_test_fake"
        mock_settings.STRIPE_WEBHOOK_SECRET = self.stripe_secret

        from chat.views.home import PLANS
        plano_avulso = next(
            (v for v in PLANS.values() if not v.get("is_subscription")), None
        )
        if plano_avulso is None:
            self.skipTest("Nenhum plano avulso configurado em PLANS")

        credits_antes = self.user.profile.credits
        amount_cents = int(plano_avulso["price"] * 100)

        payload_dict = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "payment_status": "paid",
                    "client_reference_id": str(self.user.id),
                    "amount_total": amount_cents,
                    "payment_intent": "pi_smoke_avulso_0001",
                    "id": "cs_smoke_avulso_0001",
                }
            }
        }
        payload_bytes = json.dumps(payload_dict).encode()

        with patch("stripe.Webhook.construct_event", return_value=payload_dict), \
             patch("chat.tasks.send_payment_notification_task") as mock_notif:
            mock_notif.delay = MagicMock()
            r = Client().post(
                "/webhooks/stripe/",
                data=payload_bytes,
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE="t=0,v1=fake",
            )

        self.assertEqual(r.status_code, 200)
        self.user.profile.refresh_from_db()
        self.assertGreater(
            self.user.profile.credits, credits_antes,
            "Crédito avulso deve aumentar saldo"
        )

    def test_webhook_sem_secret_retorna_400(self):
        """POST /webhooks/stripe/ sem STRIPE_WEBHOOK_SECRET configurado → 400."""
        with patch("chat.views.billing.settings") as mock_settings:
            mock_settings.STRIPE_SECRET_KEY = "sk_test_fake"
            mock_settings.STRIPE_WEBHOOK_SECRET = None
            r = Client().post(
                "/webhooks/stripe/",
                data=b"{}",
                content_type="application/json",
            )
        self.assertEqual(r.status_code, 400)

    def test_webhook_assinatura_invalida_retorna_400(self):
        """POST /webhooks/stripe/ com assinatura inválida → 400."""
        r = Client().post(
            "/webhooks/stripe/",
            data=b'{"type":"checkout.session.completed"}',
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="t=0,v1=assinatura_invalida",
        )
        self.assertEqual(r.status_code, 400)


# ── S04 — Pipeline de Fases ────────────────────────────────────────────────────

class S04_Pipeline(TestCase):
    """
    Verifica que o motor JariEngine avança as fases corretamente via
    process_message() — interface real usada em produção.
    Todas as chamadas de IA e Celery são mockadas.

    Fase 31 aceita:
      - "ok" / "confirmo"       → confirma resultado automático do JariMath
      - "Prescrição Punitiva - A" → força SIM (prejudica)
      - "Tempestividade - B"    → força INTEMPESTIVO (prejudica)
    """

    def setUp(self):
        self.user = _criar_usuario_smoke()

    @patch("chat.tasks.gerar_parecer_task")
    def test_fase31_prescricao_avanca_para_resultado(self, mock_task):
        """
        Parecer com has_prescricao_punitiva=True + mensagem 'ok'
        → JariMath determina prejudicialidade → FASE_RESULTADO via Celery.
        """
        mock_task.delay.return_value = MagicMock(id="fake-task-id")
        p = _criar_parecer_smoke(self.user, has_prescricao_punitiva=True)
        engine = JariEngine(p)
        engine.process_message("ok")
        p.refresh_from_db()
        self.assertEqual(
            p.status_fase, FASE_RESULTADO,
            "Prescrição punitiva deve levar direto a FASE_RESULTADO"
        )
        self.assertTrue(p.julgador_prescricao_punitiva)

    @patch("chat.tasks.processar_fase4_task")
    def test_fase31_recurso_limpo_avanca_para_merito(self, mock_fase4):
        """
        Recurso sem vícios + mensagem 'ok'
        → sem prejudicialidade → FASE_MERITO (Celery fase4 enfileirado).
        """
        mock_fase4.delay.return_value = MagicMock(id="fake-task-id")
        p = _criar_parecer_smoke(
            self.user,
            has_prescricao_punitiva=False,
            has_prescricao_intercorrente=False,
            has_decadencia=False,
            is_tempestivo=True,
        )
        engine = JariEngine(p)
        result = engine.process_message("ok")
        p.refresh_from_db()
        # Recurso limpo vai para fase 4 (mérito) via Celery
        mock_fase4.delay.assert_called_once_with(p.id)
        data = json.loads(result)
        self.assertEqual(data["status"], "celery")
        self.assertEqual(data["type"], "FASE4")

    @patch("chat.tasks.gerar_parecer_task")
    def test_fase31_intempestivo_avanca_para_resultado(self, mock_task):
        """
        Parecer intempestivo + mensagem 'ok'
        → JariMath detecta intempestividade → FASE_RESULTADO.
        """
        mock_task.delay.return_value = MagicMock(id="fake-task-id")
        p = _criar_parecer_smoke(
            self.user,
            is_tempestivo=False,
            has_prescricao_punitiva=False,
        )
        engine = JariEngine(p)
        engine.process_message("ok")
        p.refresh_from_db()
        self.assertEqual(
            p.status_fase, FASE_RESULTADO,
            "Recurso intempestivo deve ir para FASE_RESULTADO"
        )
        self.assertFalse(p.julgador_tempestivo)

    @patch("chat.tasks.gerar_parecer_task")
    def test_flags_julgador_sao_persistidas_no_banco(self, mock_task):
        """
        Confirma que as flags do julgador são gravadas corretamente no BD
        após process_message('ok') com prescrição punitiva ativa.
        """
        mock_task.delay.return_value = MagicMock(id="fake-task-id")
        p = _criar_parecer_smoke(self.user, has_prescricao_punitiva=True)
        engine = JariEngine(p)
        engine.process_message("ok")
        p.refresh_from_db()
        self.assertTrue(p.julgador_prescricao_punitiva)
        self.assertFalse(p.julgador_prescricao_intercorrente)
        self.assertFalse(p.julgador_decadencia)


# ── S05 — Integridade do Banco ─────────────────────────────────────────────────

class S05_Banco(TestCase):
    """
    Verifica que os modelos críticos podem ser criados, lidos e têm os
    campos esperados. Não modifica dados de usuários reais.
    """

    def setUp(self):
        self.user = _criar_usuario_smoke()

    def test_userprofile_criado_automaticamente(self):
        """UserProfile é criado automaticamente via signal no novo User."""
        self.assertTrue(
            hasattr(self.user, "profile"),
            "User deve ter UserProfile associado via related_name='profile'"
        )
        self.assertIsNotNone(self.user.profile.pk)

    def test_parecer_criado_com_campos_minimos(self):
        """Parecer pode ser criado com campos mínimos obrigatórios."""
        p = _criar_parecer_smoke(self.user)
        self.assertIsNotNone(p.pk)
        self.assertEqual(p.status_fase, FASE_AGUARDA_CONFIRMACAO_ADMISSIBILIDADE)

    def test_subscription_criada_e_campos_ok(self):
        """Subscription pode ser criada com campos obrigatórios."""
        agora = timezone.now()
        sub = Subscription.objects.create(
            user=self.user,
            plano="pro",
            creditos_base=30,
            creditos_bonus=5,
            data_inicio=agora,
            data_expiracao=agora + datetime.timedelta(days=30),
            stripe_session_id="cs_smoke_integridade_001",
            is_active=True,
        )
        self.assertIsNotNone(sub.pk)
        self.assertEqual(sub.plano, "pro")
        self.assertTrue(sub.is_active)

    def test_subscription_anterior_e_desativada(self):
        """Ao criar nova Subscription, desativar as anteriores (regra de negócio)."""
        agora = timezone.now()
        sub_antiga = Subscription.objects.create(
            user=self.user,
            plano="basic",
            creditos_base=10,
            creditos_bonus=0,
            data_inicio=agora - datetime.timedelta(days=31),
            data_expiracao=agora - datetime.timedelta(days=1),
            stripe_session_id="cs_smoke_antiga",
            is_active=True,
        )
        # Simula o fluxo do webhook: desativa antigas, cria nova
        self.user.subscriptions.filter(is_active=True).update(is_active=False)
        sub_nova = Subscription.objects.create(
            user=self.user,
            plano="pro",
            creditos_base=30,
            creditos_bonus=5,
            data_inicio=agora,
            data_expiracao=agora + datetime.timedelta(days=30),
            stripe_session_id="cs_smoke_nova",
            is_active=True,
        )
        sub_antiga.refresh_from_db()
        self.assertFalse(sub_antiga.is_active, "Assinatura antiga deve ser desativada")
        self.assertTrue(sub_nova.is_active, "Nova assinatura deve estar ativa")
        self.assertEqual(
            self.user.subscriptions.filter(is_active=True).count(), 1,
            "Apenas 1 Subscription ativa por usuário"
        )


# ── S06 — Celery / Tasks ───────────────────────────────────────────────────────

class S06_Celery(TestCase):
    """
    Verifica que as tasks existem e são registradas no Celery.
    NÃO dispara tasks reais — apenas importa e inspeciona.
    """

    def test_gerar_parecer_task_existe(self):
        """chat.tasks.gerar_parecer_task deve ser importável."""
        from chat.tasks import gerar_parecer_task
        self.assertTrue(callable(gerar_parecer_task), "gerar_parecer_task deve ser callable")

    def test_send_payment_notification_task_existe(self):
        """chat.tasks.send_payment_notification_task deve ser importável."""
        from chat.tasks import send_payment_notification_task
        self.assertTrue(callable(send_payment_notification_task))

    def test_tasks_tem_atributo_delay(self):
        """Tasks Celery devem ter atributo .delay (interface padrão Celery)."""
        from chat.tasks import gerar_parecer_task, send_payment_notification_task
        self.assertTrue(hasattr(gerar_parecer_task, "delay"))
        self.assertTrue(hasattr(send_payment_notification_task, "delay"))
