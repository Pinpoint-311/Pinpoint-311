"""Plate (and optionally face) detector service for photo redaction.

    POST /detect   raw image bytes in the body -> {"detections": [{x0,y0,x1,y1,score,kind}]}
                   (fractions of the image). ?kinds=plate,face selects detectors.
    GET  /health   whether a model is loaded, which, its sha256, and versions.

Internal only: compose publishes no port, and nothing here opens an outbound
connection. It never fakes a result -- with no model loaded, /detect answers
503 "models_missing" and the caller withholds the photo.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse

from app import backends
from app.backends.base import Detector
from app.config import Settings
from app.imaging import ImageRejected, prepare, to_fractions

logger = logging.getLogger("redactor")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


class Gate:
    """One inference at a time, a bounded queue, and a deadline.

    A timed-out request returns, but its inference cannot be interrupted, so
    the slot is released only when the thread actually finishes -- otherwise a
    run of slow photos would stack up concurrent inferences, which is exactly
    what the limit exists to prevent.
    """

    def __init__(self, queue_max: int):
        self.queue_max = queue_max
        self.waiting = 0
        self.sem = asyncio.Semaphore(1)

    async def run(self, fn, timeout: float):
        if self.waiting >= self.queue_max:
            raise OverflowError("busy")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        self.waiting += 1
        try:
            await asyncio.wait_for(self.sem.acquire(), timeout)
        finally:
            self.waiting -= 1
        future = loop.run_in_executor(None, fn)
        future.add_done_callback(lambda _f: self.sem.release())
        remaining = max(0.01, deadline - loop.time())
        return await asyncio.wait_for(asyncio.shield(future), remaining)


def versions() -> Dict[str, str]:
    import platform
    from importlib import metadata

    out = {"python": platform.python_version(), "machine": platform.machine()}
    for dist in ("onnxruntime", "torch", "torchvision", "egoblur", "Pillow", "numpy"):
        try:
            out[dist.lower()] = metadata.version(dist)
        except metadata.PackageNotFoundError:
            pass
    return out


def build_app(settings: Optional[Settings] = None, detector: Optional[Detector] = None) -> FastAPI:
    settings = settings or Settings.from_env()
    state: Dict[str, Any] = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        det = detector
        error = ""
        if det is None:
            try:
                det = backends.create(settings)
            except Exception as exc:
                error = str(exc)
        if det is not None:
            started = time.monotonic()
            await asyncio.get_running_loop().run_in_executor(None, det.load)
            logger.info("backend=%s status=%s kinds=%s load=%.2fs", det.name, det.status(),
                        det.kinds(), time.monotonic() - started)
        state.update(detector=det, error=error, gate=Gate(settings.queue_max),
                     started=time.time())
        yield
        if det is not None:
            det.close()

    app = FastAPI(title="Pinpoint redactor", lifespan=lifespan, docs_url=None,
                  redoc_url=None, openapi_url=None)

    @app.get("/health")
    async def health():
        det: Optional[Detector] = state.get("detector")
        return {
            "status": det.status() if det else "config_error",
            "error": state.get("error", ""),
            "backend": det.name if det else settings.backend,
            "kinds": det.kinds() if det else [],
            "models": [m.public() for m in det.models.values()] if det else [],
            "settings": {
                "max_edge": settings.max_edge, "threads": settings.threads,
                "timeout_s": settings.timeout_s, "max_bytes": settings.max_bytes,
                **(det.describe() if det else {}),
            },
            "versions": versions(),
        }

    @app.post("/detect")
    async def detect(request: Request, kinds: str = Query("plate")):
        det: Optional[Detector] = state.get("detector")
        if det is None or det.status() != "ok":
            return JSONResponse({"detail": "models_missing" if det else "config_error"},
                                status_code=503)
        wanted = tuple(k for k in (s.strip() for s in kinds.split(",")) if k)
        unknown = [k for k in wanted if k not in ("plate", "face")]
        if not wanted or unknown:
            return JSONResponse({"detail": f"unknown kinds {unknown or wanted}"}, status_code=400)
        missing = [k for k in wanted if k not in det.kinds()]
        if missing:
            # Never answer "nothing found" for a detector that is not there.
            return JSONResponse({"detail": "models_missing", "missing": missing}, status_code=503)

        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > settings.max_bytes:
            return JSONResponse({"detail": "too_large"}, status_code=413)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > settings.max_bytes:
                return JSONResponse({"detail": "too_large"}, status_code=413)
        if not body:
            return JSONResponse({"detail": "empty"}, status_code=400)
        raw = bytes(body)

        def work():
            started = time.monotonic()
            image = prepare(raw, settings.max_edge, settings.max_pixels)
            found = []
            timings = {}
            for kind in wanted:
                t0 = time.monotonic()
                boxes, scores = det.infer(image, kind)
                timings[kind] = round(time.monotonic() - t0, 4)
                found += to_fractions(boxes, scores, image.width, image.height, kind)
            return {
                "detections": found,
                "backend": det.name,
                "image": {"width": image.original_width, "height": image.original_height,
                          "detector_width": image.width, "detector_height": image.height},
                "seconds": {**timings, "total": round(time.monotonic() - started, 4)},
            }

        try:
            return await state["gate"].run(work, settings.timeout_s)
        except ImageRejected as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        except OverflowError:
            return JSONResponse({"detail": "busy"}, status_code=503)
        except asyncio.TimeoutError:
            return JSONResponse({"detail": "timeout"}, status_code=504)
        except Exception:
            logger.exception("inference failed")
            return JSONResponse({"detail": "inference_error"}, status_code=500)

    return app


app = build_app()
