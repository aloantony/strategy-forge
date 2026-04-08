#!/bin/bash
cd "C:/RealProjects/TradingAgent/trading-agent"
PROMPT=$(cat "C:/RealProjects/TradingAgent/trading-agent/.claude/hooks/prompts/TASK-014a.txt")
claude "$PROMPT"
echo ""
echo "=== Sesion TASK-014a terminada ==="
read -p "Pulsa Enter para cerrar..."
