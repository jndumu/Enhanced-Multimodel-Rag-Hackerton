"""Rebuild the Bifrost / LLM Gateway tutorial notebook with deep explanations."""
import json, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

cells = []
def md(src): cells.append({"cell_type": "markdown", "id": f"md{len(cells)}", "metadata": {}, "source": [src]})
def code(src): cells.append({"cell_type": "code", "id": f"c{len(cells)}", "metadata": {}, "execution_count": None, "outputs": [], "source": [src]})

# ── COVER ─────────────────────────────────────────────────────────────────────
md("""\
<div align="center">

# The LLM Gateway — Bifrost Pattern
## A Complete Tutorial for Beginners

**What this notebook teaches you:**
- What an LLM Gateway is and why every production AI app needs one
- What "Bifrost" means and where the name comes from
- How provider failover works step by step
- How to read and understand the gateway code in this project
- How to add your own providers in minutes

**No prior knowledge of gateways required.**

</div>
""")

# ── CHAPTER 1 ─────────────────────────────────────────────────────────────────
md("""\
---
# Chapter 1 — What is an LLM Provider?

Before we talk about a gateway, we need to understand what we are routing.

When your application needs to:
- Generate an answer from an LLM
- Create an embedding vector
- Describe an image with a vision model

...it makes an **API call** to a cloud service called an **LLM Provider**.

Examples of LLM providers:
| Provider | What they offer | Cost |
|----------|----------------|------|
| OpenAI | GPT-4o, text-embedding-3 | $$ |
| Requesty | 500+ models via one API | $ |
| Fireworks AI | Fast inference, open models | $ |
| Novita AI | Broad model support | $ |
| Anthropic | Claude models | $$ |
| Cohere | Command R+, embeddings | $ |

Every provider has the **same OpenAI-compatible API format**:

```
POST https://api.provider.com/v1/chat/completions
Authorization: Bearer YOUR_API_KEY

{
  "model": "some-model-name",
  "messages": [{"role": "user", "content": "Hello"}]
}
```

This is important: because they all speak the same format, switching between them
is just a matter of changing the URL and API key — no code changes needed.
""")

code("""\
# Setup — run this first
import os, sys
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

import asyncio
os.environ["DOC_INTEL_SKIP_VALIDATION"] = "1"
os.environ["LOG_LEVEL"] = "WARNING"

from dotenv import load_dotenv
load_dotenv()

import httpx

print("Setup complete.")
print("Your API base URL:", os.environ.get("MESH_API_BASE_URL", "not set"))
print("Your API key prefix:", os.environ.get("MESH_API_KEY", "not set")[:20] + "...")
""")

# ── CHAPTER 2 ─────────────────────────────────────────────────────────────────
md("""\
---
# Chapter 2 — The Problem: What Happens When a Provider Goes Down?

Imagine your app is running in production at 2am. Thousands of users are querying it.

Suddenly, the LLM provider returns this:

```json
{"error": {"code": 429, "message": "Too Many Requests — rate limit exceeded"}}
```

Or this:

```json
{"error": {"code": 503, "message": "Service Unavailable"}}
```

Or worst of all — no response at all. Just a timeout after 30 seconds.

**If you have only one provider and it fails, your entire application breaks.**

Every user gets an error. Your app is down. You get paged at 2am.

The most common failure modes and how often they happen:

| Failure | Code | How often | Impact |
|---------|------|-----------|--------|
| Rate limit | 429 | Very common | All requests fail until limit resets |
| Provider outage | 503 | Rare (2-3x/year) | Total blackout until they fix it |
| Network timeout | — | Occasional | Requests hang, users wait forever |
| Model deprecated | 404 | Happens without warning | All requests for that model fail |
| Wrong API key | 401 | Human error | All requests fail |

The code cell below simulates what happens when you call a provider that is down.
""")

code("""\
# WHAT HAPPENS when you call a broken provider directly
# (no gateway, no fallback — just a raw httpx call)

import asyncio, httpx, time

async def call_broken_provider():
    print("Making direct API call to a broken provider...")
    print("(This will fail — watch what happens)")
    print()
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.post(
                "https://provider-that-is-down.example.com/v1/chat/completions",
                headers={"Authorization": "Bearer fake-key"},
                json={"model": "gpt-4o", "messages": [{"role": "user", "content": "Hello"}]}
            )
            print("Response:", r.status_code)
    except httpx.ConnectError as e:
        elapsed = round((time.monotonic() - t0) * 1000)
        print(f"CONNECT ERROR after {elapsed}ms: {type(e).__name__}")
        print()
        print("What your user sees: 500 Internal Server Error")
        print("What your logs show: ConnectError")
        print("What you have to do: get paged at 2am and manually switch providers")
        print()
        print("THIS is the problem that the LLM Gateway solves.")

asyncio.get_event_loop().run_until_complete(call_broken_provider())
""")

