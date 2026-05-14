# /heritage-search

Semantic search over Heritage cultural documents.

## Trigger phrases
- "search heritage"
- "tìm kiếm di sản"
- "find documents about"
- "semantic search:"

## Behavior
1. Call `search_wiki` with the user query
2. Return a list of matching wiki pages (title, slug, summary)
3. Offer to read any of the returned pages in detail

## Notes
- Returns summaries only; use /heritage-query for full content
