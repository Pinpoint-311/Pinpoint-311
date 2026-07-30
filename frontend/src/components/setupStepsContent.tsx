import { Check, Copy } from 'lucide-react';

import { defineSteps } from './setupSteps';
import type { StepContext } from './setupSteps';

/**
 * The steps themselves, one registration per provider.
 *
 * Separate from setupSteps.tsx on purpose: that file is the mechanism and does
 * not go stale, this one is content about somebody else's console and will.
 * Vendors reorganise their menus on their own schedule, so entries here are
 * expected to be corrected over time, and a provider with no entry is a normal
 * state -- the card falls back to its plain field list.
 *
 * The rule for writing one: every step either does something or produces
 * something. `check` is what tells a clerk they are in the right place, and it
 * only earns its line when the next thing they do is paste a value. Where a
 * value must be copied exactly -- callback URLs, key restrictions -- give them
 * the copy button rather than a string to retype, because one missing character
 * fails silently and looks like a wrong password.
 *
 * The `fields` on each step are checked against the real credential catalogs by
 * backend/tests/test_setup_steps_content.py. A key invented from memory here
 * would otherwise render a box that saves to nothing, which is the failure this
 * whole page exists to avoid.
 */

/** A copy-to-clipboard chip for a value that must be exact. */
function CopyValue({ ctx, id, value }: { ctx: StepContext; id: string; value: string }) {
    return (
        <span className="inline-flex items-center gap-1 align-middle">
            <code className="bg-black/30 px-1.5 py-0.5 rounded text-[11px] text-primary-200 break-all">{value}</code>
            <button
                type="button"
                onClick={() => ctx.copy(value, id)}
                aria-label="Copy to clipboard"
                className="inline-flex text-white/40 hover:text-white/80 transition-colors"
            >
                {ctx.copied === id ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
            </button>
        </span>
    );
}

const B = ({ children }: { children: React.ReactNode }) => (
    <strong className="text-white/90">{children}</strong>
);

/** A vendor console link. Always new-tab: a clerk mid-setup who navigates away
 *  loses everything typed into the boxes below. */
const L = ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href} target="_blank" rel="noopener noreferrer"
        className="text-primary-300 underline underline-offset-2">{children}</a>
);

const C = ({ children }: { children: React.ReactNode }) => (
    <code className="bg-black/30 px-1 rounded text-[11px] text-primary-200">{children}</code>
);

// ===========================================================================
// Staff sign-in
//
// All three OIDC providers redirect to the same place. The callback URL goes in
// before the credentials come out in every one of them, because a tenant
// missing the redirect accepts the password and then fails on the way back,
// which reads to everybody as a wrong secret.
// ===========================================================================

const CALLBACK = (origin: string) => `${origin}/api/auth/callback`;

// ---------------------------------------------------------------------------
// Auth0
// ---------------------------------------------------------------------------

defineSteps('identity', 'auth0', (ctx) => [
    {
        body: (
            <>
                Create the account at <L href="https://auth0.com">auth0.com</L>, using a{' '}
                <B>shared town email address</B> rather than a personal one — whoever replaces you will
                need to get in. When it asks for a region, pick one in the US if your town or state has a
                rule about where data is held; it cannot be changed afterwards.
            </>
        ),
        check: <>the Auth0 dashboard, with your town's name in the top-left corner.</>,
    },
    {
        body: (
            <>
                In the left menu open <B>Applications → Applications</B> and press <B>Create
                Application</B>. Choose <B>Regular Web Application</B> — not Single Page, not Machine to
                Machine. If it then offers to pick a technology, close that; it only shows sample code.
            </>
        ),
        check: <>a settings page with boxes labelled Domain, Client ID and Client Secret.</>,
    },
    {
        body: (
            <>
                Still on <B>Settings</B>, scroll to <B>Application URIs</B> and paste these in, using the
                copy buttons rather than retyping:
                <span className="mt-2 grid gap-1.5">
                    <span className="flex items-center gap-2 flex-wrap">
                        <span className="text-white/45 text-xs w-40 shrink-0">Allowed Callback URLs</span>
                        <CopyValue ctx={ctx} id="a0cb" value={CALLBACK(ctx.origin)} />
                    </span>
                    <span className="flex items-center gap-2 flex-wrap">
                        <span className="text-white/45 text-xs w-40 shrink-0">Allowed Logout URLs</span>
                        <CopyValue ctx={ctx} id="a0lo" value={ctx.origin} />
                    </span>
                    <span className="flex items-center gap-2 flex-wrap">
                        <span className="text-white/45 text-xs w-40 shrink-0">Allowed Web Origins</span>
                        <CopyValue ctx={ctx} id="a0wo" value={ctx.origin} />
                    </span>
                </span>
                Then press <B>Save Changes</B> at the bottom.
            </>
        ),
        trouble: <>Do this before the next step. A tenant missing the callback URL accepts the password and then fails on the redirect, which looks like a wrong secret.</>,
    },
    {
        body: <>Copy the three values from that same Settings page into these boxes.</>,
        fields: ['AUTH0_DOMAIN', 'AUTH0_CLIENT_ID', 'AUTH0_CLIENT_SECRET'],
    },
]);

