"""Dedicated GPU detection and ONNX Runtime provider selection for Supertonic."""

from __future__ import annotations

import platform
import re
import subprocess
from dataclasses import dataclass
from typing import Literal

GpuBackend = Literal["cpu", "cuda", "webgpu", "directml"]

ORT_PACKAGES: dict[GpuBackend, str] = {
    "cpu": "onnxruntime",
    "cuda": "onnxruntime-gpu",
    "webgpu": "onnxruntime-webgpu",
    "directml": "onnxruntime-directml",
}

PROVIDER_CHAINS: dict[GpuBackend, list[str]] = {
    "cpu": ["CPUExecutionProvider"],
    "cuda": ["CUDAExecutionProvider", "CPUExecutionProvider"],
    "webgpu": ["WebGpuExecutionProvider", "CPUExecutionProvider"],
    "directml": ["DmlExecutionProvider", "CPUExecutionProvider"],
}

_VIRTUAL_PATTERNS = (
    "microsoft basic",
    "meta virtual",
    "remote",
    "virtual",
    "parsec",
    "vmware",
    "citrix",
    "iddcx",
)

_INTEGRATED_INTEL_PATTERNS = (
    "intel(r) uhd",
    "intel(r) hd graphics",
    "intel(r) iris",
    "intel hd graphics",
    "intel uhd graphics",
)

_NVIDIA_DISCRETE_PATTERNS = (
    "geforce",
    "quadro",
    "tesla",
    "rtx ",
    "gtx ",
    "nvidia",
)

_AMD_DISCRETE_PATTERNS = (
    "radeon rx",
    "radeon pro",
    "rx ",
    "rx6",
    "rx7",
    "rx5",
    "rx4",
)

