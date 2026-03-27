import os
import json
from django.http import HttpResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.models import User
from svix.webhooks import Webhook, WebhookVerificationError

@csrf_exempt
def clerk_webhook_view(request):
    """
    Endpoint para receber webhooks do Clerk e sincronizar usuários locais.
    """
    if request.method != 'POST':
        return HttpResponse("Method not allowed", status=405)

    clerk_webhook_secret = os.getenv("CLERK_WEBHOOK_SECRET")

    if not clerk_webhook_secret or clerk_webhook_secret == 'PLACEHOLDER_FOR_WEBHOOK_SECRET':
        return HttpResponseForbidden("Webhook secret not configured")

    headers = {
        "svix-id": request.headers.get("svix-id"),
        "svix-timestamp": request.headers.get("svix-timestamp"),
        "svix-signature": request.headers.get("svix-signature")
    }

    payload = request.body.decode('utf-8')

    try:
        wh = Webhook(clerk_webhook_secret)
        evt = wh.verify(payload, headers)
    except WebhookVerificationError as e:
        return HttpResponseForbidden(f"Invalid webhook signature: {e}")

    # Processar o evento do Clerk
    event_type = evt.get("type")
    data = evt.get("data", {})

    if event_type in ['user.created', 'user.updated']:
        clerk_id = data.get("id")
        first_name = data.get("first_name") or ""
        last_name = data.get("last_name") or ""
        
        email_addresses = data.get("email_addresses", [])
        email = email_addresses[0].get("email_address") if email_addresses else ""
        
        # Sincroniza com o User do Django (usando username como o clerk_id unico)
        user, created = User.objects.update_or_create(
            username=clerk_id,
            defaults={
                'first_name': first_name,
                'last_name': last_name,
                'email': email,
                'is_active': True
            }
        )
        # Se quiser definir senha aleatoria inútil para o django nao reclamar:
        if created:
            user.set_unusable_password()
            user.save()

    elif event_type == 'user.deleted':
        clerk_id = data.get("id")
        if clerk_id:
            User.objects.filter(username=clerk_id).delete()

    return HttpResponse("Webhook received correctly", status=200)
