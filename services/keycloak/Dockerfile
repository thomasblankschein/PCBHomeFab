# PCBHomeFab login: Keycloak with the realm "pcbhomefab" (OpenID Connect). Build context: this folder.
# The options that Keycloak fixes at build time (database, relative path, health check) are set here, the rest comes
# from the environment of the compose file.
FROM quay.io/keycloak/keycloak:26.4 AS builder
ENV KC_DB=postgres \
    KC_HEALTH_ENABLED=true \
    KC_HTTP_RELATIVE_PATH=/auth
COPY realm/pcbhomefab-realm.json /opt/keycloak/data/import/pcbhomefab-realm.json
RUN /opt/keycloak/bin/kc.sh build

FROM quay.io/keycloak/keycloak:26.4
COPY --from=builder /opt/keycloak/ /opt/keycloak/
ENTRYPOINT ["/opt/keycloak/bin/kc.sh"]
# --import-realm creates the realm at the first start and leaves an existing one alone
CMD ["start", "--optimized", "--import-realm"]
