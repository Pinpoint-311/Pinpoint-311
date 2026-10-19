"""Where upgrade requests come from, and who must have approved them.

Phase 2 ships one source, the command line: an operator on the host types
``pinpoint-updater upgrade <instance> <tag>``, and ``--yes`` (or an interactive
"yes") is their approval.

Phase 3 adds ``HttpRequestSource``: the updater polls each instance's backend
over loopback (``/api/internal/updater/*``, per-instance token), claims
requests admins filed in the console, and reports each step back. The engine
does not change: it receives an ``UpgradeRequest``, asks the ``ApprovalPolicy``
whether it may run it, and sends results to the ``Reporter`` the source hands
out. ``TwoPersonApproval`` applies to console upgrades and rollbacks while the
console's two-person setting is on (the default) or the instance config pins
it; a ``restart`` needs one admin.
"""

from __future__ import annotations

import contextlib
import getpass
import sys
import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Optional

import httpx

from pinpoint_updater import __version__
from pinpoint_updater.redact import redact
from pinpoint_updater.reporting import NullReporter, Reporter

if TYPE_CHECKING:  # pragma: no cover
    from pinpoint_updater.config import UpdaterConfig

Action = Literal["upgrade", "rollback", "restart"]
ACTIONS = ("upgrade", "rollback", "restart")


@dataclass
class UpgradeRequest:
    instance: str
    action: Action
    tag: Optional[str]
    requested_by: str
    source: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    reason: Optional[str] = None
    # Identities that approved this request (the requester counts only where
    # the policy says so).
    approvals: list[str] = field(default_factory=list)
    # A destructive migration needs its own, explicit approval: the gate in
    # app/db/migrate.py exits 2 without it.
    allow_destructive: bool = False
    # Console requests: "two_person" or "single", as the instance stated it.
    policy: Optional[str] = None
    # Set when the console refused a heartbeat or report for this request (its
    # lease ran out there). The run carries on; the outcome says so locally.
    console_lost: bool = False
    # An "upgrade" to a release older than the one running. Only an operator
    # on the host may ask for that (CliRequestSource). A console request
    # cannot: a compromised backend, or one misused admin account, could
    # otherwise move the town back onto a signed release with a known flaw.
    # The console's way back is "rollback", to the previous release only.
    allow_downgrade: bool = False


class ApprovalPolicy(ABC):
    @abstractmethod
    def check(self, request: UpgradeRequest) -> tuple[bool, str]:
        """(approved, reason)."""


class OperatorApproval(ApprovalPolicy):
    """CLI: the operator on the host is the approver, by confirming."""

    def check(self, request):
        if request.approvals:
            return True, f"confirmed by {', '.join(request.approvals)}"
        return False, "not confirmed (pass --yes, or answer the prompt)"


class ConsoleApproval(ApprovalPolicy):
    """A console request one admin may approve (a restart, or two-person
    approval switched off): someone must still have approved it."""

    def check(self, request):
        if request.approvals:
            return True, f"approved in the console by {', '.join(request.approvals)}"
        return False, "the console reports no approval for this request"


class TwoPersonApproval(ApprovalPolicy):
    """Phase 3 production default: someone other than the requester approved."""

    def check(self, request):
        others = [a for a in request.approvals if a != request.requested_by]
        if others:
            return True, f"requested by {request.requested_by}, approved by {', '.join(others)}"
        return False, f"needs approval from an admin other than {request.requested_by}"


class RequestSource(ABC):
    name: str = "?"

    @abstractmethod
    def pending(self, instance: str) -> list[UpgradeRequest]:
        """Requests waiting to run for this instance, oldest first."""

    @abstractmethod
    def claim(self, request: UpgradeRequest) -> bool:
        """Mark a request as taken; False if someone else (or a cancel) won."""

    @abstractmethod
    def reporter(self, request: UpgradeRequest) -> Reporter:
        """Where this request's step results go (besides the local JSONL log)."""

    def publish_releases(self, instance: str, releases: list[dict]) -> None:
        """Hand the normalised release list to the instance (Phase 3: the app
        shows it instead of calling GitHub/GitLab itself). No-op by default."""

    def approval_policy(self, instance: str) -> ApprovalPolicy:
        return OperatorApproval()

    def approval_policy_for(self, request: UpgradeRequest) -> ApprovalPolicy:
        """The policy for one request; by default the instance's."""
        return self.approval_policy(request.instance)

    def heartbeat(self, request: UpgradeRequest):
        """A context manager kept open while the request runs. No-op by default."""
        return contextlib.nullcontext()

    def close(self) -> None:
        pass


