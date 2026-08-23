# AWS — `pinpoint-311.yaml`

A CloudFormation template. Create it as a **change set** rather than a stack if
you want an authoritative diff first — that diff comes from Amazon.

## What it creates

| Resource | Purpose | Fills these Pinpoint boxes |
| --- | --- | --- |
| KMS key + alias, rotation on | Wraps the key that encrypts resident personal information | AWS Region, Key ID or ARN |
| IAM role + instance profile | The identity Pinpoint signs in as | **none — that is the point** |
| IAM policy on that role | Secrets Manager, Translate, Rekognition, Bedrock — each behind its own toggle | — |

## The best outcome available: no credential at all

The template creates a **role**, not a user, and no access keys. Attach the
instance profile to the EC2 instance running Pinpoint, or name the role as the
task role on ECS, and the application signs in with a token AWS issues minutes at
a time and rotates. Nothing to paste, nothing to leak, nothing to expire.
Pinpoint detects this and greys out the credential boxes.

If Pinpoint does not run on AWS compute, this stack is still the right one:
create an IAM user by hand afterwards and attach the same policy to it.

### Which of the two the trust policy assumes, and the one setting that catches people

Pinpoint asks for credentials in a fixed order and takes the first answer:

1. **ECS task role** — used when `AWS_CONTAINER_CREDENTIALS_RELATIVE_URI` is set
   in the container's environment, which ECS does for you. Name `PinpointRole` in
   the **Task role** field. Not the *task execution* role: that is a different
   field on the same page, it is what pulls the image and writes logs, and naming
   the role there leaves the application with no credentials at all.
2. **EC2 instance profile** — IMDSv2. Attach `PinpointInstanceProfile`.

The trust policy names both `ec2.amazonaws.com` and `ecs-tasks.amazonaws.com`, so
either works without changing anything.

> **If Pinpoint runs in a container on an EC2 instance** — the usual Docker
> Compose deployment — the instance's metadata options need
> `HttpPutResponseHopLimit` of **2 or more**. The default is 1, the hop out of
> the container consumes it, and the application sees no credentials and reports
> the role as missing. That setting belongs to the instance, which this stack
> does not create:
>
> ```
> aws ec2 modify-instance-metadata-options --instance-id <id> \
>     --http-tokens required --http-put-response-hop-limit 2
> ```

## Nothing is silently skipped, but several things fail late

Each `Allow…` toggle set to **No** produces a stack that deploys cleanly and a
Pinpoint card that cannot work, discovered at first use rather than at deploy
time. `AllowBedrock` is the one to watch: it defaults to **No**, and a town that
chose AWS for AI triage needs it at **Yes**. When the template is served from
your own Pinpoint instance rather than from GitHub, the form arrives with the
toggles for the capabilities you actually selected already set — that is the only
thing the instance changes about this file.

## What the role may read in Secrets Manager

`SecretsPrefix` (default `pinpoint/`) scopes the grant. The role may create,
read, write and delete secrets **whose name starts with that prefix** and no
others; `ListSecrets` cannot be scoped by AWS and is granted on its own, and it
returns names, never values. If you have changed `AWS_SECRETS_PREFIX` in
Pinpoint, set the same value here or every credential save will be denied.

## Audit trail — read this before assuming there is one

CloudTrail records KMS **management** events (key created, policy changed, key
scheduled for deletion) in every account by default, and those are enough to
answer "who changed this key".

It does **not** record `Encrypt`, `Decrypt` or `GenerateDataKey`. Those are *data
events*, they are off unless a trail carries a data-event selector for KMS, and
this template does not create one. **Without a trail there is no record of who
used the key or when, and it cannot be reconstructed after the fact.**

To turn it on for an existing trail:

```
aws cloudtrail put-event-selectors --trail-name <trail> \
    --advanced-event-selectors '[{"Name":"KMS data events",
      "FieldSelectors":[{"Field":"eventCategory","Equals":["Data"]},
                        {"Field":"resources.type","Equals":["AWS::KMS::Key"]}]}]'
```

**This costs money per event**, and a busy 311 portal decrypts constantly — every
report page view that shows a resident's name is a decrypt. Price it against the
account's own volume before switching it on estate-wide; scoping the selector to
this one key ARN is usually the right compromise. The template leaves the
decision with the town rather than making it silently either way.

## Network reachability

KMS, Secrets Manager, Translate, Rekognition and Bedrock are all public AWS API
endpoints, reached over the internet and authenticated with SigV4. None has a
network boundary this template could set, and no VPC endpoints are created —
Pinpoint frequently runs outside AWS entirely, so an interface-endpoint-only
posture would make the key unreachable by the application that exists to use it.
What limits access here is the role and the key policy, not the network. A town
running entirely inside a VPC can add interface endpoints and a
`aws:SourceVpce` condition afterwards; doing it here would break everyone else.

## What it does not cover

* **Bedrock model access.** Each model is enabled per account in the Bedrock
  console. The policy grants the call; the enablement is a provider gate.
* **Email and SMS.** SES domain verification needs DNS records only the town can
  publish, and 10DLC phone registration is carrier paperwork measured in weeks.
* **Nothing is needed for Translate or Rekognition** beyond the permissions here.
  Both are API-only; there is no resource to create.

## The one irreversible-feeling choice

`PreventAccidentalKeyDeletion` (default **Yes**) adds a policy statement denying
everyone the ability to schedule the key for deletion or disable it. A KMS key
stops working the moment deletion is *scheduled*, not when the waiting period
ends, so an accident breaks resident data immediately rather than in thirty days.
An explicit deny beats every allow, including the account root. To retire the key
deliberately later, an administrator removes that statement first.

The key also carries `DeletionPolicy: Retain` (and `UpdateReplacePolicy: Retain`).
Deleting the stack leaves the key in place, because deleting a stack should never
be the thing that starts a countdown on every resident record in the database.
Automatic annual rotation is on (`EnableKeyRotation: true`); AWS keeps every
previous backing key, so data wrapped before a rotation still decrypts.

## The key policy, and the lockout it avoids

A KMS key policy is the one document in AWS that can lock an account out of its
own key with no way back — not by the account team, not by AWS support. So:

* **`AccountKeepsAdministrativeControl`** grants `kms:*` to the account root.
  That statement is load-bearing and must not be removed. It is also what lets
  IAM policies in the account grant access to this key at all.
* **`Pinpoint311MayUseTheKey`** grants the application exactly four actions —
  `Encrypt`, `Decrypt`, `GenerateDataKey`, `DescribeKey` — and no
  administrative ones. Pinpoint can use the key; it cannot change who else may,
  create grants, or schedule it for deletion.

If the stack fails with *"MalformedPolicyDocumentException: Policy contains a
statement with one or more invalid principals"*, that is IAM's eventual
consistency, not a wrong template: the key policy names a role created seconds
earlier that has not finished propagating. Re-run the stack.

## If a name is taken

The stack fails and nothing existing is modified. The alias, role and instance
profile are all named resources and CloudFormation refuses to create one that
already exists — which is also what stops a second run quietly creating a second
KMS key you keep paying for.

Updating *this* stack is a different thing and is safe: every logical id is fixed
and nothing is randomly named, so re-running it with changed parameters updates
in place rather than creating a second set. Deploying a *second* stack beside it
collides, deliberately.

## Removing it

Delete the stack: the role, policy, instance profile and alias go with it. The
KMS key is retained, by design. Schedule its deletion deliberately if you mean to
retire it, after removing the deny statement.