// ---------------------------------------------------------------------------
// Microsoft Entra ID
//
// The path most towns will actually take, because the staff already have
// Microsoft 365 accounts and Entra is the directory behind them. The one thing
// worth reading twice is the secret: Entra shows it once and then replaces it
// with dots forever, and the box beside it labelled "Secret ID" is not it.
// ---------------------------------------------------------------------------

defineSteps('identity', 'entra', (ctx) => [
    {
        body: (
            <>
                Sign in to the <L href="https://portal.azure.com">Azure portal</L> with an account that
                can administer your directory, open <B>Microsoft Entra ID</B>, and in the left pane choose{' '}
                <B>Manage → App registrations</B>, then <B>New registration</B>.
            </>
        ),
        check: <>a form headed "Register an application".</>,
    },
    {
        body: (
            <>
                Name it something a successor will recognise — <C>Pinpoint 311</C> is fine. Under{' '}
                <B>Redirect URI</B>, set the type to <B>Web</B> and paste{' '}
                <CopyValue ctx={ctx} id="enrd" value={CALLBACK(ctx.origin)} />. Leave the account-types
                option on the default (this directory only) unless your town genuinely shares staff with
                another tenant. Press <B>Register</B>.
            </>
        ),
        trouble: <>The redirect type matters. "Single-page application" is offered right below Web and looks equivalent; it is not, and staff sign-in will fail on the way back with an error about the flow.</>,
    },
    {
        body: (
            <>
                The overview page that appears shows <B>Application (client) ID</B> and <B>Directory
                (tenant) ID</B>. Copy both here. Leave the authority box empty unless you are on a
                sovereign cloud — it defaults to the normal commercial endpoint.
            </>
        ),
        check: <>two GUIDs on the overview page, both looking like <C>8f3c…-…-…</C>.</>,
        fields: ['ENTRA_TENANT_ID', 'ENTRA_CLIENT_ID', 'ENTRA_AUTHORITY'],
    },
    {
        body: (
            <>
                In the left pane choose <B>Manage → Certificates &amp; secrets</B>, then{' '}
                <B>Client secrets → New client secret</B>. Give it a description and an expiry, press{' '}
                <B>Add</B>, and copy the <B>Value</B> column into the box below.
            </>
        ),
        fields: ['ENTRA_CLIENT_SECRET'],
        trouble: <>Copy it now. Entra shows the Value once; leave the page and it is dots forever and you have to issue a new one. The <B>Secret ID</B> next to it is not the secret. Note the expiry date somewhere — staff sign-in stops working on that day, and it is a long way from here to that diagnosis.</>,
    },
]);

// ---------------------------------------------------------------------------
// Okta
//
// The trap here is that the issuer is not on the application page. It lives
// under a different menu entirely, and the value people reach for -- the org
// URL in the address bar -- is close enough to look right and wrong enough to
// fail.
// ---------------------------------------------------------------------------

defineSteps('identity', 'okta', (ctx) => [
    {
        body: (
            <>
                In the Okta <B>Admin Console</B> (the "Admin" button in the top-right of the normal
                dashboard), open <B>Applications → Applications</B> and press <B>Create App
                Integration</B>. Choose <B>OIDC – OpenID Connect</B> as the sign-in method and{' '}
                <B>Web Application</B> as the application type, then <B>Next</B>.
            </>
        ),
        trouble: <>Web Application, not Single-Page Application. A SPA integration issues no client secret, and the box below will have nothing to put in it.</>,
    },
    {
        body: (
            <>
                Name it, then fill the two URL fields:
                <span className="mt-2 grid gap-1.5">
                    <span className="flex items-center gap-2 flex-wrap">
                        <span className="text-white/45 text-xs w-44 shrink-0">Sign-in redirect URIs</span>
                        <CopyValue ctx={ctx} id="okrd" value={CALLBACK(ctx.origin)} />
                    </span>
                    <span className="flex items-center gap-2 flex-wrap">
                        <span className="text-white/45 text-xs w-44 shrink-0">Sign-out redirect URIs</span>
                        <CopyValue ctx={ctx} id="oklo" value={ctx.origin} />
                    </span>
                </span>
                Under <B>Assignments</B>, pick the groups whose members should be able to sign in to
                Pinpoint, then <B>Save</B>.
            </>
        ),
        check: <>the app's <B>General</B> tab, with a <B>Client Credentials</B> section on it.</>,
    },
    {
        body: (
            <>
                Copy <B>Client ID</B> from that section, and press <B>Show</B> beside <B>Client
                secret</B> to reveal and copy the other.
            </>
        ),
        fields: ['OKTA_CLIENT_ID', 'OKTA_CLIENT_SECRET'],
    },
    {
        body: (
            <>
                The issuer is somewhere else. Open <B>Security → API</B> in the left menu and copy the{' '}
                <B>Issuer URI</B> of the authorization server you are using — usually the one named{' '}
                <C>default</C>.
            </>
        ),
        fields: ['OKTA_ISSUER'],
        trouble: <>Not your org URL. It typically ends <C>/oauth2/default</C>, and the plain org address looks close enough to be pasted by mistake — after which sign-in fails at discovery with a message that names neither.</>,
    },
]);

// ---------------------------------------------------------------------------
// Generic OIDC
//
// For a state-run identity provider, Keycloak, Shibboleth, or anything else
// standards-compliant. Written as questions to ask whoever runs it rather than
// as a menu path, because there is no menu to describe.
// ---------------------------------------------------------------------------

