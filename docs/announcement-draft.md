# Announcement drafts (not published — review before posting)

## r/kindlescribe

**Title:** I built a bridge so Claude can send me documents and read my handwritten notes back

I read and think better on paper, but everything I work on lives in a chat window. So I wired the two together: I ask Claude to send me a draft, it lands on my Scribe a minute later, I read it in an armchair and scribble on it with the pen, tap Share → email, and then Claude reads my handwriting and acts on it.

The part I didn't expect to work as well as it does: it reads *layout*, not just words. Strike-through means delete, an arrow from the margin means insert here, a circled word means that one. I corrected a factual error by crossing out a word and writing the replacement in the margin, and it understood the intent without being told.

How it works underneath: documents go out over Send-to-Kindle email as PDFs with a deliberately wide right margin (writing room), and come back through the Scribe's own share-by-email — a small server catches Amazon's export mail, pulls the annotated PDF, and hands the pages to Claude as images. The only manual step in the whole loop is the Share tap, since Amazon has no API.

It's free and self-hosted (MIT): https://github.com/starkshtlm/kindle-scribe-mcp

You need a Scribe, a free Resend account and a domain. Setup is about 30 minutes, mostly waiting for DNS. Happy to help anyone who gets stuck.

---

## MobileRead forum

**Title:** Open source: Claude ↔ Kindle Scribe round-trip (send, annotate by hand, read back)

Sharing a project that closes the loop between an LLM and the Scribe's pen.

Outbound uses Send-to-Kindle email with PDFs formatted for the device — 3:4 page ratio so it fills the screen, wide right margin as writing space, generous leading. Inbound uses the Scribe's built-in share-by-email: a webhook catches Amazon's export notification, follows the download link before it expires, and stores the annotated PDF. The handwriting is then read by the model's vision rather than OCR, so marginalia, strike-throughs and arrows are interpreted in context.

Notes for anyone attempting something similar:

- PDFs must arrive **by email** to be writable — USB-transferred PDFs cannot be annotated on the page
- Never use `convert` as the subject line; the reflow it triggers disables page annotation
- EPUB/DOCX only allow sticky notes, not writing on the page
- Amazon's export links expire after 7 days, so fetch them on arrival

Self-hosted, MIT licensed: https://github.com/starkshtlm/kindle-scribe-mcp

Requires a free Resend account for mail in both directions and a domain for the receiving address. Documents stay on your own server.

---

## Short version (Hacker News / X / LinkedIn)

Claude sends a document to my Kindle Scribe. I read it in an armchair, mark it up with the pen, tap share. Claude reads my handwriting — strike-throughs, margin arrows, circled words — and makes the edits.

Self-hosted, MIT: https://github.com/starkshtlm/kindle-scribe-mcp

---

**Posting tips:** a 20-second screen recording of the round trip (send → scribble → Claude's interpretation) will do more than any of this text. Post when you can be around for a few hours to answer questions — that is what turns a link into a conversation.
