# Provider setup instructions — what has been verified, and how

The per-provider steps in `frontend/src/components/setupStepsContent.tsx` describe
other companies' admin consoles. Those get reorganised on their own schedule, so
this file records what each entry was checked against and by what method. The
point is that staleness is *visible* rather than assumed.

Three levels, and the difference matters:

- **Walked** — somebody created the account, clicked the menus, obtained the
  credential and watched the feature work end to end.
- **Documented** — the steps were reconciled against the vendor's current
  official documentation. This catches renamed menus and wrong role names. It
  does not catch a console whose layout differs from its own docs, which is
  common and is why "walked" is a separate level.
- **Generic** — there is no vendor console to describe. The steps are questions
  to ask whoever operates the system, or a protocol description.

Field *keys* are not on this scale: every `fields:` declaration is checked
against the real credential catalogs by
`backend/tests/test_setup_steps_content.py`, and every secret the dispatch code
reads is checked to have a box by `backend/tests/test_dispatch_keys_are_enterable.py`.
Those are machine-verified on every commit regardless of the level below.

Last reconciliation: 2026-07-30.

| Path | Level | Checked against |
|---|---|---|
| `identity:auth0` | **Walked** | Auth0 dashboard, end to end |
| `identity:entra` | Documented | learn.microsoft.com — Register an app; Certificates & secrets |
| `identity:okta` | Documented | developer.okta.com / help.okta.com — Create OIDC app integrations; Security → API |
| `identity:oidc` | Generic | OpenID Connect Discovery |
| `maps:google` | **Walked** | Google Cloud console, end to end |
| `maps:esri` | Documented | location.arcgis.com developer dashboard; API key credentials |
| `maps:azure` | Documented | learn.microsoft.com — Manage authentication in Azure Maps |
| `maps:apple` | Documented | developer.apple.com — Creating a Maps identifier and a private key |
| `ai:vertex` | Documented | Vertex AI User role (`roles/aiplatform.user`) |
| `ai:azure` | Documented | learn.microsoft.com — Foundry deployments; Keys and Endpoint |
| `ai:bedrock` | Documented | Bedrock console — Model access; Marketplace subscription permission |
| `translation:google` | Documented | Cloud Translation API User (`roles/cloudtranslate.user`) |
| `translation:azure` | Documented | Translator resource — Keys and Endpoint, Location/Region |
| `translation:aws` | Documented | `TranslateReadOnly` managed policy (includes `translate:TranslateText`) |
| `email:smtp` | Generic | SMTP; the M365/Workspace restriction is a policy fact, not a console path |
| `email:ses` | Documented | SES console — Identities, Create identity; Request production access |
| `email:acs` | Documented | learn.microsoft.com — Prepare an email resource; Connect domain; MailFrom |
| `sms:twilio` | **Walked** | Twilio console, end to end |
| `sms:sns` | Documented | SNS console — Text messaging (SMS); SMS sandbox; origination identities |
| `sms:acs` | Documented | Azure portal — Telephony and SMS → Phone numbers |
| `sms:http` | Generic | Pinpoint's own POST contract |
| `kms:google` | Documented | Cloud KMS — Create a key; CryptoKey Encrypter/Decrypter role |
| `kms:azure` | Documented | Key Vault — Generate/Import; access policy `wrapKey`/`unwrapKey` |
| `kms:aws` | Documented | KMS console — Create key, Symmetric, Encrypt and decrypt |
| `redaction:google` | Documented | Cloud Vision API |
| `redaction:aws` | Documented | Rekognition `DetectFaces` / `DetectText` |
| `redaction:azure` | Documented | Face and Computer Vision are separate resources; Face is Limited Access |
| `redaction:local` | Generic | Runs here; nothing to configure |

## What reconciliation caught

It is worth recording that this was not a formality.

**Azure photo redaction was broken, not just imprecise.** Writing the steps
surfaced that `image_redaction.py` reads four keys — `AZURE_FACE_ENDPOINT`,
`AZURE_FACE_KEY`, `AZURE_VISION_ENDPOINT`, `AZURE_VISION_KEY` — that no card
offered. Google and AWS reuse credentials entered elsewhere, so the gap was
invisible: a town could select Azure, tick both blur toggles, save successfully,
and have every resident photo stored unblurred, with no error and nowhere on the
page to fix it. The catalog now offers all four, and
`test_dispatch_keys_are_enterable.py` fails if a provider path ever again reads a
secret that nothing can set.

**Azure's vision service has two names.** Microsoft lists it as both *Computer
Vision* and *Azure AI Vision*; the steps now say so, rather than sending someone
to look for one of the two.

## Recommended before a public launch

Two paths are worth walking by hand rather than trusting to documentation:

1. **Microsoft Entra ID** — the path most municipalities will take, because
   their staff already have Microsoft 365 accounts. Highest traffic, so highest
   cost if a menu has moved.
2. **Amazon SES** — its sandbox failure mode is indistinguishable from success.
   SES accepts the message, returns a success response, and delivers nothing to
   an unverified address. Documentation describes this correctly; only a real
   send proves the account is out of the sandbox.

Walking either one is roughly fifteen minutes and needs an account of that
vendor's. Update the level in the table when done.
