# Deploy: Oracle Cloud Always Free

Runs the Try-it service permanently for free on an Ampere A1 VM
(up to 4 OCPU / 24 GB in the always-free tier; 2 OCPU / 12 GB is plenty).

## One-time account steps (browser)

1. **Oracle Cloud account** — cloud.oracle.com → Sign up. A card is required for
   identity verification; always-free resources never bill.
2. **Create the VM** — Compute → Instances → Create:
   - Image: **Ubuntu 24.04** (aarch64) · Shape: **VM.Standard.A1.Flex**, 2 OCPU, 12 GB
   - Networking: create a new VCN with a public subnet, **assign a public IPv4**
   - Add your SSH public key (or download the generated one)
   - If you get "Out of capacity", retry later or pick another availability domain — it's common for A1.
3. **Open ports 80 and 443** — Networking → VCN → Security Lists → Default → Add Ingress Rules:
   source `0.0.0.0/0`, TCP, destination port `80`; repeat for `443`.
4. **A DNS name** (needed for automatic HTTPS) — easiest is a free DuckDNS subdomain:
   duckdns.org → sign in → create `something.duckdns.org` → set its IP to the VM's public IP.

## On the VM (one command)

```
ssh ubuntu@<public-ip>
curl -fsSL https://raw.githubusercontent.com/evanderpool/video-studio-demo/main/deploy/setup.sh -o setup.sh
DEMO_HOST=something.duckdns.org bash setup.sh
```

First build takes ~5–8 min (it downloads the Whisper model into the image).
Check: `https://something.duckdns.org/api/health` → `{"ok":true,...,"brain":"heuristic"}`.

## Point the public gallery at it

In `site/config.js` set `API_BASE` to `https://something.duckdns.org` and push —
the Try-it section then appears on the GitHub Pages site. (The VM also serves the
full site itself at the same hostname.)

## What's enforced on the box

- App container is **read-only**, all capabilities dropped, no new privileges,
  memory/CPU limited; `/tmp` is a **RAM tmpfs** — uploads never touch disk and
  vanish on restart, in addition to the 30-minute reaper.
- Caddy: automatic Let's Encrypt TLS, **access logging disabled** (no visitor IPs
  kept), body cap, security headers, server header stripped.
- Only 22/80/443 reachable; the app port is not published.
- Updates: `cd ~/video-studio-demo && git pull && cd deploy && sudo docker compose up -d --build`
