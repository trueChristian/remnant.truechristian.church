#!/usr/bin/env python3
"""Run supported clean-checkout exporters with an explicit English-only path."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import uuid


class ExportError(RuntimeError):
    pass


def _empty_output(path: Path) -> None:
    if path.is_symlink() or (path.exists() and (not path.is_dir() or any(path.iterdir()))):
        raise ExportError(f"Export output must be absent or empty; stale output is never reused: {path}")


def _run(command: list[str], cwd: Path) -> dict:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    if result.returncode:
        # Exporters are offline validators; no credentials or runtime state copied.
        raise ExportError((result.stderr or result.stdout).strip()[-4000:])
    try:
        return json.loads(result.stdout)
    except ValueError:
        return {}


def export_sources(english_checkout: Path, translation_checkout: Path | None, english_output: Path, translation_output: Path, strict_translations: bool = False) -> dict:
    english_checkout = Path(english_checkout).resolve()
    english_output, translation_output = (Path(path).absolute() for path in (english_output, translation_output))
    if english_output == translation_output:
        raise ExportError("English and translation outputs must be separate")
    _empty_output(english_output)
    _empty_output(translation_output)
    english_output.parent.mkdir(parents=True, exist_ok=True)
    _run([sys.executable, "tools/archive.py", "export", "--output", str(english_output), "--base", "/"], english_checkout)
    manifest = json.loads((english_output / "manifest.json").read_text(encoding="utf-8"))
    report = {"source_revision": manifest["source_revision"], "english_status": "ready", "english_articles": manifest["counts"]["articles"], "translation_status": "unavailable", "translation_revision": None, "translated_articles": 0, "warnings": []}
    if translation_checkout is None:
        report["warnings"].append("No translation checkout supplied; current English publishes independently.")
        return report
    try:
        _run([sys.executable, "-m", "berean_translation", "export", "--source-checkout", str(english_checkout), "--output", str(translation_output), "--base", "/"], Path(translation_checkout).resolve())
        translated = json.loads((translation_output / "manifest.json").read_text(encoding="utf-8"))
        if translated["source_revision"] != report["source_revision"]:
            raise ExportError("Translation export was not scanned against the selected English revision")
        report.update(translation_status="ready", translation_revision=translated["translation_revision"], translated_articles=translated["article_count"], translation_omissions=translated.get("omitted", []))
    except (ExportError, OSError, ValueError, KeyError) as error:
        report["translation_status"] = "failed"
        report["warnings"].append(f"Translation export failed; English-only publication, no stale translations reused: {error}")
        # The supported exporter is atomic; quarantine any foreign/partial
        # output as defense in depth. Never leave a failed bundle at the path a
        # standalone generator could otherwise mistake for successful input.
        report["translation_output_usable"] = False
        if translation_output.exists() or translation_output.is_symlink():
            quarantine = translation_output.with_name("." + translation_output.name + "-rejected-" + uuid.uuid4().hex)
            translation_output.rename(quarantine)
            report["translation_quarantine"] = str(quarantine)
        if strict_translations:
            raise ExportError(report["warnings"][-1]) from error
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--english-checkout", required=True, type=Path)
    parser.add_argument("--translation-checkout", type=Path)
    parser.add_argument("--english-output", required=True, type=Path)
    parser.add_argument("--translation-output", required=True, type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--strict-translations", action="store_true")
    args = parser.parse_args()
    try:
        result = export_sources(args.english_checkout, args.translation_checkout, args.english_output, args.translation_output, args.strict_translations)
    except (ExportError, OSError) as error:
        print(f"Source export failed: {error}", file=sys.stderr)
        return 1
    output = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output, encoding="utf-8")
    print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
