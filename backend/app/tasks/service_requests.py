from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.models import ServiceRequest, SystemSecret
from app.services.notifications import notification_service
from app.services.geocoding import get_geocoding_service
from sqlalchemy import select
import asyncio


def run_async(coro):
    """Helper to run async functions in sync context"""
    from app.db.session import engine
    
    async def _runner():
        try:
            return await coro
        finally:
            # Important: dispose the engine pool when the loop is about to close
            # to avoid loop-contaminated state in subsequent tasks
            await engine.dispose()
            
    return asyncio.run(_runner())


async def get_secret(db, key_name: str) -> str:
    """Get a secret value from database (decrypts automatically)"""
    from app.core.encryption import decrypt_safe
    
    result = await db.execute(
        select(SystemSecret).where(SystemSecret.key_name == key_name)
    )
    secret = result.scalar_one_or_none()
    if not secret or not secret.is_configured:
        return ""
    
    # Decrypt the stored value (handles both encrypted and legacy plain text)
    return decrypt_safe(secret.key_value) if secret.key_value else ""



async def configure_notifications(db):
    """Configure notification service from database secrets"""
    import logging
    logger = logging.getLogger(__name__)
    
    # Configure SMS provider
    sms_provider = await get_secret(db, "SMS_PROVIDER")
    logger.info(f"[SMS Config] SMS_PROVIDER secret value: '{sms_provider}'")
    
    if sms_provider == "twilio":
        notification_service.configure_sms("twilio", {
            "account_sid": await get_secret(db, "TWILIO_ACCOUNT_SID"),
            "auth_token": await get_secret(db, "TWILIO_AUTH_TOKEN"),
            "from_number": await get_secret(db, "TWILIO_PHONE_NUMBER")
        })
        logger.info("[SMS Config] Configured Twilio provider")
    elif sms_provider == "http":
        api_url = await get_secret(db, "SMS_HTTP_API_URL")
        api_key = await get_secret(db, "SMS_HTTP_API_KEY")
        logger.info(f"[SMS Config] Configuring HTTP provider with URL: {api_url[:50] if api_url else 'EMPTY'}...")
        notification_service.configure_sms("http", {
            "api_url": api_url,
            "api_key": api_key,
            "from_number": await get_secret(db, "SMS_FROM_NUMBER")
        })
        logger.info("[SMS Config] Configured HTTP/Textbelt provider")
    else:
        logger.warning(f"[SMS Config] Unknown or empty SMS_PROVIDER: '{sms_provider}' - SMS will not work")
    
    # Configure Email provider
    email_enabled = await get_secret(db, "EMAIL_ENABLED")
    if email_enabled.lower() == "true":
        smtp_port_str = await get_secret(db, "SMTP_PORT")
        use_tls_str = await get_secret(db, "SMTP_USE_TLS")
        
        notification_service.configure_email({
            "smtp_host": await get_secret(db, "SMTP_HOST"),
            "smtp_port": int(smtp_port_str) if smtp_port_str else 587,
            "smtp_user": await get_secret(db, "SMTP_USER"),
            "smtp_password": await get_secret(db, "SMTP_PASSWORD"),
            "from_email": await get_secret(db, "SMTP_FROM_EMAIL"),
            "from_name": await get_secret(db, "SMTP_FROM_NAME") or "Township 311",
            "use_tls": use_tls_str.lower() != "false" if use_tls_str else True
        })


