# How mail moves

Sending and receiving are configured separately, because they do not cost the
same. Sending to your Kindle from a domain you do not own is an open relay and
no provider allows it, so outbound is always an address you control. Receiving
only needs somewhere the mail lands.

| | `MAIL_OUT` / `MAIL_IN` | Domain + DNS | Public HTTPS | Documents return |
|---|---|---|---|---|
| **Mailbox** (quick start) | `smtp` / `imap` | No | No | within a minute |
| **Hybrid** | `smtp` / `resend` | No | Yes | instantly |
| **Domain** | `resend` / `resend` | Yes | Yes | instantly |

Switching is two lines in `.env` and a restart. Nothing about your stored
documents changes. (`MAIL_TRANSPORT=mailbox|resend` from earlier versions still
works and maps onto the first and third rows.)

## Mailbox — nothing to expose

The bridge sends over SMTP from a mailbox you already have and polls the same
mailbox over IMAP. No domain, no DNS, no webhook, and **nothing has to be
reachable from the internet** for mail to work — only your assistant needs to
reach the bridge, and on a laptop that is localhost.

Progress is tracked by IMAP UID, not by the unread flag, so opening Amazon's
mail on your phone first does not hide the document. The folder is opened
read-only and bodies are read with `BODY.PEEK[]`: the bridge cannot change
anything in your mailbox, read state included.

A first run looks one day back, so pointing this at a mailbox with years of
Kindle exports does not import all of them.

## Hybrid — no domain, but push

[Resend](https://resend.com) gives every account a free `<id>.resend.app`
receiving address, so documents arrive by webhook the moment Amazon sends them
instead of on the next poll — without owning a domain. Sending still goes
through your own mailbox, which is also the address Amazon wants on its
approved-sender list.

Find the address under **Emails → Receiving** in the Resend dashboard. It is
not exposed through their API, so the dashboard is the only place it exists.

The bridge has to be reachable over HTTPS for the webhook — see
[remote-access.md](remote-access.md).

## Domain — your own sender

Pick this if you want mail to come from `you@yourdomain.com`, or if your
account cannot issue an app password (Google Workspace, depending on how it is
administered). Free tier covers 3,000 mails a month, 100 a day, one domain.

## Finishing a Resend path

The webhook cannot be created before the bridge is deployed, because it needs a
public URL. Once it is:

```bash
./scribe-finish https://bridge.yourdomain.com
```

That registers the webhook through Resend's API and writes its signing secret
into `.env` — the step that otherwise ends in a silent 503 and no documents.
On a domain of your own it also checks that **both** sending and receiving are
enabled, which is the setting people miss most often: the toggle in the
add-domain form does not always stick. On a `*.resend.app` address there is
nothing to verify, and it says so.

Re-running is safe: it reuses the webhook already pointing at that URL rather
than adding a second one.
