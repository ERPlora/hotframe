# SPDX-License-Identifier: Apache-2.0
"""hotframe — Modular Python web framework with hot-mount dynamic modules."""

__version__ = "0.0.1"

# ---------------------------------------------------------------------------
# Lazy imports — only loaded when accessed
# ---------------------------------------------------------------------------

_LAZY_IMPORTS: dict[str, str] = {
    # Bootstrap
    "create_app": "hotframe.bootstrap",
    # Settings
    "HotframeSettings": "hotframe.config.settings",
    "get_settings": "hotframe.config.settings",
    # Apps
    "AppConfig": "hotframe.apps.config",
    "ModuleConfig": "hotframe.apps.config",
    # Models
    "Base": "hotframe.models.base",
    "HubBaseModel": "hotframe.models.base",
    "TimeStampedModel": "hotframe.models.base",
    "ActiveModel": "hotframe.models.base",
    "HubMixin": "hotframe.models.mixins",
    "TimestampMixin": "hotframe.models.mixins",
    "AuditMixin": "hotframe.models.mixins",
    "SoftDeleteMixin": "hotframe.models.mixins",
    "HubQuery": "hotframe.models.queryset",
    # Repository
    "BaseRepository": "hotframe.repository.base",
    # DB Protocols
    "ISession": "hotframe.db.protocols",
    "IQueryBuilder": "hotframe.db.protocols",
    "IRepository": "hotframe.db.protocols",
    "IExecuteResult": "hotframe.db.protocols",
    "IScalarResult": "hotframe.db.protocols",
    # Signals
    "AsyncEventBus": "hotframe.signals.dispatcher",
    "HookRegistry": "hotframe.signals.hooks",
    "BaseEvent": "hotframe.signals.types",
    "register_event": "hotframe.signals.types",
    # ORM
    "setup_orm_events": "hotframe.orm.events",
    # Views
    "htmx_view": "hotframe.views.responses",
    "is_htmx_request": "hotframe.views.responses",
    "htmx_redirect": "hotframe.views.responses",
    "htmx_refresh": "hotframe.views.responses",
    "htmx_trigger": "hotframe.views.responses",
    "add_message": "hotframe.views.responses",
    "sse_stream": "hotframe.views.responses",
    "TurboStream": "hotframe.views.streams",
    "StreamResponse": "hotframe.views.streams",
    "BroadcastHub": "hotframe.views.broadcast",
    # Templating
    "SlotRegistry": "hotframe.templating.slots",
    # Auth
    "get_session_user_id": "hotframe.auth.auth",
    "hash_password": "hotframe.auth.auth",
    "verify_password": "hotframe.auth.auth",
    "has_permission": "hotframe.auth.permissions",
    "require_permission": "hotframe.auth.permissions",
    # Dependencies
    "DbSession": "hotframe.auth.current_user",
    "CurrentUser": "hotframe.auth.current_user",
    "OptionalUser": "hotframe.auth.current_user",
    "EventBus": "hotframe.auth.current_user",
    "Hooks": "hotframe.auth.current_user",
    "Slots": "hotframe.auth.current_user",
    "get_db": "hotframe.auth.current_user",
    "get_current_user": "hotframe.auth.current_user",
    # Services
    "ModuleService": "hotframe.apps.service_facade",
    "action": "hotframe.apps.service_facade",
    # Engine
    "ModuleStateDB": "hotframe.engine.state",
    "HotMountPipeline": "hotframe.engine.pipeline",
    "ImportManager": "hotframe.engine.import_manager",
    "MarketplaceClient": "hotframe.engine.marketplace_client",
    # Forms
    "FormRenderer": "hotframe.forms.rendering",
    # Config
    "get_engine": "hotframe.config.database",
    "get_session_factory": "hotframe.config.database",
    # Storage
    "MediaStorage": "hotframe.storage.media",
    "get_media_storage": "hotframe.storage.media",
}


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        import importlib

        module = importlib.import_module(_LAZY_IMPORTS[name])
        return getattr(module, name)
    raise AttributeError(f"module 'hotframe' has no attribute {name!r}")


__all__ = [*list(_LAZY_IMPORTS.keys()), "__version__"]
