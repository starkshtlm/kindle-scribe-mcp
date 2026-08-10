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

os.environ.setdefault("MAIL_TRANSPORT", "resend")
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


@pytest.mark.parametrize(
    "sender",
    [
        '"kindle@amazon.com" <evil@attacker.test>',  # domain hidden in the name
        '"do-not-reply@amazon.com" <x@evil.test>',
        "Amazon <amazon.com@attacker.test>",
    ],
)
def test_a_display_name_cannot_impersonate_amazon(sender):
    """The address is what counts, never the words in front of it."""
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


# --- source pairing ---------------------------------------------------------
# A returning document is matched to the markdown it was rendered from, so the
# model sees the original next to the handwriting instead of bare images.


def test_sent_document_is_paired_with_its_source():
    slug = app.remember_source("Draft for pairing", "# Draft\n\nSection one.")
    assert slug == "draft-for-pairing"
    found = app.find_source("draft-for-pairing")
    assert found and "Section one." in found["markdown"]
    (app.OUTBOX_DIR / f"{slug}.json").unlink(missing_ok=True)


def test_truncated_filename_still_matches():
    """Amazon shortens long filenames in its export subject."""
    slug = app.remember_source("A rather long document title that amazon shortens", "x")
    assert app.find_source(slug + "-extra-tail") is not None
    (app.OUTBOX_DIR / f"{slug}.json").unlink(missing_ok=True)


def test_handwritten_note_has_no_source():
    """A notebook written on the device has nothing to pair with — that is fine."""
    assert app.find_source("some standalone notebook 4711") is None


def test_title_is_taken_from_the_quoted_filename():
    import re
    subject = 'Daniel sent a file "meeting-notes" to you from their Kindle'
    quoted = re.search(r'"([^"]+)"', subject)
    assert quoted.group(1) == "meeting-notes"


def test_replay_state_is_not_listed_as_a_document():
    """Path.glob("*.json") matches dotfiles, so state kept inside the inbox
    used to come back from list_annotated as a phantom document whose id
    nothing could open — and, lacking "processed", it looked permanently new."""
    app.mark_processed("msg_phantom_check")
    assert app.REPLAY_FILE.parent != app.INBOX_DIR
    ids = [i.get("id") for i in app.list_inbox_items(only_new=False)]
    assert "msg_phantom_check" not in ids
    assert all(i is not None for i in ids)


def test_malformed_metadata_is_skipped_not_listed():
    """A half-written file must not become an unopenable listing entry."""
    junk = app.INBOX_DIR / "halfwritten.json"
    junk.write_text('{"id": "trunc')
    try:
        assert app.list_inbox_items(only_new=False) is not None
        assert "trunc" not in str(app.list_inbox_items(only_new=False))
    finally:
        junk.unlink(missing_ok=True)


def test_missing_return_email_is_reported_at_startup(monkeypatch):
    """Sending keeps working while receiving rejects everything, so this is
    invisible until someone reads the logs days later."""
    monkeypatch.delenv("RETURN_EMAIL", raising=False)
    problems = app.warn_if_inbound_is_dead()
    assert any("RETURN_EMAIL" in p for p in problems)


def test_missing_webhook_secret_is_reported_at_startup(monkeypatch):
    monkeypatch.setenv("RESEND_WEBHOOK_SECRET", "")
    problems = app.warn_if_inbound_is_dead()
    assert any("503" in p for p in problems)


def test_configured_inbound_warns_about_nothing(monkeypatch):
    monkeypatch.setenv("RETURN_EMAIL", "inbox@scribe.example.com")
    monkeypatch.setenv("RESEND_WEBHOOK_SECRET", "whsec_example")
    assert app.warn_if_inbound_is_dead() == []


def _env_example() -> dict:
    from pathlib import Path
    root = Path(app.__file__).resolve().parent.parent
    values = {}
    for line in (root / ".env.example").read_text().splitlines():
        if line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def test_env_example_agrees_with_the_code_default():
    """.env.example claimed 0 while the code, setup.sh and the README all said
    30. Whichever value changes, this fails until both move together."""
    import re as _re
    from pathlib import Path
    source = (Path(app.__file__).resolve().parent / "app.py").read_text()
    code_default = _re.search(r'"INBOX_RETENTION_DAYS", "(\d+)"', source).group(1)
    assert _env_example()["INBOX_RETENTION_DAYS"] == code_default


def test_webhook_secret_is_documented_as_required():
    """It was listed under Optional as 'strongly recommended' while the code
    fails closed without it — the single most misleading line in the repo."""
    from pathlib import Path
    text = (Path(app.__file__).resolve().parent.parent / ".env.example").read_text()
    assert "RESEND_WEBHOOK_SECRET" in _env_example()
    assert text.index("RESEND_WEBHOOK_SECRET") < text.index("--- Optional ---")


# --- mailbox transport ------------------------------------------------------
# The IMAP path must reuse the same trust boundary as the webhook path. These
# tests exist so a future change to the adapter cannot quietly bypass it.