# ── CHAPTER 3 ─────────────────────────────────────────────────────────────────
md("""\
---
# Chapter 3 — The Solution: A Gateway (And Why It's Called Bifrost)

## The ATM Analogy

Think of LLM providers like ATMs.

You walk up to ATM #1 to withdraw cash. It says "Out of Service."
You don't stand there and cry. You walk 10 metres to ATM #2.

**A gateway does exactly this — automatically, in milliseconds, without you noticing.**

```
Your App
    |
    | "I need a chat completion"
    |
    ▼
┌─────────────────────────────────────────────────────┐
│                  LLM GATEWAY                        │
│                                                     │
│  Try provider 1 (Requesty)                          │
│    → Got 429 rate limit? Mark failure. Try next.    │
│                                                     │
│  Try provider 2 (Fireworks)                         │
│    → Got response! Return it to the caller.         │
│                                                     │
│  (Provider 1 and 2 both down? Try provider 3...)    │
└─────────────────────────────────────────────────────┘
    |          |           |
    ▼          ▼           ▼
Requesty   Fireworks    Novita
```

## Why "Bifrost"?

In Norse mythology, **Bifrost** is the rainbow bridge that connects Asgard
(the realm of the gods) to the other nine realms.

In software, the gateway is the bridge that connects your application (Asgard)
to the many LLM provider realms. It doesn't matter which realm you use —
the bridge gets you there.

The name was popularised by **Helicone** (an AI observability company) as a
design pattern for LLM routing. You will also see it called:
- **LLM Proxy** (LiteLLM uses this term)
- **AI Gateway** (PortKey, Kong use this)
- **Model Router** (Requesty itself is one)

They all mean the same thing: a layer that sits between your app and LLM providers,
handles retries, tracks health, and makes failures invisible to the caller.
""")

# ── CHAPTER 4 ─────────────────────────────────────────────────────────────────
md("""\
---
# Chapter 4 — How Health Tracking Works

The gateway needs to know which providers are currently healthy.
It tracks this with three simple fields per provider:

```python
@dataclass
class ProviderConfig:
    name: str           # "requesty", "fireworks", etc.
    base_url: str       # "https://router.requesty.ai/v1"
    api_key: str        # your API key

    healthy: bool = True    # is this provider currently usable?
    failures: int = 0       # how many times has it failed recently?
    last_failure: float = 0 # Unix timestamp of the last failure
```

**The failure → backoff → recovery cycle:**

```
Provider is healthy (failures=0)
        |
        | API call returns 429 / 503 / timeout
        |
        ▼
mark_failure() called
  → failures += 1
  → if failures >= 3: healthy = False
        |
        | (provider is now skipped for 60 seconds)
        |
        ▼
is_available() called 60 seconds later
  → time since last_failure > 60s → healthy = True, failures = 0
  → provider is back in rotation
```

This is called **exponential backoff with a circuit breaker pattern**.
- **Backoff**: wait before retrying a failed provider
- **Circuit breaker**: stop trying a provider entirely after repeated failures

The code cell below lets you play with this live.
""")

