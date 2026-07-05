"""Factory: choose the OtpSender by config (the one place that knows which gateway)."""
from __future__ import annotations

from ...core.config import settings
from .base import EmailSender, OtpSender
from .senders import DevEchoEmailSender, DevEchoSender, NullEmailSender, NullSender


def get_otp_sender() -> OtpSender:
    # Prod with no gateway wired yet → NullSender (safe: never logs the code).
    # Non-prod → DevEchoSender (echoes for testing). Wire real senders here as they land,
    # e.g. `if settings.MSG91_KEY: return Msg91Sender(settings.MSG91_KEY)`.
    if settings.is_production():
        return NullSender()
    return DevEchoSender()


def get_email_sender() -> EmailSender:
    # Same policy as SMS: Null in prod (no leak) until a provider is wired,
    # DevEcho in non-prod. Wire a real sender here, e.g.
    # `if settings.SENDGRID_KEY: return SendgridEmailSender(settings.SENDGRID_KEY)`.
    if settings.is_production():
        return NullEmailSender()
    return DevEchoEmailSender()
