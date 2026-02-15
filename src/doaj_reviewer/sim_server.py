"""Local simulation server for realistic form-based reviewer testing."""

from __future__ import annotations

import argparse
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
from .review import render_review_summary_markdown, run_review


URL_FIELDS = [
    "editorial_board",
    "reviewers",
    "latest_content",
    "archives",
    "open_access_statement",
    "aims_scope",
    "instructions_for_authors",
    "peer_review_policy",
    "license_terms",
    "copyright_author_rights",
    "publication_fees_disclosure",
    "publisher_identity",
    "issn_consistency",
]

RESULT_RULE_COLUMNS = [
    "doaj.open_access_statement.v1",
    "doaj.aims_scope.v1",
    "doaj.editorial_board.v1",
    "doaj.instructions_for_authors.v1",
    "doaj.peer_review_policy.v1",
    "doaj.license_terms.v1",
    "doaj.copyright_author_rights.v1",
    "doaj.publication_fees_disclosure.v1",
    "doaj.publisher_identity.v1",
    "doaj.issn_consistency.v1",
    "doaj.endogeny.v1",
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

    return {
        "submission_id": submission_id,
        "journal_homepage_url": homepage,
        "publication_model": publication_model,
        "source_urls": source_urls,
    }


def validate_raw_submission(raw: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not str(raw.get("journal_homepage_url", "")).strip():
        errors.append("journal_homepage_url is required")
    source_urls = raw.get("source_urls", {})
    if not isinstance(source_urls, dict):
        errors.append("source_urls must be an object")
        return errors
    if not source_urls.get("editorial_board"):
        errors.append("At least one editorial_board URL is required")
    if not source_urls.get("latest_content"):
        errors.append("At least one latest_content URL is required")
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
        errors = validate_raw_submission(raw)
        if errors:
            return {
                "ok": False,
                "errors": errors,
            }

        run_id = f"{_now_stamp()}-{uuid4().hex[:8]}"
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        raw_path = run_dir / "submission.raw.json"
        structured_path = run_dir / "submission.structured.json"
        summary_json_path = run_dir / "review-summary.json"
        summary_md_path = run_dir / "review-summary.md"
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
            _write_json(endogeny_json_path, endogeny)
            _write_text(endogeny_md_path, render_endogeny_markdown(endogeny))

            artifacts = {
                "raw": f"/runs/{run_id}/submission.raw.json",
                "structured": f"/runs/{run_id}/submission.structured.json",
                "summary_json": f"/runs/{run_id}/review-summary.json",
                "summary_md": f"/runs/{run_id}/review-summary.md",
                "endogeny_json": f"/runs/{run_id}/endogeny-result.json",
                "endogeny_md": f"/runs/{run_id}/endogeny-report.md",
            }
            return {
                "ok": True,
                "run_id": run_id,
                "overall_result": summary.get("overall_result", "need_human_review"),
                "checks": summary.get("checks", []),
                "artifacts": artifacts,
            }
        except Exception:
            stack = traceback.format_exc()
            _write_text(error_path, stack)
            return {
                "ok": False,
                "run_id": run_id,
                "errors": ["review run failed"],
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
        for run_dir in self._run_dirs(limit=limit):
            row = {
                "run_id": run_dir.name,
                "submission_id": "",
                "overall_result": "not_available",
            }
            for rule_id in RESULT_RULE_COLUMNS:
                row[rule_id] = ""

            raw_file = run_dir / "submission.raw.json"
            if raw_file.exists():
                try:
                    raw = _read_json(raw_file)
                    row["submission_id"] = str(raw.get("submission_id", ""))
                except Exception:
                    row["submission_id"] = ""

            summary_file = run_dir / "review-summary.json"
            if summary_file.exists():
                try:
                    summary = _read_json(summary_file)
                    row["submission_id"] = str(summary.get("submission_id", row["submission_id"]))
                    row["overall_result"] = str(summary.get("overall_result", ""))
                    by_rule = {
                        str(check.get("rule_id", "")): str(check.get("result", ""))
                        for check in summary.get("checks", [])
                        if isinstance(check, dict)
                    }
                    for rule_id in RESULT_RULE_COLUMNS:
                        row[rule_id] = by_rule.get(rule_id, "")
                except Exception:
                    row["overall_result"] = "unknown"
            rows.append(row)
        return rows

    def render_export_csv(self, limit: int | None = None) -> str:
        fieldnames = ["run_id", "submission_id", "overall_result"] + RESULT_RULE_COLUMNS
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
    .urls { display:grid; grid-template-columns: 1fr 1fr; gap:10px; margin-top: 10px; }
    button { background:var(--accent); color:white; border:none; cursor:pointer; font-weight:600; }
    button.secondary { background:#334155; }
    .actions { display:grid; grid-template-columns: 1fr 1fr; gap:10px; margin-top:12px; }
    table { width:100%; border-collapse:collapse; font-size:13px; margin-top:10px; }
    th, td { border-bottom:1px solid var(--line); text-align:left; padding:6px; vertical-align:top; }
    .badge { display:inline-block; padding:2px 8px; border-radius:999px; font-size:12px; font-weight:600; }
    .pass { background:#e8f7ef; color:var(--ok); }
    .need_human_review { background:#fff7df; color:var(--warn); }
    .fail { background:#fdecec; color:var(--bad); }
    code { background:#f1f5f9; padding:1px 6px; border-radius:6px; }
    .run-list a, .artifacts a { color:#0b5fff; text-decoration:none; }
    .run-list li { margin-bottom:6px; }
    @media (max-width: 980px) { .wrap { grid-template-columns: 1fr; } .urls { grid-template-columns: 1fr; } .grid { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <h1>DOAJ Reviewer Simulation</h1>
      <div class="muted">Form nyata untuk bug testing: isi URL, submit, jalankan reviewer, simpan artifact per run.</div>
      <div class="grid">
        <div>
          <label>Submission ID (optional)</label>
          <input id="submission_id" placeholder="SIM-001">
        </div>
        <div>
          <label>Journal Homepage URL</label>
          <input id="journal_homepage_url" placeholder="https://example-journal.org">
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
        <div><label>editorial_board (1 URL per baris)</label><textarea id="editorial_board"></textarea></div>
        <div><label>reviewers</label><textarea id="reviewers"></textarea></div>
        <div><label>latest_content</label><textarea id="latest_content"></textarea></div>
        <div><label>archives</label><textarea id="archives"></textarea></div>
        <div><label>open_access_statement</label><textarea id="open_access_statement"></textarea></div>
        <div><label>aims_scope</label><textarea id="aims_scope"></textarea></div>
        <div><label>instructions_for_authors</label><textarea id="instructions_for_authors"></textarea></div>
        <div><label>peer_review_policy</label><textarea id="peer_review_policy"></textarea></div>
        <div><label>license_terms</label><textarea id="license_terms"></textarea></div>
        <div><label>copyright_author_rights</label><textarea id="copyright_author_rights"></textarea></div>
        <div><label>publication_fees_disclosure</label><textarea id="publication_fees_disclosure"></textarea></div>
        <div><label>publisher_identity</label><textarea id="publisher_identity"></textarea></div>
        <div><label>issn_consistency</label><textarea id="issn_consistency"></textarea></div>
      </div>
      <div class="actions">
        <button id="fillSample">Fill sample</button>
        <button id="submitBtn">Run simulation</button>
      </div>
    </div>
    <div class="card">
      <h2 style="margin:0 0 8px;font-size:18px;">Result</h2>
      <div id="status" class="muted">Belum ada run.</div>
      <div id="artifacts" class="artifacts"></div>
      <div id="checks"></div>
      <h3 style="margin-top:14px;">Recent runs</h3>
      <div class="muted"><a href="/api/export.csv?limit=all" target="_blank">Download all runs CSV</a></div>
      <ul id="runs" class="run-list"></ul>
    </div>
  </div>
<script>
const fields = [
  "submission_id","journal_homepage_url","publication_model","js_mode",
  "editorial_board","reviewers","latest_content","archives",
  "open_access_statement","aims_scope","instructions_for_authors",
  "peer_review_policy","license_terms","copyright_author_rights",
  "publication_fees_disclosure","publisher_identity","issn_consistency"
];
const sample = {
  journal_homepage_url: "https://example-journal.org",
  publication_model: "issue_based",
  js_mode: "auto",
  editorial_board: "https://example-journal.org/editorial-board",
  reviewers: "https://example-journal.org/reviewers",
  latest_content: "https://example-journal.org/volume-12-issue-2\\nhttps://example-journal.org/volume-12-issue-1",
  archives: "https://example-journal.org/archive",
  open_access_statement: "https://example-journal.org/open-access",
  aims_scope: "https://example-journal.org/aims-and-scope",
  instructions_for_authors: "https://example-journal.org/instructions",
  peer_review_policy: "https://example-journal.org/peer-review",
  license_terms: "https://example-journal.org/licensing",
  copyright_author_rights: "https://example-journal.org/copyright",
  publication_fees_disclosure: "https://example-journal.org/apc",
  publisher_identity: "https://example-journal.org/publisher",
  issn_consistency: "https://example-journal.org/about"
};

function badge(result) { return '<span class="badge '+result+'">'+result+'</span>'; }

function payloadFromForm() {
  const body = {};
  for (const id of fields) body[id] = document.getElementById(id).value || "";
  return body;
}

function setStatus(text) { document.getElementById("status").textContent = text; }

function renderResult(data) {
  if (!data.ok) {
    setStatus("Run gagal: " + (data.errors || []).join("; "));
    const artifacts = data.artifacts || {};
    document.getElementById("artifacts").innerHTML =
      Object.entries(artifacts).map(([k,v]) => `<div><a href="${v}" target="_blank">${k}</a></div>`).join("");
    return;
  }
  setStatus(`run_id=${data.run_id} | overall=${data.overall_result}`);
  document.getElementById("artifacts").innerHTML =
    Object.entries(data.artifacts || {}).map(([k,v]) => `<div><a href="${v}" target="_blank">${k}</a></div>`).join("");
  const rows = (data.checks || []).map(c =>
    `<tr><td><code>${c.rule_id}</code></td><td>${badge(c.result)}</td><td>${c.confidence}</td><td>${c.notes || ""}</td></tr>`
  ).join("");
  document.getElementById("checks").innerHTML =
    `<table><thead><tr><th>Rule</th><th>Result</th><th>Confidence</th><th>Notes</th></tr></thead><tbody>${rows}</tbody></table>`;
}

async function loadRuns() {
  const res = await fetch("/api/runs");
  const data = await res.json();
  const items = (data.runs || []).map(r =>
    `<li><code>${r.run_id}</code> - ${r.overall_result} - <a href="${r.summary_json}" target="_blank">summary</a> - <a href="${r.raw_json}" target="_blank">raw</a></li>`
  ).join("");
  document.getElementById("runs").innerHTML = items || "<li>Tidak ada run.</li>";
}

document.getElementById("fillSample").addEventListener("click", () => {
  for (const [k,v] of Object.entries(sample)) document.getElementById(k).value = v;
});

document.getElementById("submitBtn").addEventListener("click", async () => {
  setStatus("Menjalankan simulation...");
  document.getElementById("checks").innerHTML = "";
  const res = await fetch("/api/submit", {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify(payloadFromForm())
  });
  const data = await res.json();
  renderResult(data);
  await loadRuns();
});

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
                self._text(HTTPStatus.OK, candidate.read_text(encoding="utf-8"), ctype)
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
