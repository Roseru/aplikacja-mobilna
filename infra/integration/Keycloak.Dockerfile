FROM quay.io/keycloak/keycloak:26.8.2@sha256:3879c623248408de29a5303178b5816c77e8dfef3890c361f8c0bbeaa979ba3b
RUN /opt/keycloak/bin/kc.sh build --db=postgres --health-enabled=true
ENTRYPOINT ["/opt/keycloak/bin/kc.sh"]
