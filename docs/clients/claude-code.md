# Claude Code

```bash
./scribe connect claude-code
```

That runs `claude mcp add --transport http --scope user kindle-scribe <url>`
after checking the endpoint answers. If the `claude` CLI is not on PATH it
prints the command instead, with the token redacted, for you to run where it is.

Confirm with `claude mcp list`, or just ask for something: *"send this to my
Kindle"*.

## The plugin

Optional, and separate from the MCP server — it adds `/scribe-send` and
`/scribe-fetch` slash commands that talk to the REST endpoint:

```bash
claude plugin marketplace add starkshtlm/kindle-scribe-mcp
claude plugin install kindle-scribe@kindle-scribe
```

The skills read `~/.scribe-bridge.env` for `BRIDGE_URL` and `BRIDGE_TOKEN`,
which `./setup.sh` writes. They prefer the MCP tools when the server is
connected, so installing both is fine.

## Scheduled reading

Claude Code can run the interpretation on a timer, so a document that comes
back while you are elsewhere is already read when you return. The prompt and
the permissions it needs are in [../automation.md](../automation.md).
