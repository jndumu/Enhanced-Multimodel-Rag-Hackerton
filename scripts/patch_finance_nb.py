"""Patch the finance notebook to add vision chart cell and non-text demo queries."""
import json, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

with open("notebooks/02_finance_berkshire_10k.ipynb", encoding="utf-8") as f:
    nb = json.load(f)

# ── Vision / chart cell ────────────────────────────────────────────────────────
vis_md_src = """\
---
## Step 1b — Extracted Figures + Vision AI (Charts as Images)

### Charts count as images
Financial PDFs embed performance charts, graphs, and diagrams as raster images —
not text. The parser detected **1 chart** in the Berkshire annual report:
the 5-year **Stock Performance Graph** (p.58) comparing $100 invested in
Berkshire vs the S\\&P 500 vs the S\\&P P\\&C Insurance Index.

The vision model reads the chart and returns a structured caption —
demonstrating that the pipeline handles visual financial data, not just numbers.
"""

vis_code_src = """\
import base64, asyncio, httpx, io
import matplotlib.pyplot as plt
from PIL import Image as PILImage

figure_elements = [
    e for e in parse_result.elements
    if e.label.value == "figure"
    and e.raw_image_b64
    and e.bbox
    and (e.bbox.x1 - e.bbox.x0) >= 40
    and (e.bbox.y1 - e.bbox.y0) >= 40
]
print("Finance figures extracted: " + str(len(figure_elements)))

async def describe_chart(img_b64):
    try:
        async with httpx.AsyncClient(timeout=45) as c:
            r = await c.post(
                settings.mesh_api_base_url + "/chat/completions",
                headers={"Authorization": "Bearer " + settings.mesh_api_key},
                json={
                    "model": settings.vision_model,
                    "messages": [{"role": "user", "content": [
                        {"type": "text", "text": (
                            "This is a financial chart from a Berkshire Hathaway annual report. "
                            "Describe in 2-3 sentences: what is being compared, "
                            "the time period covered, and the key takeaway for investors."
                        )},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + img_b64}}
                    ]}],
                    "max_tokens": 100,
                }
            )
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"].strip()
            return "[status " + str(r.status_code) + "]"
    except Exception as e:
        return "[error: " + str(e)[:60] + "]"

for elem in figure_elements:
    caption = asyncio.get_event_loop().run_until_complete(describe_chart(elem.raw_image_b64))
    print("")
    print("Page " + str(elem.page) + " | Vision AI caption:")
    print(caption)
    print("")
    raw_bytes = base64.b64decode(elem.raw_image_b64)
    img = PILImage.open(io.BytesIO(raw_bytes))
    fig, ax = plt.subplots(figsize=(13, 5))
    ax.imshow(img)
    ax.set_title(
        "Berkshire 2023 AR — p." + str(elem.page) +
        "  |  modality=image  |  " + caption[:70] + "...",
        fontsize=10, fontweight="bold"
    )
    ax.axis("off")
    plt.tight_layout()
    out_name = "berkshire_chart_p" + str(elem.page) + ".png"
    plt.savefig(out_name, dpi=120, bbox_inches="tight")
    plt.show()
    print("Saved " + out_name)

if not figure_elements:
    print("No figure chunks found in this PDF")
"""

# ── Non-text demo queries ──────────────────────────────────────────────────────
nontext_md_src = """\
---
## Step 6b — Non-Text Modality Queries (Table + Image)

### Asking questions that surface TABLE and IMAGE chunks

Four targeted queries that bypass text chunks and retrieve financial tables
and the stock-performance chart:

| Query | Expected modality |
|-------|------------------|
| Operating earnings per share 2023 | **table** |
| GEICO underwriting 2022 vs 2023 | **table** |
| Largest equity investment | **table** |
| Berkshire vs S\\&P 500 over 5 years | **image** (chart) |

Each result shows the retrieved modality breakdown, groundedness score, and LLM answer.
"""

nontext_code_src = """\
import asyncio, time
from collections import Counter

from doc_intel_rag.retrieval.hybrid_searcher import HybridSearcher
from doc_intel_rag.retrieval.semantic_router import SemanticRouter
from doc_intel_rag.retrieval.reranker import get_reranker
from doc_intel_rag.retrieval.groundedness import score_groundedness
from doc_intel_rag.generation.generator import generate
from doc_intel_rag.ingestion.embedder import DocumentEmbedder
from doc_intel_rag.ingestion.vector_store import QdrantDocumentStore

embedder = DocumentEmbedder(settings)
store    = QdrantDocumentStore(settings)
searcher = HybridSearcher(store, embedder)
router   = SemanticRouter(settings)
reranker = get_reranker(settings)

non_text_queries = [
    ("table", "What were Berkshire Hathaway's total operating earnings and earnings per share in 2023?"),
    ("table", "What was GEICO's underwriting gain or loss in 2023 and how did it compare to 2022?"),
    ("table", "What is Berkshire's largest equity investment and its approximate market value at year-end 2023?"),
    ("image", "How has Berkshire's stock performed compared to the S&P 500 over the past 5 years?"),
]

for expected_modality, query in non_text_queries:
    print("=" * 70)
    print("QUERY  : " + query)
    print("EXPECT : " + expected_modality + " modality chunks")
    print()
    t0     = time.monotonic()
    intent = asyncio.get_event_loop().run_until_complete(router.classify(query))
    hits   = asyncio.get_event_loop().run_until_complete(searcher.search(query, top_k=10, intent=intent))
    ranked = asyncio.get_event_loop().run_until_complete(reranker.rerank(query, hits, top_n=5))
    q_emb  = asyncio.get_event_loop().run_until_complete(embedder.embed_query(query))
    ground = score_groundedness(q_emb, ranked)

    mod_counts = Counter(c.payload.get("modality", "?") for c in ranked)
    print("Retrieved modalities : " + str(dict(mod_counts)))
    print("Groundedness score   : " + str(round(ground, 4)))

    if ranked:
        top     = ranked[0]
        top_mod = top.payload.get("modality", "?")
        top_txt = (top.payload.get("text", "") or "")[:200]
        print("Top chunk modality   : " + top_mod)
        print("Top chunk preview    : " + top_txt)

    print("")
    answer = asyncio.get_event_loop().run_until_complete(
        generate(query, ranked, groundedness_score=ground, settings=settings)
    )
    print("ANSWER :")
    print((answer or "")[:600])
    print("Latency: " + str(round((time.monotonic() - t0) * 1000)) + "ms")
    print()
"""

# ── Insert into notebook ───────────────────────────────────────────────────────
def make_code(cid, src):
    return {"cell_type": "code", "id": cid, "metadata": {},
            "execution_count": None, "outputs": [], "source": [src]}

def make_md(cid, src):
    return {"cell_type": "markdown", "id": cid, "metadata": {}, "source": [src]}

cells = nb["cells"]

# Vision cells go after cell 4 (parse code), before cell 5 (Step 2 markdown)
cells = cells[:5] + [make_md("fin-vis-md", vis_md_src), make_code("fin-vis-code", vis_code_src)] + cells[5:]

# After that insertion Step 6 code (originally index 14) is now at 14+2=16
# Insert non-text query cells after it (index 17)
cells = cells[:17] + [make_md("fin-nt-md", nontext_md_src), make_code("fin-nt-code", nontext_code_src)] + cells[17:]

nb["cells"] = cells
print(f"Total cells: {len(cells)}")

with open("notebooks/02_finance_berkshire_10k.ipynb", "w", encoding="utf-8") as f:
    json.dump(nb, f, indent=1, ensure_ascii=False)
print("Saved.")
