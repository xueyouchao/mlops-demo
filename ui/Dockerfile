#### Stage 1: build the Vite app
FROM node:20-alpine AS builder
WORKDIR /app
COPY package.json ./
COPY vite.config.ts ./
COPY index.html ./
RUN npm install
COPY src ./src
RUN npm run build

#### Stage 2: serve via Nginx, acting as the single-origin gateway.
# Diagram HTMLs are volume-mounted into /usr/share/nginx/html/diagrams (see
# docker-compose) so they can be updated without rebuilding the image.
FROM nginx:1.27-alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
