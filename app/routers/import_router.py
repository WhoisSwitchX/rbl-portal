# ═══════════════════════════════════════════════════════════════
# routers/import_router.py — Production-Grade Excel Import
#
# What this does:
#   1. Receives Excel file from IT Head
#   2. Validates file type, size, content
#   3. Parses Sheet1 using openpyxl (data_only=True, NO read_only)
#   4. Validates every row — errors + warnings
#   5. Generates downloadable error report (Excel) for invalid rows
#   6. Shows editable summary — user can fix and confirm
#   7. Saves valid rows to DB as DRAFT
#   8. Logs every step to file + DB audit table
#   9. Returns clear success/failure feedback with counts
#
# Key Fixes vs previous version:
#   - REMOVED read_only=True (was causing hang on GRC Excel)
#   - All TemplateResponse use {"request": request, ...} format
#   - Full logging at every step
#   - Error report downloadable as Excel
#   - File size limit check (10MB)
#   - Encoding-safe parsing
#   - No silent failures — every error shown to user
# ═══════════════════════════════════════════════════════════════

import os
import io
import json
import uuid
import math
import traceback
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app import models
from app.logger import (
    ImportLogger, app_logger, error_logger,
    write_audit_log, new_correlation_id,
)

router    = APIRouter()
templates = Jinja2Templates(directory="app/templates")

UPLOAD_DIR     = "uploads"
MAX_FILE_SIZE  = 10 * 1024 * 1024   # 10 MB hard limit
MAX_ROWS       = 500                  # Safety limit

os.makedirs(UPLOAD_DIR, exist_ok=True)

# ── Master Data ──────────────────────────────────────────────
BUSINESS_COST_MAP: Dict[str, int] = {
    "Operation Technology" : 3709,
    "RISK Technology"      : 3708,
    "Technology infra"     : 3701,
    "Technology operations": 3717,
    "Technology others"    : 3722,
    "Technology shared DWH": 3716,
    "Treasury"             : 3714,
}

VALID_OLD_NEW: List[str] = [
    "Old",
    "Old But Incremental",
    "New",
]

VALID_EXPENSE_TYPES: List[str] = [
    "Hardware",
    "Managed Services",
    "Subscription renewal",
    "T&M Services",
    "Professional Services",
    "Cost of being compliant",
    "Miscellaneous",
]

# Expected columns — used for schema validation warning
EXPECTED_COLUMNS = [
    "current year budget key",
    "previous year budget key",
    "old/new",
    "business name",
    "cost code",
    "it head",
    "spoc",
    "expense description",
    "final budget amt",
    "projected consumption",
    "budget amt (fy 26",
    "detailed reasoning",
    "description",
    "expense sub type",
    "application",
    "vendor",
    "resource count",
]


# ── Helpers ──────────────────────────────────────────────────
async def get_user(request: Request, db: Session):
    from app.auth import decode_token
    from jose import JWTError
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        payload = decode_token(token)
        email   = payload.get("sub")
        if not email:
            return None
        return db.query(models.User).filter(models.User.email == email).first()
    except JWTError:
        return None


def safe_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        if isinstance(val, float) and math.isnan(val):
            return None
        s = str(val).replace(",", "").replace("₹", "").replace(" ", "").strip()
        if not s or s.lower() in ("none", "null", "-", "n/a", ""):
            return None
        return float(s)
    except (ValueError, TypeError):
        return None


def safe_str(val) -> str:
    if val is None:
        return ""
    if isinstance(val, float) and math.isnan(val):
        return ""
    s = str(val).strip()
    return "" if s.lower() in ("none", "null", "n/a") else s


def _render_upload(request, user, error: str, history=None):
    """Helper to render upload page with error."""
    return templates.TemplateResponse(
        "import_export/upload.html",
        {
            "request"    : request,
            "user"       : user,
            "active_page": "import",
            "history"    : history or [],
            "error"      : error,
        }
    )


