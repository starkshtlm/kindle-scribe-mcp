# kindle-scribe-mcp

[![CI](https://github.com/starkshtlm/kindle-scribe-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/starkshtlm/kindle-scribe-mcp/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/starkshtlm/kindle-scribe-mcp)](https://github.com/starkshtlm/kindle-scribe-mcp/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

**Think with AI. Review with a pen.**

Send an AI-generated memo, plan or long draft to your Kindle Scribe. Read it
away from the screen, argue with it in the margin, and send the pages back —
the model reads your handwriting, understands where the marks belong, and
continues the work from there.

```
AI drafts  →  Kindle Scribe  →  you think with a pen  →  AI continues
```

## The part that surprises people

It reads *layout*, not just words. A strike-through means delete. An arrow from
the margin means insert here. A circled word means that word, not the sentence.

Cross out a weak assumption, write "too operational — frame this for the board"
beside it, and send the page back. The model sees which paragraph the note
belongs to and revises that one. You never explain the notation, because vision
reads a page the way a colleague would.

That is also why the outgoing PDF is shaped the way it is: a 3:4 page matching
the Scribe's screen, a wide right margin as writing room, generous leading.
Number the headings and a scrawled "see 2.3" is unambiguous on the way back.

## What people use it for

- Reviewing a strategy or board memo somewhere other than the screen it was
  written on
- Challenging the assumptions in an AI-generated market or competitor analysis
- Marking up an operating plan, investment memo or product strategy
- Reading a PRD, org proposal or risk assessment at the pace it deserves
- Preparing for a meeting that matters, with a pen
- Turning a page of handwritten decisions into the next revision
- Working through a long report while travelling, away from a laptop
- Reading something sensitive slowly, without a chat window in the way

It does not decide anything for you. It removes the screen from the part of the
work where the screen was not helping. More detail, with the prompts that work:
[`docs/use-cases.md`](docs/use-cases.md).

## Why this exists

AI has become very good at producing and reshaping information. A chat window
is not always the best place for a person to *think* about that information —
it invites the next message rather than a second reading.

So: let the model do what it is good at, then take the result somewhere with no
notifications and a pen. This project is the plumbing that makes the round trip
worth doing, and the plumbing is the only hard part.

## Quick start

```bash
git clone https://github.com/starkshtlm/kindle-scribe-mcp
cd kindle-scribe-mcp
./setup.sh              # an email account you already have, and an app password
docker compose up -d    # pulls a published image; nothing is compiled
./scribe doctor         # says what works before you trust it
./scribe connect codex  # or claude-code, or chatgpt-desktop
```

About five minutes once Docker, the app password and Amazon's settings page are
ready — those three are the actual work. Two steps the script cannot do:

1. Add your own address to Amazon's *Approved Personal Document E-mail List*
   (amazon.com/mycd → Preferences → Personal Document Settings). Amazon drops
   mail from unapproved senders silently, with no bounce.
2. Have the Scribe on wifi.

**You need:** a Kindle Scribe (or any Kindle you can write on), Docker, and an
email account that can issue an app password — Gmail, iCloud, Fastmail or your
own domain. Outlook.com cannot: Microsoft removed password sign-in for
third-party IMAP and SMTP on personal accounts in 2024. Google Workspace
depends on how the account is administered; if the option is missing, the
Resend path in [`docs/mail.md`](docs/mail.md) works regardless.

It is self-hosted, so this suits someone technically confident — or someone
with a developer nearby. A hosted path is on the [roadmap](ROADMAP.md), not in
this release.

## Prove the loop before you trust it

Three commands, because in this system everything fails quietly: Amazon does
not bounce mail from an unapproved sender, and a wrong app password looks
exactly like a slow afternoon.

```bash
./scribe doctor    # is the system ready?
./scribe test      # send a real document carrying a test id
./scribe verify    # did that exact document complete the return trip?
```

`doctor` tests the app password, the submission port, the mailbox login, the
Resend domain if you use one, and the renderers inside the container — then
names whichever one is broken:

```
  ✓ settings             MAIL_OUT=smtp MAIL_IN=imap
  ✗ smtp                 smtp.gmail.com:465 rejected the password — use an app
                         password, not your account password (2FA must be on)
  ✓ bridge               http://127.0.0.1:8377 healthy, mcp=True
  ✓ renderer weasyprint  WeasyPrint version 62.3
```

`--json` exits non-zero when something failed. Run it when something is wrong,
not on a timer: each run is a login attempt.

## A normal day

> **You:** send this strategy memo to my Kindle
>
> **Assistant:** Sent — it appears on the Scribe within a minute.
>
> *[you read it in an armchair, cross out the market assumption, write "frame
> this for the board" in the margin, bracket section 4 with "too long"]*
>
> **You:** read my Kindle feedback and revise the memo
>
> **Assistant:** You removed the current-market assumption, asked for a
> board-level framing, and marked section 4 for shortening. Here is the revision.

Handwriting interpretation is good, not perfect. Numbered headings and clear
marks make the difference; a cramped note in a crowded margin may need a second
look.

**Handwritten notes work without an original** — write in a blank notebook and
share it, and it arrives like any other document with nothing to compare
against. **A returning document brings its source**, so the model can say what
your handwriting *changes*, not merely what it sees. And it can read without
being asked: a scheduled task can pick up arrivals and push you the summary
([`docs/automation.md`](docs/automation.md)).

## Works with more than one assistant

The bridge is an MCP server, so it is not tied to one of them.

```bash
./scribe connect claude-code
./scribe connect codex            # also the Codex IDE extension
./scribe connect chatgpt-desktop  # shares Codex's configuration
```

`connect` checks the endpoint answers, shows what it will write, keeps a
backup, and leaves other servers in the file alone.

| | Status |
|---|---|
| Claude Code, Claude chats (via a public hostname) | Full loop run end to end |
| Codex CLI, Codex IDE extension, ChatGPT desktop | Registered and answering; loop not yet run by me |
| Cursor, VS Code agents, other streamable-HTTP MCP clients | Expected to work — reports welcome |

[`docs/clients/`](docs/clients/) has the detail, including what "expected"
rests on.

## Where your documents actually go

Storage and processing are different questions, and the honest answer to the
second is longer.

**Stored** on your own machine, in a Docker volume, deleted after
`INBOX_RETENTION_DAYS` (30 by default).

**Processed** by, depending on how you configure it: your mail provider and
Amazon (the document travels as mail); **whichever AI you use** — reading
handwriting means sending page images to that model, so its provider sees the
pages; Resend, on a push-based inbound path; ntfy.sh, if you enable summaries;
and your own public hostname or a Cloudflare relay, if you expose the bridge
for phone use.

No account with this project is involved, and nothing goes anywhere not listed
above. The full path is in [`docs/privacy.md`](docs/privacy.md).

## What it cannot do

Amazon publishes no API for the Scribe. Sending uses Send-to-Kindle email;
returning uses the device's own share-by-email, which Amazon answers with a
download link the bridge follows. **The share tap on the device is manual**,
and stays that way until Amazon offers a supported export API — everything on
either side of it is automated.

One deployment serves one person; there is no multi-user isolation. Some
providers cannot be used at all (see above). Handwriting interpretation varies
with the handwriting.

## Deeper

| | |
|---|---|
| [Use cases](docs/use-cases.md) | What to send, and the prompts that work |
| [How mail moves](docs/mail.md) | Three paths, from "nothing public" to your own sending domain |
| [Architecture](docs/architecture.md) | What runs where, and why it is shaped this way |
| [Privacy](docs/privacy.md) | Every processor in the path |
| [Security](SECURITY.md) | Threat model, and what is not solved |
| [Configuration](docs/configuration.md) | Every setting, `/status`, the published image |
| [Remote access](docs/remote-access.md) | Phones, claude.ai chats, public HTTPS |
| [Clients](docs/clients/) | Per-client setup and verification status |
| [Automation](docs/automation.md) | Hands-free interpretation |
| [Troubleshooting](docs/troubleshooting.md) | Every entry is a real failure that cost hours |
| [Roadmap](ROADMAP.md) · [Contributing](CONTRIBUTING.md) · [Support](SUPPORT.md) | Where this is going, and how to help |

Optional Claude Code plugin for `/scribe-send` and `/scribe-fetch`:

```bash
claude plugin marketplace add starkshtlm/kindle-scribe-mcp
claude plugin install kindle-scribe@kindle-scribe
```

## License

MIT
