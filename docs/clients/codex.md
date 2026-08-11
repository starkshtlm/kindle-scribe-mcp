# Codex

Codex CLI, the Codex IDE extension and the ChatGPT desktop app read the same
MCP configuration — `~/.codex/config.toml`, or `$CODEX_HOME/config.toml`.
Registering the bridge once covers all three.

```bash
./scribe connect codex
```

It checks that the endpoint really answers as an MCP server first, shows the
section it will add, keeps a timestamped backup, and never touches sections
belonging to other servers. Restart Codex afterwards; a running client does not
re-read the file.

What it writes:

```toml
[mcp_servers.kindle-scribe]
url = "http://127.0.0.1:8377/<MCP_TOKEN>/mcp"
```

**The URL is the credential.** The token in the path is what authenticates you,
so treat the whole line like a password — `connect` redacts it when printing,
but the file itself has the real thing.

## Running the bridge somewhere else

If Codex runs on a different machine than the bridge, give it the public
hostname instead of the local one:

```bash
./scribe connect codex --url https://bridge.yourdomain.com
```

The bridge must answer over HTTPS for this, the same requirement claude.ai
chats have — see the deployment options in the README.

## Checking it took

Ask Codex to list what the server offers. You should see five tools:
`send_to_scribe`, `list_annotated`, `get_annotated`, `push_summary` and
`ack_annotated`.

The server also sends MCP `instructions` describing the Send → Review →
Acknowledge loop, which Codex reads as server-wide guidance, so you should not
need to explain the workflow in your prompt.

## If it does not work

- `./scribe doctor` — checks the bridge itself before you suspect the client
- the endpoint must end in `/mcp`
- a bridge on a public hostname needs that hostname in `MCP_ALLOWED_HOSTS`
  (or `*`), otherwise the SDK's DNS-rebinding guard answers "Invalid Host
  header"
- see [../troubleshooting.md](../troubleshooting.md) for the rest
