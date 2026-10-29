#!/usr/bin/env bash
# Step-by-step check of the path to the GPU server. Read-only: starts no VPN, asks for no password,
# changes no routes. Guide: docs/team/SERVER_ACCESS_RU.md.
#   scripts/server_access_check.sh            # defaults below
#   DB_SERVER_HOST=... DB_SERVER_USER=... scripts/server_access_check.sh
set -u

HOST="${DB_SERVER_HOST:-195.19.35.82}"
SSH_USER="${DB_SERVER_USER:-user}"
BOGUS="192.0.2.77" # TEST-NET-1: nothing can answer here, so any "success" is a fake

ok() { printf '  OK    %s\n' "$*"; }
warn() { printf '  WARN  %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; }
note() { printf '        %s\n' "$*"; }

echo "1. Route to $HOST"
route="$(ip route get "$HOST" 2>&1 | head -1)"
note "$route"
case "$route" in
*" dev tun"* | *" dev tap"*) ok "goes through the university VPN" ;;
*vpn0* | *" dev utun"* | *" dev sb"* | *" dev Meta"*)
	note "goes through a local proxy TUN (sing-box, clash, ...). Fine at the university,"
	note "from outside the university the university VPN (tun0) must be up and win this route." ;;
*) note "goes straight through the network card (expected only inside the university network)" ;;
esac

echo "2. Does a local TUN proxy fake TCP connections?"
if timeout 4 bash -c "exec 3<>/dev/tcp/$BOGUS/22" 2>/dev/null; then
	warn "a connection to $BOGUS:22 'succeeded'. A TUN proxy answers TCP itself."
	note "Do NOT trust nc -vz, telnet or a port scanner. Only step 3 (banner) and step 4 (ssh) count."
else
	ok "no fake handshakes"
fi

echo "3. SSH banner from $HOST:22 (a real answer, not a handshake)"
banner="$(timeout 8 bash -c "exec 3<>/dev/tcp/$HOST/22 && read -t 6 -r line <&3 && printf '%s' \"\$line\"" 2>/dev/null | tr -d '\r')"
case "$banner" in
SSH-*) ok "$banner" ;;
*)
	bad "no SSH banner received"
	note "The server is not reachable on this path: the university VPN is down, the server is off,"
	note "or a TUN proxy swallows the connection. Next: docs/team/SERVER_ACCESS_RU.md, section 'Если не работает'."
	exit 1 ;;
esac

echo "4. Login with your key as $SSH_USER (no password, no prompts)"
out="$(timeout 20 ssh -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new "$SSH_USER@$HOST" \
	'hostname; uptime -p' 2>&1)"
rc=$?
if [ "$rc" -eq 0 ]; then
	ok "logged in"
	printf '%s\n' "$out" | sed 's/^/        /'
elif printf '%s' "$out" | grep -q "Permission denied"; then
	bad "the server is reachable, but it does not accept your key"
	note "Send your PUBLIC key (~/.ssh/id_ed25519.pub) to the team lead; see the guide, section 3."
	exit 2
else
	bad "ssh failed (exit $rc)"
	printf '%s\n' "$out" | tail -3 | sed 's/^/        /'
	exit 3
fi
