"""CivicPlus SeeClickFix connector (SeeClickFix API v2).

SeeClickFix (acquired by CivicPlus) exposes a documented public REST API:
https://dev.seeclickfix.com — base https://seeclickfix.com/api/v2.

Creating an issue is a two-step flow (https://dev.seeclickfix.com/v2/issues/reporting/):
the request type owns a report form of questions, and the POST must carry an
`answers` map keyed by each question's `primary_key`. A request type with a
required question the payload does not answer is rejected with a 422 that names
the question — so this connector fetches the form first, fills what a resident's
report can answer, and refuses early (naming the questions) when it cannot.

Config:
    api_base          override, default https://seeclickfix.com/api/v2
    place_url         SeeClickFix place slug used to scope pulls (e.g. "springfield")
    organization_id   organization account id — scopes pulls to the org API
                      (the only API that also returns private issues)
    request_type_id   the Request Type new issues are filed under ("other" is
                      always available); legacy key `request_type` still read
    answers           JSON object of extra report-form answers, keyed by the
                      question's primary_key — how a town satisfies a required
                      question Pinpoint cannot answer on its own
Credentials:
    api_key               Personal Access Token, sent as `Authorization: Bearer`
                          (the scheme SeeClickFix documents), OR
    username, password    legacy HTTP Basic account login
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import hashlib

from app.integrations.base import BaseConnector, ConnectorError, ExternalComment, ExternalRecord

logger = logging.getLogger(__name__)

DEFAULT_API_BASE = "https://seeclickfix.com/api/v2"

# Report-form questions that carry no answer: SCF renders them as instructions.
_NO_ANSWER_TYPES = {"note"}
# Questions whose answer is a file upload. Creating an issue with a photo means
# multipart/form-data rather than JSON, which this connector does not do — photo
# URLs ride along in the description instead.
_FILE_TYPES = {"file", "image"}
_CHOICE_TYPES = {"select", "multivaluelist"}


class SeeClickFixConnector(BaseConnector):
    platform = "civicplus"
    capabilities = {"test", "push", "pull", "comments"}

    DEFAULT_STATUS_MAP_OUT = {"open": "open", "in_progress": "acknowledged", "closed": "closed"}
    DEFAULT_STATUS_MAP_IN = {
        "open": "open",
        "acknowledged": "in_progress",
        "closed": "closed",
        "archived": "closed",
    }

    @property
    def api_base(self) -> str:
        return (self.config.get("api_base") or DEFAULT_API_BASE).rstrip("/")

    @property
    def issues_base(self) -> str:
        """Where issues are listed.

        With an organization id configured this is the org-scoped API
        (https://dev.seeclickfix.com/v2/recommendations/), which is the only one
        that returns a town's private issues and does not depend on the place
        slug being spelled the way SeeClickFix spells it.
        """
        org = str(self.config.get("organization_id") or "").strip()
        return f"{self.api_base}/organizations/{org}" if org else self.api_base

    def _auth_kwargs(self) -> Dict[str, Any]:
        # Bearer first: a Personal Access Token is the documented scheme
        # (https://dev.seeclickfix.com/v2/overview/authentication/). Basic stays
        # as a fallback for towns still on a username/password service account.
        if self.credentials.get("api_key"):
            return {"headers": {"Authorization": f"Bearer {self.credentials['api_key']}"}}
        if self.credentials.get("username") and self.credentials.get("password"):
            return {"auth": (self.credentials["username"], self.credentials["password"])}
        return {}

    def _record_from_issue(self, issue: Dict[str, Any]) -> ExternalRecord:
        raw_status = issue.get("status")
        updated_dt = None
        if issue.get("updated_at"):
            try:
                updated_dt = datetime.fromisoformat(str(issue["updated_at"]).replace("Z", "+00:00"))
            except ValueError:
                pass  # unparseable vendor timestamp — leave as None
        return ExternalRecord(
            external_id=str(issue.get("id") or ""),
            status=self.map_status_in(raw_status),
            raw_status=raw_status,
            status_notes=None,
            updated_at=updated_dt,
            raw=issue,
        )

    # ---- Report form ----------------------------------------------------

    def _request_type_id(self) -> Optional[str]:
        """The configured Request Type. `request_type` was the key before the
        field was renamed to match the API parameter; both are read so an
        existing connection keeps working."""
        value = self.config.get("request_type_id") or self.config.get("request_type")
        value = str(value or "").strip()
        return value or None

    def _configured_answers(self) -> Dict[str, Any]:
        """Answers the town supplied for questions Pinpoint cannot answer.

        Stored as JSON text by the setup wizard, or as a dict when written
        through the API directly.
        """
        raw = self.config.get("answers")
        if isinstance(raw, dict):
            return {str(k): v for k, v in raw.items()}
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
            except ValueError:
                raise ConnectorError(
                    "The SeeClickFix 'extra answers' setting is not valid JSON. It should look "
                    'like {"142": "SHALLOW"} — a question id in quotes, then its answer.'
                )
            if not isinstance(parsed, dict):
                raise ConnectorError(
                    'The SeeClickFix "extra answers" setting must be a JSON object like '
                    '{"142": "SHALLOW"}.'
                )
            return {str(k): v for k, v in parsed.items()}
        return {}

    async def _fetch_report_form(self, client, request_type_id: str) -> List[Dict[str, Any]]:
        """Step 2 of reporting: the request type's questions."""
        resp = await client.get(f"{self.api_base}/request_types/{request_type_id}")
        if resp.status_code == 404:
            raise ConnectorError(
                f"SeeClickFix has no request type '{request_type_id}'. Check the Request Type ID "
                "with CivicPlus, or use 'other', which every place has."
            )
        self._raise_for_status(resp, "SeeClickFix get request type")
        body = resp.json()
        questions = body.get("questions") if isinstance(body, dict) else None
        return [q for q in (questions or []) if isinstance(q, dict)]

    @staticmethod
    def _describe(question: Dict[str, Any]) -> str:
        """How an unanswerable question is named to an admin: the question text
        as SeeClickFix words it, plus the id they need to answer it by."""
        text = str(question.get("question") or "Untitled question").strip()
        key = str(question.get("primary_key") or "?")
        choices = [str(v.get("key")) for v in (question.get("select_values") or [])
                   if isinstance(v, dict) and v.get("key")]
        detail = f'"{text}" (id {key}'
        if choices:
            detail += "; answer with one of: " + ", ".join(choices[:12])
            if len(choices) > 12:
                detail += ", …"
        return detail + ")"

    def _build_answers(
        self, questions: List[Dict[str, Any]], payload: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], List[str]]:
        """Fill the report form from a resident's report.

        Returns the `answers` map and a list of required questions nobody can
        answer — those are the ones worth telling an admin about, because the
        alternative is a vendor 422 nobody reads.
        """
        supplied = self._configured_answers()
        summary = (payload.get("service_name") or payload.get("description") or "Service Request")
        summary = " ".join(str(summary).split())[:120] or "Service Request"
        description = str(payload.get("description") or "").strip()
        media = [u for u in (payload.get("media_urls") or []) if isinstance(u, str)]
        if media:
            # Photos cannot ride on a JSON create, so the links go where a
            # SeeClickFix user will actually see them.
            description = (description + "\n\nPhotos: " + " ".join(media[:5])).strip()

        answers: Dict[str, Any] = {}
        unanswerable: List[str] = []

        for question in questions:
            key = str(question.get("primary_key") or "").strip()
            qtype = str(question.get("question_type") or "").strip().lower()
            required = bool(question.get("response_required"))
            if not key or qtype in _NO_ANSWER_TYPES:
                continue

            if key in supplied:
                value = supplied[key]
                if qtype in _CHOICE_TYPES:
                    valid = {str(v.get("key")) for v in (question.get("select_values") or [])
                             if isinstance(v, dict) and v.get("key")}
                    given = value if isinstance(value, list) else [value]
                    unknown = [str(v) for v in given if str(v) not in valid] if valid else []
                    if unknown:
                        # A wrong option is the same failure as no option, and
                        # says so before SeeClickFix rejects the report.
                        unanswerable.append(
                            f"{self._describe(question)} — the saved answer "
                            f"{', '.join(unknown)} is not one of its choices"
                        )
                        continue
                answers[key] = value
                continue

            if key == "summary":
                answers[key] = summary
            elif key == "description":
                if description:
                    answers[key] = description
                elif required:
                    answers[key] = summary  # a report with no description still needs one
            elif key == "address" and payload.get("address"):
                answers[key] = str(payload["address"])[:255]
            elif qtype in _FILE_TYPES:
                if required:
                    unanswerable.append(
                        f"{self._describe(question)} — a photo upload, which this "
                        "connection cannot send"
                    )
            elif required:
                unanswerable.append(self._describe(question))

        return answers, unanswerable

    @staticmethod
    def _unanswerable_message(request_type_id: str, unanswerable: List[str]) -> str:
        return (
            f"SeeClickFix request type {request_type_id} requires "
            f"{len(unanswerable)} question(s) this report cannot answer: "
            + "; ".join(unanswerable)
            + ". Add answers under the connection's 'Extra answers' setting, e.g. "
            '{"142": "SHALLOW"}, or pick a request type with fewer required questions.'
        )

    # ---- Operations ------------------------------------------------------

    async def test_connection(self) -> Dict[str, Any]:
        params: Dict[str, Any] = {"per_page": 1}
        if self.config.get("place_url") and not self.config.get("organization_id"):
            params["place_url"] = self.config["place_url"]
        request_type_id = self._request_type_id()
        async with self._client(**self._auth_kwargs()) as client:
            resp = await client.get(f"{self.issues_base}/issues", params=params)
            self._raise_for_status(resp, "SeeClickFix issues probe")
            body = resp.json()
            questions = (
                await self._fetch_report_form(client, request_type_id) if request_type_id else []
            )

        total = (body.get("metadata") or {}).get("pagination", {}).get("entries")
        scope = (
            f"organization {self.config['organization_id']}"
            if self.config.get("organization_id")
            else (self.config.get("place_url") or "global")
        )

        # A connection can be perfectly authenticated and still unable to file a
        # report. Those two facts are separate, so say both.
        warnings: List[str] = []
        if not request_type_id:
            warnings.append(
                "No Request Type ID is set. SeeClickFix requires one on every new issue — "
                "ask CivicPlus which type resident reports should use, or enter 'other', "
                "which every place has."
            )
        else:
            _, unanswerable = self._build_answers(questions, {
                "service_name": "Test report",
                "description": "Checking the connection.",
                "address": "1 Main St",
            })
            if unanswerable:
                warnings.append(self._unanswerable_message(request_type_id, unanswerable))
        if not self.credentials.get("api_key") and self.credentials.get("username"):
            warnings.append(
                "Signed in with a username and password. SeeClickFix documents Personal "
                "Access Tokens instead — create one under Account → Password & Security → "
                "Personal Access Token and paste it in as the token."
            )

        detail = f"Connected — scope '{scope}', {total if total is not None else 'unknown'} issue(s) visible"
        if request_type_id and not warnings:
            detail += f"; request type {request_type_id} needs no answers we can't fill"
        result: Dict[str, Any] = {"ok": True, "detail": detail}
        if warnings:
            result["warnings"] = warnings
        return result

    async def push_request(self, payload: Dict[str, Any]) -> ExternalRecord:
        if payload.get("lat") is None or payload.get("long") is None:
            raise ConnectorError("SeeClickFix requires lat/long to create an issue")
        request_type_id = self._request_type_id()
        if not request_type_id:
            raise ConnectorError(
                "SeeClickFix needs a Request Type ID before it will accept an issue. Set one on "
                "the connection ('other' works in every place if CivicPlus hasn't given you one)."
            )

        async with self._client(**self._auth_kwargs()) as client:
            questions = await self._fetch_report_form(client, request_type_id)
            answers, unanswerable = self._build_answers(questions, payload)
            if unanswerable:
                # Fail here rather than let SeeClickFix 422 — the vendor's error
                # names question ids; this one names what to do about them.
                raise ConnectorError(self._unanswerable_message(request_type_id, unanswerable))

            body: Dict[str, Any] = {
                "lat": payload["lat"],
                "lng": payload["long"],
                "address": payload.get("address") or "",
                "request_type_id": request_type_id,
                "answers": answers,
                "anonymize_reporter": not payload.get("email"),
            }
            resp = await client.post(f"{self.api_base}/issues", json=body)
            self._raise_for_status(resp, "SeeClickFix create issue")
            issue = resp.json()

        if not issue.get("id"):
            # 202 means SeeClickFix took the report but held it for moderation;
            # there is no issue to track yet, and saying so beats "no id".
            if (issue.get("metadata") or {}).get("moderated"):
                raise ConnectorError(
                    "SeeClickFix accepted the report but held it for moderation, so it has no "
                    "issue number yet. It will appear once their staff release it."
                )
            raise ConnectorError(f"SeeClickFix create returned no issue id: {str(issue)[:300]}")
        return self._record_from_issue(issue)

    async def pull_updates(self, since: Optional[datetime] = None) -> List[ExternalRecord]:
        params: Dict[str, Any] = {"per_page": 100, "sort": "updated_at", "sort_direction": "DESC"}
        if self.config.get("place_url") and not self.config.get("organization_id"):
            params["place_url"] = self.config["place_url"]
        if since:
            # updated_at_after, not after: `after` filters on created_at, which
            # would skip an old issue whose status just changed — the exact
            # thing this poll exists to catch.
            params["updated_at_after"] = since.isoformat()
        async with self._client(**self._auth_kwargs()) as client:
            resp = await client.get(f"{self.issues_base}/issues", params=params)
            self._raise_for_status(resp, "SeeClickFix list issues")
            body = resp.json()
        issues = body.get("issues") or []
        return [self._record_from_issue(i) for i in issues if i.get("id")]

    async def fetch_record(self, external_id: str) -> Optional[ExternalRecord]:
        async with self._client(**self._auth_kwargs()) as client:
            resp = await client.get(f"{self.api_base}/issues/{external_id}")
            if resp.status_code == 404:
                return None
            self._raise_for_status(resp, "SeeClickFix get issue")
            return self._record_from_issue(resp.json())

    # ---- Comments ----

    async def push_comment(self, external_id: str, author: str, content: str) -> Optional[str]:
        body = {"comment": f"{author}: {content}" if author else content}
        async with self._client(**self._auth_kwargs()) as client:
            resp = await client.post(f"{self.api_base}/issues/{external_id}/comments", json=body)
            self._raise_for_status(resp, "SeeClickFix create comment")
            item = resp.json()
        cid = item.get("id")
        return str(cid) if cid is not None else None

    async def pull_comments(self, external_id: str) -> List[ExternalComment]:
        async with self._client(**self._auth_kwargs()) as client:
            resp = await client.get(f"{self.api_base}/issues/{external_id}/comments")
            if resp.status_code == 404:
                return []
            self._raise_for_status(resp, "SeeClickFix list comments")
            body = resp.json()
        items = body.get("comments") if isinstance(body, dict) else body
        comments = []
        for item in (items or []):
            content = item.get("comment") or ""
            if not content:
                continue
            created = None
            if item.get("created_at"):
                try:
                    created = datetime.fromisoformat(str(item["created_at"]).replace("Z", "+00:00"))
                except ValueError:
                    pass
            # SCF comment payloads don't always expose an id — derive a stable surrogate
            cid = item.get("id")
            if cid is None:
                cid = "h" + hashlib.sha1(f"{item.get('created_at')}|{content}".encode()).hexdigest()[:16]
            comments.append(ExternalComment(
                external_id=str(cid),
                content=content,
                author=(item.get("commenter") or {}).get("name") if isinstance(item.get("commenter"), dict) else None,
                created_at=created,
                raw=item,
            ))
        return comments
