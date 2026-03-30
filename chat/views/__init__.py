from .home import landing_page_view, home_view, _get_filter_kwargs, PLANS  # noqa: F401
from .parecer import (  # noqa: F401
    editar_parecer_view, salvar_parecer_view, create_parecer_view,
    delete_parecer_view, delete_projeto_view, mover_parecer_view,
    salvar_feedback_parecer_view, pdf_proxy_view,
)
from .chat import (  # noqa: F401
    chat_message_view, chat_agent_message_view,
    check_task_status_view, stream_task_status_view,
)
from .billing import planos_view, checkout_view, stripe_webhook  # noqa: F401
from .stats import estatisticas_view, estatisticas_gerais_view  # noqa: F401
from .forum import (  # noqa: F401
    criar_post_forum_view, comentar_post_forum_view, curtir_post_forum_view,
    get_comentarios_forum_view, update_forum_access_view,
)
from .teses import (  # noqa: F401
    create_citacao_view, editar_citacao_view, excluir_citacao_view,
    increment_citacao_usage_view, import_citacao_comunidade_view,
)
from .misc import (  # noqa: F401
    dismiss_onboarding_view, reorder_folders_view, proxy_image_view,
    aceitar_termos_view, visualizar_termos_view, auth_sync_view,
)
