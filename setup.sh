#!/usr/bin/env bash
# Interactive first-run setup: writes .env and prints the exact steps that
# cannot be automated (Amazon's approved-sender list, Resend DNS records).
set -euo pipefail

cd "$(dirname "$0")"

bold() { printf '\033[1m%s\033[0m\n' "$1"; }
ask() { # ask VAR "prompt" ["default"]
  local __var=$1 __prompt=$2 __default=${3:-} __input
  if [ -n "$__default" ]; then
    read -r -p "$__prompt [$__default]: " __input
    __input=${__input:-$__default}
  else
    while [ -z "${__input:-}" ]; do read -r -p "$__prompt: " __input; done
  fi
  printf -v "$__var" '%s' "$__input"
}

# Check the tools before anything is asked or written. These used to be
# discovered on the line that generates the tokens, i.e. after seven answered
# questions, and `set -e` then killed the script without writing anything.
missing=()
command -v openssl >/dev/null 2>&1 || missing+=("openssl — usually preinstalled; on Debian/Ubuntu: apt install openssl")
command -v docker  >/dev/null 2>&1 || missing+=("docker — https://docs.docker.com/get-docker/")
if [ ${#missing[@]} -gt 0 ]; then
  bold "Missing tools:"
  printf '  - %s\n' "${missing[@]}"
  echo
  echo "Install them and run ./setup.sh again."
  exit 1
fi
docker compose version >/dev/null 2>&1 || {
  bold "Docker is installed but 'docker compose' is not available."
  echo "Install the Compose plugin: https://docs.docker.com/compose/install/"
  exit 1
}

gen() { openssl rand -hex "$1"; }

if [ -f .env ]; then
  read -r -p ".env already exists. Overwrite? [y/N]: " ans
  [[ ${ans:-n} =~ ^[Yy]$ ]] || { echo "Keeping existing .env."; exit 0; }
fi

bold "kindle-scribe-mcp setup"
cat <<'EOF'

Two ways to move mail between Claude and your Kindle:

  [1] Mailbox (fastest)  Uses an email account you already have. No domain,
      no DNS, no webhook — the bridge sends over SMTP and checks for returning
      documents over IMAP. Ready in about five minutes.
      You need: an app password (Gmail/iCloud/Outlook all support these;
      Google Workspace accounts do NOT — pick option 2 there).

  [2] Domain (Resend)    Your own sending domain with instant push delivery
      instead of polling. Needs a domain, DNS records and a Resend account.

Either way you also need your Kindle address from
amazon.com/mycd -> Preferences -> Personal Document Settings.

EOF
ask TRANSPORT_CHOICE "Which one? [1/2]" "1"

ask KINDLE_EMAIL "Your Kindle address (...@kindle.com)"
ask NTFY         "ntfy.sh topic for phone pushes (blank to skip)" " "
BRIDGE_TOKEN=$(gen 32)
MCP_TOKEN=$(gen 24)

if [ "$TRANSPORT_CHOICE" = "2" ]; then
  MAIL_TRANSPORT=resend
  ask RESEND_API_KEY "Resend API key (re_...)"
  ask MAIL_DOMAIN    "Your Resend domain (e.g. scribe.yourdomain.com)"
  ask FROM_LOCAL     "Sender local-part" "claude"
  ask INBOX_LOCAL    "Return-address local-part" "inbox"
  FROM_EMAIL="${FROM_LOCAL}@${MAIL_DOMAIN}"
  RETURN_EMAIL="${INBOX_LOCAL}@${MAIL_DOMAIN}"
else
  MAIL_TRANSPORT=mailbox
  ask SMTP_USER "Your email address (this becomes the approved sender)"
  echo
  echo "  App password, not your normal password:"
  echo "    Gmail    myaccount.google.com/apppasswords  (needs 2FA on)"
  echo "    iCloud   appleid.apple.com -> Sign-In and Security"
  echo "    Outlook  account.live.com/proofs/AppPassword"
  ask SMTP_PASSWORD "App password"
  # Recognise the common providers so nobody has to look up host names.
  case "${SMTP_USER##*@}" in
    gmail.com|googlemail.com) SMTP_HOST=smtp.gmail.com;   IMAP_HOST=imap.gmail.com ;;
    icloud.com|me.com|mac.com) SMTP_HOST=smtp.mail.me.com; IMAP_HOST=imap.mail.me.com ;;
    outlook.com|hotmail.com|live.com) SMTP_HOST=smtp-mail.outlook.com; IMAP_HOST=outlook.office365.com ;;
    yahoo.com) SMTP_HOST=smtp.mail.yahoo.com; IMAP_HOST=imap.mail.yahoo.com ;;
    *) ask SMTP_HOST "SMTP server"; ask IMAP_HOST "IMAP server" ;;
  esac
  FROM_EMAIL="${SMTP_USER}"
  RETURN_EMAIL="${SMTP_USER}"
