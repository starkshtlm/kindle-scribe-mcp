"""scribe-bridge: relay documents between Claude and a Kindle Scribe by email.

Outbound: POST /send (or MCP-tool send_to_scribe) -> emails a PDF to the
          user's @kindle.com address, over SMTP (MAIL_OUT=smtp) or Resend
          (MAIL_OUT=resend).
Inbound:  Amazon's "shared from Kindle" export mail arrives either in a mailbox
          we poll over IMAP (MAIL_IN=imap) or through Resend's webhook
          (MAIL_IN=resend); either way we fetch the mail, extract the download
          link, pull the annotated PDF and store it in INBOX_DIR. Both routes
          meet in store_document, which is the whole trust boundary.
MCP:      Mounted at /<MCP_TOKEN>/mcp (streamable HTTP) so Claude chats and
          Claude Code can use the bridge as a connector. The token in the path
          is the auth — treat the whole URL as a secret.
"""

import asyncio
import base64
import contextlib
import hashlib
import hmac
import ipaddress
import json
import os
import re
import smtplib
import socket
import subprocess
import tempfile
import time
import unicodedata
from datetime import date
from email.message import EmailMessage
from email.utils import parseaddr
from html import escape as html_escape
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

RESEND_API = "https://api.resend.com"


def required_env(name: str, hint: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required env var {name} — {hint}. See .env.example.")
    return value


# The two directions are configured independently, because what they cost is
# not the same. Sending from a domain you do not own is an open relay and every
# provider refuses it, so outbound is either your own mailbox or your own
# verified domain. Receiving only needs *somewhere* the mail lands: a mailbox
# to poll, or a webhook — and Resend's free *.resend.app receiving address
# needs no domain of yours at all, just a publicly reachable bridge.
#
#   MAIL_OUT=smtp    send from a mailbox you already have (app password)
#   MAIL_OUT=resend  send from your Resend-verified domain
#   MAIL_IN=imap     poll that mailbox; nothing has to be publicly reachable
#   MAIL_IN=resend   Resend's webhook, on your domain or on *.resend.app
#
# MAIL_TRANSPORT is the older single switch and still works: "mailbox" means
# smtp+imap, "resend" means resend+resend.
LEGACY_TRANSPORTS = {"mailbox": ("smtp", "imap"), "resend": ("resend", "resend")}
MAIL_TRANSPORT = os.environ.get("MAIL_TRANSPORT", "").strip().lower()
if MAIL_TRANSPORT and MAIL_TRANSPORT not in LEGACY_TRANSPORTS:
    raise SystemExit("MAIL_TRANSPORT must be 'mailbox' or 'resend'.")
_out_default, _in_default = LEGACY_TRANSPORTS.get(MAIL_TRANSPORT, ("resend", "resend"))
MAIL_OUT = os.environ.get("MAIL_OUT", "").strip().lower() or _out_default
MAIL_IN = os.environ.get("MAIL_IN", "").strip().lower() or _in_default
if MAIL_OUT not in ("smtp", "resend"):
    raise SystemExit("MAIL_OUT must be 'smtp' or 'resend'.")
if MAIL_IN not in ("imap", "resend"):
    raise SystemExit("MAIL_IN must be 'imap' or 'resend'.")

KINDLE_EMAIL = required_env("KINDLE_EMAIL", "your device's @kindle.com address")
BRIDGE_TOKEN = required_env("BRIDGE_TOKEN", "generate with: openssl rand -hex 32")

# Receiving needs the key too: the webhook carries only metadata, so the mail
# itself is fetched from Resend's receiving API afterwards.
RESEND_API_KEY = (
    required_env("RESEND_API_KEY", "create one at resend.com/api-keys")
    if "resend" in (MAIL_OUT, MAIL_IN)
    else ""
)

if MAIL_OUT == "resend":
    FROM_EMAIL = required_env("FROM_EMAIL", "sender on your Resend-verified domain")
    SMTP_HOST = SMTP_USER = SMTP_PASSWORD = ""
    SMTP_PORT = 0
else:
    SMTP_HOST = required_env("SMTP_HOST", "e.g. smtp.gmail.com")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
    SMTP_USER = required_env("SMTP_USER", "the mailbox address you send from")
    SMTP_PASSWORD = required_env(
        "SMTP_PASSWORD", "an app password, not your account password"
    )
    # Amazon matches the approved-sender list on this address.
    FROM_EMAIL = os.environ.get("FROM_EMAIL", "").strip() or SMTP_USER

# Polling can read a different mailbox than the one we send from; both default
# to the SMTP credentials, which is the common case.
IMAP_USER = os.environ.get("IMAP_USER", "").strip() or SMTP_USER
IMAP_PASSWORD = os.environ.get("IMAP_PASSWORD", "").strip() or SMTP_PASSWORD
if MAIL_IN == "imap" and not IMAP_USER:
    raise SystemExit(
        "MAIL_IN=imap needs a mailbox to poll — set IMAP_USER and IMAP_PASSWORD "
        "(or SMTP_USER/SMTP_PASSWORD when they are the same account)."
    )
WEBHOOK_SECRET = os.environ.get("RESEND_WEBHOOK_SECRET", "")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
MCP_TOKEN = os.environ.get("MCP_TOKEN", "")
INBOX_DIR = Path(os.environ.get("INBOX_DIR", "/var/lib/scribe-bridge/inbox"))
# Hosts the MCP transport accepts. The SDK's DNS-rebinding guard rejects any
# Host header not listed here, which behind a reverse proxy means every public
# hostname must be named. "*" disables the check (fine when the secret path is
# the only entry point and a proxy terminates TLS).
MCP_ALLOWED_HOSTS = [
    h.strip() for h in os.environ.get("MCP_ALLOWED_HOSTS", "*").split(",") if h.strip()
]
INBOX_RETENTION_DAYS = int(os.environ.get("INBOX_RETENTION_DAYS", "30"))
TEMPLATE_PATH = Path(__file__).parent / "template.html"


def warn_if_inbound_is_dead() -> list[str]:
    """Both of these leave sending fully working while receiving silently
    rejects everything, which is indistinguishable from "Amazon is slow" until
    someone reads the logs days later. Say it at startup instead.

    Deliberately a warning and not SystemExit: an existing deployment that is
    happily sending should not turn into a restart loop on upgrade.
    """
    problems = []
    if not os.environ.get("RETURN_EMAIL", "").strip():
        problems.append(
            "RETURN_EMAIL is not set — every incoming document will be rejected. "
            "Set it to the address you share to from the Scribe."
        )
    if MAIL_IN == "resend" and not os.environ.get(
        "RESEND_WEBHOOK_SECRET", ""
    ).strip():
        problems.append(
            "RESEND_WEBHOOK_SECRET is not set — the webhook answers 503 and no "
            "document can arrive. Register the webhook in Resend and paste its "
            "signing secret here."
        )
    if MAIL_IN == "imap" and not os.environ.get("IMAP_HOST", "").strip():
        problems.append(
            "IMAP_HOST is not set — nothing polls for returning documents. Set it "
            "to your provider's IMAP server, e.g. imap.gmail.com."
        )
    return problems


for _problem in warn_if_inbound_is_dead():
    print(f"WARNING: {_problem}", flush=True)

# --- Inbound trust boundary -------------------------------------------------
# Resend inbound is catch-all: ANY address at the receiving domain reaches the
# webhook, and the Svix signature only proves Resend relayed the mail — not
# that Amazon sent it. Everything below re-establishes that guarantee.

# Only mail addressed here is processed (comma-separated). Required.
RETURN_EMAILS = {
    a.strip().lower()
    for a in os.environ.get("RETURN_EMAIL", "").split(",")
    if a.strip()
}
# Domains Amazon actually sends Kindle exports from, and signs with.
TRUSTED_SENDER_RE = re.compile(
    r"(^|\.)(amazon\.[a-z]{2,3}(\.[a-z]{2})?|kindle\.com|amazonses\.com)$", re.I
)
# Hosts the *first* link may point at. The mail body is attacker-controlled
# until the sender is proven, so this stays tight.
TRUSTED_LINK_HOST_RE = re.compile(
    r"(^|\.)(amazon\.[a-z]{2,3}(\.[a-z]{2})?|amazonaws\.com|media-amazon\.com"
    r"|ssl-images-amazon\.com|kindle\.com)$",
    re.I,
)
# Amazon's /gp/f.html forwards to S3, so redirects cannot simply be disabled;
# later hops are constrained by scheme + publicly-routable IP instead.
MAX_REDIRECT_HOPS = 4
MAX_DOWNLOAD_BYTES = 60 * 1024 * 1024
REPLAY_WINDOW_SECONDS = 3600
# Kept beside the inbox, never inside it: Path.glob("*.json") matches dotfiles
# (unlike glob.glob), so state stored here would be listed as a document.
REPLAY_FILE = INBOX_DIR.parent / ".seen-webhooks.json"
LEGACY_REPLAY_FILE = INBOX_DIR / ".seen-webhooks.json"
# Markdown of everything sent out, so a returning document can be paired with
# the text it was made from instead of coming back as context-free images.
OUTBOX_DIR = Path(os.environ.get("OUTBOX_DIR", str(INBOX_DIR.parent / "outbox")))
MAX_SOURCE_CHARS = 40_000

MAX_DOC_BYTES = 45 * 1024 * 1024  # Send to Kindle rejects docs over ~50 MB
MAX_PAGE_IMAGES = 8  # most pages ever rendered per get_annotated call
MCP_PAYLOAD_BUDGET = 400_000  # raw bytes; ~533 kB as base64, under claude.ai's cap

INBOX_DIR.mkdir(parents=True, exist_ok=True)
OUTBOX_DIR.mkdir(parents=True, exist_ok=True)

# Carry replay state over from the old in-inbox location so an upgrade cannot
# reopen the replay window for deliveries already seen.
if LEGACY_REPLAY_FILE.exists() and not REPLAY_FILE.exists():
    with contextlib.suppress(OSError):
        LEGACY_REPLAY_FILE.replace(REPLAY_FILE)
with contextlib.suppress(OSError):
    LEGACY_REPLAY_FILE.unlink(missing_ok=True)


# Exactly what store_document mints: a unix timestamp, a dash, and a slug.
# Checking the shape beats blocking "/", which misses the Windows separator —
# and the server is meant to run locally, on Windows too.
ITEM_ID_RE = re.compile(r"[0-9]{10,}-[a-z0-9-]{1,60}")


def valid_item_id(item_id: str) -> bool:
    return bool(ITEM_ID_RE.fullmatch(item_id or ""))


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return text[:60] or "document"


def remember_source(title: str, markdown: str) -> str:
    """Keep the text a document was rendered from, keyed by the filename slug
    Amazon echoes back in its export subject."""
    slug = slugify(title)
    with contextlib.suppress(OSError):
        (OUTBOX_DIR / f"{slug}.json").write_text(
            json.dumps(
                {"slug": slug, "title": title, "markdown": markdown,
                 "sent_at": int(time.time())},
                ensure_ascii=False,
            )
        )
    return slug


def find_source(document_name: str) -> dict | None:
    """Match a returning document to what we sent. Amazon truncates long
    filenames, so fall back to a prefix match."""
    slug = slugify(document_name)
    exact = OUTBOX_DIR / f"{slug}.json"
    if exact.exists():
        with contextlib.suppress(ValueError, OSError):
            return json.loads(exact.read_text())
    candidates = [
        p for p in OUTBOX_DIR.glob("*.json")
        if p.stem.startswith(slug[:40]) or slug.startswith(p.stem[:40])
    ]
    if len(candidates) == 1:
        with contextlib.suppress(ValueError, OSError):
            return json.loads(candidates[0].read_text())
    return None


def notify_rejection(reason: str) -> None:
    """Rejections must never fail silently — a false positive has to be visible
    immediately, not discovered later as a document that never arrived."""
    print(f"REJECTED inbound mail: {reason}", flush=True)
    if not NTFY_TOPIC:
        return
    try:
        httpx.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            content=f"Rejected inbound mail: {reason}".encode(),
            headers={"Title": "Kindle Scribe", "Tags": "warning"},
            timeout=15,
        )
    except httpx.HTTPError:
        pass


