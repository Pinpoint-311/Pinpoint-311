"""
Notification services for SMS and Email with configurable providers.
"""
import os
import httpx
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, Dict, Any
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


# ============ SMS Providers ============

class SMSProvider(ABC):
    """Base class for SMS providers"""
    
    @abstractmethod
    async def send_sms(self, to: str, message: str) -> bool:
        pass


class TwilioProvider(SMSProvider):
    """Twilio SMS provider"""
    
    def __init__(self, account_sid: str, auth_token: str, from_number: str):
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_number = from_number
        self.base_url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    
    async def send_sms(self, to: str, message: str) -> bool:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.base_url,
                    auth=(self.account_sid, self.auth_token),
                    data={
                        "To": to,
                        "From": self.from_number,
                        "Body": message
                    }
                )
                return response.status_code == 201
        except Exception as e:
            logger.warning(f"Twilio SMS error: {e}")
            return False


class GenericHTTPSMSProvider(SMSProvider):
    """Generic HTTP-based SMS provider for any API (supports Textbelt, etc.)"""
    
    def __init__(self, api_url: str, api_key: str, from_number: str):
        self.api_url = api_url
        self.api_key = api_key
        self.from_number = from_number
        # Detect if this is Textbelt based on URL
        self.is_textbelt = "textbelt" in api_url.lower()
    
    async def send_sms(self, to: str, message: str) -> bool:
        try:
            async with httpx.AsyncClient() as client:
                if self.is_textbelt:
                    # Textbelt format: phone, message, key (no auth header)
                    response = await client.post(
                        self.api_url,
                        data={
                            "phone": to,
                            "message": message,
                            "key": self.api_key
                        }
                    )
                    # Textbelt returns JSON with "success": true/false
                    if response.is_success:
                        result = response.json()
                        logger.debug(f"[Textbelt SMS] Response: {result}")
                        if not result.get("success"):
                            logger.warning(f"[Textbelt SMS] Error: {result.get('error', 'Unknown error')}")
                        return result.get("success", False)
                    logger.warning(f"[Textbelt SMS] HTTP Error: {response.status_code}")
                    return False
                else:
                    # Standard format with Bearer auth
                    response = await client.post(
                        self.api_url,
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json"
                        },
                        json={
                            "to": to,
                            "from": self.from_number,
                            "message": message
                        }
                    )
                    return response.is_success
        except Exception as e:
            logger.warning(f"HTTP SMS error: {e}")
            return False


# ============ Email Provider ============

class EmailProvider:
    """SMTP Email provider"""
    
    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        smtp_user: str,
        smtp_password: str,
        from_email: str,
        from_name: str = "Township 311",
        use_tls: bool = True
    ):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.from_email = from_email
        self.from_name = from_name
        self.use_tls = use_tls
    
    def send_email(
        self,
        to: str,
        subject: str,
        body_html: str,
        body_text: Optional[str] = None
    ) -> bool:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"{self.from_name} <{self.from_email}>"
            msg["To"] = to
            
            if body_text:
                msg.attach(MIMEText(body_text, "plain"))
            msg.attach(MIMEText(body_html, "html"))
            
            if self.use_tls:
                with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                    server.starttls()
                    server.login(self.smtp_user, self.smtp_password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port) as server:
                    server.login(self.smtp_user, self.smtp_password)
                    server.send_message(msg)
            
            return True
        except Exception as e:
            logger.error(f"Email error: {e}")
            return False


# ============ Notification Service ============

