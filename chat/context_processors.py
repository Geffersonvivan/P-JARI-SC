import random
from django.core.cache import cache
from django.conf import settings
from django.utils import timezone

def pjari_info(request):
    """
    Context processor para injetar a versão do P-JARI e o número de usuários online
    (reais + tráfego fantasma orgânico) em todos os templates.
    """
    # 1. Rastreio de usuários reais
    online_users_keys = cache.get('online_users_keys', set())
    
    if request.user.is_authenticated:
        user_key = f'user_online_{request.user.id}'
        # Set the user as online in cache for 15 minutes
        cache.set(user_key, True, 60 * 15)
        online_users_keys.add(user_key)
        
    # Limpa chaves expiradas
    active_keys = {key for key in online_users_keys if cache.get(key)}
    cache.set('online_users_keys', active_keys, 60 * 60 * 24) # Mantém a lista por 24h
    real_users_count = len(active_keys)

    # 2. Usuários Fantasmas Orgânicos baseados no horário
    now = timezone.localtime(timezone.now())
    hour = now.hour
    
    # Baselines (trafego fake)
    if 8 <= hour < 12 or 13 <= hour < 18:
        # Horário comercial forte
        baseLine = 15
        fluctuation = 4
    elif 12 <= hour < 13 or 18 <= hour < 20:
        # Horário de almoço / fim de expediente
        baseLine = 8
        fluctuation = 3
    else:
        # Madrugada ou tarde da noite
        baseLine = 2
        fluctuation = 2
        
    # Obtém uma flutuação estável a cada 5 minutos usando uma semente baseada na hora e minuto atual
    # Para que não mude a cada F5, mas mude sutilmente ao longo do tempo.
    time_seed = f"{now.date()}_{hour}_{now.minute // 5}"
    random.seed(time_seed)
    
    # Adicionamos uma pequena randomicidade que dura 5 minutos
    ghost_users = baseLine + random.randint(-fluctuation, fluctuation)
    if ghost_users < 1:
        ghost_users = 1
        
    # Reseta a seed do Python para não afetar o resto da aplicação
    random.seed()
    
    total_online = real_users_count + ghost_users
    
    return {
        'pjari_version': getattr(settings, 'PJARI_VERSION', '1.0'),
        'online_users_count': total_online
    }