def domain_of(address: str) -> str:
    """The domain of a single address. parseaddr is what stops a display name
    from passing itself off as the address: in
    `"kindle@amazon.com" <evil@attacker.test>` the sender is attacker.test."""
    _, addr = parseaddr(address or "")
    return addr.rpartition("@")[2].strip().lower().rstrip(".")


def is_trusted_domain(domain: str) -> bool:
    return bool(domain) and bool(TRUSTED_SENDER_RE.search(domain))


# Only the labelled fields of an Authentication-Results header count. The free
# text around them ("domain of amazon.com designates ...") is written by
# whoever sent the mail, so matching on that would trust the attacker's prose.
DKIM_PASS_RE = re.compile(
    r"dkim\s*=\s*pass[^;]*?header\.(?:d|i|from)\s*=\s*<?(?:[^@\s;<>]*@)?"
    r"([A-Za-z0-9.-]+)",
    re.I,
)
SPF_PASS_RE = re.compile(
    r"spf\s*=\s*pass[^;]*?(?:smtp\.mailfrom|envelope-from)\s*=\s*<?(?:[^@\s;<>]*@)?"
    r"([A-Za-z0-9.-]+)",
    re.I,
)
ENVELOPE_RE = re.compile(
    r"(?:smtp\.mailfrom|envelope-from)\s*=\s*<?(?:[^@\s;<>]*@)?([A-Za-z0-9.-]+)", re.I
)


