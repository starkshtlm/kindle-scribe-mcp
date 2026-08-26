# Claude chats (claude.ai and mobile)

Chats do not run on your machine, so the bridge needs a public HTTPS address —
see [../remote-access.md](../remote-access.md) for the deployment options.

Then add a custom connector under **Settings → Connectors**:

```
https://<your-host>/<MCP_TOKEN>/mcp
```

The token in the path is the credential. Anyone with the URL has your bridge.

## Worth knowing

**Replies are size-limited.** `get_annotated` paginates page images to stay
under the cap and tells the model to call again for the rest. If a long
document seems to stop early, ask it to read every page before summarising —
identical byte counts across attempts mean you are looking at the same stored
document, not a limit.

**Tool definitions are cached per conversation.** After changing anything
server-side, ask the chat to re-read the MCP server's tool definitions rather
than starting a new conversation.

**If a chat cannot reach a server that works everywhere else** and your access
log shows no inbound requests at all, it is a known upstream broker bug — see
[../troubleshooting.md](../troubleshooting.md#mcp--connector).
