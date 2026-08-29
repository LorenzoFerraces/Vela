FROM node:20-alpine AS build

WORKDIR /app

# Build-time: origin the browser uses to reach the stack (e.g. http://localhost).
# client.ts requires an absolute http(s) origin; the nginx container proxies /api
# to the API, so same-origin requests work without further configuration.
ARG VITE_API_BASE_URL=http://localhost
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
