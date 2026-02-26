# mcp-opensearch

Read-only MCP server for exploring and searching [OpenSearch 2](https://opensearch.org/) clusters. Ideal for log analysis, index exploration, and query execution.

## Tools

| Tool | Description |
|---|---|
| `ping` | Check connectivity — returns cluster name and version |
| `cluster_health` | Cluster health status (green/yellow/red), node and shard counts |
| `list_indices` | List indices with health, doc count, and size. Optional pattern filter |
| `get_index_mapping` | Show field types and structure for an index |
| `search` | Execute queries using OpenSearch Query DSL (JSON) |
| `count` | Count documents matching an optional query |
| `list_aliases` | List all index aliases |
| `get_document` | Retrieve a specific document by ID |

## Installation — Claude Desktop Extension

1. Build the extension package:

```bash
npx @anthropic-ai/mcpb pack .
```

2. In Claude Desktop, go to **Settings → Extensions** and upload `mcpopensearch.mcpb`.

3. Configure via the UI:
   - **OpenSearch URL** — e.g. `http://your-opensearch:9200`
   - **Username** / **Password** — optional, for basic auth

## Installation — Claude Code

Add to your `.claude/settings.json`:

```json
{
  "mcpServers": {
    "opensearch": {
      "command": "uv",
      "args": ["--directory", "/path/to/mcpopensearch", "run", "server.py"],
      "env": {
        "OPENSEARCH_URL": "http://localhost:9200",
        "OPENSEARCH_USERNAME": "",
        "OPENSEARCH_PASSWORD": ""
      }
    }
  }
}
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `OPENSEARCH_URL` | `http://localhost:9200` | OpenSearch cluster URL |
| `OPENSEARCH_USERNAME` | *(none)* | Basic auth username |
| `OPENSEARCH_PASSWORD` | *(none)* | Basic auth password |

## Query Examples

Search for errors in the last hour:
```json
{
  "query": {
    "bool": {
      "must": [
        {"match": {"level": "ERROR"}},
        {"range": {"@timestamp": {"gte": "now-1h"}}}
      ]
    }
  },
  "sort": [{"@timestamp": "desc"}]
}
```

Count documents by status code:
```json
{
  "query": {"match_all": {}},
  "aggs": {"status_codes": {"terms": {"field": "response_code"}}}
}
```

## License

MIT
