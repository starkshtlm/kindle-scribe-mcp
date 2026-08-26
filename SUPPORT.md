# Support

## Something is broken

1. **`./scribe doctor`** — it tests the app password, the submission port, the
   mailbox login, the Resend domain and the renderers, and names the one that
   is broken. Most questions are answered here.
2. **[docs/troubleshooting.md](docs/troubleshooting.md)** — every entry is a
   real failure that cost real hours. The Resend "Enable Receiving" toggle, the
   `convert` subject line and blocked SMTP ports are the top three.
3. **[Open an issue](https://github.com/starkshtlm/kindle-scribe-mcp/issues)**
   with the output of `./scribe doctor --json`. Redact nothing except
   credentials; the addresses and hostnames are usually the clue.

## Something is unclear

Documentation gaps are bugs. Open an issue saying what you expected to find and
where you looked for it.

## A vulnerability

[SECURITY.md](SECURITY.md) — please do not use a public issue.

## Expectations

One maintainer, evenings and weekends. Issues get read; fixes for things that
lose documents or leak credentials get priority over everything else.
