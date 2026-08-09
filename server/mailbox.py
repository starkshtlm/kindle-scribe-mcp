"""Poll an ordinary mailbox over IMAP for Amazon's Kindle export mails.

This is the no-domain path: instead of Resend delivering a webhook, the bridge
logs into the user's own mailbox and looks for the export notification itself.
No domain, no DNS, no MX record, no public HTTPS — the bridge does not even
need to be reachable from the internet for the mail leg to work.

The whole point of this module is the adapter: it turns a raw RFC822 message
into exactly the dict shape Resend's API returns, so every downstream check in
app.py — recipient, DKIM/SPF, link validation, replay — is reused unchanged.
Security logic lives in app.store_document and must not be duplicated here.
"""

import asyncio
import email
import imaplib
import os
from email.header import decode_header, make_header
from email.message import Message

IMAP_HOST = os.environ.get("IMAP_HOST", "")
IMAP_PORT = int(os.environ.get("IMAP_PORT", "993"))
IMAP_FOLDER = os.environ.get("IMAP_FOLDER", "INBOX")
POLL_SECONDS = int(os.environ.get("IMAP_POLL_SECONDS", "60"))
# A mailbox holds unrelated mail; only look at what could be a Kindle export.
SEARCH = '(UNSEEN FROM "amazon")'
MAX_PER_POLL = 10


def _decode(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except (UnicodeDecodeError, LookupError, ValueError):
        return value


def _body(message: Message, subtype: str) -> str:
    """Concatenate every text/<subtype> part, tolerating odd encodings."""
    chunks = []
    for part in message.walk():
        if part.get_content_type() != f"text/{subtype}":
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            chunks.append(payload.decode(charset, errors="replace"))
        except LookupError:
            chunks.append(payload.decode("utf-8", errors="replace"))
    return "\n".join(chunks)


def to_resend_shape(raw: bytes) -> dict:
    """Adapt a raw message to the dict Resend's receiving API returns.

    Header names are lowercased and repeated headers are kept as lists, in
    arrival order — the first Authentication-Results is the one our own
    provider wrote, and sender_is_authentic trusts only that one.

    DKIM-Signature is dropped on purpose. It is part of the message, so anyone
    who can mail this address can write `d=amazon.com` into it; it is proof of
    nothing without verifying the signature, which we do not do. Over Resend it
    survives as a fallback because Resend's MX accepted the mail upstream.
    """
    message = email.message_from_bytes(raw)
    headers: dict[str, object] = {}
    for key, value in message.items():
        key = key.lower()
        if key == "dkim-signature":
            continue
        if key in headers:
            existing = headers[key]
            headers[key] = (existing if isinstance(existing, list) else [existing]) + [
                value
            ]
        else:
            headers[key] = value

    recipients = [a for a in (message.get_all("to") or []) if a]
    delivered_to = [a for a in (message.get_all("delivered-to") or []) if a]
    return {
        "from": _decode(message.get("from")),
        "to": [_decode(a) for a in recipients],
        # Providers record the true envelope recipient here, which survives
        # forwarding better than the To header.
        "received_for": [_decode(a) for a in delivered_to],
        "cc": [_decode(a) for a in (message.get_all("cc") or []) if a],
        "subject": _decode(message.get("subject")),
        "created_at": _decode(message.get("date")),
        "message_id": _decode(message.get("message-id")),
        "html": _body(message, "html"),
        "text": _body(message, "plain"),
        "headers": headers,
    }


def _fetch_unseen(user: str, password: str) -> list[tuple[bytes, bytes]]:
    """Return (uid, raw message) for candidate mails, newest handled first."""
    with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, timeout=60) as imap:
        imap.login(user, password)
        imap.select(IMAP_FOLDER)
        status, data = imap.search(None, SEARCH)
        if status != "OK" or not data or not data[0]:
            return []
        uids = data[0].split()[:MAX_PER_POLL]
        out = []
        for uid in uids:
            status, payload = imap.fetch(uid, "(RFC822)")
            if status == "OK" and payload and isinstance(payload[0], tuple):
                out.append((uid, payload[0][1]))
        return out


def _mark_seen(user: str, password: str, uids: list[bytes]) -> None:
    if not uids:
        return
    with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, timeout=60) as imap:
        imap.login(user, password)
        imap.select(IMAP_FOLDER)
        for uid in uids:
            imap.store(uid, "+FLAGS", "\\Seen")


async def poll_forever(store_document, already_processed, mark_processed,
                       user: str, password: str) -> None:
    """Check the mailbox on a timer until the app shuts down.

    Dependencies are passed in rather than imported so this module never
    reaches back into app.py — the trust boundary stays in one place.
    """
    print(
        f"mailbox transport: polling {IMAP_HOST} every {POLL_SECONDS}s",
        flush=True,
    )
    while True:
        try:
            messages = await asyncio.to_thread(_fetch_unseen, user, password)
            handled = []
            for uid, raw in messages:
                mail = to_resend_shape(raw)
                key = mail.get("message_id") or f"uid-{uid.decode()}"
                if already_processed(key):
                    handled.append(uid)
                    continue
                result = await store_document(mail)
                # Leave a failed fetch unseen so the next poll retries it; an
                # ignored mail is settled and should not be looked at again.
                if "stored" in result:
                    mark_processed(key)
                    handled.append(uid)
                elif "ignored" in result:
                    handled.append(uid)
            await asyncio.to_thread(_mark_seen, user, password, handled)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # keep polling through transient failures
            print(f"mailbox poll failed: {type(exc).__name__}: {exc}", flush=True)
        await asyncio.sleep(POLL_SECONDS)
