#!/usr/bin/env bash
# =============================================================================
# Legal Analyst Squad — Deploy Remoto para VPS Hostinger
# =============================================================================
# Execute este script do seu terminal LOCAL para deployar na VPS.
#
# USO:
#   VPS_IP=host REPO_URL=git-url ANTHROPIC_API_KEY=sk-ant-... ./deploy-remote.sh
#
# O script envia o deploy-hostinger.sh para a VPS e executa automaticamente.
# =============================================================================

set -euo pipefail

VPS_IP="${VPS_IP:-}"
VPS_USER="${VPS_USER:-root}"
REPO_URL="${REPO_URL:-}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEPLOY_SCRIPT="$SCRIPT_DIR/deploy-hostinger.sh"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Verificar API key
if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo -e "${YELLOW}[?] Informe sua ANTHROPIC_API_KEY:${NC}"
  read -r ANTHROPIC_API_KEY
  if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo -e "${RED}[x] API key obrigatoria.${NC}"
    exit 1
  fi
fi

if [ -z "$VPS_IP" ]; then
  echo -e "${YELLOW}[?] Informe o host ou IP da VPS:${NC}"
  read -r VPS_IP
fi

if [ -z "$REPO_URL" ]; then
  echo -e "${YELLOW}[?] Informe a URL do repositorio Git privado do AEXOS:${NC}"
  read -r REPO_URL
fi

if [ -z "$VPS_IP" ] || [ -z "$REPO_URL" ]; then
  echo -e "${RED}[x] VPS_IP e REPO_URL sao obrigatorios.${NC}"
  exit 1
fi

# Verificar se o script de deploy existe
if [ ! -f "$DEPLOY_SCRIPT" ]; then
  echo -e "${RED}[x] Nao encontrei deploy-hostinger.sh em $SCRIPT_DIR${NC}"
  exit 1
fi

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   Enviando deploy para VPS ${VPS_IP}                    ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# Executar deploy via SSH
echo -e "${GREEN}[1/1] Executando deploy na VPS...${NC}"
ssh "${VPS_USER}@${VPS_IP}" \
  "ANTHROPIC_API_KEY='${ANTHROPIC_API_KEY}' \
   REPO_URL='${REPO_URL}' \
   bash -s" < "$DEPLOY_SCRIPT"

echo ""
echo -e "${GREEN}Deploy finalizado!${NC}"
echo -e "Acesse: ${GREEN}http://${VPS_IP}${NC}"
echo -e "Health: ${GREEN}http://${VPS_IP}/api/health${NC}"
echo ""
