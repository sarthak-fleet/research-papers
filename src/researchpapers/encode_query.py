"""One-shot query encoder for semantic search.

Loads MiniLM, encodes a single string, prints JSON to stdout, exits — so the
API process never keeps the model resident (saves ~400 MB in lean mode).
"""

from __future__ import annotations

import json
import sys

from researchpapers.embed import MODEL_NAME


def encode_text(text: str) -> list[float]:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(MODEL_NAME)
    return model.encode([text], normalize_embeddings=True)[0].tolist()


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: papers encode-query <text>")
    print(json.dumps(encode_text(sys.argv[1])))


if __name__ == "__main__":
    main()
