"""Outbound notifications (OTP SMS + email). Program to the sender Protocols; pick
the concrete sender with get_otp_sender() / get_email_sender()."""
from .base import EmailSender, OtpSender
from .factory import get_email_sender, get_otp_sender

__all__ = ["OtpSender", "EmailSender", "get_otp_sender", "get_email_sender"]