code("""\
# LIVE DEMO: Health tracking in action
# Watch a provider go from healthy -> unhealthy -> recovered

import time
from doc_intel_rag.gateway.llm_gateway import ProviderConfig

print("=" * 55)
print("HEALTH TRACKING DEMO")
print("=" * 55)

p = ProviderConfig(
    name="demo-provider",
    base_url="https://api.example.com",
    api_key="test-key"
)

print()
print("STEP 1: Provider starts healthy")
print(f"  healthy   = {p.healthy}")
print(f"  failures  = {p.failures}")
print(f"  available = {p.is_available()}")

print()
print("STEP 2: First failure (rate limit 429)")
p.mark_failure()
print(f"  healthy   = {p.healthy}")
print(f"  failures  = {p.failures}")
print(f"  available = {p.is_available()} ← still available (threshold is 3)")

print()
print("STEP 3: Second failure (timeout)")
p.mark_failure()
print(f"  healthy   = {p.healthy}")
print(f"  failures  = {p.failures}")
print(f"  available = {p.is_available()} ← still available")

print()
print("STEP 4: Third failure → circuit breaker trips")
p.mark_failure()
print(f"  healthy   = {p.healthy}  ← CIRCUIT BREAKER OPEN")
print(f"  failures  = {p.failures}")
print(f"  available = {p.is_available()} ← provider is now SKIPPED")

print()
print("STEP 5: 60 seconds pass (simulated)")
p.last_failure = time.monotonic() - 61  # pretend 61 seconds passed
print(f"  healthy   = {p.healthy}")
print(f"  available = {p.is_available()} ← auto-recovered! Back in rotation.")
print(f"  healthy   = {p.healthy}  ← mark_success() called internally")
print(f"  failures  = {p.failures}  ← reset to 0")

print()
print("STEP 6: Successful call after recovery")
p.mark_success()
print(f"  healthy   = {p.healthy}")
print(f"  failures  = {p.failures}")
print(f"  available = {p.is_available()}")
print()
print("The provider is fully operational again.")
print("Your app never saw any of this — it got answers the whole time.")
""")

# ── CHAPTER 5 ─────────────────────────────────────────────────────────────────
md("""\
---
# Chapter 5 — The Routing Algorithm: Step by Step

When your app asks the gateway for a chat completion, here is EXACTLY what happens
inside `LLMGateway.chat()`, line by line:

```python
async def chat(self, model, messages, ...):

    # Step 1: Get a list of providers that are currently healthy
    for provider in self._available_providers():

        try:
            # Step 2: Make the API call to this provider
            r = await client.post(
                f"{provider.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {provider.api_key}"},
                json={"model": model, "messages": messages}
            )

            # Step 3: Check for "soft" failures (provider is up but overloaded)
            if r.status_code in (429, 503, 502, 504):
                provider.mark_failure()   # record this failure
                continue                  # go to NEXT provider

            # Step 4: Success! Reset failure count and return the response
            provider.mark_success()
            return r.json()

        except (TimeoutException, ConnectError):
            # Step 5: "Hard" failure (can't even reach the provider)
            provider.mark_failure()
            continue   # go to NEXT provider

    # Step 6: All providers failed — raise an error (this is very rare)
    raise RuntimeError("All providers exhausted")
```

**Key insight:** Your calling code looks like this:

```python
response = await gateway.chat(model="qwen-turbo", messages=[...])
```

It has NO idea that provider 1 failed and provider 2 answered.
The gateway absorbed the failure completely.

The diagram below shows what happens during a failover:

```
Time →
  0ms   Gateway tries Provider 1 (Requesty)
  3000ms  Requesty times out → mark_failure()
  3001ms  Gateway tries Provider 2 (Fireworks)
  3450ms  Fireworks responds with 200 OK → mark_success()
  3451ms  Your app receives the response

Your app waited 3.45 seconds instead of 3 seconds.
Your app got an answer instead of an error.
```
""")

code("""\
# VISUALISE THE ROUTING ALGORITHM
# Show which providers get tried and in what order

from doc_intel_rag.gateway.llm_gateway import LLMGateway, ProviderConfig

gw = LLMGateway(providers=[
    ProviderConfig(name="requesty",  base_url="https://router.requesty.ai/v1",
                   api_key=os.environ.get("MESH_API_KEY", "")),
    ProviderConfig(name="fireworks", base_url="https://api.fireworks.ai/inference/v1",
                   api_key=os.environ.get("FIREWORKS_API_KEY", "no-key-set")),
    ProviderConfig(name="novita",    base_url="https://api.novita.ai/v3/openai",
                   api_key=os.environ.get("NOVITA_API_KEY", "no-key-set")),
])

print("SCENARIO 1: All providers healthy (normal operation)")
print("-" * 50)
available = gw._available_providers()
for rank, p in enumerate(available, start=1):
    icon = "→" if rank == 1 else " "
    print(f"  {icon} [{rank}] {p.name:<15} healthy={p.healthy}  will_try={'YES' if rank == 1 else 'only if #' + str(rank-1) + ' fails'}")
print()

print("SCENARIO 2: Requesty has 3 failures (circuit breaker open)")
print("-" * 50)
gw.providers[0].failures = 3
gw.providers[0].healthy = False
available = gw._available_providers()
for rank, p in enumerate(available, start=1):
    icon = "→" if rank == 1 else " "
    print(f"  {icon} [{rank}] {p.name:<15} healthy={p.healthy}")
skipped = [p for p in gw.providers if not p.is_available()]
for p in skipped:
    print(f"    [X] {p.name:<15} SKIPPED (circuit breaker open)")
print()

print("SCENARIO 3: Requesty AND Fireworks down")
print("-" * 50)
gw.providers[1].failures = 3
gw.providers[1].healthy = False
available = gw._available_providers()
for rank, p in enumerate(available, start=1):
    icon = "→" if rank == 1 else " "
    print(f"  {icon} [{rank}] {p.name:<15} (last provider standing)")
print()

# Reset for next cells
for p in gw.providers:
    p.healthy = True
    p.failures = 0

print("All providers reset to healthy.")
""")

