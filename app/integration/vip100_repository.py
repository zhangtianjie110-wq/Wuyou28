from __future__ import annotations

from pathlib import Path

from .health import freshness, read_json_object, readonly_sqlite
from .models import Vip100Batch, Vip100Prediction


class Vip100Repository:
    """Read immutable LOCAL_V2 production batches and their settled hits."""

    def __init__(self, production_dir: Path, hash_status_path: Path, strategy_db: Path):
        self.production_dir = Path(production_dir)
        self.hash_status_path = Path(hash_status_path)
        self.strategy_db = Path(strategy_db)

    @property
    def predictions_dir(self) -> Path:
        return self.production_dir / "predictions"

    def latest_issue(self) -> str | None:
        issues = self.list_issues(limit=1)
        return issues[0] if issues else None

    def list_issues(self, limit: int = 200) -> list[str]:
        """Return available immutable production batches, newest first."""
        if limit <= 0 or not self.predictions_dir.is_dir():
            return []
        issues = [
            item.stem
            for item in self.predictions_dir.glob("*.json")
            if item.is_file() and item.stem.isdigit()
        ]
        return sorted(issues, key=int, reverse=True)[:limit]

    def _settlement(self, issue: str) -> tuple[dict[str, bool], str | None]:
        if not self.strategy_db.is_file():
            return {}, None
        with readonly_sqlite(self.strategy_db) as connection:
            period = connection.execute(
                "SELECT actual_result FROM production_periods WHERE issue=?", (int(issue),)
            ).fetchone()
            rows = connection.execute(
                "SELECT algorithm_id, hit FROM production_predictions WHERE issue=?",
                (int(issue),),
            ).fetchall()
        return ({str(row["algorithm_id"]): bool(row["hit"]) for row in rows}, str(period[0]) if period else None)

    def get(self, issue: str | int) -> Vip100Batch | None:
        path = self.predictions_dir / f"{issue}.json"
        if not path.is_file():
            return None
        document = read_json_object(path)
        rows = document.get("records")
        if document.get("source") != "VIP100_LOCAL_V2":
            raise ValueError("VIP100 production source is not VIP100_LOCAL_V2")
        if document.get("prediction_count") != 100 or not isinstance(rows, list) or len(rows) != 100:
            raise ValueError("VIP100 production batch is not exactly 100 rows")
        ids = [str(row.get("algorithm_id", "")) for row in rows]
        if not all(ids) or len(set(ids)) != 100:
            raise ValueError("VIP100 production batch has missing or duplicate algorithm ids")
        hits, actual_result = self._settlement(str(issue))
        predictions = tuple(
            Vip100Prediction(
                position=position,
                algorithm_id=str(row["algorithm_id"]),
                algorithm_name=str(row["algorithm_name"]),
                formula=str(row["formulaText"]),
                prediction=int(row["local_prediction"]),
                combination=str(row["combination"]),
                hit=hits.get(str(row["algorithm_id"])),
            )
            for position, row in enumerate(rows, 1)
        )
        return Vip100Batch(
            issue=str(document["issue"]),
            generated_at=str(document["generated_at"]),
            engine_version=str(document["engine_version"]),
            algorithm_hash=str(document["algorithm_hash"]),
            history_hash=str(document["history_sha256"]),
            input_hash=str(document["yu28_input_sha256"]),
            source=str(document["source"]),
            actual_result=actual_result,
            predictions=predictions,
        )

    def latest(self) -> Vip100Batch | None:
        issue = self.latest_issue()
        return self.get(issue) if issue else None

    def hash_status(self) -> dict:
        try:
            value = read_json_object(self.hash_status_path)
            expected = value.get("standard_sha256")
            current = value.get("current_sha256")
            status = "HASH_OK" if value.get("status") == "HASH_OK" and expected == current else "HASH_MISMATCH"
            return {**value, "status": status}
        except FileNotFoundError:
            return {"status": "OFFLINE"}
        except Exception as exc:
            return {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}

    def status(self) -> dict:
        state_path = self.production_dir / "state.json"
        latest = None
        try:
            latest = self.latest()
        except Exception as exc:
            latest_error = f"{type(exc).__name__}: {exc}"
        else:
            latest_error = None
        try:
            state = read_json_object(state_path)
            current = freshness(state.get("updated_at"), 120)
            status = str(state.get("status", "OFFLINE"))
            if current["status"] == "STALE" and status == "RUNNING":
                status = "STALE"
            return {
                "status": status,
                "latest_issue": latest.issue if latest else None,
                "prediction_count": latest.prediction_count if latest else 0,
                "hash_status": self.hash_status().get("status", "OFFLINE"),
                "source": state.get("primary_source", "LOCAL_V2"),
                "freshness": current,
                "error": latest_error,
            }
        except FileNotFoundError:
            return {
                "status": "OFFLINE",
                "latest_issue": latest.issue if latest else None,
                "prediction_count": latest.prediction_count if latest else 0,
                "hash_status": self.hash_status().get("status", "OFFLINE"),
                "freshness": {"status": "OFFLINE"},
                "error": latest_error,
            }
        except Exception as exc:
            return {
                "status": "ERROR",
                "latest_issue": None,
                "prediction_count": 0,
                "hash_status": "ERROR",
                "error": f"{type(exc).__name__}: {exc}",
            }
