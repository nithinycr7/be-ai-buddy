"""Concrete OtpSender implementations. Add real gateways (MSG91/Twilio/Gupshup) here."""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


class DevEchoSender:
    """Non-prod: log the code so the parent-login flow is end-to-end testable."""
    async def send(self, *, phone: str, code: str) -> None:
        log.info("[DEV OTP] %s -> %s", phone, code)


class NullSender:
    """Prod until a gateway is wired: never leak the code; just warn."""
    async def send(self, *, phone: str, code: str) -> None:
        log.warning("OTP requested for %s but no SMS provider is configured", phone)


# Future, implementing the same OtpSender interface — factory wires them by config:
#   class Msg91Sender:  async def send(self, *, phone, code): ...  (HTTP call to MSG91)
#   class TwilioSender: async def send(self, *, phone, code): ...


class DevEchoEmailSender:
    """Non-prod: log the email so invite/OTP-by-email flows are end-to-end testable."""
    async def send(self, *, to: str, subject: str, body: str) -> None:
        log.info("[DEV EMAIL] to=%s | %s | %s", to, subject, body)


class NullEmailSender:
    """Prod until an email provider is wired: never leak contents; just warn."""
    async def send(self, *, to: str, subject: str, body: str) -> None:
        log.warning("Email requested for %s but no email provider is configured", to)


# Future, same EmailSender interface — factory wires them by config:
#   class SesEmailSender:      async def send(self, *, to, subject, body): ...  (AWS SES)
#   class SendgridEmailSender: async def send(self, *, to, subject, body): ...
