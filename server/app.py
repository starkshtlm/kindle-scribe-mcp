"""scribe-bridge: relay documents between Claude and a Kindle Scribe via Resend.

Outbound: POST /send (or MCP-tool send_to_scribe) -> emails a PDF to the
          user's @kindle.com address.
Inbound:  Resend fires POST /webhook/inbound when Amazon's "shared from
          Kindle" export mail arrives; we fetch the mail body, extract the
          download link, pull the annotated PDF and store it in INBOX_DIR.
MCP:      Mounted at /<MCP_TOKEN>/mcp (streamable HTTP) so Claude chats and
          Claude Code can use the bridge as a connector. The token in the path
          is the auth — treat the whole URL as a secret.
"""

import base64
import contextlib
import hashlib
import hmac
import ipaddress
import json
import os
import re
import socket
import subprocess
import tempfile
import time
import unicodedata
from datetime import date
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


RESEND_API_KEY = required_env("RESEND_API_KEY", "create one at resend.com/api-keys")
KINDLE_EMAIL = required_env("KINDLE_EMAIL", "your device's @kindle.com address")
FROM_EMAIL = required_env("FROM_EMAIL", "sender on your Resend-verified domain")
BRIDGE_TOKEN = required_env("BRIDGE_TOKEN", "generate with: openssl rand -hex 32")
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
TRUSTED_SENDER_DOMAINS = ("amazon.com", "kindle.com", "amazonses.com")
# Hosts the *first* link may point at. The mail body is attacker-controlled
# until the sender is proven, so this stays tight.
TRUSTED_LINK_HOST_RE = re.compile(r"(^|\.)amazon\.[a-z]{2,3}(\.[a-z]{2})?$", re.I)
# Amazon's /gp/f.html forwards to S3, so redirects cannot simply be disabled;
# later hops are constrained by scheme + publicly-routable IP instead.
MAX_REDIRECT_HOPS = 4
MAX_DOWNLOAD_BYTES = 60 * 1024 * 1024
REPLAY_WINDOW_SECONDS = 600
REPLAY_FILE = INBOX_DIR / ".seen-webhooks.json"

MAX_DOC_BYTES = 45 * 1024 * 1024  # Send to Kindle rejects docs over ~50 MB
MAX_PAGE_IMAGES = 8  # most pages ever rendered per get_annotated call
MCP_PAYLOAD_BUDGET = 400_000  # raw bytes; ~533 kB as base64, under claude.ai's cap

INBOX_DIR.mkdir(parents=True, exist_ok=True)


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return text[:60] or "document"


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
    match = re.search(r"@([A-Za-z0-9.-]+)", address or "")
    return match.group(1).lower().rstrip(".") if match else ""


def is_trusted_domain(domain: str) -> bool:
    return any(domain == d or domain.endswith(f".{d}") for d in TRUSTED_SENDER_DOMAINS)


def sender_is_authentic(email: dict) -> tuple[bool, str]:
    """Require a trusted From domain *and* a passing DKIM/SPF result for that
    domain. A From header on its own is trivially forged."""
    from_domain = domain_of(str(email.get("from", "")))
    if not is_trusted_domain(from_domain):
        return False, f"untrusted sender domain {from_domain or '(missing)'}"

    headers = email.get("headers") or {}
    lowered = {str(k).lower(): v for k, v in headers.items()}

    dkim_domains = []
    dkim = lowered.get("dkim-signature")
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

    auth = " ".join(
        str(lowered.get(k, "")) for k in ("authentication-results", "received-spf")
    ).lower()
    envelope = domain_of(auth)
    if "spf=pass" in auth or auth.strip().startswith("pass"):
        if is_trusted_domain(envelope):
            return True, f"SPF pass ({envelope})"
        return False, f"SPF pass but envelope domain {envelope or '(unknown)'}"
    return False, "neither DKIM nor SPF establishes the sender"


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
    return False, f"recipients {sorted(recipients) or '(none)'}"


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


def seen_webhook(msg_id: str) -> bool:
    """Reject replays of an already-processed Svix delivery."""
    now = int(time.time())
    seen = {}
    if REPLAY_FILE.exists():
        with contextlib.suppress(ValueError, OSError):
            seen = json.loads(REPLAY_FILE.read_text())
    seen = {k: v for k, v in seen.items() if now - int(v) < 86400}
    if msg_id in seen:
        return True
    seen[msg_id] = now
    with contextlib.suppress(OSError):
        REPLAY_FILE.write_text(json.dumps(seen))
    return False


