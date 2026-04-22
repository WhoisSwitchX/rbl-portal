# ═══════════════════════════════════════════════════════════════
# app/logger.py — Centralized Logging System
#
# Architecture:
#   - Structured JSON logs to logs/app.log (INFO+)
#   - Structured JSON logs to logs/error.log (ERROR only)
#   - Console output for development visibility
#   - Correlation ID per request for end-to-end tracing
#   - Separate import pipeline logger
#   - DB audit logger (writes to AuditLog table)
#
# Log Levels:
#   DEBUG  — detailed flow (dev only)
#   INFO   — normal operations (login, import start, save)
#   WARN   — non-fatal issues (partial import, missing fields)
#   ERROR  — failures (parse error, DB error, auth failure)
# ═══════════════════════════════════════════════════════════════

import logging
import logging.handlers
import json
import uuid
import traceback
import os
from datetime import datetime
from typing import Optional, Any, Dict

# ── Ensure logs directory exists ──────────────────────────────
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)


# ── JSON Formatter ────────────────────────────────────────────
class JSONFormatter(logging.Formatter):
    """
    Outputs each log line as a JSON object.
    Makes logs machine-parseable and grep-friendly.
    """
    def format(self, record: logging.LogRecord) -> str:
        log_obj: Dict[str, Any] = {
            "timestamp"    : datetime.utcnow().isoformat() + "Z",
            "level"        : record.levelname,
            "logger"       : record.name,
            "message"      : record.getMessage(),
            "module"       : record.module,
            "function"     : record.funcName,
            "line"         : record.lineno,
        }

        # Add correlation_id if present
        if hasattr(record, "correlation_id"):
            log_obj["correlation_id"] = record.correlation_id

        # Add user context if present
        if hasattr(record, "user_id"):
            log_obj["user_id"] = record.user_id
        if hasattr(record, "user_email"):
            log_obj["user_email"] = record.user_email

        # Add extra fields
        if hasattr(record, "extra"):
            log_obj.update(record.extra)

        # Add exception info
        if record.exc_info:
            log_obj["exception"] = {
                "type"     : record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message"  : str(record.exc_info[1]),
                "traceback": traceback.format_exception(*record.exc_info),
            }

        return json.dumps(log_obj, ensure_ascii=False, default=str)


