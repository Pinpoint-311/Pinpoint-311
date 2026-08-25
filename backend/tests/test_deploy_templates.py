"""The one-click deployment templates, and the promises made about them.

`deploy/templates/` holds an ARM template and a CloudFormation template that a
town deploys into their own cloud account from a button on the setup page. Two
things about them are load-bearing and neither is visible from reading the setup
copy:

  * they must not emit a key, password or secret as a deployment output. Both
    clouds retain outputs -- Azure in the resource group's deployment history,
    AWS in the stack -- where they are readable by a wider audience than the
    person who deployed. The setup page says which blade each key is copied
    from instead, and that is a deliberate trade rather than an oversight, so it
    needs something to hold it in place.

  * the values they *do* emit are labelled with the names of the boxes on our
    own cards, so a clerk copies across without translating. Those labels come
    from the credential catalogs, which move; an output naming a label that no
    longer exists sends somebody looking for a box that is not there.

Deliberately stdlib-only. CI installs five packages and none of them is a YAML
parser, so the CloudFormation file is checked as text -- which is also how a
reviewer reads it.
"""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "deploy/templates"
ARM = TEMPLATES / "azure/pinpoint-311.json"
CFN = TEMPLATES / "aws/pinpoint-311.yaml"
CONTENT = ROOT / "frontend/src/components/setupStepsContent.tsx"


def _skip_without(path: Path):
    if not path.exists():
        pytest.skip(f"{path.name} not present in this checkout")


def _arm():
    _skip_without(ARM)
    return json.loads(ARM.read_text())


# ---------------------------------------------------------------------------
# Nothing secret comes back out
# ---------------------------------------------------------------------------

def test_the_arm_template_emits_no_secret_as_an_output():
    """`listKeys` is how an ARM template reaches a Cognitive Services or storage
    key, and putting one in an output writes it into deployment history for
    everyone who can read that history -- which is more people than deployed it,
    and more of them every time somebody joins."""
    template = _arm()
    rendered = json.dumps(template["outputs"])
    for forbidden in ("listKeys", "listSecrets", "listAccountSas", "adminPassword"):
        assert forbidden not in rendered, (
            f"the ARM template's outputs call {forbidden}, which puts a secret into "
            "deployment history. Outputs are names and endpoints; the setup page "
            "tells the operator which blade to copy each key from."
        )


def test_the_cloudformation_template_creates_no_access_key():
    """An AWS::IAM::AccessKey would put a long-lived secret in the stack, and the
    whole point of the role this template creates is that there is not one."""
    _skip_without(CFN)
    source = CFN.read_text()
    assert "AWS::IAM::AccessKey" not in source, (
        "the CloudFormation template creates an IAM access key. It creates a role "
        "and an instance profile precisely so that no long-lived credential exists."
    )
    outputs = source.split("\nOutputs:", 1)
    assert len(outputs) == 2, "the CloudFormation template has no Outputs section"
    lowered = outputs[1].lower()
    for forbidden in ("secretaccesskey", "password"):
        assert forbidden not in lowered, f"a secret ({forbidden}) is emitted as a stack output"


# ---------------------------------------------------------------------------
# What they do emit is named the way our boxes are named
# ---------------------------------------------------------------------------

def _catalog_labels():
    """Every credential label our cards render, across the importable catalogs.

    Same tolerance as test_setup_steps_content: CI cannot import all of them, so
    each is tried on its own and the check runs against whatever loaded.
    """
    labels = set()
    sources = [
        ("app.services.ai.registry", "AI_CATALOG"),
        ("app.services.translation_providers", "TRANSLATION_CATALOG"),
        ("app.services.map_provider", "MAP_CATALOG"),
        ("app.services.identity", "IDENTITY_CATALOG"),
    ]
    catalogs = []
    for module, name in sources:
        try:
            catalogs.append(getattr(__import__(module, fromlist=[name]), name))
        except Exception:
            continue
    try:
        from app.services.delivery_providers import _CATALOGS
        catalogs.extend(_CATALOGS.values())
    except Exception:
        pass
    for catalog in catalogs:
        for entry in catalog.values():
            for field in entry.get("credential_fields", []):
                labels.add(field["label"])
    return labels


def _boxes_claimed_in(text: str) -> list:
    """Every label a "Pinpoint box: ..." phrase in this text points a clerk at."""
    claimed = []
    for match in re.findall(r"Pinpoint box(?:es)?:\s*([^.\n']+)", text):
        for label in re.split(r"\s+and\s+|,", match):
            label = label.strip().rstrip(".")
            # Trailing prose after the label, e.g. "- the same value in both".
            label = re.split(r"\s+[-–—]\s+", label)[0].strip()
            if label:
                claimed.append(label)
    return claimed


def test_every_output_that_claims_a_box_names_a_real_one():
    """The outputs say "Pinpoint box: Key Vault URL". If that label stops
    existing -- renamed, or the field dropped -- the template is directing an
    operator at a box that is not on the card, and nothing else would say so.

    Both templates, scanned as they are written rather than through the pinned
    maps below: the maps are a second, deliberate copy, and a label added to a
    template and to the map together would sail past a check that only read the
    map."""
    template = _arm()
    labels = _catalog_labels()
    if not labels:
        pytest.skip("no provider catalog could be imported here")

    claimed = []
    for output in template["outputs"].values():
        claimed.extend(_boxes_claimed_in(output.get("metadata", {}).get("description", "")))
    arm_claims = list(claimed)
    assert arm_claims, "no ARM output claims a Pinpoint box; the labelling convention moved"

    if CFN.exists():
        cfn_claims = _boxes_claimed_in(CFN.read_text())
        assert cfn_claims, (
            "no CloudFormation output claims a Pinpoint box; the labelling convention moved"
        )
        claimed.extend(cfn_claims)

    unknown = [c for c in claimed if c not in labels]
    assert not unknown, (
        f"ARM outputs name boxes that no catalog has: {unknown}. "
        f"Known labels include {sorted(labels)[:8]}..."
    )


