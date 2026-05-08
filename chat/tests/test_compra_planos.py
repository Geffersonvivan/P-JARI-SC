"""
TESTE DE COMPRA DOS 3 PLANOS — Simulação completa sem pagamento real
=====================================================================

Simula o fluxo integral de compra dos 3 planos disponíveis:

  Plano EXTRA      → R$  20,00 | 1 crédito avulso    | não é assinatura
  Plano BÁSICO     → R$ 540,00 | 40 créditos/mês     | assinatura mensal
  Plano PRO        → R$ 720,00 | 80 créditos/mês     | assinatura mensal

Cada cenário percorre o fluxo completo:
  1. Usuário acessa /checkout/?plan=<plano>  (mock Stripe Session criada)
  2. Stripe dispara checkout.session.completed com assinatura HMAC válida
  3. Webhook processa: cria Subscription (se assinatura) ou adiciona crédito
  4. Verifica estado final do UserProfile e Subscription no banco
  5. Verifica envio do e-mail de confirmação via Celery

Garantias de segurança:
  - stripe.checkout.Session.create é mockado → nenhuma chamada real à API Stripe
  - stripe.Webhook.construct_event é mockado → nenhum secret real necessário
  - Todos os dados são revertidos (rollback automático do TestCase por classe)
  - Nenhum e-mail real é enviado (task Celery mockada)

Executar:
    python manage.py test chat.tests.test_compra_planos --keepdb -v 2
"""

import json
import datetime
import hashlib
import hmac
import time
from unittest.mock import patch, MagicMock, call

from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone

from chat.models import Subscription
from chat.views.home import PLANS


# ── Helpers ────────────────────────────────────────────────────────────────────

_STRIPE_SECRET_FAKE   = "sk_test_smoke_fake_key"
_WEBHOOK_SECRET_FAKE  = "whsec_smoke_fake_webhook_secret"


def _criar_usuario(username: str) -> User:
    u = User.objects.create_user(
        username=username,
        email=f"{username}@pjari-smoke.invalid",
        password="smoke-senha-2026!",
    )
    u.profile.credits = 0
    u.profile.is_pro = False
    u.profile.subscription_status = ""
    u.profile.save(update_fields=["credits", "is_pro", "subscription_status"])
    return u


def _stripe_sig(payload: bytes, secret: str) -> str:
    """Gera assinatura Stripe válida (mesmo algoritmo do SDK oficial)."""
    ts = int(time.time())
    signed = f"{ts}.{payload.decode()}"
    mac = hmac.new(secret.encode(), signed.encode(), hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


def _payload_checkout_completed(user_id: int, plano_key: str) -> dict:
    """Monta evento checkout.session.completed idêntico ao enviado pelo Stripe."""
    plan = PLANS[plano_key]
    amount_cents = int(plan["price"] * 100)
    return {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "payment_status": "paid",
                "client_reference_id": str(user_id),
                "amount_total": amount_cents,
                "payment_intent": f"pi_smoke_{plano_key}_001",
                "id": f"cs_smoke_{plano_key}_001",
            }
        }
    }


def _disparar_webhook(payload_dict: dict) -> "HttpResponse":
    """Dispara o webhook simulado com assinatura HMAC válida."""
    payload_bytes = json.dumps(payload_dict).encode()
    sig = _stripe_sig(payload_bytes, _WEBHOOK_SECRET_FAKE)

    with patch("stripe.Webhook.construct_event", return_value=payload_dict):
        with patch("chat.tasks.send_payment_notification_task") as mock_email:
            mock_email.delay = MagicMock()
            response = Client().post(
                "/webhooks/stripe/",
                data=payload_bytes,
                content_type="application/json",
                HTTP_STRIPE_SIGNATURE=sig,
            )
            return response, mock_email


# ── Cenário base (mixin compartilhado) ────────────────────────────────────────