@celery_app.task(bind=True, max_retries=3)
def analyze_request(self, request_id: int):
    """Analyze service request with Vertex AI (if enabled)"""
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"[AI Analysis] Starting analysis for request {request_id}")
    
    async def _analyze():
        from app.models import SystemSettings
        from app.services.vertex_ai_service import (
            get_historical_context,
            get_spatial_context,
            build_analysis_prompt,
            analyze_with_gemini,
            strip_pii
        )
        from datetime import datetime
        
        async with SessionLocal() as db:
            # Check if AI analysis is enabled
            settings_result = await db.execute(select(SystemSettings).limit(1))
            settings = settings_result.scalar_one_or_none()
            if not settings or not settings.modules.get('ai_analysis', False):
                msg = f"[AI Analysis] Skipped - AI analysis not enabled. modules={settings.modules if settings else 'No settings'}"
                logger.info(msg)
                return {"status": "skipped", "reason": "AI analysis not enabled"}
            
            logger.info(f"[AI Analysis] AI module is enabled, proceeding...")
            
            # Get Vertex AI credentials
            project_id = await get_secret(db, "VERTEX_AI_PROJECT")
            if not project_id:
                msg = "[AI Analysis] Skipped - VERTEX_AI_PROJECT not configured"
                logger.warning(msg)
                return {"status": "skipped", "reason": "VERTEX_AI_PROJECT not configured"}
            
            logger.info(f"[AI Analysis] Project ID found: {project_id}")
            
            location = "global"  # Gemini 3 Flash is available on global endpoints
            service_account_json = await get_secret(db, "VERTEX_AI_SERVICE_ACCOUNT_KEY")
            
            # Get the request
            result = await db.execute(
                select(ServiceRequest).where(ServiceRequest.id == request_id)
            )
            request = result.scalar_one_or_none()
            if not request:
                return {"error": "Request not found"}
            
            # Build request data with PII stripped
            request_data = {
                "service_name": request.service_name,
                "service_code": request.service_code,
                "description": strip_pii(request.description or ""),
                "address": request.address,  # Keep address for context
                "submitted_date": request.requested_datetime.isoformat() if request.requested_datetime else None,
                "matched_asset": request.matched_asset,
                "custom_fields": request.custom_fields,
            }
            
            from app.services.weather_service import get_weather_for_location
            
            # Record time of analysis
            from zoneinfo import ZoneInfo
            analysis_time = datetime.now(ZoneInfo("US/Eastern"))
            request_data["analysis_time"] = analysis_time.strftime("%Y-%m-%d %H:%M:%S %Z")

            # Get historical & spatial context
            historical_context = await get_historical_context(
                db, request.address, request.service_code, request.lat, request.long, exclude_id=request.id, description=request.description or ""
            )
            spatial_context = await get_spatial_context(
                db, request.lat, request.long, request.service_code
            )
            
            # Fetch real-time weather for triage location
            request_data["current_weather"] = await get_weather_for_location(request.lat, request.long)

            # Build the analysis prompt
            prompt = build_analysis_prompt(
                request_data,
                historical_context=historical_context,
                spatial_context=spatial_context
            )
            
            # Get images for multimodal analysis
            image_data = request.media_urls[:3] if request.media_urls else None
            
            # Call Vertex AI
            logger.info(f"[AI Analysis] Calling Vertex AI for request {request_id}...")
            
            analysis_result = await analyze_with_gemini(
                project_id=project_id,
                location=location,
                prompt=prompt,
                image_data=image_data,
                service_account_json=service_account_json if service_account_json else None
            )
            
            logger.info(f"[AI Analysis] Got result: {analysis_result}")
            
            # Check for errors in result
            if "_error" in analysis_result:
                logger.error(f"[AI Analysis] Error from Vertex AI: {analysis_result['_error']}")
            
            # Add similar_reports from historical context to the stored result
            # These are already filtered by geo (500m) + category + description similarity (>25%)
            if historical_context.get("similar_reports"):
                analysis_result["similar_reports"] = historical_context["similar_reports"]
            
            # Store the analysis (but NOT the priority - staff must explicitly accept)
            request.ai_analysis = analysis_result
            # NOTE: We no longer auto-set request.priority or request.vertex_ai_priority_score
            # The AI suggestion is stored in ai_analysis['priority_score'] 
            # Staff must click "Accept AI Score" or manually set priority
            request.flagged = len(analysis_result.get("safety_flags", [])) > 0
            if request.flagged:
                request.flag_reason = ", ".join(analysis_result.get("safety_flags", [])[:3])
            
            # Store summary and timestamp for display (but NOT the priority score)
            request.vertex_ai_summary = analysis_result.get("qualitative_analysis", "")
            request.vertex_ai_analyzed_at = datetime.utcnow()
            
            await db.commit()
            logger.info(f"[AI Analysis] Saved analysis for request {request_id}")
            return {"status": "success", "analysis": analysis_result}
    
    try:
        result = run_async(_analyze())
        logger.info(f"[AI Analysis] Task completed: {result}")
        return result
    except Exception as exc:
        logger.error(f"[AI Analysis] Task failed with error: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=60)


@celery_app.task(bind=True)
def geocode_address(self, request_id: int):
    """Geocode address to lat/long using configured service"""
    async def _geocode():
        async with SessionLocal() as db:
            result = await db.execute(
                select(ServiceRequest).where(ServiceRequest.id == request_id)
            )
            request = result.scalar_one_or_none()
            if not request or not request.address:
                return {"error": "Request or address not found"}
            
            # Get Google Maps API key
            api_key = await get_secret(db, "GOOGLE_MAPS_API_KEY")
            service = get_geocoding_service(api_key if api_key else None)
            
            # Geocode the address
            geo_result = await service.geocode(request.address)
            
            if geo_result:
                request.lat = geo_result.lat
                request.long = geo_result.lng
                await db.commit()
                return {
                    "status": "success",
                    "lat": geo_result.lat,
                    "lng": geo_result.lng,
                    "formatted_address": geo_result.formatted_address
                }
            else:
                return {"status": "geocoding_failed", "address": request.address}
    
    try:
        return run_async(_geocode())
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)


