"""Work-order sync: inbound mapping, closeout, outbound body, status lifecycle.

Since the per-vendor connectors were consolidated into one configurable
generic_rest connector, these tests configure it for a Cityworks-shaped
work-order system (the mapping the old CityworksConnector baked in) to prove
the generic connector handles the full work-order lifecycle when pointed at a
vendor's field names.
"""
from app.integrations.registry import build_connector, PLATFORM_CATALOG

# Cityworks-style field mapping — supplied as config rather than baked into a
# dedicated subclass. This is exactly what an admin would enter to connect a
# Cityworks (or similar WOMS) instance via the generic connector.
CITYWORKS_CONFIG = {
    "base_url": "https://cw/api",
    "auth_style": "bearer",
    "field_map": {
        "service_request_id": "SourceId", "description": "Description", "address": "Address",
        "priority": "Priority", "assigned_to": "AssignedTo",
        "assigned_department": "WorkOrderCategory", "due_date": "ProjectedFinishDate",
    },
    "id_field": "WorkOrderId", "status_field": "Status", "work_order_id_field": "WorkOrderId",
    "priority_field": "Priority", "assigned_to_field": "AssignedTo",
    "assigned_department_field": "WorkOrderCategory", "scheduled_date_field": "ScheduledDate",
    "due_date_field": "ProjectedFinishDate", "resolution_field": "ClosedComments",
}


def test_cityworks_work_order_maps_to_record():
    cw = build_connector("generic_rest", CITYWORKS_CONFIG, {"api_key": "k"})
    rec = cw._record_from_response({
        "WorkOrderId": "WO-5567", "Status": "Assigned", "Description": "Pothole",
        "AssignedTo": "Streets Crew A", "WorkOrderCategory": "Streets",
        "ScheduledDate": "2026-07-10T08:00:00Z", "ProjectedFinishDate": "2026-07-12T00:00:00Z",
        "Priority": "High",
    })
    assert rec.external_id == "WO-5567"
    assert rec.status == "in_progress"
    assert rec.assigned_to == "Streets Crew A"
    assert rec.assigned_department == "Streets"
    assert rec.work_order_id == "WO-5567"
    assert rec.priority == "High"
    assert rec.scheduled_datetime.date().isoformat() == "2026-07-10"
    assert rec.due_datetime.date().isoformat() == "2026-07-12"


def test_completed_maps_to_closed_with_resolution():
    cw = build_connector("generic_rest", CITYWORKS_CONFIG, {"api_key": "k"})
    rec = cw._record_from_response({"WorkOrderId": "WO-9", "Status": "Completed", "ClosedComments": "Patched"})
    assert rec.status == "closed"
    assert rec.resolution == "Patched"


def test_outbound_body_carries_work_order_fields():
    gr = build_connector("generic_rest", {"base_url": "https://sdl"}, {"api_key": "k"})
    body = gr._build_create_body({
        "description": "Leak", "priority": 8, "assigned_to": "Water Div",
        "assigned_department": "Public Works", "due_date": "2026-07-15",
    })
    assert body["priority"] == 8
    assert body["assigned_to"] == "Water Div"
    assert body["department"] == "Public Works"
    assert body["due_date"] == "2026-07-15"


def test_work_order_status_lifecycle():
    gr = build_connector("generic_rest", {"base_url": "https://sdl"}, {"api_key": "k"})
    assert gr.map_status_in("Dispatched") == "in_progress"
    assert gr.map_status_in("On Hold") == "in_progress"
    assert gr.map_status_in("Scheduled") == "in_progress"
    assert gr.map_status_in("Cancelled") == "closed"


def test_catalog_work_orders_capability_consistent():
    for key, meta in PLATFORM_CATALOG.items():
        if "work_orders" in meta["capabilities"]:
            conn = build_connector(key, {"base_url": "https://x"}, {})
            assert "work_orders" in conn.capabilities, f"{key} catalog claims work_orders but connector lacks it"
