# Any other MCP client

Untested, but there is nothing Claude- or Codex-specific in the server.

**Transport:** streamable HTTP.
**URL:** `http://127.0.0.1:8377/<MCP_TOKEN>/mcp` locally, or your public
hostname — it must end in `/mcp`.
**Auth:** the token in the path. Clients that support headers can also be
pointed at the same URL; there is no separate bearer scheme yet.

Check it the way `./scribe connect` does:

```bash
curl -sf -X POST http://127.0.0.1:8377/<MCP_TOKEN>/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Five tools should come back: `send_to_scribe`, `list_annotated`,
`get_annotated`, `push_summary`, `ack_annotated`.

## What a client has to do well

**Render image content.** Reading handwriting means the client passes PNG page
images to the model. A client that drops or downsamples them will produce
confident nonsense rather than an error.

**Respect pagination.** `get_annotated` returns a page range and says when more
remain. A client that stops at the first reply reads a third of the document.

**Surface `instructions`.** The server describes the Send → Review →
Acknowledge loop in the MCP `instructions` field. Clients that ignore it still
work; the model just has to be told the workflow.

If you get it working somewhere new, an issue saying which client and whether
the images rendered is genuinely useful — that is the row this project cannot
fill in on its own.
