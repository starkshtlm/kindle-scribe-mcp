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


def test_replay_is_only_recorded_after_success():
    """A retry after a failed delivery must still be processed — recording the
    id too early would silently drop the document."""
    app.REPLAY_FILE.unlink(missing_ok=True)  # state persists across runs by design
    assert app.already_processed("msg_unique_1") is False
    assert app.already_processed("msg_unique_1") is False  # retry, not yet done
    app.mark_processed("msg_unique_1")
    assert app.already_processed("msg_unique_1") is True


@pytest.mark.parametrize(
    "domain", ["amazon.com", "amazon.co.uk", "amazon.de", "bounces.amazon.com"]
)
def test_regional_amazon_domains_are_trusted(domain):
    """Storefronts differ by country; DKIM/SPF still has to prove the domain."""
    assert app.is_trusted_domain(domain) is True


@pytest.mark.parametrize("host", [
    "kindle-content-requests-prod.s3.amazonaws.com",
    "www.amazon.co.uk",
])
def test_amazon_owned_hosts_allowed_on_first_hop(host):
    assert app.url_is_safe(f"https://{host}/x", first_hop=True)[0] is True


def test_rejection_message_says_what_to_do():
    mail = {"to": ["typo@scribe.example.com"], "received_for": []}
    ok, detail = app.addressed_to_us(mail)
    assert ok is False and "inbox@scribe.example.com" in detail


# --- outbound rendering -----------------------------------------------------
# WeasyPrint dereferences external resources and has no flag to disable it, so
# markdown reaching send_to_scribe would otherwise be an SSRF primitive.


@pytest.mark.parametrize(
    "html",
    [
        '<img src="http://169.254.169.254/latest/meta-data/">',
        '<img src="https://evil.test/pixel.png">',
        '<link rel="stylesheet" href="http://127.0.0.1:8377/x">',
        '<div style="background:url(http://evil.test/a.png)">x</div>',
        "<script>fetch('http://evil.test')</script>",
        '<iframe src="http://127.0.0.1/"></iframe>',
        '<object data="http://evil.test/x"></object>',
        '<body background="http://evil.test/bg.png">',
    ],
)
def test_external_references_are_stripped(html):
    out = app.sanitize_html_for_pdf(html)
    assert "http://" not in out and "https://" not in out
    assert "<script" not in out.lower()


def test_inline_data_uris_survive():
    html = '<img src="data:image/png;base64,AAAA">'
    assert "data:image/png" in app.sanitize_html_for_pdf(html)


def test_ordinary_content_is_untouched():
    html = "<p>Plain <b>text</b> and a <a href=\"https://example.com\">link</a></p>"
    out = app.sanitize_html_for_pdf(html)
    assert "<b>text</b>" in out and "example.com" in out  # anchors are not fetched


def test_failed_image_leaves_a_visible_note():
    """A dropped illustration must be explained, not silently vanish."""
    import asyncio

    html = '<img src="https://127.0.0.1/blocked.png">'
    out = asyncio.run(app.inline_remote_images(html))
    assert "could not be fetched" in out and "<img" not in out
