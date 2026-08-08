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

You need two accounts before continuing:
  1. resend.com  — free tier is plenty. Add a domain (a SUBdomain such as
     scribe.yourdomain.com is recommended so it cannot disturb your normal
     mail), set the DNS records it shows, and enable BOTH Sending and
     Receiving. Note: the "Enable Receiving" toggle must be switched on from
     the domain's page after the domain verifies — turning it on in the
     add-domain form does not always stick.
  2. amazon.com/mycd -> Preferences -> Personal Document Settings, where you
     find your @kindle.com address.

EOF
read -r -p "Press enter when both are ready. "

echo
ask RESEND_API_KEY   "Resend API key (re_...)"
ask KINDLE_EMAIL     "Your Kindle address (...@kindle.com)"
ask MAIL_DOMAIN      "Your Resend domain (e.g. scribe.yourdomain.com)"
ask FROM_LOCAL       "Sender local-part" "claude"
ask INBOX_LOCAL      "Return-address local-part" "inbox"
ask NTFY             "ntfy.sh topic for phone pushes (blank to skip)" " "
# The webhook signing secret is deliberately not asked for here: it does not
# exist until the service is running on a public URL and the webhook has been
# registered in Resend. Step 3 below fills it in.

FROM_EMAIL="${FROM_LOCAL}@${MAIL_DOMAIN}"
RETURN_EMAIL="${INBOX_LOCAL}@${MAIL_DOMAIN}"  # enforced by the bridge
BRIDGE_TOKEN=$(gen 32)
MCP_TOKEN=$(gen 24)

cat > .env <<EOF
RESEND_API_KEY=${RESEND_API_KEY}
RETURN_EMAIL=${RETURN_EMAIL}
KINDLE_EMAIL=${KINDLE_EMAIL}
FROM_EMAIL=${FROM_EMAIL}
BRIDGE_TOKEN=${BRIDGE_TOKEN}
MCP_TOKEN=${MCP_TOKEN}
MCP_ALLOWED_HOSTS=*
RESEND_WEBHOOK_SECRET=
NTFY_TOPIC=$(echo "$NTFY" | xargs)
INBOX_RETENTION_DAYS=30
INBOX_DIR=/data/inbox
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
bold "Do these three things now:"
cat <<EOF

1. Amazon: add this address to the Approved Personal Document E-mail List
     ${FROM_EMAIL}

2. Start the bridge and expose it over public HTTPS:
     docker compose up -d
   Then put a TLS proxy in front of 127.0.0.1:8377 (Caddy one-liner and
   platform options are in the README), so it answers on e.g.
     https://bridge.yourdomain.com/healthz

3. Resend -> Webhooks -> Add webhook:
     URL:   https://<your-public-host>/webhook/inbound
     Event: email.received
   Put the signing secret it shows into RESEND_WEBHOOK_SECRET in .env and
   restart (docker compose up -d).

   This step is NOT optional. Until RESEND_WEBHOOK_SECRET is set the bridge
   answers 503 to every delivery and nothing you share from the Scribe will
   arrive. Resend keeps inbound mail for 30 days, so nothing is lost while you
   finish this.

Then add the connector in Claude with this URL:
     https://<your-public-host>/${MCP_TOKEN}/mcp

And on the Scribe, share annotated documents by email to:
     ${RETURN_EMAIL}

Full walkthrough: README.md — stuck? docs/troubleshooting.md
EOF
