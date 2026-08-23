"""Serving the cloud deployment templates from the town's own instance.

The setup page has two buttons that open Azure's or AWS's own deployment form
pre-loaded with a template of ours. Neither button uploads anything: it hands
the provider a URL and the provider fetches it. So the file has to be readable
from the public internet, by somebody who is not signed in to Pinpoint.

It used to be read from `raw.githubusercontent.com/.../main`, which is wrong in
three ways and only one of them is visible when it works:

  * **version skew.** A town on last quarter's build got whatever is on `main`
    today. A template that declares a parameter the town's app does not know how
    to consume produces a resource nobody can enter into a card.
  * **a third party in the path.** Rename the repository, make it private, or
    put the operator on a government network that does not reach GitHub, and
    every town's deploy button breaks at once, in a console that reports it as
    "template not found" -- with nothing anywhere saying whose URL it was.
  * **fork hostility.** A self-hoster who forked and edited the templates still
    got ours.

Serving them from the instance fixes all three: the file travels with the build
that knows how to consume it, the only host in the path is the one the operator
is already looking at, and a fork serves the fork's copy.

**Public and unauthenticated, deliberately.** The cloud provider fetches
anonymously. Both files are resource definitions -- names, SKUs, role
definition ids, and an explicit refusal to emit any key as a deployment output
(see backend/tests/test_deploy_templates.py, which holds that in place). There
is nothing in them a reader learns that reading our public repository would not
also tell them.

`Access-Control-Allow-Origin: *` is set on the response and is load-bearing:
the Azure portal fetches the template with an XHR *from portal.azure.com*, so
without it the browser refuses the read and the portal shows an empty form. The
app's own CORS middleware allows only the town's origins, which is right for
every other route and wrong for this one.

**One thing is rewritten on the way out: default values, and nothing else.**
The setup card says "Microsoft Azure - Key management, AI triage, Translation"
and the Azure form used to arrive with `deployAzureOpenAI: false` and
`deployCognitiveServices: false`, because those are the on-disk defaults. An
operator who reads the card, presses Deploy and then presses Create gets a vault
and no AI resources, and the two cards they came for stay empty with nothing
saying why. Flipping the defaults in the repository is not the fix -- it would
create billable resources in the account of every town that did not ask. Since
the file is already served from the town's own instance, the town's own
selections can be written into it as it leaves. See `_capability_defaults`.
"""

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Dict, Optional, Tuple

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import RedirectResponse

router = APIRouter()


# Where these files are published for anybody -- or any build -- that does not
# have its own copy. Only ever a last hop: see the 302 below.
PUBLISHED_BASE_URL = "https://raw.githubusercontent.com/Pinpoint-311/Pinpoint-311/main/deploy/templates"


# The files we will serve, and nothing else. An allowlist rather than a path
# join under a root: a route that takes a filename and joins it to a directory
# is one `..` away from serving the environment file, and the set of templates
# is two entries that change about once a year.
TEMPLATE_FILES: Dict[str, Tuple[str, str]] = {
    "azure/pinpoint-311.json": ("deploy/templates/azure/pinpoint-311.json", "application/json"),
    "aws/pinpoint-311.yaml": ("deploy/templates/aws/pinpoint-311.yaml", "application/x-yaml"),
}


def _candidate_roots() -> list:
    """Where `deploy/templates` might be, in the ways this app actually runs.

    Ordered by how specific the answer is, not by how likely it is:

      1. `PINPOINT_DEPLOY_TEMPLATES_DIR` -- an operator who has put the files
         somewhere else has said so, and should not be second-guessed.
      2. `/project/deploy/templates` -- both compose files bind-mount the
         repository root at /project, so this is the live deployment and the
         published-image deployment.
      3. `/app/deploy/templates` -- if the backend image ever carries its own
         copy, this is where it would land.
      4. the repository, walking up from this file -- a source checkout, and
         every test run.

    A miss on all four is a supported state, not an error: the setup page falls
    back to the published copy on GitHub and says so. The button keeps working;
    it just stops being served from here.
    """
    roots = []
    override = os.environ.get("PINPOINT_DEPLOY_TEMPLATES_DIR", "").strip()
    if override:
        roots.append(Path(override))
    roots.append(Path("/project/deploy/templates"))
    roots.append(Path("/app/deploy/templates"))
    # backend/app/api/deploy_templates.py -> api -> app -> backend -> repo root
    roots.append(Path(__file__).resolve().parents[3] / "deploy" / "templates")
    return roots


def resolve_template(relative: str) -> Optional[Path]:
    """The on-disk file for an allowlisted template name, or None.

    `relative` is only ever a key of TEMPLATE_FILES -- the caller checks that
    before calling -- so no part of a request reaches the filesystem as a path.
    """
    entry = TEMPLATE_FILES.get(relative)
    if entry is None:
        return None
    suffix = entry[0].split("deploy/templates/", 1)[1]
    for root in _candidate_roots():
        candidate = root / suffix
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def templates_are_servable() -> bool:
    """Whether every advertised template is actually on disk here.

    All-or-nothing on purpose. A half-served pair means one button reads from
    this instance and the other from GitHub, which is two different answers to
    "where did my template come from" on one page.
    """
    return all(resolve_template(name) is not None for name in TEMPLATE_FILES)


