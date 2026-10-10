"""Actual HTTP transport; access tokens stay in the caller's session memory."""

from urllib.parse import urlsplit

import httpx

from .store import ClientError
from .wire import encode_json, loads


class SyncHTTP:
    def __init__(self, base_url, *, token_supplier, http=None):
        url = urlsplit(base_url)
        if url.username or url.password or url.query or url.fragment or not url.hostname:
            raise ClientError("invalid_api_url")
        if url.scheme != "https" and not (
            url.scheme == "http" and url.hostname in ("127.0.0.1", "localhost", "::1")
        ):
            raise ClientError("https_required")
        self.base_url = base_url.rstrip("/")
        self.token_supplier = token_supplier
        self.http = http or httpx.Client(timeout=15, follow_redirects=False)

    def close(self):
        self.http.close()

    def _request(
        self, store, context, method, path, *, params=None, content=None, reconciliation=False
    ):
        store._check(context, reconciliation=reconciliation)
        # Supplier must verify the captured exact identity, never substitute the active user.
        token = self.token_supplier(context)
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
        if content is not None:
            headers["Content-Type"] = "application/json"
        with self.http.stream(
            method, self.base_url + path, headers=headers, params=params, content=content
        ) as response:
            body = bytearray()
            for part in response.iter_bytes():
                body.extend(part)
                if len(body) > 4 * 1048576:
                    raise ClientError("response_too_large")
            value = loads(bytes(body).decode("utf-8", errors="strict"))
            if response.status_code != 200:
                code = value.get("code", "http_error") if isinstance(value, dict) else "http_error"
                store.handle_error(context, code)
                raise ClientError(code)
            return value

    def push(self, store, context, *, recovery_only=False, after_response=None):
        request = store.prepare_push(context, recovery_only=recovery_only)
        response = self._request(
            store,
            context,
            "POST",
            "/api/v1/sync/push",
            content=encode_json(request),
            reconciliation=recovery_only,
        )
        if after_response:
            after_response(response)
        store.apply_push(context, request, response)
        return response

    def pull_page(self, store, context, session_id, *, after_response=None):
        request = store.prepare_pull(context, session_id)
        params = []
        for key, value in request.items():
            if isinstance(value, list):
                params.extend((key, item) for item in value)
            else:
                params.append((key, str(value)))
        response = self._request(
            store, context, "GET", "/api/v1/sync/pull", params=params, reconciliation=True
        )
        if after_response:
            after_response(response)
        return store.apply_pull(context, session_id, request, response)

    def pull(self, store, context, *, full=False, limit=500, recovery_ids=None):
        session_id = store.start_pull(context, full=full, limit=limit, recovery_ids=recovery_ids)
        while not self.pull_page(store, context, session_id):
            pass
        return session_id
