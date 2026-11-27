"""
Smart GPU Workload Classifier & Model Extractor.
Turns raw process names (e.g. `python.exe`, `ollama_llama_server`) and command lines
into human-readable workload badges (e.g. `🦙 Ollama (qwen3:32b)`, `⚡ vLLM (Llama-3.3)`,
`🎨 ComfyUI`, `🔥 PyTorch (train.py)`, `🎬 FFmpeg`, `🎮 Cyberpunk2077.exe`).
"""

import json
import os
import re
import time
import urllib.request
from typing import Dict, List, Optional, Tuple

import psutil

from core.gpu_types import GpuProcess


_CMDLINE_CACHE: Dict[int, Tuple[float, str]] = {}
_OLLAMA_CACHE: Tuple[float, List[str]] = (0.0, [])


def get_local_ollama_models(ttl: float = 8.0) -> List[str]:
    """
    Queries local Ollama API (http://127.0.0.1:11434/api/ps) with a tiny timeout
    to discover currently loaded models without spawning any subprocesses.
    """
    global _OLLAMA_CACHE
    now = time.time()
    if now - _OLLAMA_CACHE[0] < ttl:
        return _OLLAMA_CACHE[1]

    models: List[str] = []
    try:
        req = urllib.request.Request("http://127.0.0.1:11434/api/ps", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=0.25) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        for m in data.get("models", []):
            mname = str(m.get("name") or m.get("model") or "").strip()
            if mname:
                models.append(mname)
    except Exception:
        pass
    _OLLAMA_CACHE = (now, models)
    return models


def get_local_cmdline(pid: int, ttl: float = 15.0) -> str:
    """Cached psutil cmdline lookup by PID."""
    now = time.time()
    cached = _CMDLINE_CACHE.get(pid)
    if cached and (now - cached[0]) < ttl:
        return cached[1]
    cmd = ""
    try:
        p = psutil.Process(pid)
        parts = p.cmdline()
        if parts:
            cmd = " ".join(parts)[:500]
    except Exception:
        pass
    _CMDLINE_CACHE[pid] = (now, cmd)
    # Trim stale cache entries occasionally
    if len(_CMDLINE_CACHE) > 256:
        cutoff = now - 60.0
        for k in list(_CMDLINE_CACHE.keys()):
            if _CMDLINE_CACHE[k][0] < cutoff:
                _CMDLINE_CACHE.pop(k, None)
    return cmd


def _extract_model_arg(cmdline: str) -> str:
    """Extracts a short model name or GGUF filename from common LLM CLI flags."""
    if not cmdline:
        return ""
    # Look for --model / -m / --served-model-name / .gguf / .safetensors
    patterns = [
        r"(?:--served-model-name|--model|-m)\s+['\"]?([^\s'\"]+)",
        r"([A-Za-z0-9._-]+\.gguf)",
    ]
    for pat in patterns:
        m = re.search(pat, cmdline, re.IGNORECASE)
        if m:
            raw = m.group(1).strip().strip("\"'")
            # Strip long directory paths
            base = os.path.basename(raw.rstrip("/\\"))
            if len(base) > 32:
                base = base[:29] + "..."
            return base
    return ""


def _extract_python_script(cmdline: str) -> str:
    """Extracts the primary .py script or -m module from a Python command line."""
    if not cmdline:
        return ""
    m_mod = re.search(r"-m\s+([A-Za-z0-9_.-]+)", cmdline)
    if m_mod:
        return m_mod.group(1)
    m_py = re.search(r"([A-Za-z0-9_.-]+\.py)\b", cmdline)
    if m_py:
        return os.path.basename(m_py.group(1))
    return ""


