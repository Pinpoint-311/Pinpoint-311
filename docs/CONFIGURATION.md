# Configuration

Settings live in two places:

- **`.env`**, read by Docker Compose: values that must exist before the app can start, or that every town on the same build shares.
- **The Admin Console**, stored in the database or the chosen secret store: everything a town administrator manages.

- [Environment variables](#environment-variables)
- [Backend-only variables](#backend-only-variables)
- [Admin Console](#admin-console)
- [Optional services and their providers](#optional-services-and-their-providers)
- [Translation budget](#translation-budget)
- [Photo redaction](#photo-redaction)
- [Open311 API keys](#open311-api-keys)
- [Cloud resource templates](#cloud-resource-templates)

## Environment variables

The minimum for a first start is `DB_PASSWORD`, `SECRET_KEY` and
`INITIAL_ADMIN_PASSWORD`; Compose refuses to start without them.

| Variable | Used by | Purpose |
| --- | --- | --- |
| `DB_USER`, `DB_PASSWORD`, `DB_NAME` | db, backend, worker | Database credentials. Defaults: `township`, none, `township_db`. |
| `SECRET_KEY` | backend, worker | Session signing and local key derivation. At least 32 random characters (`openssl rand -hex 32`). The backend refuses to boot with a known default or a short key. |
| `INITIAL_ADMIN_USER`, `INITIAL_ADMIN_EMAIL`, `INITIAL_ADMIN_PASSWORD` | backend | First-run admin account and bootstrap password. The default `admin123` is rejected. |
| `DOMAIN` | backend, caddy | Public hostname, for example `311.example.gov`. Defaults to `localhost`. |
| `TENANT_CADDY_PATH` | backend, caddy | Host directory for Caddy site snippets written when an administrator sets a custom domain, for example `./caddy-tenants`. Set it explicitly; the compose default points at a path used by the project's own hosting. |
| `BACKEND_IMAGE`, `FRONTEND_IMAGE` | compose | The images to run. Normally set by `release.lock` (see [RELEASES.md](RELEASES.md)). Default: the locally built `pinpoint-311-*:latest`. |
| `REDACTION_MODELS_DIR` | backend, worker | Host directory holding the photo-redaction model files, mounted read-only at `/models`. Default `./models`. See [PHOTO_REDACTION_MODELS.md](PHOTO_REDACTION_MODELS.md). |
| `ADMIN_EMAIL` | caddy | Passed to the Caddy container. The shipped Caddyfile does not reference it. |
| `RATE_LIMIT_DEFAULT` | backend | Per-client default rate limit. Default `500/minute`. |
| `GOOGLE_MAPS_API_KEY`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_VERTEX_PROJECT`, `GOOGLE_VERTEX_LOCATION` | backend, worker | Optional Google defaults. The same settings can be entered in the console. |
| `ACCELA_CLIENT_ID`, `ACCELA_CLIENT_SECRET`, `ACCELA_REDIRECT_URI` | backend, worker | Optional Accela developer-app credentials for OAuth sign-in. Without them, the Accela wizard asks for an agency username and password. See [INTEGRATIONS.md](INTEGRATIONS.md). |
| `CONTACT_FORM_URL`, `CONTACT_FORM_EMBED` | backend | Optional deployment-registration form offered in the console. See the comments in `.env.example`. |
| `DB_PORT`, `REDIS_PORT`, `BACKEND_PORT`, `FRONTEND_PORT` | compose | Host ports. All four are bound to `127.0.0.1`. |
| `HTTP_PORT`, `HTTPS_PORT` | caddy | Public ports. Defaults 80 and 443. |

> [!IMPORTANT]
> `SECRET_KEY` signs staff sessions and derives the local encryption key. Do not
> change it casually after launch, and keep a copy somewhere other than the server.

## Backend-only variables

The backend also honors a few variables that the default compose file does not
pass through. To use them, add them to the `environment:` of the `backend` and
`worker` services in a `docker-compose.override.yml`.

| Variable | Purpose |
| --- | --- |
| `DEBUG=true` | Serves interactive API docs at `/api/docs` and `/api/redoc` and disables the strict `SECRET_KEY` check. Development only. |
| `SENTRY_DSN` | Crash-reporting DSN. Overrides the DSN saved in the console. |
| `SECRETS_PROVIDER` | Forces the secret store (`database`, `google`, `azure`, `aws`) instead of the console choice. |
| `KMS_PROVIDER` | Forces the PII key manager instead of the console choice. |
| `REQUIRE_KMS` | When true, the app refuses to write resident PII unless a cloud KMS wraps the key, instead of falling back to the local key. |
| `UPGRADE_LEASE_MINUTES`, `UPGRADE_RESTART_LEASE_MINUTES` | How long a console upgrade (default 45) or restart (default 10) may go without a report from the host updater before it is marked failed. See [RELEASES.md](RELEASES.md#connecting-the-host-updater). |
| `PINPOINT_ALLOW_DESTRUCTIVE_MIGRATION=1` | Lets the startup migrator apply a destructive migration. See [OPERATIONS.md](OPERATIONS.md#database-migrations). |

## Admin Console

Administrators enter everything else in the browser: branding, users,
departments, categories, routing, retention, feature modules, and every provider
credential. What each section holds is listed in
[FEATURES.md](FEATURES.md#admin-console).

Credentials go to the chosen secret store. With an external store (Google,
Azure, AWS), the database keeps only a reference, and a scheduled task moves any
credential saved before the store was chosen into it. The Setup & Integration
page accepts no credentials until a store is chosen.

The selected AI provider is used everywhere AI appears: request triage, photo
assessment, the staff Analytics Advisor, and the Research Lab's Data Assistant.

## Optional services and their providers

Every optional service can stay off. Each card on the Setup & Integration page
has a **Save & Test** button where a live check exists.

| Capability | Providers |
| --- | --- |
| Secret storage | Encrypted database, Google Secret Manager, Azure Key Vault, AWS Secrets Manager |
| PII encryption key | Google Cloud KMS, Azure Key Vault, AWS KMS, or an application key derived from `SECRET_KEY` |
| AI (triage, Analytics Advisor, Data Assistant) | Google Vertex AI, Azure OpenAI, AWS Bedrock. The model list is refreshed from the provider. |
| Translation | Google Cloud Translation, Azure AI Translator, Amazon Translate |
| Email | SMTP, Amazon SES, Azure Communication Services |
| Text messages | Twilio, Amazon SNS, Azure Communication Services, a generic HTTP gateway, or off |
| Photo screening and face detection | Google Cloud Vision, AWS Rekognition, Azure AI, or local (OpenCV, offline) |
| Plate detection and face fallback | On the server: YOLOv9 plate model and YuNet face model (ONNX), downloaded by the town |
| Content moderation | Google, Azure, or AWS moderation services, defaulting to the AI provider's cloud. A local profanity check always runs. |
| Staff sign-in | Auth0, Microsoft Entra ID, Okta, generic OIDC |
| Maps and geocoding | Google Maps, Esri ArcGIS (Online or Enterprise), Azure Maps, Apple Maps |
| Backups | Any S3-compatible object store (AWS S3, Backblaze B2, Oracle Object Storage, and others) |
| Crash reporting | Sentry |

## Translation budget

Translation is the one optional service a resident can spend money on without
signing in, so it has a hard ceiling. Every call that sends characters to the
provider reserves them first against a daily and a monthly character budget
(`TRANSLATION_BUDGET_DAILY_CHARS`, default 500,000; `TRANSLATION_BUDGET_MONTHLY_CHARS`,
default 5,000,000), set on the translation card. Over the budget, residents and
notifications get the original text instead of an error. Cached translations
cost nothing and do not count. The health scan warns at 80% and raises a
critical alert at 100%. Source: `backend/app/services/translation_budget.py`.

## Photo redaction

The **Photo Redaction** card chooses the face provider and, under
**On-server detectors**, the plate detector (`PLATE_DETECTOR`: `yolo`, `ocr`,
`off`) and face fallback (`FACE_FALLBACK`: `yunet`, `opencv`, `off`). It also
shows whether each model file is installed. Install steps and the model
licenses: [PHOTO_REDACTION_MODELS.md](PHOTO_REDACTION_MODELS.md).

## Open311 API keys

Setup & Integration > **Open311 API keys** issues a key per integrator (name and
contact email, optional per-minute limit). The key is shown once; the instance
stores only its SHA-256 hash. Keys can be revoked, and both actions are audited.
Details: [API.md](API.md#api-keys).

## Cloud resource templates

`deploy/templates/` contains an Azure ARM template and an AWS CloudFormation
template that create the cloud resources a town needs (see
[deploy/templates/README.md](../deploy/templates/README.md)). For Google, the
setup page has a guided manual path instead.