defineSteps('identity', 'oidc', (ctx) => [
    {
        body: (
            <>
                Ask whoever operates your identity provider to register a <B>confidential client</B>{' '}
                (sometimes called a web or server-side application) using the <B>authorization code</B>{' '}
                flow, with this redirect URI: <CopyValue ctx={ctx} id="oidcrd" value={CALLBACK(ctx.origin)} />.
                Ask for the scopes <C>openid</C>, <C>profile</C> and <C>email</C> — Pinpoint matches staff
                accounts by email address, so a provider that does not release it cannot be used.
            </>
        ),
        trouble: <>If they offer a "public client", that is the wrong kind: it issues no secret. Say confidential, or server-side.</>,
    },
    {
        body: (
            <>
                Ask for the <B>issuer URL</B> — the base address, not the full endpoint. You can check it
                yourself: <C>{'<issuer>'}/.well-known/openid-configuration</C> should return a page of
                JSON in a browser. If it 404s, the issuer is wrong.
            </>
        ),
        fields: ['OIDC_ISSUER'],
    },
    {
        body: <>Then the client's ID and secret.</>,
        fields: ['OIDC_CLIENT_ID', 'OIDC_CLIENT_SECRET'],
    },
]);

// ===========================================================================
// Maps
// ===========================================================================

// ---------------------------------------------------------------------------
// Google Maps
//
// Billing is step one rather than a footnote: without it Google issues a key
// that looks correct and the map shows a grey box, which is the single most
// common failure on this page.
// ---------------------------------------------------------------------------

