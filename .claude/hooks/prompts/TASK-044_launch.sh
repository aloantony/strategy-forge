#!/bin/bash
cd "C:/RealProjects/TradingAgent/trading-agent"
PROMPT=$(cat "C:/RealProjects/TradingAgent/trading-agent/.claude/hooks/prompts/TASK-044.txt")
claude "$PROMPT"
echo ""
echo "=== Sesion TASK-044 terminada ==="
read -p "Pulsa Enter para cerrar..."
