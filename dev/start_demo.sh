#!/usr/bin/env bash
# Sets up a 3-container fake classroom for manual testing.
#
# After running this script:
#   python -m classctl          # starts the web app on http://127.0.0.1:8000
#
# The "Demo Lab" classroom has 3 machines:
#   ws-1 (172.28.0.10) — all steps succeed
#   ws-2 (172.28.0.11) — all steps succeed
#   ws-3 (172.28.0.12) — step 1 outputs an error pattern → triggers pause
#
set -euo pipefail

NETWORK=classctl-demo
SUBNET=172.28.0.0/24
GATEWAY=172.28.0.1
IMAGE=classctl-test-ssh:latest
KEY_PATH="$HOME/.config/classctl/demo_key"
CONFIG_PATH="$HOME/.config/classctl/classrooms.json"

declare -a IPS=(172.28.0.10 172.28.0.11 172.28.0.12)
declare -a NAMES=(ws-1 ws-2 ws-3)
declare -a MACS=(aa:bb:cc:dd:ee:01 aa:bb:cc:dd:ee:02 aa:bb:cc:dd:ee:03)

# ── 1. Build image if missing ────────────────────────────────────────────────
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "Building SSH test image…"
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    docker build --no-cache \
        -f "$SCRIPT_DIR/../tests/docker/Dockerfile.ssh" \
        -t "$IMAGE" \
        "$SCRIPT_DIR/../tests/docker/"
fi

# ── 2. Docker network ────────────────────────────────────────────────────────
if ! docker network inspect "$NETWORK" >/dev/null 2>&1; then
    echo "Creating Docker network $NETWORK ($SUBNET)…"
    docker network create --subnet="$SUBNET" --gateway="$GATEWAY" "$NETWORK"
fi

# ── 3. SSH key ───────────────────────────────────────────────────────────────
mkdir -p "$HOME/.config/classctl"
if [ ! -f "$KEY_PATH" ]; then
    echo "Generating SSH key at $KEY_PATH…"
    ssh-keygen -t ed25519 -N "" -f "$KEY_PATH" -C "classctl-demo" -q
fi
PUB_KEY="$(cat "${KEY_PATH}.pub")"

# ── 4. Containers ────────────────────────────────────────────────────────────
echo "Starting containers…"
for i in "${!NAMES[@]}"; do
    NAME="${NAMES[$i]}"
    IP="${IPS[$i]}"
    docker rm -f "$NAME" 2>/dev/null || true
    docker run -d --name "$NAME" \
        --network "$NETWORK" --ip "$IP" \
        "$IMAGE" >/dev/null
done

echo "Waiting for sshd…"
sleep 2

# ── 5. Inject key + per-step scripts ─────────────────────────────────────────
for i in "${!NAMES[@]}"; do
    NAME="${NAMES[$i]}"

    # Authorise our key
    docker exec "$NAME" sh -c \
        "echo '$PUB_KEY' > /home/testuser/.ssh/authorized_keys && \
         chmod 600 /home/testuser/.ssh/authorized_keys && \
         chown testuser:testuser /home/testuser/.ssh/authorized_keys"

    # Create step scripts.
    # ws-3 step 1 outputs an error pattern to demo the pause/retry/skip flow.
    for step in 1 2 3 4; do
        if [ "$NAME" = "ws-3" ] && [ "$step" = "1" ]; then
            ARGS="--output-pattern error --sleep 1"
        else
            ARGS="--sleep 1"
        fi
        docker exec "$NAME" sh -c \
            "printf '#!/bin/sh\n/home/testuser/scripts/fake_script.sh $ARGS\n' \
             > /home/testuser/scripts/step${step}.sh && \
             chmod +x /home/testuser/scripts/step${step}.sh"
    done
done

# ── 6. classrooms.json ───────────────────────────────────────────────────────
KEY_ABS="$(realpath "$KEY_PATH")"
cat > "$CONFIG_PATH" << JSON
{
  "classrooms": [
    {
      "name": "Demo Lab",
      "subnet": "$SUBNET",
      "ssh_key_path": "$KEY_ABS",
      "username": "testuser",
      "script_directory": "/home/testuser/scripts",
      "step_mapping": {
        "1": "step1.sh",
        "2": "step2.sh",
        "3": "step3.sh",
        "4": "step4.sh"
      },
      "machines": [
        {"ip": "${IPS[0]}", "mac": "${MACS[0]}"},
        {"ip": "${IPS[1]}", "mac": "${MACS[1]}"},
        {"ip": "${IPS[2]}", "mac": "${MACS[2]}"}
      ]
    }
  ],
  "error_patterns": ["error", "failed", "traceback", "exception"]
}
JSON

echo ""
echo "✓  Demo environment ready"
echo ""
echo "   ws-1  ${IPS[0]}  — steps 1-4 succeed"
echo "   ws-2  ${IPS[1]}  — steps 1-4 succeed"
echo "   ws-3  ${IPS[2]}  — step 1 outputs an error → pause demo"
echo ""
echo "Start the app:"
echo "   python -m classctl"
echo ""
echo "Then open:  http://127.0.0.1:8000"
