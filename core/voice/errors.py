"""User-facing errors for local voice model loading."""

from __future__ import annotations


def is_offline_model_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    if "localentrynotfounderror" in type(exc).__name__.lower():
        return True
    markers = (
        "getaddrinfo failed",
        "connecterror",
        "connection error",
        "internet connection",
        "network is unreachable",
        "failed to establish a new connection",
        "name or service not known",
        "temporary failure in name resolution",
    )
    return any(m in msg for m in markers)


def format_voice_model_error(component: str, exc: BaseException) -> str:
    if is_offline_model_error(exc):
        return (
            f"{component} is unavailable — model not cached and the download server "
            "could not be reached. Connect to the internet and restart Emily to enable "
            "voice. You can still type commands in the text box."
        )
    short = str(exc).splitlines()[0][:180]
    return f"{component} failed to load: {short}"
