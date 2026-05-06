#!/usr/bin/env python3
"""
Inject all non-empty .env variables into GitHub Actions Secrets.

Usage:
    python scripts/inject_github_secrets.py \
        --repo jndumu/Enhanced-Multimodel-Rag-Hackerton \
        --token ghp_your_pat_here \
        --env-file .env

The script uses the GitHub REST API (PUT /repos/{owner}/{repo}/actions/secrets/{name}).
Secrets are encrypted client-side with the repo's public key before upload — the
raw value is never transmitted in plaintext.

Requirements:
    pip install PyNaCl requests
"""

from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path

import requests


# ── GitHub Secrets API ────────────────────────────────────────────────────────

def get_public_key(repo: str, token: str) -> tuple[str, str]:
    """Fetch the repo's Actions public key for secret encryption."""
    r = requests.get(
        f"https://api.github.com/repos/{repo}/actions/secrets/public-key",
        headers={"Authorization": f"token {token}", "Accept": "application/vnd.github+json"},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    return data["key_id"], data["key"]


def encrypt_secret(public_key_b64: str, secret_value: str) -> str:
    """Encrypt secret_value using the repo's NaCl public key (libsodium sealed box)."""
    from nacl import encoding, public  # type: ignore[import-untyped]

    key_bytes   = base64.b64decode(public_key_b64)
    pk          = public.PublicKey(key_bytes)
    sealed_box  = public.SealedBox(pk)
    encrypted   = sealed_box.encrypt(secret_value.encode("utf-8"))
    return base64.b64encode(encrypted).decode("utf-8")


def put_secret(repo: str, token: str, name: str, encrypted: str, key_id: str) -> int:
    """Create or update a single GitHub Actions secret."""
    r = requests.put(
        f"https://api.github.com/repos/{repo}/actions/secrets/{name}",
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
        json={"encrypted_value": encrypted, "key_id": key_id},
        timeout=15,
    )
    return r.status_code  # 201 = created, 204 = updated


# ── .env parser ───────────────────────────────────────────────────────────────

def parse_env_file(path: Path) -> dict[str, str]:
    """Parse a .env file, skipping comments and empty values."""
    env: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key   = key.strip()
        value = value.strip()
        # Strip inline comments (e.g.  KEY=value  # comment)
        if " #" in value:
            value = value[: value.index(" #")].strip()
        if value:  # skip empty values
            env[key] = value
    return env


# ── Skip list — values that should NOT be pushed as secrets ──────────────────

_SKIP_KEYS = {
    # Non-sensitive runtime config — better set as plain env vars in ECS task def
    "LOG_LEVEL", "LOG_JSON", "OTEL_SERVICE_NAME",
    "QDRANT_COLLECTION", "REDIS_EMBEDDING_TTL", "REDIS_QUERY_TTL",
    "MAX_CHUNK_TOKENS", "CHUNK_OVERLAP_TOKENS", "INGEST_BATCH_SIZE",
    "RATE_LIMIT_PER_MINUTE", "STREAMING_ENABLED", "FALLBACK_ENABLED",
    "GROUNDEDNESS_THRESHOLD", "TAVILY_MAX_RESULTS",
    "SAFETY_PII_ENABLED", "SAFETY_INJECTION_ENABLED",
    "SAFETY_OUTPUT_FAITHFULNESS", "SAFETY_TOXICITY_ENABLED", "SAFETY_BLOCK_ON_PII",
    "ENRICHMENT_ENABLED", "GLMOCR_BACKEND", "GLMOCR_TIMEOUT",
    "RERANKER_BACKEND", "COHERE_RERANK_MODEL", "JINA_RERANK_MODEL",
    "OPENAI_RERANK_MODEL", "MESH_LLM_MODEL", "MESH_EMBEDDING_MODEL",
    "MESH_EMBEDDING_DIM", "NEO4J_USER", "API_KEYS", "CORS_ORIGINS",
}


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo",     required=True,       help="owner/repo  e.g. jndumu/Enhanced-Multimodel-Rag-Hackerton")
    parser.add_argument("--token",    required=True,       help="GitHub PAT with repo+secrets write access")
    parser.add_argument("--env-file", default=".env",      help="Path to .env file (default: .env)")
    parser.add_argument("--dry-run",  action="store_true", help="Print what would be pushed without actually pushing")
    args = parser.parse_args()

    env_path = Path(args.env_file)
    if not env_path.exists():
        sys.exit(f"ERROR: {env_path} not found")

    env = parse_env_file(env_path)
    to_push = {k: v for k, v in env.items() if k not in _SKIP_KEYS}

    print(f"\n{'DRY RUN — ' if args.dry_run else ''}Injecting {len(to_push)} secrets into {args.repo}\n")
    print(f"{'Secret name':<35} {'Status'}")
    print("-" * 50)

    if args.dry_run:
        for name, value in to_push.items():
            masked = value[:4] + "***" if len(value) > 4 else "***"
            print(f"  {name:<33} would push ({masked})")
        print(f"\n{len(to_push)} secrets would be pushed (dry run — nothing sent)")
        return

    try:
        key_id, public_key = get_public_key(args.repo, args.token)
    except requests.HTTPError as exc:
        sys.exit(f"ERROR: Could not fetch public key — {exc}")

    ok = skipped = failed = 0
    for name, value in sorted(to_push.items()):
        try:
            encrypted = encrypt_secret(public_key, value)
            status    = put_secret(args.repo, args.token, name, encrypted, key_id)
            label     = "created" if status == 201 else "updated"
            print(f"  {name:<33} ✓ {label}")
            ok += 1
        except Exception as exc:
            print(f"  {name:<33} ✗ {exc}")
            failed += 1

    print(f"\n{'=' * 50}")
    print(f"  ✓ {ok} pushed    ✗ {failed} failed")
    print(f"\nVerify at: https://github.com/{args.repo}/settings/secrets/actions")


if __name__ == "__main__":
    main()
