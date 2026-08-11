# kindle-scribe-mcp

Ask your assistant for a draft. Read it on a Kindle Scribe, in an armchair, and
mark it up with the pen. Tap share. The assistant reads your handwriting and
makes the edits.

```
   your assistant            your server                    Amazon
┌────────────────┐  send_to_ ┌──────────────┐  SMTP or    ┌─────────┐
│ Claude · Codex │──scribe──▶│  PDF render  │──Resend────▶│ @kindle │──▶ Scribe
│ ChatGPT · any  │           │              │             └─────────┘  (read +
│  MCP client    │  get_     │   inbox   ◀──│◀─ IMAP poll ◀─ "shared    stylus)
│                │◀─annotated│  page images │   or webhook   from Kindle" │
└────────────────┘           └──────────────┘                            │
        ▲                                        Share → Send by email ──┘
        └── reads the marks, not just the words
```

## The part that surprises people

It reads *layout*. A strike-through means delete. An arrow from the margin
means insert here. A circled word means that word, not the sentence. Cross out
a wrong number, write the right one beside it, and the correction lands where
you meant it — you never explain the notation, because vision reads the page
the way a colleague would.

That is also why the outgoing PDF is shaped the way it is: a 3:4 page matching
the Scribe's screen, a wide right margin as writing room, generous leading.
Number the headings and a scrawled "see 2.3" is unambiguous on the way back.

## Quick start

About five minutes, and the longest step is Amazon's.

```bash
git clone https://github.com/starkshtlm/kindle-scribe-mcp
cd kindle-scribe-mcp
./setup.sh              # an email account you already have, and an app password
docker compose up -d    # pulls a published image; nothing is compiled
./scribe doctor         # says what works before you trust it
./scribe connect codex  # or claude-code, or chatgpt-desktop
```

Two things the script cannot do for you:

1. Add your own address to Amazon's *Approved Personal Document E-mail List*
   (amazon.com/mycd → Preferences → Personal Document Settings). Amazon drops
   mail from unapproved senders silently, with no bounce.
2. Have the Scribe on wifi.

Then ask for something: *"send this draft to my Kindle"*. Write on it. Share it
back by email to yourself. Ask: *"read my feedback"*.

`./scribe test` sends a document carrying a test id and `./scribe verify`
confirms that exact document came back, so the first round trip is a check
rather than a hope.

**You need:** a Kindle Scribe (or any Kindle you can write on), Docker, and an
email account that can issue an app password — Gmail, iCloud, Fastmail or your
own domain. Not Outlook.com or Google Workspace; both are OAuth-only now.

## Works with whatever you already use

The bridge is an MCP server, so it is not tied to one assistant.

```bash
./scribe connect claude-code
./scribe connect codex            # also the Codex IDE extension
./scribe connect chatgpt-desktop  # shares Codex's configuration
```

`connect` checks the endpoint answers, shows what it will write, keeps a
backup, and leaves other servers in the file alone. Cursor, VS Code agents and
anything else speaking the protocol work too — point them at the same URL. See
[`docs/clients/`](docs/clients/).

For chats on claude.ai or a phone, the bridge needs a public HTTPS address:
[`docs/remote-access.md`](docs/remote-access.md).

## Living with it

**Handwritten notes work without an original.** Write in a blank notebook and
share it — it arrives like any other document, just with nothing to compare
against.

**A returning document brings its source.** The markdown it was rendered from
comes back with the page images, so the model can say what your handwriting
*changes*, not merely what it sees.

**It can interpret without being asked.** A scheduled task picks up new
arrivals, reads the handwriting and pushes a summary to your phone, so the
reading is waiting for you: [`docs/automation.md`](docs/automation.md). Set
`NTFY_TOPIC` for a push the moment something lands.

## The five tools

| Tool | Purpose |
|---|---|
| `send_to_scribe(title, content_markdown)` | Render a pen-friendly PDF and mail it to the device |
| `list_annotated(only_new)` | List documents that came back |
| `get_annotated(item_id, start_page)` | Page images to read the handwriting, paginated — with the original text when the document was sent from here |
| `push_summary(message)` | Push a short summary to the phone via ntfy |
| `ack_annotated(item_id)` | Mark one as processed |

## What it cannot do

Amazon has no API for the Scribe. Sending uses Send-to-Kindle email; returning
uses the device's own share-by-email, which Amazon answers with a download link
the bridge follows. **The share tap on the device is manual and always will
be** — everything on either side of it is automated.

Documents stay on your own server. Nothing leaves it except to your mail
provider and Amazon, and on the quick-start path that mail provider is the one
you already use.

## Deeper

- [How mail moves](docs/mail.md) — three paths, from "no domain, nothing
  public" to your own sending domain
- [Remote access](docs/remote-access.md) — claude.ai chats, phones, public HTTPS
- [Configuration](docs/configuration.md) — every setting, the published image,
  `/status`
- [Troubleshooting](docs/troubleshooting.md) — the traps that cost the most
  hours, each one a real failure
- [Security](SECURITY.md) — the trust boundary, and what is not solved
- [Automation](docs/automation.md) — hands-free interpretation

Optional Claude Code plugin for `/scribe-send` and `/scribe-fetch`:

```bash
claude plugin marketplace add starkshtlm/kindle-scribe-mcp
claude plugin install kindle-scribe@kindle-scribe
```

## License

MIT
