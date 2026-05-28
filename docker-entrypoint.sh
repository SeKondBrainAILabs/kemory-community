#!/bin/sh
# Generate runtime config from environment variables.
# This allows the same Docker image to work across environments
# without rebuilding (VITE_ vars are baked at build time).

cat > /usr/share/nginx/html/config.json <<EOF
{
  "KEYCLOAK_URL": "${KEYCLOAK_PUBLIC_URL:-/auth}",
  "KEYCLOAK_REALM": "${KEYCLOAK_REALM:-s9n-mvp}",
  "KEYCLOAK_CLIENT_ID": "${KEYCLOAK_CLIENT_ID:-kemory-dashboard}",
  "SKIP_AUTH": "${SKIP_AUTH:-true}",
  "API_KEY": "${API_KEY:-}"
}
EOF

exec nginx -g "daemon off;"
