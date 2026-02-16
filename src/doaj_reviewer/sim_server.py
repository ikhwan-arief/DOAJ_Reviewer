"""Local simulation server for realistic form-based reviewer testing."""

from __future__ import annotations

import argparse
import base64
import csv
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import traceback
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse
from uuid import uuid4

from .intake import build_structured_submission_from_raw
from .reporting import render_endogeny_markdown
from .review import render_review_summary_markdown, render_review_summary_text, run_review


URL_FIELDS = [
    "open_access_statement",
    "issn_consistency",
    "publisher_identity",
    "license_terms",
    "copyright_author_rights",
    "peer_review_policy",
    "plagiarism_policy",
    "aims_scope",
    "editorial_board",
    "reviewers",
    "latest_content",
    "instructions_for_authors",
    "publication_fees_disclosure",
    "archiving_policy",
    "repository_policy",
    "archives",
]
POLICY_HINT_KEYS = [
    "open_access_statement",
    "issn_consistency",
    "publisher_identity",
    "license_terms",
    "copyright_author_rights",
    "peer_review_policy",
    "plagiarism_policy",
    "aims_scope",
    "publication_fees_disclosure",
    "archiving_policy",
    "repository_policy",
    "instructions_for_authors",
]

RESULT_RULE_COLUMNS = [
    "doaj.open_access_statement.v1",
    "doaj.issn_consistency.v1",
    "doaj.publisher_identity.v1",
    "doaj.license_terms.v1",
    "doaj.copyright_author_rights.v1",
    "doaj.peer_review_policy.v1",
    "doaj.aims_scope.v1",
    "doaj.editorial_board.v1",
    "doaj.instructions_for_authors.v1",
    "doaj.publication_fees_disclosure.v1",
    "doaj.endogeny.v1",
]

RULE_HINT_BY_ID = {
    "doaj.open_access_statement.v1": "open_access_statement",
    "doaj.issn_consistency.v1": "issn_consistency",
    "doaj.publisher_identity.v1": "publisher_identity",
    "doaj.license_terms.v1": "license_terms",
    "doaj.copyright_author_rights.v1": "copyright_author_rights",
    "doaj.peer_review_policy.v1": "peer_review_policy",
    "doaj.aims_scope.v1": "aims_scope",
    "doaj.editorial_board.v1": "editorial_board",
    "doaj.instructions_for_authors.v1": "instructions_for_authors",
    "doaj.publication_fees_disclosure.v1": "publication_fees_disclosure",
    "doaj.endogeny.v1": "endogeny",
    "doaj.plagiarism_policy.v1": "plagiarism_policy",
    "doaj.archiving_policy.v1": "archiving_policy",
    "doaj.repository_policy.v1": "repository_policy",
}

REQUIRED_URL_FIELDS = [
    "open_access_statement",
    "issn_consistency",
    "publisher_identity",
    "license_terms",
    "copyright_author_rights",
    "peer_review_policy",
    "aims_scope",
    "editorial_board",
    "latest_content",
    "instructions_for_authors",
    "publication_fees_disclosure",
]

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RULESET_PATH = REPO_ROOT / "specs" / "reviewer" / "rules" / "ruleset.must.v1.json"
DEFAULT_RUNS_DIR = REPO_ROOT / "runs"


def split_urls(text: str) -> list[str]:
    if not text:
        return []
    seen = set()
    out: list[str] = []
    for line in text.replace("|", "\n").splitlines():
        value = line.strip()
        if not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _extract_text_from_pdf_bytes(payload: bytes) -> str:
    for module_name in ("pypdf", "PyPDF2"):
        try:
            module = __import__(module_name, fromlist=["PdfReader"])
            reader = module.PdfReader(io.BytesIO(payload))
            chunks: list[str] = []
            for page in reader.pages[:40]:
                try:
                    text = page.extract_text() or ""
                except Exception:
                    text = ""
                if text.strip():
                    chunks.append(text.strip())
            merged = "\n\n".join(chunks).strip()
            if merged:
                return merged
        except Exception:
            continue
    return ""


def _normalize_manual_policy_pages(payload: dict[str, Any]) -> tuple[list[dict[str, str]], list[str]]:
    raw_items = payload.get("manual_policy_pages", [])
    if not isinstance(raw_items, list):
        return [], []

    pages: list[dict[str, str]] = []
    warnings: list[str] = []
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            continue
        hint = str(item.get("rule_hint", "")).strip()
        if hint not in POLICY_HINT_KEYS:
            warnings.append(f"Ignored manual fallback entry with unknown rule_hint: `{hint}`.")
            continue

        title = str(item.get("title", "")).strip() or f"Manual fallback ({hint})"
        source_label = str(item.get("source_label", "")).strip() or f"manual://{hint}/{index}"
        if "://" not in source_label:
            source_label = f"manual://{hint}/{index}"

        text_value = str(item.get("text", "")).strip()
        if text_value:
            pages.append(
                {
                    "rule_hint": hint,
                    "url": source_label,
                    "title": title[:180],
                    "text": text_value[:120000],
                }
            )

        pdf_base64 = str(item.get("pdf_base64", "")).strip()
        if pdf_base64:
            file_name = str(item.get("file_name", "")).strip() or f"{hint}.pdf"
            try:
                pdf_bytes = base64.b64decode(pdf_base64, validate=True)
            except Exception:
                warnings.append(f"Manual PDF `{file_name}` for `{hint}` could not be decoded.")
                continue
            extracted = _extract_text_from_pdf_bytes(pdf_bytes)
            if not extracted:
                warnings.append(
                    f"Manual PDF `{file_name}` for `{hint}` was uploaded, but text extraction failed. Paste text manually for this rule."
                )
                continue
            pages.append(
                {
                    "rule_hint": hint,
                    "url": f"{source_label}/pdf",
                    "title": f"Manual PDF: {file_name}"[:180],
                    "text": extracted[:120000],
                }
            )

    return pages, warnings


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def build_raw_submission_from_form(payload: dict[str, Any]) -> dict[str, Any]:
    submission_id = str(payload.get("submission_id", "")).strip()
    homepage = str(payload.get("journal_homepage_url", "")).strip()
    publication_model = str(payload.get("publication_model", "issue_based")).strip() or "issue_based"
    if publication_model not in {"issue_based", "continuous"}:
        publication_model = "issue_based"
    if not submission_id:
        suffix = uuid4().hex[:8]
        submission_id = f"SIM-{_now_stamp()}-{suffix}"

    source_urls: dict[str, list[str]] = {}
    for field in URL_FIELDS:
        source_urls[field] = split_urls(str(payload.get(field, "")))
    manual_policy_pages, manual_warnings = _normalize_manual_policy_pages(payload)

    raw = {
        "submission_id": submission_id,
        "journal_homepage_url": homepage,
        "publication_model": publication_model,
        "source_urls": source_urls,
    }
    if manual_policy_pages:
        raw["manual_policy_pages"] = manual_policy_pages
    if manual_warnings:
        raw["manual_input_warnings"] = manual_warnings
    return raw