def published_url(relative: str) -> str:
    """Where this template is published for a build that has no copy of it."""
    return f"{PUBLISHED_BASE_URL}/{relative}"


# ---------------------------------------------------------------------------
# Defaults that match what the town actually asked for
# ---------------------------------------------------------------------------

# Which of the town's capability selections turns each template toggle on.
#
# Read as: `deployCognitiveServices` should arrive pre-ticked if the town runs
# either translation *or* photo screening on Azure, because one multi-service
# account serves both. `redaction` is Pinpoint's name for photo screening --
# face blurring and licence plates; there is no separate `photo` capability.
#
# The provider names are the catalog's, not the cloud's: Azure's AI provider is
# spelled `azure`, AWS's is spelled `bedrock`.
AZURE_TOGGLE_SOURCES: Dict[str, Tuple[Tuple[str, str], ...]] = {
    "deployKeyVault": (("kms", "azure"),),
    "deployAzureOpenAI": (("ai", "azure"),),
    "deployCognitiveServices": (("translation", "azure"), ("redaction", "azure")),
}

AWS_TOGGLE_SOURCES: Dict[str, Tuple[Tuple[str, str], ...]] = {
    "AllowBedrock": (("ai", "bedrock"),),
    "AllowTranslate": (("translation", "aws"),),
    "AllowRekognition": (("redaction", "aws"),),
    "AllowSecretsManager": (("secrets", "aws"),),
}

# How long the whole reading-our-own-settings step gets. The caller here is
# Azure's portal or CloudFormation fetching a URL, and a secret store that has
# gone slow must not turn into a deployment form that never renders. Past this,
# the file goes out exactly as it is on disk.
_SELECTION_BUDGET_SECONDS = 4.0


async def _selected_providers() -> Dict[str, str]:
    """The provider each capability is switched on and running under, right now.

    Server-side state only. The cloud provider fetches this route anonymously --
    there is no session, no town header and nothing trustworthy in the request
    to read a selection out of -- so the answer has to come from the instance's
    own settings or not at all.

    A capability appears here only if it is both switched on and resolvable. A
    capability that raises, times out, or cannot be read is simply absent, and
    an absent capability leaves the on-disk default alone.
    """
    try:
        from app.api.system import effective_provider_for
        from app.services import capability_switches
    except Exception:
        return {}

    wanted = set()
    for sources in (AZURE_TOGGLE_SOURCES, AWS_TOGGLE_SOURCES):
        for pairs in sources.values():
            for capability, _provider in pairs:
                wanted.add(capability)

    async def one(capability: str) -> Tuple[str, Optional[str]]:
        try:
            if not await capability_switches.enabled(capability):
                return capability, None
            return capability, await effective_provider_for(capability)
        except Exception:
            return capability, None

    try:
        results = await asyncio.wait_for(
            asyncio.gather(*(one(c) for c in sorted(wanted))),
            timeout=_SELECTION_BUDGET_SECONDS,
        )
    except Exception:
        return {}

    return {c: p.strip().lower() for c, p in results if isinstance(p, str) and p.strip()}


def _capability_defaults(relative: str, selected: Dict[str, str]) -> Dict[str, bool]:
    """Which template toggles this town's selections say should start ticked.

    **One direction only: off to on, never on to off.** Turning a toggle on is
    justified by a positive reading -- the town chose this cloud for that
    capability, so the resource is one they asked for. Turning one off could not
    be justified the same way, because "not selected" and "not selected *yet*"
    read identically from here, and the operator deploying a key vault has
    usually not finished choosing Azure inside Pinpoint at the moment they press
    the button. Serving `deployKeyVault: false` to that operator would produce
    no vault at all, which is a worse failure than the extra one this rewrite
    exists to avoid.
    """
    sources = AZURE_TOGGLE_SOURCES if relative.startswith("azure/") else AWS_TOGGLE_SOURCES
    return {
        toggle: True
        for toggle, pairs in sources.items()
        if any(selected.get(capability) == provider for capability, provider in pairs)
    }


def _rewrite_arm_defaults(source: str, defaults: Dict[str, bool]) -> str:
    """Set `defaultValue` on named ARM parameters, touching nothing else.

    A line rewrite rather than parse-and-redump on purpose. Re-serialising the
    template would reflow every line of it, and the promise this route makes is
    that a reviewer diffing the served file against the published one sees
    default values and nothing else.
    """
    out = source
    for name, value in defaults.items():
        pattern = re.compile(
            r'("' + re.escape(name) + r'"\s*:\s*\{(?:[^{}]|\{[^{}]*\})*?"defaultValue"\s*:\s*)'
            r"(true|false)",
            re.S,
        )
        out, _count = pattern.subn(lambda m: m.group(1) + ("true" if value else "false"), out, count=1)
    return out


