# Clients

The bridge is an MCP server over streamable HTTP. Anything that speaks that
should work; what follows is what has actually been tried.

| Client | Status | Setup |
|---|---|---|
| Claude Code | Full loop run end to end | [claude-code.md](claude-code.md) |
| Claude chats (claude.ai, mobile) | Full loop run end to end, needs public HTTPS | [claude-ai.md](claude-ai.md) |
| Codex CLI | Registered, tools list confirmed over the wire | [codex.md](codex.md) |
| Codex IDE extension | Shares Codex's configuration | [codex.md](codex.md) |
| ChatGPT desktop | Shares Codex's configuration | [chatgpt-desktop.md](chatgpt-desktop.md) |
| Cursor, VS Code agents, others | Expected to work, untested | [generic-mcp.md](generic-mcp.md) |

**What "registered, tools list confirmed" means.** `./scribe connect` posts a
`tools/list` to the endpoint and checks all five tools answer before it writes
anything, so the client is pointed at a server that demonstrably works. What
has not been verified for those rows is the other half: that the client renders
the returned page images well enough for the model to read handwriting from
them. If you run that loop, please say so in an issue — it is the one claim
this table cannot make for you.

## Two things every client needs

**The URL is the credential.** The token in the path is the only thing
authenticating the connection. Treat the whole URL like a password.

**The endpoint must end in `/mcp`**, and a public deployment needs its hostname
in `MCP_ALLOWED_HOSTS` or the SDK's DNS-rebinding guard rejects it.