# ── Excel Parser ──────────────────────────────────────────────
def parse_excel(file_path: str, ilog: ImportLogger) -> tuple:
    """
    Parse GRC Excel file.
    Returns: (parsed_rows, missing_columns, column_map)

    Critical: NO read_only=True — it hangs on GRC merged-cell Excel files.
    Use data_only=True only to get formula calculated values.
    """
    import openpyxl

    ilog.parsing_start()

    # Load without read_only — CRITICAL FIX
    wb = openpyxl.load_workbook(file_path, data_only=True)

    # Sheet selection: Sheet1 → fallback to first sheet
    if "Sheet1" in wb.sheetnames:
        ws = wb["Sheet1"]
        ilog.info("Using Sheet1", {"sheet": "Sheet1"})
    else:
        ws = wb.active
        ilog.warn(
            f"Sheet1 not found — using '{ws.title}'",
            {"available_sheets": wb.sheetnames}
        )

    # Read rows with row limit
    all_rows = []
    for row in ws.iter_rows(values_only=True, max_row=MAX_ROWS + 10):
        cleaned_row = []
        for cell in row:
            if isinstance(cell, float) and math.isnan(cell):
                cleaned_row.append(None)
            else:
                cleaned_row.append(cell)
        all_rows.append(cleaned_row)

    wb.close()

    if len(all_rows) < 2:
        raise ValueError(
            "Excel file has too few rows — no data found. "
            "Please ensure Sheet1 has data starting from row 4."
        )

    ilog.info(f"Raw rows read: {len(all_rows)}", {"total_raw_rows": len(all_rows)})

    # ── Find header row ────────────────────────────────────────
    header_idx = None
    for i, row in enumerate(all_rows[:10]):  # Only scan first 10 rows
        if row and any(
            cell is not None and "budget key" in str(cell).lower()
            for cell in row
        ):
            header_idx = i
            break

    if header_idx is None:
        # GRC Excel default: row 3 (index 2) is headers
        if len(all_rows) >= 3:
            header_idx = 2
            ilog.warn(
                "Could not auto-detect header — using row 3 (GRC default)",
                {"header_idx": header_idx}
            )
        else:
            raise ValueError(
                "Header row not found. Expected a row containing 'Budget Key'. "
                "Please use the GRC_2_0_STEP1_AUTOMATED Excel format."
            )

    ilog.parsing_done(len(all_rows) - header_idx - 1, header_idx)

    header_row = all_rows[header_idx]
    headers    = [safe_str(h).lower() for h in header_row]

    # ── Schema validation — check for missing expected columns ──
    missing_columns = []
    for exp_col in EXPECTED_COLUMNS:
        found = any(exp_col.lower() in h for h in headers if h)
        if not found:
            missing_columns.append(exp_col)

    if missing_columns:
        ilog.warn(
            f"Schema warning: {len(missing_columns)} expected columns not found",
            {"missing_columns": missing_columns}
        )

    # ── Column mapping ─────────────────────────────────────────
    def find_col(*keywords) -> Optional[int]:
        for kw in keywords:
            for i, h in enumerate(headers):
                if h and kw.lower() in h:
                    return i
        return None

    C: Dict[str, Optional[int]] = {
        "key"  : find_col("current year budget key"),
        "prev" : find_col("previous year budget key"),
        "on"   : find_col("old/new"),
        "biz"  : find_col("business name"),
        "cc"   : find_col("cost code"),
        "ith"  : find_col("it head"),
        "spoc" : find_col("spoc"),
        "edesc": find_col("expense description"),
        "a"    : find_col("final budget amt", "final budget amount"),
        "b"    : find_col("projected consumption"),
        "c"    : find_col("budget amt (fy 26", "( c)", "(c)"),
        "rsn"  : find_col("detailed reasoning"),
        "desc" : find_col("description"),
        "etype": find_col("expense sub type"),
        "app"  : find_col("application/platform", "application"),
        "vnd"  : find_col("vendor name", "vendor"),
        "rc"   : find_col("resource count"),
    }

    # Extra fallback for column C (Budget FY 26-27)
    if C["c"] is None:
        for i, h in enumerate(headers):
            if h and ("26-27" in h or ("26" in h and "amt" in h and "budget" in h)):
                C["c"] = i
                break

    ilog.info("Column mapping complete", {"column_map": {k: v for k, v in C.items() if v is not None}})

    # Log any unmapped critical columns
    critical = ["key", "on", "biz", "a", "c", "etype"]
    unmapped = [k for k in critical if C.get(k) is None]
    if unmapped:
        ilog.warn(f"Critical columns not mapped: {unmapped}", {"unmapped": unmapped})

    # ── Parse data rows ────────────────────────────────────────
    parsed: List[Dict[str, Any]] = []
    data_rows = all_rows[header_idx + 1:]

    for row_offset, row in enumerate(data_rows):
        row_num = header_idx + 2 + row_offset   # 1-based Excel row number

        # Skip fully empty rows
        if not row or all(cell is None or str(cell).strip() == "" for cell in row):
            continue

        # Skip GRC meta rows (row 1 = notes, row 2 = field type hints)
        first_val = safe_str(row[0]) if row else ""
        if any(first_val.lower().startswith(x) for x in [
            "m/unique", "line item", "dropdown", "s/dropdown",
            "single select", "freetext", "number/bl"
        ]):
            continue

        # Skip rows that have no budget key AND no business name — filler
        if not any(
            row[C[k]] is not None and str(row[C[k]]).strip()
            for k in ("key", "biz")
            if C.get(k) is not None and C[k] < len(row)
        ):
            continue

        def g(key: str) -> str:
            idx = C.get(key)
            if idx is None or idx >= len(row):
                return ""
            return safe_str(row[idx])

        def gn(key: str) -> Optional[float]:
            idx = C.get(key)
            if idx is None or idx >= len(row):
                return None
            return safe_float(row[idx])

        rd: Dict[str, Any] = {
            "row_num"       : row_num,
            "budget_key"    : g("key"),
            "prev_key"      : g("prev"),
            "old_new"       : g("on"),
            "business"      : g("biz"),
            "cost_code"     : g("cc"),
            "it_head"       : g("ith"),
            "spoc"          : g("spoc"),
            "exp_desc"      : g("edesc"),
            "budget_a"      : gn("a"),
            "projected_b"   : gn("b"),
            "budget_c"      : gn("c"),
            "reasoning"     : g("rsn"),
            "description"   : g("desc"),
            "expense_type"  : g("etype"),
            "application"   : g("app"),
            "vendor"        : g("vnd"),
            "resource_count": gn("rc"),
            "errors"        : [],
            "warnings"      : [],
            "valid"         : True,
        }

        errors:   List[str] = []
        warnings: List[str] = []

        # ── HARD VALIDATIONS (row skipped if any) ──────────────
        if not rd["budget_key"]:
            errors.append("Budget Key (Column A) missing")

        if not rd["old_new"]:
            errors.append("Old/New field missing")
        elif rd["old_new"] not in VALID_OLD_NEW:
            errors.append(
                f"Old/New value '{rd['old_new']}' not allowed. "
                f"Must be one of: {', '.join(VALID_OLD_NEW)}"
            )

        if not rd["business"]:
            errors.append("Business Name missing")
        elif rd["business"] not in BUSINESS_COST_MAP:
            errors.append(
                f"Business Name '{rd['business']}' not in master list. "
                f"Allowed: {', '.join(BUSINESS_COST_MAP.keys())}"
            )

        if not rd["expense_type"]:
            errors.append("Expense Sub Type missing")
        elif rd["expense_type"] not in VALID_EXPENSE_TYPES:
            errors.append(
                f"Expense Type '{rd['expense_type']}' invalid. "
                f"Allowed: {', '.join(VALID_EXPENSE_TYPES)}"
            )

        if rd["budget_a"] is None:
            errors.append("Final Budget FY 25-26 (Column A) missing or not a number")
        elif rd["budget_a"] < 0:
            errors.append("Budget A cannot be negative")

        if rd["budget_c"] is None:
            errors.append("Budget FY 26-27 (Column C) missing or not a number")
        elif rd["budget_c"] < 0:
            errors.append("Budget C cannot be negative")

        # ── SOFT VALIDATIONS (row saved, warning shown) ────────
        if not rd["exp_desc"]:
            warnings.append("Expense Description is empty")
        if not rd["reasoning"]:
            warnings.append("Detailed Reasoning is empty — please add justification")
        if rd["projected_b"] is None:
            warnings.append("Projected Consumption (B) empty — can be filled later by Admin")
        if not rd["vendor"]:
            warnings.append("Vendor Name is empty")
        if not rd["it_head"]:
            warnings.append("IT Head name is empty — will use logged-in user")

        rd["errors"]  = errors
        rd["warnings"] = warnings
        rd["valid"]   = len(errors) == 0
        parsed.append(rd)

    return parsed, missing_columns, C


