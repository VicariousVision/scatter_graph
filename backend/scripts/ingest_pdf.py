"""Ingest one PDF from the command line, using the same pipeline as the API.

Usage (from the project root):
    .venv/bin/python backend/scripts/ingest_pdf.py path/to/contract.pdf
"""

import argparse
import asyncio
import hashlib
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.clients import get_driver  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.indexes import ensure_indexes  # noqa: E402
from app.ingest import IngestionService, Job, ingest_pdf  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pdf", type=Path)
    args = parser.parse_args()

    path: Path = args.pdf.resolve()
    if not path.is_file():
        print(f"File not found: {path}")
        return 1

    settings, driver = get_settings(), get_driver()
    ensure_indexes(driver, settings)
    data = path.read_bytes()
    file_hash = hashlib.sha256(data).hexdigest()
    duplicate = IngestionService(settings, driver).find_duplicate(file_hash)
    if duplicate:
        print(f"Already ingested as '{duplicate}'.")
        return 0

    job = Job(id=uuid.uuid4().hex, file_name=path.name, file_path=path, file_hash=file_hash, file_size=len(data))
    counts = asyncio.run(
        ingest_pdf(path, job.metadata(), settings, driver, on_stage=lambda stage: print(f"... {stage}", flush=True))
    )
    print(f"Done: {counts['chunks']} chunks, {counts['entities']} entities linked to {path.name}")
    driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
