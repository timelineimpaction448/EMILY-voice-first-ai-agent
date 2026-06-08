"""
Local face detection for the camera feed (no LLM).

Uses OpenCV Haar frontal-face cascades with CLAHE preprocessing.
Optional HOG people + MobileNet-SSD object detection can be enabled via constructor flags.
"""

from __future__ import annotations

import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None  # type: ignore

_MODEL_DIR = Path.home() / ".emily" / "models"
_PROTOTXT_NAME = "MobileNetSSD_deploy.prototxt"
_CAFFEMODEL_NAME = "MobileNetSSD_deploy.caffemodel"
_PROTOTXT_URL = (
    "https://raw.githubusercontent.com/chuanqi305/MobileNet-SSD/master/deploy.prototxt"
)
_CAFFEMODEL_URL = (
    "https://github.com/chuanqi305/MobileNet-SSD/raw/master/"
    "mobilenet_iter_73000.caffemodel"
)

# MobileNet-SSD VOC labels (index 0 = background)
_SSD_LABELS = (
    "background", "aeroplane", "bicycle", "bird", "boat", "bottle", "bus", "car",
    "cat", "chair", "cow", "dining table", "dog", "horse", "motorbike", "person",
    "potted plant", "sheep", "sofa", "train", "tv/monitor",
)

_PERSON_KIND = "person"
_FACE_KIND = "face"
_OBJECT_KIND = "object"


@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float
    x1: int
    y1: int
    x2: int
    y2: int
    kind: str = _OBJECT_KIND

    def as_dict(self) -> dict:
        return {
            "label": self.label,
            "confidence": round(self.confidence, 2),
            "box": [self.x1, self.y1, self.x2, self.y2],
            "kind": self.kind,
        }


def _clip_box(x1: int, y1: int, x2: int, y2: int, w: int, h: int) -> tuple[int, int, int, int]:
    return (
        max(0, min(x1, w - 1)),
        max(0, min(y1, h - 1)),
        max(0, min(x2, w)),
        max(0, min(y2, h)),
    )


