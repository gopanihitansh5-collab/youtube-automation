"""Web search tool using Gemini search-grounded models.

Searches the web for REAL-TIME LIVE information — only the most recent news,
trends, and events across USA, Australia, UK, India, and other regions.
"""
import os
import json
import re
import datetime

GEMINI_MODELS = [
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
]

REGIONS = {
    "us": "United States",
    "au": "Australia",
    "uk": "United Kingdom",
    "in": "India",
    "ca": "Canada",
    "de": "Germany",
    "fr": "France",
    "jp": "Japan",
    "sg": "Singapore",
    "nz": "New Zealand",
    "ae": "UAE / Dubai",
    "br": "Brazil",
}

PRIORITY_REGIONS = ["us", "au", "uk", "in", "ca", "sg"]

_LIVE_INSTRUCTION = (
    "CRITICAL: You MUST use search-grounding to fetch LIVE, REAL-TIME data. "
    "Do NOT rely on your training data. Only return information published within "
    "the LAST 7 DAYS. If you cannot find recent results, say so clearly. "
    "Every result must include evidence of recency (date, URL with timestamp)."
)


def _extract_json(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    raw = text[start:end + 1]
    raw = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _call_gemini(prompt, temperature=0.2, max_tokens=4096, timeout=90):
    """Internal: call Gemini with search grounding for LIVE data."""
    import requests
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return {"status": "error", "error": "GEMINI_API_KEY not set"}

    for model in GEMINI_MODELS[:3]:
        try:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": key},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "temperature": temperature,
                        "maxOutputTokens": max_tokens,
                    },
                    "tools": [{"googleSearchRetrieval": {}}],
                },
                timeout=timeout,
            )
            r.raise_for_status()
            body = r.json()
            text = body["candidates"][0]["content"]["parts"][0]["text"]
            grounding = body.get("candidates", [{}])[0].get("groundingMetadata", {})
            chunks = grounding.get("groundingChunks", [])
            sources = []
            for ch in chunks:
                web = ch.get("web", {})
                if web.get("uri"):
                    sources.append({"title": web.get("title", ""), "url": web.get("uri", "")})
            data = _extract_json(text)
            return {
                "status": "ok",
                "model": model,
                "data": data or {},
                "raw_text": text[:1000],
                "sources": sources,
            }
        except Exception as e:
            print(f"  Gemini {model} failed: {e}", flush=True)
    return {"status": "error", "error": "all Gemini models failed"}


def search_web(query, max_results=5):
    """LIVE web search. Only returns results from the last 7 days."""
    prompt = (
        f"{_LIVE_INSTRUCTION}\n\n"
        f"Search the web LIVE for this query:\n"
        f"Query: {query}\n\n"
        f"Only return results PUBLISHED IN THE LAST 7 DAYS. "
        f"Include publication dates and source URLs.\n\n"
        f"Return ONLY valid JSON:\n"
        f"{{\n"
        f"  \"query\": \"{query}\",\n"
        f"  \"search_date\": \"{datetime.date.today().isoformat()}\",\n"
        f"  \"is_live\": true,\n"
        f"  \"results\": [\n"
        f"    {{\"title\": \"...\", \"url\": \"...\", \"date\": \"...\", \"snippet\": \"...\"}}\n"
        f"  ],\n"
        f"  \"summary\": \"What's happening RIGHT NOW\"\n"
        f"}}\n\n"
        f"Fresh data only. No markdown. Only JSON."
    )
    result = _call_gemini(prompt, temperature=0.15, max_tokens=4096, timeout=90)
    if result["status"] == "ok":
        data = result["data"]
        if not data:
            data = {"query": query, "results": [], "summary": result.get("raw_text", "")[:200], "is_live": False}
        data["_sources"] = result.get("sources", [])[:max_results]
        data["status"] = "ok"
        data["model"] = result.get("model", "")
        return data
    return {"status": "error", "error": result.get("error", "unknown"), "query": query}


