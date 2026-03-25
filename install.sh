#!/bin/bash
set -e

INSTALL_DIR="$HOME/.coinwar"
BIN_DIR="/usr/local/bin"

echo "Installing coinwar..."

# Check Python3
if ! command -v python3 &>/dev/null; then
    echo "Error: python3 is required. Please install Python 3.10+."
    exit 1
fi

# Create venv
python3 -m venv "$INSTALL_DIR"

# Install package
"$INSTALL_DIR/bin/pip" install --quiet git+https://github.com/latte0205/coin_war.git

# Create wrapper in /usr/local/bin
sudo tee "$BIN_DIR/coinwar" > /dev/null <<EOF
#!/bin/bash
exec "$INSTALL_DIR/bin/coinwar" "\$@"
EOF
sudo chmod +x "$BIN_DIR/coinwar"

echo "Done! Run: coinwar --help"
