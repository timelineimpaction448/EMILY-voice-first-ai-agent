from core.llm.helpers import llm_complete_with_search
from core.llm.factory import get_llm_provider


def _provider_search(query: str) -> str:
    provider = get_llm_provider()
    if provider.supports_search():
        return llm_complete_with_search(query)
    raise RuntimeError(f"Provider {provider.name} has no search grounding")


def _ddg_search(query: str, max_results: int = 6) -> list[dict]:
    from ddgs import DDGS

    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=max_results):
            results.append({
                "title": r.get("title", ""),
                "snippet": r.get("body", ""),
                "url": r.get("href", ""),
            })
    return results


def _format_ddg(query: str, results: list[dict]) -> str:
    if not results:
        return f"No results found for: {query}"

    lines = [f"Search results for: {query}\n"]
    for i, r in enumerate(results, 1):
        if r.get("title"):
            lines.append(f"{i}. {r['title']}")
        if r.get("snippet"):
            lines.append(f"   {r['snippet']}")
        if r.get("url"):
            lines.append(f"   {r['url']}")
        lines.append("")
    return "\n".join(lines).strip()


def _compare(items: list[str], aspect: str) -> str:
    query = (
        f"Compare {', '.join(items)} in terms of {aspect}. "
        "Give specific facts and data."
    )
    try:
        return _provider_search(query)
    except Exception as e:
        print(f"[WebSearch] Provider search failed: {e} — falling back to DDG")

    all_results: dict[str, list] = {}
    for item in items:
        try:
            all_results[item] = _ddg_search(f"{item} {aspect}", max_results=3)
        except Exception:
            all_results[item] = []

    lines = [f"Comparison — {aspect.upper()}", "─" * 40]
    for item in items:
        lines.append(f"\n▸ {item}")
        for r in all_results.get(item, [])[:2]:
            if r.get("snippet"):
                lines.append(f"  • {r['snippet']}")
    return "\n".join(lines)


def web_search(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters or {}
    query = params.get("query", "").strip()
    mode = params.get("mode", "search").lower().strip()
    items = params.get("items", [])
    aspect = params.get("aspect", "general").strip() or "general"

    if not query and not items:
        return "Please provide a search query, sir."

    if items and mode != "compare":
        mode = "compare"

    if player:
        player.write_log(f"[Search] {query or ', '.join(items)}")

    print(f"[WebSearch] Query: {query!r}  Mode: {mode}")

    try:
        if mode == "compare" and items:
            print(f"[WebSearch] Comparing: {items}")
            result = _compare(items, aspect)
            print("[WebSearch] Compare done.")
            return result

        results: list[dict] = []
        print("[WebSearch] Trying DDG...")
        try:
            results = _ddg_search(query)
            if results:
                print(f"[WebSearch] DDG: {len(results)} result(s).")
                return _format_ddg(query, results)
        except Exception as e:
            print(f"[WebSearch] DDG failed ({e}) — trying provider search...")

        try:
            result = _provider_search(query)
            print("[WebSearch] Provider search OK.")
            return result
        except Exception as e:
            print(f"[WebSearch] Provider search failed ({e})")
            if results:
                return _format_ddg(query, results)
            raise

    except Exception as e:
        print(f"[WebSearch] All backends failed: {e}")
        return f"Search failed, sir: {e}"