# ── Error Report Generator ────────────────────────────────────
def generate_error_report(parsed_rows: List[Dict], file_name: str) -> bytes:
    """
    Create a downloadable Excel file listing all invalid rows
    with their errors clearly marked.
    Returns bytes of the Excel file.
    """
    import openpyxl
    from openpyxl.styles import PatternFill, Font, Alignment

    wb    = openpyxl.Workbook()
    ws    = wb.active
    ws.title = "Validation Errors"

    red_fill    = PatternFill("solid", fgColor="FFD7D7")
    header_fill = PatternFill("solid", fgColor="C8102E")
    bold_white  = Font(bold=True, color="FFFFFF")

    headers = [
        "Row #", "Budget Key", "Business Name", "Old/New",
        "Expense Type", "Budget A", "Budget C",
        "Error Count", "Errors (pipe-separated)"
    ]

    # Header row
    for col_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=h)
        cell.fill = header_fill
        cell.font = bold_white
        cell.alignment = Alignment(horizontal="center")

    # Data rows — only invalid
    invalid_rows = [r for r in parsed_rows if not r["valid"]]
    for row_idx, row in enumerate(invalid_rows, start=2):
        ws.cell(row=row_idx, column=1, value=row["row_num"])
        ws.cell(row=row_idx, column=2, value=row.get("budget_key") or "")
        ws.cell(row=row_idx, column=3, value=row.get("business") or "")
        ws.cell(row=row_idx, column=4, value=row.get("old_new") or "")
        ws.cell(row=row_idx, column=5, value=row.get("expense_type") or "")
        ws.cell(row=row_idx, column=6, value=row.get("budget_a") or "")
        ws.cell(row=row_idx, column=7, value=row.get("budget_c") or "")
        ws.cell(row=row_idx, column=8, value=len(row.get("errors", [])))
        ws.cell(row=row_idx, column=9, value=" | ".join(row.get("errors", [])))

        # Red fill for error rows
        for col in range(1, len(headers) + 1):
            ws.cell(row=row_idx, column=col).fill = red_fill

    # Auto-fit columns
    for col in ws.columns:
        max_len = max((len(str(cell.value or "")) for cell in col), default=10)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 60)

    # Summary sheet
    ws2 = wb.create_sheet("Summary")
    ws2["A1"] = "Import Error Report"
    ws2["A2"] = f"Source File: {file_name}"
    ws2["A3"] = f"Generated: {datetime.now().strftime('%d %b %Y %H:%M')}"
    ws2["A5"] = "Total Rows Processed"
    ws2["B5"] = len(parsed_rows)
    ws2["A6"] = "Valid Rows"
    ws2["B6"] = len([r for r in parsed_rows if r["valid"]])
    ws2["A7"] = "Invalid Rows (see sheet 1)"
    ws2["B7"] = len(invalid_rows)

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