def _topmost(value: object) -> str:
    """The first copy of a repeated header. Receiving servers prepend theirs,
    so the first Authentication-Results is the one our own provider wrote —
    any others travelled with the message and prove nothing."""
    if isinstance(value, list):
        value = value[0] if value else ""
    if isinstance(value, dict):
        value = value.get("value", "")
    return str(value or "")


def verified_domains(headers: dict) -> list[str]:
    """Domains a receiving mail server said it verified for this message."""
    auth = _topmost(headers.get("authentication-results"))
    found = DKIM_PASS_RE.findall(auth) + SPF_PASS_RE.findall(auth)
    spf = _topmost(headers.get("received-spf"))
    if spf.strip().lower().startswith("pass"):
        found += ENVELOPE_RE.findall(spf)
    return [d.strip().rstrip(".").lower() for d in found]


def sender_is_authentic(email: dict) -> tuple[bool, str]:
    """Require a trusted From domain *and* a verification result for it from a
    server we trust. A From header on its own is trivially forged — and so is
    a DKIM-Signature header, which carries no proof by itself; it is consulted
    only as a fallback for Resend, whose MX accepted the message upstream. The
    mailbox transport strips it, because over IMAP the whole message including
    that header is written by whoever mailed the user."""
    from_domain = domain_of(str(email.get("from", "")))
    if not is_trusted_domain(from_domain):
        return False, f"untrusted sender domain {from_domain or '(missing)'}"

    headers = {str(k).lower(): v for k, v in (email.get("headers") or {}).items()}

    for domain in verified_domains(headers):
        if is_trusted_domain(domain):
            return True, f"verified sender {domain}"

    dkim_domains = []
    dkim = headers.get("dkim-signature")
    for entry in dkim if isinstance(dkim, list) else [dkim]:
        if isinstance(entry, dict):
            dkim_domains.append(str(entry.get("params", {}).get("d", "")).lower())
        elif isinstance(entry, str):
            found = re.search(r"[;\s]d=([A-Za-z0-9.-]+)", entry)
            if found:
                dkim_domains.append(found.group(1).lower())
    trusted_dkim = next((d for d in dkim_domains if d and is_trusted_domain(d)), "")
    if trusted_dkim:
        return True, f"DKIM d={trusted_dkim}"
    return False, "no receiving server verified this sender"


