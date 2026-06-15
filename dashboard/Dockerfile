FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm install --package-lock-only && npm ci
COPY . .
# FE_VERSION is consumed by vite.config.ts to override the package.json
# default, so the dashboard footer's "FE:x.y.z" badge tracks the actual
# release tag (e.g. "3.37.4" from SDDMini-KH/v3.37.4). When unset (local
# dev, CI/cloud builds), vite falls back to package.json#version.
ARG FE_VERSION=""
ENV FE_VERSION=$FE_VERSION
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh
EXPOSE 5173
CMD ["/docker-entrypoint.sh"]