RAW_AMAZON = b"""Delivered-To: inbox@scribe.example.com
Received-SPF: pass (domain of bounces.amazon.com designates 54.240.13.28 as permitted sender)
Authentication-Results: mx.google.com; dkim=pass header.i=@amazon.com; spf=pass smtp.mailfrom=bounces.amazon.com
DKIM-Signature: v=1; a=rsa-sha256; d=amazon.com; s=abc; h=From:To:Subject
From: "Amazon" <do-not-reply@amazon.com>
To: inbox@scribe.example.com
Subject: Daniel sent a file "my-plan" to you from their Kindle
Message-ID: <01000198abcdef@email.amazonses.com>
Content-Type: text/html; charset=UTF-8

<html><a href="https://www.amazon.com/gp/f.html?C=ABC">Download</a></html>
"""


def _adapted(raw=RAW_AMAZON):
    import mailbox as mb
    return mb.to_resend_shape(raw)


def test_imap_adapter_matches_the_resend_shape():
    mail = _adapted()
    assert mail["to"] == ["inbox@scribe.example.com"]
    assert mail["received_for"] == ["inbox@scribe.example.com"]
    assert "amazon.com/gp/f.html" in mail["html"]


def test_adapter_drops_the_unverifiable_dkim_header():
    """Anyone who can mail this address can write d=amazon.com into a
    DKIM-Signature header, so it must not reach the trust check."""
    assert "dkim-signature" not in _adapted()["headers"]


def test_forged_dkim_signature_does_not_authenticate_over_imap():
    forged = (
        RAW_AMAZON.replace(b"Authentication-Results", b"X-Was-Auth")
        .replace(b"Received-SPF", b"X-Was-Spf")
    )
    assert b"d=amazon.com" in forged  # the header the attacker controls
    assert app.sender_is_authentic(_adapted(forged))[0] is False


def test_only_the_provider_authentication_results_is_trusted():
    """A second Authentication-Results travelled with the message; ours is the
    one on top. Trusting the wrong one hands the check to the sender."""
    forged = RAW_AMAZON.replace(
        b"Authentication-Results: mx.google.com; dkim=pass header.i=@amazon.com;"
        b" spf=pass smtp.mailfrom=bounces.amazon.com",
        b"Authentication-Results: mx.google.com; dkim=fail header.i=@attacker.test;"
        b" spf=fail smtp.mailfrom=attacker.test\r\n"
        b"Authentication-Results: mx.google.com; dkim=pass header.i=@amazon.com;"
        b" spf=pass smtp.mailfrom=bounces.amazon.com",
    )
    assert app.sender_is_authentic(_adapted(forged))[0] is False


def test_spf_prose_is_not_a_verification_result():
    """`domain of amazon.com designates ...` is free text the sender writes."""
    mail = dict(
        GENUINE,
        headers={
            "received-spf": "pass (domain of amazon.com designates 1.2.3.4)",
            "authentication-results": "mx.google.com; spf=pass "
            "smtp.mailfrom=attacker.test",
        },
    )
    assert app.sender_is_authentic(mail)[0] is False


def test_genuine_mail_passes_the_same_checks_over_imap():
    mail = _adapted()
    assert app.addressed_to_us(mail)[0] is True
    assert app.sender_is_authentic(mail)[0] is True


def test_forged_sender_rejected_over_imap():
    mail = _adapted(RAW_AMAZON.replace(b"do-not-reply@amazon.com",
                                       b"amazon@attacker.example"))
    assert app.sender_is_authentic(mail)[0] is False


def test_stripped_authentication_headers_rejected_over_imap():
    """A message that never passed DKIM/SPF must not be trusted."""
    mail = _adapted(
        RAW_AMAZON.replace(b"DKIM-Signature", b"X-Was-Dkim")
        .replace(b"Authentication-Results", b"X-Was-Auth")
        .replace(b"Received-SPF", b"X-Was-Spf")
    )
    assert app.sender_is_authentic(mail)[0] is False


def test_mail_to_a_different_address_rejected_over_imap():
    mail = _adapted(
        RAW_AMAZON.replace(b"To: inbox@scribe.example.com", b"To: other@example.com")
        .replace(b"Delivered-To: inbox@scribe.example.com",
                 b"Delivered-To: other@example.com")
    )
    assert app.addressed_to_us(mail)[0] is False


# --- outbound rendering and item ids ----------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        '<img src="http://169.254.169.254/latest/meta-data">',
        "<script>fetch('http://127.0.0.1:8377')</script>",
        '"><link rel=stylesheet href="http://evil.test/x.css">',
    ],
)
def test_a_model_supplied_title_cannot_inject_markup(title):
    """The title bypassed sanitize_html_for_pdf, which only ever saw the body,
    and WeasyPrint fetches whatever it is handed."""
    html = app.document_html(title, "<p>body</p>", "meta")
    # The text may survive; what must not is a tag the renderer would fetch.
    for tag in ("<img", "<script", "<link"):
        assert tag not in html.lower()
    assert "&lt;" in html


