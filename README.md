# kindle-scribe-mcp

Send documents from Claude to a Kindle Scribe, annotate them by hand with the
stylus, share them back, and have Claude read your handwriting and act on it.

Works from any Claude surface — a chat on your phone, Claude Code in the
terminal — because the bridge is an MCP server.

```
   Claude                     your server                    Amazon
┌────────────┐   send_to_    ┌──────────────┐   Resend    ┌─────────┐
│ chat / CLI │──scribe──────▶│  PDF render  │────mail────▶│ @kindle │──▶ Scribe
│            │               │              │             └─────────┘   (read +
│            │  get_         │   inbox   ◀──│◀── webhook ◀── "shared     stylus)
│            │◀─annotated────│  page images │    (Resend)   from Kindle"    │
└────────────┘               └──────────────┘                              │
        ▲                                          Share → Send by email ──┘
        └── reads your handwriting with vision
```

## What you need

- A **Kindle Scribe** (or any Kindle that supports writing on PDFs)
- An **email account you already have** — Gmail, iCloud or Outlook
- Docker

That is it. No domain, no DNS, no webhook. **About five minutes.**

## Quick start

```bash
git clone https://github.com/starkshtlm/kindle-scribe-mcp
cd kindle-scribe-mcp
./setup.sh          # pick "mailbox", paste an app password
docker compose up -d
```

Then two things `setup.sh` cannot do for you:

1. Add your own email address to Amazon's *Approved Personal Document E-mail
   List* (amazon.com/mycd → Preferences → Personal Document Settings)
2. Connect Claude Code:
   ```bash
   claude mcp add --transport http --scope user kindle-scribe \
     http://127.0.0.1:8377/<MCP_TOKEN>/mcp
   ```

Ask Claude to send something to your Kindle. Write on it. Share it back by
email to yourself — the bridge watches that mailbox and picks it up.

Works with **any MCP client**, not just Claude: Claude Code, Cursor, VS Code
agents and anything else that speaks the protocol.

### Using it from claude.ai chats

Chats on claude.ai and the mobile app need the bridge on a public HTTPS URL.
Deploy it somewhere reachable and use that hostname in the connector URL:

| Option | How |
|---|---|
| **Fly.io** (simplest) | `deploy/fly.toml.example` — HTTPS included, and Claude's connector reaches it directly |
| **Your own VPS** | `deploy/Caddyfile.example` — two lines, automatic Let's Encrypt |
| **Behind a firewall / broker cannot reach you** | `worker/` — a Cloudflare Worker relay, see [troubleshooting](docs/troubleshooting.md#mcp--connector) |

Then add a custom connector under Settings → Connectors with
`https://<your-host>/<MCP_TOKEN>/mcp`. The token in the path is the only
credential — treat the whole URL as a password.

### Production setup: your own sending domain

The mailbox path polls your inbox once a minute and stores an app password. If
you would rather have instant push delivery, a sender on your own domain, or
you use a Google Workspace account (which cannot issue app passwords), run
`./setup.sh` and pick the **domain** option. It uses
[Resend](https://resend.com) — free tier covers 3,000 mails a month — and needs
a domain with DNS access.

Once the bridge is publicly reachable, finish it in one command:

```bash
./scribe-finish https://bridge.yourdomain.com
```

That creates the inbound webhook through Resend's API, writes its signing
secret into `.env`, and verifies that your domain has both sending *and*
receiving enabled — the setting people miss most often.

Switching between the two is one line in `.env` plus a restart. Nothing about
your stored documents changes.

Optionally install the plugin for `/scribe-send` and `/scribe-fetch` slash
commands in Claude Code:

```bash
claude plugin marketplace add starkshtlm/kindle-scribe-mcp
claude plugin install kindle-scribe@kindle-scribe
```

## Daily use

1. Ask Claude to send something: *"send this draft to my Kindle"*
2. Read it on the Scribe, write on the pages with the stylus
3. **Share → Send by email** to your return address (save it as a contact —
   then it is one tap)
4. Ask Claude: *"read my feedback"* — it fetches the pages, transcribes your
   handwriting, and acts on it

Set `NTFY_TOPIC` and subscribe in the [ntfy](https://ntfy.sh) app to get a
phone push the moment an annotated document lands.

**Handwritten notes work too.** Write in a blank notebook on the Scribe and
share it to the same address — it arrives like any other document, just
without an original to compare against.

**Hands-free interpretation.** Because documents are paired with the text they
were made from, a scheduled task can pick up new arrivals, read the
handwriting and `push_summary` the result to your phone — so the interpretation
is waiting for you instead of something you have to ask for. See
[`docs/automation.md`](docs/automation.md).

## Tools the MCP server exposes

| Tool | Purpose |
|---|---|
| `send_to_scribe(title, content_markdown)` | Render a pen-friendly PDF and mail it to the device |
| `list_annotated(only_new)` | List documents that came back |
| `get_annotated(item_id, start_page)` | Page images to read the handwriting, paginated — plus the original text when the document was sent from here |
| `push_summary(message)` | Push a short summary to the user's phone via ntfy |
| `ack_annotated(item_id)` | Mark one as processed |

The outgoing PDF uses a 3:4 page (matching the Scribe's screen), a wide right
margin as writing room, and generous line spacing. Ask Claude to number the
headings — handwritten references like "see 2.3" then land unambiguously.

## Configuration

All settings are environment variables; see [`.env.example`](.env.example).
Notable ones: `MCP_ALLOWED_HOSTS` (host allowlist for the MCP transport, `*`
disables the check), `RETURN_EMAIL` (the only address whose mail is processed — required),
`INBOX_RETENTION_DAYS` (auto-delete stored documents, 30 days by default),
`RESEND_WEBHOOK_SECRET` (required to receive anything — the webhook answers 503
until it is set).

## How it works, and what it cannot do

Amazon has no API for the Scribe. Sending uses Send-to-Kindle email; returning
uses the device's built-in share-by-email, which Amazon answers with a
download link that the bridge follows automatically. **Exporting from the
Scribe is therefore always a manual tap** — everything on either side of it is
automated.

Handwriting is read by Claude's vision, not OCR, so context and layout
(arrows, strike-throughs, circled words) are interpreted rather than just
transcribed.

Documents are stored on your own server. Nothing goes anywhere except Resend
(mail delivery) and Amazon (your own Kindle account).

## Troubleshooting

See [`docs/troubleshooting.md`](docs/troubleshooting.md) — it covers the traps
that cost the most time, including the Resend "Enable Receiving" toggle, the
`convert` subject line, and the upstream connector bug that makes some hosts
unreachable from Claude chats.

## License

MIT