class _BaseCompra(TestCase):
    """
    Classe base com helpers de asserção comuns a todos os cenários de compra.
    Cada subclasse define plano_key e o usuário de teste.
    """

    plano_key: str = ""

    def setUp(self):
        self.plan = PLANS[self.plano_key]
        self.user = _criar_usuario(f"smoke_{self.plano_key}")
        self.client = Client()
        self.client.force_login(self.user)

    # ── Etapa 1: checkout ──────────────────────────────────────────────────────

    def _testar_checkout_redireciona_para_stripe(self):
        """
        GET /checkout/?plan=<plano> deve criar Stripe Session e redirecionar.

        O middleware ClerkAuthenticationMiddleware força AnonymousUser quando
        não há cookie '__session' (token JWT Clerk). Por isso usamos RequestFactory
        diretamente na view, injetando o usuário autenticado sem passar pelo middleware.
        """
        from django.test import RequestFactory
        from chat.views.billing import checkout_view

        fake_url = f"https://checkout.stripe.com/pay/smoke_{self.plano_key}"
        mock_session = MagicMock()
        mock_session.url = fake_url

        factory = RequestFactory()
        request = factory.get(f"/checkout/?plan={self.plano_key}")
        request.user = self.user  # injeta usuário autenticado diretamente

        with patch("stripe.checkout.Session.create", return_value=mock_session) as mock_create, \
             patch("chat.views.billing.settings") as mock_settings:
            mock_settings.STRIPE_SECRET_KEY = _STRIPE_SECRET_FAKE
            mock_settings.STRIPE_WEBHOOK_SECRET = _WEBHOOK_SECRET_FAKE

            # Bypassa @ratelimit (que depende de cache Redis em produção)
            with patch("chat.views.billing.ratelimit", lambda *a, **kw: lambda f: f):
                r = checkout_view(request)

        # Deve redirecionar para a URL do Stripe
        self.assertIn(r.status_code, [301, 302],
            f"[{self.plano_key}] checkout deve redirecionar para Stripe")
        self.assertIn(fake_url, r.get("Location", ""),
            f"[{self.plano_key}] destino deve ser a URL de checkout Stripe")

        # Verifica que Session.create foi chamado com os dados corretos
        call_kwargs = mock_create.call_args[1]
        self.assertEqual(call_kwargs["client_reference_id"], str(self.user.id))
        line_item = call_kwargs["line_items"][0]
        self.assertEqual(
            line_item["price_data"]["unit_amount"],
            int(self.plan["price"] * 100),
            f"[{self.plano_key}] valor em centavos deve ser {int(self.plan['price'] * 100)}"
        )

    # ── Etapa 2 + 3: webhook processa pagamento ────────────────────────────────

    def _testar_webhook_retorna_200(self):
        """Webhook simulado deve retornar 200."""
        payload = _payload_checkout_completed(self.user.id, self.plano_key)
        with patch("chat.views.billing.settings") as mock_settings:
            mock_settings.STRIPE_SECRET_KEY = _STRIPE_SECRET_FAKE
            mock_settings.STRIPE_WEBHOOK_SECRET = _WEBHOOK_SECRET_FAKE
            response, _ = _disparar_webhook(payload)

        self.assertEqual(response.status_code, 200,
            f"[{self.plano_key}] webhook deve retornar 200")

    # ── Etapa 4: estado final do banco ─────────────────────────────────────────

    def _testar_creditos_atualizados(self, esperado: int):
        """UserProfile.credits deve ser exatamente o esperado após pagamento."""
        self.user.profile.refresh_from_db()
        self.assertEqual(
            self.user.profile.credits, esperado,
            f"[{self.plano_key}] créditos esperados={esperado}, obtidos={self.user.profile.credits}"
        )

    def _testar_is_pro(self, esperado: bool):
        """UserProfile.is_pro deve refletir o plano pago."""
        self.user.profile.refresh_from_db()
        self.assertEqual(
            self.user.profile.is_pro, esperado,
            f"[{self.plano_key}] is_pro esperado={esperado}"
        )

    def _testar_subscription_ativa(self, deve_existir: bool):
        """Subscription ativa deve existir (ou não) de acordo com o tipo de plano."""
        count = Subscription.objects.filter(user=self.user, is_active=True).count()
        if deve_existir:
            self.assertEqual(count, 1,
                f"[{self.plano_key}] deve haver exatamente 1 Subscription ativa")
            sub = Subscription.objects.get(user=self.user, is_active=True)
            self.assertEqual(sub.plano, self.plano_key)
            self.assertGreater(sub.data_expiracao, timezone.now(),
                "Subscription deve expirar no futuro (30 dias)")
            self.assertEqual(sub.creditos_base, self.plan["credits_base"])
            self.assertEqual(sub.creditos_bonus, self.plan["credits_bonus"])
        else:
            self.assertEqual(count, 0,
                f"[{self.plano_key}] plano avulso não deve criar Subscription")

    # ── Etapa 5: e-mail de confirmação ─────────────────────────────────────────

    def _testar_email_confirmacao_disparado(self):
        """send_payment_notification_task.delay deve ser chamado após pagamento."""
        payload = _payload_checkout_completed(self.user.id, self.plano_key)
        with patch("chat.views.billing.settings") as mock_settings:
            mock_settings.STRIPE_SECRET_KEY = _STRIPE_SECRET_FAKE
            mock_settings.STRIPE_WEBHOOK_SECRET = _WEBHOOK_SECRET_FAKE
            _, mock_email = _disparar_webhook(payload)

        mock_email.delay.assert_called_once()
        args = mock_email.delay.call_args[0]
        # args = (nome_cliente, email_cliente, valor, payment_id)
        self.assertAlmostEqual(args[2], self.plan["price"], places=2,
            msg=f"[{self.plano_key}] valor no e-mail deve ser R${self.plan['price']:.2f}")


