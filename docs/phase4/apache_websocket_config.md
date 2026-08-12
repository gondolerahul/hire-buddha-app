# Apache WebSocket Proxy Configuration for Streaming Service

## Problem
Twilio WebSocket connections to `/stream/twilio/{session_id}` fail with Error 31920 
(WebSocket Handshake Error) because Apache is not forwarding WebSocket upgrade headers.

## Required Apache Modules
```bash
sudo a2enmod proxy proxy_http proxy_wstunnel rewrite
sudo systemctl restart apache2
```

## Virtual Host Configuration
Add the following to your Apache virtual host config for `streaming.hirebuddha.com`:

```apache
<VirtualHost *:443>
    ServerName streaming.hirebuddha.com
    
    # SSL Configuration (keep existing)
    SSLEngine on
    SSLCertificateFile /path/to/cert.pem
    SSLCertificateKeyFile /path/to/key.pem
    
    # ===== WebSocket Proxy (MUST come before regular proxy) =====
    # This handles WebSocket upgrade requests for Twilio Media Streams
    RewriteEngine On
    RewriteCond %{HTTP:Upgrade} =websocket [NC]
    RewriteRule /stream/(.*) ws://127.0.0.1:8002/stream/$1 [P,L]
    
    # Also handle the Tata Tele WebSocket path
    RewriteCond %{HTTP:Upgrade} =websocket [NC]
    RewriteRule /webhooks/voice/tata/(.*) ws://127.0.0.1:8002/webhooks/voice/tata/$1 [P,L]
    
    # ===== Regular HTTP Proxy =====
    ProxyPreserveHost On
    ProxyPass / http://127.0.0.1:8002/
    ProxyPassReverse / http://127.0.0.1:8002/
    
    # Increase timeouts for long-lived WebSocket connections
    ProxyTimeout 86400
    
    # Required headers for WebSocket
    RequestHeader set X-Forwarded-Proto "https"
    RequestHeader set X-Forwarded-For "%{REMOTE_ADDR}s"
</VirtualHost>
```

## Verification
After applying changes:
```bash
sudo apachectl configtest
sudo systemctl reload apache2
```

Test WebSocket connectivity:
```bash
# Should return 101 Switching Protocols for WebSocket
curl -i -N \
  -H "Connection: Upgrade" \
  -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Version: 13" \
  -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
  https://streaming.hirebuddha.com/stream/twilio/test-session-id

# Should return a helpful JSON diagnostic message (not 404)
curl https://streaming.hirebuddha.com/stream/twilio/test-session-id
```