# ---------------------------------------------------------------------------
# Least privilege, and scoped to what was created
# ---------------------------------------------------------------------------

def test_arm_role_assignments_say_what_kind_of_principal_they_are_granting_to():
    """Without `principalType`, ARM looks the object id up in Entra, and a
    service principal created minutes earlier -- which is this exact flow, where
    the operator registers the app and then deploys -- may not have replicated.
    The deployment then fails with PrincipalNotFound, intermittently: it passes
    wherever the principal is old and fails on the first town that follows the
    steps in order. Stating it removes the lookup."""
    template = _arm()
    assignments = [r for r in template["resources"]
                   if r["type"] == "Microsoft.Authorization/roleAssignments"]
    assert assignments, "the ARM template grants nothing; the vault would be unusable"
    for assignment in assignments:
        assert assignment["properties"].get("principalType") == "ServicePrincipal", (
            f"role assignment {assignment['name']} does not declare "
            "principalType ServicePrincipal, so ARM will resolve the principal against "
            "Entra and may fail on replication lag"
        )


def test_the_optional_principal_says_what_leaving_it_blank_costs():
    """Azure's form shows the parameter description and nothing else. Blank is a
    legitimate answer, but the consequence -- a vault and a key Pinpoint has no
    permission to use, reported as a successful deployment -- is invisible unless
    the description says it. The same description is also the only place the
    operator is told which of the two near-identical ids on the Entra page to
    copy, and that a user object id will now be rejected."""
    description = _arm()["parameters"]["pinpointPrincipalObjectId"]["metadata"]["description"]
    lowered = description.lower()
    for fragment in ("blank", "by hand", "access control", "crypto user"):
        assert fragment in lowered, (
            f"the pinpointPrincipalObjectId description no longer says {fragment!r}: "
            "an operator leaving it empty is not told what they must do afterwards"
        )
    assert "object id" in lowered and "client) id" in lowered, (
        "the description no longer distinguishes the object id from the application "
        "(client) id, which are adjacent and identical-looking on the same Entra page"
    )
    assert "serviceprincipal" in lowered.replace(" ", ""), (
        "the description does not warn that a user object id is now rejected, which is "
        "the behaviour change principalType introduces"
    )


def test_the_vault_audit_log_is_offered_and_only_created_when_asked_for():
    """Key Vault retains nothing about key access on its own. A diagnostic
    setting is the whole of the audit trail our setup copy implies, and it has to
    be conditional because it can only point at a destination that already
    exists."""
    template = _arm()
    parameter = template["parameters"]["auditLogDestinationId"]
    assert parameter["defaultValue"] == "", "the audit destination is no longer optional"
    lowered = parameter["metadata"]["description"].lower()
    assert "audit" in lowered and ("no key-access" in lowered or "retains no" in lowered), (
        "the auditLogDestinationId description no longer states that leaving it empty "
        "means no key-access audit trail is retained"
    )

    settings = [r for r in template["resources"]
                if r["type"] == "Microsoft.Insights/diagnosticSettings"]
    assert len(settings) == 1, "the vault's diagnostic setting is missing"
    setting = settings[0]
    assert setting.get("condition"), (
        "the diagnostic setting is unconditional, so a deployment with no destination "
        "would fail on a resource that cannot be created"
    )
    # The condition may go through a variable; follow it to the parameter.
    resolved = setting["condition"]
    for name, expression in template.get("variables", {}).items():
        if f"variables('{name}')" in resolved and isinstance(expression, str):
            resolved += " " + expression
    assert "auditLogDestinationId" in resolved, (
        "the diagnostic setting is not conditional on a destination being supplied"
    )
    assert "Microsoft.KeyVault/vaults/" in setting.get("scope", ""), (
        "the diagnostic setting is not scoped to the vault"
    )
    categories = [entry["category"] for entry in setting["properties"]["logs"]]
    assert "AuditEvent" in categories, (
        "the diagnostic setting routes no AuditEvent category, which is the one that "
        "records who used the key"
    )


def test_the_vault_says_why_it_is_reachable_from_the_internet():
    """Deliberate, and a government security review will ask. `publicNetwork-
    Access: Enabled` because Pinpoint commonly runs outside Azure -- a vault
    behind a virtual network would be unreachable by the application it exists to
    serve. "It is the default" is not an answer; the file has to carry the
    reasoning where a reviewer reads it."""
    template = _arm()
    vault = next(r for r in template["resources"] if r["type"] == "Microsoft.KeyVault/vaults")
    assert vault["properties"]["publicNetworkAccess"] == "Enabled", (
        "the vault's network access changed; if that is deliberate this test and the "
        "README paragraph explaining the old choice both need rewriting"
    )
    comments = vault.get("comments", "").lower()
    assert "publicnetworkaccess" in comments.replace(" ", ""), (
        "the vault no longer explains its network posture in the template itself"
    )
    assert "outside azure" in comments or "oracle" in comments, (
        "the vault's comment no longer gives the reason -- Pinpoint usually runs outside "
        "Azure -- which is the whole of the justification"
    )

    readme = (TEMPLATES / "azure/README.md").read_text().lower()
    assert "publicnetworkaccess" in readme.replace(" ", "") or "reachable from the internet" in readme, (
        "the Azure README does not document why the vault is reachable from the internet"
    )


def test_arm_role_assignments_are_scoped_to_the_vault():
    """A role assignment with no `scope` lands on the resource group, which is
    the difference between an identity that can use one key and one that can use
    everything the town ever puts beside it."""
    template = _arm()
    assignments = [r for r in template["resources"]
                   if r["type"] == "Microsoft.Authorization/roleAssignments"]
    assert assignments, "the ARM template grants nothing; the vault would be unusable"
    for assignment in assignments:
        scope = assignment.get("scope", "")
        assert "Microsoft.KeyVault/vaults/" in scope, (
            f"role assignment {assignment['name']} is scoped to {scope or 'the resource group'} "
            "rather than to the vault"
        )


