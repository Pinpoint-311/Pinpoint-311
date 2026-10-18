# Features

What each part of Pinpoint 311 does. The [README](../README.md) has the short
version and the diagrams; settings are in [CONFIGURATION.md](CONFIGURATION.md).

- [Resident portal](#resident-portal)
- [Photo and content safety](#photo-and-content-safety)
- [Staff dashboard](#staff-dashboard)
- [Admin Console](#admin-console)
- [Map layers](#map-layers)
- [Open311 API](#open311-api)
- [Research Lab](#research-lab)
- [Records and retention](#records-and-retention)

## Resident portal

Served at `/`.

- **Report without an account.** Pick a category, drop a map pin or type an address, describe the problem, and attach up to three photos.
- **Track a report** through a private link. Residents who give an email address or phone number also get email and text updates.
- **Public map and list** of community reports, with personal details removed. When the Unlisted Reports module is on, residents can keep their own report off the public map. Unlisted reports, reports in a hidden category, and archived reports (archived by staff, or aged out by the town's public archival setting) are left out of the public map, the public list and Open311 `GET requests`. All of them still open from their tracking link.
- **More than 100 languages.** The interface, categories, and resident-submitted text are translated through the configured translation provider, within the town's daily and monthly translation budget. Over the budget, residents see the original text instead of an error.
- **Emergency notices.** A one-time non-emergency notice and a persistent "call 911 for emergencies" banner. Each acknowledgment is recorded.
- **Legal pages.** Editable Privacy Policy, Terms of Service, and Accessibility Statement at `/privacy`, `/terms`, and `/accessibility`.

## Photo and content safety

- **Text.** Explicit or abusive descriptions are refused before the report is saved (a local profanity check plus the cloud text moderator when configured). Milder language goes through and the report is flagged for staff.
- **Photos.** Explicit images are refused. Faces and license plates are blurred and EXIF metadata (including GPS) is stripped before the photo is stored; no unblurred original is kept.
  - Faces come from the town's cloud provider (Google Cloud Vision, AWS Rekognition or Azure AI). If it cannot answer, the YuNet face model on the server takes over (or the older OpenCV Haar cascades). If neither can check the photo, it is withheld.
  - Plates come from a YOLOv9 plate model that runs inside the backend (ONNX). The older text-based heuristic is still available.
  - A photo that cannot be checked or blurred is **withheld for staff review**, never published. Staff release or discard it from the held-photo queue.
  - The model files are downloaded by each town; Pinpoint does not bundle them. Install steps, measurements and the open license question about the plate model's weights: [PHOTO_REDACTION_MODELS.md](PHOTO_REDACTION_MODELS.md).

> [!NOTE]
> Face and plate detection is a mitigation, not a guarantee.

## Staff dashboard

Served at `/staff`.

- **One queue** with list, map, and detail views, and filters by status, priority, department, category, and date. Non-admin staff see reports routed to their departments, reports assigned to them, and unrouted reports that still need triage.
- **Working a report.** Internal notes, public comments, assignment, and status: open, in progress, or closed as resolved (optionally with a completion photo), no action needed, or referred to a third party. Status changes notify the resident and are mirrored to connected town systems.
- **Priority is one number from 1 to 10.** When AI is on, it suggests a priority. Staff accept or change it, and every change is recorded in the audit log.
- **Triage panel.** Nearby similar reports, proximity to schools, hospitals, and other critical sites, current weather, asset history, and the parcel or zone the report falls in, all computed from your own data without AI. When AI is on, it adds a plain-language summary, a suggested priority, and safety flags. AI never routes, assigns, or closes a report.
- **Manual intake.** Log a report taken by phone, email, in person, or another channel. It runs through the same routing, notifications, triage, and connector pushes as a resident submission, and the channel is recorded. Blank optional fields stay blank; no placeholder contact details are invented.
- **Resident history (optional module).** Shows a resident's other reports and searches by full email address or full name. Matching uses keyed fingerprints, so encrypted contact fields are never decrypted to search. Results are limited to reports the staff member could already open and show only ID, category, status, and date. Every lookup is audited; if the audit record cannot be written, no results are returned.
- **Analytics Advisor.** A chat assistant that answers questions about the town's request data. It runs on the configured AI provider and sees aggregated data only, never resident contact details.
- **Printable work orders** with a QR code, map, location context, and dispatch notes.
- **Held-photo review queue** for photos withheld by screening.

## Admin Console

Served at `/admin`. Three groups, plus **Version Control** in the sidebar.

| Group | Sections | What is configured there |
| --- | --- | --- |
| Branding & Setup | Branding, Setup & Integration | Town name, colors, logo, legal pages; secret store, AI, translation and its budget, email, text messaging, PII encryption, photo redaction and on-server detectors, staff sign-in, maps, backups, crash reporting, Open311 API keys, and connections to town systems |
| Organization | Users, Departments, Service Categories | Staff accounts and roles; departments and routing emails; categories, routing rules, custom questions, icons, location mode, public visibility |
| System & Compliance | System Settings, System Health, Compliance | Feature modules, maps, municipal boundary, map layers, public archival; health checks and alert muting; records retention, legal holds, recoverable deletions, database backups, audit log and its integrity check |

**Version Control** shows the running release (with image digests), the signed
releases the host updater has verified, and the upgrade, rollback and restart
requests with their live step list. See [OPERATIONS.md](OPERATIONS.md#upgrades).

### Per-category settings

- **Routing.** Handled by the municipality (routed to a department), third-party only (residents see the outside agency's contact details instead of a form), or road-based (routed by which jurisdiction maintains the road at the pin). Road rules are enforced on the server for every intake path.
- **Location mode.** *Required* (a pin or address is needed to submit), *Optional* (the map is shown and can be skipped; the default), or *Not collected* (no map on the form, and any location sent anyway is discarded). The same rule applies to the resident form, the Open311 API, staff manual intake, and inbound connectors.
- **Hide from public view.** Keeps every report in the category off the public map and list. Staff still see them.
- **Icons.** One shared set of about 110 municipal icons, grouped by topic. The picker is searchable and suggests an icon from the category name.
- **Custom questions.** Extra fields per category, for example "Is the dog aggressive?". They are published as Open311 service-definition attributes.

### Feature modules

Switched on in System Settings: Research Portal, Unlisted Reports, Platform
Feedback (one anonymous ease-of-use question), and Resident History.

## Map layers

- **Point layers** (hydrants, streetlights, storm drains) are uploaded as GeoJSON and shown on the resident and staff maps. A resident or clerk can pick an asset, and its history and attributes appear on the report and the work order.
- **Polygon layers** (Custom Map Layers > *Add Polygon Layer*) take a GeoJSON FeatureCollection of Polygon/MultiPolygon features in WGS 84 (EPSG:4326 or CRS84; any other declared coordinate system is refused with re-export instructions). Up to **100 MB and 200,000 features** per layer. The file is uploaded in 8 MB parts, parsed on the server one feature at a time, repaired with `ST_MakeValid`, and stored one row per polygon in PostGIS with a spatial index, so a county's parcels never have to be sent to a browser.
- **Location context.** A polygon layer whose purpose is *Location context* is matched against every new report with coordinates (resident portal, staff intake, Open311 API, connector imports, and reports geocoded after intake). The containing features are saved on the report as a snapshot, so it keeps what the parcel record said when the report came in, even after the layer is re-uploaded. Staff see a *Location context* card per feature with the other reports in the same parcel, and the work order prints it. *Record on existing reports* backfills older reports in batches. Staff cannot move a report's location.
- **Privacy.** Admins choose which fields staff see (none by default) plus an ID field (PARCEL_ID, PIN) and a label field. Only those fields are ever copied onto a report; owner names and mailing addresses in the file are used for matching only. Context layers are staff-only by default.
- **Outlines.** At parcel zoom (15+), the staff map draws context layers as outlines fetched for the visible area, simplified on the server and capped at 500 per request. An admin can also show a layer's outlines on the resident Community Requests map. That route returns shapes only: never field values, feature IDs or keys.

## Open311 API

GeoReport v2 under `/api/open311/v2`, in JSON and XML.

- **Reads** (`services`, service definitions, `requests`) need no key and show only publicly listed reports.
- **Submissions** (`POST requests.json`) need an `api_key` the town issues under Setup & Integration > **Open311 API keys**. Keys are stored hashed, can be revoked, have their own rate limit, and every issue and revocation is audited. An admin can allow anonymous submissions instead.
- An Open311 submission goes through exactly the same intake as the resident portal: location rule, moderation, photo redaction, road rules, routing and the post-save pipeline.
- Conformance with the spec is tested in `backend/tests/test_open311_spec_conformance.py` and `test_open311_api_keys_and_conformance.py`. The remaining differences are listed in [API.md](API.md#remaining-differences-from-georeport-v2).

## Research Lab

Served at `/research` for users with the `researcher` role, when the Research
Portal module is on. It provides aggregate analytics and CSV and GeoJSON exports
with a data dictionary. Exports exclude free-text descriptions and contact
details, snap coordinates to a grid, and record every access. A Data Assistant
chat runs on the same AI provider as triage.

## Records and retention

- The town clerk sets retention in days. If it is not set, nothing is purged.
- When records expire, the town chooses to anonymize them (remove resident details, keep operational counts) or delete them.
- Legal holds exempt individual records from retention.
- An administrator can restore soft-deleted reports.
