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

## Mailbox transport (SMTP + IMAP)

**The app password is rejected.**
Use an *app password*, never your account password, and turn on 2FA first —
providers only issue app passwords once 2FA is enabled. Gmail:
myaccount.google.com/apppasswords. iCloud: appleid.apple.com → Sign-In and
Security.

**Outlook.com, Hotmail, Live or MSN: this path does not work at all.**
Microsoft removed password sign-in for third-party IMAP/SMTP on personal
accounts on 2024-09-16, and app passwords went with it — the only symptom is an
authentication failure that looks like a typo. `setup.sh` stops you here on
purpose. Use Gmail, iCloud, Fastmail or your own domain, or take the Resend
path.

**Google Workspace account: there is no app-password option.**
Google removed app passwords for Workspace accounts, so a `you@yourcompany.com`
Google account cannot use this path. Use a personal Gmail/iCloud/Fastmail
address, or switch to the domain (Resend) path.

**A returning document is rejected with "no receiving server verified this
sender".**
Over IMAP the bridge trusts only the topmost `Authentication-Results` header —
the one your own provider added — and ignores the message's `DKIM-Signature`
entirely, because anyone who can mail you can write `d=amazon.com` into it.
If your provider does not stamp `Authentication-Results`, or a forwarding rule
strips it, genuine mail is refused too. Forward to a mailbox that stamps it
(Gmail, iCloud and Fastmail all do), or use the Resend path.

**Documents send fine but nothing comes back.**
The bridge only looks at unread mail *from Amazon* in `IMAP_FOLDER`. Check that
a rule or filter is not moving Amazon's mail out of the inbox before the poll
sees it, and that you shared to the address in `RETURN_EMAIL` (with this
transport that is your own address). Rejections are logged and pushed to ntfy.

**It takes up to a minute.**
That is the poll interval. Lower `IMAP_POLL_SECONDS` if you want, but every
poll is a login — a minute is a reasonable balance.

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

**Webhook returns 503.**
`RESEND_WEBHOOK_SECRET` is empty. The webhook fails closed rather than accept
unsigned requests, so every delivery is refused and nothing reaches the inbox.
Register the webhook in Resend, paste its signing secret into `.env`, restart.
Resend keeps inbound mail for 30 days, so the documents are still there.

**Webhook returns 401.**
`RESEND_WEBHOOK_SECRET` does not match the signing secret shown on the webhook's
page in Resend. Copy it again and restart. If it *did* work until recently,
check the server clock: deliveries more than an hour out of step are rejected
as stale, and a suspended VM comes back with a drifted clock.

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
   URL gets through. This is what the reference deployment does. The worker
   relays `/webhook/inbound` as well, so the same hostname works for the Resend
   webhook and you do not need a second public route.

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
