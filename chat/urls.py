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
    path('api/citacao/create/', views.create_citacao_view, name='create_citacao'),
    path('api/citacao/<int:id>/edit/', views.editar_citacao_view, name='editar_citacao'),
    path('api/citacao/<int:id>/delete/', views.excluir_citacao_view, name='excluir_citacao'),
    path('api/citacao/<int:id>/increment/', views.increment_citacao_usage_view, name='increment_citacao_usage'),
    path('api/citacao/<int:id>/import/', views.import_citacao_comunidade_view, name='import_citacao_comunidade'),
    
    # Forum APIs
    path('api/forum/post/create/', views.criar_post_forum_view, name='criar_post_forum'),
    path('api/forum/post/<int:post_id>/comentar/', views.comentar_post_forum_view, name='comentar_post_forum'),
    path('api/forum/post/<int:post_id>/curtir/', views.curtir_post_forum_view, name='curtir_post_forum'),
    path('api/forum/post/<int:post_id>/comentarios/', views.get_comentarios_forum_view, name='get_comentarios_forum'),
    path('api/forum/update-access/', views.update_forum_access_view, name='update_forum_access'),
    path('api/proxy-image/', views.proxy_image_view, name='proxy_image'),
    path('aceite-termos/', views.aceitar_termos_view, name='aceitar_termos'),
    path('termos/', views.visualizar_termos_view, name='termos'),
]