@celery_app.task
def send_notification(request_id: int, notification_type: str):
    """Send notification (email/SMS) for request updates"""
    async def _notify():
        async with SessionLocal() as db:
            # Configure notification providers
            await configure_notifications(db)
            
            # Get the request
            result = await db.execute(
                select(ServiceRequest).where(ServiceRequest.id == request_id)
            )
            request = result.scalar_one_or_none()
            if not request:
                return {"error": "Request not found"}
            
            if notification_type == "confirmation":
                # Send confirmation for new request
                notification_service.send_request_confirmation(
                    request_id=str(request.service_request_id),
                    email=request.email,
                    phone=request.phone
                )
            elif notification_type == "status_update":
                # Send status update
                await notification_service.send_status_update(
                    request_id=str(request.service_request_id),
                    new_status=request.status,
                    email=request.email,
                    phone=request.phone
                )
            
            return {"status": "sent", "type": notification_type}
    
    try:
        return run_async(_notify())
    except Exception as e:
        return {"status": "error", "error": str(e)}


@celery_app.task
def send_branded_notification(request_id: int, notification_type: str, old_status: str = None, completion_message: str = None):
    """Send branded notification (email/SMS) using township branding from SystemSettings"""
    import logging
    logger = logging.getLogger(__name__)
    
    async def _notify():
        from app.models import SystemSettings
        
        async with SessionLocal() as db:
            # Configure notification providers
            await configure_notifications(db)
            
            # Get system settings for branding
            settings_result = await db.execute(select(SystemSettings).limit(1))
            settings = settings_result.scalar_one_or_none()
            
            township_name = settings.township_name if settings else "Your Township"
            logo_url = settings.logo_url if settings else None
            primary_color = settings.primary_color if settings else "#6366f1"
            
            # Check if notifications are enabled via module toggles
            modules = settings.modules if settings else {}
            email_enabled = modules.get('email_notifications', True)  # Default to enabled for backwards compatibility
            sms_enabled = modules.get('sms_alerts', False)
            
            if not email_enabled and not sms_enabled:
                logger.info(f"[Notification] Skipping - both email and SMS notifications disabled in modules")
                return {"status": "skipped", "reason": "notifications disabled"}
            
            # Get custom domain for portal URL
            custom_domain = settings.custom_domain if settings else None
            portal_url = f"https://{custom_domain}" if custom_domain else "http://localhost:5173"
            
            # Get the request
            result = await db.execute(
                select(ServiceRequest).where(ServiceRequest.id == request_id)
            )
            request = result.scalar_one_or_none()
            if not request:
                return {"error": "Request not found"}
            
            logger.info(f"[Notification] Sending {notification_type} for request {request.service_request_id} (email={email_enabled}, sms={sms_enabled})")
            
            # Get user's preferred language for translation
            preferred_lang = request.preferred_language or "en"
            logger.info(f"[Notification] User language: {preferred_lang}")
            
            # Translate content if needed (not English)
            async def translate_if_needed(text: str) -> str:
                """Translate text to user's preferred language if not English"""
                if not text or preferred_lang == "en":
                    return text
                
                try:
                    from app.services.translate import translate_text
                    return await translate_text(text, preferred_lang, "en")
                except Exception as e:
                    logger.warning(f"[Notification] Translation failed: {e}, using original text")
                    return text
            
            if notification_type == "confirmation":
                # Translate service name and description for confirmation
                service_name_translated = await translate_if_needed(request.service_name)
                description_translated = await translate_if_needed(request.description or "")
                
                # Send branded confirmation email if enabled
                if email_enabled and request.email:
                    await notification_service.send_request_confirmation_branded_async(
                        request_id=str(request.service_request_id),
                        service_name=service_name_translated,
                        description=description_translated,
                        address=request.address,
                        email=request.email,
                        phone=request.phone,
                        township_name=township_name,
                        logo_url=logo_url,
                        primary_color=primary_color,
                        portal_url=portal_url,
                        language=preferred_lang
                    )
                
                # Also send SMS if enabled and phone provided
                if sms_enabled and request.phone:
                    from app.services.email_templates import build_sms_confirmation
                    sms_message = build_sms_confirmation(
                        request.service_request_id, 
                        township_name, 
                        portal_url,
                        service_name=service_name_translated,
                        description=description_translated,
                        address=request.address or ""
                    )
                    # Translate SMS message as well
                    sms_translated = await translate_if_needed(sms_message)
                    await notification_service.send_sms(request.phone, sms_translated)
                    
            elif notification_type == "status_update":
                # Translate service name and completion message
                service_name_translated = await translate_if_needed(request.service_name)
                completion_msg_translated = await translate_if_needed(completion_message or request.completion_message or "")
                
                # Send branded status update (checks internally for email/phone)
                await notification_service.send_status_update_branded(
                    request_id=str(request.service_request_id),
                    service_name=service_name_translated,
                    old_status=old_status or "open",
                    new_status=request.status,
                    completion_message=completion_msg_translated if completion_msg_translated else None,
                    completion_photo_url=request.completion_photo_url,
                    email=request.email if email_enabled else None,
                    phone=request.phone if sms_enabled else None,
                    township_name=township_name,
                    logo_url=logo_url,
                    primary_color=primary_color,
                    portal_url=portal_url
                )
            
            return {
                "status": "sent", 
                "type": notification_type, 
                "email": email_enabled, 
                "sms": sms_enabled,
                "language": preferred_lang
            }
    
    try:
        return run_async(_notify())
    except Exception as e:
        logger.error(f"[Notification] Failed: {e}")
        return {"status": "error", "error": str(e)}