fi

FROM_EMAIL="${FROM_LOCAL}@${MAIL_DOMAIN}"
RETURN_EMAIL="${INBOX_LOCAL}@${MAIL_DOMAIN}"  # enforced by the bridge
BRIDGE_TOKEN=$(gen 32)
MCP_TOKEN=$(gen 24)

cat > .env <<EOF
MAIL_TRANSPORT=${MAIL_TRANSPORT}
KINDLE_EMAIL=${KINDLE_EMAIL}
FROM_EMAIL=${FROM_EMAIL}
RETURN_EMAIL=${RETURN_EMAIL}
BRIDGE_TOKEN=${BRIDGE_TOKEN}
MCP_TOKEN=${MCP_TOKEN}
MCP_ALLOWED_HOSTS=*
NTFY_TOPIC=$(echo "$NTFY" | xargs)
INBOX_RETENTION_DAYS=30
INBOX_DIR=/data/inbox
OUTBOX_DIR=/data/outbox
RESEND_API_KEY=${RESEND_API_KEY:-}
RESEND_WEBHOOK_SECRET=
SMTP_HOST=${SMTP_HOST:-}
SMTP_PORT=465
SMTP_USER=${SMTP_USER:-}
SMTP_PASSWORD=${SMTP_PASSWORD:-}
IMAP_HOST=${IMAP_HOST:-}
IMAP_PORT=993
IMAP_POLL_SECONDS=60
EOF
chmod 600 .env

# The plugin skills read this file for the REST endpoint. Without it they have
# no bridge to talk to. BRIDGE_URL points at the local port; change it if you
# reach the bridge on a public hostname instead.
BRIDGE_ENV="$HOME/.scribe-bridge.env"
if [ -f "$BRIDGE_ENV" ]; then
  echo "Keeping existing $BRIDGE_ENV"
else
  cat > "$BRIDGE_ENV" <<EOF
BRIDGE_URL=http://127.0.0.1:8377
BRIDGE_TOKEN=${BRIDGE_TOKEN}
EOF
  chmod 600 "$BRIDGE_ENV"
fi

echo
bold "Wrote .env and $BRIDGE_ENV"
echo

if [ "$MAIL_TRANSPORT" = "mailbox" ]; then
cat <<EOF
$(bold "Two things left:")

1. Amazon: add this address to the Approved Personal Document E-mail List
   at amazon.com/mycd -> Preferences -> Personal Document Settings:
     ${FROM_EMAIL}

2. Start the bridge:
     docker compose up -d

That is it — no domain, no webhook, nothing to expose. Connect Claude Code:
     claude mcp add --transport http --scope user kindle-scribe \\
       http://127.0.0.1:8377/${MCP_TOKEN}/mcp

Ask Claude to send something to your Kindle, write on it, then share it by
email back to ${RETURN_EMAIL} — the bridge checks that mailbox every minute.

Want it available in claude.ai chats too? Put the bridge behind public HTTPS
(see README) and use that hostname in the connector URL instead.
EOF
else
cat <<EOF
$(bold "Do these three things now:")

1. Amazon: add this address to the Approved Personal Document E-mail List
     ${FROM_EMAIL}

2. Start the bridge and expose it over public HTTPS:
     docker compose up -d
   Then put a TLS proxy in front of 127.0.0.1:8377 (Caddy one-liner and
   platform options are in the README), so it answers on e.g.
     https://bridge.yourdomain.com/healthz

3. Register the Resend webhook — let the script do it:
     ./scribe-finish https://<your-public-host>

   That creates the webhook, stores its signing secret in .env and restarts
   the bridge. It also checks that your domain has BOTH sending and receiving
   enabled, which is the setting people most often miss.

   Until the signing secret is set the bridge answers 503 to every delivery and
   nothing you share from the Scribe arrives. Resend keeps inbound mail for 30
   days, so nothing is lost while you finish this.

Then add the connector in Claude with this URL:
     https://<your-public-host>/${MCP_TOKEN}/mcp

And on the Scribe, share annotated documents by email to:
     ${RETURN_EMAIL}
EOF
fi

echo
echo "Full walkthrough: README.md — stuck? docs/troubleshooting.md"