defineSteps('maps', 'google', (ctx) => [
    {
        body: (
            <>
                In <L href="https://console.cloud.google.com">Google Cloud</L>, open{' '}
                <B>APIs &amp; Services → Library</B> and enable all three of <C>Maps JavaScript API</C>,{' '}
                <C>Geocoding API</C> and <C>Places API</C>. Then open <B>Billing</B> and attach a payment
                method.
            </>
        ),
        check: <>an "API Enabled" banner on each of the three, and a billing account listed under Billing.</>,
        trouble: <>The payment method is not optional and it is the step people skip. Google will issue a key without it, the key will look correct, and the map will show a grey box saying "this page can't load Google Maps correctly".</>,
    },
    {
        body: (
            <>
                Go to <B>APIs &amp; Services → Credentials → Create Credentials → API key</B>. Then open
                the key and restrict it: under <B>Application restrictions</B> choose <B>Websites</B> and
                add <CopyValue ctx={ctx} id="gmref" value={`${ctx.origin}/*`} /> — the <C>/*</C> matters.
                Under <B>API restrictions</B> choose <B>Restrict key</B> and tick the same three APIs.
            </>
        ),
        check: <>your site under Website restrictions, and only those three APIs ticked.</>,
        trouble: <>An unrestricted key can be lifted off your site and run up a bill on the town's card.</>,
    },
    {
        body: <>Paste the key here. The Map ID is optional and only changes how the map looks — leave it empty.</>,
        fields: ['GOOGLE_MAPS_API_KEY', 'GOOGLE_MAPS_MAP_ID'],
        trouble: <>Changes to a Google key can take up to five minutes. If the map is still grey straight after saving, wait before changing anything else.</>,
    },
]);

// ---------------------------------------------------------------------------
// Esri / ArcGIS
//
// The one most likely to already be in place: a town with a GIS department has
// an ArcGIS organisation, and often its own address locator, which is better
// than any national geocoder at finding a local address.
// ---------------------------------------------------------------------------

defineSteps('maps', 'esri', () => [
    {
        body: (
            <>
                Before anything else, ask your GIS department whether the town already has an ArcGIS
                organisation. If it does, the key should be created there rather than on a new personal
                developer account — otherwise it belongs to whoever signed up.
            </>
        ),
    },
    {
        body: (
            <>
                Sign in at <L href="https://location.arcgis.com">location.arcgis.com</L>, open the
                developer dashboard, and create an <B>API key</B> credential. Scope it to the services
                you need: <B>Basemap styles</B> and <B>Geocoding</B> at minimum. Set an expiry you will
                remember — ArcGIS API keys are valid for up to a year and then simply stop.
            </>
        ),
        check: <>a key string starting <C>AAPT</C> or <C>AAPK</C>.</>,
        trouble: <>Note the expiry date somewhere the town will see it. When one of these lapses the map goes blank with no warning and nothing in the console says why.</>,
    },
    {
        body: (
            <>
                Paste the key. Both other boxes are optional: the basemap is an Esri style id (for
                example <C>arcgis/navigation</C>) if you want something other than the default, and the
                locator is the URL of your own address locator service if the GIS department publishes
                one.
            </>
        ),
        fields: ['ARCGIS_API_KEY', 'ARCGIS_BASEMAP_ID', 'ARCGIS_LOCATOR_URL'],
        trouble: <>A town locator is worth asking for. It knows your street names, your address ranges and your recent subdivisions, which a national geocoder often does not.</>,
    },
]);

// ---------------------------------------------------------------------------
// Azure Maps
// ---------------------------------------------------------------------------

defineSteps('maps', 'azure', () => [
    {
        body: (
            <>
                In the <L href="https://portal.azure.com">Azure portal</L>, press <B>Create a
                resource</B>, search for <B>Azure Maps</B>, and create an account in the same
                subscription and region as the rest of your Azure services.
            </>
        ),
        check: <>the new Maps account's overview page.</>,
    },
    {
        body: (
            <>
                Open <B>Settings → Authentication</B> on that account and copy the <B>Primary Key</B>{' '}
                under Shared Key Authentication.
            </>
        ),
        fields: ['AZURE_MAPS_KEY'],
        trouble: <>Take the primary key and leave the secondary alone. The pair exists so a key can be rotated without downtime — using both at once removes the point of having two.</>,
    },
]);

// ---------------------------------------------------------------------------
// Apple Maps
//
// The most involved of the four and the only one where a downloaded file is the
// credential. It also requires a paid Apple Developer membership, which is
// worth saying at the top rather than discovering at step three.
// ---------------------------------------------------------------------------

defineSteps('maps', 'apple', () => [
    {
        body: (
            <>
                This needs a paid <L href="https://developer.apple.com/programs/">Apple Developer
                Program</L> membership (about $99/year) held by the town, not by a person. If you do not
                have one, one of the other map providers will be much less work.
            </>
        ),
    },
    {
        body: (
            <>
                At <L href="https://developer.apple.com/account">developer.apple.com/account</L> open{' '}
                <B>Certificates, Identifiers &amp; Profiles → Identifiers</B>, press <B>+</B>, and create
                an identifier of type <B>Maps IDs</B>.
            </>
        ),
        check: <>your new Maps ID in the identifiers list.</>,
    },
    {
        body: (
            <>
                Then open <B>Keys</B> in the same sidebar, press <B>+</B>, tick <B>MapKit JS</B>, and
                configure it to use the Maps ID you just made. Create the key and press <B>Download</B>.
                You get a file named <C>AuthKey_XXXXXXXXXX.p8</C>.
            </>
        ),
        trouble: <>Download it now and keep it. Apple removes the file from their servers after the one download; if you lose it the only remedy is revoking the key and starting again.</>,
    },
    {
        body: (
            <>
                The <B>Key ID</B> is on that key's page. The <B>Team ID</B> is in{' '}
                <B>Membership details</B> at the top of your account. For the private key, open the{' '}
                <C>.p8</C> file in a plain text editor and paste the whole contents — including the{' '}
                <C>-----BEGIN PRIVATE KEY-----</C> and <C>-----END PRIVATE KEY-----</C> lines.
            </>
        ),
        fields: ['APPLE_MAPKIT_TEAM_ID', 'APPLE_MAPKIT_KEY_ID', 'APPLE_MAPKIT_PRIVATE_KEY'],
        trouble: <>Open it with a text editor, not Word — a word processor will add formatting that makes the key unreadable. The header and footer lines are part of the key, not decoration.</>,
    },
]);

// ===========================================================================
// AI analysis
// ===========================================================================

defineSteps('ai', 'vertex', () => [
    {
        body: (
            <>
                In <L href="https://console.cloud.google.com">Google Cloud</L>, select or create the
                project you want to bill this to, then open <B>APIs &amp; Services → Library</B> and
                enable <C>Vertex AI API</C>. Attach a billing account if the project has none.
            </>
        ),
        check: <>"API Enabled" on the Vertex AI API page.</>,
    },
    {
        body: (
            <>
                Open <B>IAM &amp; Admin → Service Accounts</B> and create one — a name like{' '}
                <C>pinpoint-311</C> is fine. Grant it the <B>Vertex AI User</B> role. Do not grant Owner
                or Editor: this account only ever needs to ask the model a question.
            </>
        ),
        trouble: <>The broad roles are one click away and it is tempting to take them to avoid a permissions problem later. A leaked key with Vertex AI User can run up a model bill; the same key with Editor can delete the project.</>,
    },
    {
        body: (
            <>
                On that service account open <B>Keys → Add Key → Create new key → JSON</B>. A file
                downloads. Open it in a plain text editor and paste the whole contents below, along with
                your project ID (it is in the file, as <C>project_id</C>).
            </>
        ),
        fields: ['VERTEX_AI_PROJECT', 'VERTEX_AI_SERVICE_ACCOUNT_KEY'],
        trouble: <>Delete the downloaded file once it is saved here. It is a password to your cloud account sitting in the Downloads folder of whichever machine did the setup.</>,
    },
]);

defineSteps('ai', 'azure', () => [
    {
        body: (
            <>
                In the <L href="https://portal.azure.com">Azure portal</L>, create an <B>Azure OpenAI</B>{' '}
                resource in a region your town is allowed to use. Access to Azure OpenAI is granted per
                subscription and can take a day or two to be approved if it has not been requested
                before.
            </>
        ),
        trouble: <>Check this first if you are on a deadline. Everything else here takes ten minutes; the approval does not.</>,
    },
    {
        body: (
            <>
                Open the resource in <L href="https://ai.azure.com">Microsoft Foundry</L> and deploy a
                model — <B>Deployments → Deploy model</B>. The <B>deployment name</B> you choose is what
                goes in the box below, and it is not necessarily the model name: you can call a GPT-4o
                deployment anything you like, and Pinpoint asks for the deployment.
            </>
        ),
        check: <>your deployment listed with status Succeeded.</>,
    },
    {
        body: (
            <>
                Back on the Azure resource, open <B>Resource Management → Keys and Endpoint</B> and copy{' '}
                <B>KEY 1</B> and the <B>Endpoint</B>. Leave the API version box empty unless Microsoft
                has told you to pin one — it defaults to a current version.
            </>
        ),
        fields: ['AZURE_OPENAI_ENDPOINT', 'AZURE_OPENAI_API_KEY', 'AZURE_OPENAI_DEPLOYMENT', 'AZURE_OPENAI_API_VERSION'],
        trouble: <>The endpoint is the base address ending in a slash, not the full chat-completions URL from the sample code.</>,
    },
]);

defineSteps('ai', 'bedrock', () => [
    {
        body: (
            <>
                In the <L href="https://console.aws.amazon.com/bedrock">Bedrock console</L>, set the
                region selector (top right) to the region you intend to use — model availability differs
                by region and this choice is load-bearing for everything below.
            </>
        ),
    },
    {
        body: (
            <>
                In the left pane under <B>Bedrock configurations</B> choose <B>Model access</B>, then{' '}
                <B>Modify model access</B>. Select the models you want and submit the use-case form.
                Access usually appears within a few minutes.
            </>
        ),
        check: <>the model showing <B>Access granted</B> rather than Available to request.</>,
        trouble: <>If submitting fails, the account may not have AWS Marketplace subscription permission — that lives under <B>Billing → Marketplace settings</B> and usually needs whoever owns the AWS account.</>,
    },
    {
        body: (
            <>
                Create an IAM user for Pinpoint with permission to invoke models —{' '}
                <C>bedrock:InvokeModel</C> and <C>bedrock:InvokeModelWithResponseStream</C> — and nothing
                else. Take an access key from <B>Security credentials</B> and paste it here with the same
                region you set above.
            </>
        ),
        fields: ['AWS_REGION', 'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY'],
        trouble: <>The secret access key is shown once, on the screen where you create it. There is no way to see it again — only to issue a new one.</>,
    },
]);

// ===========================================================================
// Translation
// ===========================================================================

defineSteps('translation', 'google', () => [
    {
        body: (
            <>
                In <L href="https://console.cloud.google.com">Google Cloud</L>, open{' '}
                <B>APIs &amp; Services → Library</B> and enable <C>Cloud Translation API</C> in the same
                project you are using elsewhere.
            </>
        ),
        check: <>"API Enabled" on the Cloud Translation API page.</>,
    },
    {
        body: (
            <>
                Enter that project's ID. Translation reuses the Google credentials already configured for
                this deployment, so there is no separate key to create.
            </>
        ),
        fields: ['GOOGLE_CLOUD_PROJECT'],
        trouble: <>The project <B>ID</B>, not the display name. They are often similar and occasionally identical; the ID is the one shown in the project picker in smaller grey type.</>,
    },
]);

defineSteps('translation', 'azure', () => [
    {
        body: (
            <>
                In the <L href="https://portal.azure.com">Azure portal</L>, press <B>Create a
                resource</B> and create a <B>Translator</B> resource. The free tier handles a
                small town's volume; note the <B>region</B> you pick, because it is part of the
                credentials.
            </>
        ),
    },
    {
        body: (
            <>
                Open <B>Resource Management → Keys and Endpoint</B> and copy <B>KEY 1</B> and the{' '}
                <B>Location/Region</B> value. Leave the endpoint box empty unless you were given a
                custom one — the default global endpoint is correct for almost everyone.
            </>
        ),
        fields: ['AZURE_TRANSLATOR_KEY', 'AZURE_TRANSLATOR_REGION', 'AZURE_TRANSLATOR_ENDPOINT'],
        trouble: <>The region must be the short form shown on that page, like <C>eastus</C>, not "East US". A mismatched region fails authentication and reports it as a bad key.</>,
    },
]);

defineSteps('translation', 'aws', () => [
    {
        body: (
            <>
                Amazon Translate needs no setup in its own console — it is on by default. Create an IAM
                user for Pinpoint with the <C>TranslateReadOnly</C> managed policy, which despite the
                name is what permits translating text.
            </>
        ),
        trouble: <>If you already made an IAM user for Bedrock or SES, add this policy to that one rather than creating another set of keys to keep track of.</>,
    },
    {
        body: <>Take an access key from that user's <B>Security credentials</B> tab and enter it with your region.</>,
        fields: ['AWS_REGION', 'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY'],
    },
]);

// ===========================================================================
// Email
// ===========================================================================

defineSteps('email', 'smtp', () => [
    {
        body: (
            <>
                Ask whoever runs the town's email for the SMTP server address and port, and for a
                dedicated account to send from. A separate account matters: when residents reply to a
                status update, the replies land wherever this sends from.
            </>
        ),
        trouble: <>Microsoft 365 and Google Workspace both restrict plain SMTP by default. If your IT provider says it is blocked, they are right, and Amazon SES or Azure Communication Services will be less work than arguing for an exception.</>,
    },
    {
        body: (
            <>
                Fill in the server details. Port <C>587</C> with STARTTLS is the usual answer; <C>465</C>{' '}
                is the older implicit-TLS port and also works.
            </>
        ),
        fields: ['SMTP_HOST', 'SMTP_PORT', 'SMTP_USER', 'SMTP_PASSWORD'],
    },
    {
        body: (
            <>
                Then what residents see in their inbox. Use a monitored address —{' '}
                <C>311@yourtown.gov</C> rather than <C>noreply@</C>, because people reply to these and a
                reply that goes nowhere is a complaint you never hear.
            </>
        ),
        fields: ['SMTP_FROM_EMAIL', 'SMTP_FROM_NAME'],
    },
]);

defineSteps('email', 'ses', () => [
    {
        body: (
            <>
                In the <L href="https://console.aws.amazon.com/ses">SES console</L>, set your region,
                then open <B>Identities → Create identity</B> and verify your <B>domain</B> — not just a
                single address. Verifying the domain lets you send from any address on it, and it is what
                makes DKIM available.
            </>
        ),
        check: <>the identity showing <B>Verified</B>. It requires DNS records, so whoever manages the town's DNS needs to be involved.</>,
    },
    {
        body: (
            <>
                New SES accounts are in the <B>sandbox</B> and can only send to addresses you have also
                verified — which means residents get nothing. Open <B>Account dashboard</B> and press{' '}
                <B>Request production access</B>. Approval usually takes about a day.
            </>
        ),
        trouble: <>This is the step that quietly breaks a launch. In the sandbox everything looks like it works: SES accepts the message and returns success, and the resident never receives it.</>,
    },
    {
        body: (
            <>
                Create an IAM user for Pinpoint with the <C>AmazonSESFullAccess</C> policy (or just{' '}
                <C>ses:SendEmail</C> and <C>ses:SendRawEmail</C> if you would rather be precise), then
                fill these in. The from address must be on the domain you verified.
            </>
        ),
        fields: ['AWS_REGION', 'SES_FROM_EMAIL', 'SMTP_FROM_NAME', 'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY'],
        trouble: <>The region must be the one where you verified the domain. SES identities do not exist across regions, and a mismatch reports as an unverified sender.</>,
    },
]);

defineSteps('email', 'acs', () => [
    {
        body: (
            <>
                In the <L href="https://portal.azure.com">Azure portal</L> create two resources:{' '}
                <B>Communication Services</B>, and <B>Email Communication Services</B>. Both are needed,
                and they must be in the <B>same geography</B> — you cannot connect them otherwise.
            </>
        ),
        trouble: <>Two resources with near-identical names is genuinely confusing. The Email one owns the domain; the plain Communication Services one owns the endpoint and key.</>,
    },
    {
        body: (
            <>
                On the Email resource, add a domain. <B>Add a free Azure subdomain</B> is one click and
                works immediately, but sends from an <C>azurecomm.net</C> address, which residents will
                not recognise as the town. <B>Set up a custom domain</B> takes DNS records (TXT, SPF and
                DKIM) and is worth it for anything public-facing.
            </>
        ),
        check: <>the domain listed with verification complete, and a MailFrom address shown on its page.</>,
    },
    {
        body: (
            <>
                Open the Communication Services resource, go to <B>Email → Domains</B> and press{' '}
                <B>Connect domain</B> to link the one you just made.
            </>
        ),
    },
    {
        body: (
            <>
                Then on that same resource open <B>Settings → Keys</B> and copy the <B>Endpoint</B> and{' '}
                <B>Primary key</B>. The from address is the MailFrom value on the domain page.
            </>
        ),
        fields: ['ACS_ENDPOINT', 'ACS_ACCESS_KEY', 'ACS_FROM_EMAIL', 'SMTP_FROM_NAME'],
    },
]);

// ===========================================================================
// Text messages
// ===========================================================================

defineSteps('sms', 'twilio', () => [
    {
        body: (
            <>
                Sign in at <L href="https://console.twilio.com">console.twilio.com</L>. The{' '}
                <B>Account SID</B> and <B>Auth Token</B> are on the dashboard home page.
            </>
        ),
        fields: ['TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN'],
    },
    {
        body: <>Buy or select a number under <B>Phone Numbers → Manage → Active numbers</B>, and enter it in <C>+1XXXXXXXXXX</C> form.</>,
        fields: ['TWILIO_PHONE_NUMBER'],
        trouble: <>It has to be a number you own in Twilio. A trial account can only text numbers you have verified.</>,
    },
]);

defineSteps('sms', 'sns', () => [
    {
        body: (
            <>
                In the <L href="https://console.aws.amazon.com/sns">SNS console</L>, open <B>Text
                messaging (SMS)</B> in the left pane and check the account status at the top. A new
                account is in the <B>SMS sandbox</B> and can only text numbers you have verified there.
            </>
        ),
        trouble: <>Leave the sandbox before launch, from that same page. Inside it, messages to residents are rejected — and the rejection is in a log, not on the page where somebody would see it.</>,
    },
    {
        body: (
            <>
                Still on that page, set a <B>monthly spending limit</B> you are comfortable with, then
                register an origination identity. For a US municipality that normally means a{' '}
                <B>10DLC</B> number, which requires registering the town as a brand; the carriers filter
                unregistered traffic heavily.
            </>
        ),
        trouble: <>Start the 10DLC registration early. It is a carrier process, not an AWS one, and it can take a couple of weeks.</>,
    },
    {
        body: (
            <>
                Create an IAM user for Pinpoint with permission for <C>sns:Publish</C>, and enter its
                access key with your region. The sender ID box is optional and only has an effect in
                countries that support alphabetic senders — it is ignored for US numbers.
            </>
        ),
        fields: ['AWS_REGION', 'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'SMS_SENDER_ID'],
    },
]);

defineSteps('sms', 'acs', () => [
    {
        body: (
            <>
                Use the same <B>Communication Services</B> resource as email if you have one. Open it in
                the <L href="https://portal.azure.com">Azure portal</L> and go to{' '}
                <B>Telephony and SMS → Phone numbers → Get</B> to acquire a number with SMS enabled.
            </>
        ),
        check: <>a number listed with SMS among its capabilities.</>,
        trouble: <>Acquiring a US number needs a regulatory profile and, for most SMS use, 10DLC registration. Azure walks you through it, but it is not instant — start it before you need it.</>,
    },
    {
        body: (
            <>
                Then <B>Settings → Keys</B> on that resource for the endpoint and key, and the number you
                just acquired in <C>+1XXXXXXXXXX</C> form.
            </>
        ),
        fields: ['ACS_ENDPOINT', 'ACS_ACCESS_KEY', 'SMS_FROM_NUMBER'],
    },
]);

defineSteps('sms', 'http', () => [
    {
        body: (
            <>
                For a gateway that is not listed — a regional carrier, a state contract, or an existing
                notification system. Pinpoint sends a POST with a JSON body containing the destination
                number and the message text, and treats any 2xx response as delivered.
            </>
        ),
    },
    {
        body: (
            <>
                Enter the endpoint URL your provider gave you, and the key they issued. The key is sent
                as a bearer token.
            </>
        ),
        fields: ['SMS_HTTP_API_URL', 'SMS_HTTP_API_KEY'],
        trouble: <>If their API expects a different shape or a different header, this will fail on every send. Check with them before relying on it, and send yourself a test message from the button below.</>,
    },
]);

// ===========================================================================
// Key management for resident data
//
// These wrap the key that encrypts resident names, emails and phone numbers.
// The recurring warning is the same in all three: this key is not something you
// can lose and re-create. Losing it means the data it protected is gone.
// ===========================================================================

defineSteps('kms', 'google', () => [
    {
        body: (
            <>
                In <L href="https://console.cloud.google.com">Google Cloud</L>, enable{' '}
                <C>Cloud KMS API</C>, then open <B>Security → Key Management</B> and create a{' '}
                <B>key ring</B> followed by a <B>key</B> inside it. Choose purpose{' '}
                <B>Symmetric encrypt/decrypt</B>. A rotation period of 90 days is a reasonable default.
            </>
        ),
        check: <>your key listed inside your key ring.</>,
    },
    {
        body: (
            <>
                Grant the service account this deployment uses the role <B>Cloud KMS CryptoKey
                Encrypter/Decrypter</B> on that key. Grant it on the key itself, not on the whole
                project.
            </>
        ),
        trouble: <>Without this the key exists, the settings save, and resident data is quietly encrypted with the application key instead. The health dashboard will say so — it is the one place that reports it.</>,
    },
    {
        body: (
            <>
                Enter the location, key ring name and key name exactly as they appear in the console.
                The location is the short form, like <C>us-central1</C>.
            </>
        ),
        fields: ['KMS_LOCATION', 'KMS_KEY_RING', 'KMS_KEY_ID'],
        trouble: <>Never delete or disable this key, or the key ring holding it. Resident contact details are encrypted under it, and Google cannot recover a destroyed key for anyone.</>,
    },
]);

defineSteps('kms', 'azure', () => [
    {
        body: (
            <>
                In the <L href="https://portal.azure.com">Azure portal</L> create a <B>Key Vault</B>.
                Turn on <B>soft delete</B> and <B>purge protection</B> — both are offered during
                creation, and they are what stops an accidental deletion becoming permanent.
            </>
        ),
        trouble: <>Purge protection cannot be turned on later on some configurations, and it is exactly the setting a town regrets not having. Take it now.</>,
    },
    {
        body: (
            <>
                Open <B>Objects → Keys → Generate/Import</B> and create an <B>RSA</B> key. 2048 is fine;
                4096 is fine too. Note the key's name.
            </>
        ),
        check: <>the key listed with status Enabled.</>,
    },
    {
        body: (
            <>
                Register an application for Pinpoint (<B>Microsoft Entra ID → App registrations → New
                registration</B>), create a client secret for it under{' '}
                <B>Certificates &amp; secrets</B>, and grant that application <B>Get</B>, <B>Wrap Key</B>{' '}
                and <B>Unwrap Key</B> on the vault — under <B>Access policies</B>, or as the{' '}
                <B>Key Vault Crypto User</B> role if your vault uses Azure RBAC.
            </>
        ),
        trouble: <>Wrap and Unwrap are the two that matter and they are easy to miss in a long checklist of permissions. Get alone is not enough.</>,
    },
    {
        body: (
            <>
                Then fill these in. The vault URL is the full{' '}
                <C>https://yourvault.vault.azure.net/</C> address from the vault's overview page.
            </>
        ),
        fields: ['AZURE_KEYVAULT_URL', 'AZURE_KEYVAULT_KEY', 'AZURE_TENANT_ID', 'AZURE_KEYVAULT_CLIENT_ID', 'AZURE_KEYVAULT_CLIENT_SECRET'],
        trouble: <>The client secret has an expiry date. Write it down: when it lapses, resident data stops decrypting, and nothing about that failure points at a calendar.</>,
    },
]);

defineSteps('kms', 'aws', () => [
    {
        body: (
            <>
                In the <L href="https://console.aws.amazon.com/kms">KMS console</L>, set your region,
                choose <B>Customer managed keys</B>, then <B>Create key</B>. Take key type{' '}
                <B>Symmetric</B> and key usage <B>Encrypt and decrypt</B> — both are the defaults. Give
                it an alias like <C>pinpoint-311-pii</C>.
            </>
        ),
        check: <>the key listed with status Enabled.</>,
    },
    {
        body: (
            <>
                On the key's <B>Key policy</B>, add the IAM user or role this deployment uses as a{' '}
                <B>key user</B>, which grants encrypt and decrypt. Then enter the key ID (or its ARN) and
                the region.
            </>
        ),
        fields: ['AWS_REGION', 'AWS_KMS_KEY_ID'],
        trouble: <>Never schedule this key for deletion. AWS enforces a waiting period of at least seven days, and at the end of it the resident data encrypted under it is unrecoverable — by you, and by AWS.</>,
    },
]);

// ===========================================================================
// Photo redaction
//
// Three cloud detectors and one that runs here. The steps are short because the
// work is a permission, not a console tour -- and the settings below are what a
// town is actually deciding, which is what to blur.
// ===========================================================================

const REDACTION_CHOICE = (
    <>
        Faces and licence plates are both on by default. Residents photograph potholes with cars parked
        beside them and neighbours walking past, and neither of those people asked to be in a public
        record.
    </>
);

defineSteps('redaction', 'google', () => [
    {
        body: (
            <>
                In <L href="https://console.cloud.google.com">Google Cloud</L>, open{' '}
                <B>APIs &amp; Services → Library</B> and enable <C>Cloud Vision API</C>. The service
                account this deployment already uses needs no extra role beyond being able to call it.
            </>
        ),
        check: <>"API Enabled" on the Cloud Vision API page.</>,
    },
    { body: REDACTION_CHOICE, fields: ['REDACT_FACES', 'REDACT_PLATES'] },
]);

defineSteps('redaction', 'aws', () => [
    {
        body: (
            <>
                Amazon Rekognition needs nothing enabled in its console. Add{' '}
                <C>rekognition:DetectFaces</C> and <C>rekognition:DetectText</C> to the IAM user this
                deployment uses — plate detection works by reading text in the image.
            </>
        ),
    },
    { body: REDACTION_CHOICE, fields: ['REDACT_FACES', 'REDACT_PLATES'] },
]);

// Azure is the only redaction backend with credentials of its own. Google and
// AWS reuse what was entered elsewhere; Azure needs two separate resources,
// because Microsoft splits face detection and text reading across them.

defineSteps('redaction', 'azure', () => [
    {
        body: (
            <>
                <B>Read this before choosing Azure.</B> Faces and plates come from two different Azure
                services, so you create two resources, and the face one is gated: Microsoft keeps the{' '}
                <B>Face API</B> behind a Limited Access review under its Responsible AI Standard.
                Detection — returning rectangles, which is all Pinpoint does — is the least restricted
                use, but the subscription still has to be approved before it will answer. If you only
                want plates, you can skip the face resource entirely.
            </>
        ),
        trouble: <>If your town cannot get through that review, pick a different detector. Google and Amazon have no equivalent gate, and the on-server option has none at all.</>,
    },
    {
        body: (
            <>
                For faces: in the <L href="https://portal.azure.com">Azure portal</L> create a <B>Face</B>{' '}
                resource (under Azure AI services), then open{' '}
                <B>Resource Management → Keys and Endpoint</B> and copy <B>KEY 1</B> and the endpoint.
            </>
        ),
        fields: ['AZURE_FACE_ENDPOINT', 'AZURE_FACE_KEY'],
    },
    {
        body: (
            <>
                For plates: create a <B>Computer Vision</B> resource — Microsoft also lists this as{' '}
                <B>Azure AI Vision</B>, and the two names refer to the same thing. Copy its key and
                endpoint from the same place. Plates are found by reading the text in the photo, which
                is why this is a separate service from the one that finds faces.
            </>
        ),
        fields: ['AZURE_VISION_ENDPOINT', 'AZURE_VISION_KEY'],
        trouble: <>A multi-service Azure AI resource covers the vision half, but not Face — that one is always its own resource.</>,
    },
    { body: REDACTION_CHOICE, fields: ['REDACT_FACES', 'REDACT_PLATES'] },
]);

defineSteps('redaction', 'local', () => [
    {
        body: (
            <>
                Detection runs on this server. Nothing to configure and no photo ever leaves the
                building, which is the reason to choose it. It finds fewer faces than the cloud
                detectors, particularly small or partly turned ones — so it is the safer choice for
                privacy and the weaker one for coverage.
            </>
        ),
    },
    { body: REDACTION_CHOICE, fields: ['REDACT_FACES', 'REDACT_PLATES'] },
]);