# ══════════════════════════════════════════════════════════════════════════════
# PLANO EXTRA — R$20,00 / 1 crédito avulso / não é assinatura
# ══════════════════════════════════════════════════════════════════════════════

class TestCompraPlanoExtra(_BaseCompra):
    """
    Plano EXTRA (R$20,00): crédito avulso, sem assinatura mensal.
    Saldo atual deve ser SOMADO, não substituído.
    """

    plano_key = "extra"

    def _processar_pagamento(self):
        """Dispara o webhook e aplica as configurações de settings mock."""
        payload = _payload_checkout_completed(self.user.id, self.plano_key)
        with patch("chat.views.billing.settings") as mock_settings:
            mock_settings.STRIPE_SECRET_KEY = _STRIPE_SECRET_FAKE
            mock_settings.STRIPE_WEBHOOK_SECRET = _WEBHOOK_SECRET_FAKE
            _disparar_webhook(payload)

    def test_01_checkout_redireciona_stripe(self):
        """GET /checkout/?plan=extra → redireciona para URL Stripe mockada."""
        self._testar_checkout_redireciona_para_stripe()

    def test_02_webhook_retorna_200(self):
        """Webhook checkout.session.completed retorna 200."""
        self._processar_pagamento()
        self._testar_webhook_retorna_200()

    def test_03_credito_somado_ao_saldo(self):
        """
        Crédito avulso (R$20) SOMA ao saldo existente — não substitui.
        Saldo inicial = 0 → após compra = 1.
        """
        self._processar_pagamento()
        self._testar_creditos_atualizados(esperado=1)

    def test_04_is_pro_nao_muda(self):
        """Crédito avulso NÃO altera is_pro (permanece False)."""
        self._processar_pagamento()
        self._testar_is_pro(esperado=False)

    def test_05_nao_cria_subscription(self):
        """Plano avulso NÃO deve criar Subscription no banco."""
        self._processar_pagamento()
        self._testar_subscription_ativa(deve_existir=False)

    def test_06_email_confirmacao_disparado(self):
        """E-mail de confirmação é disparado via Celery com valor R$20,00."""
        self._testar_email_confirmacao_disparado()

    def test_07_compra_dupla_acumula_creditos(self):
        """
        Duas compras avulsas acumulam: saldo 0 → compra 1 → 1 → compra 2 → 2.
        Confirma que NÃO há reset de saldo para planos avulsos.
        """
        payload = _payload_checkout_completed(self.user.id, self.plano_key)
        with patch("chat.views.billing.settings") as mock_settings:
            mock_settings.STRIPE_SECRET_KEY = _STRIPE_SECRET_FAKE
            mock_settings.STRIPE_WEBHOOK_SECRET = _WEBHOOK_SECRET_FAKE
            _disparar_webhook(payload)
            _disparar_webhook(payload)

        self.user.profile.refresh_from_db()
        self.assertEqual(
            self.user.profile.credits, 2,
            "Duas compras avulsas devem resultar em 2 créditos (acumulação)"
        )


