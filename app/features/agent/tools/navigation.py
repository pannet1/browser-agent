from __future__ import annotations

from typing import Any

from app.core.logger import logging_func

logger = logging_func(__name__)

DEVTO_ALGOLIA_ENDPOINT = (
    "https://prsobfp46h-dsn.algolia.net/1/indexes/Article_production/query"
    "?x-algolia-agent=Algolia%20for%20JavaScript%20(4.23.3)%3B%20Browser%20(lite)"
    "&x-algolia-api-key=9aa7d31610cba78851c9b1f63776a9dd"
    "&x-algolia-application-id=PRSOBFP46H"
)


async def navigate(page: Any, url: str) -> dict[str, Any]:
    logger.info(f"navigate {url}")
    await page.goto(url, wait_until="domcontentloaded")
    return {"status": "ok", "url": url}


async def wait_for(page: Any, selector: str | None = None, ms: int | None = None) -> dict[str, Any]:
    if selector:
        logger.info(f"wait_for selector {selector}")
        await page.wait_for_selector(selector, timeout=5000)
    elif ms:
        logger.info(f"wait {ms}ms")
        await page.wait_for_timeout(ms)
    return {"status": "ok"}


async def recover_devto_search(page: Any) -> dict[str, Any]:
    """Recover dev.to results when its Algolia widget aborts before rendering."""
    try:
        request_info = await page.evaluate(
            """() => {
                const list = document.querySelector('#substories');
                if (!list) return 0;
                // An empty-state or loading node is still a child, but is not
                // a search result. Only skip recovery when an actual result
                // title/link has already been rendered.
                if (list.querySelector('.crayons-story__title, a[href*="/"]')) {
                    return {endpoint: '', query: '', count: list.querySelectorAll('.crayons-story__title').length};
                }
                const query = new URLSearchParams(location.search).get('q') || '';
                const resource = performance.getEntriesByType('resource')
                    .find(entry => entry.name.includes('algolia.net/1/indexes/') && entry.name.includes('/query?'));
                return {endpoint: resource?.name || '', query, count: 0};
            }"""
        )  # type: ignore[attr-defined]
        if not isinstance(request_info, dict):
            return {"status": "skipped", "count": 0}
        endpoint = request_info.get("endpoint") or DEVTO_ALGOLIA_ENDPOINT
        query = str(request_info.get("query") or "")
        if not query:
            logger.info("dev.to search recovery skipped: no query")
            return {"status": "skipped", "count": 0}
        response = await page.request.post(  # type: ignore[attr-defined]
            endpoint,
            data={"params": f"query={query}&hitsPerPage=20"},
        )
        if not response.ok:
            raise RuntimeError(f"Algolia returned HTTP {response.status}")
        data = await response.json()
        hits = data.get("hits", []) if isinstance(data, dict) else []
        count = await page.evaluate(
            """hits => {
                const list = document.querySelector('#substories');
                if (!list) return 0;
                list.replaceChildren(...hits.map(hit => {
                    const story = document.createElement('div');
                    story.className = 'crayons-story';
                    const link = document.createElement('a');
                    link.className = 'crayons-story__title';
                    link.href = hit.path || '#';
                    link.textContent = hit.title || 'Untitled article';
                    const meta = document.createElement('p');
                    meta.className = 'crayons-story__meta';
                    meta.textContent = hit.user?.name ? `by ${hit.user.name}` : '';
                    story.append(link, meta);
                    return story;
                }));
                return hits.length;
            }""",
            hits,
        )  # type: ignore[attr-defined]
        logger.info(f"dev.to search results recovered: {count}")
        return {"status": "ok", "count": count}
    except Exception as exc:
        logger.info(f"dev.to search recovery skipped: {exc}")
        return {"status": "skipped", "error": str(exc)}
