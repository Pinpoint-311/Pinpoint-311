"""Build TorchScript models with EgoBlur Gen2's *calling convention*, for tests
and benchmarks when the real weights are not available.

Gen2 models are scripted Detectron2 networks called as
``model.inference([{"image": uint8 BGR CHW}], do_postprocess=False)`` and
returning a list of scripted ``Instances`` with pred_boxes / scores /
pred_classes (EgoBlur gen2/script/predictor.py:369-371, 494-504). Anything built
here goes through the redactor's real EgoBlur code path, including
``patch_instances`` and EgoBlur's own resize, NMS and thresholding.

Two kinds:
  * ``dummy``: tiny and deterministic. It reports a plate box around the pure-red
    pixels it sees (so a channel-order or dtype mistake upstream makes it miss),
    plus fixed boxes that exercise NMS, the score threshold and class filtering.
    It raises if the input is not uint8.
  * ``proxy``: torchvision Faster R-CNN with a random-weight FPN backbone, for
    latency and memory. resnext101_32x8d-FPN is ~105M parameters, about the size
    of the real Gen2 model (~104M; ~400 MB on disk).

Usage: python egoblur_signature.py dummy|proxy OUT.jit [backbone]
"""

from __future__ import annotations

import sys
from typing import Dict, List

import torch
from torch import Tensor, nn


def _patched():
    import gen2.script  # noqa: F401  registers the vendored detectron2 aliases
    from gen2.script.detectron2.export.torchscript_patch import patch_instances
    from gen2.script.predictor import PATCH_INSTANCES_FIELDS

    return patch_instances(fields=PATCH_INSTANCES_FIELDS)


def build_dummy(path: str) -> None:
    from gen2.script.detectron2.structures import Boxes, Instances

    class Dummy(nn.Module):
        @torch.jit.export
        def inference(self, batched_inputs: List[Dict[str, Tensor]],
                      do_postprocess: bool = False) -> List[Instances]:
            out: List[Instances] = []
            for item in batched_inputs:
                img = item["image"]
                if img.dtype != torch.uint8:
                    raise RuntimeError("EgoBlur expects uint8 input")
                h = img.shape[1]
                w = img.shape[2]
                # BGR: red is channel 2. Pure red in the photo => (B, G, R) = (0, 0, 255).
                mask = (img[2] > 200) & (img[1] < 60) & (img[0] < 60)
                idx = torch.nonzero(mask)
                rows: List[Tensor] = []
                scores: List[float] = []
                classes: List[int] = []
                if idx.shape[0] > 0:
                    y0 = idx[:, 0].min().float()
                    y1 = idx[:, 0].max().float() + 1.0
                    x0 = idx[:, 1].min().float()
                    x1 = idx[:, 1].max().float() + 1.0
                    rows.append(torch.stack([x0, y0, x1, y1]))
                    scores.append(0.95)
                    classes.append(1)
                    # A near-duplicate with a lower score: NMS (IoU 0.5) must drop it.
                    rows.append(torch.stack([x0 + 1.0, y0 + 1.0, x1 + 1.0, y1 + 1.0]))
                    scores.append(0.90)
                    classes.append(1)
                # Below the 0.74475 plate threshold: must be filtered out.
                rows.append(torch.tensor([0.0, 0.0, w * 0.1, h * 0.1]))
                scores.append(0.50)
                classes.append(1)
                # Confident, but class 0 (face): the plate detector must ignore it.
                rows.append(torch.tensor([w * 0.8, h * 0.8, w * 0.9, h * 0.9]))
                scores.append(0.99)
                classes.append(0)
                inst = Instances((h, w))
                inst.pred_boxes = Boxes(torch.stack(rows))
                inst.scores = torch.tensor(scores)
                inst.pred_classes = torch.tensor(classes)
                out.append(inst)
            return out

        def forward(self, x: Tensor) -> Tensor:
            return x

    with _patched():
        torch.jit.save(torch.jit.script(Dummy()), path)


def build_proxy(path: str, backbone: str = "resnext101_32x8d") -> int:
    from gen2.script.detectron2.structures import Boxes, Instances
    from torchvision.models.detection import FasterRCNN
    from torchvision.models.detection.backbone_utils import resnet_fpn_backbone

    torch.manual_seed(0)
    fpn = resnet_fpn_backbone(backbone_name=backbone, weights=None, trainable_layers=0)
    det = FasterRCNN(fpn, num_classes=2, min_size=1200, max_size=1200).eval()

    class Proxy(nn.Module):
        def __init__(self, det):
            super().__init__()
            self.det = det

        @torch.jit.export
        def inference(self, batched_inputs: List[Dict[str, Tensor]],
                      do_postprocess: bool = False) -> List[Instances]:
            out: List[Instances] = []
            for item in batched_inputs:
                img = item["image"]
                x = img.flip(0).float() / 255.0
                _, found = self.det([x])
                inst = Instances((img.shape[1], img.shape[2]))
                inst.pred_boxes = Boxes(found[0]["boxes"])
                inst.scores = found[0]["scores"]
                inst.pred_classes = torch.ones_like(found[0]["labels"])
                out.append(inst)
            return out

        def forward(self, x: Tensor) -> Tensor:
            return x

    params = sum(p.numel() for p in det.parameters())
    with _patched():
        torch.jit.save(torch.jit.script(Proxy(det)), path)
    return params


if __name__ == "__main__":
    kind, out = sys.argv[1], sys.argv[2]
    if kind == "dummy":
        build_dummy(out)
    else:
        print("params", build_proxy(out, *(sys.argv[3:4] or [])))
