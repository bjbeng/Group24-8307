#!/usr/bin/env bash
# install.sh — Ubuntu VPS 一键部署脚本
# 用法：sudo bash install.sh YOUR_DOMAIN your@email.com
set -euo pipefail

DOMAIN=${1:-""}
EMAIL=${2:-""}
INSTALL_DIR=/opt/industryagent
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if [[ -z "$DOMAIN" || -z "$EMAIL" ]]; then
    echo "用法: sudo bash deploy/install.sh <domain> <email>"
    exit 1
fi

echo "==> [1/7] 安装系统依赖"
apt-get update -qq
apt-get install -y python3.11 python3.11-venv python3-pip nginx certbot python3-certbot-nginx \
    libreoffice-writer libreoffice-common

echo "==> [2/7] 创建目录结构"
mkdir -p "$INSTALL_DIR"/{backend,frontend/dist,data/{uploads,results},deploy}
cp -r "$REPO_DIR/backend/." "$INSTALL_DIR/backend/"
cp -r "$REPO_DIR/frontend/dist/." "$INSTALL_DIR/frontend/dist/" 2>/dev/null || echo "  前端 dist 未找到，请先执行 npm run build"
cp -r "$REPO_DIR/deploy/." "$INSTALL_DIR/deploy/"

echo "==> [3/7] 创建 Python 虚拟环境"
python3.11 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip -q
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/backend/requirements.txt" -q 2>/dev/null \
    || "$INSTALL_DIR/venv/bin/pip" install -e "$INSTALL_DIR/backend" -q

echo "==> [4/7] 配置 .env（请编辑 $INSTALL_DIR/.env）"
if [[ ! -f "$INSTALL_DIR/.env" ]]; then
    cp "$REPO_DIR/backend/.env.example" "$INSTALL_DIR/.env"
    # 自动生成 SECRET_KEY（64字符随机串）
    SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
    sed -i "s|SECRET_KEY=change-me.*|SECRET_KEY=$SECRET|" "$INSTALL_DIR/.env"
    sed -i "s|CORS_ORIGINS=.*|CORS_ORIGINS=https://$DOMAIN|" "$INSTALL_DIR/.env"
    sed -i "s|COOKIE_SECURE=false|COOKIE_SECURE=true|" "$INSTALL_DIR/.env"
    echo "  .env 已生成，SECRET_KEY 已随机化"
fi

echo "==> [5/7] 配置 Nginx + HTTPS"
bash "$REPO_DIR/deploy/certbot.sh" "$DOMAIN" "$EMAIL"

echo "==> [6/7] 安装 systemd 服务"
sed "s|/opt/industryagent|$INSTALL_DIR|g" "$REPO_DIR/deploy/backend.service" \
    > /etc/systemd/system/industryagent.service
systemctl daemon-reload
systemctl enable industryagent
systemctl restart industryagent

echo "==> [7/7] 检查服务状态"
sleep 3
systemctl is-active industryagent && echo "✓ 后端服务运行中" || echo "✗ 后端服务异常，请检查: journalctl -u industryagent -n 50"
nginx -t && echo "✓ Nginx 配置正确" || echo "✗ Nginx 配置错误"

echo ""
echo "=========================================="
echo "  部署完成！访问: https://$DOMAIN"
echo "  日志: journalctl -fu industryagent"
echo "  配置: $INSTALL_DIR/.env"
echo "=========================================="
