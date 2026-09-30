#!/bin/bash
# HireBuddha Platform v2.0 - Shutdown
# This script stops all backend services and the frontend

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get the script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
BACKEND_DIR="$SCRIPT_DIR/backend"
LOG_DIR="$SCRIPT_DIR/logs"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  HireBuddha Platform Shutdown v2.0    ${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Function to stop a service by PID file
stop_service() {
    local name=$1
    local pid_file=$2
    
    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file")
        if ps -p $pid > /dev/null 2>&1; then
            echo -e "${YELLOW}Stopping $name (PID: $pid)...${NC}"
            kill $pid 2>/dev/null || kill -9 $pid 2>/dev/null
            rm "$pid_file"
            echo -e "${GREEN}✓ $name stopped${NC}"
        else
            echo -e "${YELLOW}$name not running (stale PID file)${NC}"
            rm "$pid_file"
        fi
    else
        echo -e "${YELLOW}$name PID file not found${NC}"
    fi
}

# Function to force kill processes on a specific port
kill_port() {
    local name=$1
    local port=$2
    local pids=$(lsof -t -i:$port 2>/dev/null)
    if [ -n "$pids" ]; then
        echo -e "${YELLOW}Cleaning up remaining $name processes on port $port...${NC}"
        kill -9 $pids 2>/dev/null
        echo -e "${GREEN}✓ Port $port cleared${NC}"
    fi
}

# Step 1: Stop Frontend (Port 3000)
echo -e "${BLUE}[1/4] Stopping Frontend...${NC}"
stop_service "Frontend" "$LOG_DIR/frontend.pid"
pkill -f "npm run dev" 2>/dev/null || true
pkill -f "vite" 2>/dev/null || true
kill_port "Frontend" 3000

# Step 2: Stop Arq Worker
echo -e "${BLUE}[2/4] Stopping Arq Worker...${NC}"
stop_service "Arq Worker" "$LOG_DIR/arq_worker.pid"
pkill -f "arq src.ai.worker.WorkerSettings" 2>/dev/null && echo -e "${GREEN}✓ Arq processes terminated${NC}"
stop_service "Arq child-run worker" "$LOG_DIR/arq_child_worker.pid"
pkill -f "arq src.ai.worker.ChildWorkerSettings" 2>/dev/null && echo -e "${GREEN}✓ Arq child-run processes terminated${NC}"

# Step 3: Stop the API (Port 8000)
echo -e "${BLUE}[3/4] Stopping API...${NC}"
stop_service "API" "$LOG_DIR/backend_api.pid"
kill_port "API" 8000

# Final cleanup of uvicorn (also stops a gateway left on :8001 by an older start script)
pkill -f "uvicorn" 2>/dev/null && echo -e "${GREEN}✓ All remaining Uvicorn processes stopped${NC}"

# Step 4: Stop Docker services
echo -e "${BLUE}[4/4] Stopping Docker services...${NC}"
cd "$BACKEND_DIR"
if docker compose ps > /dev/null 2>&1; then
    docker compose down
    echo -e "${GREEN}✓ Docker services stopped${NC}"
else
    echo -e "${YELLOW}Docker compose not found or not active in $BACKEND_DIR${NC}"
fi

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}✓ All HireBuddha services stopped${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "${YELLOW}To start services again, run:${NC}"
echo -e "  ${GREEN}./start_services.sh${NC}"
echo ""
