"""Build the Bifrost / LLM Gateway learning notebook."""
import json, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

cells = []
def md(src): cells.append({"cell_type": "markdown", "id": f"md{len(cells)}", "metadata": {}, "source": [src]})
def code(src): cells.append({"cell_type": "code", "id": f"c{len(cells)}", "metadata": {}, "execution_count": None, "outputs": [], "source": [src]})

md("""\
<div align="center">

# Understanding the LLM Gateway (Bifrost Pattern)
### From Single Provider → Production-Grade Failover Router

</div>

This notebook teaches the **Bifrost pattern** from scratch — what the problem is,
why a single API call is fragile, and how a gateway layer solves it.
By the end you will understand every line of `src/doc_intel_rag/gateway/llm_gateway.py`.
""")

# ── Part 1: The Problem ───────────────────────────────────────────────────────
md("""\
---
## Part 1 — The Problem: Why a Single LLM Provider is Fragile

Every production RAG system calls an LLM provider for:
- Text generation (chat completions)
- Embeddings (vector search)
- Vision / multimodal (figure captions)

If you call one provider directly and it goes down, **your entire application stops.**

Common failure modes:

| Failure | HTTP code | Frequency |
|---------|-----------|-----------|
| Rate limit hit | 429 | Very common under load |
| Provider outage | 503 / 502 | Rare but devastating |
| Cold start timeout | timeout | Common for free tiers |
| Model deprecated | 404 | Happens with no warning |

**Bifrost** is the pattern that solves this: route requests through a gateway that
knows about multiple providers and retries automatically when one fails.

The name comes from Norse mythology — Bifrost is the rainbow bridge connecting
the realms. The gateway is the bridge connecting your app to the LLM ecosystem.
""")

code("""\
# Let's first demonstrate the fragility of a direct single-provider call
import asyncio, os, sys
from pathlib import Path

_here = Path(os.getcwd())
_project_root = _here.parent if _here.name == "notebooks" else _here
os.chdir(str(_project_root))
sys.path.insert(0, str(_project_root / "src"))

try:
    import nest_asyncio
    nest_asyncio.apply()
except ImportError:
    pass

from dotenv import load_dotenv
load_dotenv()
import httpx

# Simulate what happens with a direct call to a broken provider
async def direct_call_broken():
    print("=== Direct single-provider call (broken endpoint) ===")
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.post(
                "https://this-provider-is-down.ai/v1/chat/completions",
                headers={"Authorization": "Bearer fake-key"},
                json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]}
            )
            print("Response:", r.status_code)
    except Exception as e:
        print("FAILED: " + type(e).__name__ + ": " + str(e)[:80])
        print()
        print("With a single provider: your app crashes. User gets a 500 error.")
        print("With a gateway: the next provider is tried automatically.")

asyncio.get_event_loop().run_until_complete(direct_call_broken())
""")

# ── Part 2: The Bifrost Pattern ───────────────────────────────────────────────
md("""\
---
## Part 2 — The Bifrost Pattern: How It Works

The gateway sits between your application and all LLM providers.

```
Your App
    │
    ▼
┌─────────────────────────────────────────┐
│           LLM Gateway (Bifrost)         │
│                                         │
│  Priority queue of providers:           │
│  [1] Requesty  ← try first              │
│  [2] Fireworks ← fallback if 1 fails    │
│  [3] Novita    ← fallback if 2 fails    │
│                                         │
│  Per-provider health tracking:          │
│  - failures counter                     │
│  - last_failure timestamp               │
│  - backoff window (60 seconds)          │
└─────────────────────────────────────────┘
    │          │          │
    ▼          ▼          ▼
Requesty  Fireworks   Novita
```

**The routing algorithm:**
1. Ask: which providers are currently healthy?
2. Try the first healthy provider
3. If it returns 429/503/timeout → mark failure, try the next
4. After 3 failures on one provider → mark it unhealthy for 60 seconds
5. After 60 seconds → automatically re-enable it (exponential backoff)
6. If ALL providers fail → raise an error (this is extremely rare)
""")

code("""\
# Read and understand the ProviderConfig class
import inspect
from doc_intel_rag.gateway.llm_gateway import ProviderConfig, LLMGateway

print("=== ProviderConfig: tracks health per provider ===")
print()

# Create a provider and demonstrate health tracking
p = ProviderConfig(name="test-provider", base_url="https://api.example.com", api_key="test-key")
print("Initial state:")
print("  healthy    :", p.healthy)
print("  failures   :", p.failures)
print("  available  :", p.is_available())
print()

# Simulate failures
p.mark_failure()
p.mark_failure()
print("After 2 failures:")
print("  healthy  :", p.healthy)
print("  failures :", p.failures)
print("  available:", p.is_available(), " (still available — threshold is 3)")
print()

p.mark_failure()
print("After 3 failures (threshold reached):")
print("  healthy  :", p.healthy)
print("  failures :", p.failures)
print("  available:", p.is_available(), " (provider is now in backoff!)")
print()

p.mark_success()
print("After mark_success():")
print("  healthy  :", p.healthy)
print("  failures :", p.failures)
print("  available:", p.is_available(), " (provider re-enabled)")
""")