def test_the_kms_key_survives_stack_deletion():
    """Deleting a stack must never be the thing that starts a deletion countdown
    on every resident record in the database."""
    _skip_without(CFN)
    source = CFN.read_text()
    key = source.split("  PiiKey:", 1)
    assert len(key) == 2, "the KMS key resource was renamed; re-point this test"
    head = key[1][:400]
    assert "DeletionPolicy: Retain" in head, "the encryption key is not retained on stack deletion"


# ---------------------------------------------------------------------------
# The buttons and the files agree
# ---------------------------------------------------------------------------

def test_the_deploy_buttons_point_at_templates_that_exist():
    """Both button URLs are built by one module from one base. A path typo
    there produces a button that opens the provider's console with a fetch
    failure, which reads as the cloud being broken rather than as our link."""
    urls = ROOT / "frontend/src/components/deployTemplateUrls.ts"
    if not urls.exists():
        pytest.skip("frontend not present in this checkout")
    source = urls.read_text()

    paths = re.findall(r"\$\{base\}(/[A-Za-z0-9._/-]+)", source)
    assert paths, "no template path is built from the base URL"
    for path in paths:
        assert (TEMPLATES / path.lstrip("/")).exists(), (
            f"a deploy button points at deploy/templates{path}, which is not in the repository"
        )
    # And what the buttons ask for is what the route agrees to serve. These are
    # two lists in two languages; a template added to one and not the other is
    # a button that opens a console with nothing in it.
    served = set(_route_module().TEMPLATE_FILES)
    assert {p.lstrip("/") for p in paths} == served, (
        f"the buttons ask for {sorted(p.lstrip('/') for p in paths)} and the route serves "
        f"{sorted(served)}"
    )


def test_each_template_directory_explains_itself():
    """A town's IT reviewer opens the directory before the file. A template with
    no README is a file to be reverse-engineered."""
    if not TEMPLATES.exists():
        pytest.skip("deploy/templates not present in this checkout")
    for readme in (TEMPLATES / "README.md",
                   TEMPLATES / "azure/README.md",
                   TEMPLATES / "aws/README.md"):
        assert readme.exists(), f"{readme.relative_to(ROOT)} is missing"


# ---------------------------------------------------------------------------
# Served from the town's own instance
#
# The buttons used to hand Azure and AWS a raw.githubusercontent.com URL. That
# works right up until it does not, and the three ways it fails are all silent:
# a town on an older build is handed today's `main`; a renamed, private or
# unreachable repository breaks every town at once; and a fork is handed our
# templates rather than its own. The route below is what makes the file travel
# with the build that knows how to consume it.
# ---------------------------------------------------------------------------

def _route_module():
    pytest.importorskip("fastapi.routing")
    from app.api import deploy_templates
    return deploy_templates


def _fetch(path: str):
    """Call the route the way the app would, without a test client.

    Deliberately not starlette's TestClient: it needs an httpx whose version
    agrees with starlette's, and this file has to keep running in CI -- which
    installs five packages -- and inside the production image, which pins a
    different httpx than pip resolves. The route is one async function taking
    two strings; calling it is the same coverage with none of that.

    Returns the Response, or the HTTPException for a refusal.
    """
    import asyncio

    from fastapi import HTTPException

    cloud, _, filename = path.partition("/")
    try:
        return asyncio.run(_route_module().get_deploy_template(cloud, filename))
    except HTTPException as exc:
        return exc


def _status(result) -> int:
    return getattr(result, "status_code", None)


def test_the_route_serves_both_templates_with_the_content_type_each_cloud_expects():
    """Not decoration. Azure's portal parses the response as JSON and
    CloudFormation sniffs YAML; a file served as text/html or as
    application/octet-stream is a template the provider declines to render, and
    it reports that as our template being malformed."""
    if not _route_module().templates_are_servable():
        pytest.skip("deploy/templates not resolvable from this checkout")

    response = _fetch("azure/pinpoint-311.json")
    assert _status(response) == 200
    assert response.headers["content-type"].startswith("application/json")
    assert json.loads(response.body)["parameters"], "the served ARM template is not the template"

    response = _fetch("aws/pinpoint-311.yaml")
    assert _status(response) == 200
    assert "yaml" in response.headers["content-type"]
    assert b"AWSTemplateFormatVersion" in response.body


def test_the_served_template_is_readable_cross_origin():
    """The Azure portal fetches the template with an XHR from portal.azure.com.
    The app's CORS middleware allows the town's own origins and nothing else,
    which is right for every other route and would leave this one rendering an
    empty deployment form with the failure visible only in a browser console."""
    if not _route_module().templates_are_servable():
        pytest.skip("deploy/templates not resolvable from this checkout")
    response = _fetch("azure/pinpoint-311.json")
    assert response.headers.get("access-control-allow-origin") == "*"


def test_the_route_serves_nothing_but_the_two_templates():
    """It takes two path segments and joins them. An allowlist is what keeps
    that from being a file reader pointed at the container."""
    for path in ("azure/../../.env", "aws/pinpoint-311.json", "azure/README.md", "azure/.env"):
        assert _status(_fetch(path)) == 404, f"{path} was served"


def test_a_build_without_the_files_forwards_rather_than_404s(monkeypatch):
    """A managed tenancy runs the image with no repository mounted, so this
    route can genuinely have nothing to serve. The button still points here --
    that is the point of it pointing here -- so the answer has to be the
    template, not "not found" rendered inside Azure's portal as a broken
    template. One visible hop to the published copy is the worse-but-working
    answer; a 404 is the failure this route was written to remove."""
    module = _route_module()
    monkeypatch.setattr(module, "_candidate_roots", lambda: [Path("/nonexistent-deploy-templates")])
    response = _fetch("azure/pinpoint-311.json")
    assert _status(response) == 302
    assert response.headers["location"] == (
        "https://raw.githubusercontent.com/Pinpoint-311/Pinpoint-311/main/deploy/templates"
        "/azure/pinpoint-311.json"
    )


