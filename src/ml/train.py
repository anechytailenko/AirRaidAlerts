"""Training loop for A3T-GCN (plans/06 §2–§7).

Run: `PYTHONPATH=src python -m ml.train`  (or via the Kaggle notebook built by scripts/build_notebook.py).

MLOps (plans/06 §4): Weights & Biases + Weave tracking, tqdm epoch/batch bars, per-epoch checkpoints +
`best_model.pt`. After training: threshold calibration (§7) and the full inference-artifact bundle (§6).

Note: heavy/optional deps (wandb, weave) are imported lazily inside `init_tracking()` so importing this
module (e.g. in tooling) never requires them; on Kaggle the notebook pip-installs them first.
"""
from __future__ import annotations

import json
import os
import random
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader
from tqdm import tqdm

from .config import Config
from .dataset import build_datasets
from .losses import MultiHorizonBCE, calibrate_thresholds, pos_weight_from_targets
from .model import A3TGCN

_WANDB_ON = False  # set True inside init_tracking() if W&B is reachable


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def init_tracking() -> None:
    """Hardcoded Weights & Biases + Weave init (per explicit user instruction)."""
    global _WANDB_ON
    try:
        import wandb
        import weave
        wandb.login(key="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")
        weave.init('anna-nechytailenko-kyiv-school-of-economics/alert_time_series')
        _WANDB_ON = True
    except Exception as e:  # offline / not installed → train without remote logging, never crash
        print(f"[tracking] W&B/Weave unavailable, continuing without it: {e}")
        _WANDB_ON = False


def _wandb_log(payload: dict) -> None:
    if _WANDB_ON:
        try:
            import wandb
            wandb.log(payload)
        except Exception:
            pass


def _wandb_log_artifacts(art_dir: Path, best_ckpt: Path) -> None:
    """Upload the inference bundle to W&B as a versioned model Artifact (Bug 2)."""
    if not _WANDB_ON:
        return
    try:
        import wandb
        art = wandb.Artifact("a3tgcn-stgnn", type="model")
        files = ["best_model.pt", "model_config.json", "feature_scaler.json", "edge_index.pt",
                 "node_mapping.json", "thresholds.json", "metrics.json", "run_metadata.json"]
        for name in files:
            p = art_dir / name
            if p.exists():
                art.add_file(str(p))
        if best_ckpt.exists() and not (art_dir / "best_model.pt").exists():
            art.add_file(str(best_ckpt))
        wandb.log_artifact(art)
        print("[wandb] logged model artifact 'a3tgcn-stgnn'")
    except Exception as e:
        print(f"[wandb] artifact logging failed: {e}")


def _wandb_finish() -> None:
    """Close the run so the dashboard stops showing it as 'Running' (Bug 1)."""
    if not _WANDB_ON:
        return
    try:
        import wandb
        if wandb.run is not None:
            wandb.finish()
            print("[wandb] run finished")
    except Exception as e:
        print(f"[wandb] finish failed: {e}")


@torch.no_grad()
def evaluate(model, loader, edge_index, device, horizon):
    """Return (probs, targets) flattened to [total*N, H]."""
    model.eval()
    P, Yt = [], []
    for x, y in loader:
        x = x.to(device)
        logits = model(x, edge_index.to(device))
        P.append(torch.sigmoid(logits).cpu().reshape(-1, horizon).numpy())
        Yt.append(y.reshape(-1, horizon).numpy())
    if not P:
        return np.zeros((0, horizon)), np.zeros((0, horizon))
    return np.concatenate(P), np.concatenate(Yt)


def compute_metrics(probs, targets, horizon) -> dict:
    from sklearn.metrics import average_precision_score, brier_score_loss, log_loss
    m = {}
    for k in range(horizon):
        p, y = probs[:, k], targets[:, k]
        key = f"k{k + 1}"
        if len(np.unique(y)) < 2:  # degenerate fold (all 0 or all 1)
            m[key] = {"pr_auc": float("nan"), "brier": float(np.mean((p - y) ** 2)), "log_loss": float("nan")}
            continue
        m[key] = {
            "pr_auc": float(average_precision_score(y, p)),
            "brier": float(brier_score_loss(y, p)),
            "log_loss": float(log_loss(y, np.clip(p, 1e-7, 1 - 1e-7), labels=[0, 1])),
        }
    valid = [m[f"k{k+1}"]["pr_auc"] for k in range(horizon) if not np.isnan(m[f"k{k+1}"]["pr_auc"])]
    m["mean_pr_auc"] = float(np.mean(valid)) if valid else float("nan")
    return m


