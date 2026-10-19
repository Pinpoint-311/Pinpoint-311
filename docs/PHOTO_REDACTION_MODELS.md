# Photo redaction models

Pinpoint blurs faces and license plates in resident photos before they are stored.
Faces come from the town's cloud provider (Azure, Google or AWS). Plates come from a
plate detector that runs on your own server. If the cloud face provider stops
answering, a face model on your server takes over. Both models are ONNX files that
**your town downloads**. Pinpoint never bundles or redistributes the weights.

| Setting | Values | Default |
|---|---|---|
| `PLATE_DETECTOR` | `yolo` · `ocr` · `off` | `yolo` when the plate model file is present, otherwise `ocr` |
| `FACE_FALLBACK` | `yunet` · `opencv` · `off` | `yunet` when the face model file is present, otherwise `opencv` |
| `PLATE_OCR_UNION` | `true` · `false` | `false` |

You set these on the **Photo Redaction** card, under **On-server detectors**. The card
also shows whether each model file is installed.

- `ocr` is the old behaviour. It infers plates from text the cloud provider reads, so it
  cannot see a plate that has no digit (vanity plates). It also blurs some street signs.
- `PLATE_OCR_UNION=true` runs the text heuristic as well as the model. It is off by
  default because it added false positives on signs and found nothing the model missed.
- The order for faces is: cloud provider → YuNet → photo withheld for staff review.
  `opencv` uses the older Haar cascades instead of YuNet. `off` withholds the photo.
- **The detectors fail closed.** Suppose a model is selected but its file is missing, or
  it fails to load, or it errors or times out on a photo. Then that photo is withheld
  for staff review with the reason `plate-detector-error`. It is never published unchecked.
  The health check warns while this is happening.

## Install

Download the files into the models directory. That directory is mounted read-only
at `/models` in the backend and the worker. By default it is `./models` next to
`docker-compose.yml`; set `REDACTION_MODELS_DIR` in the instance's `.env` to use
another path.

```sh
mkdir -p models && cd models
curl -LO https://github.com/ankandrew/open-image-models/releases/download/assets/yolo-v9-s-608-license-plates-end2end.onnx
curl -LO https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
sha256sum -c <<'EOF'
2b878b38d9aa07b6ddc3ea75c4ffcb39869bc5c218e0a14002f60ab2f7b0be9a  yolo-v9-s-608-license-plates-end2end.onnx
8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4  face_detection_yunet_2023mar.onnx
EOF
```

Then restart the backend. The models load on the first photo, so there is no
warm-up step. Open **Photo Redaction → On-server detectors**: both should say
**Model installed**. Plates switch to the model automatically once the file is
present. If you had chosen something else, select **On-server plate model** there.

The checksums above are the ones we computed from the files we downloaded on
2026-10-18. Upstream does not publish checksums.

## Which plate model

All three use the same pipeline, so choose with `PLATE_MODEL_FILE`. They were measured
on two aarch64 cores against an evaluation set of 25 images: 20 plates, including two
vanity plates, plus signs, house numbers and a bus display.

| `PLATE_MODEL_FILE` | Size | Latency | Plates found | False positives |
|---|---|---|---|---|
| `yolo-v9-s-608-license-plates-end2end.onnx` (**default**) | 28.6 MB | ~0.5 s | 20 / 20 | 2 |
| `yolo-v9-t-640-license-plates-end2end.onnx` | 7.8 MB | ~0.2 s | 18 / 20 | 3 |
| `yolo-v9-t-384-license-plates-end2end.onnx` | 7.8 MB | ~0.07 s | 17 / 20 | 2 |

The `s` model is the default because, for a privacy filter, a missed plate costs more
than an over-blurred badge. All three models found both vanity plates ("CRAZYGUY",
"KATYDID") that the text heuristic missed.

The project's published figures for the default are P 0.957, R 0.917, mAP50 0.966
(open-image-models README, "Plate Detection" table). The training data is not stated.

**int8.** `backend/scripts/quantize_plate_model.py` makes a dynamically quantized copy
of the default model:

| | Size | Peak RSS | Latency | Found | FP | CRAZYGUY score |
|---|---|---|---|---|---|---|
| fp32 | 28.6 MB | +107 MB | ~0.5 s | 20/20 | 2 | 0.91 |
| int8 | 7.8 MB | +93 MB | ~0.3 s | 20/20 | 3 | 0.27 |

int8 is not the default. It added a false positive, and its score on a real vanity
plate fell to just above the 0.25 threshold.

## Licences — read before installing

- **YuNet** (`face_detection_yunet_2023mar.onnx`, opencv_zoo): MIT licence, which covers
  the code and the model.
- **YOLOv9 plate models** (open-image-models by ankandrew): the code is MIT. **The weights
  have no stated licence.** The upstream YOLOv9 training code (WongKinYiu/yolov9) is
  GPL-3.0, and it is unclear whether weights trained with it carry any obligation. We
  recommend asking the author (github.com/ankandrew/open-image-models) before relying on
  them, and checking with your counsel. Each town downloads the file itself and makes
  that decision itself; Pinpoint does not distribute it.
- A licence-clean alternative is **LPD-YuNet** (opencv_zoo, Apache-2.0). It was trained
  on Chinese plates. On the two real photos it found "KATYDID" at 0.97 and "CRAZYGUY" at
  0.886, which is below the opencv_zoo demo threshold of 0.9 but above the model class
  default of 0.8. It is not wired in.

## Memory and processes

Only the API process runs redaction, at intake and in the pick-time screen. That is
the only process that loads the models: once, on first use, shared by all requests.
The Celery worker never loads them. It mounts `/models` only so that the health scan
can see whether the files are there.

The models are unloaded after `MODEL_IDLE_UNLOAD_S` seconds with no photos (default
600) and reload on demand in about 0.1 s.

Sessions run without the onnxruntime memory arena and memory-pattern buffers, with
`ONNX_THREADS` intra-op threads (default 2). One plate inference runs at a time per
process.

These figures were measured in the production image, as RSS above the 62 MB baseline
of a Python process with the libraries already imported:

| Model | After load | Peak, one 1280 px photo | After unload |
|---|---|---|---|
| YOLOv9-s fp32 | +45 MB | +107 MB | +12 MB |
| YuNet | +4 MB | +118 MB | +6 MB |

**Image size.** onnxruntime 1.23.2 adds 132 MB to the backend image with its declared
dependencies. Installing it `--no-deps` adds only 46 MB, since it imports only numpy.

## Pointing an instance at the models

Keep the model files in one directory on the host, with a `SHA256SUMS` file, and
add it to each instance's `.env`; then recreate the backend and worker:

```sh
REDACTION_MODELS_DIR=/opt/pinpoint/models
```

## Experimental: EgoBlur sidecar

`redactor/` packages Meta's EgoBlur Gen2 as an opt-in sidecar, enabled with
`docker compose --profile redactor`. Selecting it means setting
`PLATE_DETECTOR=redactor`.

**It requires a GPU for practical speed.** A model of the same size took about 25 s per
photo on this CPU.

See `redactor/README.md`.