def test_the_frontend_and_the_route_agree_on_the_path():
    """Two files name this path -- the router prefix in main.py and
    INSTANCE_TEMPLATE_PATH in the frontend. They are edited months apart."""
    main = ROOT / "backend/app/main.py"
    urls = ROOT / "frontend/src/components/deployTemplateUrls.ts"
    if not (main.exists() and urls.exists()):
        pytest.skip("not a full checkout")
    assert 'prefix="/api/deploy-templates"' in main.read_text(), "the route moved"
    assert "INSTANCE_TEMPLATE_PATH = '/api/deploy-templates'" in urls.read_text(), (
        "the frontend builds a different path than the backend serves"
    )


def test_the_fallback_url_is_the_same_one_in_both_halves():
    """Backend redirect and frontend fallback both name the published copy."""
    urls = ROOT / "frontend/src/components/deployTemplateUrls.ts"
    if not urls.exists():
        pytest.skip("frontend not present in this checkout")
    assert _route_module().PUBLISHED_BASE_URL in urls.read_text(), (
        "the backend's redirect target and the frontend's fallback have drifted apart"
    )


# ---------------------------------------------------------------------------
# Every output lands in a box, and the boxes are pinned
# ---------------------------------------------------------------------------

# What each template output is for, by the exact label of the card field it is
# copied into. Written out rather than derived, because the failure being
# guarded is a *rename* -- an output quietly renamed, or a field label reworded,
# leaves a clerk hunting the card for a box that is no longer called that, and
# every derived check would follow the rename and stay green.
ARM_OUTPUT_TO_BOX = {
    "keyVaultUrl": ["Key Vault URL"],
    "keyName": ["Key name"],
    "directoryTenantId": ["Directory (tenant) ID"],
    "azureOpenAiEndpoint": ["Azure OpenAI Endpoint"],
    "azureOpenAiDeploymentName": ["Deployment name"],
    "aiServicesEndpoint": ["Vision endpoint", "Face endpoint"],
    "translatorRegion": ["Region"],
}

CFN_OUTPUT_TO_BOX = {
    "PinpointBoxAwsRegion": ["AWS Region"],
    "PinpointBoxKeyIdOrArn": ["Key ID or ARN"],
}


def test_the_arm_outputs_are_the_ones_the_cards_ask_for():
    """A pin, in both directions: an output that disappears or is renamed fails
    here, and so does one added without deciding which box it fills."""
    template = _arm()
    emitted = {name for name in template["outputs"] if name != "readMeFirst"}
    assert emitted == set(ARM_OUTPUT_TO_BOX), (
        "the ARM template's outputs changed. Added: "
        f"{sorted(emitted - set(ARM_OUTPUT_TO_BOX))}; removed: "
        f"{sorted(set(ARM_OUTPUT_TO_BOX) - emitted)}. Each output must name the card "
        "field it is copied into, here and in its own description."
    )
    for name, boxes in ARM_OUTPUT_TO_BOX.items():
        description = template["outputs"][name].get("metadata", {}).get("description", "")
        for box in boxes:
            assert box in description, (
                f"ARM output {name} no longer tells the operator it goes in the {box!r} box"
            )


def test_the_cloudformation_outputs_are_the_ones_the_cards_ask_for():
    _skip_without(CFN)
    source = CFN.read_text()
    tail = source.split("\nOutputs:", 1)[1]
    emitted = set(re.findall(r"^  ([A-Za-z0-9]+):$", tail, re.M))
    named = set(CFN_OUTPUT_TO_BOX)
    # ReadMeFirst and the three for-your-records outputs are not card fields.
    informational = {"ReadMeFirst", "KeyArn", "RoleArnToAttach", "InstanceProfileName"}
    assert emitted - informational == named, (
        "the CloudFormation outputs changed. Added: "
        f"{sorted(emitted - informational - named)}; removed: {sorted(named - emitted)}"
    )
    for name, boxes in CFN_OUTPUT_TO_BOX.items():
        block = tail.split(f"\n  {name}:", 1)[1][:300]
        for box in boxes:
            assert f"Pinpoint box: {box}" in block, (
                f"CloudFormation output {name} no longer names the {box!r} box"
            )


def test_every_box_a_template_names_is_a_real_field_in_a_real_catalog():
    """The other half of the pin. The label check above is textual; this one
    resolves each label against the catalogs the cards are actually drawn from,
    so a field renamed in Python fails here even though both templates still
    agree with each other."""
    labels = _catalog_labels()
    if not labels:
        pytest.skip("no provider catalog could be imported here")
    claimed = set()
    for boxes in ARM_OUTPUT_TO_BOX.values():
        claimed.update(boxes)
    for boxes in CFN_OUTPUT_TO_BOX.values():
        claimed.update(boxes)
    missing = sorted(box for box in claimed if box not in labels)
    assert not missing, (
        f"the templates emit values for boxes no catalog has: {missing}. A clerk with the "
        "deployment output in front of them would be looking for a field that is not there."
    )


# ---------------------------------------------------------------------------
# AWS, on its own terms
# ---------------------------------------------------------------------------

def _cfn() -> str:
    _skip_without(CFN)
    return CFN.read_text()


def test_the_kms_key_policy_cannot_lock_the_account_out_of_its_own_key():
    """The one mistake in AWS that nobody can repair afterwards -- not the
    account team, not AWS support. The root statement is what keeps the key
    administrable, and it is also what lets an IAM policy in the account grant
    access to it at all."""
    source = _cfn()
    policy = source.split("      KeyPolicy:", 1)
    assert len(policy) == 2, "the KMS key policy was restructured; re-point this test"
    body = policy[1].split("\n  PiiKeyAlias:", 1)[0]

    assert "iam::${AWS::AccountId}:root" in body and "Action: 'kms:*'" in body, (
        "the account root no longer holds kms:* on this key. A KMS key whose policy "
        "locks out the account that owns it cannot be repaired by anybody."
    )
    grant = body.split("Sid: Pinpoint311MayUseTheKey", 1)
    assert len(grant) == 2, "Pinpoint's grant on the key was renamed"
    grant = grant[1].split("- !If", 1)[0]
    assert "kms:Encrypt" in grant and "kms:Decrypt" in grant and "kms:GenerateDataKey" in grant, (
        "Pinpoint's grant no longer covers the three actions it needs"
    )
    for administrative in ("kms:*", "kms:PutKeyPolicy", "kms:ScheduleKeyDeletion",
                           "kms:CreateGrant", "kms:Delete"):
        assert administrative not in grant, (
            f"Pinpoint's grant on the key now includes {administrative}, which is key "
            "administration rather than key use"
        )


