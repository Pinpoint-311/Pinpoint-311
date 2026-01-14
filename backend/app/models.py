from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON, Float, Text, Boolean, Table
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from geoalchemy2 import Geometry
from app.db.session import Base


# Association table for ServiceDefinition-Department many-to-many
service_departments = Table(
    "service_departments",
    Base.metadata,
    Column("service_id", Integer, ForeignKey("service_definitions.id"), primary_key=True),
    Column("department_id", Integer, ForeignKey("departments.id"), primary_key=True)
)


# Association table for User-Department many-to-many
user_departments = Table(
    "user_departments",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("department_id", Integer, ForeignKey("departments.id"), primary_key=True)
)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, index=True, nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    full_name = Column(String(255))
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(20), default="staff")  # admin, staff
    is_active = Column(Boolean, default=True)
    notification_preferences = Column(JSON, default={
        "email_new_requests": True,
        "email_status_changes": True,
        "email_comments": True,
        "email_assigned_only": False,
        "sms_new_requests": False,
        "sms_status_changes": False
    })
    phone = Column(String(50))  # Staff phone for SMS alerts
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Staff can be assigned to multiple departments
    departments = relationship(
        "Department",
        secondary=user_departments,
        back_populates="staff_members"
    )


class Department(Base):
    __tablename__ = "departments"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, index=True, nullable=False)
    description = Column(Text)
    routing_email = Column(String(255))
    is_active = Column(Boolean, default=True)
    
    # Multi-language support
    translations = Column(JSON, default={})
    # Format: {"en": {"name": "Public Works", "description": "..."}, "es": {...}}
    
    services = relationship(
        "ServiceDefinition",
        secondary=service_departments,
        back_populates="departments"
    )
    
    staff_members = relationship(
        "User",
        secondary=user_departments,
        back_populates="departments"
    )


class ServiceDefinition(Base):
    __tablename__ = "service_definitions"

    id = Column(Integer, primary_key=True, index=True)
    service_code = Column(String(50), unique=True, index=True, nullable=False)
    service_name = Column(String(100), nullable=False)
    description = Column(Text)
    icon = Column(String(50), default="AlertCircle")  # Lucide icon name
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Routing configuration
    routing_mode = Column(String(50), default="township")  # township, third_party, road_based
    routing_config = Column(JSON, default={})
    # For third_party: { "url": "...", "message": "..." }
    # For road_based: { 
    #   "default": "township|third_party", 
    #   "township_roads": ["Main St", ...],
    #   "county_roads": ["County Rd 1", ...],
    #   "third_party_url": "...", 
    #   "third_party_message": "..." 
    # }
    
    # Multi-language support
    translations = Column(JSON, default={})
    # Format: {
    #   "en": {"service_name": "Pothole Repair", "description": "Report road damage"},
    #   "es": {"service_name": "Reparación de Baches", "description": "Reportar daños"},
    #   ...
    # }
    
    assigned_department_id = Column(Integer, ForeignKey("departments.id"))
    assigned_department = relationship("Department", foreign_keys=[assigned_department_id])
    
    departments = relationship(
        "Department",
        secondary=service_departments,
        back_populates="services"
    )


class ServiceRequest(Base):
    __tablename__ = "service_requests"

    id = Column(Integer, primary_key=True, index=True)
    service_request_id = Column(String(50), unique=True, index=True, nullable=False)
    
    # Service info
    service_code = Column(String(50), index=True, nullable=False)
    service_name = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)
    
    # Status
    status = Column(String(20), default="open", index=True)  # open, in_progress, closed
    priority = Column(Integer, default=5)  # 1-10
    
    # Location
    address = Column(String(500))
    lat = Column(Float)
    long = Column(Float)
    location = Column(Geometry("POINT", srid=4326))
    
    # Reporter info (PII - hidden from public)
    first_name = Column(String(100))
    last_name = Column(String(100))
    email = Column(String(255), nullable=False)
    phone = Column(String(50))
    
    # Resident's preferred language (captured from UI at submission)
    preferred_language = Column(String(10), default="en")  # ISO 639-1 code (en, es, hi, etc.)
    
    # Metadata
    source = Column(String(50), default="resident_portal")  # resident_portal, phone, walk_in, email
    media_urls = Column(JSON, default=[])  # Array of up to 3 photo URLs/base64
    
    # AI Analysis
    ai_analysis = Column(JSON)
    flagged = Column(Boolean, default=False, server_default='false', nullable=False)
    flag_reason = Column(String(255))
    
    # Timestamps
    requested_datetime = Column(DateTime(timezone=True), server_default=func.now())
    updated_datetime = Column(DateTime(timezone=True), onupdate=func.now())
    closed_datetime = Column(DateTime(timezone=True))
    
    # Staff notes
    staff_notes = Column(Text)
    assigned_department_id = Column(Integer, ForeignKey("departments.id"))
    assigned_department = relationship("Department", foreign_keys=[assigned_department_id])
    assigned_to = Column(String(100))
    
    # Matched asset from map layers (detected on submit)
    matched_asset = Column(JSON)  # { layer_name, asset_id, asset_type, properties, distance_meters }
    
    # Custom question responses from resident portal
    custom_fields = Column(JSON)  # { question_id: answer }
    
    # Closed sub-status (when status = 'closed')
    closed_substatus = Column(String(30))  # no_action, resolved, third_party
    completion_message = Column(Text)  # Staff message when closing
    completion_photo_url = Column(String(500))  # Photo proof of resolution
    
    # Soft delete support
    deleted_at = Column(DateTime(timezone=True), index=True)
    deleted_by = Column(String(100))  # Username who deleted
    delete_justification = Column(Text)
    
    # Vertex AI Analysis
    vertex_ai_summary = Column(Text)  # AI-generated summary
    vertex_ai_classification = Column(String(100))  # AI category classification
    # NOTE: AI priority score is stored ONLY in ai_analysis JSON, not as a separate column
    # This ensures staff must explicitly accept AI suggestions before they take effect
    manual_priority_score = Column(Float)  # Human-approved priority (1-10), required for prioritization
    vertex_ai_analyzed_at = Column(DateTime(timezone=True))
    
    # Document retention / archival
    archived_at = Column(DateTime(timezone=True), index=True)  # When record was archived