def search_web_by_region(query, region_code="us"):
    """LIVE regional search. Only results from the last 7 days in that country."""
    region_name = REGIONS.get(region_code, region_code.upper())
    prompt = (
        f"{_LIVE_INSTRUCTION}\n\n"
        f"Search the web LIVE for what is TRENDING RIGHT NOW in {region_name}:\n\n"
        f"Query: {query}\n\n"
        f"Only results from the LAST 7 DAYS. Must be specific to {region_name}. "
        f"Include publication dates.\n\n"
        f"Return ONLY valid JSON:\n"
        f"{{\n"
        f"  \"region\": \"{region_name}\",\n"
        f"  \"region_code\": \"{region_code}\",\n"
        f"  \"query\": \"{query}\",\n"
        f"  \"search_date\": \"{datetime.date.today().isoformat()}\",\n"
        f"  \"is_live\": true,\n"
        f"  \"trending_topics\": [\n"
        f"    {{\"topic\": \"...\", \"why_trending\": \"...\", \"date\": \"...\", \"source_url\": \"...\"}}\n"
        f"  ],\n"
        f"  \"summary\": \"What's happening RIGHT NOW in {region_name}\"\n"
        f"}}\n\n"
        f"Fresh data only. No markdown. Only JSON."
    )
    result = _call_gemini(prompt, temperature=0.2, max_tokens=4096, timeout=90)
    if result["status"] == "ok":
        data = result["data"]
        if not data:
            data = {"region": region_name, "region_code": region_code, "trending_topics": [],
                    "summary": result.get("raw_text", "")[:200], "is_live": False}
        data["_sources"] = result.get("sources", [])
        data["status"] = "ok"
        data["model"] = result.get("model", "")
        return data
    return {"status": "error", "error": result.get("error", "unknown"),
            "region": region_name, "region_code": region_code}


def get_multi_region_trends(categories=None, region_codes=None):
    """LIVE multi-region trends. Only what's happening RIGHT NOW in USA, AUS, UK, India, etc."""
    if categories is None:
        categories = ["technology", "business", "science", "health", "finance"]
    if region_codes is None:
        region_codes = PRIORITY_REGIONS

    regions_list = [{"code": c, "name": REGIONS.get(c, c.upper())} for c in region_codes]
    cats_str = ", ".join(categories)
    regions_str = ", ".join(f"{r['name']} ({r['code']})" for r in regions_list)

    prompt = (
        f"{_LIVE_INSTRUCTION}\n\n"
        f"Today is {datetime.date.today().isoformat()}.\n\n"
        f"Search the web LIVE for what is TRENDING RIGHT NOW in these countries:\n"
        f"{regions_str}\n\n"
        f"Categories: {cats_str}\n\n"
        f"For INDIA specifically, also search: politics, stock market, ISRO, "
        f"Bollywood, cricket, tech startups, and any BREAKING national news.\n\n"
        f"Only results from the LAST 7 DAYS. For EACH country find TOP 2-3 "
        f"trending topics that happened THIS WEEK.\n\n"
        f"Return ONLY valid JSON:\n"
        f"{{\n"
        f"  \"date\": \"{datetime.date.today().isoformat()}\",\n"
        f"  \"is_live\": true,\n"
        f"  \"regions\": [\n"
        f"    {{\n"
        f"      \"region_code\": \"us\",\n"
        f"      \"region_name\": \"United States\",\n"
        f"      \"trending_topics\": [{{\"topic\": \"...\", \"category\": \"...\", \"why_trending_now\": \"...\", \"date\": \"...\"}}],\n"
        f"      \"mood\": \"optimistic/tense/curious\"\n"
        f"    }}\n"
        f"  ],\n"
        f"  \"global_pulse\": \"2-3 sentence live snapshot of global sentiment\",\n"
        f"  \"best_video_topic\": {{\"topic\": \"best long-form topic RIGHT NOW\", \"region\": \"us\", \"reason\": \"...\"}}\n"
        f"}}\n\n"
        f"Fresh live data only. No markdown. Pure JSON."
    )

    result = _call_gemini(prompt, temperature=0.2, max_tokens=8192, timeout=120)
    if result["status"] == "ok":
        data = result["data"]
        if not data:
            data = {"date": str(datetime.date.today()), "regions": [],
                    "best_video_topic": {"topic": result.get("raw_text", "")[:100]}, "is_live": False}
        data["_sources"] = result.get("sources", [])
        data["status"] = "ok"
        data["model"] = result.get("model", "")
        return data
    return {"status": "error", "error": result.get("error", "unknown")}


def get_trending_news(category="technology", region_code="us"):
    """LIVE trending news in a specific category + country. Last 7 days only."""
    region_name = REGIONS.get(region_code, region_code.upper())
    query = f"BREAKING {category} news in {region_name} this week {datetime.date.today().strftime('%B %Y')}"
    return search_web_by_region(query, region_code)


def get_youtube_trends(region_code="us"):
    """LIVE YouTube trending educational content. Last 7 days only."""
    region_name = REGIONS.get(region_code, region_code.upper())
    query = f"viral trending educational YouTube videos in {region_name} this week 2026"
    return search_web_by_region(query, region_code)


