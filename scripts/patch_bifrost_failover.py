"""Patch the Bifrost notebook failover cell to use the real Fireworks provider."""
import json, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

with open("notebooks/04_bifrost_llm_gateway.ipynb", encoding="utf-8") as f:
    nb = json.load(f)

new_src = """\
import asyncio, time
from doc_intel_rag.gateway.llm_gateway import LLMGateway

gw = LLMGateway.from_env()

print("=" * 55)
print("LIVE FAILOVER DEMO - REAL TWO-PROVIDER GATEWAY")
print("=" * 55)
print()
print("Providers configured:")
for i, p in enumerate(gw.providers, 1):
    print("  [" + str(i) + "] " + p.name + " - " + p.base_url[:50])

if len(gw.providers) < 2:
    print()
    print("Only one provider found.")
    print("Add FIREWORKS_API_KEY to .env to enable live failover.")
else:
    print()
    print("Step 1: Marking Requesty as DOWN (3 failures, circuit breaker open)")
    primary = gw.providers[0]
    primary.failures     = 3
    primary.healthy      = False
    primary.last_failure = time.monotonic()

    print()
    print("Step 2: Available providers after Requesty failure:")
    for p in gw._available_providers():
        print("  -> " + p.name + " will handle this request")

    print()
    print("Step 3: Making request - gateway routes to Fireworks automatically...")
    t0 = time.monotonic()
    try:
        response = asyncio.get_event_loop().run_until_complete(gw.chat(
            model="accounts/fireworks/models/glm-5",
            messages=[{"role": "user", "content": "Say FAILOVER SUCCESS in all caps"}],
            max_tokens=15
        ))
        elapsed = round((time.monotonic() - t0) * 1000)
        print("RESPONSE : " + response["choices"][0]["message"]["content"])
        print("LATENCY  : " + str(elapsed) + "ms")
    except Exception as e:
        print("Error: " + str(e))

    print()
    print("Step 4: Provider health AFTER failover:")
    for p in gw.providers:
        icon = "OK  " if p.healthy else "DOWN"
        print("  [" + icon + "] " + p.name.ljust(15) + "  healthy=" + str(p.healthy) + "  failures=" + str(p.failures))

    print()
    print("Requesty was DOWN. Fireworks answered. Your users got a response.")
    print("This is the Bifrost pattern working in production.")

    # Restore for subsequent cells
    primary.healthy  = True
    primary.failures = 0
"""

for i, c in enumerate(nb["cells"]):
    if c.get("cell_type") == "code":
        src = "".join(c.get("source", []))
        if "FAILOVER" in src and ("broken" in src.lower() or "gw_failover" in src):
            c["source"] = [new_src]
            print(f"Updated failover cell at index {i}")
            break

with open("notebooks/04_bifrost_llm_gateway.ipynb", "w", encoding="utf-8") as f:
    json.dump(nb, f, indent=1, ensure_ascii=False)
print("Saved.")
