FROM node:20-alpine AS build

WORKDIR /app

# Build-time: optional API origin baked into the SPA. Leave unset (recommended):
# the SPA then calls same-origin /api, which the nginx container proxies to the
# API — works for local and remote deployments alike.
ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# Unprivileged image: no root process, listens on 8080 (compose maps the host
# port to it).
FROM nginxinc/nginx-unprivileged:alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080

HEALTHCHECK CMD wget --spider http://127.0.0.1:8080/ || exit 1
