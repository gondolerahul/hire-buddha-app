#!/bin/bash
# ============================================================================
# HireBuddha Platform — Apache Reverse Proxy Setup Script
# ============================================================================
# Run this on the NEW production VM AFTER setup_production_vm.sh
# This installs Apache, configures reverse proxy vhosts, security hardening,
# and obtains Let's Encrypt SSL certificates.
#
# Prerequisites:
#   - DNS records for all subdomains must point to this VM's external IP
#   - Ports 80 and 443 must be open in the GCP firewall
#   - setup_production_vm.sh must have been run first
#
# Usage:
#   chmod +x deploy/apache/setup_apache.sh
#   sudo ./deploy/apache/setup_apache.sh
# ============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Please run as root (sudo)${NC}"
    exit 1
fi

echo -e "${BLUE}============================================================${NC}"
echo -e "${BLUE}  HireBuddha — Apache Reverse Proxy Setup                  ${NC}"
echo -e "${BLUE}============================================================${NC}"
echo ""

# ── Step 1: Install Apache ───────────────────────────────────────────────────
echo -e "${CYAN}[1/6] Installing Apache...${NC}"
apt-get update -y
apt-get install -y apache2 libapache2-mod-evasive
echo -e "${GREEN}✓ Apache installed${NC}"
echo ""

# ── Step 2: Enable required Apache modules ───────────────────────────────────
echo -e "${CYAN}[2/6] Enabling Apache modules...${NC}"
a2enmod proxy
a2enmod proxy_http
a2enmod proxy_wstunnel
a2enmod ssl
a2enmod rewrite
a2enmod headers
a2enmod remoteip
a2enmod deflate
echo -e "${GREEN}✓ Apache modules enabled${NC}"
echo ""

# ── Step 3: Copy vhost configs ───────────────────────────────────────────────
echo -e "${CYAN}[3/6] Installing VirtualHost configurations...${NC}"

# Copy all site configs (HTTP vhosts — SSL vhosts will be created by certbot)
for conf in api.hirebuddha.com.conf app.hirebuddha.com.conf dev.hirebuddha.com.conf \
            gateway.hirebuddha.com.conf streaming.hirebuddha.com.conf; do
    if [ -f "$SCRIPT_DIR/$conf" ]; then
        cp "$SCRIPT_DIR/$conf" /etc/apache2/sites-available/
        a2ensite "$conf"
        echo -e "  ${GREEN}✓ $conf${NC}"
    else
        echo -e "  ${YELLOW}⚠ $conf not found, skipping${NC}"
    fi
done

# Disable default site
a2dissite 000-default.conf 2>/dev/null || true

echo -e "${GREEN}✓ VirtualHost configs installed${NC}"
echo ""

# ── Step 4: Install security hardening config ────────────────────────────────
echo -e "${CYAN}[4/6] Installing security hardening...${NC}"

if [ -f "$SCRIPT_DIR/hirebuddha-security.conf" ]; then
    cp "$SCRIPT_DIR/hirebuddha-security.conf" /etc/apache2/conf-available/
    a2enconf hirebuddha-security
    # Create mod_evasive log directory
    mkdir -p /var/log/apache2/mod_evasive
    chown www-data:www-data /var/log/apache2/mod_evasive
    echo -e "${GREEN}✓ Security hardening installed${NC}"
else
    echo -e "${YELLOW}⚠ hirebuddha-security.conf not found, skipping${NC}"
fi
echo ""

# ── Step 5: Test Apache config ───────────────────────────────────────────────
echo -e "${CYAN}[5/6] Testing Apache configuration...${NC}"
if apache2ctl configtest 2>&1; then
    echo -e "${GREEN}✓ Apache config is valid${NC}"
else
    echo -e "${RED}✗ Apache config has errors. Fix them before continuing.${NC}"
    exit 1
fi
echo ""

# ── Step 6: Install Certbot & obtain SSL certificates ───────────────────────
echo -e "${CYAN}[6/6] Setting up Let's Encrypt SSL...${NC}"

# Install certbot
apt-get install -y certbot python3-certbot-apache

# Restart Apache first (needed for certbot to verify)
systemctl restart apache2

echo -e "${YELLOW}Obtaining SSL certificates...${NC}"
echo -e "${YELLOW}Make sure DNS A records for all subdomains point to this VM's IP!${NC}"
echo ""

# Get the VM's external IP
EXTERNAL_IP=$(curl -s -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip 2>/dev/null || echo "unknown")
echo -e "This VM's external IP: ${GREEN}${EXTERNAL_IP}${NC}"
echo ""

# Obtain certificates for each domain
DOMAINS=("dev.hirebuddha.com" "api.hirebuddha.com" "gateway.hirebuddha.com" "app.hirebuddha.com" "streaming.hirebuddha.com")

for domain in "${DOMAINS[@]}"; do
    echo -e "${CYAN}Obtaining certificate for ${domain}...${NC}"
    certbot --apache -d "$domain" --non-interactive --agree-tos --email admin@hirebuddha.com --redirect 2>&1 || {
        echo -e "${YELLOW}⚠ Failed for ${domain} — DNS may not be pointing to this VM yet. Run manually later:${NC}"
        echo -e "  ${CYAN}certbot --apache -d ${domain}${NC}"
    }
    echo ""
done

# Enable auto-renewal
systemctl enable certbot.timer
systemctl start certbot.timer

echo -e "${GREEN}✓ SSL setup complete${NC}"
echo ""

# ── Final reload ─────────────────────────────────────────────────────────────
systemctl reload apache2

echo -e "${BLUE}============================================================${NC}"
echo -e "${GREEN}✓ Apache reverse proxy setup complete!${NC}"
echo -e "${BLUE}============================================================${NC}"
echo ""
echo -e "Proxy routing:"
echo -e "  ${CYAN}app.hirebuddha.com${NC}       → localhost:3000 (Frontend)"
echo -e "  ${CYAN}dev.hirebuddha.com${NC}       → localhost:3000 (Frontend)"
echo -e "  ${CYAN}api.hirebuddha.com${NC}       → localhost:8001 (Unified Gateway)"
echo -e "  ${CYAN}gateway.hirebuddha.com${NC}   → localhost:8000 (Backend API)"
echo -e "  ${CYAN}streaming.hirebuddha.com${NC} → localhost:8002 (Streaming/WS)"
echo ""
echo -e "${YELLOW}Note: If DNS hasn't propagated yet, re-run certbot later:${NC}"
echo -e "  ${CYAN}sudo certbot --apache -d DOMAIN_NAME${NC}"
echo ""
