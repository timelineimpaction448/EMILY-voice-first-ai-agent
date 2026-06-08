#!/usr/bin/env python3
"""Install the ONNX Runtime wheel that matches Emily's GPU acceleration profile."""

from __future__ import annotations

import importlib.metadata
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_gpu_detect():
    """Load gpu_detect without importing core.voice (avoids circular imports)."""
    import importlib.util

    path = ROOT / "core" / "voice" / "gpu_detect.py"
    spec = importlib.util.spec_from_file_location("emily_gpu_detect", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load GPU detect module from {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod

ORT_VARIANTS = (
    "onnxruntime",
    "onnxruntime-gpu",
    "onnxruntime-webgpu",
    "onnxruntime-directml",
)


def _installed_ort_package() -> str | None:
    for name in ORT_VARIANTS:
        try:
            importlib.metadata.version(name)
            return name
        except importlib.metadata.PackageNotFoundError:
            continue
    return None


def _pip_install(package: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "pip", "install", package],
        check=True,
    )


def _pip_uninstall_all() -> None:
    subprocess.run(
        [sys.executable, "-m", "pip", "uninstall", "-y", *ORT_VARIANTS],
        check=False,
    )


def main() -> int:
    gpu_detect = _load_gpu_detect()
    detect_gpu_accel_profile = gpu_detect.detect_gpu_accel_profile
    get_available_ort_providers = gpu_detect.get_available_ort_providers
    resolve_install_package = gpu_detect.resolve_install_package

    profile = detect_gpu_accel_profile()
    target = profile.package

    installed = _installed_ort_package()
    if installed == target:
        providers = get_available_ort_providers()
        if profile.backend == "cpu" or any(
            p in providers
            for p in ("CUDAExecutionProvider", "WebGpuExecutionProvider", "DmlExecutionProvider")
        ):
            print(f"[Emily] ONNX Runtime already installed: {installed} ({profile.reason})")
            return 0

    print(f"[Emily] Installing ONNX Runtime: {target} ({profile.reason})")
    _pip_uninstall_all()
    _pip_install(target)

    profile = resolve_install_package(detect_gpu_accel_profile())
    if profile.package != target:
        print(f"[Emily] WebGPU unavailable — installing {profile.package} ({profile.reason})")
        _pip_uninstall_all()
        _pip_install(profile.package)

    providers = get_available_ort_providers()
    print(f"[Emily] ONNX Runtime ready: {profile.package}")
    print(f"[Emily] Available providers: {', '.join(providers) or 'none'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as e:
        print(f"[Emily] ONNX Runtime install failed: {e}")
        raise SystemExit(1)
