"""
Unit tests for the LLD abstractions (no DB, no real LLM/SMS):
- LLM fallback chain (Strategy): order, first-success short-circuit, all-fail → None.
- OTP sender factory (Factory): non-prod → DevEchoSender, prod → NullSender; senders
  satisfy the OtpSender async contract.

    ./venv/bin/python -m tests.test_llm_and_notifications
"""
import asyncio
import sys

from app.services.llm import generate_text
from app.services.notifications import get_otp_sender
from app.services.notifications.senders import DevEchoSender, NullSender


class _Fake:
    """A fake LLMTextProvider that records calls and returns a scripted result."""
    def __init__(self, name, result, log):
        self.name, self.result, self.log = name, result, log

    def generate(self, *, system, user, max_tokens=9000, temperature=0.6):
        self.log.append(self.name)
        return self.result


def _run():
    checks = []

    # 1) first provider succeeds → returned, later providers NOT called
    log = []
    out = generate_text([_Fake("a", "HTML_A", log), _Fake("b", "HTML_B", log)], system="s", user="u")
    checks.append(("first success short-circuits", out == "HTML_A" and log == ["a"]))

    # 2) first returns None → falls through to second
    log = []
    out = generate_text([_Fake("a", None, log), _Fake("b", "HTML_B", log)], system="s", user="u")
    checks.append(("falls through on None", out == "HTML_B" and log == ["a", "b"]))

    # 3) all fail → None (every provider tried, in order)
    log = []
    out = generate_text([_Fake("a", None, log), _Fake("b", None, log)], system="s", user="u")
    checks.append(("all fail -> None", out is None and log == ["a", "b"]))

    # 4) empty string is treated as failure (not a valid result)
    log = []
    out = generate_text([_Fake("a", "", log), _Fake("b", "HTML_B", log)], system="s", user="u")
    checks.append(("empty string is a miss", out == "HTML_B" and log == ["a", "b"]))

    # 5) OTP factory picks by env; senders honor the async OtpSender contract
    import types as _types
    import app.services.notifications.factory as fac
    real_settings = fac.settings
    try:
        fac.settings = _types.SimpleNamespace(is_production=lambda: False)
        checks.append(("non-prod -> DevEchoSender", isinstance(get_otp_sender(), DevEchoSender)))
        fac.settings = _types.SimpleNamespace(is_production=lambda: True)
        checks.append(("prod -> NullSender", isinstance(get_otp_sender(), NullSender)))
    finally:
        fac.settings = real_settings

    async def _send_both():
        await DevEchoSender().send(phone="+91999", code="123456")
        await NullSender().send(phone="+91999", code="123456")
    asyncio.run(_send_both())
    checks.append(("senders send() is awaitable + no raise", True))

    for name, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    passed = all(ok for _, ok in checks)
    print("\nRESULT:", "ALL PASS" if passed else "FAILURES")
    return passed


if __name__ == "__main__":
    sys.exit(0 if _run() else 1)
