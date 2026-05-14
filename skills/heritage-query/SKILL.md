# /heritage-query

Query the Heritage cultural knowledge base.

## Trigger phrases
- "what does the knowledge base say about X"
- "find in heritage knowledge"
- "query:"
- "tra cứu di sản"

## Behavior
1. Call `search_wiki` with the query
2. If a relevant page is found, call `read_wiki_page` to get full content
3. Summarize the answer with source citations (slug or source ID)
4. If nothing found, say so clearly and suggest related topics

## Notes
- Always cite the wiki slug when answering
- Use Vietnamese for heritage-related terminology