# ── CHAPTER 6 ─────────────────────────────────────────────────────────────────
md("""\
---
# Chapter 6 — Live API Calls Through the Gateway

Now let's use the real gateway to make actual API calls.

**What you will see:**
1. A chat completion request routed through Requesty
2. An embedding request returning a 1536-dimensional vector
3. A check of provider health after the calls

**What to look for in the output:**
- The gateway logs which provider it chose (only WARNING+ shown, so you'll see the result directly)
- `healthy=True failures=0` means the call succeeded with no issues
- The embedding dimension is 1536 (from `openai/text-embedding-3-small`)
""")

code("""\
# LIVE GATEWAY CALLS — real API, real responses
import asyncio
from doc_intel_rag.gateway.llm_gateway import get_gateway

gw = get_gateway()

print("=" * 55)
print("LIVE CHAT COMPLETION via Gateway")
print("=" * 55)
print()
print("Sending: 'Explain what an LLM Gateway is in exactly 2 sentences.'")
print()

response = asyncio.get_event_loop().run_until_complete(gw.chat(
    model="alibaba/qwen-turbo",
    messages=[{
        "role": "user",
        "content": "Explain what an LLM Gateway is in exactly 2 sentences."
    }],
    max_tokens=80,
    temperature=0.1
))

print("ANSWER FROM LLM:")
print(response["choices"][0]["message"]["content"])
print()
print(f"Tokens used: {response.get('usage', {}).get('total_tokens', 'unknown')}")

print()
print("=" * 55)
print("LIVE EMBEDDING REQUEST via Gateway")
print("=" * 55)
print()

texts = [
    "LLM Gateway routes requests across multiple providers",
    "Bifrost is the bridge between your app and AI providers",
    "What is the weather today?"   # unrelated — similarity should be low
]

embeddings = asyncio.get_event_loop().run_until_complete(gw.embed(
    model="openai/text-embedding-3-small",
    texts=texts
))

print(f"Embedded {len(embeddings)} texts, each {len(embeddings[0])} dimensions")
print()

# Cosine similarity between embeddings
def cosine(a, b):
    dot = sum(x*y for x,y in zip(a,b))
    mag_a = sum(x**2 for x in a) ** 0.5
    mag_b = sum(x**2 for x in b) ** 0.5
    return dot / (mag_a * mag_b)

sim_01 = cosine(embeddings[0], embeddings[1])
sim_02 = cosine(embeddings[0], embeddings[2])

print(f'Similarity: "{texts[0][:40]}..."')
print(f'       vs: "{texts[1][:40]}..."')
print(f'       = {sim_01:.4f}  ← HIGH (both about LLM gateways)')
print()
print(f'Similarity: "{texts[0][:40]}..."')
print(f'       vs: "{texts[2]}"')
print(f'       = {sim_02:.4f}  ← LOW (unrelated topic)')

print()
print("=" * 55)
print("GATEWAY HEALTH CHECK")
print("=" * 55)
health = asyncio.get_event_loop().run_until_complete(gw.health())
for name, status in health.items():
    icon = "OK" if status["healthy"] else "DOWN"
    print(f"  [{icon}] {name:<15} healthy={status['healthy']}  failures={status['failures']}")
""")

# ── CHAPTER 7 ─────────────────────────────────────────────────────────────────
md("""\
---
# Chapter 7 — Failover Demo (The Most Important Part)

This is the whole point of the gateway. Watch what happens when provider 1 is broken:

**Setup:**
- Provider 1: a fake URL that will fail immediately
- Provider 2: the real Requesty API

**Expected behaviour:**
1. Gateway tries Provider 1 → ConnectError
2. Gateway records a failure on Provider 1
3. Gateway tries Provider 2 → Success
4. Your app receives the answer — **as if nothing went wrong**

**What to look for in the output:**
- Total time will be slightly longer than a normal call (because of the failed attempt)
- Provider 1 shows `failures > 0` in the health check
- Provider 2 shows `failures = 0` (it succeeded)
- The answer still arrives correctly
""")