class CliRequestSource(RequestSource):
    """Requests typed at the host's command line. Nothing is ever pending."""

    name = "cli"

    def pending(self, instance):
        return []

    def claim(self, request):
        return True

    def reporter(self, request):
        return NullReporter()

    def build(self, instance: str, action: Action, tag: Optional[str], *, confirmed: bool,
              allow_destructive: bool = False, reason: Optional[str] = None) -> UpgradeRequest:
        try:
            user = getpass.getuser()
        except Exception:  # no passwd entry in some sandboxes
            user = "unknown"
        operator = f"{user}@host"
        return UpgradeRequest(
            instance=instance, action=action, tag=tag, requested_by=operator, source=self.name,
            reason=reason, approvals=[operator] if confirmed else [], allow_destructive=allow_destructive,
            allow_downgrade=True,
        )


class RequestSourceError(RuntimeError):
    """The instance's backend could not be reached or answered unexpectedly."""


class ConsoleLostTrack(RequestSourceError):
    """409 on a report: the console already closed this request (lease expired
    or an admin marked it failed). Never retried."""


INTERNAL = "/api/internal/updater"

# The console is the internet-facing backend, which the design does not trust
# with the host. Its answers are small JSON documents; a larger or endless one
# is refused rather than read into the memory of a process that has the
# Docker socket.
MAX_RESPONSE_BYTES = 1024 * 1024
# Requests run per instance per pass. More wait for the next pass, so one
# instance's console cannot keep the updater busy and starve the others.
MAX_REQUESTS_PER_PASS = 3


