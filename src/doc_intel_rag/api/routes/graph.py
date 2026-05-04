"""Knowledge graph export endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from doc_intel_rag.api.dependencies import get_graph_store, verify_api_key
from doc_intel_rag.api.schemas import GraphResponse

router = APIRouter(tags=["graph"])


@router.get("/graph/{doc_id}", response_model=GraphResponse)
async def get_graph(
    doc_id: str,
    api_key: str = Depends(verify_api_key),
    graph_store: object = Depends(get_graph_store),
) -> GraphResponse:
    from doc_intel_rag.ingestion.graph_store import GraphStore
    assert isinstance(graph_store, GraphStore)

    data = graph_store.serialize(doc_id)
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No graph found for doc_id={doc_id}",
        )

    return GraphResponse(
        doc_id=doc_id,
        nodes=data["nodes"],
        edges=data["edges"],
        node_count=len(data["nodes"]),
        edge_count=len(data["edges"]),
    )
