#!/usr/bin/env bash
# certbot.sh — 申请 / 续签 Let's Encrypt 证书
# 用法：sudo bash certbot.sh YOUR_DOMAIN your@email.com
set -euo pipefail

DOMAIN=${1:-""}
EMAIL=${2:-""}

if [[ -z "$DOMAIN" || -z "$EMAIL" ]]; then
    echo "用法: sudo bash certbot.sh <domain> <email>"
    exit 1
fi

# 安装 certbot（Debian/Ubuntu）
if ! command -v certbot &>/dev/null; then
    apt-get update -qq
    apt-get install -y certbot python3-certbot-nginx
fi

# 申请证书（webroot 模式，Nginx 需已启动）
certbot certonly \
    --nginx \
    --non-interactive \
    --agree-tos \
    --email "$EMAIL" \
    -d "$DOMAIN"

# 替换 nginx.conf 里的占位符
NGINX_CONF="/opt/industryagent/deploy/nginx.conf"
sed -i "s/YOUR_DOMAIN/$DOMAIN/g" "$NGINX_CONF"
cp "$NGINX_CONF" /etc/nginx/sites-available/industryagent
ln -sf /etc/nginx/sites-available/industryagent /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx

# 自动续签（certbot 已自带 systemd timer，验证即可）
systemctl status certbot.timer 2>/dev/null || echo "certbot.timer 未启用，请手动配置续签"

echo "✓ HTTPS 证书配置完成: https://$DOMAIN"
