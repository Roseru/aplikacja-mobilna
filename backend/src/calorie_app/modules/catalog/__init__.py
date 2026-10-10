"""Versioned catalog and offline delivery.

The public v1 URLs permanently identify this official package. A different
identity requires a new, explicit channel/contract, never an environment toggle.
"""

from uuid import UUID

OFFICIAL_PACKAGE_ID = UUID("c12631e2-1a02-547c-a7f9-ebf87bb42e55")
