#!/usr/bin/env bash
# Install the Tailscale client on a team laptop (Ubuntu or Debian) and join the team tailnet.
# Interactive: sudo asks for your password; "tailscale up" prints a login URL to open in the browser.
# Does not touch DNS (--accept-dns=false). Plan: docs/team/SERVER_TAILSCALE_RU.md.
set -euo pipefail

. /etc/os-release
DISTRO="${ID:-}"
CODENAME="${VERSION_CODENAME:-}"
case "$DISTRO" in
ubuntu | debian) ;;
*) echo "Unsupported distro '$DISTRO'. Install from https://tailscale.com/download and run: sudo tailscale up --accept-dns=false" >&2; exit 1 ;;
esac

sudo -v
if ! command -v tailscale >/dev/null 2>&1; then
	sudo mkdir -p --mode=0755 /usr/share/keyrings
	curl -fsSL "https://pkgs.tailscale.com/stable/$DISTRO/$CODENAME.noarmor.gpg" |
		sudo tee /usr/share/keyrings/tailscale-archive-keyring.gpg >/dev/null
	curl -fsSL "https://pkgs.tailscale.com/stable/$DISTRO/$CODENAME.tailscale-keyring.list" |
		sudo tee /etc/apt/sources.list.d/tailscale.list >/dev/null
	sudo apt-get update
	sudo apt-get install -y tailscale
fi
sudo systemctl enable --now tailscaled
sudo tailscale up --accept-dns=false
echo "== result =="
tailscale status | head -5
echo "my tailscale ip: $(tailscale ip -4 | head -1)"