@celery_app.task
def send_comment_notification_task(request_id: int, comment_author: str, comment_content: str):
    """Send notification when staff leaves a public comment on a request"""
    import logging
    logger = logging.getLogger(__name__)
    
    async def _notify():
        from app.models import SystemSettings
        
        async with SessionLocal() as db:
            # Configure notification providers
            await configure_notifications(db)
            
            # Get system settings for branding
            settings_result = await db.execute(select(SystemSettings).limit(1))
            settings = settings_result.scalar_one_or_none()
            
            township_name = settings.township_name if settings else "Your Township"
            logo_url = settings.logo_url if settings else None
            primary_color = settings.primary_color if settings else "#6366f1"
            custom_domain = settings.custom_domain if settings else None
            portal_url = f"https://{custom_domain}" if custom_domain else "http://localhost:5173"
            
            # Get the request
            result = await db.execute(
                select(ServiceRequest).where(ServiceRequest.id == request_id)
            )
            request = result.scalar_one_or_none()
            if not request:
                return {"error": "Request not found"}
            
            logger.info(f"[Notification] Sending comment notification for request {request.service_request_id} to {request.email}")
            
            # Get user's preferred language for translation
            preferred_lang = request.preferred_language or "en"
            
            # Translate content if needed
            async def translate_if_needed(text: str) -> str:
                """Translate text to user's preferred language if not English"""
                if not text or preferred_lang == "en":
                    return text
                
                try:
                    from app.services.translate import translate_text
                    return await translate_text(text, preferred_lang, "en")
                except Exception as e:
                    logger.warning(f"[Notification] Translation failed: {e}, using original text")
                    return text
            
            # Translate service name and comment content
            service_name_translated = await translate_if_needed(request.service_name)
            comment_content_translated = await translate_if_needed(comment_content)
            
            # Send comment notification
            notification_service.send_comment_notification(
                request_id=str(request.service_request_id),
                service_name=service_name_translated,
                comment_author=comment_author,
                comment_content=comment_content_translated,
                email=request.email,
                township_name=township_name,
                logo_url=logo_url,
                primary_color=primary_color,
                portal_url=portal_url
            )
            
            return {"status": "sent", "type": "comment", "language": preferred_lang}
    
    try:
        return run_async(_notify())
    except Exception as e:
        logger.error(f"[Notification] Comment notification failed: {e}")
        return {"status": "error", "error": str(e)}


