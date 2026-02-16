#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  ./scripts/export_docx.sh [INPUT_MD] [OUTPUT_DOCX]

Examples:
  ./scripts/export_docx.sh
  ./scripts/export_docx.sh LAPORAN_PROYEK_2026-02-16.md
  ./scripts/export_docx.sh LAPORAN_PROYEK_2026-02-16.md LAPORAN_PROYEK_2026-02-16.docx

Notes:
  - Requires pandoc.
  - If pandoc is missing on macOS, install with: brew install pandoc
USAGE
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

input_md="${1:-LAPORAN_PROYEK_2026-02-16.md}"
if [[ ! -f "${input_md}" ]]; then
  echo "Error: input file not found: ${input_md}" >&2
  exit 1
fi

default_output="${input_md%.md}.docx"
output_docx="${2:-${default_output}}"

if ! command -v pandoc >/dev/null 2>&1; then
  echo "Error: pandoc is not installed." >&2
  echo "Install on macOS with: brew install pandoc" >&2
  exit 127
fi

out_dir="$(dirname "${output_docx}")"
mkdir -p "${out_dir}"

pandoc "${input_md}" -o "${output_docx}"
echo "DOCX exported: ${output_docx}"
