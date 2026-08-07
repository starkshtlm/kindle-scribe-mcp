---
name: scribe-send
description: Send a document to the user's Kindle Scribe for reading and handwritten feedback. Use when the user says "send to Scribe/Kindle", "/scribe-send", or wants a document, draft or plan to read and annotate on their Kindle Scribe.
---

# Send a document to the Kindle Scribe

## Configuration

Read `~/.scribe-bridge.env` (`BRIDGE_URL=...`, `BRIDGE_TOKEN=...`). If it is
missing, tell the user the bridge is not configured yet and point them at the
repository README.

If the `kindle-scribe` MCP server is connected, prefer its `send_to_scribe`
tool — it renders the PDF server-side and needs no local browser. Use the
steps below when running against the REST endpoint instead.

## Steps

1. **Determine the source.** Already a PDF → skip to step 3. Markdown or text
   (a file, or content you wrote) → step 2.

2. **Render the PDF** using `assets/template.html` (relative to this skill):
   - Convert the content to HTML and substitute `{{TITLE}}`, `{{META}}` and
     `{{BODY}}`. Set `{{META}}` to the date plus short context, e.g.
     `2026-08-07 · Draft v2 · Sent by Claude`.
   - **Number the headings** (1, 1.1, 2 …) so the user's handwritten
     references are unambiguous when the document comes back.
   - The template deliberately has a wide right margin and generous line
     spacing — that is writing room for the stylus. Do not change the page
     size (3:4 matches the Scribe's screen).
   - Render with headless Chrome:
     ```
     "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
       --headless --disable-gpu --no-pdf-header-footer \
       --print-to-pdf=<out.pdf> <in.html>
     ```
     On Linux use `google-chrome`/`chromium`. No Chrome available? Use
     `weasyprint <in.html> <out.pdf>`.

3. **Send:**
   ```
   curl -sf -X POST "$BRIDGE_URL/send" \
     -H "Authorization: Bearer $BRIDGE_TOKEN" \
     -F "file=@<file.pdf>"
   ```
   Give the PDF a descriptive filename first — it becomes the document title
   on the Kindle.

4. **Confirm** to the user: it appears on the Scribe within a minute (the
   device needs wifi). Briefly remind them of the return path: write on the
   pages with the stylus, then **Share → Send by email** to the return
   address, and the bridge picks it up automatically.

## Handwritten notes coming the other way

The user can also **write by hand in a blank notebook on the Scribe** and share
it to the return address — the bridge accepts it exactly like an annotated
document. Mention this when they want to sketch something by hand, keep a
journal, or turn meeting scribbles into text.

## Important

- Always send a **PDF attachment** — never EPUB or DOCX (you cannot write
  directly on those pages, only attach sticky notes) and never with the
  subject line `convert`.
- Keep documents under 45 MB.