_INTEL_ARC_RE = re.compile(
    r"intel\s+arc|arc\s+(?:pro|a\d|b\d)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class GpuAdapter:
    name: str
    pnp_device_id: str
    kind: Literal["nvidia", "other_discrete", "integrated", "virtual", "unknown"]


@dataclass(frozen=True)
class GpuAccelProfile:
    backend: GpuBackend
    package: str
    adapter_name: str
    reason: str


def _norm(text: str) -> str:
    return (text or "").strip().lower()


def _sanitize_name(text: str) -> str:
    """Strip trademark markers so 'Intel(R) Arc(TM) Pro B60' matches Arc heuristics."""
    s = _norm(text)
    s = re.sub(r"\(r\)|\(tm\)|®|™", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _is_intel_arc(name: str) -> bool:
    return bool(_INTEL_ARC_RE.search(_sanitize_name(name)))


def _is_virtual(name: str, pnp: str) -> bool:
    blob = _norm(f"{name} {pnp}")
    return any(p in blob for p in _VIRTUAL_PATTERNS)


def _classify_adapter(name: str, pnp_device_id: str) -> GpuAdapter:
    name_l = _norm(name)
    pnp_l = _norm(pnp_device_id)

    if _is_virtual(name_l, pnp_l):
        return GpuAdapter(name=name, pnp_device_id=pnp_device_id, kind="virtual")

    if "ven_10de" in pnp_l or any(p in name_l for p in _NVIDIA_DISCRETE_PATTERNS):
        if "geforce" in name_l or "quadro" in name_l or "tesla" in name_l or "rtx" in name_l or "gtx" in name_l or "ven_10de" in pnp_l:
            return GpuAdapter(name=name, pnp_device_id=pnp_device_id, kind="nvidia")

    if _is_intel_arc(name):
        return GpuAdapter(name=name, pnp_device_id=pnp_device_id, kind="other_discrete")

    if any(p in name_l for p in _INTEGRATED_INTEL_PATTERNS):
        return GpuAdapter(name=name, pnp_device_id=pnp_device_id, kind="integrated")

    if "radeon(tm) graphics" in name_l and not any(p in name_l for p in _AMD_DISCRETE_PATTERNS):
        return GpuAdapter(name=name, pnp_device_id=pnp_device_id, kind="integrated")

    if any(p in name_l for p in _AMD_DISCRETE_PATTERNS) or ("ven_1002" in pnp_l and "radeon" in name_l):
        return GpuAdapter(name=name, pnp_device_id=pnp_device_id, kind="other_discrete")

    if "ven_8086" in pnp_l and not _is_intel_arc(name):
        return GpuAdapter(name=name, pnp_device_id=pnp_device_id, kind="integrated")

    return GpuAdapter(name=name, pnp_device_id=pnp_device_id, kind="unknown")


def _dedupe_adapters(adapters: list[GpuAdapter]) -> list[GpuAdapter]:
    seen: set[tuple[str, str]] = set()
    unique: list[GpuAdapter] = []
    for adapter in adapters:
        key = (_sanitize_name(adapter.name), _norm(adapter.pnp_device_id))
        if key in seen:
            continue
        seen.add(key)
        unique.append(adapter)
    return unique


def _list_windows_adapters_wmi() -> list[GpuAdapter]:
    ps = (
        "Get-CimInstance Win32_VideoController | "
        "Select-Object Name, PNPDeviceID | "
        "ConvertTo-Json -Compress"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return []
        import json

        data = json.loads(proc.stdout)
        rows = data if isinstance(data, list) else [data]
        adapters: list[GpuAdapter] = []
        for row in rows:
            name = str(row.get("Name", "")).strip()
            pnp = str(row.get("PNPDeviceID", "")).strip()
            if name:
                adapters.append(_classify_adapter(name, pnp))
        return _dedupe_adapters(adapters)
    except Exception as e:
        print(f"[GPU] WMI adapter enumeration failed: {e}")
        return []


def _list_windows_adapters_enum_display() -> list[GpuAdapter]:
    """Enumerate GPUs via Win32 API when PowerShell/WMI is unavailable."""
    try:
        import ctypes
        from ctypes import wintypes

        class DISPLAY_DEVICEW(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("DeviceName", wintypes.WCHAR * 32),
                ("DeviceString", wintypes.WCHAR * 128),
                ("StateFlags", wintypes.DWORD),
                ("DeviceID", wintypes.WCHAR * 128),
                ("DeviceKey", wintypes.WCHAR * 128),
            ]

        adapters: list[GpuAdapter] = []
        device = DISPLAY_DEVICEW()
        device.cb = ctypes.sizeof(DISPLAY_DEVICEW)
        index = 0
        while ctypes.windll.user32.EnumDisplayDevicesW(None, index, ctypes.byref(device), 0):
            name = str(device.DeviceString).strip()
            pnp = str(device.DeviceID).strip()
            if name:
                adapters.append(_classify_adapter(name, pnp))
            index += 1
        return _dedupe_adapters(adapters)
    except Exception as e:
        print(f"[GPU] EnumDisplayDevices enumeration failed: {e}")
        return []


def _list_windows_adapters() -> list[GpuAdapter]:
    adapters = _list_windows_adapters_wmi()
    if adapters:
        return adapters
    adapters = _list_windows_adapters_enum_display()
    if adapters:
        print("[GPU] Using EnumDisplayDevices adapter enumeration (WMI unavailable)")
    return adapters


def _list_linux_adapters() -> list[GpuAdapter]:
    adapters: list[GpuAdapter] = []
    try:
        proc = subprocess.run(
            ["lspci"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if proc.returncode != 0:
            return adapters
        for line in proc.stdout.splitlines():
            if not re.search(r"VGA|3D|Display", line, re.I):
                continue
            name = line.split(":", 2)[-1].strip() if ":" in line else line.strip()
            pnp = ""
            if "nvidia" in line.lower():
                adapters.append(GpuAdapter(name=name, pnp_device_id="VEN_10DE", kind="nvidia"))
            elif "advanced micro devices" in line.lower() or "amd" in line.lower():
                kind = "other_discrete" if re.search(r"rx|radeon pro", name, re.I) else "integrated"
                adapters.append(GpuAdapter(name=name, pnp_device_id="VEN_1002", kind=kind))
            elif "intel" in line.lower():
                kind = "other_discrete" if "arc" in name.lower() else "integrated"
                adapters.append(GpuAdapter(name=name, pnp_device_id="VEN_8086", kind=kind))
            else:
                adapters.append(_classify_adapter(name, pnp))
    except Exception as e:
        print(f"[GPU] Linux adapter enumeration failed: {e}")
    return adapters


def _pick_best_adapter(adapters: list[GpuAdapter]) -> GpuAdapter | None:
    for kind in ("nvidia", "other_discrete"):
        for adapter in adapters:
            if adapter.kind == kind:
                return adapter
    return None


def _detect_auto_backend() -> GpuAccelProfile:
    system = platform.system().lower()
    if system == "darwin":
        return GpuAccelProfile(
            backend="cpu",
            package=ORT_PACKAGES["cpu"],
            adapter_name="",
            reason="macOS — CPU ONNX Runtime",
        )

    adapters = _list_windows_adapters() if system == "windows" else _list_linux_adapters()
    usable = [a for a in adapters if a.kind not in ("virtual", "integrated")]

    best = _pick_best_adapter(usable)
    if best is None:
        return GpuAccelProfile(
            backend="cpu",
            package=ORT_PACKAGES["cpu"],
            adapter_name="",
            reason="no dedicated GPU detected",
        )

    if best.kind == "nvidia":
        return GpuAccelProfile(
            backend="cuda",
            package=ORT_PACKAGES["cuda"],
            adapter_name=best.name,
            reason=f"NVIDIA discrete GPU: {best.name}",
        )

    return GpuAccelProfile(
        backend="webgpu",
        package=ORT_PACKAGES["webgpu"],
        adapter_name=best.name,
        reason=f"non-NVIDIA discrete GPU: {best.name}",
    )


def _apply_override(backend: GpuBackend, base: GpuAccelProfile) -> GpuAccelProfile:
    if backend == "cpu":
        return GpuAccelProfile(
            backend="cpu",
            package=ORT_PACKAGES["cpu"],
            adapter_name=base.adapter_name,
            reason="forced CPU via config",
        )
    if backend == "cuda":
        return GpuAccelProfile(
            backend="cuda",
            package=ORT_PACKAGES["cuda"],
            adapter_name=base.adapter_name,
            reason="forced CUDA via config",
        )
    if backend == "directml":
        return GpuAccelProfile(
            backend="directml",
            package=ORT_PACKAGES["directml"],
            adapter_name=base.adapter_name,
            reason="forced DirectML via config",
        )
    return GpuAccelProfile(
        backend="webgpu",
        package=ORT_PACKAGES["webgpu"],
        adapter_name=base.adapter_name,
        reason="forced WebGPU via config",
    )


def detect_gpu_accel_profile() -> GpuAccelProfile:
    from core.config import get_supertonic_accel

    auto = _detect_auto_backend()
    override = get_supertonic_accel()
    if override == "auto":
        return auto
    return _apply_override(override, auto)


def get_available_ort_providers() -> list[str]:
    try:
        import onnxruntime as ort

        return list(ort.get_available_providers())
    except Exception:
        return []


def _filter_providers(chain: list[str]) -> list[str]:
    available = set(get_available_ort_providers())
    filtered = [p for p in chain if p in available]
    return filtered or ["CPUExecutionProvider"]


def resolve_ort_providers(profile: GpuAccelProfile) -> list[str]:
    """Map profile to ONNX providers, with runtime fallbacks."""
    providers = _filter_providers(PROVIDER_CHAINS[profile.backend])
    if profile.backend != "cpu" and providers == ["CPUExecutionProvider"]:
        print(
            f"[GPU] {profile.backend} providers unavailable at runtime — "
            "falling back to CPUExecutionProvider"
        )
    return providers


def resolve_install_package(profile: GpuAccelProfile) -> GpuAccelProfile:
    """
    Pick the ONNX wheel to install. On Windows, WebGPU may fall back to DirectML
    when the installed package does not expose WebGpuExecutionProvider.
    """
    if profile.backend != "webgpu" or platform.system().lower() != "windows":
        return profile

    available = set(get_available_ort_providers())
    if "WebGpuExecutionProvider" in available:
        return profile

    return GpuAccelProfile(
        backend="directml",
        package=ORT_PACKAGES["directml"],
        adapter_name=profile.adapter_name,
        reason=f"{profile.reason} — WebGPU unavailable, using DirectML",
    )


def package_for_backend(backend: GpuBackend) -> str:
    return ORT_PACKAGES[backend]
