"""OtpSender Protocol.

An abstraction (not speculative): it has real concrete variations selected at
runtime by config — DevEchoSender (logs the code in non-prod so the login flow is
testable) and NullSender (prod safe no-op until a gateway is wired). Future
MSG91 / Twilio / Gupshup senders implement this same interface, so otp_service
never changes when a real gateway lands — only the factory does.
"""
from __future__ import annotations

from typing import Protocol


class OtpSender(Protocol):
    async def send(self, *, phone: str, code: str) -> None:
        ...