def test_the_key_is_retained_rotated_and_hard_to_delete_by_accident():
    """Three claims the README makes about this key. Each is one line in the
    file and each would be silently untrue if the line were dropped."""
    source = _cfn()
    key = source.split("  PiiKey:", 1)[1].split("\n  PiiKeyAlias:", 1)[0]
    assert "DeletionPolicy: Retain" in key
    assert "UpdateReplacePolicy: Retain" in key
    assert "EnableKeyRotation: true" in key, "automatic key rotation is off"
    assert "Sid: NobodyMayStartDeletingThisKey" in key, (
        "PreventAccidentalKeyDeletion no longer adds a deny statement, which the README "
        "and the parameter description both promise it does"
    )
    assert "kms:ScheduleKeyDeletion" in key and "kms:DisableKey" in key


def test_the_role_can_be_assumed_by_both_ways_pinpoint_actually_signs_in():
    """The application probes the ECS container credentials endpoint and then
    EC2 IMDSv2. A trust policy naming only one of those leaves whichever the town
    used unable to assume the role at all, and the failure reads as bad
    credentials rather than as a missing trust relationship."""
    source = _cfn()
    trust = source.split("      AssumeRolePolicyDocument:", 1)
    assert len(trust) == 2, "the role's trust policy was restructured"
    body = trust[1].split("\n  PinpointInstanceProfile:", 1)[0]
    assert "ec2.amazonaws.com" in body, "the instance-profile path cannot assume this role"
    assert "ecs-tasks.amazonaws.com" in body, "the ECS task-role path cannot assume this role"
    assert "sts:AssumeRole" in body

    # And the template says which arrangement it assumes, in the place a reader
    # of the file will see it.
    lowered = source.lower()
    assert "imds" in lowered, (
        "the template no longer mentions IMDS, so nothing tells an operator running "
        "Pinpoint in a container on EC2 that the default metadata hop limit of 1 stops "
        "the application seeing any credentials"
    )
    assert "task role" in lowered, (
        "the template no longer says to use the ECS *task* role rather than the task "
        "execution role, which is the adjacent field that silently does not work"
    )


def test_secrets_manager_access_is_scoped_to_pinpoints_own_secrets():
    """`Resource: '*'` on GetSecretValue lets a 311 portal read every secret in
    the account, including ones belonging to systems it has nothing to do with.
    Scoped to the prefix Pinpoint names its own under; ListSecrets is the one
    action AWS refuses to let a policy scope, so it stands alone."""
    source = _cfn()
    assert "SecretsPrefix" in source.split("Parameters:", 1)[1].split("Conditions:", 1)[0], (
        "the secrets prefix is no longer a parameter, so the grant cannot be scoped"
    )
    block = source.split("Sid: KeepTownCredentialsInSecretsManager", 1)
    assert len(block) == 2, "the Secrets Manager grant was renamed"
    block = block[1].split("- !If", 1)[0]
    assert "secretsmanager:GetSecretValue" in block
    assert "${SecretsPrefix}*" in block, (
        "the Secrets Manager grant is no longer scoped to Pinpoint's own secret names"
    )
    assert "Resource: '*'" not in block, (
        "the Secrets Manager grant is account-wide again"
    )
    assert "Sid: ListSecretNames" in source, (
        "ListSecrets was folded back into the scoped statement; AWS rejects a policy "
        "that scopes it, so the whole statement stops working"
    )


def test_the_aws_toggles_say_what_leaving_them_off_costs():
    """Every one of these produces a stack that deploys cleanly and a card that
    cannot work, discovered at first use. AllowBedrock is the one that matters
    most: it is off by default, and a town that chose AWS for AI triage needs it
    on."""
    source = _cfn()
    parameters = source.split("Parameters:", 1)[1].split("\nConditions:", 1)[0]
    for name, fragments in (
        ("AllowBedrock", ("ai triage", "never work")),
        ("AllowTranslate", ("access-denied", "reports success")),
        ("AllowRekognition", ("still succeeds", "photo screening")),
        ("AllowSecretsManager", ("fail",)),
    ):
        block = parameters.split(f"\n  {name}:", 1)[1].split("\n\n", 1)[0].lower()
        for fragment in fragments:
            assert fragment in block, (
                f"the {name} description no longer says what choosing No costs "
                f"(looking for {fragment!r})"
            )


def test_the_aws_readme_is_honest_about_the_key_usage_audit_trail():
    """CloudTrail records KMS management events everywhere by default and data
    events nowhere. Our setup copy implies an access trail; if the template does
    not create one, the README has to say so and say what it costs to add."""
    _skip_without(CFN)
    readme = (TEMPLATES / "aws/README.md").read_text().lower()
    assert "data event" in readme, "the README does not distinguish data events from management events"
    assert "cloudtrail" in readme
    assert "per event" in readme or "charged" in readme, (
        "the README recommends turning on data events without saying they are charged "
        "per event, which for a portal that decrypts on every page view is the whole "
        "of the decision"
    )
    assert "put-event-selectors" in readme, "the README says what is missing but not how to add it"


def test_the_aws_readme_documents_the_network_posture_rather_than_implying_it():
    readme = (TEMPLATES / "aws/README.md").read_text().lower()
    assert "vpc endpoint" in readme, (
        "the README does not say whether VPC endpoints are created, so the reachability "
        "posture of the key is left to be inferred"
    )
    assert "sigv4" in readme or "public aws api" in readme


