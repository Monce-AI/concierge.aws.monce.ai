#!/bin/bash
# Deploy Concierge API to EC2 server
# Usage: ./deploy.sh [server_ip]

set -e

cd "$(dirname "$0")"

SERVER_IP="${1:-$(terraform output -raw public_ip 2>/dev/null || echo "")}"
KEY_PATH="$HOME/.ssh/vlm-extraction-key.pem"
REMOTE_USER="ubuntu"
SSH_CMD="ssh -i $KEY_PATH $REMOTE_USER@$SERVER_IP"

if [ -z "$SERVER_IP" ]; then
    echo "ERROR: No server IP. Run 'terraform apply' first or pass IP as argument"
    exit 1
fi

echo "========================================"
echo "  Deploying Concierge API to $SERVER_IP"
echo "========================================"

if [ ! -f "$KEY_PATH" ]; then
    echo "ERROR: SSH key not found at $KEY_PATH"
    exit 1
fi

# Sync app files
echo "-> Syncing app files..."
rsync -avz --exclude '__pycache__' --exclude '*.pyc' --exclude '.git' \
    --exclude 'terraform' --exclude 'venv' --exclude '.venv' \
    --exclude '.egg-info' \
    -e "ssh -i $KEY_PATH" \
    ../ $REMOTE_USER@$SERVER_IP:/opt/concierge/app/

# Ensure .env exists (empty is fine, prevents systemd crash)
$SSH_CMD 'touch /opt/concierge/.env'

# Create data dirs
$SSH_CMD 'mkdir -p /opt/concierge/data'

# Create venv + install deps
echo "-> Installing dependencies..."
$SSH_CMD 'cd /opt/concierge && \
    ([ -d venv ] || python3 -m venv venv) && \
    source venv/bin/activate && \
    pip install --upgrade pip -q && \
    pip install fastapi uvicorn pydantic requests gunicorn -q'

# Create systemd service
echo "-> Configuring systemd..."
$SSH_CMD 'sudo tee /etc/systemd/system/concierge.service > /dev/null' << 'SERVICE'
[Unit]
Description=Moncey Concierge — Monce AI Memory & Intelligence
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/opt/concierge/app
EnvironmentFile=/opt/concierge/.env
Environment="PATH=/opt/concierge/venv/bin"
ExecStart=/opt/concierge/venv/bin/gunicorn -k uvicorn.workers.UvicornWorker --bind 127.0.0.1:8000 --workers 2 --timeout 60 api.main:app
Restart=always

[Install]
WantedBy=multi-user.target
SERVICE

$SSH_CMD 'sudo systemctl daemon-reload && sudo systemctl enable concierge && sudo systemctl restart concierge'

# Configure nginx (only if SSL not already configured)
HAS_SSL=$($SSH_CMD 'grep -q ssl_certificate /etc/nginx/sites-enabled/concierge 2>/dev/null && echo yes || echo no')

if [ "$HAS_SSL" = "yes" ]; then
    echo "-> Nginx SSL already configured, preserving..."
    $SSH_CMD 'sudo systemctl reload nginx'
else
    echo "-> Configuring nginx..."
    $SSH_CMD 'sudo tee /etc/nginx/sites-available/concierge > /dev/null' << 'NGINX'
server {
    listen 80;
    server_name concierge.aws.monce.ai;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
        proxy_read_timeout 60s;
        proxy_connect_timeout 60s;
    }
}
NGINX

    $SSH_CMD 'sudo ln -sf /etc/nginx/sites-available/concierge /etc/nginx/sites-enabled/ && \
        sudo rm -f /etc/nginx/sites-enabled/default && \
        sudo nginx -t && sudo systemctl reload nginx'
fi

# Verify
echo "-> Verifying..."
$SSH_CMD 'sudo systemctl status concierge --no-pager' || true

echo ""
echo "========================================"
echo "  Deployment complete!"
echo ""
echo "  HTTPS: https://concierge.aws.monce.ai"
echo "  Chat:  https://concierge.aws.monce.ai/ui"
echo ""
echo "  Add tokens to /opt/concierge/.env:"
echo "  AWS_BEARER_TOKEN_BEDROCK=..."
echo "========================================"
