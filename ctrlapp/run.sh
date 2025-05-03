#!/bin/sh

CERT_PATH="/certs/cert.pem"
KEY_PATH="/certs/key.pem"
RENEW_DAYS=30
RENEW_SECS=$((RENEW_DAYS * 86400))
CERT_RENEW_REQUIRED=0

# Check if cert is missing or about to expire
if [ ! -f "$CERT_PATH" ] || [ ! -f "$KEY_PATH" ]; then
  CERT_RENEW_REQUIRED=1
elif ! openssl x509 -checkend "$RENEW_SECS" -noout -in "$CERT_PATH" > /dev/null 2>&1; then
  CERT_RENEW_REQUIRED=1
fi

if [ "$CERT_RENEW_REQUIRED" -eq 1 ]; then
  echo "[CtrlApp] Generating new self-signed certificate..."
  mkdir -p /certs
  openssl req -x509 -nodes -days 365 \
    -newkey rsa:2048 \
    -keyout "$KEY_PATH" \
    -out "$CERT_PATH" \
    -subj "/CN=localhost" \
    > /dev/null 2>&1
else
  echo "[CtrlApp] Certificate is still valid – no renewal needed."
fi

echo "[CtrlApp] Starting NGINX..."

# Generate minimal nginx config with HTTPS and static file serving
cat <<EOF > /etc/nginx/nginx.conf
events {}

http {
    include       mime.types;
    default_type  application/octet-stream;

    server {
        listen 8443 ssl;
        ssl_certificate $CERT_PATH;
        ssl_certificate_key $KEY_PATH;

        location / {
            root /www;
            index index.html;
            try_files \$uri \$uri/ /index.html;
        }
    }
}
EOF

# Run nginx in the foreground
nginx -g "daemon off;"
