# Hacker News (Show HN)

Builder-to-builder. No executive framing, no adjectives that have to be taken
on trust. Be in the thread.

---

**Title:** Show HN: An MCP server that turns handwriting on a Kindle Scribe into edits

The loop: ask an assistant for a draft, it renders a pen-friendly PDF and mails
it to the device, you annotate it with the stylus, share it back by email, and
the server hands the pages to the model as images along with the markdown it
was rendered from — so the model can say what your handwriting *changes*, not
just what it sees.

It is an MCP server, so it is not tied to one assistant: `./scribe connect`
registers it with Claude Code, Codex CLI, the Codex IDE extension or the
ChatGPT desktop app. Anything speaking streamable-HTTP MCP should work; I have
run the full loop on Claude Code myself.

Three things I would have got wrong without building it:

**Vision beats OCR, and it is not close.** Strike-through, margin arrows and
circled words are notation a colleague understands and a transcriber destroys.
Reading the page as an image keeps the meaning of *where* something is written.

**The trust boundary is the whole project.** Inbound mail is attacker-supplied:
anyone who knows your address can send you something claiming to be from
Amazon. So mail is accepted only when it is addressed to your return address
*and* a receiving server verified the sender — read from the topmost
Authentication-Results header, never from the message's own DKIM-Signature,
which anyone can write. Then every link hop is validated, and the model is told
the document is data, not instructions.

**Silent failure is the default in this domain.** Amazon does not bounce mail
from unapproved senders. A wrong app password looks exactly like a quiet
afternoon. So `./scribe doctor` tests the password, the port, the mailbox and
the renderers, and says which one is broken — and `./scribe test` sends a
document with an id that `./scribe verify` looks for.

MIT, self-hosted, no project-hosted account or proprietary service required:
https://github.com/starkshtlm/kindle-scribe-mcp

Quick start is an email account you already have, Docker, and five minutes. The
only step that can never be automated is the share tap on the device — Amazon
has no API for it.

---

**Notes.** The trust-boundary paragraph is what makes this credible to this
audience — it shows the failure mode was thought about before it was found.
Expect "why not OCR" and "what stops someone mailing you a document"; both are
answered in the post, which is the point.