# ══════════════════════════════════════════════════════════════════════════════
# PLANO BÁSICO — R$540,00 / 40 créditos / assinatura mensal
# ══════════════════════════════════════════════════════════════════════════════

class TestCompraPlanoBasico(_BaseCompra):
    """
    Plano BÁSICO (R$540,00): 40 créditos, assinatura mensal.
    Saldo deve ser SUBSTITUÍDO (reset), não somado.
    """

    plano_key = "basic"

    def _processar_pagamento(self):
        payload = _payload_checkout_completed(self.user.id, self.plano_key)
        with patch("chat.views.billing.settings") as mock_settings:
            mock_settings.STRIPE_SECRET_KEY = _STRIPE_SECRET_FAKE
            mock_settings.STRIPE_WEBHOOK_SECRET = _WEBHOOK_SECRET_FAKE
            _disparar_webhook(payload)

    def test_01_checkout_redireciona_stripe(self):
        """GET /checkout/?plan=basic → redireciona para URL Stripe mockada."""
        self._testar_checkout_redireciona_para_stripe()

    def test_02_webhook_retorna_200(self):
        """Webhook checkout.session.completed retorna 200."""
        self._processar_pagamento()
        self._testar_webhook_retorna_200()

    def test_03_creditos_resetados_para_40(self):
        """
        Assinatura básica reseta saldo para 40 créditos (credits_base=36 + credits_bonus=4).
        Saldo inicial = 0 → após compra = 40.
        """
        self._processar_pagamento()
        self._testar_creditos_atualizados(esperado=PLANS["basic"]["credits"])

    def test_04_is_pro_true(self):
        """Plano básico marca is_pro=True no UserProfile."""
        self._processar_pagamento()
        self._testar_is_pro(esperado=True)

    def test_05_subscription_criada_e_ativa(self):
        """
        Subscription básica criada com:
          - plano='basic', creditos_base=36, creditos_bonus=4
          - is_active=True, expira em ~30 dias
        """
        self._processar_pagamento()
        self._testar_subscription_ativa(deve_existir=True)

    def test_06_subscription_status_active(self):
        """UserProfile.subscription_status deve ser 'active'."""
        self._processar_pagamento()
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.subscription_status, "active")

    def test_07_email_confirmacao_disparado(self):
        """E-mail de confirmação é disparado com valor R$540,00."""
        self._testar_email_confirmacao_disparado()

    def test_08_renovacao_reseta_saldo_sem_acumular(self):
        """
        Segunda compra básica desativa assinatura anterior e cria nova.
        Saldo deve ser RESETADO para 40 (não somado para 80).
        """
        payload = _payload_checkout_completed(self.user.id, self.plano_key)
        with patch("chat.views.billing.settings") as mock_settings:
            mock_settings.STRIPE_SECRET_KEY = _STRIPE_SECRET_FAKE
            mock_settings.STRIPE_WEBHOOK_SECRET = _WEBHOOK_SECRET_FAKE
            _disparar_webhook(payload)  # 1ª compra → 40 créditos
            _disparar_webhook(payload)  # 2ª compra → deve resetar para 40, não 80

        self.user.profile.refresh_from_db()
        self.assertEqual(
            self.user.profile.credits, PLANS["basic"]["credits"],
            "Renovação de assinatura deve resetar para 40, não acumular"
        )
        # Apenas 1 assinatura ativa
        count_ativas = Subscription.objects.filter(user=self.user, is_active=True).count()
        self.assertEqual(count_ativas, 1, "Deve haver apenas 1 Subscription ativa após renovação")

    def test_09_subscription_anterior_desativada_na_renovacao(self):
        """
        Ao renovar, a Subscription anterior deve ser marcada is_active=False.
        """
        payload = _payload_checkout_completed(self.user.id, self.plano_key)
        with patch("chat.views.billing.settings") as mock_settings:
            mock_settings.STRIPE_SECRET_KEY = _STRIPE_SECRET_FAKE
            mock_settings.STRIPE_WEBHOOK_SECRET = _WEBHOOK_SECRET_FAKE
            _disparar_webhook(payload)
            sub_inicial = Subscription.objects.filter(user=self.user).order_by("id").first()
            _disparar_webhook(payload)

        sub_inicial.refresh_from_db()
        self.assertFalse(sub_inicial.is_active,
            "Assinatura anterior deve ser desativada ao renovar")


