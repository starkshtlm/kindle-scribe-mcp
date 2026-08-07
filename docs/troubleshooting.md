# Troubleshooting

Every item below is a real failure that cost hours to diagnose. Check here
before assuming your setup is broken.

## Sending

**The document never appears on the Scribe.**
Check Resend's dashboard (Emails → Sending). `Delivered` means Amazon accepted
it — then the usual cause is that `FROM_EMAIL` is not on Amazon's *Approved
Personal Document E-mail List*, or the device is off wifi. Amazon silently
drops mail from unapproved senders.

**The document arrives but you cannot write on the page.**
It was not sent as a PDF, or it got converted. Two rules: send **PDF only**
(EPUB/DOCX allow sticky notes, not writing on the page), and never use
`convert` as the subject line — that makes Amazon reflow the document and
disables page annotation. PDFs transferred over USB also cannot be annotated;
the mail path is the only one that works.

## Receiving

**You shared from the Scribe but nothing arrives.**
1. Resend → Domains → your domain: is **Enable Receiving** actually on? The
   toggle in the *add domain* form does not always persist — you often have to
   switch it on again from the domain page afterwards. This is the single most
   common setup mistake.
2. Resend → Emails → **Receiving** tab: is the mail there? If yes, the problem
   is your webhook, not the mail path. Resend stores inbound mail for 30 days,
   so nothing is lost while you fix it.
3. Check the MX record is on the right (sub)domain and has the lowest priority.

**Webhook returns 401.**
`RESEND_WEBHOOK_SECRET` does not match the signing secret shown on the webhook's
page in Resend. Copy it again and restart.

## MCP / connector

**"Couldn't reach the server" in a Claude chat, but the same URL works in
Claude Code, and your access logs show zero inbound requests.**
Claude's connector broker fails before it sends anything — a known upstream bug
that affects some hosting providers
([#214](https://github.com/anthropics/claude-ai-mcp/issues/214),
[#227](https://github.com/anthropics/claude-ai-mcp/issues/227),
[#374](https://github.com/anthropics/claude-ai-mcp/issues/374)). Nothing on your
side is wrong. Fixes, in order of preference:
1. Host where the broker can reach you — Fly.io works (see
   `deploy/fly.toml.example`).
2. Front your origin with the Cloudflare Worker in `worker/` — a `workers.dev`
   URL gets through. This is what the reference deployment does.

**"Invalid Host header" from the MCP endpoint.**
The MCP SDK's DNS-rebinding guard rejects Host headers it does not know. Set
`MCP_ALLOWED_HOSTS` to your public hostname(s), or `*` to disable the check.

**The endpoint 404s or the connector dialog rejects the URL.**
The URL must end in `/mcp` (`https://host/<MCP_TOKEN>/mcp`). Claude's connector
form also normalizes away a trailing slash, so do not rely on one.

**Tool changes do not take effect in an open chat.**
Claude caches tool definitions per conversation. Ask it to *re-read the MCP
server's tool definitions* — that is enough, no new chat needed.

## Server

**`No usable temporary directory found`.**
Under systemd with `ProtectSystem=strict`, `/tmp` is read-only. Add
`PrivateTmp=true` to the unit (already set in `deploy/systemd/`). PDF rendering
and page extraction both need writable temp space.

**Returned documents look truncated / only the first pages are read.**
`get_annotated` is paginated: it fills each reply up to a byte budget and tells
the model to call again with the next `start_page`. If Claude summarizes early,
say "read every page first". Note that identical byte sizes across attempts mean
you are looking at the *same stored document*, not a size limit.

## Hosting

**SSH to your own VPS stops responding while everything else works.**
Not related to this project, but it bit the reference deployment: sshd's
connection queue can be swamped by brute-force traffic. `MaxStartups 30:30:200`
plus `ufw limit 22/tcp` (rate limiting — never pin to a source IP if yours is
dynamic) fixes it. Recover through your provider's web console.
