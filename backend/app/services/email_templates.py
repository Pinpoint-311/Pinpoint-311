"""
Branded Email Templates for Township 311 System

Generates beautiful, responsive HTML email templates with township branding.
Pulls configuration from SystemSettings for logo, colors, and township name.
"""
from typing import Optional, Dict, Any
from datetime import datetime


# Email template translations for common languages
EMAIL_I18N = {
    "en": {
        "service_portal": "311 Service Portal",
        "request_received": "Request Received!",
        "report_submitted": "Your report has been submitted successfully",
        "request_id": "Request ID",
        "category": "Category",
        "description": "Description",
        "location": "Location",
        "track_request": "Track Your Request",
        "or_visit": "or visit",
        "thank_you": "Thank you for helping make {township} a better place!",
        "no_reply": "Please do not reply directly to this email.",
        "subject_received": "Request #{id} Received - {township}",
        "subject_update": "Update on Request #{id} - {township}",
        "status_updated": "Status Updated",
        "your_request_status": "The status of your request has been updated",
        "new_status": "New Status",
        "message_from_staff": "Message from staff",
        "request_details": "Request Details",
    },
    "es": {
        "service_portal": "Portal de Servicios 311",
        "request_received": "¡Solicitud Recibida!",
        "report_submitted": "Su reporte ha sido enviado exitosamente",
        "request_id": "ID de Solicitud",
        "category": "Categoría",
        "description": "Descripción",
        "location": "Ubicación",
        "track_request": "Seguir Su Solicitud",
        "or_visit": "o visite",
        "thank_you": "¡Gracias por ayudar a hacer de {township} un lugar mejor!",
        "no_reply": "Por favor no responda directamente a este correo.",
        "subject_received": "Solicitud #{id} Recibida - {township}",
        "subject_update": "Actualización de Solicitud #{id} - {township}",
        "status_updated": "Estado Actualizado",
        "your_request_status": "El estado de su solicitud ha sido actualizado",
        "new_status": "Nuevo Estado",
        "message_from_staff": "Mensaje del personal",
        "request_details": "Detalles de la Solicitud",
    },
    "zh": {
        "service_portal": "311服务门户",
        "request_received": "请求已收到！",
        "report_submitted": "您的报告已成功提交",
        "request_id": "请求编号",
        "category": "类别",
        "description": "描述",
        "location": "位置",
        "track_request": "追踪您的请求",
        "or_visit": "或访问",
        "thank_you": "感谢您帮助让{township}变得更好！",
        "no_reply": "请勿直接回复此邮件。",
        "subject_received": "请求 #{id} 已收到 - {township}",
        "subject_update": "请求 #{id} 更新 - {township}",
        "status_updated": "状态已更新",
        "your_request_status": "您的请求状态已更新",
        "new_status": "新状态",
        "message_from_staff": "工作人员留言",
        "request_details": "请求详情",
    },
    "hi": {
        "service_portal": "311 सेवा पोर्टल",
        "request_received": "अनुरोध प्राप्त!",
        "report_submitted": "आपकी रिपोर्ट सफलतापूर्वक जमा की गई है",
        "request_id": "अनुरोध आईडी",
        "category": "श्रेणी",
        "description": "विवरण",
        "location": "स्थान",
        "track_request": "अपना अनुरोध ट्रैक करें",
        "or_visit": "या देखें",
        "thank_you": "{township} को बेहतर बनाने में मदद के लिए धन्यवाद!",
        "no_reply": "कृपया इस ईमेल का सीधे जवाब न दें।",
        "subject_received": "अनुरोध #{id} प्राप्त - {township}",
        "subject_update": "अनुरोध #{id} पर अपडेट - {township}",
        "status_updated": "स्थिति अपडेट",
        "your_request_status": "आपके अनुरोध की स्थिति अपडेट की गई है",
        "new_status": "नई स्थिति",
        "message_from_staff": "स्टाफ से संदेश",
        "request_details": "अनुरोध विवरण",
    },
    "ko": {
        "service_portal": "311 서비스 포털",
        "request_received": "요청이 접수되었습니다!",
        "report_submitted": "귀하의 신고가 성공적으로 제출되었습니다",
        "request_id": "요청 ID",
        "category": "카테고리",
        "description": "설명",
        "location": "위치",
        "track_request": "요청 추적",
        "or_visit": "또는 방문",
        "thank_you": "{township}를 더 나은 곳으로 만드는 데 도움을 주셔서 감사합니다!",
        "no_reply": "이 이메일에 직접 회신하지 마십시오.",
        "subject_received": "요청 #{id} 접수 - {township}",
        "subject_update": "요청 #{id} 업데이트 - {township}",
        "status_updated": "상태 업데이트",
        "your_request_status": "귀하의 요청 상태가 업데이트되었습니다",
        "new_status": "새 상태",
        "message_from_staff": "직원 메시지",
        "request_details": "요청 세부정보",
    },
    "ar": {
        "service_portal": "بوابة خدمة 311",
        "request_received": "تم استلام الطلب!",
        "report_submitted": "تم إرسال تقريرك بنجاح",
        "request_id": "رقم الطلب",
        "category": "الفئة",
        "description": "الوصف",
        "location": "الموقع",
        "track_request": "تتبع طلبك",
        "or_visit": "أو قم بزيارة",
        "thank_you": "شكرًا لمساعدتك في جعل {township} مكانًا أفضل!",
        "no_reply": "يرجى عدم الرد مباشرة على هذا البريد الإلكتروني.",
        "subject_received": "تم استلام الطلب #{id} - {township}",
        "subject_update": "تحديث على الطلب #{id} - {township}",
        "status_updated": "تم تحديث الحالة",
        "your_request_status": "تم تحديث حالة طلبك",
        "new_status": "الحالة الجديدة",
        "message_from_staff": "رسالة من الموظفين",
        "request_details": "تفاصيل الطلب",
    },
    "fr": {
        "service_portal": "Portail de Service 311",
        "request_received": "Demande Reçue!",
        "report_submitted": "Votre signalement a été soumis avec succès",
        "request_id": "Numéro de Demande",
        "category": "Catégorie",
        "description": "Description",
        "location": "Emplacement",
        "track_request": "Suivre Votre Demande",
        "or_visit": "ou visitez",
        "thank_you": "Merci de contribuer à améliorer {township}!",
        "no_reply": "Veuillez ne pas répondre directement à cet email.",
        "subject_received": "Demande #{id} Reçue - {township}",
        "subject_update": "Mise à jour de la Demande #{id} - {township}",
        "status_updated": "Statut Mis à Jour",
        "your_request_status": "Le statut de votre demande a été mis à jour",
        "new_status": "Nouveau Statut",
        "message_from_staff": "Message du personnel",
        "request_details": "Détails de la Demande",
    },
    "pt": {
        "service_portal": "Portal de Serviços 311",
        "request_received": "Solicitação Recebida!",
        "report_submitted": "Seu relato foi enviado com sucesso",
        "request_id": "ID da Solicitação",
        "category": "Categoria",
        "description": "Descrição",
        "location": "Localização",
        "track_request": "Acompanhe Sua Solicitação",
        "or_visit": "ou visite",
        "thank_you": "Obrigado por ajudar a tornar {township} um lugar melhor!",
        "no_reply": "Por favor, não responda diretamente a este email.",
        "subject_received": "Solicitação #{id} Recebida - {township}",
        "subject_update": "Atualização da Solicitação #{id} - {township}",
        "status_updated": "Status Atualizado",
        "your_request_status": "O status da sua solicitação foi atualizado",
        "new_status": "Novo Status",
        "message_from_staff": "Mensagem da equipe",
        "request_details": "Detalhes da Solicitação",
    },
    "ja": {
        "service_portal": "311サービスポータル",
        "request_received": "リクエストを受け付けました！",
        "report_submitted": "レポートは正常に送信されました",
        "request_id": "リクエストID",
        "category": "カテゴリ",
        "description": "説明",
        "location": "場所",
        "track_request": "リクエストを追跡",
        "or_visit": "または訪問",
        "thank_you": "{township}をより良い場所にするためにご協力いただきありがとうございます！",
        "no_reply": "このメールに直接返信しないでください。",
        "subject_received": "リクエスト #{id} 受付 - {township}",
        "subject_update": "リクエスト #{id} 更新 - {township}",
        "status_updated": "ステータス更新",
        "your_request_status": "リクエストのステータスが更新されました",
        "new_status": "新しいステータス",
        "message_from_staff": "スタッフからのメッセージ",
        "request_details": "リクエスト詳細",
    },
    "vi": {
        "service_portal": "Cổng Dịch vụ 311",
        "request_received": "Yêu Cầu Đã Nhận!",
        "report_submitted": "Báo cáo của bạn đã được gửi thành công",
        "request_id": "Mã Yêu Cầu",
        "category": "Danh Mục",
        "description": "Mô Tả",
        "location": "Địa Điểm",
        "track_request": "Theo Dõi Yêu Cầu",
        "or_visit": "hoặc truy cập",
        "thank_you": "Cảm ơn bạn đã giúp {township} trở nên tốt đẹp hơn!",
        "no_reply": "Vui lòng không trả lời trực tiếp email này.",
        "subject_received": "Yêu cầu #{id} Đã Nhận - {township}",
        "subject_update": "Cập nhật Yêu cầu #{id} - {township}",
        "status_updated": "Trạng Thái Đã Cập Nhật",
        "your_request_status": "Trạng thái yêu cầu của bạn đã được cập nhật",
        "new_status": "Trạng Thái Mới",
        "message_from_staff": "Tin nhắn từ nhân viên",
        "request_details": "Chi Tiết Yêu Cầu",
    },
}