class HttpRequestSource(RequestSource):
    """The console channel. Contract (the backend side is
    backend/app/api/updater_internal.py):

    * ``GET  {api_url}/api/internal/updater/requests``      → pending requests
    * ``POST {api_url}/api/internal/updater/requests/{id}/claim``  (200 won, 409 lost)
    * ``POST {api_url}/api/internal/updater/requests/{id}/steps``  (StepResult JSON)
    * ``POST {api_url}/api/internal/updater/requests/{id}/outcome`` (RunOutcome JSON)
    * ``PUT  {api_url}/api/internal/updater/releases``      (normalised list)

    Authenticated with ``Authorization: Bearer <token_file contents>``. The
    URL is the instance's loopback backend port (``api_url``, default
    ``app_url``): Caddy answers 404 for the prefix and the backend refuses
    proxied calls. Redirects are never followed, so the token cannot be
    handed to another host. The token is registered with redact() as it is
    read, so it never reaches a log line.

    Instances without ``token_file`` have nothing pending and publish nothing.
    """

    name = "http"

    def __init__(self, config: "UpdaterConfig", *, transport: Optional[httpx.BaseTransport] = None,
                 timeout: float = 15.0, retries: int = 3, sleep=time.sleep,
                 heartbeat_interval: Optional[float] = 60.0):
        self.config = config
        self.heartbeat_interval = heartbeat_interval
        self._lock = threading.Lock()  # httpx.Client is shared with the heartbeat thread
        self.transport = transport
        self.timeout = timeout
        self.retries = max(1, retries)
        self.sleep = sleep
        self._clients: dict[str, httpx.Client] = {}

    # -- plumbing ----------------------------------------------------------------

    def enabled(self, instance: str) -> bool:
        return bool(self.config.instance(instance).token_file)

    def _client(self, instance: str) -> httpx.Client:
        if instance not in self._clients:
            inst = self.config.instance(instance)
            token = inst.updater_token()  # ConfigError if unreadable
            if not token:
                from pinpoint_updater.config import ConfigError
                raise ConfigError(f"{instance}: token_file {inst.token_path} is empty")
            self._clients[instance] = httpx.Client(
                base_url=inst.api_base, transport=self.transport, follow_redirects=False,
                timeout=httpx.Timeout(self.timeout, connect=min(5.0, self.timeout)),
                headers={"Authorization": f"Bearer {token}", "User-Agent": f"pinpoint-updater/{__version__}",
                         "Accept": "application/json"},
            )
        return self._clients[instance]

    def _call(self, instance: str, method: str, path: str, *, json: Any = None,
              ok: tuple[int, ...] = (200, 201)) -> httpx.Response:
        try:
            with self._lock:
                resp = self._bounded(self._client(instance), method, f"{INTERNAL}{path}", json)
        except httpx.HTTPError as exc:
            raise RequestSourceError(redact(f"{instance}: {method} {INTERNAL}{path} failed "
                                            f"({exc.__class__.__name__}: {exc})")) from None
        if resp.status_code not in ok:
            body = redact((resp.text or "")[:300])
            if resp.status_code == 409 and path.rsplit("/", 1)[-1] in ("steps", "outcome", "heartbeat"):
                raise ConsoleLostTrack(f"{instance}: {method} {INTERNAL}{path} answered 409: {body}")
            hint = ""
            if resp.status_code == 401:
                hint = " (token unknown or revoked: create a new one in the console and update token_file)"
            elif resp.status_code == 404 and path == "/requests":
                hint = " (is api_url the backend's loopback port, not Caddy?)"
            raise RequestSourceError(f"{instance}: {method} {INTERNAL}{path} answered {resp.status_code}{hint}: {body}")
        return resp

    def _bounded(self, client: httpx.Client, method: str, url: str, json: Any) -> httpx.Response:
        """One request whose answer is at most MAX_RESPONSE_BYTES and arrives
        within about twice the timeout in total. httpx's own timeouts are per
        read, so a console dripping a byte at a time would otherwise hold the
        updater (and every other instance's upgrades) indefinitely."""
        request = client.build_request(method, url, json=json)
        deadline = time.monotonic() + 2 * self.timeout
        resp = client.send(request, stream=True)
        try:
            declared = resp.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > MAX_RESPONSE_BYTES:
                raise httpx.DecodingError(f"response of {declared} bytes is over the {MAX_RESPONSE_BYTES}-byte limit",
                                          request=request)
            chunks, size = [], 0
            for chunk in resp.iter_bytes():
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise httpx.DecodingError(f"response is over the {MAX_RESPONSE_BYTES}-byte limit", request=request)
                if time.monotonic() > deadline:
                    raise httpx.ReadTimeout("response took too long to arrive", request=request)
                chunks.append(chunk)
        finally:
            resp.close()
        return httpx.Response(resp.status_code, headers=resp.headers, content=b"".join(chunks), request=request)

    @staticmethod
    def _log(message: str) -> None:
        print(f"pinpoint-updater: {redact(message)}", file=sys.stderr)

    def close(self) -> None:
        for client in self._clients.values():
            try:
                client.close()
            except Exception:
                pass
        self._clients.clear()

    # -- RequestSource -------------------------------------------------------------

    def pending(self, instance: str) -> list[UpgradeRequest]:
        if not self.enabled(instance):
            return []
        body = self._call(instance, "GET", "/requests").json()
        rows = body.get("requests") if isinstance(body, dict) else None
        if not isinstance(rows, list):
            raise RequestSourceError(f"{instance}: /requests returned an unexpected shape")
        out: list[UpgradeRequest] = []
        for row in rows:
            req = self._parse(instance, row)
            if req is not None:
                out.append(req)
        if len(out) > MAX_REQUESTS_PER_PASS:
            self._log(f"{instance}: {len(out)} requests pending; running the oldest {MAX_REQUESTS_PER_PASS} "
                      "this pass, the rest on the next")
        return out[:MAX_REQUESTS_PER_PASS]

    def _parse(self, instance: str, row: Any) -> Optional[UpgradeRequest]:
        from pinpoint_updater.config import ConfigError, validate_tag

        if not isinstance(row, dict):
            return None
        rid, action, tag = str(row.get("id") or ""), row.get("action"), row.get("tag")
        if not (rid.isascii() and rid.isdigit() and len(rid) <= 18) or action not in ACTIONS:
            self._log(f"{instance}: ignoring malformed request {redact(str(row)[:200])}")
            return None
        if action == "upgrade":
            try:
                validate_tag(tag or "")
            except ConfigError as exc:
                self._log(f"{instance}: ignoring request {rid}: {exc}")
                return None
        else:
            tag = None
        approvals = [str(a) for a in (row.get("approvals") or []) if a]
        return UpgradeRequest(
            instance=instance, action=action, tag=tag, requested_by=str(row.get("requested_by") or "unknown"),
            source=self.name, id=rid, reason=row.get("reason"), approvals=approvals,
            allow_destructive=bool(row.get("allow_destructive")) and action == "upgrade",
            policy=row.get("policy") if row.get("policy") in ("two_person", "single") else "two_person",
        )

    def claim(self, request: UpgradeRequest) -> bool:
        resp = self._call(request.instance, "POST", f"/requests/{request.id}/claim", ok=(200, 404, 409))
        return resp.status_code == 200

    def reporter(self, request: UpgradeRequest) -> Reporter:
        return HttpReporter(self, request)

    def approval_policy(self, instance: str) -> ApprovalPolicy:
        return TwoPersonApproval()

    def approval_policy_for(self, request: UpgradeRequest) -> ApprovalPolicy:
        if request.action == "restart":
            return ConsoleApproval()
        floor = self.config.instance(request.instance).require_two_person_approval
        if floor or request.policy != "single":
            return TwoPersonApproval()
        return ConsoleApproval()

    def publish_releases(self, instance: str, releases: list[dict], current: Optional[dict] = None) -> None:
        if not self.enabled(instance):
            return
        self._call(instance, "PUT", "/releases", json={"releases": releases, "current": current})

    # -- used by HttpReporter ----------------------------------------------------

    def post(self, request: UpgradeRequest, kind: str, payload: dict) -> None:
        """POST a step or the outcome. The outcome is retried: a lost outcome
        would leave the console showing "running" forever. A 409 (the console
        closed the request) is not retried and marks the request lost."""
        if request.console_lost:
            return
        attempts = self.retries if kind == "outcome" else 1
        for attempt in range(attempts):
            try:
                self._call(request.instance, "POST", f"/requests/{request.id}/{kind}", json=redact(payload))
                return
            except ConsoleLostTrack as exc:
                self.lost(request, exc)
                return
            except RequestSourceError as exc:
                if attempt + 1 >= attempts:
                    raise
                self._log(f"{exc}; retrying")
                self.sleep(2 ** attempt)


    # -- heartbeat ---------------------------------------------------------------

    def heartbeat(self, request: UpgradeRequest):
        return Heartbeat(self, request, self.heartbeat_interval)

    def beat(self, request: UpgradeRequest) -> None:
        self._call(request.instance, "POST", f"/requests/{request.id}/heartbeat")

    def lost(self, request: UpgradeRequest, exc: Exception) -> None:
        if not request.console_lost:
            request.console_lost = True
            self._log("!!! CONSOLE LOST TRACK of request "
                      f"{request.id} on {request.instance}: {exc}. The run continues (stopping halfway is worse); "
                      "the console already shows it failed. Check this run's outcome in the local log.")


