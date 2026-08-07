"""Security regression tests for the inbound trust boundary.

Resend inbound is catch-all and its signature only proves Resend relayed the
mail, so these checks are the only thing standing between a stranger's email
and a stored "Kindle" document. Run: python -m pytest server/test_security.py
"""

import importlib
import os
import sys

import pytest

os.environ.setdefault("RESEND_API_KEY", "re_test")
os.environ.setdefault("KINDLE_EMAIL", "test@kindle.com")
os.environ.setdefault("FROM_EMAIL", "claude@example.com")
os.environ.setdefault("BRIDGE_TOKEN", "testtoken")
os.environ.setdefault("RETURN_EMAIL", "inbox@scribe.example.com")
os.environ.setdefault("INBOX_DIR", "/tmp/scribe-test-inbox")

sys.path.insert(0, os.path.dirname(__file__))
app = importlib.import_module("app")

# Shape of a genuine Amazon export mail, as returned by Resend's API.
GENUINE = {
    "from": "do-not-reply@amazon.com",
    "to": ["inbox@scribe.example.com"],
    "received_for": ["inbox@scribe.example.com"],
    "headers": {
        "dkim-signature": [{"value": "v=1", "params": {"a": "rsa-sha256", "d": "amazon.com"}}],
        "received-spf": "pass (spfCheck: domain of bounces.amazon.com designates 54.240.13.28 as permitted sender)",
    },
}


def test_genuine_mail_is_accepted():
    assert app.addressed_to_us(GENUINE)[0] is True
    assert app.sender_is_authentic(GENUINE)[0] is True


@pytest.mark.parametrize(
    "sender",
    [
        "amazon@attacker.example",  # substring in the local part
        "noreply@amazon.com.attacker.example",  # suffix trick
        "kindle@evil.test",
        "",
    ],
)
def test_forged_senders_are_rejected(sender):
    mail = dict(GENUINE, **{"from": sender})
    assert app.sender_is_authentic(mail)[0] is False


def test_trusted_from_without_authentication_is_rejected():
    """A From header alone proves nothing — DKIM or SPF must back it."""
    mail = dict(GENUINE, headers={})
    assert app.sender_is_authentic(mail)[0] is False


def test_spf_pass_for_untrusted_envelope_is_rejected():
    mail = dict(
        GENUINE,
        headers={"received-spf": "pass (domain of attacker.example designates ...)"},
    )
    assert app.sender_is_authentic(mail)[0] is False


def test_mail_to_another_catch_all_address_is_rejected():
    """Resend accepts any local part at the domain; only ours may proceed."""
    mail = dict(GENUINE, to=["someone-else@scribe.example.com"], received_for=[])
    assert app.addressed_to_us(mail)[0] is False


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8377/internal?amazon",  # plaintext to loopback
        "https://127.0.0.1/?amazon",
        "https://169.254.169.254/latest/meta-data?amazon",  # cloud metadata
        "https://evil.example/?amazon",  # substring trick
        "https://amazon.com.attacker.example/x",  # suffix trick
        "file:///etc/passwd",
    ],
)
def test_ssrf_targets_are_blocked_on_first_hop(url):
    assert app.url_is_safe(url, first_hop=True)[0] is False


def test_real_amazon_link_is_allowed():
    assert app.url_is_safe("https://www.amazon.com/gp/f.html?C=X", first_hop=True)[0]


def test_amazon_redirect_target_is_allowed_on_later_hops():
    """Amazon forwards to S3, so redirects must keep working."""
    ok, _ = app.url_is_safe(
        "https://kindle-content-requests-prod.s3.amazonaws.com/doc.pdf",
        first_hop=False,
    )
    assert ok is True


def test_private_address_blocked_even_on_later_hops():
    """A redirect must not be able to walk into internal space."""
    assert app.url_is_safe("https://localhost/x", first_hop=False)[0] is False


def test_replay_detection():
    assert app.seen_webhook("msg_unique_1") is False
    assert app.seen_webhook("msg_unique_1") is True