class RequestComment(Base):
    """Two-way comments on service requests with visibility control"""
    __tablename__ = "request_comments"

    id = Column(Integer, primary_key=True, index=True)
    service_request_id = Column(Integer, ForeignKey("service_requests.id"), nullable=False, index=True)
    
    # Author info
    user_id = Column(Integer, ForeignKey("users.id"))
    username = Column(String(100), nullable=False)
    
    # Comment content
    content = Column(Text, nullable=False)
    
    # Visibility: internal (staff only) or external (visible to resident)
    visibility = Column(String(20), default="internal")  # internal, external
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    service_request = relationship("ServiceRequest", backref="comments")


class RequestAuditLog(Base):
    """Audit trail for all changes to service requests"""
    __tablename__ = "request_audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    service_request_id = Column(Integer, ForeignKey("service_requests.id"), nullable=False, index=True)
    
    # Action type: submitted, status_change, department_assigned, staff_assigned, comment_added
    action = Column(String(50), nullable=False)
    
    # What changed
    old_value = Column(String(255))  # Previous value (e.g., "open", department name)
    new_value = Column(String(255))  # New value (e.g., "in_progress", department name)
    
    # Who made the change
    actor_type = Column(String(20), nullable=False)  # "resident" or "staff"
    actor_name = Column(String(100))  # Username or "Resident"
    
    # When
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Additional context (JSON for flexibility)
    extra_data = Column(JSON)  # { substatus, completion_message, etc. }
    
    # Relationship
    service_request = relationship("ServiceRequest", backref="audit_logs")



class SystemSettings(Base):
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, index=True)
    township_name = Column(String(200), default="Your Township")
    logo_url = Column(String(500))
    favicon_url = Column(String(500))
    hero_text = Column(String(500), default="How can we help?")
    primary_color = Column(String(7), default="#6366f1")
    custom_domain = Column(String(255))  # For custom domain configuration
    modules = Column(JSON, default={"ai_analysis": False, "sms_alerts": False, "email_notifications": True})
    township_boundary = Column(JSON)  # GeoJSON boundary from OpenStreetMap
    
    # Multi-language support
    translations = Column(JSON, default={})
    # Format: {"en": {"township_name": "...", "hero_text": "..."}, "es": {...}}
    
    # Document retention configuration
    retention_state_code = Column(String(2), default="NJ")  # State for retention rules
    retention_days_override = Column(Integer)  # Custom override (null = use state default)
    retention_mode = Column(String(20), default="anonymize")  # "anonymize" or "delete"
    
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())



class SystemSecret(Base):
    __tablename__ = "system_secrets"

    id = Column(Integer, primary_key=True, index=True)
    key_name = Column(String(100), unique=True, index=True, nullable=False)
    key_value = Column(Text)  # Should be encrypted in production
    description = Column(String(255))
    is_configured = Column(Boolean, default=False)


class MapLayer(Base):
    """Custom GeoJSON layers for township assets (parks, storm drains, utilities, etc.)"""
    __tablename__ = "map_layers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)  # "Parks", "Storm Drains", etc.
    description = Column(String(500))
    layer_type = Column(String(50))  # polygon, line, point, or auto-detected
    
    # Styling
    fill_color = Column(String(20), default="#3b82f6")
    stroke_color = Column(String(20), default="#1d4ed8")
    fill_opacity = Column(Float, default=0.3)
    stroke_width = Column(Integer, default=2)
    
    # GeoJSON data
    geojson = Column(JSON, nullable=False)
    
    # Visibility
    is_active = Column(Boolean, default=True)
    show_on_resident_portal = Column(Boolean, default=True)
    
    # Category association - which service categories this layer applies to
    service_codes = Column(JSON, default=list)  # ["streetlight", "pothole", etc.] - empty = all categories
    
    # Polygon routing behavior
    routing_mode = Column(String(20), default="none")  # none, log, block
    visible_on_map = Column(Boolean, default=True)  # Whether to render the layer visually
    
    # Routing for polygons (redirect requests within polygon to third-party)
    routing_config = Column(JSON)  # { "message": "...", "contacts": [{ "name": "...", "phone": "...", "url": "..." }] }
    
    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class ResearchAccessLog(Base):
    """Audit trail for research data access - tracks who downloaded what and when"""
    __tablename__ = "research_access_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    username = Column(String(100), nullable=False)
    
    # Action type: export_csv, export_geojson, query, view_analytics
    action = Column(String(50), nullable=False)
    
    # Query parameters used (filters, date range, etc.)
    parameters = Column(JSON)
    
    # Number of records accessed
    record_count = Column(Integer)
    
    # Whether fuzzed (privacy mode) or exact location was used
    privacy_mode = Column(String(20), default="fuzzed")  # fuzzed, exact
    
    # When
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationship
    user = relationship("User", backref="research_access_logs")