@celery_app.task
def send_department_notification(request_id: int, department_email: str):
    """Notify department staff based on their individual notification preferences"""
    import logging
    logger = logging.getLogger(__name__)
    
    async def _notify():
        from app.models import SystemSettings, Department
        
        async with SessionLocal() as db:
            await configure_notifications(db)
            
            # Get system settings for branding and module checks
            settings_result = await db.execute(select(SystemSettings).limit(1))
            settings = settings_result.scalar_one_or_none()
            
            modules = settings.modules if settings else {}
            sms_enabled_globally = modules.get('sms_alerts', False)
            
            township_name = settings.township_name if settings else "Your Township"
            custom_domain = settings.custom_domain if settings else None
            portal_url = f"https://{custom_domain}" if custom_domain else "http://localhost:5173"
            
            # Get the request
            result = await db.execute(
                select(ServiceRequest).where(ServiceRequest.id == request_id)
            )
            request = result.scalar_one_or_none()
            if not request:
                return {"error": "Request not found"}
            
            # Find staff members who should receive this notification
            # Get department by email to find staff members
            dept_result = await db.execute(
                select(Department).where(Department.routing_email == department_email)
            )
            department = dept_result.scalar_one_or_none()
            
            notified_staff = []
            
            if department:
                # Query staff in this department with their notification preferences
                from app.models import User, user_departments
                staff_result = await db.execute(
                    select(User)
                    .join(user_departments)
                    .where(user_departments.c.department_id == department.id)
                    .where(User.is_active == True)
                )
                staff_members = staff_result.scalars().all()
                
                for staff in staff_members:
                    prefs = staff.notification_preferences or {}
                    
                    # Check if they want new request notifications
                    if not prefs.get('email_new_requests', True) and not prefs.get('sms_new_requests', False):
                        continue
                    
                    # Build notification content
                    subject = f"📋 New Request: {request.service_name}"
                    staff_link = f"{portal_url}/staff#request/{request.service_request_id}"
                    
                    body_html = f"""
                    <html>
                    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
                        <div style="background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%); color: white; padding: 24px; border-radius: 12px 12px 0 0;">
                            <h2 style="margin: 0;">📋 New Request Assigned</h2>
                            <p style="margin: 8px 0 0 0; opacity: 0.9;">{township_name} 311</p>
                        </div>
                        <div style="background: #f8fafc; padding: 24px; border: 1px solid #e2e8f0; border-top: none; border-radius: 0 0 12px 12px;">
                            <p style="margin: 0 0 16px 0;"><strong>Hi {staff.full_name or staff.username},</strong></p>
                            <p style="margin: 0 0 16px 0;">A new service request has been submitted to your department:</p>
                            
                            <div style="background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; margin-bottom: 16px;">
                                <p style="margin: 0 0 8px 0;"><strong>Request ID:</strong> {request.service_request_id}</p>
                                <p style="margin: 0 0 8px 0;"><strong>Category:</strong> {request.service_name}</p>
                                <p style="margin: 0 0 8px 0;"><strong>Address:</strong> {request.address or 'Not provided'}</p>
                                <p style="margin: 0;"><strong>Description:</strong></p>
                                <p style="margin: 8px 0 0 0; color: #475569;">{request.description[:200]}{'...' if len(request.description or '') > 200 else ''}</p>
                            </div>
                            
                            <a href="{staff_link}" style="display: inline-block; background: #6366f1; color: white; text-decoration: none; padding: 12px 24px; border-radius: 8px; font-weight: 500;">View Request →</a>
                        </div>
                    </body>
                    </html>
                    """
                    
                    # Send email if enabled
                    if prefs.get('email_new_requests', True) and staff.email:
                        notification_service.send_email(
                            to=staff.email,
                            subject=subject,
                            body_html=body_html
                        )
                        notified_staff.append({"email": staff.email, "type": "email"})
                    
                    # Send SMS if enabled globally and by user preference
                    if sms_enabled_globally and prefs.get('sms_new_requests', False) and staff.phone:
                        short_desc = (request.description or "")[:50]
                        sms_message = f"""📋 {township_name} 311
New Request: {request.service_name}
"{short_desc}..."
📍 {request.address or 'No address'}

🔗 {staff_link}"""
                        await notification_service.send_sms(staff.phone, sms_message)
                        notified_staff.append({"phone": staff.phone, "type": "sms"})
            
            # Also send to department email as fallback/archive
            if department_email and not notified_staff:
                subject = f"New Service Request: #{request.service_request_id} - {request.service_name}"
                body_html = f"""
                <html>
                <body style="font-family: Arial, sans-serif;">
                    <h2>New Service Request Received</h2>
                    <p><strong>Request ID:</strong> {request.service_request_id}</p>
                    <p><strong>Category:</strong> {request.service_name}</p>
                    <p><strong>Description:</strong></p>
                    <p>{request.description}</p>
                    <p><strong>Address:</strong> {request.address or 'Not provided'}</p>
                    <p><strong>Submitted:</strong> {request.requested_datetime}</p>
                    <hr>
                    <p>Please log in to the staff dashboard to manage this request.</p>
                </body>
                </html>
                """
                notification_service.send_email(
                    to=department_email,
                    subject=subject,
                    body_html=body_html
                )
                notified_staff.append({"email": department_email, "type": "fallback"})
            
            logger.info(f"[Dept Notification] Sent to {len(notified_staff)} recipients for request {request.service_request_id}")
            return {"status": "sent", "recipients": notified_staff}
    
    try:
        return run_async(_notify())
    except Exception as e:
        return {"status": "error", "error": str(e)}


