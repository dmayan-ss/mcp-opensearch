"""MCP server for OpenSearch 2 — read-only log exploration and search."""

import json
import os
from typing import Optional

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("opensearch")

OPENSEARCH_URL = os.environ.get("OPENSEARCH_URL", "http://localhost:9200")
OPENSEARCH_USERNAME = os.environ.get("OPENSEARCH_USERNAME")
OPENSEARCH_PASSWORD = os.environ.get("OPENSEARCH_PASSWORD")

MAX_SEARCH_SIZE = 100


async def _os_request(
    method: str,
    path: str,
    params: Optional[dict] = None,
    json_body: Optional[dict] = None,
) -> httpx.Response:
    """Make an HTTP request to OpenSearch, adding basic auth if configured."""
    url = f"{OPENSEARCH_URL.rstrip('/')}{path}"
    auth = None
    if OPENSEARCH_USERNAME and OPENSEARCH_PASSWORD:
        auth = (OPENSEARCH_USERNAME, OPENSEARCH_PASSWORD)

    async with httpx.AsyncClient() as client:
        resp = await client.request(
            method,
            url,
            params=params,
            json=json_body,
            auth=auth,
            timeout=30.0,
        )
        return resp


def _format_hits(data: dict) -> str:
    """Format OpenSearch search response hits into readable text."""
    hits = data.get("hits", {})
    total = hits.get("total", {})
    total_value = total.get("value", 0) if isinstance(total, dict) else total
    total_relation = total.get("relation", "eq") if isinstance(total, dict) else "eq"

    hit_list = hits.get("hits", [])
    if not hit_list:
        return f"No results (total: {total_value})."

    parts: list[str] = []
    total_str = f"{total_value}" if total_relation == "eq" else f"{total_value}+"
    parts.append(f"Total hits: {total_str}  |  Showing: {len(hit_list)}")
    parts.append("")

    for i, hit in enumerate(hit_list, 1):
        source = hit.get("_source", {})
        index = hit.get("_index", "")
        doc_id = hit.get("_id", "")
        score = hit.get("_score")

        header = f"--- [{i}] {index} / {doc_id}"
        if score is not None:
            header += f"  (score: {score})"
        parts.append(header)

        for key, value in source.items():
            val_str = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
            if len(val_str) > 200:
                val_str = val_str[:200] + "..."
            parts.append(f"  {key}: {val_str}")
        parts.append("")

    took = data.get("took", "?")
    parts.append(f"Query took: {took}ms")
    return "\n".join(parts).rstrip()


def _format_mapping(mapping: dict) -> str:
    """Format OpenSearch index mapping into a readable tree."""
    parts: list[str] = []

    for index_name, index_data in mapping.items():
        parts.append(f"Index: {index_name}")
        properties = index_data.get("mappings", {}).get("properties", {})
        if not properties:
            parts.append("  (no properties)")
            continue
        _walk_properties(properties, parts, indent=1)
        parts.append("")

    return "\n".join(parts).rstrip() if parts else "No mapping data."


def _walk_properties(props: dict, parts: list[str], indent: int = 0) -> None:
    """Recursively walk mapping properties and append formatted lines."""
    prefix = "  " * indent
    for field, info in sorted(props.items()):
        field_type = info.get("type", "object")
        sub_props = info.get("properties")
        if sub_props:
            parts.append(f"{prefix}{field} (object)")
            _walk_properties(sub_props, parts, indent + 1)
        else:
            parts.append(f"{prefix}{field}: {field_type}")


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def ping() -> str:
    """Check connectivity to the OpenSearch cluster. Returns cluster name and version."""
    resp = await _os_request("GET", "/")
    resp.raise_for_status()
    data = resp.json()
    name = data.get("cluster_name", "unknown")
    version = data.get("version", {}).get("number", "unknown")
    distribution = data.get("version", {}).get("distribution", "opensearch")
    return f"OK — {distribution} {version}, cluster: {name} at {OPENSEARCH_URL}"


@mcp.tool()
async def cluster_health() -> str:
    """Get the cluster health status including node count, shard info, and overall status (green/yellow/red)."""
    resp = await _os_request("GET", "/_cluster/health")
    resp.raise_for_status()
    data = resp.json()

    lines = [
        f"Cluster: {data.get('cluster_name', '?')}",
        f"Status: {data.get('status', '?')}",
        f"Nodes: {data.get('number_of_nodes', '?')} (data: {data.get('number_of_data_nodes', '?')})",
        f"Shards: {data.get('active_shards', '?')} active, "
        f"{data.get('relocating_shards', 0)} relocating, "
        f"{data.get('initializing_shards', 0)} initializing, "
        f"{data.get('unassigned_shards', 0)} unassigned",
        f"Active shards %: {data.get('active_primary_shards', '?')} primary / "
        f"{data.get('active_shards_percent_as_number', '?')}%",
    ]
    return "\n".join(lines)


