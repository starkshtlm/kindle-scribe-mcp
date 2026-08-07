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
- A **[Resend](https://resend.com)** account — free tier is plenty
- A **domain** you can add DNS records to (a subdomain such as
  `scribe.yourdomain.com` is recommended)
- Somewhere to run a small container with **public HTTPS**

Setup takes about 30 minutes, most of it waiting for DNS.

## Quick start

```bash
git clone https://github.com/starkshtlm/kindle-scribe-mcp
cd kindle-scribe-mcp
./setup.sh          # asks for your keys, writes .env, prints the next steps
docker compose up -d
```

`setup.sh` prints the two things it cannot do for you (adding the sender to
Amazon's approved list, registering the Resend webhook) and the exact connector
URL to paste into Claude.

### Exposing it

The bridge listens on `127.0.0.1:8377` and must be reachable over public HTTPS.

| Option | How |
|---|---|
| **Fly.io** (simplest) | `deploy/fly.toml.example` — HTTPS included, and Claude's connector reaches it directly |
| **Your own VPS** | `deploy/Caddyfile.example` — two lines, automatic Let's Encrypt |
| **Behind a firewall / broker cannot reach you** | `worker/` — a Cloudflare Worker relay, see [troubleshooting](docs/troubleshooting.md#mcp--connector) |

### Connecting Claude

Add a custom connector with the URL `setup.sh` printed:

```
https://<your-host>/<MCP_TOKEN>/mcp
```

- **Claude chats (web + mobile):** Settings → Connectors → Add custom connector
- **Claude Code:** `claude mcp add --transport http --scope user kindle-scribe "<url>"`

The token in the path is the only credential — treat the whole URL as a
password.

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

## Tools the MCP server exposes

| Tool | Purpose |
|---|---|
| `send_to_scribe(title, content_markdown)` | Render a pen-friendly PDF and mail it to the device |
| `list_annotated(only_new)` | List documents that came back |
| `get_annotated(item_id, start_page)` | Page images to read the handwriting (paginated) |
| `ack_annotated(item_id)` | Mark one as processed |

The outgoing PDF uses a 3:4 page (matching the Scribe's screen), a wide right
margin as writing room, and generous line spacing. Ask Claude to number the
headings — handwritten references like "see 2.3" then land unambiguously.

## Configuration

All settings are environment variables; see [`.env.example`](.env.example).
Notable ones: `MCP_ALLOWED_HOSTS` (host allowlist for the MCP transport, `*`
disables the check), `INBOX_RETENTION_DAYS` (auto-delete stored documents),
`RESEND_WEBHOOK_SECRET` (verify webhook signatures — recommended).

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
