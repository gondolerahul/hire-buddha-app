#!/bin/bash
# ============================================================================
# HireBuddha Platform — Production VM Setup Script
# ============================================================================
# This script sets up a fresh Ubuntu VM with all dependencies needed to run
# the HireBuddha platform. Run this AFTER cloning the repo from GitHub.
#
# Prerequisites:
#   - Ubuntu 22.04 or 24.04 LTS
#   - sudo access
#   - Internet connectivity
#   - Git access to the repo (SSH key or PAT configured)
#
# Usage:
#   chmod +x setup_production_vm.sh
#   ./setup_production_vm.sh
# ============================================================================

set -e  # Exit on any error

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"

echo -e "${BLUE}============================================================${NC}"
echo -e "${BLUE}  HireBuddha Platform — Production VM Setup                 ${NC}"
echo -e "${BLUE}============================================================${NC}"
echo ""

# ── Step 1: System updates & essential packages ──────────────────────────────
echo -e "${CYAN}[1/8] Updating system packages...${NC}"
sudo apt-get update -y
sudo apt-get upgrade -y
sudo apt-get install -y \
    curl \
    wget \
    git \
    build-essential \
    software-properties-common \
    apt-transport-https \
    ca-certificates \
    gnupg \
    lsof \
    unzip \
    jq \
    libpq-dev \
    libffi-dev \
    libssl-dev
echo -e "${GREEN}✓ System packages updated${NC}"
echo ""

# ── Step 2: Install Python 3.12 ─────────────────────────────────────────────
echo -e "${CYAN}[2/8] Installing Python 3.12...${NC}"
if python3 --version 2>/dev/null | grep -q "3.1[2-9]"; then
    echo -e "${YELLOW}Python 3.12+ already installed: $(python3 --version)${NC}"
else
    sudo add-apt-repository ppa:deadsnakes/ppa -y
    sudo apt-get update -y
    sudo apt-get install -y python3.12 python3.12-venv python3.12-dev python3-pip
    sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1
    echo -e "${GREEN}✓ Python 3.12 installed${NC}"
fi
echo ""

# ── Step 3: Install Poetry ──────────────────────────────────────────────────
echo -e "${CYAN}[3/8] Installing Poetry...${NC}"
if command -v poetry &>/dev/null; then
    echo -e "${YELLOW}Poetry already installed: $(poetry --version)${NC}"
else
    curl -sSL https://install.python-poetry.org | python3 -
    # Add Poetry to PATH for current session and permanently
    export PATH="$HOME/.local/bin:$PATH"
    if ! grep -q 'poetry' "$HOME/.bashrc" 2>/dev/null; then
        echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
    fi
    echo -e "${GREEN}✓ Poetry installed: $(poetry --version)${NC}"
fi
echo ""

# ── Step 4: Install Node.js 20 LTS & npm ────────────────────────────────────
echo -e "${CYAN}[4/8] Installing Node.js 20 LTS...${NC}"
if node --version 2>/dev/null | grep -q "v20"; then
    echo -e "${YELLOW}Node.js 20 already installed: $(node --version)${NC}"
else
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
    sudo apt-get install -y nodejs
    echo -e "${GREEN}✓ Node.js installed: $(node --version), npm: $(npm --version)${NC}"
fi
echo ""

# ── Step 5: Install Docker & Docker Compose ─────────────────────────────────
echo -e "${CYAN}[5/8] Installing Docker...${NC}"
if command -v docker &>/dev/null; then
    echo -e "${YELLOW}Docker already installed: $(docker --version)${NC}"
else
    # Add Docker's official GPG key
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg
    
    # Add Docker repo
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    
    sudo apt-get update -y
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    
    # Add current user to docker group
    sudo usermod -aG docker $USER
    echo -e "${GREEN}✓ Docker installed: $(docker --version)${NC}"
    echo -e "${YELLOW}NOTE: You may need to log out and back in for Docker group permissions.${NC}"
fi
echo ""

# ── Step 6: Backend — Python venv + Poetry install ──────────────────────────
echo -e "${CYAN}[6/8] Setting up Backend (Python dependencies)...${NC}"
cd "$BACKEND_DIR"

# Create virtual environment if not exists
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo -e "${GREEN}✓ Created Python virtual environment${NC}"
else
    echo -e "${YELLOW}Virtual environment already exists${NC}"
fi

# Install dependencies using Poetry
export PATH="$HOME/.local/bin:$PATH"
poetry install --no-interaction --no-ansi
echo -e "${GREEN}✓ Backend Python dependencies installed${NC}"

echo ""

# ── Step 7: Frontend — npm install ──────────────────────────────────────────
echo -e "${CYAN}[7/8] Setting up Frontend (Node dependencies)...${NC}"
cd "$FRONTEND_DIR"
npm install --legacy-peer-deps
echo -e "${GREEN}✓ Frontend dependencies installed${NC}"
echo ""

# ── Step 8: Create .env from example ────────────────────────────────────────
echo -e "${CYAN}[8/8] Setting up environment configuration...${NC}"
cd "$BACKEND_DIR"

if [ ! -f ".env" ]; then
    cp .env.example .env
    echo -e "${GREEN}✓ Created .env from .env.example${NC}"
    echo -e "${YELLOW}⚠ IMPORTANT: Edit .env with your production values before starting!${NC}"
else
    echo -e "${YELLOW}.env already exists. Skipping.${NC}"
fi
echo ""

# ── Summary ─────────────────────────────────────────────────────────────────
echo -e "${BLUE}============================================================${NC}"
echo -e "${GREEN}✓ Setup complete!${NC}"
echo -e "${BLUE}============================================================${NC}"
echo ""
echo -e "Installed versions:"
echo -e "  Python:   $(python3 --version)"
echo -e "  Poetry:   $(poetry --version 2>/dev/null || echo 'installed (re-login for PATH)')"
echo -e "  Node.js:  $(node --version)"
echo -e "  npm:      $(npm --version)"
echo -e "  Docker:   $(docker --version 2>/dev/null)"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo -e "  1. Edit ${CYAN}backend/.env${NC} with production values"
echo -e "  2. Start Docker services:  ${CYAN}cd backend && docker compose up -d db redis${NC}"
echo -e "  3. Run DB migrations:      ${CYAN}cd backend && .venv/bin/alembic upgrade head${NC}"
echo -e "  4. Seed admin user:        ${CYAN}cd backend && .venv/bin/python db-scripts/seed_admin_user.py${NC}"
echo -e "  5. Start all services:     ${CYAN}./start_services.sh${NC}"
echo ""