# ── GET /import/ ──────────────────────────────────────────────
@router.get("/", response_class=HTMLResponse)
async def import_page(request: Request, db: Session = Depends(get_db)):
    user = await get_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    history = db.query(models.UploadedFile).filter(
        models.UploadedFile.uploaded_by == user.id
    ).order_by(models.UploadedFile.upload_at.desc()).limit(10).all()

    error = request.query_params.get("error", None)

    app_logger.info(f"Import page visited by user#{user.id}", extra={
        "extra": {"user_id": user.id, "page": "import"}
    })

    return templates.TemplateResponse(
        "import_export/upload.html",
        {
            "request"    : request,
            "user"       : user,
            "active_page": "import",
            "history"    : history,
            "error"      : error,
        }
    )


# ── POST /import/upload ───────────────────────────────────────
@router.post("/upload")
async def import_upload(
    request: Request,
    db     : Session    = Depends(get_db),
    file   : UploadFile = File(...),
):
    user = await get_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    # Generate correlation ID for this entire import operation
    corr_id = new_correlation_id()
    fname   = file.filename or "unknown.xlsx"

    ilog = ImportLogger(
        correlation_id = corr_id,
        user_id        = user.id,
        filename       = fname,
    )

    ilog.info("Import request started", {"correlation_id": corr_id, "user_email": user.email})

    # ── VALIDATION 1: File extension ──────────────────────────
    if not (fname.lower().endswith(".xlsx") or fname.lower().endswith(".xls")):
        ilog.warn("Invalid file extension", {"filename": fname})
        return _render_upload(request, user,
            f"Invalid file type '{fname.split('.')[-1]}'. "
            "Only .xlsx or .xls files are accepted."
        )

    # ── VALIDATION 2: Read file contents ──────────────────────
    contents = await file.read()
    file_size = len(contents)

    if file_size == 0:
        ilog.warn("Empty file uploaded", {"filename": fname})
        return _render_upload(request, user, "Uploaded file is empty. Please upload a valid Excel file.")

    # ── VALIDATION 3: File size ────────────────────────────────
    if file_size > MAX_FILE_SIZE:
        size_mb = file_size / (1024 * 1024)
        ilog.warn(f"File too large: {size_mb:.1f}MB", {"size_bytes": file_size})
        return _render_upload(request, user,
            f"File size {size_mb:.1f}MB exceeds the 10MB limit. "
            "Please reduce file size or split into smaller batches."
        )

    ilog.file_received(file_size)

    # ── Save to disk ───────────────────────────────────────────
    ts          = datetime.now().strftime("%Y%m%d_%H%M%S")
    uid         = uuid.uuid4().hex[:8]
    stored_name = f"{user.id}_{ts}_{uid}_{fname}"
    file_path   = os.path.join(UPLOAD_DIR, stored_name)

    with open(file_path, "wb") as f:
        f.write(contents)

    ilog.info("File saved to disk", {"stored_name": stored_name, "path": file_path})

    # ── Parse Excel ────────────────────────────────────────────
    try:
        parsed_rows, missing_cols, col_map = parse_excel(file_path, ilog)
    except Exception as exc:
        ilog.parse_error(exc)
        try:
            os.remove(file_path)
        except Exception:
            pass
        err_str = str(exc)
        return _render_upload(request, user,
            f"Failed to read Excel file: {err_str}. "
            "Please ensure it is a valid .xlsx file in GRC format."
        )

    if not parsed_rows:
        ilog.warn("No data rows found after parsing", {"filename": fname})
        try:
            os.remove(file_path)
        except Exception:
            pass
        return _render_upload(request, user,
            "No data rows found in the Excel file. "
            "Please check that Sheet1 has data starting from row 4."
        )

    # ── DB duplicate check ─────────────────────────────────────
    for rd in parsed_rows:
        if rd["budget_key"] and rd["valid"]:
            exists = db.query(models.BudgetLine).filter(
                models.BudgetLine.budget_key_current == rd["budget_key"]
            ).first()
            if exists:
                rd["errors"].append(
                    f"Budget Key '{rd['budget_key']}' already exists in database (imported/entered previously)"
                )
                rd["valid"] = False

    valid_count   = sum(1 for r in parsed_rows if r["valid"])
    invalid_count = sum(1 for r in parsed_rows if not r["valid"])

    ilog.validation_done(valid_count, invalid_count)

    # ── Generate error report if any invalid rows ──────────────
    error_report_path = None
    if invalid_count > 0:
        try:
            report_bytes = generate_error_report(parsed_rows, fname)
            rpt_name     = f"error_report_{corr_id}.xlsx"
            rpt_path     = os.path.join(UPLOAD_DIR, rpt_name)
            with open(rpt_path, "wb") as f:
                f.write(report_bytes)
            error_report_path = rpt_path
            ilog.info(f"Error report generated: {rpt_name}", {"report_path": rpt_path})
        except Exception as rpt_err:
            ilog.warn(f"Could not generate error report: {rpt_err}")

    # ── Save upload record ─────────────────────────────────────
    file_rec = models.UploadedFile(
        original_name     = fname,
        stored_name       = stored_name,
        uploaded_by       = user.id,
        rows_total        = len(parsed_rows),
        rows_imported     = 0,
        rows_failed       = invalid_count,
        status            = "pending",
        error_report_path = error_report_path,
        correlation_id    = corr_id,
        file_size_bytes   = file_size,
    )
    db.add(file_rec)
    db.commit()
    db.refresh(file_rec)

    # Audit log
    write_audit_log(
        db            = db,
        action_type   = "IMPORT_UPLOAD",
        table_name    = "uploaded_files",
        record_id     = file_rec.id,
        user_id       = user.id,
        user_email    = user.email,
        description   = f"Excel uploaded: {fname} — {len(parsed_rows)} rows ({valid_count} valid, {invalid_count} invalid)",
        new_value     = json.dumps({"filename": fname, "total": len(parsed_rows), "valid": valid_count, "invalid": invalid_count}),
        correlation_id= corr_id,
    )

    # Store summary as temp JSON for confirm step
    summary = {
        "file_id"           : file_rec.id,
        "file_name"         : fname,
        "correlation_id"    : corr_id,
        "total"             : len(parsed_rows),
        "valid_count"       : valid_count,
        "invalid_count"     : invalid_count,
        "missing_columns"   : missing_cols,
        "has_error_report"  : error_report_path is not None,
        "rows"              : parsed_rows,
    }

    temp_path = os.path.join(UPLOAD_DIR, f"summary_{file_rec.id}.json")
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, default=str)

    ilog.info("Summary page ready", {
        "file_id"     : file_rec.id,
        "valid_count" : valid_count,
        "invalid_count": invalid_count,
    })

    return templates.TemplateResponse(
        "import_export/summary.html",
        {
            "request"            : request,
            "user"               : user,
            "active_page"        : "import",
            "summary"            : summary,
            "file_id"            : file_rec.id,
            "correlation_id"     : corr_id,
            "VALID_OLD_NEW"      : VALID_OLD_NEW,
            "VALID_EXPENSE_TYPES": VALID_EXPENSE_TYPES,
            "BUSINESS_NAMES"     : list(BUSINESS_COST_MAP.keys()),
        }
    )


