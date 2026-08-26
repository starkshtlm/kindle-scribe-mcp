# Configuration

Every setting is an environment variable, and
[`.env.example`](../.env.example) documents all of them next to sensible
defaults. `./setup.sh` writes the file for you; this page is for changing it
afterwards.

## The ones worth knowing

| Setting | Why you would touch it |
|---|---|
| `MAIL_OUT` / `MAIL_IN` | Which way mail moves — see [mail.md](mail.md) |
| `RETURN_EMAIL` | The only address whose mail is processed. Required; everything else is rejected and logged |
| `SMTP_PORT` / `SMTP_SECURITY` | 465 is implicit TLS, anything else upgrades with STARTTLS. iCloud only offers 587, and hosting providers block 465 routinely. The override is for hosts where the convention does not hold |
| `IMAP_USER` / `IMAP_PASSWORD` | When the mailbox you poll is not the one you send from. An app password reads the *whole* mailbox, so a dedicated address is worth it |
| `MCP_ALLOWED_HOSTS` | Host allowlist for the MCP transport; `*` disables the DNS-rebinding guard |
| `INBOX_RETENTION_DAYS` | Stored documents are deleted after this many days (30 by default; 0 keeps them) |
| `RESEND_WEBHOOK_SECRET` | Required with `MAIL_IN=resend`. Without it the webhook answers 503 and nothing arrives — `./scribe-finish` writes it |
| `NTFY_TOPIC` | Phone push when a document lands or is rejected. Use a long random name; anyone who knows it can subscribe |
| `SCRIBE_VERSION` | Which published image to run |

## Asking the bridge how it is doing

```bash
curl -sf -H "Authorization: Bearer $BRIDGE_TOKEN" http://127.0.0.1:8377/status
```

Reports the configured directions, whether the mailbox has ever connected, the
last error, how long since the last successful poll, and where the IMAP
checkpoint stands. It contains no credentials by design, and a test enforces
that. `/healthz` stays a plain unauthenticated liveness check — it says the
process is alive, not that mail is flowing.

`./scribe doctor` reads this and adds the checks it cannot do from inside the
container: the app password, the submission port, the mailbox login, the Resend
domain, the renderers.

## The image

Published multi-arch (amd64 and arm64) to
`ghcr.io/starkshtlm/kindle-scribe-mcp` on every tag, with an SBOM and build
provenance, and smoke-tested by digest before the attestation is pushed.

```bash
SCRIBE_VERSION=v1.2.3 docker compose up -d   # pin a version (see Releases)
docker compose -f docker-compose.dev.yml up -d --build   # build from a checkout
```

Builds install [`server/requirements.lock`](../server/requirements.lock),
resolved inside the same Python the image runs, so two builds of a tag install
the same versions months apart. `requirements.txt` stays the human-edited
source; regenerate the lock after changing it — the header has the command, and
CI fails if the two disagree.

Rolling back is changing `SCRIBE_VERSION` and restarting. Stored documents live
in the `scribe-data` volume and are untouched by that.

## The container

Runs as an unprivileged user with a read-only filesystem, all capabilities
dropped, `no-new-privileges`, and memory and PID limits. It parses PDFs that
strangers mailed you; assume a parser bug and give it as little as possible.
Rebuild regularly so weasyprint and poppler stay patched — the base image is
digest-pinned, so it only moves when you move it.
