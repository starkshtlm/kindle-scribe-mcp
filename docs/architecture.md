# Architecture

A small FastAPI service you run yourself, exposing an MCP server and a REST
endpoint, that moves documents to and from a Kindle by email.

```
   MCP client                 the bridge                     Amazon
┌───────────────┐          ┌──────────────┐               ┌─────────┐
│ Claude · Codex│ send_to_ │ markdown →   │  SMTP or      │ Send to │
│ ChatGPT · any │─scribe──▶│ HTML → PDF   │──Resend──────▶│ Kindle  │──▶ device
│               │          │ (weasyprint) │               └─────────┘
│               │          │              │                    │ share by email
│               │  get_    │ store_       │  IMAP poll or      ▼
│               │◀annotated│ document ◀───│◀─Resend webhook ◀ export mail
└───────────────┘          │ page images  │                 (download link)
                           │ (pdftoppm)   │
                           └──────────────┘
```

## The one function that matters

Everything inbound meets in `store_document`. Both transports — the IMAP poll
and the Resend webhook — build the same dictionary and hand it to that
function, which is where every check lives: is this addressed to us, did a
receiving server verify the sender, is this link one we may follow, have we
seen this delivery before.

That is deliberate. Two inbound paths with two sets of checks would be two
different products, and the second one would be the one with the hole in it.

## Outbound

`send_to_scribe` takes markdown, renders it through a template built for the
device (3:4 page, wide right margin, generous leading), and mails the PDF.

Before rendering, external references are stripped from the markdown and images
are fetched separately, size-capped and embedded as data URIs — WeasyPrint
dereferences anything it is handed and has no flag to stop it, so the fetching
is done where it can be constrained.

The markdown is kept in an outbox so a returning document can be paired with
what it was made from.

## Inbound

Amazon's export mail carries a link, not an attachment. The bridge follows it
by hand rather than trusting a redirect chain: HTTPS only, an Amazon-owned host
on the first hop, publicly-routable addresses on every hop, a capped number of
hops, and a streamed download with a hard byte limit.

On the mailbox path, progress is a UID checkpoint rather than the unread flag,
and the folder is opened read-only — the bridge cannot alter anything in a
mailbox it is given access to.

## Reading

`get_annotated` rasterises pages with `pdftoppm` and returns them as images,
paginated to stay under the client's payload limit, with the original markdown
in the first reply. The model reads the pages; there is no OCR step, because
the position of a mark is most of its meaning.

## What runs where

The container holds the service, weasyprint and poppler. It runs unprivileged
with a read-only filesystem and dropped capabilities, because it parses PDFs
that strangers mailed you.

`./scribe` runs on your machine, not in the container: it reads `.env`, tests
the things only reachable from outside (mail login, the endpoint, the client
configuration) and shells into the container for the renderers.

State is a Docker volume: stored documents, the outbox, the replay record and
the IMAP checkpoint. No database.
