#!/usr/bin/env bash
# classctl installer
# Usage: bash install.sh
set -euo pipefail

INSTALL_DIR="$HOME/.local/share/classctl"
BIN_DIR="$HOME/.local/bin"
VENV="$INSTALL_DIR/venv"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── helpers ──────────────────────────────────────────────────────────────────
info()  { echo "  $*"; }
ok()    { echo "✓ $*"; }
die()   { echo "✗ $*" >&2; exit 1; }

echo ""
echo "classctl installer"
echo "══════════════════"
echo ""

# ── 1. Python ────────────────────────────────────────────────────────────────
info "Checking Python 3.11+…"
PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
        ver=$("$candidate" -c 'import sys; print(sys.version_info >= (3,11))')
        if [ "$ver" = "True" ]; then
            PYTHON="$candidate"
            break
        fi
    fi
done
[ -n "$PYTHON" ] || die "Python 3.11 or newer not found. Install it first."
ok "Python: $PYTHON"

# ── 2. System packages ───────────────────────────────────────────────────────
info "Installing system packages (nmap)…"
if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get install -y --no-install-recommends nmap python3-venv >/dev/null
elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y nmap python3 >/dev/null
elif command -v pacman >/dev/null 2>&1; then
    sudo pacman -S --noconfirm nmap python >/dev/null
else
    echo "  ⚠ Unknown package manager — make sure 'nmap' is installed manually."
fi
ok "System packages"

# ── 3. Virtual environment ───────────────────────────────────────────────────
info "Creating virtual environment in $VENV…"
mkdir -p "$INSTALL_DIR"
"$PYTHON" -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
ok "Virtual environment"

# ── 4. Install classctl ──────────────────────────────────────────────────────
info "Installing classctl and dependencies…"
"$VENV/bin/pip" install --quiet "$REPO_DIR"
ok "classctl installed"

# ── 5. Raw socket capability (for ARP discovery, no sudo at runtime) ─────────
info "Granting ARP scan capability to Python…"
VENV_PYTHON="$(readlink -f "$VENV/bin/python3")"
sudo setcap cap_net_raw+ep "$VENV_PYTHON"
ok "cap_net_raw granted to $VENV_PYTHON"

# ── 6. Launcher script ───────────────────────────────────────────────────────
info "Creating launcher at $BIN_DIR/classctl…"
mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/classctl" << EOF
#!/usr/bin/env bash
exec "$VENV/bin/python3" -m classctl "\$@"
EOF
chmod +x "$BIN_DIR/classctl"
ok "Launcher created"

# ── 7. PATH reminder ─────────────────────────────────────────────────────────
echo ""
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    echo "  ⚠  Add this to your ~/.bashrc or ~/.zshrc:"
    echo ""
    echo "       export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo ""
    echo "  Then reload: source ~/.bashrc"
    echo ""
fi

echo "══════════════════════════════════"
echo " Done! Start the app with:"
echo ""
echo "   classctl"
echo ""
echo " Then open: http://127.0.0.1:8000"
echo "══════════════════════════════════"
echo ""
