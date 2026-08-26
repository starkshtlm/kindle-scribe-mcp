# Contributing

This is a solo-maintained project that people trust with their mailbox
credentials, so the bar is less about process and more about not breaking that
trust.

## Before a pull request

```bash
python3 -m pip install -r server/requirements.txt pytest
python3 -m pytest server/test_security.py -q
```

CI runs the same tests, builds the image, and boots it in three configurations.
A red CI is not a formality here — most of those checks exist because something
failed in real use.

## What gets merged quickly

**A troubleshooting entry for something that cost you hours.** The most
valuable file in this repo is the list of traps, and every entry came from
someone losing an afternoon.

**A client report.** "I connected it to X, the images rendered, the model read
my handwriting" — or did not. `docs/clients/README.md` has a column this
project cannot fill in alone.

**A fix with a test that fails without it.** Especially anywhere near
`store_document`.

## What needs a conversation first

Anything touching the inbound trust boundary — sender verification, link
validation, replay handling. Open an issue describing the case before writing
code; the checks look redundant and are not.

Anything that adds a dependency. The image installs a lock file so builds are
reproducible; a new package means regenerating it (the header in
`server/requirements.lock` has the command).

## House style

- Comments explain *why*, and are worth writing when the reason is not obvious
  from the code. Comments that restate the line are noise.
- Documentation must be true. A test asserts every setting appears in
  `.env.example` and every README link resolves, because documentation drifted
  once and nobody noticed for four releases.
- No absolute claims without proof — "always", "never", "any client",
  "nothing leaves". If it has not been run, say what has.

## Security

Do not open a public issue for a vulnerability. [SECURITY.md](SECURITY.md) has
the reporting path.
