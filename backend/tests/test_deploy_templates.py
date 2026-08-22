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


def test_every_arm_output_that_claims_a_box_names_a_real_one():
    """The outputs say "Pinpoint box: Key Vault URL". If that label stops
    existing -- renamed, or the field dropped -- the template is directing an
    operator at a box that is not on the card, and nothing else would say so."""
    template = _arm()
    labels = _catalog_labels()
    if not labels:
        pytest.skip("no provider catalog could be imported here")

    claimed = []
    for output in template["outputs"].values():
        description = output.get("metadata", {}).get("description", "")
        for match in re.findall(r"Pinpoint box(?:es)?:\s*([^.]+)", description):
            for label in re.split(r"\s+and\s+|,", match):
                label = label.strip().rstrip(".")
                # Trailing prose after the label, e.g. "- the same value in both".
                label = re.split(r"\s+[-–—]\s+", label)[0].strip()
                if label:
                    claimed.append(label)

    assert claimed, "no ARM output claims a Pinpoint box; the labelling convention moved"
    unknown = [c for c in claimed if c not in labels]
    assert not unknown, (
        f"ARM outputs name boxes that no catalog has: {unknown}. "
        f"Known labels include {sorted(labels)[:8]}..."
    )


# ---------------------------------------------------------------------------
# Least privilege, and scoped to what was created
# ---------------------------------------------------------------------------

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