def _rewrite_cfn_defaults(source: str, defaults: Dict[str, bool]) -> str:
    """Set `Default:` on named CloudFormation parameters, touching nothing else.

    Line-oriented because there is no YAML parser here and there is deliberately
    not going to be one -- see the test module. The parameters concerned are all
    two-line `Type: String` / `Default: 'Yes'` blocks at a known indent, so this
    stays a search for one line inside one named block.
    """
    lines = source.splitlines(keepends=True)
    for name, value in defaults.items():
        header = f"  {name}:\n"
        try:
            start = lines.index(header)
        except ValueError:
            continue
        for index in range(start + 1, len(lines)):
            line = lines[index]
            if line.strip() and not line.startswith("    "):
                break  # left the parameter's block
            if line.startswith("    Default:"):
                lines[index] = f"    Default: '{'Yes' if value else 'No'}'\n"
                break
    return "".join(lines)


def apply_selected_defaults(relative: str, body: bytes, selected: Dict[str, str]) -> bytes:
    """The served body: the file on disk, with defaults the town's own answer.

    Returns the file unchanged if anything at all is off -- nothing to change,
    an unrecognised template, or a rewrite that did not come back parseable.
    """
    defaults = _capability_defaults(relative, selected)
    if not defaults:
        return body
    try:
        source = body.decode("utf-8")
    except UnicodeDecodeError:
        return body

    if relative.startswith("azure/"):
        rewritten = _rewrite_arm_defaults(source, defaults)
        try:
            parsed = json.loads(rewritten)
        except ValueError:
            return body
        # Belt and braces: the rewrite is a regex over a file we ship, so the
        # thing worth checking is not that it worked but that it changed only
        # what it was allowed to change.
        if _arm_without_defaults(parsed) != _arm_without_defaults(json.loads(source)):
            return body
    else:
        rewritten = _rewrite_cfn_defaults(source, defaults)
        if _cfn_without_defaults(rewritten) != _cfn_without_defaults(source):
            return body

    return rewritten.encode("utf-8")


def _arm_without_defaults(template: dict) -> str:
    """An ARM template with every parameter default blanked, as a stable string.

    The comparison key for "these two files differ only in default values".
    """
    stripped = json.loads(json.dumps(template))
    for parameter in stripped.get("parameters", {}).values():
        if isinstance(parameter, dict):
            parameter.pop("defaultValue", None)
    return json.dumps(stripped, sort_keys=True, indent=1)


def _cfn_without_defaults(source: str) -> str:
    """The same comparison key for the CloudFormation file, as text."""
    return "".join(
        line for line in source.splitlines(keepends=True) if not line.startswith("    Default:")
    )


@router.get("/{cloud}/{filename}")
async def get_deploy_template(cloud: str, filename: str) -> Response:
    """Serve one deployment template to whoever asks, including a cloud provider.

    The body is the file on disk with **only `defaultValue` (ARM) and `Default:`
    (CloudFormation) fields adjusted**, so that the form Azure or AWS draws
    arrives with the capabilities this town selected already ticked rather than
    at the repository's neutral defaults. Nothing else about the file is
    touched: not a resource, not a permission, not a description, not the
    formatting. That is the guarantee -- a security reviewer diffing what this
    URL serves against the published copy must find default values and nothing
    else, and `test_deploy_templates.py` holds it in place by normalising every
    default away and asserting the two are then identical.

    Anything unreadable leaves the on-disk defaults exactly as they are.
    """
    relative = f"{cloud}/{filename}"
    entry = TEMPLATE_FILES.get(relative)
    if entry is None:
        raise HTTPException(status_code=404, detail="No such deployment template")

    path = resolve_template(relative)
    if path is None:
        # A template we publish, in a build that has no copy of it -- a managed
        # tenancy running the image with no repository mounted, most likely.
        #
        # Redirect rather than 404. The whole reason the button points here is
        # so that the URL is one the operator can reason about; answering it
        # with "not found" inside Azure's portal is the failure this route was
        # written to remove. Following one hop to the published copy is a worse
        # answer than serving our own, and a far better one than no answer --
        # and unlike a 404 it is visible in the provider's own network trace, so
        # "where did this template come from" stays answerable.
        return RedirectResponse(url=published_url(relative), status_code=302)

    try:
        body = path.read_bytes()
    except OSError:
        return RedirectResponse(url=published_url(relative), status_code=302)

    try:
        body = apply_selected_defaults(relative, body, await _selected_providers())
    except Exception:
        # The published file is always a correct answer. A settings read that
        # went wrong must not be the reason a town cannot deploy at all.
        pass

    return Response(
        content=body,
        media_type=entry[1],
        headers={
            # See the module docstring: the Azure portal reads this cross-origin.
            "Access-Control-Allow-Origin": "*",
            # Short, because the point of serving it here is that it matches the
            # build. A provider that caches for a day would reintroduce the skew
            # this route exists to remove.
            "Cache-Control": "public, max-age=300",
        },
    )
