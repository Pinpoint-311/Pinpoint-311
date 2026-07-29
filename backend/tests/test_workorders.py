"""Work-order sync: inbound mapping, closeout, outbound body, status lifecycle."""
from app.integrations.registry import build_connector, PLATFORM_CATALOG


def test_cityworks_work_order_maps_to_record():
    cw = build_connector("cityworks", {"base_url": "https://cw/api"}, {"api_key": "k"})
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
    cw = build_connector("cityworks", {"base_url": "https://cw/api"}, {"api_key": "k"})
    rec = cw._record_from_response({"WorkOrderId": "WO-9", "Status": "Completed", "ClosedComments": "Patched"})
    assert rec.status == "closed"
    assert rec.resolution == "Patched"


def test_outbound_body_carries_work_order_fields():
    gr = build_connector("sdl", {"base_url": "https://sdl"}, {"api_key": "k"})
    body = gr._build_create_body({
        "description": "Leak", "priority": 8, "assigned_to": "Water Div",
        "assigned_department": "Public Works", "due_date": "2026-07-15",
    })
    assert body["priority"] == 8
    assert body["assigned_to"] == "Water Div"
    assert body["department"] == "Public Works"
    assert body["due_date"] == "2026-07-15"


def test_work_order_status_lifecycle():
    gr = build_connector("sdl", {"base_url": "https://sdl"}, {"api_key": "k"})
    assert gr.map_status_in("Dispatched") == "in_progress"
    assert gr.map_status_in("On Hold") == "in_progress"
    assert gr.map_status_in("Scheduled") == "in_progress"
    assert gr.map_status_in("Cancelled") == "closed"


def test_catalog_work_orders_capability_consistent():
    for key, meta in PLATFORM_CATALOG.items():
        if "work_orders" in meta["capabilities"]:
            conn = build_connector(key, {"base_url": "https://x"}, {})
            assert "work_orders" in conn.capabilities, f"{key} catalog claims work_orders but connector lacks it"
