from django.urls import path
from . import views

urlpatterns = [
    path('', views.home_view, name='home'),
    path('parecer/create/', views.create_parecer_view, name='create_parecer'),
    path('parecer/<int:id>/delete/', views.delete_parecer_view, name='delete_parecer'),
    path('parecer/<int:id>/mover/', views.mover_parecer_view, name='mover_parecer'),
    path('projeto/<int:id>/delete/', views.delete_projeto_view, name='delete_projeto'),
    path('chat/message/', views.chat_message_view, name='chat_message'),
    path('chat/task-status/<str:task_id>/', views.check_task_status_view, name='check_task_status'),
    path('parecer/<int:id>/editor/', views.editar_parecer_view, name='editar_parecer'),
    path('parecer/<int:id>/salvar/', views.salvar_parecer_view, name='salvar_parecer'),
    path('planos/', views.planos_view, name='planos'),
    path('checkout/', views.checkout_view, name='checkout'),
    path('webhooks/mercadopago/', views.mercadopago_webhook, name='mercadopago_webhook'),
    path('estatisticas/', views.estatisticas_view, name='estatisticas'),
    path('estatisticas-gerais/', views.estatisticas_gerais_view, name='estatisticas_gerais'),
    path('onboarding/dismiss/', views.dismiss_onboarding_view, name='dismiss_onboarding'),
    path('api/reorder-folders/', views.reorder_folders_view, name='reorder_folders'),
]
