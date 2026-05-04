"""Streamlit knowledge graph and chunk visualiser for doc-intel-rag."""

from __future__ import annotations

import os

import streamlit as st

st.set_page_config(page_title="doc-intel-rag Visualiser", layout="wide")
st.title("doc-intel-rag — Knowledge Graph Explorer")

API_URL = os.getenv("API_URL", "http://localhost:8000")

doc_id = st.text_input("Document ID (SHA-256)", placeholder="Enter doc_id here")
api_key = st.text_input("API Key (optional)", type="password")

if st.button("Load Graph") and doc_id:
    import httpx

    headers = {"X-API-Key": api_key} if api_key else {}
    with st.spinner("Fetching graph..."):
        try:
            resp = httpx.get(f"{API_URL}/graph/{doc_id}", headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                st.success(f"Loaded {data['node_count']} nodes, {data['edge_count']} edges")

                col1, col2 = st.columns(2)
                with col1:
                    st.subheader("Nodes")
                    st.dataframe(data["nodes"])
                with col2:
                    st.subheader("Edges")
                    st.dataframe(data["edges"])

                # Try to render with pyvis if available
                try:
                    from pyvis.network import Network  # type: ignore[import-untyped]

                    net = Network(height="600px", width="100%", directed=True)
                    for node in data["nodes"]:
                        net.add_node(node["id"], label=node.get("label", node["id"]), title=node.get("type", ""))
                    for edge in data["edges"]:
                        net.add_edge(edge["source"], edge["target"], title=edge.get("relation", ""))

                    html_path = "/tmp/graph.html"
                    net.save_graph(html_path)
                    with open(html_path) as f:
                        st.components.v1.html(f.read(), height=620)
                except ImportError:
                    st.info("Install `pyvis` for interactive graph rendering: `pip install pyvis`")
            else:
                st.error(f"Error {resp.status_code}: {resp.text}")
        except Exception as exc:
            st.error(f"Connection failed: {exc}")

st.divider()
st.subheader("Quick Search")

query = st.text_input("Search query")
if st.button("Search") and query:
    import httpx
    import json

    headers = {"X-API-Key": api_key} if api_key else {}
    with st.spinner("Searching..."):
        try:
            resp = httpx.post(
                f"{API_URL}/search",
                json={"query": query, "top_k": 10, "top_n": 5},
                headers=headers,
                timeout=30,
            )
            if resp.status_code == 200:
                results = resp.json()
                st.metric("Groundedness", f"{results['groundedness_score']:.3f}")
                st.metric("Fallback used", str(results["fallback_used"]))
                for chunk in results["chunks"]:
                    with st.expander(f"[{chunk['modality'].upper()}] {chunk['source_file']} p.{chunk['page']} — score {chunk['score']:.4f}"):
                        st.write(chunk["text"])
            else:
                st.error(f"Error {resp.status_code}: {resp.text}")
        except Exception as exc:
            st.error(f"Search failed: {exc}")
