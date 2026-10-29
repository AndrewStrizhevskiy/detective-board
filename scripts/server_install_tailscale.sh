#!/usr/bin/env bash
# Run ON THE SERVER (Debian 13 trixie), interactively: sudo asks for the password, the Tailscale auth key is read
# silently (never passed through chat or stored). Plan and rollback: docs/team/SERVER_TAILSCALE_RU.md.
# Changes: adds the Tailscale apt repo, installs the package, joins the tailnet with the tag tag:dbserver.
# Does not touch sshd, the firewall or DNS (--accept-dns=false).
set -euo pipefail

CODENAME="$(. /etc/os-release && printf '%s' "${VERSION_CODENAME:-}")"
if [ "$CODENAME" != "trixie" ]; then
	echo "Expected Debian trixie, found '$CODENAME'. Pick the matching URLs at https://pkgs.tailscale.com/stable/ and edit this script." >&2
	exit 1
fi

echo "== sudo (enter the password of $USER) =="
sudo -v

if command -v tailscale >/dev/null 2>&1; then
	echo "== tailscale already installed: $(tailscale version | head -1) =="
else
	echo "== adding the Tailscale apt repository and installing =="
	sudo mkdir -p --mode=0755 /usr/share/keyrings
	curl -fsSL "https://pkgs.tailscale.com/stable/debian/$CODENAME.noarmor.gpg" |
		sudo tee /usr/share/keyrings/tailscale-archive-keyring.gpg >/dev/null
	curl -fsSL "https://pkgs.tailscale.com/stable/debian/$CODENAME.tailscale-keyring.list" |
		sudo tee /etc/apt/sources.list.d/tailscale.list >/dev/null
	sudo apt-get update
	sudo apt-get install -y tailscale
fi
sudo systemctl enable --now tailscaled

if [ -n "$(sudo tailscale ip -4 2>/dev/null)" ]; then
	echo "== already joined: $(sudo tailscale ip -4 | head -1) =="
else
	printf 'Tailscale auth key (tskey-..., input hidden; Enter to skip and join later): '
	read -r -s KEY
	echo
	if [ -n "$KEY" ]; then
		KEYFILE=""
		ARG="--auth-key=$KEY"
		# keep the key out of the process list when this tailscale version reads it from a file
		if tailscale up --help 2>&1 | grep -q 'file:'; then
			KEYFILE="$(mktemp)"
			chmod 600 "$KEYFILE"
			printf '%s' "$KEY" >"$KEYFILE"
			ARG="--auth-key=file:$KEYFILE"
		fi
		sudo tailscale up "$ARG" --hostname=dbserver --advertise-tags=tag:dbserver --accept-dns=false
		if [ -n "$KEYFILE" ]; then rm -f "$KEYFILE"; fi
		unset KEY ARG KEYFILE
	else
		echo "Skipped. Later: sudo tailscale up --auth-key=tskey-... --hostname=dbserver --advertise-tags=tag:dbserver --accept-dns=false"
	fi
fi

echo "== result =="
sudo tailscale status 2>&1 | head -5 || true
echo "tailscale ip: $(sudo tailscale ip -4 2>/dev/null | head -1)"
echo "tailscaled enabled: $(systemctl is-enabled tailscaled)"
echo "== sshd (read only) =="
sudo sshd -T | grep -E '^(passwordauthentication|pubkeyauthentication|permitrootlogin) '
