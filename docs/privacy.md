# Where your documents go

"Self-hosted" answers where documents are *stored*. It does not answer who
*processes* them, and for a system whose whole purpose is having a model read
your handwriting, the second question is the one that matters.

## Stored

On the machine running the bridge, in the `scribe-data` Docker volume:

- the annotated PDFs that came back, and their metadata
- the markdown of everything sent out, so a returning document can be paired
  with what it was made from
- a replay record and the IMAP checkpoint

Deleted after `INBOX_RETENTION_DAYS`, 30 by default; `0` keeps them forever.
Nothing is copied anywhere else by the bridge.

## Processed

Every one of these is a consequence of a choice you make, and none of them
involves an account with this project.

**Your mail provider and Amazon.** The document travels as email in both
directions: out through SMTP or Resend to your Send-to-Kindle address, back
through Amazon's export mail and the link it contains. Amazon holds the
exported PDF for seven days behind that link. Your provider holds the mail as
long as your mailbox does.

**Whichever AI you are using.** Reading handwriting means sending page images
to a model. `get_annotated` returns PNGs of the pages, and the client sends
them to its provider — Anthropic, OpenAI or whoever runs the assistant you
connected. This is not different from pasting the pages into a chat yourself,
but it is worth saying plainly: **the pages leave your server the moment you
ask the model to read them.** That is what makes the feature work.

The same applies to the original markdown, which travels with the pages so the
model can compare them.

**Resend**, if `MAIL_IN=resend` or `MAIL_OUT=resend`. Inbound mail is stored by
Resend for 30 days and fetched from their API. On the mailbox path Resend is
not involved at all.

**ntfy.sh**, if `NTFY_TOPIC` is set. It carries whatever `push_summary` sends
and the rejection notices — summaries and error text, not documents. The topic
name is the only access control, so use a long random one; anyone who guesses
it can subscribe.

**Your public hostname, or a Cloudflare Worker**, if you expose the bridge for
phone or claude.ai use. Then MCP traffic — including page images — passes
through that hop. On the quick-start path nothing is exposed and the bridge
answers only on localhost.

## The credential worth thinking about

An app password is not scoped to a folder. The bridge reads only Amazon's mail
and **cannot write at all** — the folder is opened read-only and bodies are
read with `BODY.PEEK[]`, so not even the read/unread flag changes. But the
credential itself would permit more, and it sits in `.env` in plain text like
every other secret here.

If that matters to you, point `IMAP_USER` and `IMAP_PASSWORD` at a dedicated
address that receives only Kindle exports, or use a Resend path, where the
bridge never holds a mailbox credential.

## What the bridge refuses

Inbound mail is untrusted until proven otherwise: it must be addressed to your
`RETURN_EMAIL` and a receiving server must have verified that it came from
Amazon. Rejections are logged and pushed, never silently dropped. The details,
including what a forged sender can and cannot do, are in
[SECURITY.md](../SECURITY.md).

## One person per deployment

There is no multi-user isolation. One bridge serves one mailbox and one Kindle.
Do not point several people at a shared instance and expect their documents to
be separated, because nothing separates them.
