#!/bin/bash
cd "C:/RealProjects/TradingAgent/trading-agent"
PROMPT=$(cat "C:/RealProjects/TradingAgent/trading-agent/.claude/hooks/prompts/TASK-014c-fix.txt")
claude "$PROMPT"

echo ""
echo "=== Sesion TASK-014c-fix terminada ==="
read -p "Pulsa Enter para cerrar..."
