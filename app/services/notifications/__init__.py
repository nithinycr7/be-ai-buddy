"""Outbound notifications (OTP SMS). Program to the OtpSender Protocol; pick the
concrete sender with get_otp_sender()."""
from .base import OtpSender
from .factory import get_otp_sender

__all__ = ["OtpSender", "get_otp_sender"]