def test_the_aws_stack_still_creates_no_long_lived_credential():
    """Restated beside the changes above, because the scoped Secrets Manager
    grant and the audit wording are the kind of edit that reaches for an access
    key when something does not work."""
    source = _cfn()
    assert "AWS::IAM::AccessKey" not in source
    assert "AWS::IAM::User" not in source


def test_the_aws_key_card_asks_for_nothing_the_stack_refuses_to_create():
    """The CloudFormation template deliberately creates a role and no access
    key, and the card has to agree: a required Access Key ID box beside a
    template that creates none is an unfinishable card."""
    try:
        from app.services.delivery_providers import KMS_CATALOG
    except Exception:
        pytest.skip("the KMS catalog could not be imported here")
    fields = KMS_CATALOG["aws"]["credential_fields"]
    required = {f["key"] for f in fields if f.get("required")}
    assert required == {"AWS_REGION", "AWS_KMS_KEY_ID"}, (
        f"the AWS encryption card now requires {sorted(required)}. The stack emits only the "
        "region and the key id, and creates no credential at all -- anything else here is a "
        "box the one-click path cannot fill."
    )
    for field in fields:
        assert "AWS_ACCESS_KEY" not in field["key"] and "AWS_SECRET_ACCESS_KEY" != field["key"], (
            "the AWS encryption card offers an access-key box. The whole point of the instance "
            "profile the template creates is that there is no long-lived credential to paste."
        )


# ---------------------------------------------------------------------------
# The served copy differs from the published one in default values, and in
# nothing else at all
#
# The setup card said "Microsoft Azure -- Key management, AI triage,
# Translation" and Azure's form arrived with `deployAzureOpenAI: false` and
# `deployCognitiveServices: false`, because those are the repository's defaults
# and the repository does not know which town is asking. Pressing Create then
# produced a vault and no AI resources, and the two cards the operator came for
# stayed empty with nothing saying why.
#
# Flipping the on-disk defaults is not the fix -- it would create billable
# resources in the account of every town that did not ask. Rewriting them on the
# way out is, and the whole safety of that rests on it being *only* defaults: a
# reviewer diffing what their instance serves against the published file has to
# be able to see, at a glance, that nothing else moved.
# ---------------------------------------------------------------------------

def test_only_default_values_may_differ_between_the_served_and_published_arm_template():
    module = _route_module()
    on_disk = ARM.read_text()
    for selected in (
        {},
        {"kms": "azure", "ai": "azure", "translation": "azure", "redaction": "azure"},
        {"ai": "azure"},
        {"redaction": "azure"},
        {"kms": "google", "ai": "vertex"},
    ):
        served = module.apply_selected_defaults(
            "azure/pinpoint-311.json", on_disk.encode(), selected
        ).decode()
        assert module._arm_without_defaults(json.loads(served)) == \
            module._arm_without_defaults(json.loads(on_disk)), (
                f"serving the ARM template with {selected} changed something other than a "
                "default value"
            )
        # Textually too: same file, same line count, same lines but for defaults.
        served_lines = [l for l in served.splitlines() if '"defaultValue"' not in l]
        disk_lines = [l for l in on_disk.splitlines() if '"defaultValue"' not in l]
        assert served_lines == disk_lines, "the served ARM template was reformatted"


def test_only_default_values_may_differ_between_the_served_and_published_cfn_template():
    _skip_without(CFN)
    module = _route_module()
    on_disk = CFN.read_text()
    for selected in (
        {},
        {"ai": "bedrock", "translation": "aws", "redaction": "aws", "secrets": "aws"},
        {"ai": "bedrock"},
        {"ai": "azure"},
    ):
        served = module.apply_selected_defaults(
            "aws/pinpoint-311.yaml", on_disk.encode(), selected
        ).decode()
        served_lines = [l for l in served.splitlines() if not l.startswith("    Default:")]
        disk_lines = [l for l in on_disk.splitlines() if not l.startswith("    Default:")]
        assert served_lines == disk_lines, (
            f"serving the CloudFormation template with {selected} changed something other "
            "than a Default: line"
        )
        # Every Default: line still parses as one, in the same place.
        served_defaults = [(i, l) for i, l in enumerate(served.splitlines())
                           if l.startswith("    Default:")]
        disk_defaults = [(i, l) for i, l in enumerate(on_disk.splitlines())
                         if l.startswith("    Default:")]
        assert [i for i, _ in served_defaults] == [i for i, _ in disk_defaults], (
            "a Default: line moved, was added or was removed"
        )


def test_the_served_defaults_follow_the_towns_own_selections():
    """The bug this exists for: the card said Azure would do AI triage and
    translation, and the form arrived with both switched off."""
    module = _route_module()
    on_disk = ARM.read_text()

    served = json.loads(module.apply_selected_defaults(
        "azure/pinpoint-311.json",
        on_disk.encode(),
        {"kms": "azure", "ai": "azure", "translation": "azure"},
    ))
    defaults = {name: p.get("defaultValue") for name, p in served["parameters"].items()}
    assert defaults["deployKeyVault"] is True
    assert defaults["deployAzureOpenAI"] is True, (
        "a town that selected Azure for AI triage still gets a form with the OpenAI "
        "account switched off"
    )
    assert defaults["deployCognitiveServices"] is True, (
        "a town that selected Azure for translation still gets a form with the AI "
        "Services account switched off"
    )

    # Photo screening alone is enough for the multi-service account: one account
    # serves Vision, Face and Translator.
    served = json.loads(module.apply_selected_defaults(
        "azure/pinpoint-311.json", on_disk.encode(), {"redaction": "azure"}
    ))
    assert served["parameters"]["deployCognitiveServices"]["defaultValue"] is True

    if CFN.exists():
        served = module.apply_selected_defaults(
            "aws/pinpoint-311.yaml", CFN.read_text().encode(), {"ai": "bedrock"}
        ).decode()
        block = served.split("\n  AllowBedrock:", 1)[1][:200]
        assert "Default: 'Yes'" in block, (
            "a town that selected AWS for AI triage still gets a stack with no Bedrock "
            "permission at all"
        )


