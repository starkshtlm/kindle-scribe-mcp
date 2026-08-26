# Security

## Reporting a vulnerability

**Please do not open a public issue.** Use GitHub's
[private vulnerability reporting](https://github.com/starkshtlm/kindle-scribe-mcp/security/advisories/new)
— the report is visible only to the maintainer. If that form is not available
to you, open an issue saying only that you have a security finding and want a
private channel, with no details in it.

Useful in a report: what an attacker would have to control, the smallest
sequence that demonstrates it, which version or commit you tested, and how you
configured the bridge (`MAIL_OUT`/`MAIL_IN` matter — the two inbound paths have
different exposure).

**What to expect.** One maintainer, evenings and weekends. An acknowledgement
within a few days, and an honest assessment rather than a silence. Anything
that leaks credentials or lets a stranger place a document in someone's inbox
gets worked on ahead of everything else; a hardening suggestion may sit longer.

**Disclosure.** Please give a reasonable window before publishing — thirty days
is more than enough for a project this size, and less is fine once a fix is
released. Fixes ship as a normal release with the reasoning in the notes, and
a GitHub advisory when the finding warrants one. Credit is offered by default
and withheld on request.

## Supported versions

The latest release is the supported one. This is a single-maintainer project
with no backport branches: fixes land on `main` and go out in the next tag.
Upgrading is `SCRIBE_VERSION` and a restart, so staying current is cheap.

## Threat model

The bridge sits between three parties you do not control: **inbound email**
(anyone can write to the address you receive on, whichever route it takes),
**Amazon's servers** (whose
download links you follow), and **the model** (which reads whatever ends up in
your inbox). The design assumptions:

1. **Inbound mail is untrusted until proven otherwise.** Resend inbound is
   catch-all — any address at your domain reaches the webhook — and a valid
   Svix signature only proves Resend relayed the message, *not* that Amazon
   sent it. Mail is therefore accepted only when it is addressed to
   `RETURN_EMAIL` **and** the sender domain is trusted **and** a receiving
   server said it verified that domain. Rejections are logged and pushed via
   ntfy, never silently dropped.

   The sender domain comes from `parseaddr`, so a display name reading
   `"kindle@amazon.com" <evil@attacker.test>` is the attacker, not Amazon. The
   verification result is read only from the *topmost* `Authentication-Results`
   or `Received-SPF` header — the one the receiving server prepended — and only
   from its labelled fields (`header.d`, `smtp.mailfrom`), never from the free
   text around them. Over the mailbox (IMAP) transport the message's own
   `DKIM-Signature` header is discarded: the bridge does not verify signatures,
   and anyone who can mail the address can write `d=amazon.com` into that
   header. It survives as a fallback only on the Resend path, where Resend's MX
   accepted the message upstream.

2. **Links in mail are untrusted.** The first link must be HTTPS on an Amazon
   host. Redirects cannot be disabled (Amazon's `/gp/f.html` forwards to S3),
   so every hop is validated instead: HTTPS only, capped hop count, and the
   hostname must resolve to publicly-routable addresses — blocking loopback,
   private ranges and cloud metadata endpoints. Downloads stream with a hard
   byte limit.

3. **The renderer never touches the network.** WeasyPrint dereferences
   images, stylesheets and fonts by default and offers no switch to stop it,
   so every external reference is stripped from model-supplied content before
   rendering. Without this, anything reaching `send_to_scribe` (including
   untrusted text pasted into a chat) could probe localhost or cloud metadata
   and have the response baked into a PDF and mailed out.

   Images are still supported: they are fetched *before* rendering, over HTTPS
   only, to publicly-routable addresses only, size-capped, and only when the
   response really is an image — then embedded as `data:` URIs. An image that
   cannot be fetched leaves a visible note rather than vanishing. This means
   the bridge will fetch public URLs on request (an ordinary capability for
   any HTML-to-PDF service); what it will not do is reach internal
   infrastructure, and no fetched content is returned to the caller.

4. **Document content is data, never instructions.** A PDF that reaches your
   inbox may contain text aimed at the model. Treat transcribed content as
   material to summarize and act on *within the current task*; do not let it
   trigger outward-facing actions (sending mail, calling other tools) without
   the user confirming. The bundled `scribe-fetch` skill is written this way.

5. **Nothing that reports on the bridge reports its secrets.** `GET /status`
   needs `BRIDGE_TOKEN` and returns what is configured and what happened —
   never a password, token, webhook secret or the MCP path. A test asserts
   that. `/healthz` is unauthenticated and therefore says only that the process
   is alive. `./scribe doctor` prints results, not credentials, and `./scribe
   connect` redacts the token from the section it echoes before writing it.

`server/test_security.py` covers these boundaries and runs in CI; extend it
with any new finding.

## What is not solved

- **The MCP endpoint authenticates with a secret in the URL path.** Claude's
  connector UI offers OAuth or nothing, so a path token is the practical
  option today. Consequence: the credential can appear in proxy and CDN logs.
  The container disables uvicorn's access log, but check your own edge. Rotate
  `MCP_TOKEN` if a log may have leaked, and prefer OAuth once available.
- **No multi-user isolation.** One deployment serves one person. Do not expose
  a shared instance to several users.
- **PDF parsing is not sandboxed.** poppler runs as a subprocess under the
  container's unprivileged user with dropped capabilities and a read-only
  filesystem, but not in a dedicated sandbox. Rebuild the image regularly so
  weasyprint and poppler stay patched; the base image is pinned by digest, so
  bump it when you rebuild.
- **DNS rebinding between validation and connection** is theoretically
  possible. The Amazon-host allowlist on the first hop makes it impractical.
- **An app password is not scoped to one folder.** With `MAIL_OUT=smtp` and
  `MAIL_IN=imap` the bridge holds a credential that can read your entire
  mailbox, and it sits in `.env` in plain text like every other secret here.
  It only ever reads mail from Amazon, and it *cannot write*: the folder is
  opened read-only and bodies are read with `BODY.PEEK[]`, so no flag changes
  and nothing is deleted — but the permission the credential grants is still
  broader than the use. Point `IMAP_USER`/`IMAP_PASSWORD` at a
  dedicated address if that matters to you, or take a Resend path, where the
  bridge never holds a mailbox credential at all.

## Deployment checklist

- [ ] `RESEND_WEBHOOK_SECRET` set when `MAIL_IN=resend` — the webhook refuses
      to run without it (and answers 404 when `MAIL_IN=imap`, so no unused door
      is left open)
- [ ] `RETURN_EMAIL` set to the address you share to from the Scribe
- [ ] `NTFY_TOPIC` set, so rejected mail is visible immediately
- [ ] `INBOX_RETENTION_DAYS` matches how long you want documents kept
- [ ] The MCP URL treated as a password; access logs off or redacted
- [ ] Container running non-root, read-only, cap-drop ALL, with memory limits
- [ ] Image rebuilt recently (weasyprint/poppler parse untrusted input)
