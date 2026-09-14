"""Config package — lazy imports to avoid circular/missing-dep crashes."""

__all__ = ["settings"]


def __getattr__(name):
    if name == "settings":
        from config.settings import settings  # noqa: PLC0415
        return settings
    raise AttributeError(f"module 'config' has no attribute {name!r}")
