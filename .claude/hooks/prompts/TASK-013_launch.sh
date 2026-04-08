#!/bin/bash
cd "C:/RealProjects/TradingAgent/trading-agent"
PROMPT=$(cat "C:/RealProjects/TradingAgent/trading-agent/.claude/hooks/prompts/TASK-013.txt")
claude --dangerously-skip-permissions -p "$PROMPT"
echo ""
echo "=== Sesion TASK-013 terminada ==="
read -p "Pulsa Enter para cerrar..."
