# ChatGPT desktop

The desktop app reads the same MCP configuration as Codex —
`~/.codex/config.toml`. There is nothing separate to set up, and a second
configuration file would only be a second thing to keep in step.

```bash
./scribe connect codex            # registers the bridge
./scribe connect chatgpt-desktop  # confirms the app will see it
```

The second command writes nothing. It checks that the endpoint answers, that
the section is present in the shared file, and reminds you to restart the app —
a running client does not re-read the configuration.

See [codex.md](codex.md) for what gets written, how to point at a bridge on
another machine, and what to check when it does not work.

## Worth knowing

**Images.** Reading handwriting means the client has to render the page images
`get_annotated` returns. Replies are paginated to stay under a size limit
tuned for claude.ai; if a client truncates them, lower the budget rather than
assuming the document is broken.

**The device tap is still manual.** No client can export from the Scribe for
you — Amazon has no API for it. Everything on either side of that tap is
automated.
