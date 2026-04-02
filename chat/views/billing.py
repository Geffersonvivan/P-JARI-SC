import logging
from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.contrib.auth.models import User
import stripe
from django_ratelimit.decorators import ratelimit
from ..models import Parecer
from .home import PLANS

logger = logging.getLogger(__name__)


@ratelimit(key='user', rate='10/h', method='GET', block=True)
@login_required
def checkout_view(request):
    try:
        stripe.api_key = settings.STRIPE_SECRET_KEY

        plan_type = request.GET.get('plan', 'pro')
        plan = PLANS.get(plan_type, PLANS['pro'])

        payer_email = request.user.email or f"user_{request.user.id}@pjari.com.br"

        session = stripe.checkout.Session.create(
            payment_method_types=['card', 'pix'],
            customer_email=payer_email,
            client_reference_id=str(request.user.id),
            line_items=[{
                'price_data': {
                    'currency': 'brl',
                    'product_data': {
                        'name': plan['title'],
                        'description': 'Créditos de sistema',
                    },
                    'unit_amount': int(plan['price'] * 100),
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=request.build_absolute_uri("/planos/?success=1"),
            cancel_url=request.build_absolute_uri("/planos/?failure=1"),
        )
        return redirect(session.url)
    except Exception as e:
        logger.error("Erro ao gerar checkout da Stripe: %s", e, exc_info=True)
        return HttpResponse(f"Erro ao gerar checkout da Stripe: {e}", status=500)


@csrf_exempt
def stripe_webhook(request):
    if request.method == 'POST':
        stripe.api_key = settings.STRIPE_SECRET_KEY
        endpoint_secret = getattr(settings, 'STRIPE_WEBHOOK_SECRET', None)

        payload = request.body
        sig_header = request.headers.get('STRIPE_SIGNATURE')

        if not endpoint_secret:
            return HttpResponse(status=400)

        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, endpoint_secret
            )
        except ValueError:
            return HttpResponse(status=400)
        except stripe.error.SignatureVerificationError:
            return HttpResponse(status=400)

        try:
            event_type = event.get('type') if isinstance(event, dict) else event.type

            # Se for uma notificação de pagamento concluído (imediato ou assíncrono via Boleto)
            if event_type in ['checkout.session.completed', 'checkout.session.async_payment_succeeded']:
                session = event.get('data', {}).get('object', {}) if isinstance(event, dict) else event.data.object

                if session.get('payment_status') == 'paid':
                    user_id = session.get('client_reference_id')
                    trans_amount_cents = session.get('amount_total', 0)
                    trans_amount = trans_amount_cents / 100.0

                    plan = next((p for p in PLANS.values() if p['price'] == trans_amount), None)

                    if user_id and plan:
                        from django.db import transaction
                        with transaction.atomic():
                            user = User.objects.select_for_update().get(id=user_id)

                            update_fields = ['credits']
                            user.profile.credits += plan['credits']
                            if plan['is_pro']:
                                user.profile.is_pro = True
                                user.profile.subscription_status = "active"
                                update_fields += ['is_pro', 'subscription_status']

                            user.profile.save(update_fields=update_fields)
                            logger.info("Usuário %s - Pagamento processado Stripe: %s", user.username, trans_amount)

                        # Disparar Email de notificação
                        try:
                            from ..tasks import send_payment_notification_task
                            payment_id = session.get('payment_intent') or session.get('id')
                            nome_cliente = user.get_full_name() or user.username
                            email_cliente = user.email or 'N/A'
                            send_payment_notification_task.delay(nome_cliente, email_cliente, trans_amount, payment_id)
                        except Exception as em:
                            logger.error("Erro disparando webhook email: %s", em)

            return HttpResponse(status=200)
        except Exception as e:
            logger.error("Stripe Webhook Handling Error: %s", e, exc_info=True)
            return HttpResponse(status=400)
    return HttpResponse(status=405)


def planos_view(request):
    if not request.session.session_key:
        request.session.create()

    from django.shortcuts import render
    if request.user.is_authenticated:
        total_julgados = Parecer.objects.filter(user=request.user).count()
    else:
        total_julgados = Parecer.objects.filter(user__isnull=True, session_key=request.session.session_key).count()

    context = {
        'total_julgados': total_julgados
    }
    return render(request, 'planos.html', context)
