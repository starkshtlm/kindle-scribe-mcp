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

os.environ.setdefault("MCP_TOKEN", "testmcptoken")
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


# --- SMTP submission --------------------------------------------------------


def test_starttls_is_used_on_the_submission_port(monkeypatch):
    """465 is TLS from the first byte, 587 upgrades. Hosting providers block
    465 routinely (Hetzner does), so only supporting it means sending times out
    with no explanation on the machines people deploy to."""
    calls = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            calls.append(("plain", host, port))

        def starttls(self):
            calls.append(("starttls",))

        def close(self):
            pass

    def fake_ssl(host, port, timeout=None):
        calls.append(("ssl", host, port))
        return object()

    monkeypatch.setattr(app.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(app.smtplib, "SMTP_SSL", fake_ssl)
    monkeypatch.setattr(app, "SMTP_HOST", "smtp.example.com")

    monkeypatch.setattr(app, "SMTP_PORT", 465)
    app.smtp_connection()
    assert calls == [("ssl", "smtp.example.com", 465)]

    calls.clear()
    monkeypatch.setattr(app, "SMTP_PORT", 587)
    app.smtp_connection()
    assert calls == [("plain", "smtp.example.com", 587), ("starttls",)]


def test_a_server_refusing_starttls_is_not_used_in_the_clear(monkeypatch):
    class RefusingSMTP:
        def __init__(self, host, port, timeout=None):
            pass

        def starttls(self):
            raise app.smtplib.SMTPException("not supported")

        def close(self):
            pass

    monkeypatch.setattr(app.smtplib, "SMTP", RefusingSMTP)
    monkeypatch.setattr(app, "SMTP_PORT", 587)
    with pytest.raises(RuntimeError, match="clear"):
        app.smtp_connection()


def test_every_setting_the_code_reads_is_documented():
    """Documentation drifts silently; this makes it fail loudly instead. A new
    env var must appear in .env.example — as a key or in the prose above it —
    before it can be merged."""
    import re as _re
    from pathlib import Path

    server = Path(app.__file__).resolve().parent
    code = (server / "app.py").read_text() + (server / "mailbox.py").read_text()
    used = set(_re.findall(r'(?:os\.environ\.get|required_env)\(\s*"([A-Z_]+)"', code))
    used.discard("PATH")  # inherited, not a setting of ours
    documented = (server.parent / ".env.example").read_text()
    missing = sorted(name for name in used if name not in documented)
    assert not missing, f"undocumented settings: {missing}"


# --- provider presets -------------------------------------------------------
# setup.sh is the only place most people ever configure a provider, so a wrong
# port there is indistinguishable from a broken bridge. These pin the presets
# to what each provider actually offers.


PROVIDER_PRESETS = [
    ("gmail.com", "smtp.gmail.com", "465", "imap.gmail.com"),
    ("icloud.com", "smtp.mail.me.com", "587", "imap.mail.me.com"),
    ("fastmail.com", "smtp.fastmail.com", "465", "imap.fastmail.com"),
    ("yahoo.com", "smtp.mail.yahoo.com", "465", "imap.mail.yahoo.com"),
]


def _setup_sh() -> str:
    from pathlib import Path
    return (Path(app.__file__).resolve().parent.parent / "setup.sh").read_text()


@pytest.mark.parametrize("domain,smtp,port,imap", PROVIDER_PRESETS)
def test_provider_presets_carry_host_and_port(domain, smtp, port, imap):
    """iCloud shipped with 465 because the port was hardcoded once for
    everyone; it only offers STARTTLS on 587, so setup produced an .env that
    could never send."""
    import re as _re
    text = _setup_sh()
    branch = _re.search(rf"^\s*{_re.escape(domain)}[|)].*?;;", text, _re.M | _re.S)
    assert branch, f"no preset branch for {domain}"
    body = branch.group(0)
    assert f"SMTP_HOST={smtp}" in body
    assert f"SMTP_PORT={port}" in body
    assert f"IMAP_HOST={imap}" in body


def test_setup_does_not_pin_one_port_for_every_provider():
    assert "SMTP_PORT=${SMTP_PORT:-465}" in _setup_sh()


def test_outlook_is_not_sent_to_a_path_that_also_uses_smtp():
    """Options 1 and 2 both send over SMTP, so pointing an Outlook user at
    option 2 sends them back into the same wall."""
    import re as _re
    text = _setup_sh()
    branch = _re.search(r"^\s*outlook\.com[|)].*?;;", text, _re.M | _re.S).group(0)
    assert "option 3" in branch
    assert "option 2" not in branch or "so neither" in branch


def test_provider_matching_is_case_insensitive():
    """Addresses are case-insensitive; a preset must not need the shift key."""
    assert "tr '[:upper:]' '[:lower:]'" in _setup_sh()


@pytest.mark.parametrize(
    "security,port,expected",
    [("", 465, "ssl"), ("", 587, "plain"), ("ssl", 587, "ssl"),
     ("starttls", 465, "plain")],
)
def test_smtp_security_overrides_the_port_guess(monkeypatch, security, port, expected):
    calls = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            calls.append("plain")

        def starttls(self):
            pass

    monkeypatch.setattr(app.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(app.smtplib, "SMTP_SSL",
                        lambda *a, **k: calls.append("ssl"))
    monkeypatch.setattr(app, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(app, "SMTP_PORT", port)
    monkeypatch.setattr(app, "SMTP_SECURITY", security)
    app.smtp_connection()
    assert calls == [expected]


# --- IMAP import ------------------------------------------------------------
# Progress is a UID checkpoint, not the \Seen flag: a mail the user already
# opened on their phone must still arrive, and the bridge must never change
# what is read in someone's mailbox to keep track of its own work.


class FakeIMAP:
    """Enough of imaplib to exercise the poll loop without a network."""

    def __init__(self, messages, uidvalidity=100):
        self.messages = dict(messages)  # uid -> raw bytes
        self.uidvalidity = uidvalidity
        self.selected_readonly = None
        self.searches = []
        self.flag_calls = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        return "OK", [b""]

    def status(self, folder, what):
        return "OK", [f"INBOX (UIDVALIDITY {self.uidvalidity})".encode()]

    def select(self, folder, readonly=False):
        self.selected_readonly = readonly
        return "OK", [b"1"]

    def store(self, *a, **k):  # pragma: no cover - must never be called
        self.flag_calls.append(a)
        raise AssertionError("the bridge must not change flags")

    def uid(self, command, *args):
        if command == "SEARCH":
            criteria = args[-1]
            self.searches.append(criteria)
            uids = sorted(self.messages)
            if criteria.startswith("UID "):
                low = int(criteria.split()[1].split(":")[0])
                hit = [u for u in uids if u >= low]
                # An IMAP "n:*" range always matches the highest UID even when
                # it is below n. Reproduce that, because the code must survive
                # it: this is what caused every quiet poll to re-import.
                if not hit and uids:
                    hit = [uids[-1]]
                uids = hit
            return "OK", [" ".join(str(u) for u in uids).encode()]
        if command == "FETCH":
            uid = int(args[0])
            return "OK", [(b"1 (BODY[] {1})", self.messages[uid])]
        raise AssertionError(command)


def _run_poll(fake, tmp_path, stored, monkeypatch, seen=None):
    """One pass of the poll loop against a fake server."""
    import asyncio
    import mailbox as mb

    seen = set() if seen is None else seen
    monkeypatch.setattr(mb.imaplib, "IMAP4_SSL", lambda *a, **k: fake)
    monkeypatch.setattr(mb, "POLL_SECONDS", 0)

    class Stop(Exception):
        pass

    async def sleep(_):
        raise Stop

    monkeypatch.setattr(mb.asyncio, "sleep", sleep)

    async def store(mail):
        stored.append(mail)
        return {"stored": mail.get("message_id", "x")}

    status = importlib.import_module("status").MailboxStatus()
    with contextlib_suppress(Stop):
        asyncio.run(mb.poll_forever(
            store, lambda k: k in seen, seen.add,
            "u", "p", tmp_path / ".imap-state.json", status,
        ))
    return status


def contextlib_suppress(exc):
    import contextlib
    return contextlib.suppress(exc)


READ_ALREADY = RAW_AMAZON  # the flag state is irrelevant now; that is the point


def test_an_already_read_mail_is_still_imported(tmp_path, monkeypatch):
    """Opening Amazon's mail on your phone used to hide it from the bridge
    forever, because the search filtered on UNSEEN."""
    fake = FakeIMAP({7: READ_ALREADY})
    stored = []
    _run_poll(fake, tmp_path, stored, monkeypatch)
    assert len(stored) == 1


def test_the_mailbox_is_opened_read_only_and_no_flag_is_touched(tmp_path, monkeypatch):
    fake = FakeIMAP({7: RAW_AMAZON})
    _run_poll(fake, tmp_path, [], monkeypatch)
    assert fake.selected_readonly is True
    assert fake.flag_calls == []


def test_a_quiet_poll_does_not_reimport_the_newest_mail(tmp_path, monkeypatch):
    """"UID n:*" still matches the highest UID when it is below n, so without a
    local filter every idle poll would hand back the same document."""
    fake = FakeIMAP({7: RAW_AMAZON})
    first = []
    _run_poll(fake, tmp_path, first, monkeypatch)
    second = []
    _run_poll(fake, tmp_path, second, monkeypatch)
    assert len(first) == 1 and second == []


def test_the_checkpoint_survives_a_restart(tmp_path, monkeypatch):
    fake = FakeIMAP({7: RAW_AMAZON})
    _run_poll(fake, tmp_path, [], monkeypatch)
    import json as _json
    state = _json.loads((tmp_path / ".imap-state.json").read_text())
    assert state["last_settled_uid"] == 7 and state["uidvalidity"] == 100


def test_a_failure_does_not_advance_past_the_mail(tmp_path, monkeypatch):
    """The next poll has to see it again; everything after it is newer, so
    waiting skips nothing."""
    import asyncio
    import mailbox as mb

    fake = FakeIMAP({7: RAW_AMAZON, 8: RAW_AMAZON})
    monkeypatch.setattr(mb.imaplib, "IMAP4_SSL", lambda *a, **k: fake)

    async def store(mail):
        return {"error": "download failed"}

    status = importlib.import_module("status").MailboxStatus()
    state_file = tmp_path / ".imap-state.json"

    async def one_pass():
        messages, uidvalidity, checkpoint = await asyncio.to_thread(
            mb.fetch_candidates, "u", "p", mb.read_state(state_file)
        )
        assert messages, "expected candidates"
        try:
            for uid, raw in messages:
                result = await store(mb.to_resend_shape(raw))
                if "error" in result:
                    raise RuntimeError("stop")
                mb.write_state(state_file, "INBOX", uidvalidity, uid)
        except RuntimeError:
            pass

    asyncio.run(one_pass())
    assert not state_file.exists()
    assert status.last_settled_uid is None


def test_a_renumbered_folder_rescans_without_duplicating(tmp_path, monkeypatch):
    fake = FakeIMAP({7: RAW_AMAZON})
    seen = set()
    _run_poll(fake, tmp_path, [], monkeypatch, seen=seen)
    fake.uidvalidity = 999  # server renumbered the folder
    fake.messages = {3: RAW_AMAZON}  # same mail, new uid
    again = []
    _run_poll(fake, tmp_path, again, monkeypatch, seen=seen)
    assert again == [], "Message-ID dedupe should absorb the rescan"


def test_a_cold_start_only_looks_at_the_recent_window(tmp_path, monkeypatch):
    fake = FakeIMAP({7: RAW_AMAZON})
    _run_poll(fake, tmp_path, [], monkeypatch)
    assert fake.searches[0].startswith("SINCE "), fake.searches
    assert 'FROM "amazon"' in fake.searches[0]


# --- status endpoint and client guidance ------------------------------------


def _client():
    from fastapi.testclient import TestClient
    return TestClient(app.app)


def test_status_requires_the_bridge_token():
    assert _client().get("/status").status_code == 401


def test_status_never_returns_a_secret():
    """It reports what is configured and what happened, never a credential."""
    body = _client().get(
        "/status", headers={"Authorization": f"Bearer {app.BRIDGE_TOKEN}"}
    ).text
    for secret in (app.BRIDGE_TOKEN, app.MCP_TOKEN, app.RESEND_API_KEY,
                   app.SMTP_PASSWORD, app.WEBHOOK_SECRET):
        if secret:
            assert secret not in body, "a secret reached the status endpoint"


def test_status_reports_the_configured_directions():
    body = _client().get(
        "/status", headers={"Authorization": f"Bearer {app.BRIDGE_TOKEN}"}
    ).json()
    assert body["mail_out"] == app.MAIL_OUT and body["mail_in"] == app.MAIL_IN


def test_mailbox_status_starts_out_never_connected():
    from status import MailboxStatus
    fresh = MailboxStatus()
    assert fresh.ever_connected is False
    assert fresh.as_dict()["checkpoint"]["last_settled_uid"] is None


def test_a_failed_poll_is_recorded_and_truncated():
    from status import MailboxStatus
    fresh = MailboxStatus()
    fresh.poll_failed(ValueError("x" * 500))
    assert fresh.consecutive_failures == 1
    assert len(fresh.as_dict()["last_error"]) <= 200


def test_the_server_tells_clients_how_the_loop_works():
    """Codex reads the instructions field and uses the first 512 characters
    when deciding how to use the server, so the loop has to be complete before
    the caveats start."""
    instructions = app.mcp.instructions or ""
    assert instructions, "no MCP instructions set"
    opening = instructions[:512]
    for word in ("send_to_scribe", "list_annotated", "get_annotated",
                 "ack_annotated"):
        assert word in opening, f"{word} missing from the first 512 characters"


# --- packaging --------------------------------------------------------------
# Installing should mean pulling a published image, not compiling weasyprint on
# a laptop. These keep the pieces of that from drifting apart.


def _repo_root():
    from pathlib import Path
    return Path(app.__file__).resolve().parent.parent


def test_every_requirement_is_pinned_in_the_lock():
    """The lock is what the image installs; a package only in the ranges file
    would be resolved at build time and differ between builds."""
    import re as _re
    root = _repo_root()
    named = _re.findall(r"^([A-Za-z0-9_.\-]+)",
                        (root / "server" / "requirements.txt").read_text(), _re.M)
    lock = (root / "server" / "requirements.lock").read_text().lower()
    missing = [n for n in named if f"\n{n.lower()}==" not in "\n" + lock]
    assert not missing, f"not pinned in requirements.lock: {missing}"


def test_the_image_installs_the_lock_not_the_ranges():
    assert "requirements.lock" in (_repo_root() / "Dockerfile").read_text()


def test_compose_defaults_to_the_version_being_released():
    """A compose file pointing at a tag that was never published gives every
    new user 'manifest unknown' as their first experience."""
    import json as _json
    import re as _re
    root = _repo_root()
    compose = (root / "docker-compose.yml").read_text()
    default = _re.search(r"kindle-scribe-mcp:\$\{SCRIBE_VERSION:-(v[0-9.]+)\}",
                         compose)
    assert default, "compose does not pin a default image version"
    plugin = _json.loads(
        (root / "plugin" / ".claude-plugin" / "plugin.json").read_text())["version"]
    assert default.group(1) == f"v{plugin}", (
        f"compose default {default.group(1)} != manifest v{plugin}")


def test_production_compose_keeps_the_container_hardened():
    compose = (_repo_root() / "docker-compose.yml").read_text()
    for setting in ("read_only: true", "cap_drop", "no-new-privileges"):
        assert setting in compose, f"{setting} disappeared from docker-compose.yml"


@pytest.mark.parametrize(
    "port,override,expected",
    [(465, "", "ssl"), (587, "", "starttls"), (2525, "", "starttls"),
     (587, "ssl", "ssl"), (465, "starttls", "starttls"), (465, "SSL", "ssl")],
)
def test_submission_mode_is_shared_by_server_and_cli(port, override, expected):
    """./scribe doctor must test the same connection the bridge makes, so the
    rule lives in one module both import."""
    from mailmode import submission_mode
    assert submission_mode(port, override) == expected


def test_the_mcp_pin_cannot_be_widened_by_a_bot():
    """mcp 2.0 moved the module structure and mcp.server.fastmcp disappeared.
    The <2 pin is load-bearing, so the update has to be ignored explicitly."""
    root = _repo_root()
    assert "mcp>=1.10,<2" in (root / "server" / "requirements.txt").read_text()
    dependabot = (root / ".github" / "dependabot.yml").read_text()
    assert "dependency-name: mcp" in dependabot
    assert "version-update:semver-major" in dependabot


# --- scribe connect ---------------------------------------------------------
# Editing someone's client configuration is the one thing here that touches a
# file we do not own. It must add our server without disturbing theirs.


def _cli():
    import importlib.util
    from importlib.machinery import SourceFileLoader
    path = str(_repo_root() / "scribe")
    spec = importlib.util.spec_from_loader("scribecli",
                                           SourceFileLoader("scribecli", path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OTHER_SERVERS = """[mcp_servers.something-else]
command = "other"
args = ["x"]

[history]
persistence = "save-all"
"""


def test_connect_leaves_other_servers_alone():
    cli = _cli()
    updated, action = cli.upsert_codex(OTHER_SERVERS, "https://h/tok/mcp")
    assert action == "added"
    assert "[mcp_servers.something-else]" in updated
    assert 'persistence = "save-all"' in updated
    assert 'url = "https://h/tok/mcp"' in updated


def test_connect_is_idempotent():
    cli = _cli()
    once, _ = cli.upsert_codex(OTHER_SERVERS, "https://h/tok/mcp")
    twice, action = cli.upsert_codex(once, "https://h/tok/mcp")
    assert action == "unchanged" and twice == once


def test_connect_replaces_only_its_own_section_when_the_url_changes():
    cli = _cli()
    once, _ = cli.upsert_codex(OTHER_SERVERS, "https://h/old/mcp")
    changed, action = cli.upsert_codex(once, "https://h/new/mcp")
    assert action == "updated"
    assert "https://h/old/mcp" not in changed
    assert "[mcp_servers.something-else]" in changed
    assert changed.count("[mcp_servers.kindle-scribe]") == 1


def test_the_token_is_never_printed():
    """The whole URL is the credential, and connect echoes what it will write."""
    cli = _cli()
    assert cli.redact("https://host/supersecret/mcp") == "https://host/<MCP_TOKEN>/mcp"
    assert "supersecret" not in cli.redact("https://host/supersecret/mcp")