# ══════════════════════════════════════════════════════════════════════════════
# PLANO PRO — R$720,00 / 80 créditos / assinatura mensal
# ══════════════════════════════════════════════════════════════════════════════

class TestCompraplanoPro(_BaseCompra):
    """
    Plano PRO (R$720,00): 80 créditos, assinatura mensal.
    Saldo deve ser SUBSTITUÍDO (reset), não somado.
    """

    plano_key = "pro"

    def _processar_pagamento(self):
        payload = _payload_checkout_completed(self.user.id, self.plano_key)
        with patch("chat.views.billing.settings") as mock_settings:
            mock_settings.STRIPE_SECRET_KEY = _STRIPE_SECRET_FAKE
            mock_settings.STRIPE_WEBHOOK_SECRET = _WEBHOOK_SECRET_FAKE
            _disparar_webhook(payload)

    def test_01_checkout_redireciona_stripe(self):
        """GET /checkout/?plan=pro → redireciona para URL Stripe mockada."""
        self._testar_checkout_redireciona_para_stripe()

    def test_02_webhook_retorna_200(self):
        """Webhook checkout.session.completed retorna 200."""
        self._processar_pagamento()
        self._testar_webhook_retorna_200()

    def test_03_creditos_resetados_para_80(self):
        """
        Assinatura PRO reseta saldo para 80 créditos (credits_base=72 + credits_bonus=8).
        Saldo inicial = 0 → após compra = 80.
        """
        self._processar_pagamento()
        self._testar_creditos_atualizados(esperado=PLANS["pro"]["credits"])

    def test_04_is_pro_true(self):
        """Plano PRO marca is_pro=True no UserProfile."""
        self._processar_pagamento()
        self._testar_is_pro(esperado=True)

    def test_05_subscription_criada_e_ativa(self):
        """
        Subscription PRO criada com:
          - plano='pro', creditos_base=72, creditos_bonus=8
          - is_active=True, expira em ~30 dias
        """
        self._processar_pagamento()
        self._testar_subscription_ativa(deve_existir=True)

    def test_06_subscription_status_active(self):
        """UserProfile.subscription_status deve ser 'active'."""
        self._processar_pagamento()
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.subscription_status, "active")

    def test_07_subscription_expires_at_preenchido(self):
        """
        subscription_expires_at deve ser ~30 dias no futuro após compra PRO.
        """
        self._processar_pagamento()
        self.user.profile.refresh_from_db()
        self.assertIsNotNone(self.user.profile.subscription_expires_at,
            "subscription_expires_at deve ser preenchido ao comprar PRO")
        self.assertGreater(
            self.user.profile.subscription_expires_at,
            timezone.now(),
            "subscription_expires_at deve estar no futuro"
        )

    def test_08_email_confirmacao_disparado(self):
        """E-mail de confirmação é disparado com valor R$720,00."""
        self._testar_email_confirmacao_disparado()

    def test_09_renovacao_reseta_saldo_sem_acumular(self):
        """
        Renovação PRO não acumula: saldo permanece 80 (não vai para 160).
        """
        payload = _payload_checkout_completed(self.user.id, self.plano_key)
        with patch("chat.views.billing.settings") as mock_settings:
            mock_settings.STRIPE_SECRET_KEY = _STRIPE_SECRET_FAKE
            mock_settings.STRIPE_WEBHOOK_SECRET = _WEBHOOK_SECRET_FAKE
            _disparar_webhook(payload)
            _disparar_webhook(payload)

        self.user.profile.refresh_from_db()
        self.assertEqual(
            self.user.profile.credits, PLANS["pro"]["credits"],
            "Renovação PRO deve manter 80 créditos, não acumular"
        )
        count_ativas = Subscription.objects.filter(user=self.user, is_active=True).count()
        self.assertEqual(count_ativas, 1)

    def test_10_subscription_anterior_desativada_na_renovacao(self):
        """Assinatura PRO anterior é desativada ao renovar."""
        payload = _payload_checkout_completed(self.user.id, self.plano_key)
        with patch("chat.views.billing.settings") as mock_settings:
            mock_settings.STRIPE_SECRET_KEY = _STRIPE_SECRET_FAKE
            mock_settings.STRIPE_WEBHOOK_SECRET = _WEBHOOK_SECRET_FAKE
            _disparar_webhook(payload)
            sub_inicial = Subscription.objects.filter(user=self.user).order_by("id").first()
            _disparar_webhook(payload)

        sub_inicial.refresh_from_db()
        self.assertFalse(sub_inicial.is_active)