def train_one_epoch(model, loader, edge_index, loss_fn, optimizer, device, cfg, epoch) -> float:
    model.train()
    total, n = 0.0, 0
    bar = tqdm(loader, desc=f"epoch {epoch} [train]", leave=False)
    for x, y in bar:
        x, y = x.to(device), y.to(device)
        optimizer.zero_grad()
        loss = loss_fn(model(x, edge_index.to(device)), y)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.grad_clip)
        optimizer.step()
        total += loss.item() * x.size(0)
        n += x.size(0)
        bar.set_postfix(loss=f"{loss.item():.4f}", lr=f"{optimizer.param_groups[0]['lr']:.2e}")
    return total / max(n, 1)


def save_artifacts(out: Path, model, cfg, data, val_metrics, test_metrics, thresholds, run_id) -> None:
    out.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), out / "best_model.pt")  # bundle root copy (self-contained for inference)
    torch.save(data["edge_index"], out / "edge_index.pt")
    (out / "feature_scaler.json").write_text(json.dumps(data["scaler"].to_dict(), indent=2))
    (out / "model_config.json").write_text(json.dumps({
        "in_channels": cfg.num_features, "window": cfg.window, "hidden": cfg.hidden,
        "num_layers": cfg.num_layers, "dropout": cfg.dropout, "horizon": cfg.horizon,
        "feature_cols": cfg.feature_cols, "horizons": list(range(1, cfg.horizon + 1)),
    }, indent=2))
    (out / "node_mapping.json").write_text(json.dumps({
        "idx_to_oblast_id": data["mapping"]["idx_to_oblast_id"],
        "idx_to_name": data["mapping"]["idx_to_name"],
    }, indent=2))
    (out / "thresholds.json").write_text(json.dumps(thresholds, indent=2))
    (out / "metrics.json").write_text(json.dumps({"val": val_metrics, "test": test_metrics}, indent=2))
    (out / "run_metadata.json").write_text(json.dumps({
        "wandb_run_id": run_id, "seed": cfg.seed,
        "built_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fbeta": cfg.fbeta,
    }, indent=2))


def _report_test(test_metrics: dict, horizon: int) -> None:
    """Print AND log the holdout-test metrics so the evaluation is visible (Bug 3)."""
    if not test_metrics:
        print("[test] holdout TEST split produced no metrics (empty split?).")
        return
    mean = test_metrics.get("mean_pr_auc", float("nan"))
    per_k = " ".join(
        f"k{k+1}={test_metrics.get(f'k{k+1}', {}).get('pr_auc', float('nan')):.3f}" for k in range(horizon)
    )
    print(f"[test] HOLDOUT TEST mean_PR_AUC={mean:.4f} | {per_k}")
    if _WANDB_ON:
        try:
            import wandb
            payload = {"test_mean_pr_auc": mean}
            for k in range(horizon):
                kk = f"k{k+1}"
                if kk in test_metrics:
                    payload[f"test_pr_auc_{kk}"] = test_metrics[kk]["pr_auc"]
                    payload[f"test_brier_{kk}"] = test_metrics[kk]["brier"]
            wandb.log(payload)
            wandb.summary.update(payload)
        except Exception:
            pass


