# syntax=docker/dockerfile:1.7

FROM node:24.18.0-alpine AS builder
ARG VITE_API_BASE_URL=/api/v1
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27.5-alpine AS runtime
ARG APP_VERSION=0.1.0
ARG CODE_COMMIT=unknown
ARG SOURCE_URL=https://github.com/sashkotenk/energy-consumption-forecasting-system

LABEL org.opencontainers.image.title="EnergyForecast web" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${CODE_COMMIT}" \
      org.opencontainers.image.source="${SOURCE_URL}"

USER root
RUN rm -f /etc/nginx/conf.d/default.conf \
    && mkdir -p /tmp/nginx/client_temp /tmp/nginx/proxy_temp /tmp/nginx/fastcgi_temp /tmp/nginx/uwsgi_temp /tmp/nginx/scgi_temp \
    && chown -R nginx:nginx /tmp/nginx /usr/share/nginx/html
COPY nginx.conf /etc/nginx/nginx.conf
COPY --from=builder --chown=nginx:nginx /app/dist /usr/share/nginx/html

USER nginx
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
