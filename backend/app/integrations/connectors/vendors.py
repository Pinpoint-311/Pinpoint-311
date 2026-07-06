"""Thin vendor-specific connectors built on the Open311 and generic REST bases.

These vendors issue API endpoints and credentials per customer (partner APIs)
rather than publishing one universal public endpoint. Each subclass bakes in
the vendor's conventional defaults (auth style, header names, status
vocabulary) so an admin typically only needs to paste the base URL + key their
vendor rep provides.
"""

import os

from app.integrations.connectors.generic_rest import GenericRestConnector
from app.integrations.connectors.open311 import Open311Connector


class SandboxConnector(GenericRestConnector):
    """Practice connector pointed at Pinpoint's own built-in sandbox vendor
    (app/api/integration_sandbox.py). Lets anyone verify the full sync
    pipeline — push, photos, comments, status pull, assets, import — without
    credentials for any real platform."""
    platform = "sandbox"
    # The practice sandbox is the Pinpoint backend itself (in-cluster host),
    # so it is the one connector allowed past the SSRF guard.
    allow_internal_hosts = True

    def __init__(self, config, credentials):
        default_url = os.environ.get(
            "SANDBOX_VENDOR_URL",
            # docker-compose service address, reachable from backend and worker
            "http://backend:8000/api/integrations/sandbox-vendor",
        )
        # SECURITY: because this connector bypasses the SSRF guard, the
        # base_url must NOT be user-configurable — a custom value could point
        # the guard-exempt client at internal services or cloud metadata.
        # The sandbox always talks to the operator-pinned address.
        config = {**{k: v for k, v in (config or {}).items() if v}, "base_url": default_url}
        super().__init__(config, credentials)


class TylerConnector(Open311Connector):
    """Tyler Technologies (Tyler 311 / MyCivic / EnerGov CSS).

    Tyler's citizen-request products expose Open311 GeoReport v2 endpoints per
    jurisdiction; the base URL and api_key come from your Tyler implementation
    team.
    """
    platform = "tyler"


class SDLConnector(GenericRestConnector):
    """SDL (Spatial Data Logic) — municipal operations platform.

    SDL provides a customer-scoped REST API (API key issued by SDL support).
    """
    platform = "sdl"

    def __init__(self, config, credentials):
        config = {"auth_style": "api_key_header", "auth_header": "X-API-Key", **(config or {})}
        super().__init__(config, credentials)


class EdmundsConnector(GenericRestConnector):
    """Edmunds GovTech (MCSJ) — finance/community ERP.

    Edmunds enables its REST/web-service interface per customer; request
    endpoint + credentials from Edmunds support.
    """
    platform = "edmunds"

    def __init__(self, config, credentials):
        config = {"auth_style": "basic", **(config or {})}
        super().__init__(config, credentials)


class GovPilotConnector(GenericRestConnector):
    """GovPilot — government management platform (GIS-centric).

    GovPilot issues customer API keys for its report-a-concern and records
    modules through its support team.
    """
    platform = "govpilot"

    def __init__(self, config, credentials):
        config = {"auth_style": "bearer", **(config or {})}
        super().__init__(config, credentials)


class FastTrackGovConnector(GenericRestConnector):
    """FastTrackGov (MS Govern / Harris) — licensing, permitting, code enforcement."""
    platform = "fasttrackgov"

    def __init__(self, config, credentials):
        config = {"auth_style": "api_key_header", "auth_header": "Ocp-Apim-Subscription-Key", **(config or {})}
        super().__init__(config, credentials)


class PolimorphicConnector(GenericRestConnector):
    """Polimorphic — AI front desk / constituent CRM.

    Typical deployment is bidirectional webhooks: Polimorphic's AI voice/chat
    intake POSTs new requests to Pinpoint's inbound webhook URL, and this
    connector pushes Pinpoint requests/status changes to the webhook endpoint
    Polimorphic provisions for your workspace.
    """
    platform = "polimorphic"

    def __init__(self, config, credentials):
        config = {"auth_style": "bearer", **(config or {})}
        super().__init__(config, credentials)


class CityworksConnector(GenericRestConnector):
    """Trimble Cityworks — the dominant public-works work-order & asset
    management system (AMS/PLL).

    Cityworks exposes a token-based REST API. Reports become Cityworks work
    orders; the connector maps the work-order lifecycle (assignment, schedule,
    status, resolution) back into Pinpoint. Ships with Cityworks-oriented field
    defaults that remain configurable to your instance — run the connection
    check to confirm your endpoints.
    """
    platform = "cityworks"

    def __init__(self, config, credentials):
        config = {
            "auth_style": "bearer",
            "field_map": {
                "service_request_id": "SourceId",
                "description": "Description",
                "address": "Address",
                "priority": "Priority",
                "assigned_to": "AssignedTo",
                "assigned_department": "WorkOrderCategory",
                "due_date": "ProjectedFinishDate",
            },
            "id_field": "WorkOrderId",
            "status_field": "Status",
            "work_order_id_field": "WorkOrderId",
            "priority_field": "Priority",
            "assigned_to_field": "AssignedTo",
            "assigned_department_field": "WorkOrderCategory",
            "scheduled_date_field": "ScheduledDate",
            "due_date_field": "ProjectedFinishDate",
            "resolution_field": "ClosedComments",
            **(config or {}),
        }
        super().__init__(config, credentials)
