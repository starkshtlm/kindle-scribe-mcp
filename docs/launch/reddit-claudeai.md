# r/ClaudeAI (and Claude Code communities)

People who already extend their assistant and will immediately understand what
a new interface for it is worth.

---

**Title:** I gave Claude a handwriting interface — annotate its output on paper, hand it back, it revises

Most of my Claude usage is producing or reshaping long documents. The bit that
never worked well was reviewing them: I would read a memo in the same window I
asked for it in, and skim what I should have argued with.

So I built an MCP server that closes the loop through paper. Claude renders the
document as a pen-friendly PDF and mails it to my Kindle Scribe. I mark it up
with the stylus, share it back by email, and Claude reads the pages as images.

Three things that turned out to matter more than I expected:

**It reads marks, not just text.** Strike-through is a deletion, a margin arrow
is an insertion pointing at a specific paragraph, a circled word scopes the
note to that word. No notation has to be explained, because the model sees the
page rather than a transcript. OCR would throw away exactly the part that
carries the meaning — *where* something is written.

**Returning the original with the pages changes the answer.** The server keeps
the markdown it rendered, and hands it back alongside the images. So Claude
does not describe a page; it tells you what your handwriting *changes* about
the text it wrote. "You removed the market assumption and asked for a
board-level framing" rather than "there is writing in the margin".

**A prompt worth stealing:** ask it to list the decisions before rewriting
anything. A model that rewrites first will smooth over whatever it misread.

It is an MCP server, so it is not Claude-only — `./scribe connect` also
registers it with Codex and ChatGPT desktop — but Claude Code is where I run
it, including a scheduled task that reads returning documents and pushes me the
summary before I ask.

Self-hosted, MIT, no account with anyone:
https://github.com/starkshtlm/kindle-scribe-mcp

Setup is an email account you already have plus Docker. The only manual step in
the whole loop is the share tap on the device, because Amazon has no export
API.

---

**Notes.** This audience will ask about the MCP details — tool shape,
pagination, how the images get to the model. Answer specifically; it is the
fastest way to earn a star from someone who builds their own servers.
