#!/bin/bash
cd "C:/RealProjects/TradingAgent/trading-agent"
PROMPT=$(cat "C:/RealProjects/TradingAgent/trading-agent/.claude/hooks/prompts/TASK-015.txt")
claude "$PROMPT"
echo ""
echo "=== Sesion TASK-015 terminada ==="
read -p "Pulsa Enter para cerrar..."