def test_an_unreadable_or_absent_selection_leaves_the_published_defaults_alone():
    """Conservative is the right failure. An instance that cannot tell what the
    town chose must serve the repository's defaults rather than guess, because
    guessing wrong creates billable resources in somebody else's account."""
    module = _route_module()
    for relative, path in (("azure/pinpoint-311.json", ARM), ("aws/pinpoint-311.yaml", CFN)):
        if not path.exists():
            continue
        body = path.read_bytes()
        assert module.apply_selected_defaults(relative, body, {}) == body
        assert module.apply_selected_defaults(relative, body, {"ai": "somethingelse"}) == body


def test_a_default_is_never_turned_off_on_the_way_out():
    """Only ever off-to-on. "Not selected" and "not selected *yet*" are the same
    reading from here, and the operator deploying a key vault has usually not
    finished choosing Azure inside Pinpoint at the moment they press the button.
    Serving them `deployKeyVault: false` would produce no vault at all, which is
    a worse failure than the extra resource this rewrite exists to avoid."""
    module = _route_module()
    served = json.loads(module.apply_selected_defaults(
        "azure/pinpoint-311.json", ARM.read_bytes(), {"kms": "google", "ai": "vertex"}
    ))
    assert served["parameters"]["deployKeyVault"]["defaultValue"] is True, (
        "an on-by-default toggle was switched off because the town's current selection "
        "names another cloud"
    )
    assert all(value is not False or name != "deployKeyVault"
               for name, value in
               [(n, p.get("defaultValue")) for n, p in served["parameters"].items()])


def test_the_route_only_ever_adjusts_defaults_and_says_so():
    """The hard constraint, stated where the next person to edit this route will
    read it. A docstring is not a mechanism, but the two tests above are, and
    this is what points at them."""
    doc = (_route_module().get_deploy_template.__doc__ or "").lower()
    assert "defaultvalue" in doc and "default:" in doc, (
        "the route's docstring no longer names the two fields it is allowed to touch"
    )
    assert "nothing else" in doc or "only" in doc


def test_every_generated_name_fits_the_ceiling_it_declares():
    """A default that cannot satisfy its own maxLength, which is a deployment
    that fails on the form's own validator before a single resource is made.

    `vaultName` shipped as `concat('pinpoint311-kv-', uniqueString(...))`
    against `maxLength: 24`. `uniqueString()` returns thirteen characters,
    always -- it is a fixed-length hash, not a variable one -- so the literal
    part has an eleven-character budget and that one spent fifteen. Every
    deployment run with the defaults died on:

        The provided value for the template parameter 'vaultName' is not valid.
        Length of the value should be less than or equal to '24'.

    The constraint was right and the default ignored it, which is the failure a
    reviewer is least likely to catch by reading: both halves look correct on
    their own, and only the arithmetic between them is wrong.

    Asserted for every parameter rather than for the one that broke, because
    the next generated name will be written by copying one of these.
    """
    template = json.loads(ARM.read_text())
    UNIQUE_STRING_LENGTH = 13

    for name, spec in template["parameters"].items():
        default = spec.get("defaultValue")
        ceiling = spec.get("maxLength")
        if not isinstance(default, str) or "uniqueString(" not in default:
            continue
        assert ceiling, (
            f"{name} generates its default with uniqueString() but declares no "
            f"maxLength, so nothing checks that what it generates can be used"
        )
        literals = re.findall(r"'([^']*)'", default)
        worst = sum(len(part) for part in literals) + UNIQUE_STRING_LENGTH
        assert worst <= ceiling, (
            f"{name}'s default is {worst} characters against a maxLength of "
            f"{ceiling}: {default}. uniqueString() is always "
            f"{UNIQUE_STRING_LENGTH}, so the literal text may be at most "
            f"{ceiling - UNIQUE_STRING_LENGTH}."
        )


def test_the_chosen_cloud_reaches_the_template_before_any_card_is_saved():
    """The guide's answer lives in the browser; the link has to carry it.

    The setup guide tells the reader that choosing a cloud moves AI triage,
    translation, key management and photo screening together. It then served a
    template with AI and translation switched off, because the toggles are
    derived from the SERVER's stored providers and the guide's answer had not
    reached the server -- it does not, until a card is saved. The reader saw a
    form contradicting the sentence they had just read.
    """
    module = _route_module()
    served = json.loads(module.apply_selected_defaults(
        "azure/pinpoint-311.json", ARM.read_bytes(),
        {"kms": "google", "ai": "vertex", "translation": "google"},
        "azure",
    ))
    for toggle in ("deployKeyVault", "deployAzureOpenAI", "deployCognitiveServices"):
        assert served["parameters"][toggle]["defaultValue"] is True, (
            f"{toggle} is off for a reader who has just chosen Azure in the guide"
        )


def test_the_hint_can_only_turn_things_on():
    """One direction, like the stored-provider rule it sits beside.

    A query string must not be able to take a key vault OUT of somebody's
    deployment. Asked for AWS against the Azure template, the hint matches
    nothing and the stored selection decides on its own.
    """
    module = _route_module()
    served = json.loads(module.apply_selected_defaults(
        "azure/pinpoint-311.json", ARM.read_bytes(),
        {"kms": "azure"}, "aws",
    ))
    assert served["parameters"]["deployKeyVault"]["defaultValue"] is True
    assert served["parameters"]["deployAzureOpenAI"]["defaultValue"] is False


def test_every_key_bearing_resource_can_be_locked_to_the_server():
    """A leaked credential should be worthless off the town's own address.

    This is the guardrail the 17 and 23 August translation charges did not have:
    keys that worked from anywhere, so a copy taken from anywhere could spend.
    One optional parameter locks the vault and both AI accounts at once -- and it
    has to be all of them, since a locked vault beside an open OpenAI account
    just moves which key is worth stealing.
    """
    template = json.loads(ARM.read_text())
    assert "allowedIpAddress" in template["parameters"]

    lockable = [
        r for r in template["resources"]
        if r["type"] in ("Microsoft.KeyVault/vaults",
                         "Microsoft.CognitiveServices/accounts")
    ]
    assert lockable, "no key-bearing resources found; this test needs rewriting"
    for r in lockable:
        acls = json.dumps(r["properties"].get("networkAcls"))
        assert "lockToServerIp" in acls, (
            f"{r['type']} ignores allowedIpAddress, so its key still works from "
            f"anywhere while the others do not"
        )


