#!/usr/bin/env bash
# Sets up 3 containers accessible from other machines on the local network
# via port forwarding (ws-1→2201, ws-2→2202, ws-3→2203).
#
# Usage:
#   bash start_demo_remote.sh            # auto-detects host LAN IP
#   bash start_demo_remote.sh 192.168.1.5  # explicit IP
#
# After running:
#   python -m classctl    # start the app
#
# Other machines on the network can then open:
#   http://<this-machine-ip>:8000
#
set -euo pipefail

IMAGE=classctl-test-ssh:latest
KEY_PATH="$HOME/.config/classctl/demo_key"
CONFIG_PATH="$HOME/.config/classctl/classrooms.json"

declare -a NAMES=(ws-1 ws-2 ws-3)
declare -a PORTS=(2201 2202 2203)
declare -a MACS=(aa:bb:cc:dd:ee:01 aa:bb:cc:dd:ee:02 aa:bb:cc:dd:ee:03)

# ── 1. Resolve host LAN IP ───────────────────────────────────────────────────
if [ -n "${1:-}" ]; then
    HOST_IP="$1"
else
    HOST_IP="$(ip route get 8.8.8.8 2>/dev/null | grep -oP 'src \K\S+')"
fi

if [ -z "$HOST_IP" ]; then
    echo "Could not detect LAN IP. Pass it explicitly: bash start_demo_remote.sh <ip>"
    exit 1
fi

echo "Host LAN IP: $HOST_IP"

# ── 2. Build image if missing ────────────────────────────────────────────────
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "Building SSH test image…"
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    docker build --no-cache \
        -f "$SCRIPT_DIR/../tests/docker/Dockerfile.ssh" \
        -t "$IMAGE" \
        "$SCRIPT_DIR/../tests/docker/"
fi

# ── 3. SSH key ───────────────────────────────────────────────────────────────
mkdir -p "$HOME/.config/classctl"
if [ ! -f "$KEY_PATH" ]; then
    echo "Generating SSH key at $KEY_PATH…"
    ssh-keygen -t ed25519 -N "" -f "$KEY_PATH" -C "classctl-demo" -q
fi
PUB_KEY="$(cat "${KEY_PATH}.pub")"

# ── 4. Containers with port forwarding ──────────────────────────────────────
echo "Starting containers…"
for i in "${!NAMES[@]}"; do
    NAME="${NAMES[$i]}"
    PORT="${PORTS[$i]}"
    docker rm -f "$NAME" 2>/dev/null || true
    docker run -d --name "$NAME" \
        -p "${HOST_IP}:${PORT}:22" \
        "$IMAGE" >/dev/null
done

echo "Waiting for sshd…"
sleep 2

# ── 5. Inject key + scripts ──────────────────────────────────────────────────
for i in "${!NAMES[@]}"; do
    NAME="${NAMES[$i]}"

    docker exec "$NAME" sh -c \
        "echo '$PUB_KEY' > /home/testuser/.ssh/authorized_keys && \
         chmod 600 /home/testuser/.ssh/authorized_keys && \
         chown testuser:testuser /home/testuser/.ssh/authorized_keys"

    docker exec "$NAME" sh -c \
        "mkdir -p /home/testuser/scripts/demo \
                  /home/testuser/scripts/short \
                  /home/testuser/scripts/long"

    for step in 1 2 3 4; do
        if [ "$NAME" = "ws-3" ] && [ "$step" = "1" ]; then
            ERROR_ARG="--output-pattern error"
        else
            ERROR_ARG=""
        fi

        docker exec "$NAME" sh -c \
            "printf '#!/bin/sh\n/home/testuser/scripts/fake_script.sh $ERROR_ARG --sleep 1\n' \
             > /home/testuser/scripts/demo/step${step}.sh && \
             chmod +x /home/testuser/scripts/demo/step${step}.sh"

        docker exec "$NAME" sh -c \
            "printf '#!/bin/sh\n/home/testuser/scripts/fake_script.sh $ERROR_ARG --sleep 450\n' \
             > /home/testuser/scripts/short/step${step}.sh && \
             chmod +x /home/testuser/scripts/short/step${step}.sh"

        docker exec "$NAME" sh -c \
            "printf '#!/bin/sh\n/home/testuser/scripts/fake_script.sh $ERROR_ARG --sleep 1350\n' \
             > /home/testuser/scripts/long/step${step}.sh && \
             chmod +x /home/testuser/scripts/long/step${step}.sh"
    done
done

# ── 6. classrooms.json ───────────────────────────────────────────────────────
KEY_ABS="$(realpath "$KEY_PATH")"
cat > "$CONFIG_PATH" << JSON
{
  "classrooms": [
    {
      "name": "Demo Lab (remote)",
      "subnet": "$(echo "$HOST_IP" | cut -d. -f1-3).0/24",
      "ssh_key_path": "$KEY_ABS",
      "username": "testuser",
      "script_directory": "/home/testuser/scripts/demo",
      "step_mapping": {
        "1": "step1.sh",
        "2": "step2.sh",
        "3": "step3.sh",
        "4": "step4.sh"
      },
      "machines": [
        {"ip": "$HOST_IP", "mac": "${MACS[0]}", "port": ${PORTS[0]}},
        {"ip": "$HOST_IP", "mac": "${MACS[1]}", "port": ${PORTS[1]}},
        {"ip": "$HOST_IP", "mac": "${MACS[2]}", "port": ${PORTS[2]}}
      ]
    }
  ],
  "error_patterns": ["error", "failed", "traceback", "exception"]
}
JSON

echo ""
echo "✓  Remote demo environment ready"
echo ""
echo "   ws-1  $HOST_IP:2201  — steps 1-4 succeed"
echo "   ws-2  $HOST_IP:2202  — steps 1-4 succeed"
echo "   ws-3  $HOST_IP:2203  — step 1 outputs an error → pause demo"
echo ""
echo "   Script directories on each container:"
echo "     /home/testuser/scripts/demo/   — ~1 s/step  (UI testing)"
echo "     /home/testuser/scripts/short/  — ~7.5 min/step"
echo "     /home/testuser/scripts/long/   — ~22.5 min/step"
echo ""
echo "Start the app:"
echo "   python -m classctl"
echo ""
echo "Then open from any machine on the network:"
echo "   http://$HOST_IP:8000"
echo ""
echo "Stop with:  bash dev/stop_demo_remote.sh"
