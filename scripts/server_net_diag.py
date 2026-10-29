#!/usr/bin/env python3
"""Run ON THE SERVER (inside the university network): why does Tailscale's control long-poll stall?

Opens keep-alive HTTPS connections to Tailscale's control plane and to two other hosts, sends a request, stays
idle for N seconds, sends again. A silent drop (no answer, no reset) after N seconds means a firewall on the path
forgets or kills the connection. Comparing hosts tells whether only Tailscale is affected. Optional --proxy checks
whether the university proxy reaches the control plane. Read-only, about two minutes. Guide:
docs/team/SERVER_TAILSCALE_RU.md, section 8.

    python3 -I server_net_diag.py [--proxy http://proxy.bmstu.ru:PORT]
"""

import argparse
import socket
import ssl
import threading
import time
import urllib.request

HOSTS = ["controlplane.tailscale.com", "pkgs.tailscale.com", "deb.debian.org"]
WAITS = [20, 45, 70, 100]


def head(sock, host):
    sock.sendall(f"HEAD / HTTP/1.1\r\nHost: {host}\r\nConnection: keep-alive\r\n\r\n".encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            raise EOFError
        buf += chunk
    return buf.split(b"\r\n", 1)[0].decode(errors="replace")


def probe(host, wait, results):
    try:
        raw = socket.create_connection((host, 443), timeout=10)
        sock = ssl.create_default_context().wrap_socket(raw, server_hostname=host)
        head(sock, host)
        time.sleep(wait)
        sock.settimeout(15)
        head(sock, host)
        results[(host, wait)] = "alive"
    except EOFError:
        results[(host, wait)] = "closed by the server (normal)"
    except (ConnectionResetError, BrokenPipeError):
        results[(host, wait)] = "RESET"
    except socket.timeout:
        results[(host, wait)] = "NO ANSWER (silently dropped)"
    except OSError as exc:
        results[(host, wait)] = f"error: {exc}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proxy", help="e.g. http://proxy.bmstu.ru:3128")
    args = ap.parse_args()

    results = {}
    threads = [threading.Thread(target=probe, args=(h, w, results)) for h in HOSTS for w in WAITS]
    print(f"idle test: {len(threads)} connections, longest wait {max(WAITS)} s ...", flush=True)
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for h in HOSTS:
        print(f"  {h}")
        for w in WAITS:
            print(f"    idle {w:>3} s: {results.get((h, w), 'no result')}")

    if args.proxy:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({"https": args.proxy, "http": args.proxy}))
        try:
            with opener.open("https://controlplane.tailscale.com/key?v=130", timeout=15) as r:
                print(f"proxy {args.proxy}: control plane answers, HTTP {r.status}")
        except OSError as exc:
            print(f"proxy {args.proxy}: FAILED: {exc}")


if __name__ == "__main__":
    main()