# ══════════════════════════════════════════════════════════════════════════════
# CENÁRIO CRUZADO — Upgrade BÁSICO → PRO
# ══════════════════════════════════════════════════════════════════════════════

class TestUpgradeBasicoParaPro(TestCase):
    """
    Cenário real: usuário tem assinatura BÁSICA ativa e faz upgrade para PRO.
    Verifica que:
      - Assinatura BÁSICA é desativada
      - Nova assinatura PRO é criada
      - Saldo é resetado para 80 (não 40+80=120)
      - is_pro permanece True
    """

    def setUp(self):
        self.user = _criar_usuario("smoke_upgrade")

    def _comprar(self, plano_key: str):
        payload = _payload_checkout_completed(self.user.id, plano_key)
        with patch("chat.views.billing.settings") as mock_settings:
            mock_settings.STRIPE_SECRET_KEY = _STRIPE_SECRET_FAKE
            mock_settings.STRIPE_WEBHOOK_SECRET = _WEBHOOK_SECRET_FAKE
            _disparar_webhook(payload)

    def test_upgrade_basico_para_pro(self):
        """Upgrade BÁSICO → PRO: desativa basic, ativa pro, saldo = 80."""
        self._comprar("basic")

        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.credits, 40, "Após BÁSICO: 40 créditos")
        self.assertTrue(
            Subscription.objects.filter(user=self.user, plano="basic", is_active=True).exists()
        )

        self._comprar("pro")

        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.credits, 80, "Após upgrade PRO: 80 créditos (reset)")
        self.assertTrue(self.user.profile.is_pro)

        # Básica deve estar inativa
        self.assertFalse(
            Subscription.objects.filter(user=self.user, plano="basic", is_active=True).exists(),
            "Assinatura BÁSICA deve ser desativada após upgrade para PRO"
        )
        # PRO ativa
        self.assertTrue(
            Subscription.objects.filter(user=self.user, plano="pro", is_active=True).exists(),
            "Assinatura PRO deve estar ativa"
        )
        # Total de assinaturas ativas = 1
        self.assertEqual(
            Subscription.objects.filter(user=self.user, is_active=True).count(), 1
        )


