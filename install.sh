#!/usr/bin/env bash
#
# Install script for pylint-cache
#
# Usage:
#   sudo ./install.sh           # Install to /opt/pylint-cache
#   sudo ./install.sh uninstall # Remove installation
#

set -e

INSTALL_DIR="/opt/pylint-cache"
BIN_LINK="/usr/local/bin/pylint-cache"
SCRIPT_NAME="pylint_cache.py"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}ERROR: Please run with sudo${NC}"
    echo "Usage: sudo ./install.sh"
    exit 1
fi

# Function to install
install_pylint_cache() {
    echo -e "${GREEN}Installing pylint-cache...${NC}"
    
    # Check if pylint is installed
    if ! command -v pylint &> /dev/null; then
        echo -e "${YELLOW}WARNING: pylint is not installed${NC}"
        echo "Install it with: pip install pylint"
        echo ""
    fi
    
    # Create installation directory
    echo "Creating directory: $INSTALL_DIR"
    mkdir -p "$INSTALL_DIR"
    
    # Copy the script
    echo "Copying $SCRIPT_NAME to $INSTALL_DIR/"
    cp "$SCRIPT_NAME" "$INSTALL_DIR/"
    chmod 755 "$INSTALL_DIR/$SCRIPT_NAME"
    
    # Create symlink
    echo "Creating symlink: $BIN_LINK"
    ln -sf "$INSTALL_DIR/$SCRIPT_NAME" "$BIN_LINK"
    
    echo -e "${GREEN}✓ Installation complete!${NC}"
    echo ""
    echo "You can now run: pylint-cache <files>"
    echo "Cache database will be created in the directory where you run it."
    echo ""
    echo "To uninstall: sudo ./install.sh uninstall"
}

# Function to uninstall
uninstall_pylint_cache() {
    echo -e "${YELLOW}Uninstalling pylint-cache...${NC}"
    
    # Remove symlink
    if [ -L "$BIN_LINK" ]; then
        echo "Removing symlink: $BIN_LINK"
        rm "$BIN_LINK"
    fi
    
    # Remove installation directory
    if [ -d "$INSTALL_DIR" ]; then
        echo "Removing directory: $INSTALL_DIR"
        rm -rf "$INSTALL_DIR"
    fi
    
    echo -e "${GREEN}✓ Uninstallation complete!${NC}"
    echo ""
    echo "Note: .pylint-cache.db files in your projects were not removed."
}

# Main logic
case "${1:-install}" in
    install)
        install_pylint_cache
        ;;
    uninstall)
        uninstall_pylint_cache
        ;;
    *)
        echo "Usage: sudo ./install.sh [install|uninstall]"
        exit 1
        ;;
esac