# ── Part 3: Provider routing in action ────────────────────────────────────────
md("""\
---
## Part 3 — Provider Routing in Action

The gateway maintains an ordered list of providers. `_available_providers()`
returns only the healthy ones in priority order.

This is how the gateway decides WHERE to send each request.
""")

code("""\
from doc_intel_rag.gateway.llm_gateway import LLMGateway, ProviderConfig
import time

# Build a gateway with 3 providers manually (without env vars)
gw = LLMGateway(providers=[
    ProviderConfig(name="requesty",  base_url="https://router.requesty.ai/v1",       api_key=os.environ.get("MESH_API_KEY", "")),
    ProviderConfig(name="fireworks", base_url="https://api.fireworks.ai/inference/v1", api_key=os.environ.get("FIREWORKS_API_KEY", "no-key")),
    ProviderConfig(name="novita",    base_url="https://api.novita.ai/v3/openai",       api_key=os.environ.get("NOVITA_API_KEY", "no-key")),
])

print("=== All providers (healthy) ===")
for p in gw._available_providers():
    print("  " + p.name + " — " + p.base_url)

print()
print("=== Simulate Requesty going down ===")
gw.providers[0].mark_failure()
gw.providers[0].mark_failure()
gw.providers[0].mark_failure()  # 3rd failure -> unhealthy

print("Available providers after Requesty failure:")
for p in gw._available_providers():
    print("  " + p.name + "  [healthy=" + str(p.healthy) + "]")

print()
print("=== After 60-second backoff window (simulated) ===")
gw.providers[0].last_failure = time.monotonic() - 65  # artificially age the failure
print("Available providers after backoff expires:")
for p in gw._available_providers():
    print("  " + p.name + "  [healthy=" + str(p.healthy) + "]")
""")

# ── Part 4: Live gateway call ─────────────────────────────────────────────────
md("""\
---
## Part 4 — Live Gateway Call with Health Monitoring

Now use the real gateway to make actual API calls and observe the health tracking.
""")

code("""\
from doc_intel_rag.gateway.llm_gateway import get_gateway
import asyncio

gw = get_gateway()

print("=== Gateway health BEFORE any calls ===")
health = asyncio.get_event_loop().run_until_complete(gw.health())
for name, s in health.items():
    icon = "✅" if s["healthy"] else "❌"
    print(f"  {icon} {name:<15} healthy={s['healthy']}  failures={s['failures']}")

print()
print("=== Making a chat completion via gateway ===")
r = asyncio.get_event_loop().run_until_complete(gw.chat(
    model="alibaba/qwen-turbo",
    messages=[{"role": "user", "content": "What is a Bifrost pattern in software? Answer in 2 sentences."}],
    max_tokens=80
))
print("Answer: " + r["choices"][0]["message"]["content"])
print("Provider used: " + r.get("model", "unknown"))

print()
print("=== Making an embedding call via gateway ===")
embs = asyncio.get_event_loop().run_until_complete(gw.embed(
    model="openai/text-embedding-3-small",
    texts=["Bifrost gateway pattern", "LLM provider failover"]
))
print("Embedding 1 dim : " + str(len(embs[0])))
print("Embedding 2 dim : " + str(len(embs[1])))
print("Cosine similarity (same topic?): " + str(round(
    sum(a*b for a,b in zip(embs[0], embs[1])) /
    (sum(x**2 for x in embs[0])**0.5 * sum(x**2 for x in embs[1])**0.5), 4
)))

print()
print("=== Gateway health AFTER calls ===")
health = asyncio.get_event_loop().run_until_complete(gw.health())
for name, s in health.items():
    icon = "✅" if s["healthy"] else "❌"
    print(f"  {icon} {name:<15} healthy={s['healthy']}  failures={s['failures']}")
""")

# ── Part 5: Failover walkthrough ──────────────────────────────────────────────
md("""\
---
## Part 5 — Step-by-Step Failover Walkthrough

This is the most important part. Here we trace exactly what the gateway does
when a provider fails mid-request.

```python
# Inside LLMGateway.chat():
for provider in self._available_providers():      # try each provider in order
    try:
        r = await client.post(...)                # make the API call

        if r.status_code in (429, 503, 502, 504): # provider error?
            provider.mark_failure()               # record the failure
            continue                              # try the NEXT provider

        provider.mark_success()                   # success — reset failure count
        return r.json()                           # return the response

    except (TimeoutException, ConnectError):      # network error?
        provider.mark_failure()                   # record the failure
        continue                                  # try the NEXT provider

raise RuntimeError("all providers exhausted")    # only if ALL fail (rare)
```

The key insight: **the caller never knows a failure happened.**
The gateway absorbed it silently and retried.
""")