def classify_workload(
    name: str,
    cmdline: str = "",
    ollama_models: Optional[List[str]] = None,
) -> Tuple[str, str]:
    """
    Returns (friendly_label, category) for a GPU process.
    Categories: 'AI/LLM', 'AI/Image', 'AI/ML', 'Media/3D', 'Game', 'Browser', 'System', 'Compute'
    """
    n_low = (name or "").lower()
    c_low = (cmdline or "").lower()
    combined = f"{n_low} {c_low}"

    # 1. Ollama
    if "ollama" in combined:
        model_tag = ""
        if ollama_models:
            model_tag = ", ".join(ollama_models[:2])
        else:
            model_tag = _extract_model_arg(cmdline)
        if model_tag:
            return (f"🦙 Ollama ({model_tag})", "AI/LLM")
        return ("🦙 Ollama Runner", "AI/LLM")

    # 2. vLLM
    if "vllm" in combined:
        mod = _extract_model_arg(cmdline)
        return (f"⚡ vLLM ({mod})" if mod else "⚡ vLLM Server", "AI/LLM")

    # 3. SGLang / TGI / TabbyAPI / ExLlama / Aphrodite
    if "sglang" in combined:
        mod = _extract_model_arg(cmdline)
        return (f"⚡ SGLang ({mod})" if mod else "⚡ SGLang", "AI/LLM")
    if "text-generation" in combined or "tgi" in n_low:
        mod = _extract_model_arg(cmdline)
        return (f"⚡ TGI ({mod})" if mod else "⚡ Text-Gen-Inference", "AI/LLM")

    # 4. llama.cpp / llama-server / koboldcpp / LM Studio / Jan
    if "lm studio" in combined or "lmstudio" in combined:
        mod = _extract_model_arg(cmdline)
        return (f"🧠 LM Studio ({mod})" if mod else "🧠 LM Studio", "AI/LLM")
    if any(k in combined for k in ("llama-server", "llama_server", "llama-cli", "llama.cpp", "koboldcpp", "llamacpp")):
        mod = _extract_model_arg(cmdline)
        return (f"🦙 llama.cpp ({mod})" if mod else "🦙 llama.cpp", "AI/LLM")

    # 5. Image / Video Gen: ComfyUI, Automatic1111, Forge, Diffusers, InvokeAI
    if "comfyui" in combined or ("main.py" in c_low and "comfy" in c_low):
        return ("🎨 ComfyUI", "AI/Image")
    if "stable-diffusion" in combined or "webui" in combined and ("sd" in combined or "forge" in combined):
        return ("🎨 Stable Diffusion WebUI", "AI/Image")
    if "invokeai" in combined:
        return ("🎨 InvokeAI", "AI/Image")

    # 6. Apple MLX / Whisper / PyTorch / TensorFlow / JAX / Jupyter
    if "mlx" in combined:
        script = _extract_python_script(cmdline)
        return (f"🍎 MLX ({script})" if script else "🍎 Apple MLX", "AI/ML")
    if "whisper" in combined:
        return ("🎙️ Whisper ASR", "AI/ML")
    if any(k in combined for k in ("torchrun", "deepspeed", "accelerate", "train", "finetune", "lora", "unsloth", "axolotl")):
        script = _extract_python_script(cmdline)
        return (f"🔥 AI Training ({script})" if script else "🔥 AI Training", "AI/ML")
    if "jupyter" in combined or "ipykernel" in combined:
        return ("📓 Jupyter Kernel", "AI/ML")
    if n_low in ("python", "python3", "python.exe", "pythonw.exe") or n_low.startswith("python3."):
        script = _extract_python_script(cmdline)
        if script:
            return (f"🐍 Python ({script})", "AI/ML")
        return ("🐍 Python GPU", "AI/ML")

    # 7. Media / Video / 3D Rendering
    if any(k in n_low for k in ("ffmpeg", "handbrake", "obs64", "obs", "davinci", "resolve", "premiere", "afterfx", "plex")):
        clean = name.replace(".exe", "")
        return (f"🎬 {clean}", "Media/3D")
    if any(k in n_low for k in ("blender", "unreal", "unity", "maya", "houdini", "cinema 4d", "godot")):
        clean = name.replace(".exe", "")
        return (f"🧊 {clean}", "Media/3D")

    # 8. Browsers & Electron / Desktop Compositors
    if any(k in n_low for k in ("chrome", "msedge", "firefox", "brave", "opera", "vivaldi", "zen", "arc", "electron", "code", "discord", "slack", "teams", "spotify")):
        clean = name.replace(".exe", "")
        return (f"🌐 {clean}", "Browser")
    if any(k in n_low for k in ("dwm", "explorer", "csrss", "xorg", "xwayland", "kwin", "gnome-shell", "hyprland", "sway", "windowserver", "gpu-sentry")):
        clean = name.replace(".exe", "")
        return (f"🖥️ {clean}", "System")

    # 9. Games / Steam / Vulkan / DX12
    if any(k in combined for k in ("steamapps", "epic games", "shipping.exe", "win64-shipping", "proton", "wine64")):
        clean = name.replace(".exe", "")
        return (f"🎮 {clean}", "Game")

    clean = name.replace(".exe", "") if name else "GPU Process"
    return (f"⚙ {clean}", "Compute")


def enrich_local_process(proc: GpuProcess, ollama_models: Optional[List[str]] = None) -> GpuProcess:
    """Enriches a local GpuProcess with cmdline and friendly workload classification."""
    if not proc.cmdline and proc.pid > 0:
        proc.cmdline = get_local_cmdline(proc.pid)
    label, cat = classify_workload(proc.name, proc.cmdline, ollama_models=ollama_models)
    proc.workload_label = label
    proc.category = cat
    return proc