def get_india_major_events():
    """LIVE — major events happening in India RIGHT NOW across all domains."""
    prompt = (
        f"{_LIVE_INSTRUCTION}\n\n"
        f"Today is {datetime.date.today().isoformat()}.\n\n"
        f"Search the web LIVE for MAJOR EVENTS AND BREAKING NEWS in India right now. "
        f"Only events from the LAST 7 DAYS. Cover:\n"
        f"- Indian politics (parliament, elections, policy changes, bills)\n"
        f"- Indian economy (stock market, GDP, RBI, startups, unicorns)\n"
        f"- Indian tech (IT sector, AI, digital India, startup funding)\n"
        f"- Indian science & space (ISRO launches, discoveries)\n"
        f"- Indian business (markets, trade, manufacturing, fintech)\n"
        f"- Indian cinema (Bollywood, OTT releases, controversies)\n"
        f"- Indian sports (cricket, Olympics, emerging sports)\n"
        f"- Indian education & social issues\n"
        f"- Major infrastructure projects\n"
        f"- Any BREAKING national news\n\n"
        f"Return ONLY valid JSON:\n"
        f"{{\n"
        f"  \"date\": \"{datetime.date.today().isoformat()}\",\n"
        f"  \"region\": \"India\",\n"
        f"  \"is_live\": true,\n"
        f"  \"major_events\": [\n"
        f"    {{\n"
        f"      \"domain\": \"politics/economy/tech/cinema/sports/science/business\",\n"
        f"      \"headline\": \"...\",\n"
        f"      \"date\": \"...\",\n"
        f"      \"why_major\": \"...why this is significant RIGHT NOW\",\n"
        f"      \"video_angle\": \"...educational YouTube video angle\",\n"
        f"      \"trending_score\": 0-10\n"
        f"    }}\n"
        f"  ],\n"
        f"  \"top_3_trending\": [\"...\", \"...\", \"...\"],\n"
        f"  \"youtube_worthy\": {{\"topic\": \"...best educational video idea from India right now\", \"reason\": \"...\", \"hook\": \"...\"}}\n"
        f"}}\n\n"
        f"Fresh live data only. No markdown. Pure JSON."
    )

    result = _call_gemini(prompt, temperature=0.2, max_tokens=8192, timeout=120)
    if result["status"] == "ok":
        data = result["data"]
        if not data:
            data = {"region": "India", "major_events": [], "top_3_trending": [],
                    "youtube_worthy": {"topic": result.get("raw_text", "")[:200]}, "is_live": False}
        data["_sources"] = result.get("sources", [])
        data["status"] = "ok"
        data["model"] = result.get("model", "")
        return data
    return {"status": "error", "error": result.get("error", "unknown")}


def get_daily_briefing(region_codes=None):
    """LIVE daily briefing across countries INCLUDING India major events. Last 7 days only."""
    if region_codes is None:
        region_codes = PRIORITY_REGIONS

    regions_list = [REGIONS.get(c, c.upper()) for c in region_codes]
    regions_str = ", ".join(regions_list)

    prompt = (
        f"{_LIVE_INSTRUCTION}\n\n"
        f"Today is {datetime.date.today().isoformat()}.\n\n"
        f"Search the web LIVE for BREAKING news this week across:\n"
        f"{regions_str}\n\n"
        f"Categories: technology AI | science discoveries | global economy | "
        f"health wellness | business startups | climate environment\n\n"
        f"For INDIA specifically: politics, stock market, ISRO, Bollywood, "
        f"cricket, tech startups, and any BREAKING national news.\n\n"
        f"Only results from the LAST 7 DAYS. Must include dates.\n\n"
        f"Return ONLY valid JSON:\n"
        f"{{\n"
        f"  \"date\": \"{datetime.date.today().isoformat()}\",\n"
        f"  \"is_live\": true,\n"
        f"  \"regions\": [\n"
        f"    {{\n"
        f"      \"region_code\": \"us\",\n"
        f"      \"region_name\": \"United States\",\n"
        f"      \"briefings\": [{{\"category\": \"technology\", \"headlines\": [\"...\"], \"trending_score\": 0-10}}],\n"
        f"      \"top_trending\": \"...\",\n"
        f"      \"video_ideas\": [\"...\"]\n"
        f"    }}\n"
        f"  ],\n"
        f"  \"cross_region_trends\": \"topics trending in multiple countries THIS WEEK\",\n"
        f"  \"recommended_video_topic\": {{\"topic\": \"...\", \"region\": \"...\", \"reason\": \"...\", \"hook\": \"...\"}}\n"
        f"}}\n\n"
        f"Fresh live data with dates. No markdown. Pure JSON."
    )

    result = _call_gemini(prompt, temperature=0.2, max_tokens=8192, timeout=120)
    if result["status"] == "ok":
        data = result["data"]
        if not data:
            data = {"date": str(datetime.date.today()), "regions": [],
                    "recommended_video_topic": {"topic": result.get("raw_text", "")[:200]}, "is_live": False}
        data["_sources"] = result.get("sources", [])
        data["status"] = "ok"
        data["model"] = result.get("model", "")
        return data
    return {"status": "error", "error": result.get("error", "unknown")}


def get_top_regions():
    return list(REGIONS.items())


def get_priority_regions():
    return PRIORITY_REGIONS[:]
