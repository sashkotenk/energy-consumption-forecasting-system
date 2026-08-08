# syntax=docker/dockerfile:1.7

FROM nginx:1.30.4-alpine3.24
ARG APP_VERSION=0.1.0
ARG CODE_COMMIT=unknown
ARG SOURCE_URL=https://github.com/sashkotenk/energy-consumption-forecasting-system

LABEL org.opencontainers.image.title="EnergyForecast edge proxy" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${CODE_COMMIT}" \
      org.opencontainers.image.source="${SOURCE_URL}"

USER root
RUN rm -f /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/nginx.conf

USER nginx
EXPOSE 8080
CMD ["sh", "-c", "mkdir -p /tmp/nginx/client_temp /tmp/nginx/proxy_temp /tmp/nginx/fastcgi_temp /tmp/nginx/uwsgi_temp /tmp/nginx/scgi_temp && exec nginx -g 'daemon off;'"]