# ── GET /import/download-errors/{file_id} ─────────────────────
@router.get("/download-errors/{file_id}")
async def download_error_report(
    file_id: int,
    request: Request,
    db     : Session = Depends(get_db),
):
    """Download the error report Excel for a specific upload."""
    user = await get_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    file_rec = db.query(models.UploadedFile).filter(
        models.UploadedFile.id == file_id,
        models.UploadedFile.uploaded_by == user.id,
    ).first()

    if not file_rec or not file_rec.error_report_path:
        return RedirectResponse(url="/import/?error=Error+report+not+found", status_code=302)

    if not os.path.exists(file_rec.error_report_path):
        return RedirectResponse(url="/import/?error=Error+report+file+missing+on+server", status_code=302)

    with open(file_rec.error_report_path, "rb") as f:
        content = f.read()

    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=import_errors_{file_id}.xlsx"
        }
    )


# ── POST /import/confirm ──────────────────────────────────────
@router.post("/confirm")
async def import_confirm(request: Request, db: Session = Depends(get_db)):
    user = await get_user(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=302)

    form    = await request.form()
    file_id = int(form.get("file_id", 0))
    corr_id = str(form.get("correlation_id", new_correlation_id()))

    ilog = ImportLogger(
        correlation_id = corr_id,
        user_id        = user.id,
        filename       = f"file_id={file_id}",
    )
    ilog.info("Import confirm started", {"file_id": file_id})

    # Load temp summary
    temp_path = os.path.join(UPLOAD_DIR, f"summary_{file_id}.json")
    if not os.path.exists(temp_path):
        ilog.warn("Temp summary not found — session likely expired", {"file_id": file_id})
        return RedirectResponse(
            url="/import/?error=Session+expired.+Please+upload+the+file+again.",
            status_code=302
        )

    with open(temp_path, "r", encoding="utf-8") as f:
        summary = json.load(f)

    expense_map = {e.value: e for e in models.ExpenseSubType}
    old_new_map = {o.value: o for o in models.OldNew}
    imported    = 0
    skipped     = 0
    errors_list = []

    for row in summary["rows"]:
        if not row["valid"]:
            continue

        rn = row["row_num"]

        if not form.get(f"import_row_{rn}"):
            skipped += 1
            continue

        def fv(field, fallback=""):
            return str(form.get(f"row_{rn}_{field}", fallback or "")).strip()

        def fn(field, fallback=None):
            v = form.get(f"row_{rn}_{field}", "")
            try:
                return float(str(v).replace(",", "").strip())
            except (ValueError, TypeError):
                return fallback

        budget_key   = fv("budget_key",   row.get("budget_key",   ""))
        prev_key     = fv("prev_key",     row.get("prev_key",     ""))
        old_new_val  = fv("old_new",      row.get("old_new",      "Old"))
        business     = fv("business",     row.get("business",     ""))
        it_head      = fv("it_head",      row.get("it_head",      ""))
        spoc         = fv("spoc",         row.get("spoc",         ""))
        exp_desc     = fv("exp_desc",     row.get("exp_desc",     ""))
        expense_type = fv("expense_type", row.get("expense_type", "Miscellaneous"))
        application  = fv("application",  row.get("application",  ""))
        vendor       = fv("vendor",       row.get("vendor",       ""))
        description  = fv("description",  row.get("description",  ""))
        reasoning    = fv("reasoning",    row.get("reasoning",    ""))
        budget_a     = fn("budget_a",     row.get("budget_a")  or 0)
        projected_b  = fn("projected_b",  row.get("projected_b"))
        budget_c     = fn("budget_c",     row.get("budget_c")  or 0)

        rc_raw = form.get(f"row_{rn}_resource_count", "")
        try:
            resource_count = int(rc_raw) if str(rc_raw).strip() else None
        except (ValueError, TypeError):
            resource_count = None

        # Final safety check
        if not budget_key:
            skipped += 1
            ilog.warn(f"Row {rn} skipped — empty budget key after edit")
            continue

        if db.query(models.BudgetLine).filter(
            models.BudgetLine.budget_key_current == budget_key
        ).first():
            skipped += 1
            ilog.warn(f"Row {rn} skipped — duplicate key '{budget_key}'")
            errors_list.append(f"Row {rn}: Key '{budget_key}' already exists — skipped")
            continue

        a = budget_a or 0
        b = projected_b
        c = budget_c or 0

        try:
            entry = models.BudgetLine(
                budget_key_current   = budget_key,
                budget_key_previous  = prev_key or None,
                old_new              = old_new_map.get(old_new_val, models.OldNew.OLD),
                business_name        = business,
                cost_code            = BUSINESS_COST_MAP.get(business, 0),
                submitted_by         = user.id,
                it_head_name         = it_head or user.full_name,
                spoc_name            = spoc or None,
                expense_sub_type     = expense_map.get(expense_type, models.ExpenseSubType.MISCELLANEOUS),
                expense_description  = exp_desc or None,
                description          = description or None,
                application_platform = application or None,
                vendor_name          = vendor or None,
                resource_count       = resource_count,
                budget_amt_current_fy= a,
                projected_consumption= b,
                budget_amt_next_fy   = c,
                diff_a_minus_b       = (a - b) if b is not None else None,
                diff_c_minus_b       = (c - b) if b is not None else None,
                diff_c_minus_a       = c - a,
                detailed_reasoning   = reasoning or None,
                import_file_id       = file_id,
                status               = models.BudgetStatus.DRAFT,
            )
            db.add(entry)
            db.flush()  # Get the ID without full commit

            # Audit log per entry
            write_audit_log(
                db            = db,
                action_type   = "INSERT",
                table_name    = "budget_lines",
                record_id     = entry.id,
                user_id       = user.id,
                user_email    = user.email,
                description   = f"Budget line imported: {budget_key} — {business}",
                new_value     = json.dumps({"budget_key": budget_key, "business": business, "budget_a": a, "budget_c": c}),
                correlation_id= corr_id,
            )
            imported += 1

        except Exception as row_err:
            skipped += 1
            err_msg = f"Row {rn} DB error: {str(row_err)}"
            errors_list.append(err_msg)
            ilog.error(err_msg, exc_info=True)
            db.rollback()

    # Commit all inserts
    try:
        db.commit()
    except Exception as commit_err:
        ilog.error(f"Commit failed: {commit_err}", exc_info=True)
        db.rollback()
        return _render_upload(request, user,
            f"Database error during save: {str(commit_err)}. Please try again."
        )

    # Update file record
    rec = db.query(models.UploadedFile).filter(models.UploadedFile.id == file_id).first()
    if rec:
        rec.rows_imported = imported
        rec.status        = "processed" if imported > 0 else ("failed" if imported == 0 and skipped > 0 else "processed")
        db.commit()

    ilog.save_done(imported, skipped)

    # Final audit log for the whole import
    write_audit_log(
        db            = db,
        action_type   = "IMPORT_CONFIRM",
        table_name    = "uploaded_files",
        record_id     = file_id,
        user_id       = user.id,
        user_email    = user.email,
        description   = f"Import confirmed: {imported} saved, {skipped} skipped",
        new_value     = json.dumps({"imported": imported, "skipped": skipped, "errors": errors_list}),
        correlation_id= corr_id,
    )

    # Cleanup temp JSON
    try:
        os.remove(temp_path)
    except Exception:
        pass

    return RedirectResponse(
        url=f"/budget/?imported={imported}&skipped={skipped}",
        status_code=302
    )