class Heartbeat:
    """Renews the request's lease every ``interval`` seconds while a run is in
    progress, from a daemon thread, so a backup, pull or migrate that takes
    longer than the console's lease is not taken for a dead updater. Stops on
    exit whether the run finished or raised; a 409 marks the request lost and
    ends the beats; other errors are logged and retried on the next beat."""

    def __init__(self, source: HttpRequestSource, request: UpgradeRequest, interval: Optional[float]):
        self.source = source
        self.request = request
        self.interval = interval
        self.beats = 0
        self._stop = threading.Event()
        self.thread: Optional[threading.Thread] = None

    def __enter__(self) -> "Heartbeat":
        if self.interval and self.interval > 0:
            self.thread = threading.Thread(target=self._run, name=f"heartbeat-{self.request.id}", daemon=True)
            self.thread.start()
        return self

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.source.beat(self.request)
                self.beats += 1
            except ConsoleLostTrack as exc:
                self.source.lost(self.request, exc)
                return
            except Exception as exc:  # unreachable console: try again next beat
                self.source._log(f"heartbeat for request {self.request.id} failed: {exc}")

    def __exit__(self, *exc) -> bool:
        self._stop.set()
        if self.thread is not None:
            self.thread.join(timeout=self.source.timeout + 5)
        return False


class LostTrackMarker(Reporter):
    """First in the reporter chain: when the console lost track of the request,
    say so in the outcome every local reporter (JSONL log, console) records."""

    def __init__(self, request: UpgradeRequest):
        self.request = request

    def step(self, run, result):
        pass

    def finished(self, run, outcome):
        if self.request.console_lost:
            outcome.data["console"] = "lost track"
            outcome.summary = (f"{outcome.summary} [console lost track: the instance had already marked request "
                               f"{self.request.id} failed, so this outcome did not reach it]")


class HttpReporter(Reporter):
    def __init__(self, source: HttpRequestSource, request: UpgradeRequest):
        self.source = source
        self.request = request

    def step(self, run, result):
        self.source.post(self.request, "steps", result.as_dict())

    def finished(self, run, outcome):
        self.source.post(self.request, "outcome", outcome.as_dict(run))