# Cache for translated email strings: {(key, lang): translated_value}
_email_translation_cache: Dict[tuple, str] = {}


async def get_i18n_async(lang: str) -> Dict[str, str]:
    """
    Get i18n strings for a language.
    1. First checks static dictionary for pre-translated common languages
    2. Falls back to Google Translate API with caching for all other 130+ languages
    """
    # If we have static translations for this language, use them
    if lang in EMAIL_I18N:
        return EMAIL_I18N[lang]
    
    # English - use as-is
    if lang == "en":
        return EMAIL_I18N["en"]
    
    # For other languages, translate using Google Translate API with caching
    from app.services.translation import translate_text
    
    english_strings = EMAIL_I18N["en"]
    translated = {}
    
    for key, english_value in english_strings.items():
        cache_key = (key, lang)
        
        # Check cache first
        if cache_key in _email_translation_cache:
            translated[key] = _email_translation_cache[cache_key]
            continue
        
        # Translate via Google Translate API
        try:
            result = await translate_text(english_value, "en", lang)
            if result:
                translated[key] = result
                _email_translation_cache[cache_key] = result
            else:
                # Fallback to English if translation fails
                translated[key] = english_value
        except Exception:
            translated[key] = english_value
    
    return translated


def get_i18n(lang: str) -> Dict[str, str]:
    """
    Synchronous version - returns static translations only.
    For full translation support, use get_i18n_async().
    """
    return EMAIL_I18N.get(lang, EMAIL_I18N["en"])


