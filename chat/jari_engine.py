"""
Stub de compatibilidade — NÃO EDITAR AQUI.

A lógica foi migrada para chat/engine/.
Este arquivo existe apenas para que imports antigos continuem funcionando:

    from chat.jari_engine import JariEngine, FASE_COLETA, ...

Qualquer nova funcionalidade deve ser adicionada em chat/engine/__init__.py
ou nos módulos chat/engine/phase_X.py correspondentes.
"""

from chat.engine import (  # noqa: F401
    JariEngine,
    FASE_COLETA,
    FASE_AGUARDA_CONFIRMACAO_FASE1,
    FASE_DIR,
    FASE_ADMISSIBILIDADE_GERADA,
    FASE_AGUARDA_CONFIRMACAO_ADMISSIBILIDADE,
    FASE_MERITO,
    FASE_AGUARDA_CONFIRMACAO_MERITO,
    FASE_RESULTADO,
    FASE_AUDITORIA,
    FASE_SELECAO_PASTA,
    FASE_FINALIZADO,
    _p,
)
