import httpx
from .config import settings

async def remediation_research(service: str, product: str, version: str):
    """Defensive research only. Never sends target addresses or performs target interaction."""
    if not settings.tavily_api_key: return []
    query = f"{service} {product} {version} security hardening vendor advisory remediation"
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post('https://api.tavily.com/search', json={
            "api_key": settings.tavily_api_key, "query": query,
            "topic": "general", "search_depth": "basic", "max_results": 4,
            "include_answer": False
        })
        r.raise_for_status()
        return [{"title": x.get('title',''), "url": x.get('url',''), "content": x.get('content','')[:500]} for x in r.json().get('results', [])]
