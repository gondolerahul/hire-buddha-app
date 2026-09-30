#!/bin/bash
# HireBuddha Platform v2.0
# Starts Docker (Postgres, Redis), the API on port 8000 (REST, webhooks, internal
# events and the audio/video/telephony WebSockets), the Arq worker and the frontend.

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get the script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"

# Log file directory
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}      HireBuddha Platform v2.0         ${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Function to check if a port is in use
check_port() {
    local port=$1
    if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1 ; then
        return 0  # Port is in use
    else
        return 1  # Port is free
    fi
}

# Function to wait for a service to be ready
wait_for_service() {
    local name=$1
    local port=$2
    local max_attempts=30
    local attempt=0
    
    echo -ne "${YELLOW}Waiting for $name to be ready on port $port... ${NC}"
    
    while [ $attempt -lt $max_attempts ]; do
        if check_port $port; then
            echo -e "${GREEN}✓ Ready!${NC}"
            return 0
        fi
        attempt=$((attempt + 1))
        echo -ne "."
        sleep 1
    done
    
    echo -e "${RED}✗ Failed to start within expected time${NC}"
    return 1
}

# Check for .env file
if [ ! -f "$BACKEND_DIR/.env" ]; then
    echo -e "${RED}Error: .env file not found in $BACKEND_DIR${NC}"
    echo -e "Please create it from .env.example"
    exit 1
fi

# Step 1: Start Docker services (PostgreSQL and Redis)
echo -e "${BLUE}[1/4] Starting Docker services (PostgreSQL & Redis)...${NC}"
cd "$BACKEND_DIR"

# Ensure docker is running
if ! docker info >/dev/null 2>&1; then
    echo -e "${RED}Error: Docker is not running. Please start Docker and try again.${NC}"
    exit 1
fi

if docker compose ps db --status running | grep -q "db" && docker compose ps redis --status running | grep -q "redis"; then
    echo -e "${YELLOW}Database and Redis are already running${NC}"
else
    docker compose up -d db redis
    echo -e "${GREEN}✓ Docker services started${NC}"
fi

# Step 2: Start the API (port 8000 — every HTTP and WebSocket endpoint)
echo -e "${BLUE}[2/4] Starting API (Port 8000)...${NC}"

if check_port 8000; then
    echo -e "${YELLOW}Port 8000 already in use. Skipping Backend API startup.${NC}"
else
    cd "$BACKEND_DIR"
    nohup "$BACKEND_DIR/.venv/bin/python" -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload > "$LOG_DIR/backend_api.log" 2>&1 &
    BACKEND_PID=$!
    echo $BACKEND_PID > "$LOG_DIR/backend_api.pid"
    echo -e "${GREEN}✓ Backend API process spawned (PID: $BACKEND_PID)${NC}"
    wait_for_service "Backend API" 8000
fi

# The Unified Gateway on :8001 was merged into the API (2026-09-30).
if check_port 8001; then
    echo -e "${YELLOW}Port 8001 is still in use - probably the retired Unified Gateway. Run ./stop_services.sh, then start again.${NC}"
fi

# Step 3: Start Arq Worker
echo -e "${BLUE}[3/4] Starting Arq Worker...${NC}"

# Check if arq worker is already running by process name
if pgrep -f "arq src.ai.worker.WorkerSettings" > /dev/null; then
    echo -e "${YELLOW}Arq worker already running. Skipping.${NC}"
else
    cd "$BACKEND_DIR"
    # Using 'arq' module instead of 'arq.cli' for better compatibility
    nohup "$BACKEND_DIR/.venv/bin/python" -m arq src.ai.worker.WorkerSettings > "$LOG_DIR/arq_worker.log" 2>&1 &
    ARQ_PID=$!
    echo $ARQ_PID > "$LOG_DIR/arq_worker.pid"
    echo -e "${GREEN}✓ Arq Worker started (PID: $ARQ_PID)${NC}"
fi

# Child runs have their own queue and worker (SA-07); without it they never run.
if pgrep -f "arq src.ai.worker.ChildWorkerSettings" > /dev/null; then
    echo -e "${YELLOW}Arq child-run worker already running. Skipping.${NC}"
else
    cd "$BACKEND_DIR"
    nohup "$BACKEND_DIR/.venv/bin/python" -m arq src.ai.worker.ChildWorkerSettings > "$LOG_DIR/arq_child_worker.log" 2>&1 &
    CHILD_PID=$!
    echo $CHILD_PID > "$LOG_DIR/arq_child_worker.pid"
    echo -e "${GREEN}✓ Arq child-run worker started (PID: $CHILD_PID)${NC}"
fi

# Step 4: Start Frontend
echo -e "${BLUE}[4/4] Starting Frontend (Port 3000)...${NC}"

if check_port 3000; then
    echo -e "${YELLOW}Port 3000 already in use. Skipping Frontend startup.${NC}"
else
    cd "$FRONTEND_DIR"
    nohup npm run dev -- --host 0.0.0.0 > "$LOG_DIR/frontend.log" 2>&1 &
    FRONTEND_PID=$!
    echo $FRONTEND_PID > "$LOG_DIR/frontend.pid"
    echo -e "${GREEN}✓ Frontend started (PID: $FRONTEND_PID)${NC}"
    wait_for_service "Frontend" 3000
fi

# Final Summary
echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}✓ All services are running!${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "Access the application at:          ${GREEN}https://dev.hirebuddha.com${NC}"
echo -e "API (Port 8000):                   ${GREEN}https://gateway.hirebuddha.com${NC} (also api.hirebuddha.com)"
echo -e "  REST API:                        ${GREEN}https://gateway.hirebuddha.com/api/v1/*${NC}"
echo -e "  Health:                          ${GREEN}https://gateway.hirebuddha.com/api/v1/health${NC}"
echo -e "  Webhook endpoint:                ${GREEN}https://gateway.hirebuddha.com/webhook/inbound${NC}"
echo -e "  Internal event endpoint:         ${GREEN}https://gateway.hirebuddha.com/internal/event${NC}"
echo -e "  Telephony streams (WS):          ${GREEN}wss://gateway.hirebuddha.com/stream/twilio|tata/{id}${NC}"
echo -e "  Audio streaming (WS):            ${GREEN}wss://gateway.hirebuddha.com/stream/audio${NC}"
echo -e "  Video streaming (WebRTC/WS):     ${GREEN}wss://gateway.hirebuddha.com/stream/video${NC}"
echo -e "API Docs:                          ${GREEN}https://gateway.hirebuddha.com/docs${NC}"
echo ""
echo -e "Logs available in:        ${YELLOW}$LOG_DIR/${NC}"
echo -e "To stop services, run:    ${GREEN}./stop_services.sh${NC}"
echo ""
