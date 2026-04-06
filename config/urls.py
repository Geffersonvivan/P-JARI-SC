"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static


from django.contrib.auth.decorators import user_passes_test

def trigger_error(request):
    division_by_zero = 1 / 0

from chat.webhooks_clerk import clerk_webhook_view

from django.http import JsonResponse, HttpResponse, HttpResponseRedirect
from django.views.generic import RedirectView

def health_check(request):
    return JsonResponse({'status': 'ok'})

def robots_txt(request):
    lines = [
        "User-agent: *",
        "Disallow: /pjari-admin/",
        "Disallow: /app/",
        "Disallow: /api/",
        "Disallow: /chat/",
        "Disallow: /aceite-termos/",
        "Disallow: /checkout/",
        "Disallow: /estatisticas/",
        "Allow: /",
        "Allow: /planos/",
        "Allow: /termos/",
        "Allow: /politica-de-privacidade/",
        "",
        f"Sitemap: https://www.pjarisc.com.br/sitemap.xml",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")

def sitemap_xml(request):
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        '  <url><loc>https://www.pjarisc.com.br/</loc>'
        '<changefreq>weekly</changefreq><priority>1.0</priority></url>\n'
        '  <url><loc>https://www.pjarisc.com.br/planos/</loc>'
        '<changefreq>weekly</changefreq><priority>0.8</priority></url>\n'
        '  <url><loc>https://www.pjarisc.com.br/termos/</loc>'
        '<changefreq>monthly</changefreq><priority>0.5</priority></url>\n'
        '  <url><loc>https://www.pjarisc.com.br/politica-de-privacidade/</loc>'
        '<changefreq>monthly</changefreq><priority>0.5</priority></url>\n'
        '</urlset>'
    )
    return HttpResponse(xml, content_type="application/xml")

def favicon_ico(request):
    # Redireciona /favicon.ico para o favicon estático real
    return HttpResponseRedirect('/static/img/favicon.png')

urlpatterns = [
    path('health/', health_check, name='health_check'),
    path('robots.txt', robots_txt, name='robots_txt'),
    path('sitemap.xml', sitemap_xml, name='sitemap_xml'),
    path('favicon.ico', favicon_ico, name='favicon_ico'),
    path('pjari-admin/', admin.site.urls),
    path('', include('chat.urls')),
    path('api/webhooks/clerk/', clerk_webhook_view, name='clerk_webhook'),
    # path('accounts/', include('allauth.urls')), # Removing django-allauth routing
    path('tinymce/', include('tinymce.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += [
        path('sentry-debug/', user_passes_test(lambda u: u.is_superuser)(trigger_error)),
    ]

if getattr(settings, 'SILK_ENABLED', False):
    urlpatterns += [path('silk/', include('silk.urls', namespace='silk'))]