def test_leaving_the_address_blank_changes_nothing():
    """Optional means optional. A town that cannot pin an address must still get
    a working deployment, not a locked-out one."""
    template = json.loads(ARM.read_text())
    assert template["parameters"]["allowedIpAddress"]["defaultValue"] == ""
    # The open branch of each conditional has to be a real, permissive value --
    # not null, which Key Vault reads as "deny".
    assert template["variables"]["vaultNetworkAclsOpen"]["defaultAction"] == "Allow"


def test_a_budget_is_offered_on_both_clouds():
    """Neither cloud caps spend, so the only defence is being told early.

    Both are opt-in and both require an address: a budget with nowhere to send
    its alerts is decoration.
    """
    template = json.loads(ARM.read_text())
    assert "monthlyBudgetUsd" in template["parameters"]
    budgets = [r for r in template["resources"]
               if r["type"] == "Microsoft.Consumption/budgets"]
    assert len(budgets) == 1
    assert "budgetAlertEmail" in budgets[0]["condition"], (
        "the budget is created without checking there is an address to alert"
    )

    cfn = CFN.read_text()
    assert "AWS::Budgets::Budget" in cfn
    assert "MonthlyBudgetUsd" in cfn and "BudgetAlertEmail" in cfn


def test_aws_locks_the_same_things_azure_does():
    """The two templates should not offer different amounts of protection.

    Azure locks the vault and both AI accounts by network ACL; AWS has no keys
    to lock, so the equivalent is an aws:SourceIp condition on the statements
    that spend or read secrets. A town choosing AWS should not quietly get less.

    Deliberately NOT conditioned: the three KMS key-policy statements. That is
    the decryption path, and an address typed wrong there does not degrade a
    feature -- it makes every resident record unreadable. ListSecrets is also
    left alone; it returns names and no values.
    """
    cfn = CFN.read_text()
    assert "AllowedIpAddress" in cfn and "RestrictBySourceIp" in cfn

    import re
    parts = re.split(r"- Sid: (\w+)", cfn)
    covered = {}
    for i in range(1, len(parts), 2):
        covered[parts[i]] = "RestrictBySourceIp" in parts[i + 1][:900]

    for sid in ("TranslateResidentReports", "BlurFacesAndPlates",
                "InvokeBedrockModels", "KeepTownCredentialsInSecretsManager"):
        assert covered.get(sid), f"{sid} can still be used from any address"

    for sid in ("Pinpoint311MayUseTheKey", "NobodyMayStartDeletingThisKey"):
        assert not covered.get(sid), (
            f"{sid} is IP-conditioned; a wrong address there makes resident data "
            f"unreadable rather than degrading a feature"
        )


def test_the_budget_amount_is_pre_filled_on_both_clouds():
    """A protection nobody is asked about is a protection nobody takes.

    The amount arrives filled in, so the operator supplies an address rather
    than deciding a number and an address. It still creates nothing without the
    address -- a budget with nowhere to send alerts is decoration -- but that is
    one field to fill rather than two to think about.

    The alert address itself cannot be pre-filled. This endpoint is
    unauthenticated, because Azure's portal fetches it cross-origin without
    credentials, so a default written in here is published to anyone who
    requests the URL. Putting a staff email in it would be the same leak as the
    map key that started this.
    """
    template = json.loads(ARM.read_text())
    assert template["parameters"]["monthlyBudgetUsd"]["defaultValue"] > 0
    assert template["parameters"]["budgetAlertEmail"]["defaultValue"] == ""

    cfn = CFN.read_text()
    import re
    block = cfn[cfn.index("MonthlyBudgetUsd:"):][:400]
    default = re.search(r"Default:\s*(\d+)", block)
    assert default and int(default.group(1)) > 0


def test_the_firewall_rule_arrives_filled_in():
    """The address is resolved, not asked for.

    allowedIpAddress locks the vault and the AI accounts to one address, and it
    was blank because the template cannot guess a value -- so nobody filled it
    in and nothing got locked. The server does not have to guess: its own public
    hostname resolves to its own public address, which is a DNS lookup and not a
    call to anybody.
    """
    module = _route_module()
    served = json.loads(module.apply_selected_defaults(
        "azure/pinpoint-311.json", ARM.read_bytes(), {}, None, "203.0.113.7"))
    assert served["parameters"]["allowedIpAddress"]["defaultValue"] == "203.0.113.7"

    cfn = module.apply_selected_defaults(
        "aws/pinpoint-311.yaml", CFN.read_bytes(), {}, None, "203.0.113.7").decode()
    assert "Default: '203.0.113.7'" in cfn


def test_a_private_or_loopback_answer_is_refused():
    """A development machine resolves to 127.0.0.1 or a 10.x address. Writing
    one into a cloud firewall rule would lock the deployment out of itself, so
    an unusable answer becomes no answer."""
    module = _route_module()
    for bad in ("127.0.0.1", "10.1.2.3", "192.168.1.10"):
        module._ip_cache.clear()
        import unittest.mock as mock
        with mock.patch.object(module.socket, "getaddrinfo",
                               return_value=[(2, 1, 6, "", (bad, 0))]):
            assert module._resolve_public_ip("https://town.example.gov") is None


def test_resolving_nothing_leaves_the_box_empty():
    """No origin, an unresolvable name, or a resolver that is down: all of them
    are a blank box, never a wrong one."""
    module = _route_module()
    module._ip_cache.clear()
    assert module._resolve_public_ip(None) is None
    assert module._resolve_public_ip("not a url") is None
