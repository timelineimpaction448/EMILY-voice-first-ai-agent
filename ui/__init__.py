"""Emily desktop UI package.

EmilyUI is imported lazily so lightweight submodules (e.g. ui.services.audio_level)
can be imported from the engine without pulling in PyQt6 / the whole HUD.
"""

__all__ = ["EmilyUI"]


def __getattr__(name):  # PEP 562 lazy attribute
    if name == "EmilyUI":
        from ui.app import EmilyUI
        return EmilyUI
    raise AttributeError(f"module 'ui' has no attribute {name!r}")
