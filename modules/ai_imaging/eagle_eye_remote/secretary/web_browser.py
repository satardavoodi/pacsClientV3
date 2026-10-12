"""Optional isolated server browser. All network requests use the checked fetcher."""
import importlib.util
import time


class ServerBrowser:
    def __init__(self, fetch, channel='msedge'):
        if channel not in ('msedge', 'chrome', 'chromium'):
            raise ValueError('Unsupported server browser channel')
        self.fetch, self.channel = fetch, channel

    @property
    def available(self):
        return importlib.util.find_spec('playwright') is not None

    def read(self, url):
        if not self.available:
            raise ValueError('Server browser runtime is not installed')
        from playwright.sync_api import sync_playwright
        final, mime, raw = self.fetch(url)
        if mime not in ('text/html', 'text/plain', 'application/xhtml+xml'):
            raise ValueError('Use download for an image or document')
        count, total, started = 0, len(raw), time.monotonic()
        with sync_playwright() as driver:
            browser = driver.chromium.launch(headless=True,
                args=['--force-webrtc-ip-handling-policy=disable_non_proxied_udp','--disable-background-networking'], **(
                {} if self.channel == 'chromium' else {'channel': self.channel}))
            try:
                context = browser.new_context(accept_downloads=False, service_workers='block')
                context.set_default_timeout(10000)
                def route_request(route):
                    nonlocal count, total
                    request = route.request
                    if (request.method != 'GET' or request.resource_type in ('image','font','media')
                            or count >= 30 or time.monotonic()-started > 30):
                        route.abort()
                        return
                    count += 1
                    try:
                        target, kind, payload = ((final,mime,raw) if count == 1 and request.url == final
                                                  else self.fetch(request.url))
                        total += len(payload)
                        if total > 32*1024*1024 or kind in ('application/pdf','application/octet-stream'):
                            raise ValueError('Browser request limit')
                        # Redirects are independently checked by fetch; preserve their final origin.
                        if target != request.url:
                            route.fulfill(status=302, headers={'location':target})
                        else:
                            route.fulfill(status=200, content_type=kind, body=payload)
                    except Exception:
                        route.abort()
                context.route('**/*', route_request)
                context.route_web_socket('**/*', lambda socket: socket.close())
                page = context.new_page()
                response = page.goto(final, wait_until='domcontentloaded', timeout=30000)
                if response is None or not response.ok:
                    raise ValueError('Server browser could not read the page')
                result = page.evaluate("""() => ({text:document.body?.innerText.slice(0,20000)||'',
                    links:Array.from(document.querySelectorAll('a[href]')).slice(0,100).map(a=>({url:a.href})),
                    images:Array.from(document.images).slice(0,100).map(i=>({url:i.currentSrc||i.src,alt:i.alt.slice(0,500),srcset:i.srcset.slice(0,4000)}))})""")
                if not result['text'].strip():
                    raise ValueError('Server browser returned no page text')
                for field in ('links','images'):
                    result[field] = [item for item in result[field] if item['url'].startswith('https://')]
                return {**result,'url':page.url,'backend':'server_playwright',
                        'scripts_executed':True,'content_is_untrusted':True}
            finally:
                browser.close()
