# MobileRead

The most technically curious reader audience there is. The trap list is the
gift here — it is what someone attempting this themselves would pay for.

---

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

**Notes.** Expect follow-up questions about DRM, formats and whether this works
on older Kindles. It does not: writing on the page needs a Scribe.