def validate_raw_submission(raw: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not str(raw.get("journal_homepage_url", "")).strip():
        errors.append("journal_homepage_url is required")
    source_urls = raw.get("source_urls", {})
    if not isinstance(source_urls, dict):
        errors.append("source_urls must be an object")
        return errors
    for field in REQUIRED_URL_FIELDS:
        if not source_urls.get(field):
            errors.append(f"At least one `{field}` URL is required")
    return errors


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def _write_text(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(data)


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _sanitize_cell(value: Any) -> str:
    return " ".join(str(value or "").split())


def _dedupe_strings(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = _sanitize_cell(value)
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _as_string_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if _sanitize_cell(item)]


def _join_csv_cell(values: list[str]) -> str:
    return " | ".join(_dedupe_strings(values))


def _check_problem_urls(check: dict[str, Any], raw_source_urls: dict[str, Any]) -> list[str]:
    # Prefer explicitly traced source URLs from rich summary output.
    source_urls = _as_string_list(check.get("source_urls", []))
    if source_urls:
        return _dedupe_strings(source_urls)

    evidence_urls = _as_string_list(check.get("evidence_urls", []))
    if evidence_urls:
        return _dedupe_strings(evidence_urls)

    rule_id = str(check.get("rule_id", "")).strip()
    rule_hint = RULE_HINT_BY_ID.get(rule_id, "")
    if rule_id == "doaj.endogeny.v1":
        fallback_hints = ["latest_content", "archives", "editorial_board", "reviewers"]
    elif rule_id == "doaj.editorial_board.v1":
        fallback_hints = ["editorial_board", "reviewers"]
    elif rule_hint:
        fallback_hints = [rule_hint]
    else:
        fallback_hints = []

    fallback_urls_all: list[str] = []
    for hint in fallback_hints:
        fallback_urls = raw_source_urls.get(hint, [])
        if isinstance(fallback_urls, list):
            fallback_urls_all.extend([str(item) for item in fallback_urls])
    return _dedupe_strings(fallback_urls_all)


def _export_fieldnames() -> list[str]:
    fieldnames = [
        "run_id",
        "submission_id",
        "overall_result",
        "overall_decision_reason",
    ] + RESULT_RULE_COLUMNS
    for rule_id in RESULT_RULE_COLUMNS:
        fieldnames.append(f"{rule_id}__note")
        fieldnames.append(f"{rule_id}__problem_urls")
    fieldnames.extend(
        [
            "must_attention_rules",
            "must_attention_notes",
            "must_attention_urls",
            "supplementary_attention_rules",
            "supplementary_attention_notes",
            "supplementary_attention_urls",
        ]
    )
    return fieldnames


def _parse_limit(raw: str | None, default: int | None) -> int | None:
    if raw is None:
        return default
    value = raw.strip().lower()
    if not value:
        return default
    if value == "all":
        return None
    try:
        return max(0, int(value))
    except ValueError:
        return default


class SimulationApp:
    def __init__(self, ruleset_path: Path, runs_dir: Path) -> None:
        self.ruleset_path = ruleset_path
        self.runs_dir = runs_dir
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.ruleset = _read_json(ruleset_path)

    def run_submission(self, form_payload: dict[str, Any]) -> dict[str, Any]:
        js_mode = str(form_payload.get("js_mode", "auto")).strip().lower() or "auto"
        if js_mode not in {"off", "auto", "on"}:
            js_mode = "auto"

        raw = build_raw_submission_from_form(form_payload)
        warnings = [str(item) for item in raw.get("manual_input_warnings", []) if str(item).strip()]
        errors = validate_raw_submission(raw)
        if errors:
            return {
                "ok": False,
                "errors": errors,
                "warnings": warnings,
            }

        run_id = f"{_now_stamp()}-{uuid4().hex[:8]}"
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        raw_path = run_dir / "submission.raw.json"
        structured_path = run_dir / "submission.structured.json"
        summary_json_path = run_dir / "review-summary.json"
        summary_md_path = run_dir / "review-summary.md"
        summary_txt_path = run_dir / "review-summary.txt"
        endogeny_json_path = run_dir / "endogeny-result.json"
        endogeny_md_path = run_dir / "endogeny-report.md"
        error_path = run_dir / "error.txt"

        _write_json(raw_path, raw)
        try:
            structured = build_structured_submission_from_raw(raw, js_mode=js_mode)
            _write_json(structured_path, structured)

            summary, endogeny = run_review(submission=structured, ruleset=self.ruleset)
            _write_json(summary_json_path, summary)
            _write_text(summary_md_path, render_review_summary_markdown(summary))
            _write_text(summary_txt_path, render_review_summary_text(summary))
            _write_json(endogeny_json_path, endogeny)
            _write_text(endogeny_md_path, render_endogeny_markdown(endogeny))

            artifacts = {
                "raw": f"/runs/{run_id}/submission.raw.json",
                "structured": f"/runs/{run_id}/submission.structured.json",
                "summary_json": f"/runs/{run_id}/review-summary.json",
                "summary_md": f"/runs/{run_id}/review-summary.md",
                "summary_txt": f"/runs/{run_id}/review-summary.txt",
                "endogeny_json": f"/runs/{run_id}/endogeny-result.json",
                "endogeny_md": f"/runs/{run_id}/endogeny-report.md",
            }
            return {
                "ok": True,
                "run_id": run_id,
                "submission_id": summary.get("submission_id", raw.get("submission_id", "")),
                "overall_result": summary.get("overall_result", "need_human_review"),
                "checks": summary.get("checks", []),
                "supplementary_checks": summary.get("supplementary_checks", []),
                "warnings": warnings,
                "artifacts": artifacts,
            }
        except Exception:
            stack = traceback.format_exc()
            _write_text(error_path, stack)
            return {
                "ok": False,
                "run_id": run_id,
                "errors": ["review run failed"],
                "warnings": warnings,
                "artifacts": {
                    "raw": f"/runs/{run_id}/submission.raw.json",
                    "error": f"/runs/{run_id}/error.txt",
                },
            }

    def _run_dirs(self, limit: int | None = 20) -> list[Path]:
        run_dirs = sorted([p for p in self.runs_dir.iterdir() if p.is_dir()], reverse=True)
        if limit is None:
            return run_dirs
        return run_dirs[:limit]

    def list_runs(self, limit: int | None = 20) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for run_dir in self._run_dirs(limit=limit):
            item = {
                "run_id": run_dir.name,
                "summary_json": f"/runs/{run_dir.name}/review-summary.json",
                "raw_json": f"/runs/{run_dir.name}/submission.raw.json",
            }
            summary_file = run_dir / "review-summary.json"
            if summary_file.exists():
                try:
                    summary = _read_json(summary_file)
                    item["overall_result"] = summary.get("overall_result", "")
                except Exception:
                    item["overall_result"] = "unknown"
            else:
                item["overall_result"] = "not_available"
            rows.append(item)
        return rows

    def export_rows(self, limit: int | None = None) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        fieldnames = _export_fieldnames()
        for run_dir in self._run_dirs(limit=limit):
            row = {name: "" for name in fieldnames}
            row["run_id"] = run_dir.name
            row["overall_result"] = "not_available"

            raw_source_urls: dict[str, Any] = {}
            raw_file = run_dir / "submission.raw.json"
            if raw_file.exists():
                try:
                    raw = _read_json(raw_file)
                    row["submission_id"] = str(raw.get("submission_id", ""))
                    source_urls = raw.get("source_urls", {})
                    if isinstance(source_urls, dict):
                        raw_source_urls = source_urls
                except Exception:
                    row["submission_id"] = ""

            summary_file = run_dir / "review-summary.json"
            if summary_file.exists():
                try:
                    summary = _read_json(summary_file)
                    row["submission_id"] = str(summary.get("submission_id", row["submission_id"]))
                    row["overall_result"] = str(summary.get("overall_result", ""))
                    row["overall_decision_reason"] = _sanitize_cell(summary.get("overall_decision_reason", ""))
                    by_rule = {
                        str(check.get("rule_id", "")): check
                        for check in summary.get("checks", [])
                        if isinstance(check, dict)
                    }

                    must_attention_rules: list[str] = []
                    must_attention_notes: list[str] = []
                    must_attention_urls: list[str] = []

                    for rule_id in RESULT_RULE_COLUMNS:
                        check = by_rule.get(rule_id, {})
                        if isinstance(check, dict):
                            result = _sanitize_cell(check.get("result", ""))
                            note = _sanitize_cell(check.get("notes", ""))
                            problem_urls = _check_problem_urls(check, raw_source_urls)
                        else:
                            result = ""
                            note = ""
                            problem_urls = []

                        row[rule_id] = result
                        row[f"{rule_id}__note"] = note
                        if result in {"fail", "need_human_review"}:
                            row[f"{rule_id}__problem_urls"] = _join_csv_cell(problem_urls)
                            if result:
                                must_attention_rules.append(f"{rule_id}:{result}")
                            if note:
                                must_attention_notes.append(f"{rule_id}:{note}")
                            for url in problem_urls:
                                must_attention_urls.append(f"{rule_id}:{url}")
                        else:
                            row[f"{rule_id}__problem_urls"] = ""

                    supplementary_checks = [
                        check for check in summary.get("supplementary_checks", []) if isinstance(check, dict)
                    ]
                    supplementary_attention_rules: list[str] = []
                    supplementary_attention_notes: list[str] = []
                    supplementary_attention_urls: list[str] = []
                    for check in supplementary_checks:
                        result = _sanitize_cell(check.get("result", ""))
                        if result not in {"fail", "need_human_review"}:
                            continue
                        rule_id = _sanitize_cell(check.get("rule_id", ""))
                        note = _sanitize_cell(check.get("notes", ""))
                        urls = _check_problem_urls(check, raw_source_urls)
                        if rule_id:
                            supplementary_attention_rules.append(f"{rule_id}:{result}")
                        if note:
                            supplementary_attention_notes.append(f"{rule_id}:{note}")
                        for url in urls:
                            supplementary_attention_urls.append(f"{rule_id}:{url}")

                    row["must_attention_rules"] = _join_csv_cell(must_attention_rules)
                    row["must_attention_notes"] = _join_csv_cell(must_attention_notes)
                    row["must_attention_urls"] = _join_csv_cell(must_attention_urls)
                    row["supplementary_attention_rules"] = _join_csv_cell(supplementary_attention_rules)
                    row["supplementary_attention_notes"] = _join_csv_cell(supplementary_attention_notes)
                    row["supplementary_attention_urls"] = _join_csv_cell(supplementary_attention_urls)
                except Exception:
                    row["overall_result"] = "unknown"
            rows.append(row)
        return rows

    def render_export_csv(self, limit: int | None = None) -> str:
        fieldnames = _export_fieldnames()
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=fieldnames)
        writer.writeheader()
        for row in self.export_rows(limit=limit):
            writer.writerow({key: row.get(key, "") for key in fieldnames})
        return buffer.getvalue()


def _html_page() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>DOAJ Reviewer Simulation</title>
  <style>
    :root { --bg:#f7f9fc; --panel:#ffffff; --line:#d7dde8; --ink:#1f2937; --muted:#5b6474; --ok:#1f7a4f; --warn:#8a6a0a; --bad:#9b1c1c; --accent:#0b5fff; }
    * { box-sizing: border-box; }
    body { margin:0; font-family: "IBM Plex Sans", "Segoe UI", sans-serif; background:linear-gradient(180deg,#eef3fb,#f8fbff); color:var(--ink); }
    .wrap { max-width: 1200px; margin: 24px auto; padding: 0 16px 24px; display:grid; grid-template-columns: 1.2fr 1fr; gap:16px; }
    .card { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:16px; box-shadow:0 8px 22px rgba(15,23,42,.05);}
    h1 { margin:0 0 8px; font-size: 24px; }
    .muted { color:var(--muted); font-size: 14px; margin-bottom: 12px; }
    .grid { display:grid; grid-template-columns: 1fr 1fr; gap:10px; }
    label { display:block; font-size:12px; color:var(--muted); margin: 0 0 4px; }
    input, select, textarea, button { width:100%; border:1px solid var(--line); border-radius:8px; padding:10px; font:inherit; }
    textarea { min-height: 74px; resize: vertical; }
    .urls { display:grid; grid-template-columns: 1fr; gap:10px; margin-top: 10px; }
    .manual { display:grid; grid-template-columns: 1fr 1fr; gap:10px; margin-top: 10px; }
    button { background:var(--accent); color:white; border:none; cursor:pointer; font-weight:600; }
    button.secondary { background:#334155; }
    .actions { display:grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap:10px; margin-top:12px; }
    .result-actions { display:grid; grid-template-columns: 1fr 1fr; gap:8px; margin:8px 0 10px; }
    .result-actions button[disabled] { opacity:0.55; cursor:not-allowed; }
    table { width:100%; border-collapse:collapse; font-size:13px; margin-top:10px; }
    th, td { border-bottom:1px solid var(--line); text-align:left; padding:6px; vertical-align:top; }
    .badge { display:inline-block; padding:2px 8px; border-radius:999px; font-size:12px; font-weight:600; }
    .pass { background:#e8f7ef; color:var(--ok); }
    .need_human_review { background:#fff7df; color:var(--warn); }
    .fail { background:#fdecec; color:var(--bad); }
    .not_provided { background:#eef2f7; color:#475569; }
    code { background:#f1f5f9; padding:1px 6px; border-radius:6px; }
    .run-list a, .artifacts a { color:#0b5fff; text-decoration:none; }
    .run-list li { margin-bottom:6px; }
    @media (max-width: 980px) { .wrap { grid-template-columns: 1fr; } .manual { grid-template-columns: 1fr; } .grid { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <h1>DOAJ Reviewer Simulation</h1>
      <div class="muted">Use this realistic form to test URL crawling, rule checks, and generated artifacts per run.</div>
      <div class="grid">
        <div>
          <label>Submission ID (optional)</label>
          <input id="submission_id" placeholder="SIM-001">
        </div>
        <div>
          <label>Publication Model</label>
          <select id="publication_model">
            <option value="issue_based">issue_based</option>
            <option value="continuous">continuous</option>
          </select>
        </div>
        <div>
          <label>JS Mode</label>
          <select id="js_mode">
            <option value="auto">auto</option>
            <option value="off">off</option>
            <option value="on">on</option>
          </select>
        </div>
      </div>
      <div class="urls">
        <div><label>1. Open Access statement URL(s) (required)</label><textarea id="open_access_statement"></textarea></div>
        <div><label>2. Journal Homepage URL (required)</label><input id="journal_homepage_url" placeholder="https://example-journal.org"></div>
        <div><label>3. ISSN evidence URL(s) (required, prioritize electronic ISSN)</label><textarea id="issn_consistency"></textarea></div>
        <div><label>4. Publisher information URL(s) (required)</label><textarea id="publisher_identity"></textarea></div>
        <div><label>5. License terms URL(s) (required)</label><textarea id="license_terms"></textarea></div>
        <div><label>6. Copyright policy URL(s) (required)</label><textarea id="copyright_author_rights"></textarea></div>
        <div><label>7. Peer review policy URL(s) (required)</label><textarea id="peer_review_policy"></textarea></div>
        <div><label>8. Plagiarism policy URL(s) (optional)</label><textarea id="plagiarism_policy"></textarea></div>
        <div><label>9. Aims / Focus and Scope URL(s) (required)</label><textarea id="aims_scope"></textarea></div>
        <div><label>10. Editorial board URL(s) (required)</label><textarea id="editorial_board"></textarea></div>
        <div><label>11. Reviewer list URL(s) (optional)</label><textarea id="reviewers"></textarea></div>
        <div>
          <label>12. Latest issue URL(s) for endogeny (required, latest 2 issues; one URL per line, newest first)</label>
          <textarea id="latest_content" placeholder="https://example-journal.org/volume-12-issue-2&#10;https://example-journal.org/volume-12-issue-1"></textarea>
          <div style="font-size:12px;color:#5b6474;margin-top:4px;">Line 1 = latest issue, line 2 = previous issue. For continuous model, provide content/archive URLs covering the last calendar year.</div>
        </div>
        <div><label>13. Instructions for authors URL(s) (required)</label><textarea id="instructions_for_authors"></textarea></div>
        <div><label>14. Publication fee/APC URL(s) (required)</label><textarea id="publication_fees_disclosure"></textarea></div>
        <div><label>15. Archiving policy URL(s) (optional)</label><textarea id="archiving_policy"></textarea></div>
        <div><label>16. Repository policy URL(s) (optional)</label><textarea id="repository_policy"></textarea></div>
        <div><label>17. Archive URL(s) (optional support for continuous model)</label><textarea id="archives"></textarea></div>
      </div>
      <h3 style="margin:14px 0 6px;font-size:15px;">Manual fallback (optional, for WAF/Cloudflare blocks)</h3>
      <div class="muted" style="margin-bottom:6px;">If a policy URL is blocked, paste text and/or upload one PDF for that policy.</div>
      <div class="manual">
        <div><label>Open Access manual text</label><textarea id="manual_text_open_access_statement"></textarea><label>Open Access PDF (optional)</label><input id="manual_pdf_open_access_statement" type="file" accept=".pdf,application/pdf"></div>
        <div><label>ISSN manual text</label><textarea id="manual_text_issn_consistency"></textarea><label>ISSN PDF (optional)</label><input id="manual_pdf_issn_consistency" type="file" accept=".pdf,application/pdf"></div>
        <div><label>Publisher identity manual text</label><textarea id="manual_text_publisher_identity"></textarea><label>Publisher identity PDF (optional)</label><input id="manual_pdf_publisher_identity" type="file" accept=".pdf,application/pdf"></div>
        <div><label>License terms manual text</label><textarea id="manual_text_license_terms"></textarea><label>License terms PDF (optional)</label><input id="manual_pdf_license_terms" type="file" accept=".pdf,application/pdf"></div>
        <div><label>Copyright policy manual text</label><textarea id="manual_text_copyright_author_rights"></textarea><label>Copyright policy PDF (optional)</label><input id="manual_pdf_copyright_author_rights" type="file" accept=".pdf,application/pdf"></div>
        <div><label>Peer review policy manual text</label><textarea id="manual_text_peer_review_policy"></textarea><label>Peer review policy PDF (optional)</label><input id="manual_pdf_peer_review_policy" type="file" accept=".pdf,application/pdf"></div>
        <div><label>Plagiarism policy manual text</label><textarea id="manual_text_plagiarism_policy"></textarea><label>Plagiarism policy PDF (optional)</label><input id="manual_pdf_plagiarism_policy" type="file" accept=".pdf,application/pdf"></div>
        <div><label>Aims/scope manual text</label><textarea id="manual_text_aims_scope"></textarea><label>Aims/scope PDF (optional)</label><input id="manual_pdf_aims_scope" type="file" accept=".pdf,application/pdf"></div>
        <div><label>Publication fee/APC manual text</label><textarea id="manual_text_publication_fees_disclosure"></textarea><label>Publication fee/APC PDF (optional)</label><input id="manual_pdf_publication_fees_disclosure" type="file" accept=".pdf,application/pdf"></div>
        <div><label>Archiving policy manual text</label><textarea id="manual_text_archiving_policy"></textarea><label>Archiving policy PDF (optional)</label><input id="manual_pdf_archiving_policy" type="file" accept=".pdf,application/pdf"></div>
        <div><label>Repository policy manual text</label><textarea id="manual_text_repository_policy"></textarea><label>Repository policy PDF (optional)</label><input id="manual_pdf_repository_policy" type="file" accept=".pdf,application/pdf"></div>
        <div><label>Instructions for authors manual text</label><textarea id="manual_text_instructions_for_authors"></textarea><label>Instructions PDF (optional)</label><input id="manual_pdf_instructions_for_authors" type="file" accept=".pdf,application/pdf"></div>
      </div>
      <div class="actions">
        <button id="fillSample" type="button" class="secondary">Fill sample</button>
        <button id="resetBtn" type="button" class="secondary">Reset form</button>
        <button id="submitBtn" type="button">Run simulation</button>
      </div>
    </div>
    <div class="card">
      <h2 style="margin:0 0 8px;font-size:18px;">Result</h2>
      <div id="status" class="muted">No run yet.</div>
      <div id="warnings" class="muted"></div>
      <div class="result-actions">
        <button id="printPdfBtn" type="button" class="secondary" disabled>Print to PDF</button>
        <button id="downloadTxtBtn" type="button" class="secondary" disabled>Download text</button>
      </div>
      <div id="artifacts" class="artifacts"></div>
      <div id="checks"></div>
      <h3 style="margin-top:14px;">Recent runs</h3>
      <div class="muted"><a href="/api/export.csv?limit=all" target="_blank">Download all runs CSV</a></div>
      <ul id="runs" class="run-list"></ul>
    </div>
  </div>
<script>
const fields = [
  "submission_id","publication_model","js_mode",
  "open_access_statement","journal_homepage_url","issn_consistency","publisher_identity",
  "license_terms","copyright_author_rights","peer_review_policy",
  "plagiarism_policy","aims_scope","editorial_board","reviewers",
  "latest_content","instructions_for_authors","publication_fees_disclosure",
  "archiving_policy","repository_policy","archives"
];
const manualPolicyHints = [
  "open_access_statement","issn_consistency","publisher_identity","license_terms",
  "copyright_author_rights","peer_review_policy","plagiarism_policy","aims_scope",
  "publication_fees_disclosure","archiving_policy","repository_policy","instructions_for_authors"
];
const sample = {
  journal_homepage_url: "https://example-journal.org",
  publication_model: "issue_based",
  js_mode: "auto",
  open_access_statement: "https://example-journal.org/open-access",
  issn_consistency: "https://example-journal.org/about",
  publisher_identity: "https://example-journal.org/publisher",
  license_terms: "https://example-journal.org/licensing",
  copyright_author_rights: "https://example-journal.org/copyright",
  peer_review_policy: "https://example-journal.org/peer-review",
  plagiarism_policy: "https://example-journal.org/plagiarism",
  aims_scope: "https://example-journal.org/aims-and-scope",
  editorial_board: "https://example-journal.org/editorial-board",
  reviewers: "https://example-journal.org/reviewers",
  latest_content: "https://example-journal.org/volume-12-issue-2\\nhttps://example-journal.org/volume-12-issue-1",
  instructions_for_authors: "https://example-journal.org/instructions",
  publication_fees_disclosure: "https://example-journal.org/apc",
  archiving_policy: "https://example-journal.org/archiving",
  repository_policy: "https://example-journal.org/repository-policy",
  archives: "https://example-journal.org/archive"
};
let latestResult = null;

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll("\"", "&quot;")
    .replaceAll("'", "&#39;");
}

function setResultActions(enabled) {
  document.getElementById("printPdfBtn").disabled = !enabled;
  document.getElementById("downloadTxtBtn").disabled = !enabled;
}

function badge(result) { return '<span class="badge '+result+'">'+result+'</span>'; }

function getFieldValue(id) {
  const el = document.getElementById(id);
  if (!el) throw new Error("UI field not found: " + id);
  return el.value || "";
}

function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const out = String(reader.result || "");
      const marker = "base64,";
      const idx = out.indexOf(marker);
      if (idx >= 0) resolve(out.slice(idx + marker.length));
      else resolve(out);
    };
    reader.onerror = () => reject(reader.error || new Error("file read failed"));
    reader.readAsDataURL(file);
  });
}

async function payloadFromForm() {
  const body = {};
  for (const id of fields) body[id] = getFieldValue(id);
  const manual_policy_pages = [];
  for (const hint of manualPolicyHints) {
    const textEl = document.getElementById("manual_text_" + hint);
    if (!textEl) throw new Error("Manual text field not found: manual_text_" + hint);
    const textValue = (textEl.value || "").trim();
    if (textValue) {
      manual_policy_pages.push({
        rule_hint: hint,
        title: "Manual fallback text",
        source_label: "manual://" + hint + "/text",
        text: textValue
      });
    }
    const fileInput = document.getElementById("manual_pdf_" + hint);
    const file = fileInput && fileInput.files && fileInput.files.length ? fileInput.files[0] : null;
    if (file) {
      try {
        const pdfBase64 = await readFileAsBase64(file);
        manual_policy_pages.push({
          rule_hint: hint,
          title: "Manual PDF: " + file.name,
          source_label: "manual://" + hint + "/pdf",
          file_name: file.name,
          pdf_base64: pdfBase64
        });
      } catch (_) {
        // Server-side warnings still handle non-readable files.
      }
    }
  }
  if (manual_policy_pages.length) body.manual_policy_pages = manual_policy_pages;
  return body;
}

function setStatus(text) { document.getElementById("status").textContent = text; }

window.addEventListener("error", (event) => {
  const msg = event && event.message ? event.message : "unknown UI error";
  setStatus("UI error: " + msg);
});

window.addEventListener("unhandledrejection", (event) => {
  const reason = event && event.reason ? (event.reason.message || String(event.reason)) : "unknown async error";
  setStatus("UI async error: " + reason);
});

function resetForm() {
  for (const id of fields) {
    if (id === "publication_model") {
      document.getElementById(id).value = "issue_based";
      continue;
    }
    if (id === "js_mode") {
      document.getElementById(id).value = "auto";
      continue;
    }
    document.getElementById(id).value = "";
  }
  document.getElementById("artifacts").innerHTML = "";
  document.getElementById("checks").innerHTML = "";
  document.getElementById("warnings").innerHTML = "";
  for (const hint of manualPolicyHints) {
    const textEl = document.getElementById("manual_text_" + hint);
    const fileEl = document.getElementById("manual_pdf_" + hint);
    if (textEl) textEl.value = "";
    if (fileEl) fileEl.value = "";
  }
  setStatus("Form reset. Ready for a new simulation.");
  document.getElementById("submission_id").focus();
  latestResult = null;
  setResultActions(false);
}

function buildPlainTextResult(data) {
  const lines = [];
  lines.push("DOAJ Reviewer Simulation Result");
  lines.push("=============================");
  lines.push("Run ID        : " + (data.run_id || ""));
  lines.push("Submission ID : " + (data.submission_id || ""));
  lines.push("Overall       : " + (data.overall_result || ""));
  lines.push("");
  lines.push("Must Checks");
  lines.push("-----------");
  const checks = data.checks || [];
  checks.forEach((item, idx) => {
    lines.push((idx + 1) + ". Rule ID    : " + (item.rule_id || ""));
    lines.push("   Result     : " + (item.result || ""));
    lines.push("   Confidence : " + (item.confidence ?? ""));
    lines.push("   Notes      : " + (item.notes || ""));
    lines.push("");
  });
  const supplementary = data.supplementary_checks || [];
  if (supplementary.length) {
    lines.push("Supplementary Checks (Non-must)");
    lines.push("-------------------------------");
    supplementary.forEach((item, idx) => {
      lines.push((idx + 1) + ". Rule ID    : " + (item.rule_id || ""));
      lines.push("   Result     : " + (item.result || ""));
      lines.push("   Confidence : " + (item.confidence ?? ""));
      lines.push("   Notes      : " + (item.notes || ""));
      lines.push("");
    });
  }
  return lines.join("\\n").trim() + "\\n";
}

function buildPrintableHtml(data) {
  const mustRows = (data.checks || []).map(item =>
    `<tr><td>${escapeHtml(item.rule_id || "")}</td><td>${escapeHtml(item.result || "")}</td><td>${escapeHtml(item.confidence ?? "")}</td><td>${escapeHtml(item.notes || "")}</td></tr>`
  ).join("");
  const suppRows = (data.supplementary_checks || []).map(item =>
    `<tr><td>${escapeHtml(item.rule_id || "")}</td><td>${escapeHtml(item.result || "")}</td><td>${escapeHtml(item.confidence ?? "")}</td><td>${escapeHtml(item.notes || "")}</td></tr>`
  ).join("");
  const warnings = (data.warnings || []).map(item => `<li>${escapeHtml(item)}</li>`).join("");
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>DOAJ Simulation Result - ${escapeHtml(data.submission_id || data.run_id || "")}</title>
  <style>
    @page { size: A4; margin: 14mm; }
    body { font-family: "IBM Plex Sans", "Segoe UI", sans-serif; color: #1f2937; }
    h1 { margin: 0 0 10px; font-size: 22px; }
    h2 { margin: 14px 0 8px; font-size: 16px; }
    .meta { margin-bottom: 8px; font-size: 13px; }
    .meta div { margin: 2px 0; }
    table { width: 100%; border-collapse: collapse; font-size: 12px; }
    th, td { border: 1px solid #d7dde8; padding: 6px; vertical-align: top; text-align: left; }
    th { background: #eef3fb; }
    ul { margin: 6px 0 0 18px; padding: 0; font-size: 12px; }
  </style>
</head>
<body>
  <h1>DOAJ Reviewer Simulation Result</h1>
  <div class="meta">
    <div><strong>Run ID:</strong> ${escapeHtml(data.run_id || "")}</div>
    <div><strong>Submission ID:</strong> ${escapeHtml(data.submission_id || "")}</div>
    <div><strong>Overall Decision:</strong> ${escapeHtml(data.overall_result || "")}</div>
  </div>
  ${warnings ? `<h2>Warnings</h2><ul>${warnings}</ul>` : ""}
  <h2>Must Checks</h2>
  <table>
    <thead><tr><th>Rule</th><th>Result</th><th>Confidence</th><th>Notes</th></tr></thead>
    <tbody>${mustRows || "<tr><td colspan='4'>No data</td></tr>"}</tbody>
  </table>
  <h2>Supplementary Checks (Non-must)</h2>
  <table>
    <thead><tr><th>Rule</th><th>Result</th><th>Confidence</th><th>Notes</th></tr></thead>
    <tbody>${suppRows || "<tr><td colspan='4'>No data</td></tr>"}</tbody>
  </table>
</body>
</html>`;
}

function printResultToPdf() {
  if (!latestResult) return;
  const printWin = window.open("", "_blank");
  if (!printWin) {
    alert("Pop-up blocked. Please allow pop-ups for this page.");
    return;
  }
  printWin.document.open();
  printWin.document.write(buildPrintableHtml(latestResult));
  printWin.document.close();
  printWin.focus();
  setTimeout(() => {
    printWin.print();
  }, 250);
}

function downloadResultText() {
  if (!latestResult) return;
  const text = buildPlainTextResult(latestResult);
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  const fileToken = (latestResult.submission_id || latestResult.run_id || "simulation").replace(/[^a-zA-Z0-9._-]+/g, "_");
  anchor.href = url;
  anchor.download = `doaj-review-${fileToken}.txt`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function renderResult(data) {
  const warnings = data.warnings || [];
  document.getElementById("warnings").innerHTML = warnings.length
    ? ("Warnings: " + warnings.map(w => `<code>${w}</code>`).join(" | "))
    : "";
  if (!data.ok) {
    latestResult = null;
    setResultActions(false);
    setStatus("Run failed: " + (data.errors || []).join("; "));
    const artifacts = data.artifacts || {};
    document.getElementById("artifacts").innerHTML =
      Object.entries(artifacts).map(([k,v]) => `<div><a href="${v}" target="_blank">${k}</a></div>`).join("");
    return;
  }
  latestResult = data;
  setResultActions(true);
  setStatus(`run_id=${data.run_id} | overall=${data.overall_result}`);
  document.getElementById("artifacts").innerHTML =
    Object.entries(data.artifacts || {}).map(([k,v]) => `<div><a href="${v}" target="_blank">${k}</a></div>`).join("");
  const rowsMain = (data.checks || []).map(c =>
    `<tr><td><code>${c.rule_id}</code></td><td>${badge(c.result)}</td><td>${c.confidence}</td><td>${c.notes || ""}</td></tr>`
  ).join("");
  const rowsSupplementary = (data.supplementary_checks || []).map(c =>
    `<tr><td><code>${c.rule_id}</code></td><td>${badge(c.result)}</td><td>${c.confidence}</td><td>${c.notes || ""}</td></tr>`
  ).join("");
  document.getElementById("checks").innerHTML =
    `<h3>Must checks</h3><table><thead><tr><th>Rule</th><th>Result</th><th>Confidence</th><th>Notes</th></tr></thead><tbody>${rowsMain}</tbody></table>`
    + `<h3 style="margin-top:12px;">Supplementary checks (non-must)</h3><table><thead><tr><th>Rule</th><th>Result</th><th>Confidence</th><th>Notes</th></tr></thead><tbody>${rowsSupplementary}</tbody></table>`;
}

async function loadRuns() {
  const res = await fetch("/api/runs");
  const data = await res.json();
  const items = (data.runs || []).map(r =>
    `<li><code>${r.run_id}</code> - ${r.overall_result} - <a href="${r.summary_json}" target="_blank">summary</a> - <a href="${r.raw_json}" target="_blank">raw</a></li>`
  ).join("");
  document.getElementById("runs").innerHTML = items || "<li>No runs yet.</li>";
}

document.getElementById("fillSample").addEventListener("click", () => {
  for (const [k,v] of Object.entries(sample)) document.getElementById(k).value = v;
  for (const hint of manualPolicyHints) {
    const textEl = document.getElementById("manual_text_" + hint);
    const fileEl = document.getElementById("manual_pdf_" + hint);
    if (textEl) textEl.value = "";
    if (fileEl) fileEl.value = "";
  }
  document.getElementById("warnings").innerHTML = "";
});

document.getElementById("resetBtn").addEventListener("click", () => {
  resetForm();
});

document.getElementById("printPdfBtn").addEventListener("click", () => {
  printResultToPdf();
});

document.getElementById("downloadTxtBtn").addEventListener("click", () => {
  downloadResultText();
});

document.getElementById("submitBtn").addEventListener("click", async () => {
  const submitBtn = document.getElementById("submitBtn");
  if (submitBtn.disabled) return;

  const originalLabel = submitBtn.textContent || "Run simulation";
  submitBtn.disabled = true;
  submitBtn.textContent = "Running...";

  const controller = new AbortController();
  const timeoutMs = 5 * 60 * 1000;
  const timeoutHandle = setTimeout(() => controller.abort(), timeoutMs);

  try {
    setStatus("Running simulation... this can take up to 5 minutes for JS-heavy or WAF-protected sites.");
    document.getElementById("checks").innerHTML = "";
    document.getElementById("warnings").innerHTML = "";

    const payload = await payloadFromForm();
    const res = await fetch("/api/submit", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify(payload),
      signal: controller.signal
    });

    const rawText = await res.text();
    let data = {};
    try {
      data = JSON.parse(rawText || "{}");
    } catch (_) {
      data = {
        ok: false,
        errors: [`Server returned non-JSON response (HTTP ${res.status}).`]
      };
    }

    if (!res.ok && !data.ok) {
      const err = data.errors || [`HTTP ${res.status}`];
      renderResult({
        ok: false,
        errors: err,
        warnings: data.warnings || [],
        artifacts: data.artifacts || {}
      });
      return;
    }

    renderResult(data);
    await loadRuns();
  } catch (err) {
    const message = (err && err.name === "AbortError")
      ? "Simulation request timed out after 5 minutes. Try fewer URLs or run again."
      : ("Simulation request failed: " + (err && err.message ? err.message : "unknown error"));
    renderResult({
      ok: false,
      errors: [message],
      warnings: [],
      artifacts: {}
    });
  } finally {
    clearTimeout(timeoutHandle);
    submitBtn.disabled = false;
    submitBtn.textContent = originalLabel;
  }
});

setResultActions(false);
loadRuns();
</script>
</body>
</html>
"""


def make_handler(app: SimulationApp):
    class Handler(BaseHTTPRequestHandler):
        def _json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _text(self, status: int, text: str, content_type: str, headers: dict[str, str] | None = None) -> None:
            body = text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            if headers:
                for key, value in headers.items():
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)

            if path == "/":
                self._text(HTTPStatus.OK, _html_page(), "text/html; charset=utf-8")
                return
            if path == "/api/health":
                self._json(HTTPStatus.OK, {"ok": True})
                return
            if path == "/api/runs":
                limit = _parse_limit((query.get("limit") or [None])[0], default=20)
                self._json(HTTPStatus.OK, {"ok": True, "runs": app.list_runs(limit=limit)})
                return
            if path == "/api/export.csv":
                limit = _parse_limit((query.get("limit") or [None])[0], default=None)
                csv_text = app.render_export_csv(limit=limit)
                self._text(
                    HTTPStatus.OK,
                    csv_text,
                    "text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="runs-overview.csv"'},
                )
                return
            if path.startswith("/runs/"):
                rel = unquote(path[len("/runs/"):]).lstrip("/")
                candidate = (app.runs_dir / rel).resolve()
                if not str(candidate).startswith(str(app.runs_dir.resolve())):
                    self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "errors": ["invalid path"]})
                    return
                if not candidate.exists() or not candidate.is_file():
                    self._json(HTTPStatus.NOT_FOUND, {"ok": False, "errors": ["not found"]})
                    return
                ctype = "text/plain; charset=utf-8"
                if candidate.suffix.lower() == ".json":
                    ctype = "application/json; charset=utf-8"
                if candidate.suffix.lower() == ".md":
                    ctype = "text/markdown; charset=utf-8"
                headers = None
                if candidate.suffix.lower() == ".txt":
                    headers = {"Content-Disposition": f'attachment; filename="{candidate.name}"'}
                self._text(HTTPStatus.OK, candidate.read_text(encoding="utf-8"), ctype, headers=headers)
                return
            self._json(HTTPStatus.NOT_FOUND, {"ok": False, "errors": ["route not found"]})

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/api/submit":
                self._json(HTTPStatus.NOT_FOUND, {"ok": False, "errors": ["route not found"]})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                payload = json.loads(body.decode("utf-8")) if body else {}
                if not isinstance(payload, dict):
                    raise ValueError("payload must be object")
            except Exception:
                self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "errors": ["invalid JSON payload"]})
                return

            result = app.run_submission(payload)
            status = HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST
            self._json(status, result)

    return Handler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local simulation server for DOAJ Reviewer.")
    parser.add_argument("--host", default="127.0.0.1", help="Host bind. Default: 127.0.0.1")
    parser.add_argument("--port", type=int, default=8787, help="Port bind. Default: 8787")
    parser.add_argument(
        "--ruleset",
        default=str(DEFAULT_RULESET_PATH),
        help="Path to ruleset JSON. Default: specs/reviewer/rules/ruleset.must.v1.json",
    )
    parser.add_argument(
        "--runs-dir",
        default=str(DEFAULT_RUNS_DIR),
        help="Directory to store run artifacts. Default: ./runs",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    app = SimulationApp(ruleset_path=Path(args.ruleset), runs_dir=Path(args.runs_dir))
    handler_cls = make_handler(app)
    server = ThreadingHTTPServer((args.host, args.port), handler_cls)
    print(f"DOAJ Reviewer Simulation server running on http://{args.host}:{args.port}")
    print(f"Ruleset: {Path(args.ruleset).resolve()}")
    print(f"Runs dir: {Path(args.runs_dir).resolve()}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
