"""Full-page screenshot at a true device viewport, via Chrome's DevTools protocol.

Headless Chrome won't open a window narrower than about 500px, so --window-size
can't make a phone-width capture. This emulates the viewport instead.

Usage: python design-review/shoot_cdp.py <url> <out.png> [width] [height]
"""
import asyncio, base64, json, os, subprocess, sys, tempfile, time, urllib.request

import websockets

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PORT = 9333


async def main(url, out, width, height):
    profile = tempfile.mkdtemp(prefix="ampshot-")
    proc = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                             f"--remote-debugging-port={PORT}", "--remote-debugging-address=127.0.0.1",
                             f"--user-data-dir={profile}", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
                page = next(t for t in tabs if t["type"] == "page")
                break
            except Exception:
                time.sleep(0.2)
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=None) as ws:
            n = 0

            async def call(method, **params):
                nonlocal n
                n += 1
                await ws.send(json.dumps({"id": n, "method": method, "params": params}))
                while True:
                    msg = json.loads(await ws.recv())
                    if msg.get("id") == n:
                        return msg.get("result", {})

            await call("Emulation.setDeviceMetricsOverride", width=width, height=height,
                       deviceScaleFactor=1, mobile=width < 768)
            await call("Page.enable")
            await call("Page.navigate", url=url)
            await asyncio.sleep(8)  # let the example load, build and render
            metrics = await call("Page.getLayoutMetrics")
            full_h = min(int(metrics["cssContentSize"]["height"]), int(os.environ.get("MAXH", "100000")))
            shot = await call("Page.captureScreenshot", format="png", captureBeyondViewport=True,
                              clip={"x": 0, "y": 0, "width": width, "height": full_h, "scale": 1})
            with open(out, "wb") as f:
                f.write(base64.b64decode(shot["data"]))
            sw = await call("Runtime.evaluate", expression="document.documentElement.scrollWidth")
            print(out, f"{width}x{full_h}", "scrollWidth", sw["result"]["value"])
    finally:
        proc.terminate()


if __name__ == "__main__":
    url, out = sys.argv[1], sys.argv[2]
    w = int(sys.argv[3]) if len(sys.argv) > 3 else 390
    h = int(sys.argv[4]) if len(sys.argv) > 4 else 844
    asyncio.run(main(url, os.path.abspath(out), w, h))