def prune_inbox() -> None:
    """Delete stored documents older than INBOX_RETENTION_DAYS (0 = keep forever)."""
    if INBOX_RETENTION_DAYS <= 0:
        return
    cutoff = time.time() - INBOX_RETENTION_DAYS * 86400
    for path in INBOX_DIR.glob("*"):
        if path.is_file() and path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)


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


def render_pdf(title: str, html_body: str, meta: str) -> bytes:
    html = (
        TEMPLATE_PATH.read_text()
        .replace("{{TITLE}}", title)
        .replace("{{META}}", meta)
        .replace("{{BODY}}", html_body)
    )
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
    items = [
        json.loads(p.read_text()) for p in sorted(INBOX_DIR.glob("*.json"), reverse=True)
    ]
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
        meta = f"{date.today().isoformat()} · Sent by Claude via scribe-bridge"
        pdf = render_pdf(title, body, meta)
        await resend_send_pdf(f"{slugify(title)}.pdf", pdf)
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
        handwritten comments (transcribe verbatim; struck-through text means
        'delete', margin text with an arrow means 'add/replace here'). Long
        documents arrive in batches because of the payload limit: the reply
        states the page range and the total — if more pages remain, call again
        with the start_page it gives you until you have read EVERY page. Then
        acknowledge with ack_annotated."""
        pdf_path = INBOX_DIR / f"{item_id}.pdf"
        if "/" in item_id or not pdf_path.exists():
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
            if end < total:
                note += (
                    f" MORE PAGES REMAIN: call get_annotated again with "
                    f"start_page={end + 1} before you summarize."
                )
            return [note, *images]

    @mcp.tool()
    def ack_annotated(item_id: str) -> str:
        """Mark an annotated document as fully processed so it stops being
        listed as new."""
        meta_path = INBOX_DIR / f"{item_id}.json"
        if "/" in item_id or not meta_path.exists():
            return "Unknown id."
        meta = json.loads(meta_path.read_text())
        meta["processed"] = True
        meta_path.write_text(json.dumps(meta, ensure_ascii=False))
        return f"Acknowledged: {item_id}"


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    # FastAPI does not run mounted sub-apps' lifespans; the MCP session
    # manager must be started here or every MCP request 500s.
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
    data = await file.read()
    filename = file.filename or "dokument.pdf"
    try:
        resend_id = await resend_send_pdf(filename, data)
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


@app.post("/webhook/inbound")
async def inbound_webhook(request: Request):
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
    if msg_id and seen_webhook(msg_id):
        return {"ignored": "replay"}

    event = json.loads(body)
    if event.get("type") != "email.received":
        return {"ignored": event.get("type")}
    email_id = event["data"].get("email_id") or event["data"].get("id")
    email = await fetch_received_email(email_id)

    # Resend inbound is catch-all, so verify the mail was addressed to us and
    # genuinely authenticated as Amazon before touching anything inside it.
    ok, detail = addressed_to_us(email)
    if not ok:
        notify_rejection(detail)
        return {"ignored": detail}
    ok, detail = sender_is_authentic(email)
    if not ok:
        notify_rejection(f"{detail} (from {email.get('from')})")
        return {"ignored": detail}

    subject = email.get("subject") or "document"
    # Amazon export subjects look like: '"Titel" from your Kindle'
    title = re.sub(r"\s*from your kindle\s*$", "", subject, flags=re.I).strip('" ')

    links = extract_links(email.get("html", ""), email.get("text", ""))
    pdf, why = None, "no candidate links in the mail"
    for link in links:
        pdf, why = await fetch_pdf_safely(link)
        if pdf:
            break
    if pdf is None:
        notify_rejection(f"could not fetch a PDF ({why})")
        raise HTTPException(status_code=422, detail=f"no pdf fetched: {why}")

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
            },
            ensure_ascii=False,
        )
    )
    notify(title)
    prune_inbox()
    return {"stored": item_id}


@app.get("/inbox")
def list_inbox(new: int = 0, authorization: str | None = Header(None)):
    require_token(authorization)
    return {"items": list_inbox_items(only_new=bool(new))}


@app.get("/inbox/{item_id}/file")
def get_file(item_id: str, authorization: str | None = Header(None)):
    require_token(authorization)
    path = INBOX_DIR / f"{item_id}.pdf"
    if "/" in item_id or not path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@app.post("/inbox/{item_id}/ack")
def ack(item_id: str, authorization: str | None = Header(None)):
    require_token(authorization)
    meta_path = INBOX_DIR / f"{item_id}.json"
    if "/" in item_id or not meta_path.exists():
        raise HTTPException(status_code=404)
    meta = json.loads(meta_path.read_text())
    meta["processed"] = True
    meta_path.write_text(json.dumps(meta, ensure_ascii=False))
    return {"acked": item_id}
