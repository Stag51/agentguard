"""Record a captioned walkthrough video of the dashboard (for LinkedIn / the portfolio).

Needs: Playwright (`pip install playwright`), Google Chrome, ffmpeg, and the dashboard
running at http://127.0.0.1:8000 (`uv run agentguard serve`) with results in its database.

    python scripts/record_demo.py                # writes media/agentguard-demo.mp4

Frames come straight from Chrome's screencast (CDP) and are encoded with your own ffmpeg,
so nothing extra is downloaded. It drives a real browser like a user (scroll, hover, click), shows a visible cursor, and
burns short captions into the page so the video makes sense with the sound off, which is
how most people watch LinkedIn. Captions describe only what the dashboard actually shows.
"""

from __future__ import annotations

import base64
import shutil
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8000/"
# 1372x772 CSS pixels at device scale 1.4 = 1920x1080 real pixels: crisp text, and the page
# lays out like a laptop screen so everything stays large.
VIEW = {"width": 1372, "height": 772}
SCALE = 1.4
OUT_DIR = Path("media")

INIT_JS = """
(() => {
  // visible cursor (headless video capture does not draw one)
  const cur = document.createElement('div');
  cur.style.cssText = 'position:fixed;left:-50px;top:-50px;width:22px;height:22px;z-index:2147483647;pointer-events:none;background:#fff;border:3px solid #d55181;box-shadow:0 0 0 2px #000;';
  const cap = document.createElement('div');
  cap.id = 'cap';
  cap.style.cssText = 'position:fixed;left:0;right:0;bottom:0;z-index:2147483646;display:none;background:#d55181;color:#fff;font:800 27px/1.25 system-ui,"Segoe UI",sans-serif;padding:16px 36px 18px;border-top:6px solid #3987e5;';
  addEventListener('DOMContentLoaded', () => { document.body.append(cur, cap); });
  addEventListener('mousemove', (e) => { cur.style.left = (e.clientX - 4) + 'px'; cur.style.top = (e.clientY - 4) + 'px'; }, true);
})();
"""

SMOOTH_JS = """
(target, ms) => new Promise((resolve) => {
  const start = scrollY, dist = target - start, t0 = performance.now();
  const ease = (t) => (t < .5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2);
  const step = (now) => { const t = Math.min(1, (now - t0) / ms); scrollTo(0, start + dist * ease(t)); t < 1 ? requestAnimationFrame(step) : resolve(); };
  requestAnimationFrame(step);
})
"""


def caption(page, text: str) -> None:
    page.evaluate("(t) => { const c = document.getElementById('cap'); c.textContent = t; c.style.display = t ? 'block' : 'none'; }", text)


def scroll_to(page, selector: str, offset: int = 24, ms: int = 1500) -> None:
    y = page.evaluate("([s, o]) => document.querySelector(s).getBoundingClientRect().top + scrollY - o", [selector, offset])
    page.evaluate(f"({SMOOTH_JS})({max(0, y)}, {ms})")


def move_to(page, locator, steps: int = 28, dx: int = 0) -> tuple[float, float]:
    box = locator.bounding_box()
    x, y = box["x"] + box["width"] / 2 + dx, box["y"] + box["height"] / 2
    page.mouse.move(x, y, steps=steps)
    return x, y