def addressed_to_us(email: dict) -> tuple[bool, str]:
    if not RETURN_EMAILS:
        return False, "RETURN_EMAIL is not configured"
    recipients = set()
    for key in ("to", "received_for", "cc"):
        value = email.get(key)
        for item in value if isinstance(value, list) else [value]:
            if item:
                recipients.add(str(item).lower())
    hit = {r for r in recipients if any(a in r for a in RETURN_EMAILS)}
    if hit:
        return True, ", ".join(sorted(hit))
    expected = ", ".join(sorted(RETURN_EMAILS))
    got = ", ".join(sorted(recipients)) or "(none)"
    return False, f"addressed to {got} — share to {expected} instead"


def url_is_safe(url: str, first_hop: bool) -> tuple[bool, str]:
    """Block anything that could reach infrastructure instead of Amazon:
    non-HTTPS, unexpected hosts, and names resolving into private space."""
    parts = urlsplit(url)
    if parts.scheme != "https":
        return False, f"not HTTPS ({parts.scheme})"
    host = (parts.hostname or "").lower()
    if not host:
        return False, "no hostname"
    if first_hop and not TRUSTED_LINK_HOST_RE.search(host):
        return False, f"host not allowed: {host}"
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        return False, f"DNS lookup failed for {host}: {exc}"
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            return False, f"{host} resolves to non-public address {ip}"
    return True, host


def _load_seen() -> dict:
    now = int(time.time())
    seen = {}
    if REPLAY_FILE.exists():
        with contextlib.suppress(ValueError, OSError):
            seen = json.loads(REPLAY_FILE.read_text())
    return {k: v for k, v in seen.items() if now - int(v) < 86400}


def already_processed(msg_id: str) -> bool:
    """True only for deliveries that completed successfully before."""
    return msg_id in _load_seen()


def mark_processed(msg_id: str) -> None:
    """Record a delivery only once it has fully succeeded. Recording earlier
    would turn a retry-after-failure into a silently dropped document."""
    seen = _load_seen()
    seen[msg_id] = int(time.time())
    with contextlib.suppress(OSError):
        REPLAY_FILE.write_text(json.dumps(seen))


def prune_inbox() -> None:
    """Delete stored documents older than INBOX_RETENTION_DAYS (0 = keep forever)."""
    if INBOX_RETENTION_DAYS <= 0:
        return
    cutoff = time.time() - INBOX_RETENTION_DAYS * 86400
    for path in INBOX_DIR.glob("*"):
        if path.is_file() and path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)


def smtp_send_pdf(filename: str, data: bytes) -> str:
    """Send through an ordinary mailbox. Needs no domain — and the sender is
    the address the user already put on Amazon's approved list."""
    message = EmailMessage()
    message["From"] = FROM_EMAIL
    message["To"] = KINDLE_EMAIL
    # Never "convert": that makes Amazon reflow the PDF, which disables
    # write-on-page annotation on the Scribe.
    message["Subject"] = Path(filename).stem
    message.set_content("Sent via scribe-bridge.")
    message.add_attachment(
        data, maintype="application", subtype="pdf", filename=filename
    )
    with smtp_connection() as smtp:
        smtp.login(SMTP_USER, SMTP_PASSWORD)
        smtp.send_message(message)
    return "smtp"


def smtp_connection() -> smtplib.SMTP:
    """Open an encrypted submission connection.

    Port 465 speaks TLS from the first byte; 587 starts in the clear and
    upgrades with STARTTLS. Supporting only 465 is not a detail: hosting
    providers routinely block it (Hetzner blocks 465 and 25 outbound while
    leaving 587 open), so sending would time out with no explanation on the
    very machines people deploy this to.
    """
    if SMTP_PORT == 465:
        return smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=120)
    smtp = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=120)
    try:
        smtp.starttls()
    except smtplib.SMTPException:
        smtp.close()
        raise RuntimeError(
            f"{SMTP_HOST}:{SMTP_PORT} refused STARTTLS, so the password would "
            "cross the network in the clear. Use port 465, or a host that "
            "offers STARTTLS on 587."
        ) from None
    return smtp


async def send_pdf(filename: str, data: bytes) -> str:
    """Deliver a PDF to the Kindle over whichever transport is configured."""
    if len(data) > MAX_DOC_BYTES:
        raise ValueError("document too large for Kindle (max ~45 MB)")
    if MAIL_OUT == "smtp":
        return await asyncio.to_thread(smtp_send_pdf, filename, data)
    return await resend_send_pdf(filename, data)


async def resend_send_pdf(filename: str, data: bytes) -> str:
    if len(data) > MAX_DOC_BYTES:
        raise ValueError("document too large for Kindle (max ~45 MB)")
    # Subject must NOT be "convert": that would make Amazon reflow the PDF,
    # which disables write-on-page annotation on the Scribe.
    payload = {
        "from": FROM_EMAIL,
        "to": [KINDLE_EMAIL],
        "subject": Path(filename).stem,
        "text": "Skickat via scribe-bridge.",
        "attachments": [
            {"filename": filename, "content": base64.b64encode(data).decode()}
        ],
    }
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            f"{RESEND_API}/emails",
            json=payload,
            headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
        )
    if r.status_code >= 400:
        raise RuntimeError(f"resend error: {r.text}")
    return r.json().get("id", "")