def get_base_template(
    township_name: str,
    logo_url: Optional[str],
    primary_color: str = "#6366f1",
    content: str = "",
    footer_text: str = "",
    language: str = "en"
) -> str:
    """
    Base responsive email template with township branding.
    Uses inline CSS for maximum email client compatibility.
    """
    i18n = get_i18n(language)
    dir_attr = 'dir="rtl"' if language in ['ar', 'he', 'fa', 'ur', 'yi', 'ps'] else ''
    
    return f"""
<!DOCTYPE html>
<html lang="{language}" {dir_attr}>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{township_name} - 311 Service</title>
</head>
<body style="margin: 0; padding: 0; background-color: #f1f5f9; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">
    <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="background-color: #f1f5f9;">
        <tr>
            <td style="padding: 40px 20px;">
                <table role="presentation" cellpadding="0" cellspacing="0" width="600" style="margin: 0 auto; max-width: 600px;">
                    <!-- Header -->
                    <tr>
                        <td style="background: linear-gradient(135deg, {primary_color} 0%, #4338ca 100%); padding: 32px; border-radius: 16px 16px 0 0; text-align: center;">
                            {f'<img src="{logo_url}" alt="{township_name}" style="height: 48px; margin-bottom: 16px;">' if logo_url else ''}
                            <h1 style="margin: 0; color: white; font-size: 24px; font-weight: 600;">{township_name}</h1>
                            <p style="margin: 8px 0 0 0; color: rgba(255,255,255,0.8); font-size: 14px;">{i18n['service_portal']}</p>
                        </td>
                    </tr>
                    
                    <!-- Content -->
                    <tr>
                        <td style="background-color: white; padding: 32px; border-radius: 0 0 16px 16px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);">
                            {content}
                        </td>
                    </tr>
                    
                    <!-- Footer -->
                    <tr>
                        <td style="padding: 24px; text-align: center;">
                            <p style="margin: 0 0 8px 0; color: #64748b; font-size: 13px;">
                                {footer_text if footer_text else f"This is an automated message from {township_name} 311 Service."}
                            </p>
                            <p style="margin: 0; color: #94a3b8; font-size: 12px;">
                                {i18n['no_reply']}
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""


def build_confirmation_email(
    township_name: str,
    logo_url: Optional[str],
    primary_color: str,
    request_id: str,
    service_name: str,
    description: str,
    address: Optional[str],
    portal_url: str,
    language: str = "en"
) -> Dict[str, str]:
    """
    Build email for new request confirmation.
    Returns dict with 'subject', 'html', and 'text' keys.
    """
    tracking_url = f"{portal_url}/#track/{request_id}"
    i18n = get_i18n(language)
    
    content = f"""
        <div style="text-align: center; margin-bottom: 24px;">
            <div style="display: inline-block; background-color: #dcfce7; border-radius: 50%; width: 64px; height: 64px; line-height: 64px; margin-bottom: 16px;">
                <span style="font-size: 32px;">✓</span>
            </div>
            <h2 style="margin: 0 0 8px 0; color: #1e293b; font-size: 22px; font-weight: 600;">{i18n['request_received']}</h2>
            <p style="margin: 0; color: #64748b; font-size: 15px;">{i18n['report_submitted']}</p>
        </div>
        
        <div style="background-color: #f8fafc; border-radius: 12px; padding: 20px; margin-bottom: 24px;">
            <table role="presentation" cellpadding="0" cellspacing="0" width="100%">
                <tr>
                    <td style="padding: 8px 0; border-bottom: 1px solid #e2e8f0;">
                        <span style="color: #64748b; font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px;">{i18n['request_id']}</span>
                        <p style="margin: 4px 0 0 0; color: {primary_color}; font-size: 18px; font-weight: 600;">#{request_id}</p>
                    </td>
                </tr>
                <tr>
                    <td style="padding: 12px 0; border-bottom: 1px solid #e2e8f0;">
                        <span style="color: #64748b; font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px;">{i18n['category']}</span>
                        <p style="margin: 4px 0 0 0; color: #1e293b; font-size: 15px; font-weight: 500;">{service_name}</p>
                    </td>
                </tr>
                <tr>
                    <td style="padding: 12px 0;{' border-bottom: 1px solid #e2e8f0;' if address else ''}">
                        <span style="color: #64748b; font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px;">{i18n['description']}</span>
                        <p style="margin: 4px 0 0 0; color: #1e293b; font-size: 15px;">{description[:200]}{'...' if len(description) > 200 else ''}</p>
                    </td>
                </tr>
                {f'''
                <tr>
                    <td style="padding: 12px 0;">
                        <span style="color: #64748b; font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px;">{i18n['location']}</span>
                        <p style="margin: 4px 0 0 0; color: #1e293b; font-size: 15px;">{address}</p>
                    </td>
                </tr>
                ''' if address else ''}
            </table>
        </div>
        
        <div style="text-align: center;">
            <a href="{tracking_url}" style="display: inline-block; background-color: {primary_color}; color: white; text-decoration: none; padding: 14px 32px; border-radius: 8px; font-weight: 600; font-size: 15px;">{i18n['track_request']}</a>
            <p style="margin: 16px 0 0 0; color: #94a3b8; font-size: 13px;">
                {i18n['or_visit']}: <a href="{tracking_url}" style="color: {primary_color};">{tracking_url}</a>
            </p>
        </div>
    """
    
    html = get_base_template(
        township_name=township_name,
        logo_url=logo_url,
        primary_color=primary_color,
        content=content,
        footer_text=i18n['thank_you'].format(township=township_name),
        language=language
    )
    
    text = f"""
{i18n['request_received']}

