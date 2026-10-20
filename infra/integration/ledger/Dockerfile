ARG BACKEND_IMAGE
FROM ${BACKEND_IMAGE}
COPY --chown=10001:10001 ledger_receiver.py /opt/ledger/ledger_receiver.py
ENV PYTHONDONTWRITEBYTECODE=1
USER 10001
EXPOSE 18445
CMD ["/app/.venv/bin/python", "-I", "/opt/ledger/ledger_receiver.py", "serve", "--settings", "/run/ledger/settings.json"]
