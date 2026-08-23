# Azure — `pinpoint-311.json`

An ARM template. The Azure portal reads it and draws its own Custom deployment
form, so the preview a town sees before pressing **Create** comes from Microsoft.

## What it creates

Everything is optional and off or on via a checkbox on the form.

| Toggle | Creates | Fills these Pinpoint boxes |
| --- | --- | --- |
| `deployKeyVault` (on) | Key vault with Azure-role permissions, soft delete and **purge protection**; one RSA key with `wrapKey`/`unwrapKey` only | Key Vault URL, Key name |
| `pinpointPrincipalObjectId` (blank) | Key Vault Crypto User **and** Key Vault Secrets Officer for that identity, scoped to this vault | — |
| `auditLogDestinationId` (blank) | A diagnostic setting on the vault routing `AuditEvent` to a Log Analytics workspace or storage account | — |
| `resourceTags` (empty) | Tags on every resource created here | — |
| `deployAzureOpenAI` (off) | Azure OpenAI account and one model deployment | Azure OpenAI Endpoint, Deployment name |
| `deployCognitiveServices` (off) | One **multi-service** AI Services account | Vision endpoint, Face endpoint, Translator Region |

The two blank-by-default parameters above are the two whose *absence* is silent —
see [Two blanks that mean something](#two-blanks-that-mean-something).

When the Deploy button serves this file **from your own Pinpoint instance**
rather than from GitHub, the `deploy…` checkboxes arrive already ticked for the
capabilities you selected in Pinpoint — otherwise a town that chose Azure for AI
triage and Translation presses Create and gets a vault and nothing else. Default
values are the **only** thing the instance changes: diff what your instance
serves against this file and nothing but `defaultValue` will differ.

The multi-service account is why three cards can share one key: its endpoint
serves both the image-reading path Pinpoint calls for licence plates and the
face-detection path it calls for faces, and the same key authenticates Translator
against the global translator endpoint when the Region box names this account's
region. Azure OpenAI is a different kind of account and cannot be folded in.

## What it does not create

* **The Entra app registration and client secret.** A directory object, outside
  ARM's scope entirely. Where the server runs on Azure, use a managed identity
  instead and there is no credential to create, copy or renew — put its object id
  in `pinpointPrincipalObjectId` and the template grants it the roles.
* **An AI Face resource.** Microsoft gates Face behind a Limited Access review.
  The multi-service account serves the Face endpoint the moment it exists and
  returns 403 until the review clears. That is a provider gate, not a fault here.
* **Email and SMS.** Domain verification needs DNS the town controls.

## Two things it does that cannot be undone

Both are called out in the parameter descriptions, so Azure's own form shows them:

* **Purge protection** is enabled and Azure does not allow it to be disabled. It
  is what stops anyone wiping the vault — and every resident record encrypted
  under it — inside the recovery window.
* A **deployed model** costs money for as long as it exists. Delete the
  deployment, not just the account, if you change your mind.

## Two blanks that mean something

Both parameters are genuinely optional. Neither absence produces a warning, an
error, or anything at all on the deployment summary — the deployment reports
success either way, which is why they are written out here.

* **`pinpointPrincipalObjectId` blank → no permission is granted.** You get a
  vault and a key that Pinpoint cannot use. Encryption then fails at first use,
  not at deploy time. Grant **Key Vault Crypto User** by hand on the vault's
  *Access control (IAM)* blade — plus **Key Vault Secrets Officer** if this vault
  is also Pinpoint's secret store.

  The value is an **Object ID**, from *Entra ID → Enterprise applications → your
  app → Object ID*, or from a managed identity's Overview blade. It is not the
  *Application (client) ID*, which sits beside it on the same page and looks
  identical. It must be a **service principal** — a managed identity or an app
  registration's service principal. A human user's object id is rejected, because
  the role assignments declare `principalType: ServicePrincipal`.

* **`auditLogDestinationId` blank → no key-access audit trail is retained.** Key
  Vault keeps no log of its own. Without a diagnostic setting routing
  `AuditEvent` somewhere, Azure retains nothing about who wrapped or unwrapped
  with the key, and it cannot be reconstructed afterwards. Supply the resource id
  of a Log Analytics workspace or a storage account and the template creates the
  setting; the kind is inferred from the id.

## `principalType` is stated, not inferred

Both role assignments carry `"principalType": "ServicePrincipal"`. Without it ARM
resolves the object id against Entra at deploy time, and a service principal
created minutes earlier — which is exactly this flow, where the operator
registers the app and *then* deploys — may not have replicated yet. The
deployment fails with `PrincipalNotFound`, intermittently: it passes wherever the
principal is old and fails on the first town that follows the steps in order.

## Why the vault is reachable from the internet

`publicNetworkAccess: Enabled` and `networkAcls.defaultAction: Allow` are a
deliberate choice, and a security review will ask.

Pinpoint frequently runs **outside** Azure — the reference deployment is on
Oracle Cloud — so a vault restricted to a virtual network would be unreachable by
the one application it exists to serve, and every resident record would fail to
decrypt. The two AI Services accounts are open for the same reason.

The vault is not open in any meaningful sense. `enableRbacAuthorization` is on,
so reaching it still requires an Azure role assignment **on this vault**; every
call is authenticated against Entra; and the two roles granted here are the whole
of what Pinpoint can do. A network rule is a second lock on a door that is
already locked.

There is no IP-allowlist parameter, on purpose. A firewall rule that omits the
application's real egress address locks a town out of its own resident data with
no error until the first decrypt, and the egress address of a containerised app
behind a NAT gateway is not a value an operator reliably knows at deployment
time. A town that *does* run Pinpoint inside Azure should close the vault
afterwards, deliberately, once it knows what to allow:

```
az keyvault network-rule add --name <vault> --ip-address <cidr>
az keyvault update --name <vault> --default-action Deny
```

## Key rotation: not automatic, and that is the safe answer

No `rotationPolicy` is set, and adding one would be dangerous here rather than
merely unnecessary. Azure only auto-rotates a key that carries an **expiry time**,
and an expired key version refuses `unwrapKey`. Every resident record already
wrapped under an earlier version would become permanently unreadable on the day
that version expired, because Pinpoint has no background job that re-wraps stored
data.

Rotate deliberately instead: create a new key version, then re-wrap what is
stored under it, then retire the old version. Azure retains old versions
indefinitely, so there is no deadline forcing the issue.

(Pinpoint's Google Cloud walkthrough recommends a 90-day rotation because Cloud
KMS decrypts against *any* enabled version automatically, with no expiry
involved. The two are not the same mechanism and the recommendation does not
carry across.)

## The model version floats

`openAiModelVersion` defaults to empty, which means "whatever version this region
currently makes default". A pinned version goes stale: Microsoft retires model
versions region by region, and a retired one fails the deployment outright with
an error about the model not being found. The deployment also carries
`versionUpgradeOption: OnceCurrentVersionExpired`, so a version that is retired
after deployment moves forward rather than breaking. Pin a version only if you
need that exact one, and expect to change it.

## Tags

`resourceTags` is an optional object applied to the vault, the key and both AI
accounts. Empty by default. Municipal subscriptions often carry an Azure Policy
that denies resources without a cost-centre or owner tag; without this parameter
that denial arrives as a deployment failure naming a tag with no way to supply it.

## Preview before applying

```
az deployment group what-if --resource-group <rg> --template-file pinpoint-311.json
```

That diff comes from Azure. Note that role assignments and the key are the parts
`what-if` reasons about least confidently; the resource list is reliable.

## If a name is taken

ARM deployments are incremental. A vault of the same name **in the same resource
group** is updated in place rather than left alone, and a key of the same name
gains a new version. Vault names are also globally unique across Azure, so a name
taken in another tenant fails the deployment outright. The defaults are unique
per resource group for this reason — use a name you have not used before, and
read the names on the form before pressing Create.

## Roles it assigns

Both are Microsoft built-in roles, scoped to the vault and nothing wider. Their
definition ids are parameters rather than hard-coded so they can be corrected
without editing the file; check them against the role list on the vault's Access
control (IAM) if a deployment is rejected for an unknown role definition.

* **Key Vault Crypto User** — wrap and unwrap with the key. Cannot read, export,
  change or delete it.
* **Key Vault Secrets Officer** — only needed if this vault is also Pinpoint's
  secret store. Officer rather than User because Pinpoint writes credentials here
  as well as reading them.
