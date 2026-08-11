# Reaching the bridge from somewhere else

A bridge on your laptop is enough for Claude Code, Codex and ChatGPT desktop —
they run on the same machine. Two things need it to be publicly reachable:

- **chats on claude.ai, or your phone**, where the client is not on your machine
- **Resend's inbound webhook**, if you use `MAIL_IN=resend` ([mail.md](mail.md))

| Option | How |
|---|---|
| **Fly.io** (simplest) | `deploy/fly.toml.example` — HTTPS included, and Claude's connector reaches it directly |
| **Your own VPS** | `deploy/Caddyfile.example` — two lines, automatic Let's Encrypt |
| **Behind a firewall / the broker cannot reach you** | `worker/` — a Cloudflare Worker relay |

Then point the client at that hostname:

```bash
./scribe connect codex --url https://bridge.yourdomain.com
```

or, for a chat on claude.ai, add a custom connector under Settings → Connectors
with `https://<your-host>/<MCP_TOKEN>/mcp`.

**The URL is the credential.** The token in the path is the only thing
authenticating you, so treat the whole URL like a password. The container
disables uvicorn's access log for that reason; check your own edge, and rotate
`MCP_TOKEN` if a log may have recorded it.

**Name the hostname.** `MCP_ALLOWED_HOSTS` must include your public hostname,
or the MCP SDK's DNS-rebinding guard answers "Invalid Host header". `*` turns
the check off, which is reasonable when a secret path is the only entry point
and a proxy terminates TLS.

## When a chat cannot reach a server that works everywhere else

If Claude Code can use the URL and a claude.ai chat cannot — and your access
log shows *zero* inbound requests — nothing on your side is wrong. It is a
known upstream bug in the connector broker that affects some hosting providers,
and the Cloudflare Worker in `worker/` is the way around it. See
[troubleshooting.md](troubleshooting.md#mcp--connector) for the issue links and
the order to try things in.
