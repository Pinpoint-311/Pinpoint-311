# redactor: experimental detector sidecar (EgoBlur)

**Experimental and opt-in. It requires a GPU for practical speed.**

The default plate detector and face fallback run *inside the backend*, from ONNX files
in `/models`. See [docs/PHOTO_REDACTION_MODELS.md](../docs/PHOTO_REDACTION_MODELS.md).
Use this sidecar only if you want Meta's EgoBlur Gen2 and you have a GPU server for it.

## What it is

A small FastAPI service with one detector interface and two backends:

| Backend | Docker target | Image | Model |
|---|---|---|---|
| `egoblur` | `egoblur` | ~760 MB (CPU torch) | `ego_blur_lp_gen2.jit`, optionally `ego_blur_face_gen2.jit` |
| `onnx` | `onnx` | ~300 MB | any end-to-end YOLO plate ONNX |

The service exposes two endpoints:

- `POST /detect?kinds=plate[,face]` takes raw image bytes and returns
  `{"detections": [{x0, y0, x1, y1, score, kind}]}`, with coordinates as fractions of
  the image.
- `GET /health` reports `ok`, `models_missing` or `model_error`, plus each model's
  sha256 and the library versions.

The service never fakes a result. With no model loaded, `/detect` answers 503. The
backend treats that, or any error or timeout, as "could not look" and withholds the
photo.

Other properties:

- No published ports.
- No outbound network at runtime.
- One inference at a time, with a bounded queue.
- A request size limit and a 50 MP decode limit.
- EXIF orientation is applied and metadata dropped.

EgoBlur handling follows Meta's Gen2 code exactly. File and line references are in
`app/backends/egoblur.py`. Points worth knowing:

- Input is uint8 BGR in CHW layout.
- Images are resized to a 1200 px short edge, with the long edge capped at 1200.
- The detector's own `pre_process`, `inference` and `get_detections` are used.
- NMS IoU is **0.5**. That is the Gen2 code default; the README's 0.3 is the Gen1 value.
- Score thresholds are plate 0.74475 and face 0.67416, the `camera-rgb` defaults.

## Speed and size

| | |
|---|---|
| Model | Faster R-CNN, ResNeXt-101-32x8d FPN, ~104M parameters, ~420 MB |
| CPU (proxy of identical size, aarch64) | ~24 s per photo on 2 threads, 17–18 s on 4 |
| Input size | Has no effect, because EgoBlur always resizes to 1200 px |
| RAM | 0.65–1.0 GB idle, ~1.5 GB peak |
| Published accuracy | Gen1 paper (arXiv 2308.13093): plates AP 0.929 / AR 0.992 (Table X); faces on CCV2 AP 0.99 / AR 0.998 (Table I). Gen2 has no published numbers and was evaluated only on Aria glasses footage. |

## Install (GPU server)

1. Get the Gen2 models from <https://www.projectaria.com/tools/egoblur/>. The download
   is behind an email form; the user reports the licence as Apache-2.0. Unzip them into
   the redactor models directory (`REDACTOR_MODELS_DIR`, default `./models`) under
   exactly these names:
   - `ego_blur_lp_gen2.jit`
   - `ego_blur_face_gen2.jit` (optional)

   Meta publishes no checksums. Record the `sha256` that `/health` reports.
2. Build for CUDA and pass the GPU through, for example with a compose override:
   ```sh
   docker build --target egoblur \
     --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu128 \
     -t pinpoint-311-redactor:egoblur redactor/
   ```
   Set `REDACTOR_DEVICE=cuda:0`.
3. `docker compose --profile redactor up -d redactor`
4. Set `PLATE_DETECTOR=redactor` for the town. If the redactor runs somewhere other
   than `http://redactor:8000`, also set `REDACTOR_URL` in the backend environment.

## Tests

```sh
docker build --target egoblur -t redactor-test redactor/
docker run --rm -v $PWD/redactor:/r -w /r --entrypoint sh redactor-test -c \
  "pip install -q --user -r requirements-dev.txt && pip install -q --user --no-deps onnxruntime==1.23.2 && python -m pytest -q tests"
```

The tests use EgoBlur's real code path, driven by a tiny scripted model with Gen2's
calling convention (`scripts/egoblur_signature.py`). The same script builds a
same-size ResNeXt-101 proxy for benchmarking.
