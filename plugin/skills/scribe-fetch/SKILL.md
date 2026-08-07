---
name: scribe-fetch
description: Fetch annotated documents back from the user's Kindle Scribe and interpret the handwritten feedback. Use when the user says "/scribe-fetch", "fetch from Scribe/Kindle", "I'm done commenting", or asks whether a document has come back.
---

# Fetch and interpret feedback from the Kindle Scribe

## Configuration

Read `~/.scribe-bridge.env` (`BRIDGE_URL`, `BRIDGE_TOKEN`). If missing, point
the user at the repository README.

If the `kindle-scribe` MCP server is connected, prefer its `list_annotated` /
`get_annotated` / `ack_annotated` tools — they hand you page images directly.
Use the steps below for the REST endpoint.

## Steps

1. **List new documents:**
   ```
   curl -sf "$BRIDGE_URL/inbox?new=1" -H "Authorization: Bearer $BRIDGE_TOKEN"
   ```
   Empty result → say so, and remind the user they must tap **Share → Send by
   email** on the Scribe. Amazon's export mail can take a few minutes.

2. **Download each new PDF** to your scratch directory:
   ```
   curl -sf "$BRIDGE_URL/inbox/<id>/file" \
     -H "Authorization: Bearer $BRIDGE_TOKEN" -o <id>.pdf
   ```

3. **Interpret with vision.** Read the PDF page by page. The handwriting is
   embedded exactly where the user wrote it. For every annotated page:
   - Transcribe the handwritten text verbatim.
   - Note what it points at: circles, underlines, arrows, strike-throughs,
     margin notes — and which section of the original it concerns (use the
     section numbers).
   - Classify: **change** (do this), **question** (answer it), **comment**
     (note it), **delete** (remove). Struck-through text means "remove";
     margin text with an arrow into a paragraph usually means "add/replace
     here".
   - Unsure of a word? Give your best reading marked "(uncertain: ...)"
     rather than guessing silently.
   - **Read every page before summarizing.** Long documents may need several
     passes; never summarize from a partial read.

4. **Summarize and act.** Present a list: section → transcribed feedback →
   your interpretation. If the feedback concerns a document you have the
   source for, make the changes, answer the questions, and offer to send the
   new version back to the Scribe for another round.

5. **Acknowledge** when a document is fully processed so it is not fetched
   again:
   ```
   curl -sf -X POST "$BRIDGE_URL/inbox/<id>/ack" \
     -H "Authorization: Bearer $BRIDGE_TOKEN"
   ```
