class SyncFailure(Exception):
    """Controlled request failure; never contains a private payload."""

    def __init__(self, status, code, details=None):
        self.status, self.code, self.details = status, code, details or {}
        super().__init__(code)
