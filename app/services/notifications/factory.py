"""Factory: choose the OtpSender by config (the one place that knows which gateway)."""
from __future__ import annotations

from ...core.config import settings
from .base import OtpSender
from .senders import DevEchoSender, NullSender


def get_otp_sender() -> OtpSender:
    # Prod with no gateway wired yet → NullSender (safe: never logs the code).
    # Non-prod → DevEchoSender (echoes for testing). Wire real senders here as they land,
    # e.g. `if settings.MSG91_KEY: return Msg91Sender(settings.MSG91_KEY)`.
    if settings.is_production():
        return NullSender()
    return DevEchoSender()