code("""\
import asyncio, time
from doc_intel_rag.gateway.llm_gateway import LLMGateway, ProviderConfig

# Build a gateway where provider 1 is a broken URL but provider 2 is real
gw_demo = LLMGateway(
    providers=[
        ProviderConfig(
            name="broken-provider",
            base_url="https://this-will-fail.example.com/v1",
            api_key="fake-key"
        ),
        ProviderConfig(
            name="requesty-real",
            base_url=os.environ.get("MESH_API_BASE_URL", "https://router.requesty.ai/v1"),
            api_key=os.environ.get("MESH_API_KEY", "")
        ),
    ],
    timeout=5.0  # short timeout so the broken provider fails fast
)

print("=== Failover demo: broken provider 1, real provider 2 ===")
print()
print("Providers in order:", [p.name for p in gw_demo.providers])
print()

t0 = time.monotonic()
try:
    r = asyncio.get_event_loop().run_until_complete(gw_demo.chat(
        model="alibaba/qwen-turbo",
        messages=[{"role": "user", "content": "Say FAILOVER SUCCESS"}],
        max_tokens=10
    ))
    elapsed = round((time.monotonic() - t0) * 1000)
    print("Response: " + r["choices"][0]["message"]["content"])
    print("Total time (including failover): " + str(elapsed) + "ms")
    print()
    print("Provider health after failover:")
    for p in gw_demo.providers:
        icon = "✅" if p.healthy else "❌"
        print(f"  {icon} {p.name:<20} failures={p.failures}")
    print()
    print("The broken provider accumulated failures.")
    print("The real provider answered. The caller got a response — zero downtime.")
except Exception as e:
    print("Both providers failed: " + str(e))
""")

# ── Part 6: Integration with doc-intel-rag ────────────────────────────────────
md("""\
---
## Part 6 — How the Gateway Integrates with doc-intel-rag

The gateway is a **drop-in replacement** for direct httpx calls.
Any module that was calling Requesty directly now calls the gateway instead.

**Before (fragile):**
```python
async with httpx.AsyncClient() as c:
    r = await c.post("https://router.requesty.ai/v1/chat/completions",
                     headers={"Authorization": f"Bearer {key}"}, json={...})
```

**After (resilient):**
```python
from doc_intel_rag.gateway import get_gateway
gw = get_gateway()
r = await gw.chat(model="alibaba/qwen-turbo", messages=[...])
```

The gateway handles the URL, auth header, provider selection, retries, and health
tracking. The caller just asks for a chat completion.

### Adding a new provider in 3 lines

```bash
# In .env:
LLM_GATEWAY_PROVIDERS=requesty|https://router.requesty.ai/v1|MESH_API_KEY,\
                       fireworks|https://api.fireworks.ai/inference/v1|FIREWORKS_API_KEY,\
                       openai|https://api.openai.com/v1|OPENAI_API_KEY
```

No code changes. The gateway reads the env var at startup and adds the provider
to the rotation automatically.

### Production checklist for the gateway

| Concern | How gateway handles it |
|---------|----------------------|
| Rate limits (429) | Mark failure, retry next provider |
| Provider outage (503) | Mark failure, retry next provider |
| Network timeout | Mark failure, retry next provider |
| All providers down | Raise RuntimeError — your circuit breaker catches it |
| Provider recovers | Auto re-enabled after 60-second backoff window |
| Cost control | Priority order = cheapest first |
| Latency | Fastest provider first, failover only on error |
""")

code("""\
# Final summary: show the actual gateway code
from doc_intel_rag.gateway.llm_gateway import LLMGateway
import inspect

print("=== LLM Gateway — complete chat() method ===")
print()
src = inspect.getsource(LLMGateway.chat)
# Print with line numbers
for i, line in enumerate(src.split(chr(10)), start=1):
    print(f"{i:3}: {line}")
""")

md("""\
---
## Summary

| Concept | What it means |
|---------|--------------|
| **Bifrost** | Gateway pattern — your app talks to one interface, the gateway routes to many providers |
| **ProviderConfig** | Tracks health (failures, last_failure, healthy flag) per provider |
| **Priority order** | Providers tried left-to-right; cheapest/fastest first |
| **mark_failure()** | Increments failure counter; marks unhealthy after threshold |
| **mark_success()** | Resets failure counter; re-enables provider |
| **Backoff window** | 60 seconds after being marked unhealthy before retry |
| **_available_providers()** | Filters to only healthy providers in priority order |
| **Failover** | If provider N fails, gateway tries N+1 — caller never sees the failure |

The gateway implementation in this project is in:
`src/doc_intel_rag/gateway/llm_gateway.py`

It is ~200 lines and handles everything above. Production systems like LiteLLM,
PortKey, and the original Bifrost (Helicone) follow exactly this pattern at scale.
""")

nb = {
    "nbformat": 4, "nbformat_minor": 5,
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3.12.0"},
    },
    "cells": cells,
}

with open("notebooks/04_bifrost_llm_gateway.ipynb", "w", encoding="utf-8") as f:
    json.dump(nb, f, indent=1, ensure_ascii=False)

print(f"Written {len(cells)} cells to notebooks/04_bifrost_llm_gateway.ipynb")
