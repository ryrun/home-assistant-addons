# Base image: Alpine with package manager
FROM alpine:3.19

# Install only what's needed: nginx and openssl
RUN apk add --no-cache nginx openssl

# Create necessary directories
RUN mkdir -p /www /certs /etc/nginx

# Copy the startup script and make it executable
COPY run.sh /run.sh
RUN chmod +x /run.sh

# Copy the Angular build output into /www
COPY www/ /www/

# Expose HTTPS port
EXPOSE 8443

# Launch the server
CMD ["/run.sh"]
