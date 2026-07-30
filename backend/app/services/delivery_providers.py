"""Email, text messaging and PII encryption as pluggable capabilities.

All three were already switchable and none of them was visible. `EMAIL_PROVIDER`
picks between SMTP, Amazon SES and Azure Communication Services;
`SMS_PROVIDER` picks between Twilio, a generic HTTP gateway, Amazon SNS and ACS;
`KMS_PROVIDER` picks which key service wraps the PII encryption key. Every one
of those branches exists and runs -- see `configure_notifications` in
tasks/service_requests.py and `pii_crypto.wrap/unwrap` -- but there was no
catalog for any of them, so the admin UI had a hand-written SMTP-and-Twilio card
and no way at all to reach the other five providers or to choose a KMS.

The lists here are deliberately confined to what the dispatch code actually
implements. Offering a provider the backend cannot route to is the failure this
codebase has produced repeatedly: a setting that stores fine, reads back fine,
and silently does nothing. Each entry below was checked against its branch.

Credentials resolve through the Secret Manager of record like every other
capability; this module only says which are needed.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

EMAIL_PROVIDER_KEY = "EMAIL_PROVIDER"
SMS_PROVIDER_KEY = "SMS_PROVIDER"
KMS_PROVIDER_KEY = "KMS_PROVIDER"

DEFAULT_EMAIL_PROVIDER = "smtp"
DEFAULT_SMS_PROVIDER = "none"
DEFAULT_KMS_PROVIDER = "google"


# ---- email -------------------------------------------------------------------
# Branches: tasks/service_requests.py configure_notifications, provider_type
# "ses" | "acs" | "smtp".

EMAIL_CATALOG: Dict[str, Dict[str, Any]] = {
    "smtp": {
        "name": "SMTP",
        "description": (
            "Any mail server, including the one your town already has. Works with "
            "Microsoft 365 and Google Workspace using an app password."
        ),
        "boundary": "Wherever your mail server already is",
        "credential_fields": [
            {"key": "SMTP_HOST", "label": "SMTP host", "required": True},
            {"key": "SMTP_PORT", "label": "Port (optional, defaults to 587)", "required": False},
            {"key": "SMTP_USER", "label": "Username", "required": True},
            {"key": "SMTP_PASSWORD", "label": "Password", "secret": True, "required": True},
            {"key": "SMTP_FROM_EMAIL", "label": "From address", "required": True},
            {"key": "SMTP_FROM_NAME", "label": "From name (optional)", "required": False},
        ],
        "field_help": {
            "SMTP_PASSWORD": "For Microsoft 365 or Google Workspace this is an app password, not the account password.",
            "SMTP_FROM_EMAIL": "Residents reply to this address, so use one somebody reads.",
        },
    },
    "ses": {
        "name": "Amazon SES",
        "description": "Amazon's mail service. Uses the same AWS credentials as the rest of your AWS setup.",
        "boundary": "AWS — GovCloud available",
        "credential_fields": [
            {"key": "AWS_REGION", "label": "AWS Region", "required": True},
            {"key": "SES_FROM_EMAIL", "label": "Verified from address", "required": True},
            {"key": "SMTP_FROM_NAME", "label": "From name (optional)", "required": False},
            {"key": "AWS_ACCESS_KEY_ID", "label": "Access Key ID (optional with an instance role)", "required": False},
            {"key": "AWS_SECRET_ACCESS_KEY", "label": "Secret Access Key (optional with an instance role)", "secret": True, "required": False},
        ],
        "field_help": {
            "SES_FROM_EMAIL": "SES will not send from an address or domain you have not verified in the console first.",
        },
    },
    "acs": {
        "name": "Azure Communication Services",
        "description": "Microsoft's mail service. The natural choice if the rest of your town runs on Azure.",
        "boundary": "Azure — Government available",
        "credential_fields": [
            {"key": "ACS_ENDPOINT", "label": "ACS endpoint", "required": True},
            {"key": "ACS_ACCESS_KEY", "label": "Access key", "secret": True, "required": True},
            {"key": "ACS_FROM_EMAIL", "label": "From address", "required": True},
            {"key": "SMTP_FROM_NAME", "label": "From name (optional)", "required": False},
        ],
    },
}


# ---- text messages -----------------------------------------------------------
# Branches: "twilio" | "http" | "sns" | "acs". Anything else disables SMS, which
# is why "none" is a first-class entry rather than an empty string a clerk has
# to guess at.

SMS_CATALOG: Dict[str, Dict[str, Any]] = {
    "none": {
        "name": "Off",
        "description": "No text messages. Residents still get email updates if email is set up.",
        "boundary": "—",
        "credential_fields": [],
    },
    "twilio": {
        "name": "Twilio",
        "description": "The most common choice, and the quickest to set up from nothing.",
        "boundary": "Twilio (commercial)",
        "credential_fields": [
            {"key": "TWILIO_ACCOUNT_SID", "label": "Account SID", "required": True},
            {"key": "TWILIO_AUTH_TOKEN", "label": "Auth token", "secret": True, "required": True},
            {"key": "TWILIO_PHONE_NUMBER", "label": "From number", "required": True},
        ],
        "field_help": {
            "TWILIO_PHONE_NUMBER": "In +1XXXXXXXXXX form. It must be a number you own in Twilio.",
        },
    },
    "sns": {
        "name": "Amazon SNS",
        "description": "Amazon's messaging service, using the same AWS credentials as the rest of your AWS setup.",
        "boundary": "AWS — GovCloud available",
        "credential_fields": [
            {"key": "AWS_REGION", "label": "AWS Region", "required": True},
            {"key": "AWS_ACCESS_KEY_ID", "label": "Access Key ID (optional with an instance role)", "required": False},
            {"key": "AWS_SECRET_ACCESS_KEY", "label": "Secret Access Key (optional with an instance role)", "secret": True, "required": False},
            {"key": "SMS_SENDER_ID", "label": "Sender ID (optional)", "required": False},
        ],
    },
    "acs": {
        "name": "Azure Communication Services",
        "description": "Microsoft's messaging service, sharing the ACS resource with email if you use both.",
        "boundary": "Azure — Government available",
        "credential_fields": [
            {"key": "ACS_ENDPOINT", "label": "ACS endpoint", "required": True},
            {"key": "ACS_ACCESS_KEY", "label": "Access key", "secret": True, "required": True},
            {"key": "SMS_FROM_NUMBER", "label": "From number", "required": True},
        ],
    },
    "http": {
        "name": "Other gateway (HTTP)",
        "description": (
            "Any gateway that accepts an HTTP POST. Configure it yourself — this is a generic "
            "client, not certified against a particular vendor, so run a test send before relying on it."
        ),
        "boundary": "Wherever your gateway is",
        "credential_fields": [
            {"key": "SMS_HTTP_API_URL", "label": "POST URL", "required": True},
            {"key": "SMS_HTTP_API_KEY", "label": "API key", "secret": True, "required": False},
        ],
    },
}


# ---- PII encryption ----------------------------------------------------------
# Branches: pii_crypto wrap/unwrap handle "azure", "aws" and "google". Anything
# else falls back to the application SECRET_KEY, which is a real and supported
# state for a town with no cloud KMS -- so it is listed honestly rather than
# hidden.

KMS_CATALOG: Dict[str, Dict[str, Any]] = {
    "google": {
        "name": "Google Cloud KMS",
        "description": "Wraps the key that encrypts resident personal information. Uses your existing Google Cloud service account.",
        "boundary": "Google Cloud — Assured Workloads / FedRAMP High",
        "credential_fields": [
            {"key": "KMS_LOCATION", "label": "Key location (optional, defaults to us-central1)", "required": False},
            {"key": "KMS_KEY_RING", "label": "Key ring (optional, defaults to pinpoint311-keyring)", "required": False},
            {"key": "KMS_KEY_ID", "label": "Key name (optional, defaults to pii-encryption-key)", "required": False},
        ],
        "field_help": {
            "KMS_LOCATION": "The project comes from your Google Cloud credentials; these three only name the key within it.",
        },
    },
    "azure": {
        "name": "Azure Key Vault",
        "description": "Wraps the PII encryption key in Key Vault. The natural choice for an Azure town.",
        "boundary": "Azure Government / GCC High",
        "credential_fields": [
            {"key": "AZURE_KEYVAULT_URL", "label": "Key Vault URL", "required": True},
            {"key": "AZURE_KEYVAULT_KEY", "label": "Key name", "required": True},
            {"key": "AZURE_TENANT_ID", "label": "Directory (tenant) ID", "required": True},
            {"key": "AZURE_KEYVAULT_CLIENT_ID", "label": "Application (client) ID", "required": True},
            {"key": "AZURE_KEYVAULT_CLIENT_SECRET", "label": "Client secret", "secret": True, "required": True},
        ],
    },
    "aws": {
        "name": "AWS KMS",
        "description": "Wraps the PII encryption key in AWS KMS, using your existing AWS credentials.",
        "boundary": "AWS — GovCloud available",
        "credential_fields": [
            {"key": "AWS_REGION", "label": "AWS Region", "required": True},
            {"key": "AWS_KMS_KEY_ID", "label": "Key ID or ARN", "required": True},
        ],
    },
    "local": {
        "name": "Application key (no cloud KMS)",
        "description": (
            "Personal information is still encrypted, using the application's own SECRET_KEY "
            "rather than a cloud key service. Workable for a small town, but the key lives with "
            "the app, so a cloud KMS is the stronger choice where one is available."
        ),
        "boundary": "Self-hosted",
        "credential_fields": [],
    },
}


# ---- photo redaction ---------------------------------------------------------
# Branches: image_redaction.PROVIDERS = ("google", "aws", "azure", "local").
# It reuses the cloud credentials already entered for AI, so the only settings
# here are which detector to use and what to blur.
#
# The two toggles are stored as strings because that is what the shared save
# endpoint writes and what image_redaction._flag parses ("1/true/yes/on/enabled").

REDACTION_PROVIDER_KEY = "REDACTION_PROVIDER"
DEFAULT_REDACTION_PROVIDER = "google"

_REDACTION_TOGGLES = [
    {"key": "REDACT_FACES", "label": "Blur faces (true/false)", "required": False},
    {"key": "REDACT_PLATES", "label": "Blur licence plates (true/false)", "required": False},
]

REDACTION_CATALOG: Dict[str, Dict[str, Any]] = {
    "google": {
        "name": "Google Cloud Vision",
        "description": "Finds faces and plates in resident photos and blurs them before the photo is stored. Uses your existing Google Cloud credentials.",
        "boundary": "Google Cloud — Assured Workloads / FedRAMP High",
        "credential_fields": list(_REDACTION_TOGGLES),
        "field_help": {
            "REDACT_PLATES": "On by default. Detection guesses, so it occasionally blurs a house number — switch it off if your crews rely on those.",
        },
    },
    "aws": {
        "name": "Amazon Rekognition",
        "description": "Amazon's detector, using the AWS credentials already entered elsewhere.",
        "boundary": "AWS — GovCloud available",
        "credential_fields": list(_REDACTION_TOGGLES),
    },
    "azure": {
        "name": "Azure AI Vision",
        "description": "Microsoft's detector, using your Azure credentials.",
        "boundary": "Azure — Government available",
        "credential_fields": list(_REDACTION_TOGGLES),
    },
    "local": {
        "name": "On this server (no cloud)",
        "description": (
            "Detection runs on your own server with OpenCV and Tesseract — no photo leaves the "
            "building. Less accurate than the cloud detectors, and the only option that costs nothing "
            "per photo."
        ),
        "boundary": "Self-hosted",
        "credential_fields": list(_REDACTION_TOGGLES),
    },
}


_CATALOGS = {
    "email": EMAIL_CATALOG,
    "sms": SMS_CATALOG,
    "kms": KMS_CATALOG,
    "redaction": REDACTION_CATALOG,
}
_DEFAULTS = {
    "email": DEFAULT_EMAIL_PROVIDER,
    "sms": DEFAULT_SMS_PROVIDER,
    "kms": DEFAULT_KMS_PROVIDER,
    "redaction": DEFAULT_REDACTION_PROVIDER,
}


def catalog_for_api(capability: str) -> List[Dict[str, Any]]:
    """Provider list in the shape the shared Service Providers UI expects."""
    return [
        {
            "provider": provider_id,
            "name": spec["name"],
            "description": spec["description"],
            "boundary": spec.get("boundary", ""),
            "credential_fields": spec["credential_fields"],
            "field_help": spec.get("field_help", {}),
        }
        for provider_id, spec in _CATALOGS[capability].items()
    ]


def normalize_provider(capability: str, value: Optional[str]) -> str:
    """An unknown or missing provider falls back to that capability's default.

    SMS is the one that matters here: the dispatch code treats any unrecognised
    value as "off", so an empty string and a typo mean the same thing, and the
    UI should say so rather than showing a blank selection.
    """
    candidate = (value or "").strip().lower()
    if candidate in _CATALOGS[capability]:
        return candidate
    return _DEFAULTS[capability]