def test_the_title_still_reaches_the_page():
    assert "Plan &amp; notes" in app.document_html("Plan & notes", "<p>x</p>", "m")


@pytest.mark.parametrize(
    "item_id",
    [
        "../../etc/passwd",
        "..\\..\\windows\\win.ini",  # blocking "/" alone misses this one
        "1754400000-ok/../../x",
        "1754400000-ok\\..\\x",
        "",
        "no-timestamp",
    ],
)
def test_traversal_item_ids_are_refused(item_id):
    assert app.valid_item_id(item_id) is False


def test_real_item_ids_are_accepted():
    assert app.valid_item_id(f"{int(__import__('time').time())}-my-plan-2") is True


# --- transport selection ----------------------------------------------------
# Outbound and inbound are chosen separately, so a fresh interpreter is needed
# per combination: the module resolves its configuration at import time.


def _load(env: dict):
    """Import app.py in a subprocess with exactly this environment."""
    import json as _json
    import subprocess as _sp
    from pathlib import Path

    server = str(Path(app.__file__).resolve().parent)
    base = {
        "KINDLE_EMAIL": "x@kindle.com",
        "BRIDGE_TOKEN": "t",
        "RETURN_EMAIL": "inbox@example.com",
        "INBOX_DIR": "/tmp/scribe-transport-test/inbox",
        "OUTBOX_DIR": "/tmp/scribe-transport-test/outbox",
        "PATH": os.environ.get("PATH", ""),
    }
    code = (
        "import sys,json;sys.path.insert(0,%r);import app;"
        "print(json.dumps({'out':app.MAIL_OUT,'in':app.MAIL_IN,"
        "'from':app.FROM_EMAIL,'imap_user':app.IMAP_USER}))" % server
    )
    done = _sp.run([sys.executable, "-c", code], env={**base, **env},
                   capture_output=True, text=True)
    if done.returncode != 0:
        return {"error": (done.stderr or done.stdout).strip().splitlines()[-1]}
    return _json.loads(done.stdout.strip().splitlines()[-1])


SMTP_ENV = {
    "SMTP_HOST": "smtp.gmail.com",
    "SMTP_USER": "me@gmail.com",
    "SMTP_PASSWORD": "app-password",
    "IMAP_HOST": "imap.gmail.com",
}


@pytest.mark.parametrize(
    "transport,expected",
    [("mailbox", ("smtp", "imap")), ("resend", ("resend", "resend"))],
)
def test_the_old_single_switch_still_selects_both_directions(transport, expected):
    """Existing .env files must keep working across the upgrade."""
    env = dict(SMTP_ENV, MAIL_TRANSPORT=transport)
    if transport == "resend":
        env = {"MAIL_TRANSPORT": transport, "RESEND_API_KEY": "re_x",
               "FROM_EMAIL": "claude@scribe.example.com"}
    got = _load(env)
    assert (got.get("out"), got.get("in")) == expected, got


def test_sending_over_smtp_while_receiving_through_resend():
    """The hybrid: no domain of your own, but push instead of polling."""
    got = _load(dict(SMTP_ENV, MAIL_OUT="smtp", MAIL_IN="resend",
                     RESEND_API_KEY="re_x"))
    assert (got.get("out"), got.get("in")) == ("smtp", "resend"), got
    assert got["from"] == "me@gmail.com"  # Amazon's approved sender


def test_receiving_through_resend_still_needs_the_api_key():
    """The webhook carries only metadata; the mail body is fetched afterwards,
    so a missing key would fail on the first returning document instead."""
    got = _load(dict(SMTP_ENV, MAIL_OUT="smtp", MAIL_IN="resend"))
    assert "RESEND_API_KEY" in got.get("error", "")


def test_polling_can_read_a_different_mailbox_than_it_sends_from():
    got = _load(dict(SMTP_ENV, MAIL_OUT="smtp", MAIL_IN="imap",
                     IMAP_USER="scribe@gmail.com", IMAP_PASSWORD="other"))
    assert got["imap_user"] == "scribe@gmail.com"
    assert got["from"] == "me@gmail.com"


def test_polling_without_any_mailbox_credentials_refuses_to_start():
    got = _load({"MAIL_OUT": "resend", "MAIL_IN": "imap",
                 "RESEND_API_KEY": "re_x", "FROM_EMAIL": "c@example.com"})
    assert "IMAP_USER" in got.get("error", "")


@pytest.mark.parametrize(
    "env", [{"MAIL_OUT": "carrier-pigeon"}, {"MAIL_IN": "carrier-pigeon"},
            {"MAIL_TRANSPORT": "carrier-pigeon"}],
)
def test_an_unknown_transport_is_refused_at_startup(env):
    got = _load(dict(SMTP_ENV, **env))
    assert "must be" in got.get("error", "")