def main(cfg: Config | None = None) -> None:
    cfg = cfg or Config()
    set_seed(cfg.seed)
    init_tracking()
    run_id = None
    if _WANDB_ON:
        try:
            import wandb
            run = wandb.init(project="airraid-stgnn", config=cfg.__dict__)
            run_id = run.id if run is not None else None
        except Exception as e:
            print(f"[wandb] init failed: {e}")

    try:
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        print(f"[train] device={device}")
        data = build_datasets(cfg)
        edge_index = data["edge_index"]
        train_loader = DataLoader(data["train"], batch_size=cfg.batch_size, shuffle=True)
        val_loader = DataLoader(data["val"], batch_size=cfg.batch_size, shuffle=False)
        test_loader = DataLoader(data["test"], batch_size=cfg.batch_size, shuffle=False)
        print(f"[data] windows — train={len(data['train'])} val={len(data['val'])} test={len(data['test'])}")

        pos_w = pos_weight_from_targets(data["train"].Y, cfg.horizon)
        loss_fn = MultiHorizonBCE(pos_weight=pos_w).to(device)
        model = A3TGCN(cfg.num_features, cfg.hidden, cfg.horizon, cfg.num_layers, cfg.dropout).to(device)
        if _WANDB_ON:
            try:
                import wandb
                wandb.watch(model, log="all")
            except Exception:
                pass
        optimizer = torch.optim.AdamW(model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode="max", factor=0.5, patience=4)

        ckpt_dir = Path(cfg.artifacts_dir) / "checkpoints"
        ckpt_dir.mkdir(parents=True, exist_ok=True)
        print(f"[artifacts] writing under {cfg.artifacts_dir}")
        best_pr, best_epoch, since_best = -1.0, -1, 0

        for epoch in tqdm(range(1, cfg.epochs + 1), desc="epochs"):
            tr_loss = train_one_epoch(model, train_loader, edge_index, loss_fn, optimizer, device, cfg, epoch)
            vp, vy = evaluate(model, val_loader, edge_index, device, cfg.horizon)
            vm = compute_metrics(vp, vy, cfg.horizon)
            mean_pr = vm["mean_pr_auc"]
            scheduler.step(mean_pr if not np.isnan(mean_pr) else 0.0)
            print(f"epoch {epoch}: train_loss={tr_loss:.4f} val_mean_PR_AUC={mean_pr:.4f}")
            _wandb_log({"epoch": epoch, "train_loss": tr_loss, "val_mean_pr_auc": mean_pr,
                        "lr": optimizer.param_groups[0]["lr"],
                        **{f"val_pr_auc_{k}": v["pr_auc"] for k, v in vm.items() if k.startswith("k")}})

            # checkpoint EVERY epoch (resumable) + track best
            torch.save({"epoch": epoch, "model_state": model.state_dict(),
                        "optimizer_state": optimizer.state_dict(), "scheduler_state": scheduler.state_dict(),
                        "val_metrics": vm, "rng": torch.get_rng_state()}, ckpt_dir / f"epoch_{epoch:03d}.pt")
            if not np.isnan(mean_pr) and mean_pr > best_pr:
                best_pr, best_epoch, since_best = mean_pr, epoch, 0
                torch.save(model.state_dict(), ckpt_dir / "best_model.pt")
            else:
                since_best += 1
                if since_best >= cfg.patience:
                    print(f"early stop at epoch {epoch} (best={best_epoch}, PR-AUC={best_pr:.4f})")
                    break

        # reload best, calibrate thresholds on val, evaluate the HOLDOUT TEST split, persist artifacts
        best_path = ckpt_dir / "best_model.pt"
        if best_path.exists():
            model.load_state_dict(torch.load(best_path, map_location=device))
        vp, vy = evaluate(model, val_loader, edge_index, device, cfg.horizon)
        thresholds = calibrate_thresholds(vp, vy, beta=cfg.fbeta) if len(vp) else {}
        val_metrics = compute_metrics(vp, vy, cfg.horizon) if len(vp) else {}

        tp, ty = evaluate(model, test_loader, edge_index, device, cfg.horizon)
        test_metrics = compute_metrics(tp, ty, cfg.horizon) if len(tp) else {}
        _report_test(test_metrics, cfg.horizon)  # Bug 3: make the holdout-test evaluation visible

        out = Path(cfg.artifacts_dir)
        save_artifacts(out, model, cfg, data, val_metrics, test_metrics, thresholds, run_id)
        _wandb_log_artifacts(out, best_path)  # Bug 2: upload model artifact to W&B
        print(f"[done] best epoch={best_epoch} val_mean_PR_AUC={best_pr:.4f}; artifacts → {out}")
    finally:
        _wandb_finish()  # Bug 1: always close the W&B run so it stops showing 'Running'


if __name__ == "__main__":
    main()
