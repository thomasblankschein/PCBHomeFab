# PCBHomeFab frontend: static pages served by Caddy. Build context: this folder.
FROM caddy:2

# The packaged binary carries a file capability (bind to low ports) that cannot be used when all capabilities are
# dropped. A copy has no file capability and is enough for port 8080.
RUN cp /usr/bin/caddy /usr/local/bin/caddy-static
COPY Caddyfile /etc/caddy/Caddyfile
COPY site /srv

USER 10001
ENV XDG_DATA_HOME=/tmp/caddy-data \
    XDG_CONFIG_HOME=/tmp/caddy-config
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1

CMD ["caddy-static", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
