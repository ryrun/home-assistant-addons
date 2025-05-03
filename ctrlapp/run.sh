#!/bin/sh

CERT_PATH="/certs/cert.pem"
KEY_PATH="/certs/key.pem"

echo "[CtrlApp] Generating new self-signed certificate..."
openssl req -x509 -nodes -days 365 \
  -newkey rsa:2048 \
  -keyout "$KEY_PATH" \
  -out "$CERT_PATH" \
  -subj "/CN=localhost"

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
