"""EgoBlur Gen2 (Meta, Apache-2.0) as a backend.

Everything model-specific follows Meta's Gen2 code rather than re-implementing
it. The Gen2 models are *scripted* Detectron2 networks whose outputs are
TorchScript `Instances` objects; getting any of the following wrong produces a
model that loads, runs, and finds nothing. References are to
github.com/facebookresearch/EgoBlur at 75144e1 (2026-05-05), which is what the
pinned `egoblur==2.0.1` wheel ships:

* Predictor: EgoBlur's own `EgoblurDetector`, from the wheel. We call its
  `pre_process` -> `inference` -> `get_detections`, exactly the sequence
  `EgoblurDetector.run` uses (gen2/script/predictor.py:553-568) except that
  `run` discards the scores.
* Input: C x H x W, uint8, BGR. The demo reads with cv2.imread (BGR,
  gen2/script/utils.py:144-152) and transposes HWC->CHW with no dtype change
  (`get_image_tensor`, utils.py:164-173). The detector's default
  image_format is "BGR" (predictor.py:120) and its resize path passes the
  tensor through apart from interpolation (predictor.py:322-326).
* Resize: shortest edge 1200, longest edge capped at 1200 (RESIZE_MIN_GEN2 /
  RESIZE_MAX_GEN2, gen2/script/constants.py:24-25, passed as `resize_aug` in
  demo_ego_blur_gen2.py:411-415 / 427-431); boxes are mapped back to the input
  frame by `detector_postprocess` (gen2/script/detectron2/utils/utils.py:41-72).
* Call: tscript_type "script" (default, predictor.py:119; the demo does not
  override it) => `model.inference([{"image": t}], do_postprocess=False)`
  (predictor.py:369-371), returning Instances with pred_boxes (XYXY pixels),
  scores and optionally pred_classes (face=0, plate=1; predictor.py:78-80).
  Converting those to Python needs `patch_instances(PATCH_INSTANCES_FIELDS)`
  active while the model runs (demo_ego_blur_gen2.py:171,
  vrs_blur_gen2.py:584; fields at predictor.py:88-95). The VRS tool holds it
  open for its whole run; we hold it for the life of the process.
* Post-processing: class filter if pred_classes is present, torchvision NMS,
  then keep score > threshold, strictly (predictor.py:494-526).
* NMS IoU 0.5: both Gen2 entry points default to 0.5
  (demo_ego_blur_gen2.py:106, vrs_blur_gen2.py:294). The README's "defaults
  to 0.3" is the Gen1 value (gen1/script/demo_ego_blur_gen1.py:69).
* Thresholds: the camera-rgb defaults the demo uses without --camera_name
  (utils.py:204-221): plate 0.74475, face 0.67416 (constants.py:28-44). Meta
  tuned these on Aria glasses footage, not phone photos.
"""

from __future__ import annotations

import contextlib
import threading
from typing import Any, Dict, List, Optional, Tuple

from app.backends.base import Detector, ModelFile
from app.imaging import Prepared

EGOBLUR_RESIZE_GEN2 = 1200


class EgoBlurDetector(Detector):
    name = "egoblur"

    def __init__(self, settings):
        super().__init__(settings)
        self.models = {
            "plate": ModelFile("plate", settings.lp_file, required=True),
            "face": ModelFile("face", settings.face_file, required=False),
        }
        self._patch: Optional[contextlib.ExitStack] = None
        self._lock = threading.Lock()

    def load(self) -> None:
        import torch

        torch.set_num_threads(self.settings.threads)
        try:
            torch.set_num_interop_threads(1)
        except RuntimeError:
            pass
        super().load()
        if self.kinds():
            from gen2.script.detectron2.export.torchscript_patch import patch_instances
            from gen2.script.predictor import PATCH_INSTANCES_FIELDS

            stack = contextlib.ExitStack()
            stack.enter_context(patch_instances(fields=PATCH_INSTANCES_FIELDS))
            self._patch = stack

    def close(self) -> None:
        if self._patch is not None:
            self._patch.close()
            self._patch = None

    def _open(self, path: str, kind: str) -> Any:
        # Lazy: the wheel pulls in cv2 and torchvision, and a service with no
        # model files should still start fast and answer /health.
        from gen2.script.predictor import ClassID, EgoblurDetector

        plate = kind == "plate"
        return EgoblurDetector(
            model_path=path,
            device=self.settings.device,
            detection_class=ClassID.LICENSE_PLATE if plate else ClassID.FACE,
            score_threshold=(self.settings.egoblur_lp_threshold if plate
                             else self.settings.egoblur_face_threshold),
            nms_iou_threshold=self.settings.egoblur_nms_iou,
            resize_aug={"min_size_test": EGOBLUR_RESIZE_GEN2,
                        "max_size_test": EGOBLUR_RESIZE_GEN2},
        )

    def describe(self) -> Dict[str, Any]:
        return {
            "plate_threshold": self.settings.egoblur_lp_threshold,
            "face_threshold": self.settings.egoblur_face_threshold,
            "nms_iou": self.settings.egoblur_nms_iou,
            "model_resize": EGOBLUR_RESIZE_GEN2,
            "device": self.settings.device,
        }

    @staticmethod
    def to_tensor(image: Prepared):
        """RGB HWC uint8 -> BGR CHW uint8 (utils.py:144-173)."""
        import numpy as np
        import torch

        bgr_chw = np.ascontiguousarray(image.rgb[:, :, ::-1].transpose(2, 0, 1))
        return torch.from_numpy(bgr_chw)

    def infer(self, image: Prepared, kind: str) -> Tuple[List[List[float]], List[float]]:
        import torch

        detector = self.models[kind].handle
        with self._lock, torch.inference_mode():
            batch = self.to_tensor(image).unsqueeze(0)
            img_batch, orig_hw, model_hw = detector.pre_process(batch)
            preds = detector.inference(img_batch)
            frames = detector.get_detections(
                output_tensor=preds, timestamp_s=0.0, stream_id="",
                rotation_angle=0.0, model_input_hw_list=model_hw,
                target_img_hw_list=orig_hw,
            )
        frame = frames[0] if frames else None
        if frame is None:
            return [], []
        if kind == "plate":
            boxes, scores = frame.lp_bboxes, frame.lp_scores
        else:
            boxes, scores = frame.face_bboxes, frame.face_scores
        return [list(map(float, b)) for b in boxes], [float(s) for s in list(scores)]
