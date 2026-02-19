# Stage 1: Build
FROM node:20-slim AS build-stage
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

# Stage 2: Serve with Nginx
FROM nginx:stable-alpine
COPY --from=build-stage /app/dist /usr/share/nginx/html
# Default Vite port is 5173, but Nginx usually uses 80.
# We'll stick to 80 and map it in docker-compose.
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]