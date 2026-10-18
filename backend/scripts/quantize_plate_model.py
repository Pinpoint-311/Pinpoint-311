"""Make an int8 copy of a YOLOv9 plate detector, for towns that want it smaller.

    pip install onnx==1.17.0 onnxruntime==1.23.2
    python scripts/quantize_plate_model.py \
        /models/yolo-v9-s-608-license-plates-end2end.onnx \
        /models/yolo-v9-s-608-license-plates-end2end.int8.onnx

Dynamic quantization: weights stored as uint8, activations quantized at run
time, so no calibration images are needed and the result is reproducible from
the published fp32 file alone. Pinpoint does not ship either file; each town
downloads the fp32 model (see docs/PHOTO_REDACTION_MODELS.md) and may run this.

Measured on the evaluation set, int8 is NOT the default -- see the docs for the
numbers before choosing it.
"""

import sys

from onnxruntime.quantization import QuantType, quantize_dynamic


def main(src: str, dst: str) -> None:
    quantize_dynamic(src, dst, weight_type=QuantType.QUInt8)
    print(f"wrote {dst}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
