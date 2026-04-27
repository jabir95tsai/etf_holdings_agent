"""Notifier tests."""

from __future__ import annotations

from src.config import GmailConfig
from src.notifier import _build_message


def test_build_message_addresses_all_receivers():
    cfg = GmailConfig(
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        sender="sender@gmail.com",
        app_password="password",
        receivers=["first@gmail.com", "second@gmail.com"],
        notify_on_no_update=True,
    )

    msg = _build_message(cfg, "subject", "body")

    assert msg["To"] == "first@gmail.com, second@gmail.com"
