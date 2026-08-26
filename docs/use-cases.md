# What to send, and what to write on it

The bridge does not care what a document is. What follows is what has actually
turned out to be worth the round trip, and the prompts that make the return
half work.

## Worth the trip

**A strategy or board memo.** The one you will be questioned on. Reading it on
a screen you also write on invites editing sentences; reading it in an armchair
invites disagreeing with the argument.

**An AI-generated analysis you suspect is too smooth.** Market sizing,
competitor summaries, risk assessments. The failure mode is plausible prose
built on an assumption nobody stated. Crossing that assumption out by hand is
faster than explaining it in a chat.

**An operating plan, investment memo or product strategy.** Long, structured,
and full of places where a single margin note changes a section.

**A PRD or an org proposal.** Documents where the shape matters as much as the
words, and where "this belongs in section 2" is a spatial thought.

**Meeting preparation.** Print the brief, mark what you intend to raise, and
let the model turn your marks into talking points before you walk in.

**A long report while travelling.** No laptop, no notifications, and the
reading still produces something when you land.

**Anything sensitive enough to deserve a slower pass.** The pen enforces a pace
a scroll wheel does not.

## What to write

The interpretation is good at ordinary editing notation and gets better the
less ambiguous you are:

| Mark | Read as |
|---|---|
| Strike-through | Delete this |
| Margin text with an arrow | Insert or replace here |
| Circled word or phrase | This one, not the sentence around it |
| Bracket down the margin | This whole block |
| `?` beside a claim | Challenge or verify this |

Two habits that pay for themselves:

**Ask for numbered headings** when you request the document. A note saying
"see 2.3" then lands unambiguously, and the model can quote what it changed.

**Write instructions, not just reactions.** "Weak" tells the model something is
wrong; "reframe for the board — this is too operational" tells it what to do.

## Prompts that work on the way back

> read my Kindle feedback and revise the memo

> read what came back and list only the decisions I made — do not rewrite
> anything yet

> compare my handwriting against the original and tell me what I changed my
> mind about

The second one is worth knowing. When the marks are extensive it is better to
have the decisions listed and confirmed before a rewrite, because a model that
rewrites first will smooth over anything it misread.

## Blank pages count

Write in a blank Scribe notebook and share it the same way. There is no
original to compare against, so it arrives as a standalone note — useful for
turning a page of longhand thinking into text without typing it.
