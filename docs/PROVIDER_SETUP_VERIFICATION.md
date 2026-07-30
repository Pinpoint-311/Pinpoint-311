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

Last reconciliation: 2026-07-30 (second pass, every path).

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

It is worth recording that this was not a formality. A second pass over every
path found six factual errors on top of the broken feature below.

**Azure OpenAI is no longer gated.** The steps said access "can take a day or
two to be approved if it has not been requested before" and told towns to start
that first if they were on a deadline. Microsoft removed the general
registration requirement; every subscription is eligible for the standard
models, and a form is now needed only for restricted features Pinpoint does not
use. The advice would have sent a town looking for an approval process that does
not exist, and delayed a launch for nothing.

**Okta's issuer — a correction to an earlier correction.** These steps had
claimed the issuer is "not your org URL" and "typically ends /oauth2/default".
That is wrong, and it was written while removing a passage from the setup guide
that said the opposite. Okta documents *both* as legitimate: the org
authorization server issues on the plain domain and is Okta's recommendation for
ordinary single sign-on, which is what Pinpoint does; a custom server such as
`default` issues on `/oauth2/{id}` and exists for custom claims and policies.
What matters is that the issuer matches the server the app is assigned to. The
steps now say so, and give a ten-second check —
`<issuer>/.well-known/openid-configuration` should return JSON in a browser.

**ACS text messaging is registration-first.** The steps had a town acquire a
number and then mentioned registration as a caveat. In the US, 10DLC brand and
campaign registration must be approved *before* a number can be acquired or
SMS-enabled at all. It is also not possible on a trial subscription or with free
credits. Both facts now come before the step they would otherwise block.

**Microsoft is removing password-based SMTP.** From the end of December 2026,
Exchange Online disables basic authentication for SMTP AUTH on existing tenants
by default, and tenants created after that cannot use it. A town on Microsoft
365 choosing SMTP today buys a few months. The step says so and points at the
durable alternatives.

**ArcGIS keys start `AAPK`.** The steps accepted `AAPT` as well; that is Esri's
prefix for short-lived access tokens, which is a different credential and will
not work. Keys also expire at 00:00:00 GMT on the date set, which is now stated.

**AWS KMS deletion is 7 to 30 days, defaulting to 30**, and the key becomes
unusable the moment deletion is *scheduled* rather than when the window closes —
so resident data stops decrypting immediately. It can be cancelled inside the
window. The steps said only "at least seven days".

Confirmed correct, having originally been written from memory: `TranslateReadOnly`
does include `translate:TranslateText` despite the name; `roles/cloudtranslate.user`
and `roles/aiplatform.user` are the right role names; Rekognition finds plates
via `DetectText`; Cloud KMS Encrypter/Decrypter must be granted on the key;
`AmazonSESFullAccess` exists and `ses:SendEmail` + `ses:SendRawEmail` are the
minimum; Azure Translator's region is the short form from Keys and Endpoint.

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