class NotificationService:
    """Unified notification service for SMS and Email"""
    
    _instance = None
    _sms_provider: Optional[SMSProvider] = None
    _email_provider: Optional[EmailProvider] = None
    
    @classmethod
    def get_instance(cls) -> "NotificationService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def configure_sms(self, provider_type: str, config: Dict[str, Any]):
        """Configure SMS provider dynamically"""
        if provider_type == "twilio":
            self._sms_provider = TwilioProvider(
                account_sid=config.get("account_sid", ""),
                auth_token=config.get("auth_token", ""),
                from_number=config.get("from_number", "")
            )
        elif provider_type == "http":
            self._sms_provider = GenericHTTPSMSProvider(
                api_url=config.get("api_url", ""),
                api_key=config.get("api_key", ""),
                from_number=config.get("from_number", "")
            )
    
    def configure_email(self, config: Dict[str, Any]):
        """Configure Email provider"""
        self._email_provider = EmailProvider(
            smtp_host=config.get("smtp_host", ""),
            smtp_port=config.get("smtp_port", 587),
            smtp_user=config.get("smtp_user", ""),
            smtp_password=config.get("smtp_password", ""),
            from_email=config.get("from_email", ""),
            from_name=config.get("from_name", "Township 311"),
            use_tls=config.get("use_tls", True)
        )
    
    async def send_sms(self, to: str, message: str) -> bool:
        """Send SMS notification"""
        if not self._sms_provider:
            logger.warning("SMS provider not configured")
            return False
        return await self._sms_provider.send_sms(to, message)
    
    def send_email(
        self,
        to: str,
        subject: str,
        body_html: str,
        body_text: Optional[str] = None
    ) -> bool:
        """Send email notification"""
        if not self._email_provider:
            logger.warning("Email provider not configured")
            return False
        return self._email_provider.send_email(to, subject, body_html, body_text)
    
    def send_request_confirmation_branded(
        self,
        request_id: str,
        service_name: str,
        description: str,
        address: Optional[str],
        email: str,
        phone: Optional[str],
        township_name: str,
        logo_url: Optional[str],
        primary_color: str,
        portal_url: str,
        language: str = "en"
    ):
        """Send branded confirmation for a new service request (sync - uses static translations only)"""
        from app.services.email_templates import build_confirmation_email, build_sms_confirmation
        
        # Build branded email with translation
        email_content = build_confirmation_email(
            township_name=township_name,
            logo_url=logo_url,
            primary_color=primary_color,
            request_id=request_id,
            service_name=service_name,
            description=description,
            address=address,
            portal_url=portal_url,
            language=language
        )
        
        # Send email
        if email:
            self.send_email(email, email_content["subject"], email_content["html"], email_content["text"])
        
        # Send SMS - removed as not in scope for confirmation
    
    async def send_request_confirmation_branded_async(
        self,
        request_id: str,
        service_name: str,
        description: str,
        address: Optional[str],
        email: str,
        phone: Optional[str],
        township_name: str,
        logo_url: Optional[str],
        primary_color: str,
        portal_url: str,
        language: str = "en"
    ):
        """
        Send branded confirmation for a new service request (async - uses Google Translate API).
        Supports 130+ languages with automatic translation and caching.
        """
        from app.services.email_templates import build_confirmation_email_async
        
        # Build branded email with translation via Google Translate API
        email_content = await build_confirmation_email_async(
            township_name=township_name,
            logo_url=logo_url,
            primary_color=primary_color,
            request_id=request_id,
            service_name=service_name,
            description=description,
            address=address,
            portal_url=portal_url,
            language=language
        )
        
        # Send email
        if email:
            self.send_email(email, email_content["subject"], email_content["html"], email_content["text"])
    
    
    def send_request_confirmation(self, request_id: str, email: str, phone: Optional[str] = None):
        """Legacy confirmation - now calls branded version with defaults"""
        # This is a fallback for legacy calls - will use basic template
        subject = f"Request #{request_id} Received"
        body_html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #333;">
            <h2>Your Request Has Been Received</h2>
            <p>Thank you for submitting a service request to your local township.</p>
            <p><strong>Request ID:</strong> {request_id}</p>
            <p>You can track the status of your request using this ID.</p>
            <p>We appreciate your help in making our community better!</p>
            <hr>
            <p style="color: #666; font-size: 12px;">
                This is an automated message. Please do not reply directly to this email.
            </p>
        </body>
        </html>
        """
        body_text = f"Your service request #{request_id} has been received. Thank you!"
        
        # Send email
        if email:
            self.send_email(email, subject, body_html, body_text)
    
    async def send_status_update_branded(
        self,
        request_id: str,
        service_name: str,
        old_status: str,
        new_status: str,
        completion_message: Optional[str],
        completion_photo_url: Optional[str],
        email: Optional[str],
        phone: Optional[str],
        township_name: str,
        logo_url: Optional[str],
        primary_color: str,
        portal_url: str,
        language: str = "en"
    ):
        """
        Send branded status update notification with completion photo support.
        Uses Google Translate API for 130+ languages with caching.
        """
        from app.services.email_templates import build_status_update_email_async, build_sms_status_update_async
        
        # Build branded email with translation
        email_content = await build_status_update_email_async(
            township_name=township_name,
            logo_url=logo_url,
            primary_color=primary_color,
            request_id=request_id,
            service_name=service_name,
            old_status=old_status,
            new_status=new_status,
            completion_message=completion_message,
            completion_photo_url=completion_photo_url,
            portal_url=portal_url,
            language=language
        )
        
        if email:
            self.send_email(email, email_content["subject"], email_content["html"], email_content["text"])
        
        if phone:
            sms_message = await build_sms_status_update_async(
                request_id, new_status, township_name, portal_url, 
                completion_message or "", service_name, language
            )
            await self.send_sms(phone, sms_message)
    
    async def send_status_update(
        self,
        request_id: str,
        new_status: str,
        email: Optional[str] = None,
        phone: Optional[str] = None
    ):
        """Legacy status update - uses basic template"""
        status_text = {
            "open": "is now open and being reviewed",
            "in_progress": "is now being worked on",
            "closed": "has been resolved"
        }.get(new_status, f"status changed to {new_status}")
        
        subject = f"Request #{request_id} Status Update"
        body_html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #333;">
            <h2>Request Status Update</h2>
            <p>Your service request <strong>#{request_id}</strong> {status_text}.</p>
            <p>Thank you for your patience!</p>
        </body>
        </html>
        """
        sms_message = f"Request #{request_id} {status_text}"
        
        if email:
            self.send_email(email, subject, body_html)
        
        if phone:
            await self.send_sms(phone, sms_message)
    
    async def send_comment_notification_async(
        self,
        request_id: str,
        service_name: str,
        comment_author: str,
        comment_content: str,
        email: str,
        township_name: str,
        logo_url: Optional[str],
        primary_color: str,
        portal_url: str,
        language: str = "en"
    ):
        """
        Send notification when staff leaves a public comment.
        Uses Google Translate API for 130+ languages with caching.
        """
        from app.services.email_templates import build_comment_email_async
        
        email_content = await build_comment_email_async(
            township_name=township_name,
            logo_url=logo_url,
            primary_color=primary_color,
            request_id=request_id,
            service_name=service_name,
            comment_author=comment_author,
            comment_content=comment_content,
            portal_url=portal_url,
            language=language
        )
        
        if email:
            self.send_email(email, email_content["subject"], email_content["html"], email_content["text"])
    
    def send_comment_notification(
        self,
        request_id: str,
        service_name: str,
        comment_author: str,
        comment_content: str,
        email: str,
        township_name: str,
        logo_url: Optional[str],
        primary_color: str,
        portal_url: str
    ):
        """Send notification when staff leaves a public comment (sync - static translations only)"""
        from app.services.email_templates import build_comment_email
        
        email_content = build_comment_email(
            township_name=township_name,
            logo_url=logo_url,
            primary_color=primary_color,
            request_id=request_id,
            service_name=service_name,
            comment_author=comment_author,
            comment_content=comment_content,
            portal_url=portal_url
        )
        
        if email:
            self.send_email(email, email_content["subject"], email_content["html"], email_content["text"])


# Singleton instance
notification_service = NotificationService.get_instance()