code("""\
# FAILOVER DEMO — broken provider + real provider side by side
import asyncio, time
from doc_intel_rag.gateway.llm_gateway import LLMGateway, ProviderConfig

gw_failover = LLMGateway(
    providers=[
        ProviderConfig(
            name="broken-provider",
            base_url="https://this-url-does-not-exist.example.com/v1",
            api_key="fake-key"
        ),
        ProviderConfig(
            name="requesty-backup",
            base_url=os.environ.get("MESH_API_BASE_URL", "https://router.requesty.ai/v1"),
            api_key=os.environ.get("MESH_API_KEY", "")
        ),
    ],
    timeout=4.0
)

print("=" * 55)
print("FAILOVER DEMO")
print("=" * 55)
print()
print("Providers configured:")
for i, p in enumerate(gw_failover.providers, 1):
    print(f"  [{i}] {p.name} — {p.base_url[:45]}")

print()
print("Making request... (watch the timing)")
print()

t0 = time.monotonic()

try:
    response = asyncio.get_event_loop().run_until_complete(gw_failover.chat(
        model="alibaba/qwen-turbo",
        messages=[{"role": "user", "content": "Say FAILOVER SUCCESS"}],
        max_tokens=10
    ))
    elapsed = round((time.monotonic() - t0) * 1000)

    print(f"RESPONSE: {response['choices'][0]['message']['content']}")
    print(f"Time    : {elapsed}ms (includes failed attempt on provider 1)")
    print()

    print("HEALTH after failover:")
    for p in gw_failover.providers:
        icon = "OK" if p.healthy else "DOWN"
        bar  = "█" * p.failures
        print(f"  [{icon}] {p.name:<20} failures={p.failures} {bar}")
    print()
    print("WHAT HAPPENED:")
    print("  1. Gateway tried 'broken-provider'  → ConnectError → mark_failure()")
    print("  2. Gateway tried 'requesty-backup'  → 200 OK → mark_success()")
    print("  3. Your app got the answer — zero errors seen by the caller")

except RuntimeError as e:
    print(f"All providers failed: {e}")
""")

# ── CHAPTER 8 ─────────────────────────────────────────────────────────────────
md("""\
---
# Chapter 8 — Adding a New Provider (3 Lines)

One of the best things about this gateway design is how easy it is to add providers.

Because all providers speak the OpenAI-compatible format, you just need:
1. Their base URL
2. An API key

**In `.env`:**
```bash
# Current (single provider):
MESH_API_KEY=rqsty-sk-...
MESH_API_BASE_URL=https://router.requesty.ai/v1

# After adding Fireworks as a fallback:
LLM_GATEWAY_PROVIDERS=requesty|https://router.requesty.ai/v1|MESH_API_KEY,fireworks|https://api.fireworks.ai/inference/v1|FIREWORKS_API_KEY
FIREWORKS_API_KEY=your-fireworks-key
```

**No code changes.** The gateway reads `LLM_GATEWAY_PROVIDERS` at startup.

**Provider format:** `name|base_url|ENV_VAR_FOR_KEY`

Popular providers you can add today:
| Provider | Base URL | Get key at |
|----------|----------|-----------|
| Fireworks AI | `https://api.fireworks.ai/inference/v1` | fireworks.ai |
| Novita AI | `https://api.novita.ai/v3/openai` | novita.ai |
| Together AI | `https://api.together.xyz/v1` | together.ai |
| Groq | `https://api.groq.com/openai/v1` | groq.com |
| OpenRouter | `https://openrouter.ai/api/v1` | openrouter.ai |

All of these are free to start with generous quotas.
""")

