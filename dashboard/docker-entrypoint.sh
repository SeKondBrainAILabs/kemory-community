#!/bin/sh
# Generate runtime config from environment variables.
# This allows the same Docker image to work across environments
# without rebuilding (VITE_ vars are baked at build time).
#
# The API key is deliberately not written here: config.json is served to
# anyone who can reach the dashboard. The browser asks for the key once and
# keeps it in localStorage (see ApiKeyGate).

cat > /usr/share/nginx/html/config.json <<EOF
{
  "SKIP_AUTH": ${SKIP_AUTH:-true},
  "API_URL": "${API_PUBLIC_URL:-}"
}
EOF

DNS_RESOLVER="${DNS_RESOLVER:-$(awk '/^nameserver/ {print $2; exit}' /etc/resolv.conf)}"
sed -i "s|__DNS_RESOLVER__|${DNS_RESOLVER:-127.0.0.11}|g" \
    /etc/nginx/conf.d/default.conf

exec nginx -g "daemon off;"
