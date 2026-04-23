@app.post("/api/feeds")
async def add_feed(
    request: Request,
    background_tasks: BackgroundTasks,
    db: sqlite3.Connection = Depends(get_db),
):
    form = await request.form()
    url = form.get("url")

    if not url:
        raise HTTPException(400, "Нет URL")

    from urllib.parse import urlparse
    parsed_url = urlparse(url)
    if not parsed_url.scheme or not parsed_url.netloc:
        raise HTTPException(400, "Неверный URL")
    if parsed_url.scheme not in ("http", "https"):
        raise HTTPException(400, "Поддерживаются только HTTP и HTTPS")

    if not url.endswith(".xml") and not url.endswith("/rss") and "feed" not in url:
        try:
            headers = {"User-Agent": "Feedpipe/1.0"}
            async with httpx.AsyncClient(headers=headers) as client:
                resp = await client.get(url, timeout=5.0, follow_redirects=True)
                import re
                match = re.search(
                    r'<link[^>]+type="application/(?:rss|atom)\+xml"[^>]+href="([^"]+)"',
                    resp.text, re.IGNORECASE,
                )
                if match:
                    found_rss = match.group(1)
                    if found_rss.startswith("/"):
                        from urllib.parse import urljoin
                        found_rss = urljoin(url, found_rss)
                    url = found_rss
        except Exception:
            pass

    try:
        import feedparser
        headers = {"User-Agent": "Feedpipe/1.0"}
        async with httpx.AsyncClient(headers=headers) as client:
            resp = await client.get(url, timeout=5.0, follow_redirects=True)
            parsed = feedparser.parse(resp.text)
            title = parsed.feed.get("title", url)
    except:
        title = url

    try:
        db.execute("INSERT INTO feeds (url, title) VALUES (?, ?)", (url, title))
        db.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Уже подписан")

    background_tasks.add_task(run_parser_async)

    feeds = [dict(row) for row in db.execute("SELECT id, url, title FROM feeds ORDER BY id DESC").fetchall()]
    html_list = ""
    for feed in feeds:
        safe_url = html.escape(feed['url'])
        safe_title = html.escape(feed['title'])
        html_list += f"""
        <li>
            <span title="{safe_url}">{safe_title}</span>
            <button hx-delete="/api/feeds/{feed['id']}" hx-target="closest li" hx-swap="outerHTML">DEL</button>
        </li>
        """
    return HTMLResponse(content=html_list)


                <!--
                {% for feed in feeds %}
                <li>
                    <span title="{{ feed.url }}">{{ feed.title }}</span>
                    <button hx-delete="/api/feeds/{{ feed.id }}" hx-target="closest li" hx-swap="outerHTML">DEL</button>
                </li>
                {% endfor %}
                -->


@app.get("/", response_class=HTMLResponse)
def read_root(
    request: Request, 
    db: sqlite3.Connection = Depends(get_db),
    lang: str = None,
    feedpipe_lang: str = Cookie(None),
    view: str = "inbox"
):
    current_lang = lang or feedpipe_lang or "ru"
    
    inbox_count = db.execute("SELECT COUNT(*) FROM articles WHERE status='inbox'").fetchone()[0]
    later_count = db.execute("SELECT COUNT(*) FROM articles WHERE status='later'").fetchone()[0]
    
    if view == "later":
        cursor = db.execute("SELECT id, title, link, description, source_url FROM articles WHERE status='later' ORDER BY id DESC LIMIT 50")
    else:
        cursor = db.execute("SELECT id, title, link, description, source_url FROM articles WHERE status='inbox' ORDER BY id DESC LIMIT 50")
        
    articles = [dict(row) for row in cursor.fetchall()]
    feeds = [dict(row) for row in db.execute("SELECT id, url, title FROM feeds ORDER BY id DESC").fetchall()]

    response = templates.TemplateResponse("index.html", {
        "request": request, 
        "articles": articles,
        "total_count": inbox_count,
        "later_count": later_count,
        "feeds": feeds,
        "lang": current_lang,
        "view": view
    })
    
    if lang:
        response.set_cookie(key="feedpipe_lang", value=lang, max_age=31536000)
    return response