{i18n['request_id']}: #{request_id}
{i18n['category']}: {service_name}
{i18n['description']}: {description[:200]}
{f"{i18n['location']}: {address}" if address else ""}

{i18n['track_request']}: {tracking_url}

{i18n['thank_you'].format(township=township_name)}
"""
    
    return {
        "subject": i18n['subject_received'].format(id=request_id, township=township_name),
        "html": html,
        "text": text.strip()
    }


async def build_confirmation_email_async(
    township_name: str,
    logo_url: Optional[str],
    primary_color: str,
    request_id: str,
    service_name: str,
    description: str,
    address: Optional[str],
    portal_url: str,
    language: str = "en"
) -> Dict[str, str]:
    """
    Async version - Build email for new request confirmation.
    Uses Google Translate API for any language not in the static dictionary.
    Results are cached to minimize API calls.
    """
    tracking_url = f"{portal_url}/#track/{request_id}"
    i18n = await get_i18n_async(language)
    
    content = f"""
        <div style="text-align: center; margin-bottom: 24px;">
            <div style="display: inline-block; background-color: #dcfce7; border-radius: 50%; width: 64px; height: 64px; line-height: 64px; margin-bottom: 16px;">
                <span style="font-size: 32px;">✓</span>
            </div>
            <h2 style="margin: 0 0 8px 0; color: #1e293b; font-size: 22px; font-weight: 600;">{i18n['request_received']}</h2>
            <p style="margin: 0; color: #64748b; font-size: 15px;">{i18n['report_submitted']}</p>
        </div>
        
        <div style="background-color: #f8fafc; border-radius: 12px; padding: 20px; margin-bottom: 24px;">
            <table role="presentation" cellpadding="0" cellspacing="0" width="100%">
                <tr>
                    <td style="padding: 8px 0; border-bottom: 1px solid #e2e8f0;">
                        <span style="color: #64748b; font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px;">{i18n['request_id']}</span>
                        <p style="margin: 4px 0 0 0; color: {primary_color}; font-size: 18px; font-weight: 600;">#{request_id}</p>
                    </td>
                </tr>
                <tr>
                    <td style="padding: 12px 0; border-bottom: 1px solid #e2e8f0;">
                        <span style="color: #64748b; font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px;">{i18n['category']}</span>
                        <p style="margin: 4px 0 0 0; color: #1e293b; font-size: 15px; font-weight: 500;">{service_name}</p>
                    </td>
                </tr>
                <tr>
                    <td style="padding: 12px 0;{' border-bottom: 1px solid #e2e8f0;' if address else ''}">
                        <span style="color: #64748b; font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px;">{i18n['description']}</span>
                        <p style="margin: 4px 0 0 0; color: #1e293b; font-size: 15px;">{description[:200]}{'...' if len(description) > 200 else ''}</p>
                    </td>
                </tr>
                {f'''
                <tr>
                    <td style="padding: 12px 0;">
                        <span style="color: #64748b; font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px;">{i18n['location']}</span>
                        <p style="margin: 4px 0 0 0; color: #1e293b; font-size: 15px;">{address}</p>
                    </td>
                </tr>
                ''' if address else ''}
            </table>
        </div>
        
        <div style="text-align: center;">
            <a href="{tracking_url}" style="display: inline-block; background-color: {primary_color}; color: white; text-decoration: none; padding: 14px 32px; border-radius: 8px; font-weight: 600; font-size: 15px;">{i18n['track_request']}</a>
            <p style="margin: 16px 0 0 0; color: #94a3b8; font-size: 13px;">
                {i18n['or_visit']}: <a href="{tracking_url}" style="color: {primary_color};">{tracking_url}</a>
            </p>
        </div>
    """
    
    html = get_base_template(
        township_name=township_name,
        logo_url=logo_url,
        primary_color=primary_color,
        content=content,
        footer_text=i18n['thank_you'].format(township=township_name),
        language=language
    )
    
    text = f"""
{i18n['request_received']}