# WeasyPrint fetches external resources (images, stylesheets, fonts) by
# default and has no flag to disable it, so anything that could trigger a
# fetch is removed from model-supplied content before rendering. Without this,
# markdown reaching send_to_scribe is an SSRF primitive against localhost,
# private ranges and cloud metadata — and the response would be baked into a
# PDF and mailed out.
_DROP_WITH_CONTENT = re.compile(
    r"<(script|style|iframe|object|embed|svg|math)\b.*?</\1\s*>",
    re.I | re.S,
)
_DROP_TAGS = re.compile(r"<\s*(script|style|iframe|object|embed|link|base|svg|math)\b[^>]*>", re.I)
_IMG_TAG = re.compile(r"<\s*img\b[^>]*>", re.I)
_EXTERNAL_URL_FUNC = re.compile(r"url\(\s*['\"]?(?!data:)[^)]*\)", re.I)
_EVENT_ATTR = re.compile(r"\son[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.I)
_BACKGROUND_ATTR = re.compile(r"\sbackground\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.I)


MAX_INLINE_IMAGE_BYTES = 5 * 1024 * 1024


async def inline_remote_images(html: str) -> str:
    """Fetch images referenced in the document and embed them as data: URIs.

    Sanitising alone would silently drop every illustration, so images are
    fetched here instead — but only over HTTPS to publicly-routable addresses,
    size-capped, and only when the response really is an image. Documents keep
    looking right, the renderer itself stays offline, and the resulting PDF is
    self-contained on the device.
    """
    srcs = {
        m.group(1)
        for m in re.finditer(r'<img[^>]+src\s*=\s*["\']([^"\']+)["\']', html, re.I)
        if not m.group(1).lower().startswith("data:")
    }
    if not srcs:
        return html
    # Several hosts (Wikimedia among them) reject requests without a
    # descriptive User-Agent, which would silently drop the illustration.
    headers = {
        "User-Agent": "kindle-scribe-bridge/1.0 (+https://github.com/starkshtlm/kindle-scribe-mcp)",
        "Accept": "image/*,*/*;q=0.8",
    }
    async with httpx.AsyncClient(
        timeout=20, follow_redirects=False, headers=headers
    ) as client:
        for src in srcs:
            current, data, media = src, None, "image/png"
            for _ in range(3):
                ok, _detail = url_is_safe(current, first_hop=False)
                if not ok:
                    break
                try:
                    async with client.stream("GET", current) as response:
                        if response.is_redirect:
                            location = response.headers.get("location", "")
                            if not location:
                                break
                            current = str(httpx.URL(current).join(location))
                            continue
                        media = response.headers.get("content-type", "").split(";")[0]
                        if response.status_code != 200 or not media.startswith("image/"):
                            break
                        chunks, size = [], 0
                        async for chunk in response.aiter_bytes():
                            chunks.append(chunk)
                            size += len(chunk)
                            if size > MAX_INLINE_IMAGE_BYTES:
                                chunks = []
                                break
                        data = b"".join(chunks) or None
                        break
                except httpx.HTTPError:
                    break
            if data:
                encoded = base64.b64encode(data).decode()
                html = html.replace(src, f"data:{media};base64,{encoded}")
            else:
                # Say so rather than leaving a hole the reader cannot explain.
                host = urlsplit(src).hostname or src
                html = re.sub(
                    r'<img[^>]+src\s*=\s*["\']' + re.escape(src) + r'["\'][^>]*>',
                    f'<p><em>[image could not be fetched: {host}]</em></p>',
                    html,
                    flags=re.I,
                )
    return html


def sanitize_html_for_pdf(html: str) -> str:
    """Strip everything WeasyPrint could dereference over the network.
    Inline data: images survive; remote references do not."""
    html = _DROP_WITH_CONTENT.sub("", html)
    html = _DROP_TAGS.sub("", html)
    html = _IMG_TAG.sub(
        lambda m: m.group(0) if re.search(r'src\s*=\s*["\']?data:', m.group(0), re.I) else "",
        html,
    )
    html = _EXTERNAL_URL_FUNC.sub("none", html)
    html = _EVENT_ATTR.sub("", html)
    html = _BACKGROUND_ATTR.sub("", html)
    return html


def document_html(title: str, html_body: str, meta: str) -> str:
    """Fill the template. Kept separate from rendering so the escaping below
    can be tested without invoking the PDF engine."""
    return (
        TEMPLATE_PATH.read_text()
        # The title is model-supplied and lands in <title> and <h1>, so it has
        # to be escaped: sanitize_html_for_pdf only ever saw the body, and a
        # title of `<img src="http://169.254.169.254/...">` went straight past
        # it into the renderer.
        .replace("{{TITLE}}", html_escape(title))
        .replace("{{META}}", meta)
        .replace("{{BODY}}", sanitize_html_for_pdf(html_body))
    )


def render_pdf(title: str, html_body: str, meta: str) -> bytes:
    html = document_html(title, html_body, meta)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "doc.html"
        out = Path(tmp) / "doc.pdf"
        src.write_text(html)
        subprocess.run(
            ["weasyprint", str(src), str(out)], check=True, capture_output=True,
            timeout=120
        )
        return out.read_bytes()


def list_inbox_items(only_new: bool = False) -> list[dict]:
    """Only well-formed document metadata is listed. Anything else in the
    directory -- hidden state, a half-written file -- is skipped rather than
    surfaced as a phantom document with an id nothing can open."""
    items = []
    for p in sorted(INBOX_DIR.glob("*.json"), reverse=True):
        if p.name.startswith("."):
            continue
        try:
            meta = json.loads(p.read_text())
        except (ValueError, OSError):
            continue
        if isinstance(meta, dict) and meta.get("id"):
            items.append(meta)
    if only_new:
        items = [i for i in items if not i.get("processed")]
    return items


def notify(title: str) -> None:
    if not NTFY_TOPIC:
        return
    try:
        httpx.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            content=f"Annoterat dokument mottaget: {title}".encode(),
            headers={"Title": "Kindle Scribe", "Tags": "pencil2"},
            timeout=15,
        )
    except httpx.HTTPError:
        pass


# --- MCP server (custom connector for claude.ai chats) ----------------------

mcp = None
if MCP_TOKEN:
    import markdown as md_lib
    from mcp.server.fastmcp import FastMCP
    from mcp.server.fastmcp import Image as MCPImage
    from mcp.server.transport_security import TransportSecuritySettings

    mcp = FastMCP(
        "kindle-scribe",
        stateless_http=True,
        json_response=True,
        streamable_http_path="/mcp",
        transport_security=TransportSecuritySettings(
            # The SDK has no wildcard: "*" means turn the guard off entirely.
            enable_dns_rebinding_protection="*" not in MCP_ALLOWED_HOSTS,
            allowed_hosts=MCP_ALLOWED_HOSTS,
            allowed_origins=[f"https://{h}" for h in MCP_ALLOWED_HOSTS],
        ),
    )

    @mcp.tool()
    async def send_to_scribe(title: str, content_markdown: str) -> str:
        """Send a document to the user's Kindle Scribe to read and annotate by
        hand with the stylus. The markdown is rendered to a pen-friendly PDF
        (wide writing margin, generous line spacing) and emailed to the device —
        it arrives within about a minute. Number the headings (1, 1.1, 2 ...) so
        the user's handwritten references are unambiguous on the way back."""
        body = md_lib.markdown(
            content_markdown, extensions=["tables", "fenced_code", "sane_lists"]
        )
        body = await inline_remote_images(body)
        meta = f"{date.today().isoformat()} · Sent by Claude via scribe-bridge"
        pdf = render_pdf(title, body, meta)
        slug = remember_source(title, content_markdown)
        await send_pdf(f"{slug}.pdf", pdf)
        return (
            f"Sent to {KINDLE_EMAIL} ({len(pdf) // 1024} kB). It appears on the "
            "Scribe within a minute (the device needs wifi). Remind the user: "
            "write directly on the pages with the stylus, then export via "
            "Share -> Send by email to the return address; the bridge picks it "
            "up automatically."
        )

    @mcp.tool()
    def list_annotated(only_new: bool = True) -> str:
        """List annotated documents that came back from the Kindle Scribe.
        only_new=True shows only unprocessed ones. Pass an id to get_annotated
        to see the pages and read the handwriting."""
        items = list_inbox_items(only_new)
        if not items:
            return (
                "No new annotated documents. The user has to tap "
                "Share -> Send by email on the Scribe to export; Amazon's mail "
                "can take a few minutes to arrive."
            )
        return json.dumps(items, ensure_ascii=False)

    @mcp.tool()
    def get_annotated(item_id: str, start_page: int = 1) -> list:
        """Fetch an annotated document as page images so you can read the user's
        handwritten comments. When the document was sent from here, the ORIGINAL
        TEXT comes with the first reply so you can see exactly what the
        handwriting changes; with no original it is a standalone handwritten
        note (transcribe verbatim; struck-through text means
        'delete', margin text with an arrow means 'add/replace here'). Long
        documents arrive in batches because of the payload limit: the reply
        states the page range and the total — if more pages remain, call again
        with the start_page it gives you until you have read EVERY page. Then
        acknowledge with ack_annotated."""
        pdf_path = INBOX_DIR / f"{item_id}.pdf"
        if not valid_item_id(item_id) or not pdf_path.exists():
            return ["Unknown id. Call list_annotated for valid ids."]
        info = subprocess.run(
            ["pdfinfo", str(pdf_path)], check=True, capture_output=True, text=True,
            timeout=60
        )
        total = int(re.search(r"^Pages:\s+(\d+)", info.stdout, re.M).group(1))
        start = min(max(1, start_page), total)
        end_render = min(total, start + MAX_PAGE_IMAGES - 1)
        with tempfile.TemporaryDirectory() as tmp:
            prefix = Path(tmp) / "page"
            # -gray halves payload (pen annotations are monochrome anyway),
            # -f/-l renders only the candidate range
            subprocess.run(
                ["pdftoppm", "-png", "-gray", "-r", "100",
                 "-f", str(start), "-l", str(end_render), str(pdf_path), str(prefix)],
                check=True,
                capture_output=True,
                timeout=180,
            )
            # Pack greedily until the byte budget is hit: claude.ai truncates
            # tool results around ~625 kB of JSON, base64 inflates raw bytes
            # by 4/3, so cap raw payload well below that. Always ship >= 1 page.
            images = []
            used = 0
            for p in sorted(Path(tmp).glob("page-*.png")):
                data = p.read_bytes()
                if images and used + len(data) > MCP_PAYLOAD_BUDGET:
                    break
                images.append(MCPImage(data=data, format="png"))
                used += len(data)
            end = start + len(images) - 1
            note = f"Pages {start}-{end} of {total}."
            preamble: list = []
            if start == 1:
                meta_path = INBOX_DIR / f"{item_id}.json"
                meta = {}
                if meta_path.exists():
                    with contextlib.suppress(ValueError, OSError):
                        meta = json.loads(meta_path.read_text())
                linked = find_source(meta.get("title", "")) if meta else None
                if linked:
                    preamble.append(
                        "THE ORIGINAL TEXT that was sent to the Scribe follows. "
                        "Compare the page images against it: the handwriting marks "
                        "changes to this text. Treat the original as fact and the "
                        "handwriting as instructions about what to change.\n\n"
                        "--- ORIGINAL ---\n"
                        + linked["markdown"][:MAX_SOURCE_CHARS]
                        + "\n--- END OF ORIGINAL ---"
                    )
                else:
                    preamble.append(
                        "No original is linked — this is most likely a standalone "
                        "handwritten note from the Scribe. Transcribe it and treat "
                        "the content as the user's own notes."
                    )
            if end < total:
                note += (
                    f" MORE PAGES REMAIN: call get_annotated again with "
                    f"start_page={end + 1} before you summarize."
                )
            return [*preamble, note, *images]

    @mcp.tool()
    def push_summary(message: str, title: str = "Kindle Scribe") -> str:
        """Send a short text as a push notification to the user's phone. Use it
        after interpreting an annotated document so the summary of what they
        wrote lands on their lock screen without them opening a chat. Keep it
        under ~300 characters."""
        if not NTFY_TOPIC:
            return "No ntfy topic configured; nothing sent."
        try:
            httpx.post(
                f"https://ntfy.sh/{NTFY_TOPIC}",
                content=message[:900].encode(),
                headers={"Title": title[:80], "Tags": "pencil2"},
                timeout=15,
            )
        except httpx.HTTPError as exc:
            return f"Notification failed: {exc}"
        return "Notification sent."

    @mcp.tool()
    def ack_annotated(item_id: str) -> str:
        """Mark an annotated document as fully processed so it stops being
        listed as new."""
        meta_path = INBOX_DIR / f"{item_id}.json"
        if not valid_item_id(item_id) or not meta_path.exists():
            return "Unknown id."
        meta = json.loads(meta_path.read_text())
        meta["processed"] = True
        meta_path.write_text(json.dumps(meta, ensure_ascii=False))
        return f"Acknowledged: {item_id}"


@contextlib.asynccontextmanager
async def mailbox_poller():
    """Run the IMAP poll loop for the lifetime of the app, when configured."""
    if MAIL_IN != "imap":
        yield
        return
    import mailbox as mailbox_transport

    task = asyncio.create_task(
        mailbox_transport.poll_forever(
            store_document, already_processed, mark_processed,
            IMAP_USER, IMAP_PASSWORD,
        )
    )
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    # FastAPI does not run mounted sub-apps' lifespans; the MCP session
    # manager must be started here or every MCP request 500s.
    async with mailbox_poller():
        if mcp is not None:
            async with mcp.session_manager.run():
                yield
        else:
            yield


app = FastAPI(lifespan=lifespan)
if mcp is not None:
    # Endpoint: /<token>/mcp — canonical "/mcp" suffix, secret in the middle.
    app.mount(f"/{MCP_TOKEN}", mcp.streamable_http_app())


def require_token(authorization: str | None) -> None:
    if not authorization or not hmac.compare_digest(
        authorization, f"Bearer {BRIDGE_TOKEN}"
    ):
        raise HTTPException(status_code=401, detail="bad token")


@app.get("/healthz")
def healthz():
    return {"ok": True, "mcp": mcp is not None}


@app.post("/send")
async def send_to_kindle(
    file: UploadFile = File(...), authorization: str | None = Header(None)
):
    require_token(authorization)
    # Read in chunks so an oversized upload cannot exhaust memory before the
    # size check runs.
    chunks, size = [], 0
    while chunk := await file.read(1 << 20):
        size += len(chunk)
        if size > MAX_DOC_BYTES:
            raise HTTPException(status_code=413, detail="document too large")
        chunks.append(chunk)
    data = b"".join(chunks)
    filename = file.filename or "dokument.pdf"
    try:
        resend_id = await send_pdf(filename, data)
    except ValueError as e:
        raise HTTPException(status_code=413, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"sent": filename, "to": KINDLE_EMAIL, "resend_id": resend_id}


def verify_svix(secret: str, headers, body: bytes) -> bool:
    """Minimal Svix signature check (Resend webhooks are Svix-signed)."""
    msg_id = headers.get("svix-id", "")
    timestamp = headers.get("svix-timestamp", "")
    signatures = headers.get("svix-signature", "")
    if not (msg_id and timestamp and signatures):
        return False
    key = base64.b64decode(secret.removeprefix("whsec_"))
    signed = f"{msg_id}.{timestamp}.{body.decode()}".encode()
    expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    return any(
        hmac.compare_digest(expected, sig.partition(",")[2])
        for sig in signatures.split(" ")
    )


async def fetch_received_email(email_id: str) -> dict:
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(
            f"{RESEND_API}/emails/receiving/{email_id}",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
        )
    r.raise_for_status()
    return r.json()


def extract_links(html: str, text: str) -> list[str]:
    links = re.findall(r'href="([^"]+)"', html or "")
    links += re.findall(r"https?://\S+", text or "")
    seen, out = set(), []
    for link in links:
        link = link.replace("&amp;", "&")
        if link in seen:
            continue
        seen.add(link)
        low = link.lower()
        if "amazon" not in low and "kindle" not in low:
            continue
        if any(w in low for w in ("unsubscribe", "help", "privacy", "notification_pref")):
            continue
        out.append(link)
    return out


async def fetch_pdf_safely(url: str) -> tuple[bytes | None, str]:
    """Follow Amazon's forwarder to S3 by hand, validating every hop, and
    stream the body so an oversized response cannot exhaust memory."""
    async with httpx.AsyncClient(timeout=120, follow_redirects=False) as client:
        current = url
        for hop in range(MAX_REDIRECT_HOPS):
            ok, detail = url_is_safe(current, first_hop=(hop == 0))
            if not ok:
                return None, f"hop {hop + 1}: {detail}"
            try:
                async with client.stream("GET", current) as response:
                    if response.is_redirect:
                        location = response.headers.get("location", "")
                        if not location:
                            return None, f"hop {hop + 1}: redirect without target"
                        current = str(httpx.URL(current).join(location))
                        continue
                    if response.status_code != 200:
                        return None, f"HTTP {response.status_code}"
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        chunks.append(chunk)
                        size += len(chunk)
                        if size > MAX_DOWNLOAD_BYTES:
                            return None, "exceeds the size limit"
                    data = b"".join(chunks)
                    if data[:5] != b"%PDF-":
                        return None, "response is not a PDF"
                    return data, f"{size // 1024} kB"
            except httpx.HTTPError as exc:
                return None, f"network error: {exc}"
        return None, "too many redirects"


async def store_document(email: dict) -> dict:
    """Validate a received mail and store the annotated PDF it points at.

    Every inbound transport funnels through here, so the trust boundary is
    defined exactly once: mail must be addressed to us and provably from
    Amazon before anything inside it is touched.
    """
    ok, detail = addressed_to_us(email)
    if not ok:
        notify_rejection(detail)
        return {"ignored": detail}
    ok, detail = sender_is_authentic(email)
    if not ok:
        notify_rejection(f"{detail} (from {email.get('from')})")
        return {"ignored": detail}

    subject = email.get("subject") or "document"
    # Amazon quotes the filename in the subject:
    # 'Daniel sent a file "my-plan" to you from their Kindle'. Using just the
    # filename reads better in listings and links back to the outbox. A
    # handwritten notebook arrives the same way, simply with no match.
    quoted = re.search(r'"([^"]+)"', subject)
    title = (quoted.group(1) if quoted else subject).strip()
    source = find_source(title)

    links = extract_links(email.get("html", ""), email.get("text", ""))
    pdf, why = None, "no candidate links in the mail"
    for link in links:
        pdf, why = await fetch_pdf_safely(link)
        if pdf:
            break
    if pdf is None:
        notify_rejection(f"could not fetch a PDF ({why})")
        return {"error": f"no pdf fetched: {why}"}

    item_id = f"{int(time.time())}-{slugify(title)}"
    (INBOX_DIR / f"{item_id}.pdf").write_bytes(pdf)
    (INBOX_DIR / f"{item_id}.json").write_text(
        json.dumps(
            {
                "id": item_id,
                "title": title,
                "subject": subject,
                "received_at": email.get("created_at"),
                "size": len(pdf),
                "processed": False,
                "source_slug": (source or {}).get("slug"),
                "kind": "annotated draft" if source else "handwritten note",
            },
            ensure_ascii=False,
        )
    )
    notify(title)
    prune_inbox()
    return {"stored": item_id}


@app.post("/webhook/inbound")
async def inbound_webhook(request: Request):
    # Nothing should be able to push documents in through a door this
    # deployment does not use.
    if MAIL_IN != "resend":
        raise HTTPException(status_code=404)
    body = await request.body()
    # Fail closed: without a signing secret we cannot tell Resend from anyone.
    if not WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="webhook secret not configured")
    if not verify_svix(WEBHOOK_SECRET, request.headers, body):
        raise HTTPException(status_code=401, detail="bad signature")

    timestamp = request.headers.get("svix-timestamp", "")
    try:
        if abs(int(time.time()) - int(timestamp)) > REPLAY_WINDOW_SECONDS:
            raise HTTPException(status_code=401, detail="stale signature")
    except ValueError:
        raise HTTPException(status_code=401, detail="bad timestamp")
    msg_id = request.headers.get("svix-id", "")
    if msg_id and already_processed(msg_id):
        return {"ignored": "replay"}

    try:
        event = json.loads(body)
        if event.get("type") != "email.received":
            return {"ignored": event.get("type")}
        email_id = event["data"]["email_id"] if "email_id" in event["data"] else event["data"]["id"]
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status_code=400, detail="malformed event")
    if not re.fullmatch(r"[A-Za-z0-9-]{1,64}", str(email_id)):
        raise HTTPException(status_code=400, detail="malformed email id")

    result = await store_document(await fetch_received_email(email_id))
    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])
    # Record only after success, so a retry after a failed fetch still works.
    if msg_id and "stored" in result:
        mark_processed(msg_id)
    return result


@app.get("/inbox")
def list_inbox(new: int = 0, authorization: str | None = Header(None)):
    require_token(authorization)
    return {"items": list_inbox_items(only_new=bool(new))}


@app.get("/inbox/{item_id}/file")
def get_file(item_id: str, authorization: str | None = Header(None)):
    require_token(authorization)
    path = INBOX_DIR / f"{item_id}.pdf"
    if not valid_item_id(item_id) or not path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@app.post("/inbox/{item_id}/ack")
def ack(item_id: str, authorization: str | None = Header(None)):
    require_token(authorization)
    meta_path = INBOX_DIR / f"{item_id}.json"
    if not valid_item_id(item_id) or not meta_path.exists():
        raise HTTPException(status_code=404)
    meta = json.loads(meta_path.read_text())
    meta["processed"] = True
    meta_path.write_text(json.dumps(meta, ensure_ascii=False))
    return {"acked": item_id}