def _iou(a: Detection, b: Detection) -> float:
    ix1 = max(a.x1, b.x1)
    iy1 = max(a.y1, b.y1)
    ix2 = min(a.x2, b.x2)
    iy2 = min(a.y2, b.y2)
    iw = max(0, ix2 - ix1)
    ih = max(0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = (a.x2 - a.x1) * (a.y2 - a.y1)
    area_b = (b.x2 - b.x1) * (b.y2 - b.y1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _nms(dets: list[Detection], thresh: float = 0.45) -> list[Detection]:
    if not dets:
        return []
    ordered = sorted(dets, key=lambda d: d.confidence, reverse=True)
    kept: list[Detection] = []
    for d in ordered:
        if all(_iou(d, k) < thresh for k in kept):
            kept.append(d)
    return kept


def _nms_by_kind(dets: list[Detection], thresh: float = 0.45) -> list[Detection]:
    """NMS within each kind only — avoids dropping faces inside person boxes."""
    if not dets:
        return []
    by_kind: dict[str, list[Detection]] = {}
    for d in dets:
        by_kind.setdefault(d.kind, []).append(d)
    out: list[Detection] = []
    for group in by_kind.values():
        out.extend(_nms(group, thresh))
    return out


class LocalVisionEngine:
    """Thread-safe detector; safe to call from the camera capture thread."""

    def __init__(
        self,
        *,
        detect_objects: bool = False,
        detect_faces: bool = True,
        detect_people: bool = False,
        min_object_conf: float = 0.45,
        min_face_conf: float = 0.0,
        detect_width: int | None = None,
    ):
        self._enable_objects = detect_objects
        self._enable_faces = detect_faces
        self._enable_people = detect_people
        self._min_object_conf = min_object_conf
        self._min_face_conf = min_face_conf
        faces_only = detect_faces and not detect_objects and not detect_people
        if detect_width is None:
            detect_width = 480 if faces_only else 320
        self._detect_width = detect_width
        self._faces_only = faces_only
        self._lock = threading.Lock()
        self._hog = None
        self._face_cascade = None
        self._ssd_net = None
        self._ssd_failed = False
        self._face_idx = 0

        if cv2 is None:
            return

        if detect_people:
            self._hog = cv2.HOGDescriptor()
            self._hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

        if detect_faces:
            self._face_cascade = LocalVisionEngine._load_face_cascade()

    @property
    def available(self) -> bool:
        if cv2 is None:
            return False
        if self._enable_faces and self._face_cascade is not None:
            return True
        if self._enable_people and self._hog is not None:
            return True
        return bool(self._enable_objects)

    @staticmethod
    def _load_face_cascade() -> object | None:
        if cv2 is None:
            return None
        haar_dir = Path(cv2.data.haarcascades)
        for name in (
            "haarcascade_frontalface_alt2.xml",
            "haarcascade_frontalface_alt.xml",
            "haarcascade_frontalface_default.xml",
        ):
            path = haar_dir / name
            if not path.exists():
                continue
            cascade = cv2.CascadeClassifier(str(path))
            if cascade is not None and not cascade.empty():
                return cascade
        print("[LocalVision] No Haar face cascade loaded — face detection disabled.")
        return None

    def _ensure_ssd(self) -> bool:
        if self._ssd_net is not None:
            return True
        if self._ssd_failed or not self._enable_objects or cv2 is None:
            return False

        _MODEL_DIR.mkdir(parents=True, exist_ok=True)
        proto = _MODEL_DIR / _PROTOTXT_NAME
        model = _MODEL_DIR / _CAFFEMODEL_NAME

        try:
            if not proto.exists():
                print("[LocalVision] Downloading MobileNet-SSD prototxt…")
                urllib.request.urlretrieve(_PROTOTXT_URL, proto)
            if not model.exists():
                print("[LocalVision] Downloading MobileNet-SSD weights (~23 MB)…")
                urllib.request.urlretrieve(_CAFFEMODEL_URL, model)
            self._ssd_net = cv2.dnn.readNetFromCaffe(str(proto), str(model))
            return True
        except Exception as e:
            print(f"[LocalVision] MobileNet-SSD unavailable: {e}")
            self._ssd_failed = True
            return False

    def _detect_people(self, gray, w: int, h: int) -> list[Detection]:
        if self._hog is None:
            return []
        rects, weights = self._hog.detectMultiScale(
            gray,
            winStride=(8, 8),
            padding=(8, 8),
            scale=1.05,
        )
        out: list[Detection] = []
        for (x, y, rw, rh), wt in zip(rects, weights):
            conf = float(wt) if np.ndim(wt) == 0 else float(wt[0])
            x1, y1, x2, y2 = _clip_box(int(x), int(y), int(x + rw), int(y + rh), w, h)
            if x2 - x1 < 20 or y2 - y1 < 40:
                continue
            out.append(Detection("person", conf, x1, y1, x2, y2, kind=_PERSON_KIND))
        return out

    def _detect_faces(self, gray, w: int, h: int) -> list[Detection]:
        if self._face_cascade is None or self._face_cascade.empty():
            return []
        # CLAHE helps Haar cascades in uneven lighting / webcam exposure
        try:
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            gray_eq = clahe.apply(gray)
        except Exception:
            gray_eq = gray
        min_side = max(24, int(min(w, h) * 0.05))
        scale = 1.08 if self._faces_only else 1.05
        neighbors = 2 if self._faces_only else 3
        faces = self._face_cascade.detectMultiScale(
            gray_eq,
            scaleFactor=scale,
            minNeighbors=neighbors,
            minSize=(min_side, min_side),
            flags=cv2.CASCADE_SCALE_IMAGE,
        )
        out: list[Detection] = []
        for i, (x, y, rw, rh) in enumerate(faces, start=1):
            x1, y1, x2, y2 = _clip_box(int(x), int(y), int(x + rw), int(y + rh), w, h)
            out.append(
                Detection(f"face {i}", 0.9, x1, y1, x2, y2, kind=_FACE_KIND)
            )
        return out

    def _detect_objects(self, bgr, w: int, h: int) -> list[Detection]:
        if not self._ensure_ssd():
            return []

        blob = cv2.dnn.blobFromImage(
            bgr, 0.007843, (300, 300), (127.5, 127.5, 127.5), swapRB=False, crop=False
        )
        self._ssd_net.setInput(blob)
        detections = self._ssd_net.forward()

        out: list[Detection] = []
        for i in range(detections.shape[2]):
            conf = float(detections[0, 0, i, 2])
            if conf < self._min_object_conf:
                continue
            idx = int(detections[0, 0, i, 1])
            if idx <= 0 or idx >= len(_SSD_LABELS):
                continue
            label = _SSD_LABELS[idx]
            if label == "person":
                continue  # prefer HOG person boxes

            box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
            x1, y1, x2, y2 = _clip_box(
                int(box[0]), int(box[1]), int(box[2]), int(box[3]), w, h
            )
            if x2 - x1 < 16 or y2 - y1 < 16:
                continue
            out.append(Detection(label, conf, x1, y1, x2, y2, kind=_OBJECT_KIND))
        return out

    def detect(self, bgr_frame: np.ndarray) -> list[Detection]:
        """Run all enabled detectors on a BGR frame (full resolution)."""
        if cv2 is None or bgr_frame is None or bgr_frame.size == 0:
            return []

        h, w = bgr_frame.shape[:2]
        scale = 1.0
        work = bgr_frame
        if w > self._detect_width:
            scale = self._detect_width / w
            nh = int(h * scale)
            work = cv2.resize(bgr_frame, (self._detect_width, nh))
        wh, ww = work.shape[:2]
        gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)

        with self._lock:
            found: list[Detection] = []
            if self._enable_people:
                found.extend(self._detect_people(gray, ww, wh))
            if self._enable_faces:
                found.extend(self._detect_faces(gray, ww, wh))
            if self._enable_objects:
                found.extend(self._detect_objects(work, ww, wh))

        if scale != 1.0:
            inv = 1.0 / scale
            found = [
                Detection(
                    d.label, d.confidence,
                    int(d.x1 * inv), int(d.y1 * inv),
                    int(d.x2 * inv), int(d.y2 * inv),
                    d.kind,
                )
                for d in found
            ]

        return _nms_by_kind(found, thresh=0.4)

    @staticmethod
    def summary_text(detections: list[Detection], max_items: int = 8) -> str:
        if not detections:
            return "No face detected"
        faces = [d for d in detections if d.kind == _FACE_KIND]
        if faces and len(faces) == len(detections):
            n = len(faces)
            return "1 face" if n == 1 else f"{n} faces"
        parts: list[str] = []
        for d in detections[:max_items]:
            if d.kind == _FACE_KIND:
                parts.append(d.label)
            elif d.confidence > 0:
                parts.append(f"{d.label} {int(d.confidence * 100)}%")
            else:
                parts.append(d.label)
        extra = len(detections) - max_items
        if extra > 0:
            parts.append(f"+{extra} more")
        return " · ".join(parts)