# ══════════════════════════════════════════════════════════════════════════════
# CRÉDITOS — Consumo (Fase 7) e Bloqueio (handle_iniciar)
# ══════════════════════════════════════════════════════════════════════════════

class TestCreditosConsumoEBloqueio(TestCase):
    """
    Testes de ponta a ponta do ciclo de créditos:
      1. Fase 7 desconta 1 crédito ao salvar processo
      2. handle_iniciar bloqueia usuário com 0 créditos
      3. Após compra de crédito avulso, handle_iniciar libera normalmente
      4. Usuário PRO nunca é bloqueado nem tem créditos descontados
    """

    def setUp(self):
        self.user = _criar_usuario("smoke_creditos")
        self.client = Client()
        self.client.force_login(self.user)

    # ── Fase 7: desconto de crédito ────────────────────────────────────────────

    def test_01_fase7_desconta_credito(self):
        """Salvar processo na Fase 7 desconta 1 crédito do UserProfile."""
        self.user.profile.credits = 3
        self.user.profile.is_pro = False
        self.user.profile.save(update_fields=["credits", "is_pro"])

        from chat.models import Pasta, Parecer
        from chat.engine import phase_7

        pasta = Pasta.objects.create(user=self.user, nome_pasta="Pasta Teste")
        parecer = Parecer.objects.create(user=self.user, nome_processo="Teste", is_saved=False)

        engine_mock = type("Engine", (), {"parecer": parecer})()
        phase_7.process(engine_mock, pasta.nome_pasta)

        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.credits, 2,
            "Fase 7 deve descontar 1 crédito: 3 → 2")

    def test_02_fase7_nao_desconta_abaixo_de_zero(self):
        """Fase 7 não desconta crédito se saldo já é 0."""
        self.user.profile.credits = 0
        self.user.profile.is_pro = False
        self.user.profile.save(update_fields=["credits", "is_pro"])

        from chat.models import Pasta, Parecer
        from chat.engine import phase_7

        pasta = Pasta.objects.create(user=self.user, nome_pasta="Pasta Zero")
        parecer = Parecer.objects.create(user=self.user, nome_processo="Teste Zero", is_saved=False)

        engine_mock = type("Engine", (), {"parecer": parecer})()
        phase_7.process(engine_mock, pasta.nome_pasta)

        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.credits, 0,
            "Fase 7 não deve levar créditos a negativo")

    def test_03_fase7_pro_nao_desconta(self):
        """Usuário PRO não tem créditos descontados na Fase 7."""
        self.user.profile.credits = 10
        self.user.profile.is_pro = True
        self.user.profile.save(update_fields=["credits", "is_pro"])

        from chat.models import Pasta, Parecer
        from chat.engine import phase_7

        pasta = Pasta.objects.create(user=self.user, nome_pasta="Pasta PRO")
        parecer = Parecer.objects.create(user=self.user, nome_processo="Teste PRO", is_saved=False)

        engine_mock = type("Engine", (), {"parecer": parecer})()
        phase_7.process(engine_mock, pasta.nome_pasta)

        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.credits, 10,
            "Usuário PRO não deve ter créditos descontados")

    # ── handle_iniciar: bloqueio ───────────────────────────────────────────────

    def test_04_iniciar_bloqueado_sem_creditos(self):
        """handle_iniciar retorna sem_creditos=True quando credits=0 e não é PRO."""
        self.user.profile.credits = 0
        self.user.profile.is_pro = False
        self.user.profile.save(update_fields=["credits", "is_pro"])

        from django.test import RequestFactory
        from chat.services import ChatService

        factory = RequestFactory()
        request = factory.post("/chat/message/",
            data='{"message": "iniciar"}',
            content_type="application/json")
        request.user = self.user
        request.session = self.client.session

        response = ChatService.handle_iniciar(request, {"user": self.user})
        data = json.loads(response.content)

        self.assertTrue(data.get("sem_creditos"),
            "Deve retornar sem_creditos=True quando credits=0")
        self.assertEqual(data.get("redirect"), "/planos/",
            "Deve redirecionar para /planos/")

    def test_05_iniciar_liberado_com_creditos(self):
        """handle_iniciar cria parecer normalmente quando credits > 0."""
        self.user.profile.credits = 2
        self.user.profile.is_pro = False
        self.user.profile.save(update_fields=["credits", "is_pro"])

        from django.test import RequestFactory
        from chat.services import ChatService
        from chat.models import Pasta

        Pasta.objects.create(user=self.user, nome_pasta="Minha Pasta")

        factory = RequestFactory()
        request = factory.post("/chat/message/",
            data='{"message": "iniciar"}',
            content_type="application/json")
        request.user = self.user
        request.session = self.client.session

        response = ChatService.handle_iniciar(request, {"user": self.user})
        data = json.loads(response.content)

        self.assertFalse(data.get("sem_creditos"),
            "Não deve bloquear quando credits > 0")
        self.assertIn("active_parecer_id", data,
            "Deve retornar active_parecer_id ao iniciar normalmente")

    def test_06_pro_nunca_bloqueado(self):
        """Usuário PRO com credits=0 não é bloqueado no handle_iniciar."""
        self.user.profile.credits = 0
        self.user.profile.is_pro = True
        self.user.profile.save(update_fields=["credits", "is_pro"])

        from django.test import RequestFactory
        from chat.services import ChatService
        from chat.models import Pasta

        Pasta.objects.create(user=self.user, nome_pasta="Pasta PRO")

        factory = RequestFactory()
        request = factory.post("/chat/message/",
            data='{"message": "iniciar"}',
            content_type="application/json")
        request.user = self.user
        request.session = self.client.session

        response = ChatService.handle_iniciar(request, {"user": self.user})
        data = json.loads(response.content)

        self.assertFalse(data.get("sem_creditos"),
            "PRO com credits=0 não deve ser bloqueado")

    # ── Ponta a ponta: zero → compra → iniciar ────────────────────────────────

    def test_07_ponta_a_ponta_zero_compra_credito_iniciar(self):
        """
        Jornada completa:
          1. Usuário com 0 créditos tenta iniciar → bloqueado
          2. Compra plano EXTRA via webhook → recebe 1 crédito
          3. Tenta iniciar novamente → liberado, parecer criado
        """
        from django.test import RequestFactory
        from chat.services import ChatService
        from chat.models import Pasta

        Pasta.objects.create(user=self.user, nome_pasta="Pasta E2E")

        factory = RequestFactory()

        def _fazer_iniciar():
            request = factory.post("/chat/message/",
                data='{"message": "iniciar"}',
                content_type="application/json")
            request.user = self.user
            request.session = self.client.session
            return ChatService.handle_iniciar(request, {"user": self.user})

        # Passo 1: 0 créditos → bloqueado
        r1 = json.loads(_fazer_iniciar().content)
        self.assertTrue(r1.get("sem_creditos"), "Passo 1: deve bloquear com 0 créditos")

        # Passo 2: compra plano EXTRA → +1 crédito
        payload = _payload_checkout_completed(self.user.id, "extra")
        with patch("chat.views.billing.settings") as mock_settings:
            mock_settings.STRIPE_SECRET_KEY = _STRIPE_SECRET_FAKE
            mock_settings.STRIPE_WEBHOOK_SECRET = _WEBHOOK_SECRET_FAKE
            _disparar_webhook(payload)

        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.credits, 1, "Passo 2: deve ter 1 crédito após compra")

        # Passo 3: agora consegue iniciar
        r3 = json.loads(_fazer_iniciar().content)
        self.assertFalse(r3.get("sem_creditos"), "Passo 3: não deve bloquear após compra")
        self.assertIn("active_parecer_id", r3, "Passo 3: deve criar parecer")
