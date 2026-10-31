"""End-to-end smoke test against a running server (./start.sh).

Usage (from the project root):
    .venv/bin/python backend/scripts/smoke_test.py --pdf path/to/contract.pdf \
        --question "Who are the parties to the agreement?"

Steps: health check, optional upload (waits for ingestion), then a question, a follow-up
that depends on it, and an off-topic question that must be refused.
"""

import argparse
import sys
import time
from pathlib import Path

import httpx

NO_ANSWER = "I can't find that in the uploaded documents."


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--pdf", type=Path)
    parser.add_argument("--question", default="Who are the parties named in the documents?")
    args = parser.parse_args()
    api = httpx.Client(base_url=f"{args.url}/api", timeout=900)

    health = api.get("/health").json()
    for name, comp in health["components"].items():
        print(f"[{'ok' if comp['ok'] else 'FAIL'}] {name}: {comp['detail']}")
    if not health["ok"]:
        print("System is not healthy; fix the failing components first.")
        return 1

    if args.pdf:
        with args.pdf.open("rb") as fh:
            r = api.post("/documents", files={"file": (args.pdf.name, fh, "application/pdf")})
        if r.status_code == 409:
            print(r.json()["detail"])
        else:
            r.raise_for_status()
            doc_id = r.json()["id"]
            print(f"Uploaded {args.pdf.name}; waiting for ingestion...")
            deadline = time.time() + 3600
            while time.time() < deadline:
                doc = next(d for d in api.get("/documents").json() if d["id"] == doc_id)
                print(f"  {doc['status']}: {doc.get('stage') or ''}")
                if doc["status"] in ("done", "failed"):
                    break
                time.sleep(10)
            if doc["status"] != "done":
                print(f"Ingestion did not finish: {doc.get('error')}")
                return 1
            print(f"  {doc['chunks']} chunks, {doc['entities']} entities")

    conversation = api.post("/conversations", json={"title": "Smoke test"}).json()
    cid = conversation["id"]

    def ask(question: str) -> dict:
        r = api.post(f"/conversations/{cid}/messages", json={"content": question})
        r.raise_for_status()
        msg = r.json()
        assert {"content", "sources", "graph"} <= msg.keys(), f"unexpected response: {msg}"
        print(f"\nQ: {question}\nA: {msg['content']}")
        print(f"   sources: {sorted({s['file_name'] for s in msg['sources']})}, "
              f"subgraph: {len(msg['graph']['nodes'])} nodes / {len(msg['graph']['links'])} links")
        return msg

    ask(args.question)
    ask("Summarise your previous answer in one sentence.")
    off_topic = ask("What is the capital of France?")
    if NO_ANSWER.lower() not in off_topic["content"].lower():
        print("\nWARNING: the off-topic question was not refused.")
        return 1

    stored = api.get(f"/conversations/{cid}").json()
    assert len(stored["messages"]) == 6, f"expected 6 stored messages, got {len(stored['messages'])}"
    print("\nSmoke test passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