def _make_logger(name: str, log_file: str, level=logging.DEBUG) -> logging.Logger:
    """Create a named logger with file + console handlers."""
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if logger.handlers:
        return logger  # Already configured

    # File handler — rotating, max 5MB per file, keep 5 backups
    fh = logging.handlers.RotatingFileHandler(
        os.path.join(LOG_DIR, log_file),
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    fh.setFormatter(JSONFormatter())
    fh.setLevel(level)
    logger.addHandler(fh)

    # Error-only file
    eh = logging.handlers.RotatingFileHandler(
        os.path.join(LOG_DIR, "error.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    eh.setFormatter(JSONFormatter())
    eh.setLevel(logging.ERROR)
    logger.addHandler(eh)

    # Console handler — human-readable for dev
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(
        "[%(asctime)s] %(levelname)-8s %(name)s — %(message)s",
        datefmt="%H:%M:%S"
    ))
    logger.addHandler(ch)

    return logger


# ── Named Loggers ─────────────────────────────────────────────
app_logger    = _make_logger("rbl.app",    "app.log")
import_logger = _make_logger("rbl.import", "import.log")
auth_logger   = _make_logger("rbl.auth",   "app.log")
audit_logger  = _make_logger("rbl.audit",  "audit.log")
error_logger  = _make_logger("rbl.error",  "error.log", level=logging.ERROR)


# ── Correlation ID (per-request unique ID) ────────────────────
def new_correlation_id() -> str:
    """Generate a short unique ID to trace a single request end-to-end."""
    return uuid.uuid4().hex[:12].upper()


# ── Log Helper with Context ───────────────────────────────────
class RequestLogger:
    """
    Attach correlation_id and user context to every log call.
    Usage:
        rlog = RequestLogger(correlation_id="ABC123", user_id=5)
        rlog.info("Upload started", extra={"filename": "test.xlsx"})
    """
    def __init__(
        self,
        correlation_id: Optional[str] = None,
        user_id: Optional[int] = None,
        user_email: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.correlation_id = correlation_id or new_correlation_id()
        self.user_id        = user_id
        self.user_email     = user_email
        self._logger        = logger or app_logger

    def _log(self, level: int, message: str, extra: Optional[Dict] = None, exc_info=False):
        record_extra = {}
        if extra:
            record_extra = extra
        adapter = logging.LoggerAdapter(self._logger, {
            "correlation_id": self.correlation_id,
            "user_id"       : self.user_id,
            "user_email"    : self.user_email,
            "extra"         : record_extra,
        })
        # Manually create record with extra attributes
        self._logger.log(
            level, message,
            extra={
                "correlation_id": self.correlation_id,
                "user_id"       : self.user_id,
                "user_email"    : self.user_email,
                "extra"         : record_extra or {},
            },
            exc_info=exc_info,
        )

    def info(self, msg: str, extra: Optional[Dict] = None):
        self._log(logging.INFO, msg, extra)

    def warn(self, msg: str, extra: Optional[Dict] = None):
        self._log(logging.WARNING, msg, extra)

    def error(self, msg: str, extra: Optional[Dict] = None, exc_info=False):
        self._log(logging.ERROR, msg, extra, exc_info=exc_info)

    def debug(self, msg: str, extra: Optional[Dict] = None):
        self._log(logging.DEBUG, msg, extra)


# ── Import Pipeline Logger ────────────────────────────────────
class ImportLogger(RequestLogger):
    """
    Specialized logger for Excel import steps.
    Tracks: file received → parsing → validation → DB save → completion
    """
    def __init__(self, correlation_id: str, user_id: int, filename: str):
        super().__init__(
            correlation_id=correlation_id,
            user_id=user_id,
            logger=import_logger,
        )
        self.filename = filename
        self.step     = "init"

    def file_received(self, size_bytes: int):
        self.step = "file_received"
        self.info("Import file received", {
            "filename"   : self.filename,
            "size_bytes" : size_bytes,
            "step"       : self.step,
        })

    def parsing_start(self):
        self.step = "parsing"
        self.info("Excel parsing started", {"filename": self.filename, "step": self.step})

    def parsing_done(self, total_rows: int, header_row_idx: int):
        self.step = "parsed"
        self.info("Excel parsed successfully", {
            "filename"       : self.filename,
            "total_rows"     : total_rows,
            "header_row_idx" : header_row_idx,
            "step"           : self.step,
        })

    def validation_done(self, valid: int, invalid: int):
        self.step = "validated"
        level = logging.WARNING if invalid > 0 else logging.INFO
        self.info(f"Validation complete — {valid} valid, {invalid} invalid", {
            "valid_count"  : valid,
            "invalid_count": invalid,
            "step"         : self.step,
        })

    def save_done(self, imported: int, skipped: int):
        self.step = "saved"
        self.info(f"Import saved — {imported} imported, {skipped} skipped", {
            "imported": imported,
            "skipped" : skipped,
            "step"    : self.step,
        })

    def parse_error(self, error: Exception):
        self.step = "parse_failed"
        self.error(f"Excel parse failed: {str(error)}", {
            "filename": self.filename,
            "step"    : self.step,
        }, exc_info=True)


# ── DB Audit Log Writer ───────────────────────────────────────
def write_audit_log(
    db,
    action_type : str,
    table_name  : str,
    record_id   : Optional[int],
    user_id     : Optional[int],
    user_email  : Optional[str],
    description : str,
    old_value   : Optional[str] = None,
    new_value   : Optional[str] = None,
    correlation_id: Optional[str] = None,
):
    """
    Write an audit entry to the audit_logs DB table.
    Call this after any important DB operation.

    Example:
        write_audit_log(db, "INSERT", "budget_lines", entry.id,
                        user.id, user.email, "Budget line imported from Excel")
    """
    from app import models
    try:
        log = models.AuditLog(
            action_type    = action_type,
            table_name     = table_name,
            record_id      = record_id,
            user_id        = user_id,
            user_email     = user_email,
            description    = description,
            old_value      = old_value,
            new_value      = new_value,
            correlation_id = correlation_id,
        )
        db.add(log)
        db.commit()
        audit_logger.info(
            f"AUDIT: {action_type} on {table_name}#{record_id} by user#{user_id}",
            extra={
                "correlation_id": correlation_id,
                "user_id"       : user_id,
                "extra"         : {
                    "action_type": action_type,
                    "table_name" : table_name,
                    "record_id"  : record_id,
                    "description": description,
                }
            }
        )
    except Exception as e:
        # Audit logging must never crash the main flow
        error_logger.error(f"Audit log write failed: {e}", exc_info=True)


# ── Auth Event Logger ─────────────────────────────────────────
def log_auth_event(
    event      : str,
    email      : str,
    success    : bool,
    ip_address : Optional[str] = None,
    reason     : Optional[str] = None,
):
    """
    Log login/logout events for security audit.
    Events: login_success, login_failed, logout
    """
    level = logging.INFO if success else logging.WARNING
    auth_logger.log(level, f"AUTH: {event} — {email}", extra={
        "extra": {
            "event"     : event,
            "email"     : email,
            "success"   : success,
            "ip"        : ip_address,
            "reason"    : reason,
        }
    })