# Announcement drafts

Not published. Review before posting — and post where you can stay for a few
hours afterwards, because the questions are the point.

The one thing that would do more than any of this text: **a 20-second screen
recording of the loop**. Ask for a draft, cut a line on the Scribe, write a
replacement in the margin, ask the assistant to read it, show the edit landing.
Nobody believes the layout part until they see it.

---

## r/kindlescribe — device owners

**Title:** I wired my Scribe into my AI assistant, so notes I write by hand come back as edits

I read and think better on paper, but everything I work on lives in a chat
window. So I closed the loop: I ask for a draft, it lands on the Scribe a
minute later, I read it in an armchair and mark it up with the pen, tap Share →
email, and the assistant reads my handwriting and makes the changes.

The part I did not expect to work as well as it does: it reads *layout*, not
just words. Strike-through means delete. An arrow from the margin means insert
here. A circled word means that word, not the sentence. I corrected a wrong
figure by crossing it out and writing the right one beside it, and it landed
where I meant it — I never explained the notation.

Underneath it is plain Send-to-Kindle email out, and the Scribe's own
share-by-email back. A small server catches Amazon's export mail, follows the
download link and hands the pages to the model as images. Outgoing PDFs use a
3:4 page so they fill the screen, with a wide right margin as writing room.

The only manual step in the whole loop is the Share tap, because Amazon has no
API for the device. Everything on either side of it is automatic.

Free and self-hosted, MIT: https://github.com/starkshtlm/kindle-scribe-mcp

You need a Scribe, Docker, and an email account that can issue an app password.
No domain, no DNS, no webhook — about five minutes, and the longest step is
adding your own address to Amazon's approved-sender list. Happy to help anyone
who gets stuck.

---

## MobileRead — people who will ask how it works

**Title:** Open source: Kindle Scribe ↔ LLM round trip (send, annotate by hand, read back)

Sharing a project that closes the loop between an assistant and the Scribe's
pen, and the notes I wish I had found before starting.

Outbound is Send-to-Kindle email with PDFs shaped for the device: 3:4 page
ratio, wide right margin, generous leading. Inbound is the device's built-in
share-by-email — a small server catches Amazon's export notification, follows
the download link before it expires, and stores the annotated PDF. The
handwriting is then read by the model's vision rather than OCR, so marginalia,
strike-throughs and arrows are interpreted in context instead of flattened into
a transcript.

What cost me time, in case it saves you some:

- PDFs must arrive **by email** to be writable. USB-transferred PDFs cannot be
  annotated on the page.
- Never use `convert` as the subject line. The reflow it triggers disables page
  annotation, and the document looks fine until you try to write on it.
- EPUB and DOCX only allow sticky notes, not writing on the page.
- Amazon's export links expire after 7 days, so fetch on arrival.
- Amazon drops mail from an unapproved sender **silently**, with no bounce. An
  empty outbox and a delivered document look identical from the device.
- Sending from a VPS often needs SMTP port 587 rather than 465; hosts block 465
  routinely and the only symptom is a timeout.
- iCloud offers submission on 587 only. Outlook.com cannot do this at all any
  more — Microsoft removed password sign-in for third-party IMAP/SMTP on
  personal accounts in 2024.

Self-hosted, MIT: https://github.com/starkshtlm/kindle-scribe-mcp

It runs on an ordinary mailbox over SMTP and IMAP, so no domain or mail
provider account is required; there is a Resend-backed path if you want push
delivery or your own sending domain. Documents stay on your own server.

---

## Hacker News — Show HN, for people who build with agents

**Title:** Show HN: An MCP server that turns handwriting on a Kindle Scribe into edits

The loop: ask an assistant for a draft, it renders a pen-friendly PDF and mails
it to the device, you annotate it with the stylus, share it back by email, and
the server hands the pages to the model as images along with the markdown it
was rendered from — so the model can say what your handwriting *changes*, not
just what it sees.

It is an MCP server, so it is not tied to one assistant: `./scribe connect`
registers it with Claude Code, Codex CLI, the Codex IDE extension or the
ChatGPT desktop app, and anything else speaking the protocol works too.

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

MIT, self-hosted, no account with me or anyone else:
https://github.com/starkshtlm/kindle-scribe-mcp

Quick start is an email account you already have, Docker, and five minutes. The
only step that can never be automated is the share tap on the device — Amazon
has no API for it.

---

## Short — X, LinkedIn, anywhere with a scroll

I ask Claude for a draft. It is on my Kindle Scribe a minute later. I read it
in an armchair and cut a paragraph with the pen, writing the replacement in the
margin.

Then I ask it to read my handwriting. The strike-through becomes a deletion.
The arrow becomes an insertion, in the right place.

MCP server, self-hosted, MIT. Works with Claude, Codex and ChatGPT desktop:
https://github.com/starkshtlm/kindle-scribe-mcp

---

**Posting notes.** Lead with the recording if you have one. Expect three
questions: does it work with other e-readers (only devices you can write PDFs
on), does the handwriting have to be neat (no, but numbered headings help), and
where do the documents go (your server, nowhere else).
