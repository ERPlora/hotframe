"""
db — low-level database primitives used by ORM models.

Provides ``SingletonMixin`` (ensures exactly one DB row per class via an
upsert pattern) and custom SQLAlchemy column types: ``EncryptedString``
and ``EncryptedText`` (transparent AES encryption/decryption backed by the
hub's secret key).

Key exports::

    from hotframe.db.singletons import SingletonMixin
    from hotframe.db.types import EncryptedString, EncryptedText

Usage::

    class HubSettings(SingletonMixin, HubBaseModel):
        api_key: Mapped[str] = mapped_column(EncryptedString(255))
"""
