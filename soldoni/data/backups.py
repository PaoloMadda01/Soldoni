import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import sqlite3
from soldoni.data import store

logger = logging.getLogger(__name__)

_REQUIRED_COLUMNS = {
    "instruments": {"isin", "yahoo_ticker", "name", "native_currency", "asset_class",
                    "macro_area", "geo_weights", "sector", "sector_weights", "excluded"},
    "transactions": {"trade_date", "value_date", "isin", "op_type", "quantity",
                     "amount_eur", "price_native", "fx_rate", "commission_eur", "source",
                     "raw_desc"},
    "prices_cache": {"ticker", "date", "close_native", "adj_close_native"},
    "fx_cache": {"pair", "date", "rate"},
    "watchlist": {"ticker", "isin", "name", "asset_class", "added_at"},
    "allocation_targets": {"isin", "target_weight"},
}


@dataclass(frozen=True)
class BackupInfo:
    path: Path
    size_bytes: int
    modified_at: datetime


def backup_directory(conn: sqlite3.Connection) -> Path:
    for _, name, path in conn.execute("PRAGMA database_list").fetchall():
        if name == "main" and path:
            return Path(path).resolve().parent / "backups"
    raise ValueError("Il database in memoria non può essere salvato nella cartella backup.")


def _open_read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def validate_backup(path: str | Path) -> None:
    candidate = Path(path)
    if not candidate.is_file():
        raise ValueError("La copia selezionata non esiste.")
    try:
        conn = _open_read_only(candidate)
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise ValueError("La copia SQLite non supera il controllo di integrità.")
            tables = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            missing_tables = set(_REQUIRED_COLUMNS) - tables
            if missing_tables:
                raise ValueError("Tabelle mancanti: " + ", ".join(sorted(missing_tables)))
            required_columns = dict(_REQUIRED_COLUMNS)
            if "etf_expense_ratios" in tables:
                required_columns["etf_expense_ratios"] = {
                    "isin", "expense_ratio", "source", "saved_on"}
            for table, required in required_columns.items():
                columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
                missing_columns = required - columns
                if missing_columns:
                    raise ValueError(
                        f"Colonne mancanti in {table}: " + ", ".join(sorted(missing_columns)))
        finally:
            conn.close()
    except sqlite3.Error as e:
        raise ValueError(f"Copia SQLite non valida: {e}") from e


def create_backup(conn: sqlite3.Connection, directory: str | Path,
                  reason: str) -> Path:
    target_dir = Path(directory)
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_reason = "".join(c if c.isalnum() else "_" for c in reason).strip("_") or "manuale"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    target = target_dir / f"soldoni_{timestamp}_{safe_reason}.db"
    temporary = target.with_suffix(".tmp")
    destination = None
    try:
        conn.commit()
        destination = sqlite3.connect(temporary)
        conn.backup(destination)
        destination.close()
        destination = None
        validate_backup(temporary)
        os.replace(temporary, target)
        return target
    except Exception:
        logger.exception("Creazione backup SQLite fallita")
        if destination is not None:
            destination.close()
        if temporary.exists():
            temporary.unlink()
        raise


def list_backups(directory: str | Path) -> list[BackupInfo]:
    target_dir = Path(directory)
    if not target_dir.exists():
        return []
    infos = [
        BackupInfo(path, path.stat().st_size,
                   datetime.fromtimestamp(path.stat().st_mtime))
        for path in target_dir.glob("soldoni_*.db")
        if path.is_file()
    ]
    return sorted(infos, key=lambda info: info.modified_at, reverse=True)


def restore_backup(conn: sqlite3.Connection, path: str | Path,
                   directory: str | Path) -> Path:
    target_dir = Path(directory).resolve()
    candidate = Path(path).resolve()
    if candidate.parent != target_dir:
        raise ValueError("La copia selezionata non appartiene alla cartella backup di Soldoni.")
    available = {info.path.resolve() for info in list_backups(target_dir)}
    if candidate not in available:
        raise ValueError("La copia selezionata non è presente tra i backup di Soldoni.")
    validate_backup(candidate)
    safety_backup = create_backup(conn, target_dir, "prima_del_ripristino")
    source = None
    try:
        conn.commit()
        source = _open_read_only(candidate)
        source.backup(conn)
        store.initialize_schema(conn)
        conn.commit()
        return safety_backup
    except Exception:
        logger.exception("Ripristino backup SQLite fallito")
        raise
    finally:
        if source is not None:
            source.close()
