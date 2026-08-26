# r/kindlescribe

Device owners. They already have the hardware and the habit; what is new is
that the pen can now talk back.

---

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

**Notes.** Answer setup questions in the thread rather than linking to the
README. This subreddit is small and generous; treat it as a conversation.
