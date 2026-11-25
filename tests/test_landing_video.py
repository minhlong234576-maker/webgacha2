"""Landing page: video nen — kiem tra loading, reduced-motion va responsive.

- Video nen phai phat tren desktop (co currentTime > 0).
- `prefers-reduced-motion: reduce` -> KHONG tai video (chi hien poster).
- Khong tran ngang o 390px / 768px.
- Asset media phai tra ve 200 voi dung MIME type.

Usage: python tests/test_landing_video.py [port]
"""
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent

import asyncio
import sys

import httpx
from playwright.async_api import async_playwright

PORT = sys.argv[1] if len(sys.argv) > 1 else "8101"
BASE = f"http://127.0.0.1:{PORT}"

FAILS = []
PASSES = 0


def check(name, cond, detail=""):
    global PASSES
    if cond:
        PASSES += 1
        print(f"  PASS {name}" + (f"   {detail}" if detail else ""))
    else:
        FAILS.append(name)
        print(f"  FAIL {name}" + (f"   {detail}" if detail else ""))


async def main():
    print("=== 1. ASSET MEDIA ===")
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as c:
        for path, ctype in [
            ("/static/media/landing-poster.jpg", "image/jpeg"),
            ("/static/media/landing-loop.mp4", "video/mp4"),
            ("/static/media/landing-loop.webm", "video/webm"),
            ("/static/landing.js", "javascript"),
            ("/static/landing.css", "css"),
        ]:
            r = await c.get(path)
            check(f"GET {path} -> 200", r.status_code == 200, str(r.status_code))
            check(f"{path} co MIME dung", ctype in r.headers.get("content-type", ""),
                  r.headers.get("content-type", ""))

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)

        print()
        print("=== 2. VIDEO PHAT TREN DESKTOP ===")
        ctx = await browser.new_context(viewport={"width": 1400, "height": 900})
        page = await ctx.new_page()
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.goto(f"{BASE}/", wait_until="load")
        await page.wait_for_timeout(2500)
        info = await page.evaluate("""() => {
            const v = document.querySelector('video.lp-video');
            return {paused: v.paused, t: v.currentTime, w: v.videoWidth,
                    h: v.videoHeight, src: v.currentSrc};
        }""")
        check("video khong paused", not info["paused"], str(info))
        check("video da chay (currentTime > 0)", info["t"] > 0, str(info))
        check("video co kich thuoc thuc", info["w"] > 0 and info["h"] > 0, str(info))
        check("video chon dung nguon", ".webm" in info["src"] or ".mp4" in info["src"],
              info["src"])
        check("khong co loi JS console", not errors, str(errors[:2]))

        print()
        print("=== 3. PREFERRED-REDUCED-MOTION: KHONG TAI VIDEO ===")
        ctx_rm = await browser.new_context(
            viewport={"width": 1400, "height": 900}, reduced_motion="reduce",
        )
        p_rm = await ctx_rm.new_page()
        await p_rm.goto(f"{BASE}/", wait_until="load")
        await p_rm.wait_for_timeout(2500)
        rm = await p_rm.evaluate("""() => {
            const v = document.querySelector('video.lp-video');
            const srcs = Array.from(document.querySelectorAll('video.lp-video source'))
                .map(s => s.getAttribute('src'));
            return {srcs, anySrc: srcs.some(Boolean), currentSrc: v.currentSrc || ''};
        }""")
        check("khong gan src cho <source>", not rm["anySrc"], str(rm["srcs"]))
        check("video khong co currentSrc (chua tai)", rm["currentSrc"] == "",
              rm["currentSrc"])
        # Poster van phai hien.
        poster = await p_rm.locator("video.lp-video").get_attribute("poster")
        check("poster van duoc gan", bool(poster), str(poster))

        print()
        print("=== 4. RESPONSIVE: KHONG TRAN NGANG ===")
        for width, height in [(390, 844), (768, 1024), (1280, 900)]:
            c2 = await browser.new_context(
                viewport={"width": width, "height": height}, is_mobile=width < 500,
                has_touch=width < 500,
            )
            p2 = await c2.new_page()
            await p2.goto(f"{BASE}/", wait_until="load")
            await p2.wait_for_timeout(1200)
            # Do bang `scrollX` thuc te: `scrollWidth` co the phan anh noi dung
            # da duoc `overflow: clip` cat di (khong con tran ngang that).
            ov = await p2.evaluate("""() => {
                window.scrollTo(9999, 0);
                const x = window.scrollX;
                window.scrollTo(0, 0);
                return x;
            }""")
            check(f"{width}px: khong tran ngang", ov == 0, f"scrollX={ov}")
            stage = await p2.evaluate("""() => {
                const r = document.querySelector('.lp-stage').getBoundingClientRect();
                return {w: Math.round(r.width), h: Math.round(r.height)};
            }""")
            check(f"{width}px: video co kich thuoc hop ly",
                  stage["w"] > 100 and stage["h"] > 60, str(stage))
            await c2.close()

        await browser.close()

    print()
    print(f"=== KET QUA: {PASSES} PASS, {len(FAILS)} FAIL ===")
    if FAILS:
        print("FAIL:", FAILS)
        sys.exit(1)
    print(">>> LANDING VIDEO TEST PASS")


asyncio.run(main())
