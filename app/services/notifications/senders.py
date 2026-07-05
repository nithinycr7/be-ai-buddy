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
