# Security

## Reporting

Open a [GitHub issue](https://github.com/starkshtlm/kindle-scribe-mcp/issues)
for anything you find. This is a hobby project without a paid disclosure
process — if a finding is sensitive, say so in one line without details and we
will agree on a private channel.

## Threat model

The bridge sits between three parties you do not control: **inbound email**
(anyone can send to your receiving domain), **Amazon's servers** (whose
download links you follow), and **the model** (which reads whatever ends up in
your inbox). The design assumptions:

1. **Inbound mail is untrusted until proven otherwise.** Resend inbound is
   catch-all — any address at your domain reaches the webhook — and a valid
   Svix signature only proves Resend relayed the message, *not* that Amazon
   sent it. Mail is therefore accepted only when it is addressed to
   `RETURN_EMAIL` **and** the sender domain is trusted **and** DKIM or SPF
   backs that domain. Rejections are logged and pushed via ntfy, never
   silently dropped.

2. **Links in mail are untrusted.** The first link must be HTTPS on an Amazon
   host. Redirects cannot be disabled (Amazon's `/gp/f.html` forwards to S3),
   so every hop is validated instead: HTTPS only, capped hop count, and the
   hostname must resolve to publicly-routable addresses — blocking loopback,
   private ranges and cloud metadata endpoints. Downloads stream with a hard
   byte limit.

3. **Document content is data, never instructions.** A PDF that reaches your
   inbox may contain text aimed at the model. Treat transcribed content as
   material to summarize and act on *within the current task*; do not let it
   trigger outward-facing actions (sending mail, calling other tools) without
   the user confirming. The bundled `scribe-fetch` skill is written this way.

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
- **The container runs as root** and system packages are not pinned. Run it
  with `--cap-drop ALL --security-opt no-new-privileges` and a read-only
  filesystem, and keep the image rebuilt so weasyprint/poppler stay patched.
  PDF parsing happens in subprocesses but not in a sandbox.
- **DNS rebinding between validation and connection** is theoretically
  possible. The Amazon-host allowlist on the first hop makes it impractical.

## Deployment checklist

- [ ] `RESEND_WEBHOOK_SECRET` set — the webhook refuses to run without it
- [ ] `RETURN_EMAIL` set to the address you share to from the Scribe
- [ ] `NTFY_TOPIC` set, so rejected mail is visible immediately
- [ ] `INBOX_RETENTION_DAYS` matches how long you want documents kept
- [ ] The MCP URL treated as a password; access logs off or redacted
- [ ] Container running non-root with resource limits
