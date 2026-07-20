"""Vendor connectors built on the open standards bases.

Tyler's citizen-request products speak the Open311 GeoReport v2 standard, so
the Tyler connector is a thin subclass of the real Open311 connector. Vendors
that instead issue a customer-specific JSON REST API (Cityworks, SDL, Edmunds,
GovPilot, FastTrackGov, Polimorphic, …) are served by the single configurable
GenericRestConnector (platform "generic_rest") rather than one speculative
subclass each — see app/integrations/connectors/generic_rest.py.
"""

from app.integrations.connectors.open311 import Open311Connector


class TylerConnector(Open311Connector):
    """Tyler Technologies (Tyler 311 / MyCivic / EnerGov CSS).

    Tyler's citizen-request products expose Open311 GeoReport v2 endpoints per
    jurisdiction; the base URL and api_key come from your Tyler implementation
    team.
    """
    platform = "tyler"
