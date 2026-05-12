# Stage 1: Build
# Digest pinned — see backend/Dockerfile for rationale and bump procedure.
FROM node:26.1.0-slim@sha256:424cafd2a035ed2b2d74acc3142b68b426fb62a47742c80a75e7117db02d6b30 AS build-stage
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
ARG VITE_API_BASE=/api
ENV VITE_API_BASE=$VITE_API_BASE
RUN npm run build

# Stage 2: Serve with Nginx
FROM nginx:1.29-alpine@sha256:5616878291a2eed594aee8db4dade5878cf7edcb475e59193904b198d9b830de
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build-stage /app/dist /usr/share/nginx/html
RUN mkdir -p /var/cache/nginx/client_temp \
             /var/cache/nginx/proxy_temp \
             /var/cache/nginx/fastcgi_temp \
             /var/cache/nginx/uwsgi_temp \
             /var/cache/nginx/scgi_temp \
             /tmp/nginx \
    && chown -R nginx:nginx /var/cache/nginx /tmp/nginx \
    && sed -i 's|/run/nginx.pid|/tmp/nginx/nginx.pid|' /etc/nginx/nginx.conf
EXPOSE 80
USER nginx
CMD ["nginx", "-g", "daemon off;"]