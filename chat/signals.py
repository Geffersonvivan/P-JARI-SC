from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.core.cache import cache


@receiver([post_save, post_delete], sender='chat.PostForum')
def invalidar_cache_forum(sender, **kwargs):
    cache.delete_many(['forum_posts_top50', 'forum_ultimo_post'])


@receiver([post_save, post_delete], sender='chat.BancoTese')
def invalidar_cache_teses(sender, **kwargs):
    cache.delete('teses_comunidade_top20')
