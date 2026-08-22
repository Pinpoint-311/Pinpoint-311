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
"""

import os
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


@router.get("/{cloud}/{filename}")
async def get_deploy_template(cloud: str, filename: str) -> Response:
    """Serve one deployment template to whoever asks, including a cloud provider."""
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
