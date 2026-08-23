"""Pluggable connectors for external govtech platforms.

Each supported platform (Accela, Esri ArcGIS, Tyler Technologies, and any
GeoReport v2 or plain JSON REST system) is implemented as a connector class
that speaks that vendor's API and normalizes records into a common shape. See
app/integrations/registry.py for the platform catalog and connector factory.
"""

from app.integrations.registry import (  # noqa: F401
    PLATFORM_CATALOG, RETIRED_PLATFORMS, build_connector, build_connector_for,
    connector_available, is_retired,
)
from app.integrations.base import BaseConnector, ConnectorError, ExternalRecord  # noqa: F401
from app.integrations.credentials import (  # noqa: F401
    resolve_credentials, store_credentials, secret_key_for,
)
