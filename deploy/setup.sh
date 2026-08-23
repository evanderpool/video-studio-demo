#!/usr/bin/env bash
# One-shot setup on a fresh Oracle Always Free Ubuntu ARM VM.
# Usage (on the VM):  DEMO_HOST=yourname.duckdns.org bash setup.sh
set -euo pipefail
: "${DEMO_HOST:?set DEMO_HOST to the DNS name pointing at this VM (e.g. xyz.duckdns.org)}"

sudo apt-get update -y
sudo apt-get install -y ca-certificates curl git
# Docker (official repo)
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update -y
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker "$USER"

# Oracle's Ubuntu images ship iptables rules that drop 80/443 - open them (and persist)
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo apt-get install -y iptables-persistent >/dev/null 2>&1 || true
sudo netfilter-persistent save >/dev/null 2>&1 || true

# code
if [ ! -d "$HOME/video-studio-demo" ]; then
  git clone https://github.com/evanderpool/video-studio-demo.git "$HOME/video-studio-demo"
fi
cd "$HOME/video-studio-demo/deploy"
echo "DEMO_HOST=$DEMO_HOST" > .env
sudo docker compose up -d --build
echo
echo "Building + starting. Follow with:  sudo docker compose logs -f"
echo "When healthy:  https://$DEMO_HOST/api/health"