code("""\
# SHOW HOW PROVIDERS ARE LOADED FROM ENV
import os
from doc_intel_rag.gateway.llm_gateway import LLMGateway

print("Reading LLM_GATEWAY_PROVIDERS from environment...")
print()

raw = os.getenv("LLM_GATEWAY_PROVIDERS", "")
if raw:
    print("LLM_GATEWAY_PROVIDERS =", raw)
    print()
    print("Parsed providers:")
    for spec in raw.split(","):
        parts = spec.strip().split("|")
        if len(parts) == 3:
            name, base_url, key_env = parts
            key = os.getenv(key_env, "")
            has_key = "YES" if key else "NO KEY SET"
            print(f"  {name:<15} {base_url:<50} key={has_key}")
else:
    print("LLM_GATEWAY_PROVIDERS not set — using MESH_API_KEY directly")
    print()
    print("To add Fireworks as fallback, add to .env:")
    print()
    print("  LLM_GATEWAY_PROVIDERS=requesty|https://router.requesty.ai/v1|MESH_API_KEY,\\")
    print("                         fireworks|https://api.fireworks.ai/inference/v1|FIREWORKS_API_KEY")

print()
gw = LLMGateway.from_env()
print("Gateway initialised with providers:", [p.name for p in gw.providers])
""")

# ── CHAPTER 9 ─────────────────────────────────────────────────────────────────
md("""\
---
# Chapter 9 — How the Gateway Fits Into doc-intel-rag

The gateway is used in three places in this project:

```
doc-intel-rag/
  src/
    doc_intel_rag/
      gateway/
        llm_gateway.py      ← THE GATEWAY (what you just learned)
      ingestion/
        embedder.py         ← calls gw.embed() for dense vectors
      generation/
        generator.py        ← calls gw.chat() for answer generation
      parsing/
        pipeline.py         ← calls vision model for figure classification
```

**Before the gateway (fragile):**
```python
# embedder.py (old approach)
async with httpx.AsyncClient() as c:
    r = await c.post("https://router.requesty.ai/v1/embeddings",
                     headers={"Authorization": f"Bearer {key}"}, json={...})
    # If Requesty is down → your ingest pipeline crashes
```

**After the gateway (resilient):**
```python
# embedder.py (gateway approach)
from doc_intel_rag.gateway import get_gateway
gw = get_gateway()
embeddings = await gw.embed(model="openai/text-embedding-3-small", texts=[...])
# If Requesty is down → gateway tries Fireworks automatically
```

**The gateway is the difference between:**
- "Sorry, our service is down"
- "Here is your answer" (routed silently through a backup provider)
""")

code("""\
# FINAL SUMMARY: print the actual gateway source code with annotations
import inspect
from doc_intel_rag.gateway.llm_gateway import LLMGateway, ProviderConfig

print("=" * 60)
print("COMPLETE LLMGateway.chat() SOURCE CODE — annotated")
print("=" * 60)
print()

src_lines = inspect.getsource(LLMGateway.chat).split("\\n")
annotations = {
    3:  "# ← iterate over healthy providers in priority order",
    5:  "# ← make the actual HTTP POST to this provider",
    9:  "# ← 429=rate limit, 503=down, 502/504=proxy errors",
    10: "# ← record failure, may trip circuit breaker",
    11: "# ← move to the NEXT provider",
    13: "# ← success: reset failure count",
    14: "# ← return the response to the caller",
    16: "# ← network-level failure (can't reach provider)",
    17: "# ← record failure",
    18: "# ← move to the NEXT provider",
    21: "# ← only reached if EVERY provider failed (very rare)",
}

for i, line in enumerate(src_lines):
    annotation = annotations.get(i, "")
    print(f"{i:3}: {line}  {annotation}")
""")

# ── SUMMARY ───────────────────────────────────────────────────────────────────
md("""\
---
# Summary — Everything You Learned

| Concept | One-line definition |
|---------|-------------------|
| **LLM Provider** | A cloud API that runs LLM models (OpenAI, Requesty, Fireworks, etc.) |
| **LLM Gateway** | A layer between your app and providers that handles routing and failover |
| **Bifrost pattern** | The design pattern — named after the Norse rainbow bridge |
| **Circuit breaker** | Stops trying a failed provider after 3 failures |
| **Backoff window** | Waits 60 seconds before retrying a broken provider |
| **Failover** | Automatically switching to the next provider when one fails |
| **Provider health** | Per-provider tracking of failures, timestamps, and availability |
| **Priority order** | Providers are tried left-to-right; cheapest/fastest goes first |

**The gateway in this project:** `src/doc_intel_rag/gateway/llm_gateway.py`

**To add a new provider:** one line in `.env`, no code changes.

**The key promise:** Your app users never see a provider failure.
The gateway absorbs it silently and routes to the next available provider.
""")

# ── Write ──────────────────────────────────────────────────────────────────────
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