{i18n['request_id']}: #{request_id}
{i18n['category']}: {service_name}
{i18n['description']}: {description[:200]}
{f"{i18n['location']}: {address}" if address else ""}

{i18n['track_request']}: {tracking_url}

{i18n['thank_you'].format(township=township_name)}
"""
    
    return {
        "subject": i18n['subject_received'].format(id=request_id, township=township_name),
        "html": html,
        "text": text.strip()
    }


def build_status_update_email(
    township_name: str,
    logo_url: Optional[str],
    primary_color: str,
    request_id: str,
    service_name: str,
    old_status: str,
    new_status: str,
    completion_message: Optional[str],
    completion_photo_url: Optional[str],
    portal_url: str
) -> Dict[str, str]:
    """
    Build email for status update notification.
    Includes completion photo if provided (for closed requests).
    """
    tracking_url = f"{portal_url}/#track/{request_id}"
    
    status_configs = {
        "open": {"label": "Open", "color": "#f59e0b", "bg": "#fef3c7", "icon": "circle"},
        "in_progress": {"label": "In Progress", "color": "#3b82f6", "bg": "#dbeafe", "icon": "clock"},
        "closed": {"label": "Resolved", "color": "#16a34a", "bg": "#dcfce7", "icon": "check-circle"}
    }
    
    status_config = status_configs.get(new_status, {"label": new_status.replace("_", " ").title(), "color": "#64748b", "bg": "#f1f5f9", "icon": "circle"})
    
    # Build completion photo section if available
    completion_photo_section = ""
    if completion_photo_url and new_status == "closed":
        # Convert relative URLs to absolute for email compatibility
        if completion_photo_url.startswith('/'):
            # Remove trailing slash from portal_url if present and prepend
            base_url = portal_url.rstrip('/')
            photo_full_url = f"{base_url}{completion_photo_url}"
        else:
            photo_full_url = completion_photo_url
            
        completion_photo_section = f'''
        <div style="margin-bottom: 24px; text-align: center;">
            <p style="margin: 0 0 12px 0; color: #166534; font-size: 13px; font-weight: 600;">Completion Photo</p>
            <img src="{photo_full_url}" alt="Completion photo" style="max-width: 100%; height: auto; border-radius: 12px; border: 2px solid #dcfce7; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);">
        </div>
        '''
    
    content = f"""
        <div style="text-align: center; margin-bottom: 24px;">
            <h2 style="margin: 0 0 8px 0; color: #1e293b; font-size: 22px; font-weight: 600;">Status Update</h2>
            <p style="margin: 0; color: #64748b; font-size: 15px;">Request #{request_id}</p>
        </div>
        
        <div style="background-color: {status_config['bg']}; border-radius: 12px; padding: 24px; margin-bottom: 24px; text-align: center;">
            <p style="margin: 0 0 8px 0; color: {status_config['color']}; font-size: 13px; text-transform: uppercase; letter-spacing: 1px; font-weight: 600;">Current Status</p>
            <p style="margin: 0; color: {status_config['color']}; font-size: 24px; font-weight: 700;">{status_config['label']}</p>
        </div>
        
        <div style="background-color: #f8fafc; border-radius: 12px; padding: 20px; margin-bottom: 24px;">
            <table role="presentation" cellpadding="0" cellspacing="0" width="100%">
                <tr>
                    <td style="padding: 8px 0;">
                        <span style="color: #64748b; font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px;">Category</span>
                        <p style="margin: 4px 0 0 0; color: #1e293b; font-size: 15px; font-weight: 500;">{service_name}</p>
                    </td>
                </tr>
            </table>
        </div>
        
        {f'''
        <div style="background-color: #f0fdf4; border-left: 4px solid #16a34a; border-radius: 0 8px 8px 0; padding: 16px; margin-bottom: 24px;">
            <p style="margin: 0 0 4px 0; color: #166534; font-size: 13px; font-weight: 600;">Resolution Notes</p>
            <p style="margin: 0; color: #15803d; font-size: 15px;">{completion_message}</p>
        </div>
        ''' if completion_message and new_status == 'closed' else ''}
        
        {completion_photo_section}
        
        <div style="text-align: center;">
            <a href="{tracking_url}" style="display: inline-block; background-color: {primary_color}; color: white; text-decoration: none; padding: 14px 32px; border-radius: 8px; font-weight: 600; font-size: 15px;">View Request Details</a>
        </div>
    """
    
    html = get_base_template(
        township_name=township_name,
        logo_url=logo_url,
        primary_color=primary_color,
        content=content
    )
    
    text = f"""
