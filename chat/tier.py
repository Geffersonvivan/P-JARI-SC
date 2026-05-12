"""
Resolução do nível de IA (tier) por parecer/usuário.

Cada tier define quais modelos Gemini e Anthropic são usados em cada fase.
O tier efetivo é: override do usuário > padrão global (TierConfig singleton).
"""
import logging

_log = logging.getLogger(__name__)

# ── Mapeamento tier → modelos por fase ─────────────────────────────────────
# Chaves usadas nas integrações: gemini_f1, gemini_f2, gemini_f3, gemini_f4,
# gemini_f5, anthropic_f3, anthropic_f5, anthropic_f4_analise, anthropic_f6

TIER_MODELS = {
    'atual': {
        'gemini_f1': 'gemini-2.5-flash',
        'gemini_f2': 'gemini-2.5-flash',
        'gemini_f3': 'gemini-2.5-flash',
        'gemini_f4': 'gemini-2.5-flash',
        'gemini_f5': 'gemini-2.5-flash',
        'anthropic_f3': 'claude-haiku-4-5-20251001',
        'anthropic_f5': 'claude-sonnet-4-6',
        'anthropic_f4_analise': 'claude-haiku-4-5-20251001',
        'anthropic_f6': 'claude-haiku-4-5-20251001',
        'anthropic_cag': 'claude-haiku-4-5-20251001',
    },
    'reforcado': {
        'gemini_f1': 'gemini-2.5-flash',
        'gemini_f2': 'gemini-2.5-flash',
        'gemini_f3': 'gemini-2.5-flash',
        'gemini_f4': 'gemini-2.5-flash',
        'gemini_f5': 'gemini-2.5-pro',
        'anthropic_f3': 'claude-haiku-4-5-20251001',
        'anthropic_f5': 'claude-sonnet-4-6',
        'anthropic_f4_analise': 'claude-sonnet-4-6',
        'anthropic_f6': 'claude-sonnet-4-6',
        'anthropic_cag': 'claude-haiku-4-5-20251001',
    },
    'maximo': {
        'gemini_f1': 'gemini-2.5-pro',
        'gemini_f2': 'gemini-2.5-pro',
        'gemini_f3': 'gemini-2.5-pro',
        'gemini_f4': 'gemini-2.5-pro',
        'gemini_f5': 'gemini-2.5-pro',
        'anthropic_f3': 'claude-sonnet-4-6',
        'anthropic_f5': 'claude-sonnet-4-6',
        'anthropic_f4_analise': 'claude-sonnet-4-6',
        'anthropic_f6': 'claude-sonnet-4-6',
        'anthropic_cag': 'claude-sonnet-4-6',
    },
}


def get_tier(user=None) -> str:
    """Resolve o tier efetivo: override do usuário > padrão global."""
    # Override por usuário
    if user:
        try:
            profile = user.profile
            if profile.tier:
                return profile.tier
        except Exception:
            pass

    # Padrão global
    try:
        from chat.models import TierConfig
        config = TierConfig.load()
        return config.tier_padrao
    except Exception:
        return 'atual'


def get_models(user=None) -> dict:
    """Retorna dict com modelo de cada fase para o tier efetivo do usuário."""
    tier = get_tier(user)
    models = TIER_MODELS.get(tier, TIER_MODELS['atual'])
    _log.debug("Tier resolvido: %s (user=%s)", tier, getattr(user, 'username', None))
    return models


def get_models_for_parecer(parecer) -> dict:
    """Atalho: resolve tier a partir do parecer (usa parecer.user)."""
    return get_models(getattr(parecer, 'user', None))