@mcp.tool()
async def list_indices(pattern: Optional[str] = None) -> str:
    """List indices in the cluster with their health, doc count, and size.

    Args:
        pattern: Optional index name pattern to filter (e.g. 'filebeat-*', 'logs-*').
    """
    path = "/_cat/indices"
    if pattern:
        path += f"/{pattern}"
    resp = await _os_request("GET", path, params={"format": "json", "s": "index", "h": "health,status,index,docs.count,store.size"})
    resp.raise_for_status()
    indices = resp.json()

    if not indices:
        return "No indices found."

    col_widths = {"health": 6, "status": 6, "index": 5, "docs.count": 9, "store.size": 10}
    for idx in indices:
        for key in col_widths:
            col_widths[key] = max(col_widths[key], len(str(idx.get(key, ""))))

    header_map = {"health": "HEALTH", "status": "STATUS", "index": "INDEX", "docs.count": "DOCS", "store.size": "SIZE"}
    headers = ["health", "status", "index", "docs.count", "store.size"]
    fmt = "  ".join(f"{{:<{col_widths[h]}}}" for h in headers)

    parts: list[str] = []
    parts.append(fmt.format(*[header_map[h] for h in headers]))
    parts.append(fmt.format(*["-" * col_widths[h] for h in headers]))
    for idx in indices:
        parts.append(fmt.format(*[str(idx.get(h, "")) for h in headers]))

    parts.append(f"\nTotal: {len(indices)} indices")
    return "\n".join(parts)


@mcp.tool()
async def get_index_mapping(index: str) -> str:
    """Get the field mapping (schema) for an index, showing all fields and their types.

    Args:
        index: Name of the index (e.g. 'filebeat-2024.01.15' or 'logs-*').
    """
    resp = await _os_request("GET", f"/{index}/_mapping")
    resp.raise_for_status()
    data = resp.json()
    return _format_mapping(data)


@mcp.tool()
async def search(index: str, query_body: str, size: int = 20) -> str:
    """Execute a read-only search query against an index using OpenSearch Query DSL.

    The query_body must be a valid JSON string representing the query portion.
    Example: {"query": {"match": {"message": "error"}}, "sort": [{"@timestamp": "desc"}]}

    Args:
        index: Index name or pattern to search (e.g. 'filebeat-*').
        query_body: JSON string with the OpenSearch Query DSL body.
        size: Maximum number of results to return (default 20, max 100).
    """
    try:
        body = json.loads(query_body)
    except json.JSONDecodeError as e:
        return f"Error: invalid JSON in query_body — {e}"

    if not isinstance(body, dict):
        return "Error: query_body must be a JSON object."

    size = min(max(1, size), MAX_SEARCH_SIZE)
    body["size"] = size

    resp = await _os_request("POST", f"/{index}/_search", json_body=body)
    resp.raise_for_status()
    data = resp.json()
    return _format_hits(data)


@mcp.tool()
async def count(index: str, query_body: Optional[str] = None) -> str:
    """Count documents in an index, optionally filtered by a query.

    Args:
        index: Index name or pattern (e.g. 'logs-*').
        query_body: Optional JSON string with a query filter (e.g. '{"query": {"match": {"level": "ERROR"}}}').
    """
    body = None
    if query_body:
        try:
            body = json.loads(query_body)
        except json.JSONDecodeError as e:
            return f"Error: invalid JSON in query_body — {e}"
        if not isinstance(body, dict):
            return "Error: query_body must be a JSON object."

    resp = await _os_request("POST", f"/{index}/_count", json_body=body)
    resp.raise_for_status()
    data = resp.json()
    total = data.get("count", 0)
    return f"Count: {total} documents in '{index}'"


@mcp.tool()
async def list_aliases() -> str:
    """List all index aliases in the cluster, showing which indices they point to."""
    resp = await _os_request("GET", "/_cat/aliases", params={"format": "json", "s": "alias"})
    resp.raise_for_status()
    aliases = resp.json()

    if not aliases:
        return "No aliases found."

    col_widths = {"alias": 5, "index": 5, "is_write_index": 5}
    for a in aliases:
        for key in col_widths:
            col_widths[key] = max(col_widths[key], len(str(a.get(key, ""))))

    headers = ["alias", "index", "is_write_index"]
    header_map = {"alias": "ALIAS", "index": "INDEX", "is_write_index": "WRITE"}
    fmt = "  ".join(f"{{:<{col_widths[h]}}}" for h in headers)

    parts: list[str] = []
    parts.append(fmt.format(*[header_map[h] for h in headers]))
    parts.append(fmt.format(*["-" * col_widths[h] for h in headers]))
    for a in aliases:
        parts.append(fmt.format(*[str(a.get(h, "")) for h in headers]))

    return "\n".join(parts)


@mcp.tool()
async def get_document(index: str, doc_id: str) -> str:
    """Retrieve a specific document by its ID.

    Args:
        index: Name of the index containing the document.
        doc_id: The document ID.
    """
    resp = await _os_request("GET", f"/{index}/_doc/{doc_id}")
    if resp.status_code == 404:
        return f"Document '{doc_id}' not found in index '{index}'."
    resp.raise_for_status()
    data = resp.json()

    found = data.get("found", False)
    if not found:
        return f"Document '{doc_id}' not found in index '{index}'."

    source = data.get("_source", {})
    parts: list[str] = [
        f"Index: {data.get('_index', '')}",
        f"ID: {data.get('_id', '')}",
        f"Version: {data.get('_version', '?')}",
        "",
    ]
    for key, value in source.items():
        val_str = json.dumps(value, ensure_ascii=False, indent=2) if isinstance(value, (dict, list)) else str(value)
        parts.append(f"{key}: {val_str}")

    return "\n".join(parts)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
