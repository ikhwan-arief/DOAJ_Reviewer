"""CLI entrypoint to evaluate a submission against endogeny rule."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .endogeny import evaluate_endogeny
from .intake import build_structured_submission_from_raw
from .reporting import render_endogeny_markdown


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(content)


def _maybe_validate_schema(evaluation: dict[str, Any], schema_path: Path) -> str:
    try:
        import jsonschema  # type: ignore
    except ImportError:
        return "skipped (jsonschema package not installed)"

    schema = _load_json(schema_path)
    jsonschema.validate(instance=evaluation, schema=schema)
    return "ok"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate DOAJ submission (endogeny rule).")
    parser.add_argument("--submission", required=True, help="Path to submission JSON.")
    parser.add_argument(
        "--input-mode",
        choices=["structured", "raw"],
        default="structured",
        help="Whether --submission points to a structured submission or raw URL-based submission.",
    )
    parser.add_argument(
        "--structured-output",
        default="artifacts/submission.structured.json",
        help="Path to save built structured submission when --input-mode raw is used.",
    )
    parser.add_argument(
        "--js-mode",
        choices=["off", "auto", "on"],
        default="auto",
        help="JS rendering mode used when --input-mode raw.",
    )
    parser.add_argument("--output-json", default="artifacts/endogeny-result.json", help="Path to output JSON report.")
    parser.add_argument("--output-md", default="artifacts/endogeny-report.md", help="Path to output Markdown report.")
    parser.add_argument(
        "--schema",
        default="specs/reviewer/schemas/endogeny-evaluation.schema.json",
        help="Path to endogeny evaluation JSON schema.",
    )
    parser.add_argument("--validate-schema", action="store_true", help="Validate output against JSON schema if jsonschema is available.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    submission_input = _load_json(Path(args.submission))
    if args.input_mode == "raw":
        submission = build_structured_submission_from_raw(submission_input, js_mode=args.js_mode)
        _write_json(Path(args.structured_output), submission)
        print(f"Structured submission output: {args.structured_output}")
    else:
        submission = submission_input

    evaluation = evaluate_endogeny(submission)
    report_md = render_endogeny_markdown(evaluation)

    json_path = Path(args.output_json)
    md_path = Path(args.output_md)
    _write_json(json_path, evaluation)
    _write_text(md_path, report_md)

    schema_status = "not requested"
    if args.validate_schema:
        schema_status = _maybe_validate_schema(evaluation, Path(args.schema))

    print(f"Decision: {evaluation['result']}")
    print(f"Confidence: {evaluation['confidence']}")
    print(f"JSON output: {json_path}")
    print(f"Markdown output: {md_path}")
    print(f"Schema validation: {schema_status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
