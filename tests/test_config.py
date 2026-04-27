"""Configuration tests."""

from __future__ import annotations

from src.config import _email_list, load_config


def test_email_list_accepts_commas_and_semicolons():
    assert _email_list("a@gmail.com, b@gmail.com; c@gmail.com") == [
        "a@gmail.com",
        "b@gmail.com",
        "c@gmail.com",
    ]


def test_load_config_prefers_receiver_emails(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "holdings.sqlite"))
    monkeypatch.setenv("RAW_DIR", str(tmp_path / "raw"))
    monkeypatch.setenv("REPORT_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("GMAIL_SENDER_EMAIL", "sender@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "password")
    monkeypatch.setenv("GMAIL_RECEIVER_EMAIL", "old@gmail.com")
    monkeypatch.setenv(
        "GMAIL_RECEIVER_EMAILS",
        "first@gmail.com,second@gmail.com",
    )

    cfg = load_config()

    assert cfg.gmail.receivers == ["first@gmail.com", "second@gmail.com"]
    assert cfg.gmail.is_configured


def test_load_config_allows_source_and_ezmoney_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "holdings.sqlite"))
    monkeypatch.setenv("RAW_DIR", str(tmp_path / "raw"))
    monkeypatch.setenv("REPORT_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("EZMONEY_FUND_CODE", "ABC123")
    monkeypatch.setenv("SOURCE_ORDER", "moneydj, official")

    cfg = load_config()

    assert cfg.source_order == ["moneydj", "official"]
    assert cfg.ezmoney_excel_url.endswith("FundCode=ABC123")
    assert cfg.ezmoney_referer_url.endswith("FundCode=ABC123")