Status Update for Request #{request_id}

Your request status has been updated to: {status_config['label']}

Category: {service_name}
{f"Resolution Notes: {completion_message}" if completion_message and new_status == 'closed' else ""}
{f"Completion Photo: {completion_photo_url}" if completion_photo_url and new_status == 'closed' else ""}

View details at: {tracking_url}
"""
    
    return {
        "subject": f"Request #{request_id} Status: {status_config['label']} - {township_name}",
        "html": html,
        "text": text.strip()
    }


def build_comment_email(
    township_name: str,
    logo_url: Optional[str],
    primary_color: str,
    request_id: str,
    service_name: str,
    comment_author: str,
    comment_content: str,
    portal_url: str
) -> Dict[str, str]:
    """
    Build email for new public comment notification.
    Uses table-based layout for email client compatibility.
    """
    tracking_url = f"{portal_url}/#track/{request_id}"
    author_initial = comment_author[0].upper() if comment_author else "S"
    
    content = f"""
        <div style="text-align: center; margin-bottom: 24px;">
            <div style="display: inline-block; background-color: #dbeafe; border-radius: 50%; width: 56px; height: 56px; line-height: 56px; margin-bottom: 16px;">
                <span style="color: #3b82f6; font-size: 24px;">💬</span>
            </div>
            <h2 style="margin: 0 0 8px 0; color: #1e293b; font-size: 22px; font-weight: 600;">New Update on Your Request</h2>
            <p style="margin: 0; color: {primary_color}; font-size: 15px; font-weight: 500;">Request #{request_id} • {service_name}</p>
        </div>
        
        <div style="background-color: #f8fafc; border-radius: 12px; padding: 24px; margin-bottom: 24px;">
            <table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="margin-bottom: 16px;">
                <tr>
                    <td width="48" valign="top" style="padding-right: 12px;">
                        <div style="background-color: {primary_color}; color: white; width: 44px; height: 44px; border-radius: 50%; text-align: center; line-height: 44px; font-weight: 600; font-size: 18px;">
                            {author_initial}
                        </div>
                    </td>
                    <td valign="middle">
                        <p style="margin: 0 0 2px 0; color: #1e293b; font-size: 16px; font-weight: 600;">{comment_author}</p>
                        <p style="margin: 0; color: {primary_color}; font-size: 13px; font-weight: 500;">Staff Member</p>
                    </td>
                </tr>
            </table>
            
            <div style="background-color: white; border-radius: 8px; padding: 16px; border-left: 4px solid {primary_color};">
                <p style="margin: 0; color: #1e293b; font-size: 15px; line-height: 1.7;">"{comment_content}"</p>
            </div>
        </div>
        
        <div style="text-align: center;">
            <a href="{tracking_url}" style="display: inline-block; background-color: {primary_color}; color: white; text-decoration: none; padding: 14px 32px; border-radius: 8px; font-weight: 600; font-size: 15px;">View Full Conversation</a>
            <p style="margin: 16px 0 0 0; color: #94a3b8; font-size: 13px;">
                or visit: <a href="{tracking_url}" style="color: {primary_color};">{tracking_url}</a>
            </p>
        </div>
    """
    
    html = get_base_template(
        township_name=township_name,
        logo_url=logo_url,
        primary_color=primary_color,
        content=content,
        footer_text=f"You're receiving this because you submitted a request to {township_name}."
    )
    
    text = f"""
