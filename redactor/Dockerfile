# Pinpoint redactor: an internal plate/face detector for photo redaction.
#
# Two targets, one per detector backend, because their runtimes differ by
# ~600 MB and a town should not carry PyTorch to run a 10 MB ONNX model:
#
#   docker build --target onnx    -t pinpoint-311-redactor:onnx    redactor/
#   docker build --target egoblur -t pinpoint-311-redactor:egoblur redactor/
#
# Model files are NOT in the image. They are mounted read-only at /models; see
# README.md. Both targets build on linux/amd64 and linux/arm64.

# 3.11.15 on Debian 12.15. 3.11.13 sat on 12.12, and its OS packages (gnutls,
# krb5, pam, libcap) carried fixed CRITICAL/HIGH advisories that only a newer
# base picks up. setuptools/wheel: the base's copies (and setuptools' vendored
# jaraco.context/wheel) have HIGH advisories. setuptools 80.10.2 is the first
# fixed release; wheel 0.46.3 is what the new base already ships (0.46.2 fixed it).
FROM python:3.11.15-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    REDACTOR_MODELS_DIR=/models
# The point release still trails Debian's security fixes (perl-base, pcre2 at
# the time of writing); upgrading at build time picks them up.
RUN apt-get update && apt-get upgrade -y --no-install-recommends \
 && rm -rf /var/lib/apt/lists/*
RUN useradd --system --uid 10001 --no-create-home redactor
WORKDIR /srv
COPY requirements.txt .
RUN pip install setuptools==80.10.2 wheel==0.46.3 \
 && pip install -r requirements.txt
EXPOSE 8000
# No curl in slim; the stdlib is enough for a liveness probe.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-server-header"]

FROM base AS egoblur
# CPU wheels by default. For a GPU server build with e.g.
#   --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu128
# and run with REDACTOR_DEVICE=cuda:0 and the GPU passed through.
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
COPY requirements-egoblur.txt ./
# CPU-only torch/torchvision from the PyTorch index (no CUDA libraries on
# either arch). cv2 is needed because EgoBlur's predictor imports it; the ONNX
# image does without (its letterbox uses Pillow). egoblur itself goes in with
# --no-deps: its declared deps add moviepy, av and vrs for the video/VRS
# tools, none of which the predictor imports.
RUN pip install --index-url ${TORCH_INDEX} -r requirements-egoblur.txt \
 && pip install opencv-python-headless==4.11.0.86 \
 && pip install --no-deps egoblur==2.0.1 \
 && find /usr/local/lib/python3.11 -name '__pycache__' -prune -exec rm -rf {} + \
 && rm -rf /usr/local/lib/python3.11/site-packages/torch/include \
           /usr/local/lib/python3.11/site-packages/torch/share/cmake
COPY app ./app
ENV REDACTOR_BACKEND=egoblur
USER redactor

FROM base AS onnx
COPY requirements-onnx.txt .
RUN pip install --no-deps -r requirements-onnx.txt
COPY app ./app
ENV REDACTOR_BACKEND=onnx
USER redactor
