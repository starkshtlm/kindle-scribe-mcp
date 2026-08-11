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
import contextlib
import email
import imaplib
import json
import os
import re
import time
from email.header import decode_header, make_header
from email.message import Message
from pathlib import Path

IMAP_HOST = os.environ.get("IMAP_HOST", "")
IMAP_PORT = int(os.environ.get("IMAP_PORT", "993"))
IMAP_FOLDER = os.environ.get("IMAP_FOLDER", "INBOX")
POLL_SECONDS = int(os.environ.get("IMAP_POLL_SECONDS", "60"))
# A mailbox holds unrelated mail; only look at what could be a Kindle export.
SENDER_FILTER = 'FROM "amazon"'
MAX_PER_POLL = 10
# How far back a fresh install looks. IMAP SINCE has day resolution, so this is
# "from yesterday's date", which is deliberately generous: better a couple of
# extra candidates at setup than an empty window for someone who shared a
# document just before running it. Without a bound, a first run against a
# mailbox with years of Kindle exports would import all of them.
COLD_START_DAYS = 1


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


def read_state(path: Path) -> dict:
    if path.exists():
        with contextlib.suppress(ValueError, OSError):
            state = json.loads(path.read_text())
            if isinstance(state, dict):
                return state
    return {}


def write_state(path: Path, folder: str, uidvalidity: int, last_uid: int) -> None:
    with contextlib.suppress(OSError):
        path.write_text(json.dumps({
            "folder": folder,
            "uidvalidity": uidvalidity,
            "last_settled_uid": last_uid,
        }))


def _uidvalidity(imap: imaplib.IMAP4_SSL, folder: str) -> int:
    """UIDVALIDITY changes when the server renumbers a folder; UIDs from before
    the change mean nothing after it."""
    status, data = imap.status(f'"{folder}"', "(UIDVALIDITY)")
    if status != "OK" or not data:
        return 0
    found = re.search(rb"UIDVALIDITY\s+(\d+)", data[0] or b"")
    return int(found.group(1)) if found else 0


def _search_criteria(last_uid: int | None) -> str:
    if last_uid:
        return f"UID {last_uid + 1}:* {SENDER_FILTER}"
    cutoff = time.strftime("%d-%b-%Y", time.gmtime(time.time() - COLD_START_DAYS * 86400))
    return f'SINCE {cutoff} {SENDER_FILTER}'


def fetch_candidates(user: str, password: str, state: dict) -> tuple[list, int, int]:
    """Return (messages, uidvalidity, checkpoint) — messages oldest first.

    The mailbox is opened read-only and bodies are read with BODY.PEEK[], so
    nothing here can change a flag. Reading with RFC822 would set \\Seen as a
    side effect even without asking, which is why it is not used.
    """
    with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, timeout=60) as imap:
        imap.login(user, password)
        uidvalidity = _uidvalidity(imap, IMAP_FOLDER)
        last_uid = state.get("last_settled_uid")
        if state.get("uidvalidity") not in (None, uidvalidity):
            # The folder was renumbered. Fall back to the cold-start window and
            # let the Message-ID replay guard absorb anything already stored;
            # it keeps 24h of history, which is exactly this window.
            print("mailbox: UIDVALIDITY changed, rescanning recent mail",
                  flush=True)
            last_uid = None
        imap.select(IMAP_FOLDER, readonly=True)
        status, data = imap.uid("SEARCH", None, _search_criteria(last_uid))
        if status != "OK" or not data or not data[0]:
            return [], uidvalidity, last_uid or 0
        # A "UID n:*" range always matches the highest UID in the folder, even
        # when it is below n. Without this filter every quiet poll would hand
        # back the newest mail again.
        floor = last_uid or 0
        uids = sorted(int(u) for u in data[0].split())
        uids = [u for u in uids if u > floor][:MAX_PER_POLL]
        out = []
        for uid in uids:
            status, payload = imap.uid("FETCH", str(uid), "(BODY.PEEK[])")
            if status == "OK" and payload and isinstance(payload[0], tuple):
                out.append((uid, payload[0][1]))
        return out, uidvalidity, floor


async def poll_forever(store_document, already_processed, mark_processed,
                       user: str, password: str, state_path: Path,
                       status) -> None:
    """Check the mailbox on a timer until the app shuts down.

    Dependencies are passed in rather than imported so this module never
    reaches back into app.py — the trust boundary stays in one place.

    Progress is a UID checkpoint rather than the \\Seen flag: a mail the user
    already opened on their phone must still be imported, and the bridge must
    not change what is read in someone's mailbox to keep track of its own work.
    """
    print(
        f"mailbox transport: polling {IMAP_HOST} every {POLL_SECONDS}s",
        flush=True,
    )
    while True:
        try:
            state = read_state(state_path)
            messages, uidvalidity, checkpoint = await asyncio.to_thread(
                fetch_candidates, user, password, state
            )
            for uid, raw in messages:
                mail = to_resend_shape(raw)
                key = mail.get("message_id") or f"uid-{uidvalidity}-{uid}"
                if not already_processed(key):
                    result = await store_document(mail)
                    if "error" in result:
                        # Stop the batch without advancing: the next poll has
                        # to see this mail again, and everything after it is
                        # newer, so nothing is skipped by waiting.
                        raise RuntimeError(f"storing uid {uid}: {result['error']}")
                    if "stored" in result:
                        mark_processed(key)
                        status.document_imported()
                checkpoint = uid
                write_state(state_path, IMAP_FOLDER, uidvalidity, checkpoint)
            status.poll_succeeded(IMAP_FOLDER, uidvalidity, checkpoint)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # keep polling through transient failures
            status.poll_failed(exc)
            print(f"mailbox poll failed: {type(exc).__name__}: {exc}", flush=True)
        await asyncio.sleep(POLL_SECONDS)