@celery_app.task
def enforce_retention_policy():
    """
    Enforce document retention policy by archiving expired records.
    
    Should be scheduled to run daily via Celery Beat.
    Respects legal holds (flagged records are never archived).
    """
    import logging
    logger = logging.getLogger(__name__)
    
    async def _enforce():
        from app.models import SystemSettings
        from app.services.retention_service import (
            get_records_for_archival,
            archive_record,
            get_retention_policy
        )
        
        async with SessionLocal() as db:
            # Get retention settings
            settings_result = await db.execute(select(SystemSettings).limit(1))
            settings = settings_result.scalar_one_or_none()
            
            if not settings:
                logger.warning("[Retention] No system settings found, using defaults")
                state_code = "NJ"
                override_days = None
                archive_mode = "anonymize"
            else:
                state_code = settings.retention_state_code or "NJ"
                override_days = settings.retention_days_override
                archive_mode = settings.retention_mode or "anonymize"
            
            policy = get_retention_policy(state_code)
            logger.info(f"[Retention] Enforcing policy: {policy['name']} ({policy['retention_years']} years)")
            
            # Get records eligible for archival (limit 100 per run to avoid overwhelming)
            records = await get_records_for_archival(db, state_code, override_days, limit=100)
            
            if not records:
                logger.info("[Retention] No records eligible for archival")
                return {"status": "success", "archived": 0, "policy": policy}
            
            logger.info(f"[Retention] Found {len(records)} records eligible for archival")
            
            archived_count = 0
            skipped_count = 0
            errors = []
            
            for record in records:
                try:
                    result = await archive_record(db, record.id, archive_mode)
                    if result["status"] in ["anonymized", "deleted"]:
                        archived_count += 1
                        logger.info(f"[Retention] Archived record {record.service_request_id}")
                    else:
                        skipped_count += 1
                        logger.info(f"[Retention] Skipped record {record.service_request_id}: {result.get('message')}")
                except Exception as e:
                    errors.append({"record_id": record.id, "error": str(e)})
                    logger.error(f"[Retention] Error archiving {record.id}: {e}")
            
            return {
                "status": "success",
                "policy": policy,
                "archived": archived_count,
                "skipped": skipped_count,
                "errors": len(errors)
            }
    
    try:
        return run_async(_enforce())
    except Exception as e:
        logger.error(f"[Retention] Task failed: {e}")
        return {"status": "error", "error": str(e)}
