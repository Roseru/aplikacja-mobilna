FROM quay.io/keycloak/keycloak:26.8.1@sha256:a78d6b79572168cb25886b80a8b5b8d4ed4390743e3eecb810538683e209dd6b
RUN /opt/keycloak/bin/kc.sh build --db=postgres --health-enabled=true
ENTRYPOINT ["/opt/keycloak/bin/kc.sh"]
