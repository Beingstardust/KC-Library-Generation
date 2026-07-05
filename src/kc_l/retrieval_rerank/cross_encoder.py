from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence


def slugify_model_name(model_name: str) -> str:
    return model_name.lower().replace("/", "_").replace(":", "_").replace("-", "_")


def candidate_local_model_dirs(repo_root: Path, model_name: str) -> list[Path]:
    root = (repo_root / "data" / "reranker_models").resolve()
    names = [slugify_model_name(model_name)]
    if "/" in model_name:
        names.append(slugify_model_name(model_name.split("/")[-1]))
    seen: set[Path] = set()
    out: list[Path] = []
    for name in names:
        path = (root / name).resolve()
        if path in seen:
            continue
        seen.add(path)
        out.append(path)
    return out


def local_model_dir(repo_root: Path, model_name: str) -> Path:
    return candidate_local_model_dirs(repo_root, model_name)[0]


def has_model_weights(model_dir: Path) -> bool:
    direct_weight_files = [
        "model.safetensors",
        "pytorch_model.bin",
        "model.safetensors.index.json",
    ]
    if any((model_dir / name).exists() for name in direct_weight_files):
        return True
    return any(model_dir.glob("model-*-of-*.safetensors"))


def import_status() -> Mapping[str, bool]:
    return {
        "torch": importlib.util.find_spec("torch") is not None,
        "transformers": importlib.util.find_spec("transformers") is not None,
        "sentence_transformers": importlib.util.find_spec("sentence_transformers") is not None,
    }


def install_missing_stack() -> None:
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "torch", "transformers", "sentence-transformers"],
        check=True,
        timeout=7200,
    )


def choose_device(preferred: str) -> str:
    import torch

    requested = (preferred or "auto").strip().lower()
    if requested == "cpu":
        return "cpu"
    if requested == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("Configured reranker device cuda but torch.cuda.is_available() is false.")
        return "cuda"
    return "cuda" if torch.cuda.is_available() else "cpu"


def resolve_device_candidates(preferred: str) -> list[str]:
    requested = (preferred or "auto").strip().lower()
    chosen = choose_device(requested)
    if requested == "auto" and chosen == "cuda":
        return ["cuda", "cpu"]
    return [chosen]


def is_cuda_runtime_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return "cuda" in text or "cublas" in text or "nccl" in text or "acceleratorerror" in text


def ensure_local_model(repo_root: Path, model_name: str) -> Path:
    direct_path = Path(model_name).expanduser()
    if direct_path.exists() and direct_path.is_dir():
        if not has_model_weights(direct_path) or not (direct_path / "config.json").exists():
            raise RuntimeError(f"Local model directory is missing required files: {direct_path}")
        return direct_path.resolve()

    candidate_dirs = candidate_local_model_dirs(repo_root, model_name)
    for model_dir in candidate_dirs:
        if has_model_weights(model_dir) and (model_dir / "config.json").exists():
            return model_dir
    model_dir = candidate_dirs[0]
    model_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    from huggingface_hub import snapshot_download

    snapshot_download(repo_id=model_name, local_dir=str(model_dir), max_workers=1)
    if not has_model_weights(model_dir):
        raise RuntimeError(f"Model download incomplete for {model_name} at {model_dir}")
    return model_dir


@dataclass
class RerankerBootstrapResult:
    chosen_model: str
    model_dir: str
    device: str
    batch_size: int
    smoke_query: str
    smoke_sentence: str
    smoke_score: float
    used_fallback: bool
    import_status: Mapping[str, bool]
    model_files: Sequence[str]
    attempts: Sequence[Mapping[str, Any]]

    def as_dict(self) -> Mapping[str, Any]:
        return asdict(self)


class CrossEncoderReranker:
    def __init__(self, *, model_name: str, model_dir: Path, device: str, batch_size: int) -> None:
        from sentence_transformers.cross_encoder import CrossEncoder

        self.model_name = model_name
        self.model_dir = model_dir
        self.device = device
        self.batch_size = batch_size
        self._model = CrossEncoder(
            str(model_dir),
            device=device,
            trust_remote_code=model_name.startswith("BAAI/"),
            local_files_only=True,
        )

    def score_pairs(self, pairs: Sequence[tuple[str, str]]) -> list[float]:
        if not pairs:
            return []
        raw = self._model.predict(list(pairs), batch_size=self.batch_size, show_progress_bar=False)
        return [float(item) for item in raw]


def bootstrap_reranker(
    *,
    repo_root: Path,
    preferred_model: str,
    fallback_models: Sequence[str],
    device: str,
    batch_size: int,
    smoke_query: str,
    smoke_sentence: str,
) -> tuple[RerankerBootstrapResult, CrossEncoderReranker]:
    status = import_status()
    if not all(status.values()):
        install_missing_stack()
        status = import_status()
    if not all(status.values()):
        raise RuntimeError(f"Reranker stack unavailable after install attempt: {json.dumps(status, indent=2)}")
    device_candidates = resolve_device_candidates(device)
    attempts: list[Mapping[str, Any]] = []
    candidates = [preferred_model] + [str(item) for item in fallback_models]
    for index, model_name in enumerate(candidates):
        try:
            model_dir = ensure_local_model(repo_root, model_name)
        except Exception as exc:
            attempts.append(
                {
                    "model": model_name,
                    "device": "download",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            continue
        for device_index, chosen_device in enumerate(device_candidates):
            try:
                scorer = CrossEncoderReranker(
                    model_name=model_name,
                    model_dir=model_dir,
                    device=chosen_device,
                    batch_size=int(batch_size),
                )
                score = scorer.score_pairs([(smoke_query, smoke_sentence)])[0]
                files = sorted(path.name for path in model_dir.iterdir() if path.is_file())
                return (
                    RerankerBootstrapResult(
                        chosen_model=model_name,
                        model_dir=(
                            model_dir.relative_to(repo_root).as_posix()
                            if model_dir.is_relative_to(repo_root)
                            else model_dir.as_posix()
                        ),
                        device=chosen_device,
                        batch_size=int(batch_size),
                        smoke_query=smoke_query,
                        smoke_sentence=smoke_sentence,
                        smoke_score=float(score),
                        used_fallback=index > 0 or device_index > 0,
                        import_status=status,
                        model_files=files,
                        attempts=attempts,
                    ),
                    scorer,
                )
            except Exception as exc:
                attempts.append(
                    {
                        "model": model_name,
                        "device": chosen_device,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
                auto_cpu_retry = (
                    (device or "auto").strip().lower() == "auto"
                    and chosen_device == "cuda"
                    and device_index + 1 < len(device_candidates)
                    and is_cuda_runtime_error(exc)
                )
                if auto_cpu_retry:
                    continue
                if chosen_device == "cpu" or (device or "auto").strip().lower() == "cuda":
                    break
    raise RuntimeError(f"Unable to bootstrap any reranker: {json.dumps(attempts, indent=2)}")