def row(page, section: str, text: str):
    return page.locator(f"{section} .row", has_text=text).first


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    tmp = OUT_DIR / "_frames"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    final = OUT_DIR / "agentguard-demo.mp4"
    frames: list[tuple[float, Path]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(viewport=VIEW, device_scale_factor=SCALE)
        ctx.add_init_script(INIT_JS)
        page = ctx.new_page()
        page.goto(URL)
        page.wait_for_selector("#main:not([hidden])", timeout=20000)
        page.wait_for_timeout(600)
        page.mouse.move(900, 400)

        cdp = ctx.new_cdp_session(page)

        def on_frame(params):
            path = tmp / f"f{len(frames):06d}.jpg"
            path.write_bytes(base64.b64decode(params["data"]))
            frames.append((params["metadata"]["timestamp"], path))
            cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})

        cdp.on("Page.screencastFrame", on_frame)
        cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 92, "maxWidth": 1920, "maxHeight": 1080, "everyNthFrame": 1})

        # 1. hook
        caption(page, "AgentGuard: catch AI agent regressions before they ship")
        page.wait_for_timeout(4200)

        # 2. the setup
        scroll_to(page, ".tiles", offset=16, ms=1600)
        caption(page, "16 deliberate changes. Did the quality gate get every call right?")
        page.wait_for_timeout(2600)

        # 3. quality chart
        scroll_to(page, "#bars-success", offset=140, ms=1800)
        caption(page, "Each bar is one version of the agent. Red = blocked by the gate.")
        page.wait_for_timeout(900)
        for txt in ("B01", "R07", "R05"):
            move_to(page, row(page, "#bars-success", txt), dx=-40)
            page.wait_for_timeout(700)

        # 4. a broken tool schema -> detail panel
        caption(page, "Rename one tool argument and success falls from 100% to 33%")
        move_to(page, row(page, "#bars-success", "R03 ·"), dx=-40)
        page.wait_for_timeout(500)
        row(page, "#bars-success", "R03 ·").click()
        page.wait_for_timeout(3600)

        # 5. heatmap
        scroll_to(page, "#heat", offset=110, ms=1800)
        caption(page, "The heatmap shows exactly which kinds of task each change breaks")
        page.wait_for_timeout(1400)
        rows = page.locator("#heat tr")
        n = rows.count()
        for i in (n - 3, n - 7, n - 11):
            if 0 < i < n:
                move_to(page, rows.nth(i).locator("td").nth(4), steps=22)
                page.wait_for_timeout(900)

        # 6. cost vs quality
        scroll_to(page, "#scatter", offset=150, ms=1800)
        caption(page, "Cheaper models cost less but quality drops. Verbose prompts cost more for nothing.")
        page.wait_for_timeout(1000)
        box = page.locator("#scatter").bounding_box()
        for fx, fy in ((0.22, 0.30), (0.62, 0.78), (0.93, 0.12)):
            page.mouse.move(box["x"] + box["width"] * fx, box["y"] + box["height"] * fy, steps=26)
            page.wait_for_timeout(1000)

        # 7. the honest miss
        scroll_to(page, "#bars-success", offset=140, ms=1700)
        caption(page, "One miss, reported honestly: latency noise hid a slow model")
        page.wait_for_timeout(700)
        move_to(page, row(page, "#bars-success", "R09"), dx=-40)
        row(page, "#bars-success", "R09").click()
        page.wait_for_timeout(3800)

        # 8. close
        scroll_to(page, "body", offset=0, ms=1800)
        caption(page, "Simulated model for now. Next: real Gemini results.")
        page.wait_for_timeout(3600)

        cdp.send("Page.stopScreencast")
        ctx.close()
        browser.close()

    if len(frames) < 10:
        raise SystemExit(f"only {len(frames)} frames captured; is the dashboard running at {URL}?")

    # Frames only arrive when the page changes, so give each one the time until the next.
    lines = []
    for (ts, path), (nxt, _) in zip(frames, frames[1:] + [(frames[-1][0] + 1.0, None)]):
        lines += [f"file '{path.resolve().as_posix()}'", f"duration {max(nxt - ts, 0.001):.4f}"]
    lines.append(f"file '{frames[-1][1].resolve().as_posix()}'")  # concat demuxer quirk: repeat the last file
    listing = tmp / "list.txt"
    listing.write_text(chr(10).join(lines), encoding="utf-8")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
         "-vf", "fps=30,scale=1920:1080:flags=lanczos,format=yuv420p",
         "-c:v", "libx264", "-crf", "18", "-preset", "slow", "-movflags", "+faststart", str(final)],
        check=True,
    )
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"wrote {final} ({final.stat().st_size / 1e6:.1f} MB) from {len(frames)} frames")


if __name__ == "__main__":
    sys.exit(main())
