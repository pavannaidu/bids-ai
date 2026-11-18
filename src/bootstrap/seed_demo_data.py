"""Write the sample bid documents into the bid documents volume (run by the seed_demo_data job).

Re-runnable: every file is overwritten in place and folders are created only if missing. The
reference data (item catalog, bid and purchase history) isn't seeded here: the app creates it
directly in its Lakebase database at startup (src/app/server/reference_seed.py).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _script_file() -> Path:
    # spark_python_task may run this file without __file__; fall back to argv[0].
    for candidate in (globals().get("__file__"), sys.argv[0] if sys.argv else ""):
        if isinstance(candidate, str) and candidate and candidate not in {"-c", "-"}:
            path = Path(candidate).expanduser()
            if path.is_absolute() or path.exists():
                return path.resolve()
    raise RuntimeError("Unable to determine this task's file path.")


# The generators live in the app (src/app/server/_shared_data), which deploys only src/app;
# the bundle syncs the whole repo, so this job imports them from there.
APP_SERVER = _script_file().parents[1] / "app" / "server"
if APP_SERVER.exists() and str(APP_SERVER) not in sys.path:
    sys.path.insert(0, str(APP_SERVER))

from _shared_data.sample_documents import SAMPLE_DOCUMENTS, document_manifest, render_document_bytes  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write the sample bid documents into the documents volume.")
    parser.add_argument("--volume-path", required=True, help="/Volumes/<catalog>/<schema>/<volume>")
    return parser.parse_args()


def main() -> None:
    root = Path(parse_args().volume_path)
    samples_dir = root / "sample_bid_documents"
    for folder in (samples_dir, root / "uploads", root / "generated_proposals"):
        folder.mkdir(parents=True, exist_ok=True)

    manifest = {"volume_path": str(root), "sample_documents": []}
    for document in SAMPLE_DOCUMENTS:
        content = render_document_bytes(document)
        (samples_dir / document.file_name).write_bytes(content)
        manifest["sample_documents"].append(document_manifest(document))
        print(f"Wrote {samples_dir / document.file_name} ({len(content)} bytes)")
    (samples_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps({"status": "ok", "sample_documents": len(SAMPLE_DOCUMENTS), "path": str(samples_dir)}))


if __name__ == "__main__":
    main()
