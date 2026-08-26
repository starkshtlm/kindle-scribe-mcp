# Roadmap

What I intend to work on, ordered by how much friction it removes. No dates —
this is built in evenings, and a date I miss is worse than no date.

Open an issue if something here matters to you, or if something not here does.

## Now

**Pair a returning document with the right original, every time.** The markdown
of a sent document is currently keyed by its title, so sending two drafts with
the same name overwrites the first — and the one that comes back is then
compared against the wrong text, confidently. This is a correctness bug, and it
is next.

## Next

**Fewer steps to the first document.** Setup asks for things it could work out,
and the Amazon approved-sender step is still a paragraph of instructions. The
target is that a first-time user reaches "it is on my Kindle" without reading
the README twice.

**A first loop that proves itself.** `doctor → test → verify` exists; it should
be what a new install runs automatically, so the answer to "did it work" is
never inferred from silence.

**Templates worth reading on paper.** The current PDF is shaped for annotation.
Documents that are *structured* for review — a decision summary that fits a
page, numbered claims, a margin column that invites a verdict — would make the
pen do more.

**Notifications that respect attention.** Today it is one push per arrival. A
digest, quiet hours, and a way to say "read this one automatically, ask me
about that one" would suit how people actually work.

## Later

**More verified clients.** Codex and ChatGPT desktop are registered and
answering; nobody has yet confirmed the images render well enough for the model
to read handwriting. Every additional confirmed client makes the table in
`docs/clients/` less of a promise and more of a record.

**Authentication that is not a token in a URL.** A path secret is what today's
connector UIs accept. When bearer auth or OAuth is broadly supported, this
should move — the current scheme is documented as a limitation, not a design.

**A path for people who will never run Docker.** Everything here assumes you
can self-host. A managed option would reach the people the workflow suits best
and who are least likely to install it — and it would mean holding other
people's handwriting, which is a different kind of responsibility and needs to
be entered deliberately, not by accident.

## Not planned

**Removing the share tap.** Amazon publishes no export API. If that changes,
this moves to Now.

**Multi-user support in the self-hosted bridge.** One deployment, one person.
Making it multi-tenant without the isolation work would be worse than not
offering it.