New Update on Your Request #{request_id}

{comment_author} (Staff) wrote:

"{comment_content}"

View the full conversation at: {tracking_url}
"""
    
    return {
        "subject": f"New Update on Request #{request_id} - {township_name}",
        "html": html,
        "text": text.strip()
    }


def build_sms_confirmation(request_id: str, township_name: str, portal_url: str = "", service_name: str = "", description: str = "", address: str = "") -> str:
    """Build SMS message for request confirmation."""
    tracking_link = f"{portal_url}/#track/{request_id}" if portal_url else ""
    
    # Truncate description for SMS
    short_desc = description[:60] + "..." if len(description) > 60 else description
    
    message = f"""✅ {township_name} 311
Your request has been received!

📋 {service_name}"""
    
    if short_desc:
        message += f"\n\"{short_desc}\""
    
    if address:
        message += f"\n📍 {address}"
    
    message += f"\n\n🔖 Ref: {request_id}"
    
    if tracking_link:
        message += f"\n🔗 Track: {tracking_link}"
    
    return message


def build_sms_status_update(request_id: str, new_status: str, township_name: str, portal_url: str = "", completion_message: str = "", service_name: str = "") -> str:
    """Build SMS message for status update."""
    status_emoji = {
        "open": "📋",
        "in_progress": "🔧", 
        "closed": "✅"
    }.get(new_status, "📋")
    
    status_text = {
        "open": "is being reviewed",
        "in_progress": "is being worked on",
        "closed": "has been resolved"
    }.get(new_status, f"status: {new_status}")
    
    tracking_link = f"{portal_url}/#track/{request_id}" if portal_url else ""
    
    message = f"""{status_emoji} {township_name} 311
Your request {status_text}!"""
    
    if service_name:
        message += f"\n\n📋 {service_name}"
    
    if new_status == "closed" and completion_message:
        # Truncate long completion messages for SMS
        short_msg = completion_message[:80] + "..." if len(completion_message) > 80 else completion_message
        message += f"\n💬 {short_msg}"
    
    message += f"\n\n🔖 Ref: {request_id}"
    
    if tracking_link:
        message += f"\n🔗 Details: {tracking_link}"
    
    return message
