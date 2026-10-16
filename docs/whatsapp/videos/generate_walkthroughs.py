"""Record honest concept walkthroughs of the local WhatsApp prototype.

These recordings are design-review assets, not evidence of a live Meta integration.
Requires Playwright, Microsoft Edge, and PyAV in the local Python environment.
"""

from __future__ import annotations

import time
import sys
from pathlib import Path

import av
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent
URL = (ROOT / "index.html").as_uri()
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
SIZE = {"width": 1600, "height": 900}


def pause(seconds: float = 1.5) -> None:
    time.sleep(seconds)


def install_recording_ui(page) -> None:
    page.evaluate(
        """() => {
          const css = document.createElement('style');
          css.textContent = `
            #recording-cursor { position: fixed; z-index: 10000; width: 21px; height: 21px;
              border: 2px solid #fff; border-radius: 50%; background: #c58e7f88;
              box-shadow: 0 0 0 5px #c58e7f33, 0 3px 18px #000b;
              pointer-events: none; left: -40px; top: -40px; transition: left .08s, top .08s; }
            #recording-stamp { position: fixed; z-index: 9998; left: 18px; bottom: 17px;
              padding: 8px 12px; color: #f4ddd6; background: #1c1715e8;
              border: 1px solid #c58e7f75; border-radius: 8px; font: 700 10px Inter,Segoe UI,sans-serif;
              letter-spacing: .13em; pointer-events: none; box-shadow: 0 5px 22px #0008; }
            #recording-card { position: fixed; inset: 0; z-index: 10001; display: grid;
              place-items: center; background: radial-gradient(circle at 70% 25%, #422720, #14100f 60%, #070707);
              color: #f5eae6; font-family: Inter, Segoe UI, sans-serif; pointer-events: none;
              transition: opacity .45s; }
            #recording-card .inside { max-width: 860px; padding: 64px 72px; border: 1px solid #c58e7f55;
              border-radius: 22px; background: #211916d9; box-shadow: 0 20px 90px #0009; }
            #recording-card .kicker { color: #dcb0a3; font-size: 12px; font-weight: 700;
              letter-spacing: .2em; text-transform: uppercase; }
            #recording-card h1 { margin: 18px 0 16px; color: #f4ddd6; background: none;
              font-size: 44px; line-height: 1.13; }
            #recording-card p { color: #dbc8c1; font-size: 18px; line-height: 1.5; margin: 0; }
            #recording-card .disclaimer { margin-top: 31px; padding-top: 21px;
              border-top: 1px solid #c58e7f55; color: #edc4b8; font-size: 14px; }
          `;
          document.head.appendChild(css);
          const cursor = document.createElement('div'); cursor.id = 'recording-cursor'; document.body.appendChild(cursor);
          document.addEventListener('mousemove', e => { cursor.style.left = (e.clientX - 10) + 'px'; cursor.style.top = (e.clientY - 10) + 'px'; });
          const stamp = document.createElement('div'); stamp.id = 'recording-stamp';
          stamp.textContent = 'CONCEPT DEMO · NO LIVE META ACTION'; document.body.appendChild(stamp);
        }"""
    )


def card(page, title: str, subtitle: str, end: bool = False) -> None:
    page.evaluate(
        """([title, subtitle, end]) => {
          document.getElementById('recording-card')?.remove();
          const el = document.createElement('div'); el.id = 'recording-card';
          const box = document.createElement('div'); box.className = 'inside';
          const kicker = document.createElement('div'); kicker.className = 'kicker';
          kicker.textContent = end ? 'Evidence gap' : 'HireBuddha · WhatsApp concept';
          const h = document.createElement('h1'); h.textContent = title;
          const p = document.createElement('p'); p.textContent = subtitle;
          const d = document.createElement('div'); d.className = 'disclaimer';
          d.textContent = end
            ? 'Re-record this journey in the working app with a test business and real Meta events before App Review submission.'
            : 'Prototype walkthrough with sample data. All Meta authorization, publishing, and message actions are simulated.';
          box.append(kicker, h, p, d); el.appendChild(box); document.body.appendChild(el);
        }""",
        [title, subtitle, end],
    )
    pause(3.2 if not end else 4)
    if not end:
        page.evaluate("document.getElementById('recording-card').style.opacity='0'")
        pause(0.55)
        page.evaluate("document.getElementById('recording-card').remove()")


def click(page, selector: str, hold: float = 1.6) -> None:
    target = page.locator(selector).first
    target.scroll_into_view_if_needed(timeout=10000)
    box = target.bounding_box()
    if box:
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=10)
        pause(0.3)
    target.click(timeout=10000)
    pause(hold)


def action(page, name: str, hold: float = 1.6) -> None:
    click(page, f'[data-action="{name}"]', hold)


def go(page, route: str, hold: float = 2.0) -> None:
    click(page, f'#workspace-nav a[href="#{route}"]', hold)
    page.evaluate("window.scrollTo(0,0)")


def close_dialog(page, hold: float = 0.9) -> None:
    click(page, '#close-dialog', hold)


def onboarding(page) -> None:
    card(page, "Business onboarding & number control", "The intended tenant journey from preparation to a connected WhatsApp number.")
    go(page, "connect", 3)
    click(page, '#meta-ready', 0.5)
    click(page, '#number-ready', 0.8)
    action(page, "core:connect-meta", 4)
    action(page, "core:meta-return", 3)
    action(page, "core:verify-checks", 4)
    action(page, "core:demo-activate", 3)
    action(page, "core:activate", 3)
    click(page, '[data-go="health"]', 3)
    card(page, "Live evidence required", "Capture the real Meta-hosted Embedded Signup, asset return, permission grant, number registration, webhook checks and a test send/receive.", True)


def automation_and_handoff(page) -> None:
    card(page, "AI messaging & human handoff", "A configurable flow checks permission and the service window before AI or a human replies.")
    go(page, "automation", 2)
    click(page, '[data-go="automation-builder"]', 2)
    for node in ("consent", "window", "message", "agent", "handoff"):
        action(page, f"op:node-{node}", 2.2)
    page.evaluate("window.scrollTo(0, 650)")
    pause(2.5)
    page.evaluate("window.scrollTo(0, 0)")
    pause(0.7)
    action(page, "op:test", 2.5)
    action(page, "op:run-test", 3)
    action(page, "op:return-builder", 1.5)
    action(page, "op:publish", 2.5)
    action(page, "op:confirm-publish", 2)
    go(page, "inbox", 3)
    action(page, "core:takeover", 2.2)
    reply = page.locator('#reply-text')
    reply.fill("Hi Ananya, I can help you compare the Sora table sizes.")
    pause(1)
    action(page, "core:send-reply", 2.5)
    action(page, "core:message-details", 2.5)
    close_dialog(page)
    action(page, "core:takeover", 1.6)
    action(page, "core:thread-rohan", 3)
    card(page, "Live evidence required", "Re-record with a test contact: an actual approved template/API send, inbound webhook, status callbacks, AI response, human takeover and a real operator reply.", True)


def business_assets(page) -> None:
    card(page, "Templates, catalogue & WhatsApp Flows", "Tenant-managed content and interactive experiences in one workspace.")
    go(page, "templates", 2)
    click(page, '[data-go="template-editor"]', 3)
    action(page, "asset:validate-template", 2.5)
    close_dialog(page)
    action(page, "asset:submit-template", 2.5)
    action(page, "asset:submit-confirm", 2.3)
    go(page, "catalogues", 3)
    action(page, "asset:connect-catalogue", 3)
    action(page, "asset:catalogue-granted", 2.5)
    go(page, "forms", 2)
    click(page, '[data-go="form-builder"]', 3)
    action(page, "asset:validate-flow", 2.5)
    action(page, "asset:test-flow", 3)
    action(page, "asset:close", 1)
    action(page, "asset:publish-flow", 2)
    action(page, "asset:publish-confirm", 2)
    card(page, "Live evidence required", "Show a real template submission and status, authorized catalogue asset and sync, and WhatsApp Flow validation, publication and customer submission.", True)


def campaigns_and_reporting(page) -> None:
    card(page, "Consent, campaigns & analytics", "Eligibility gates, reply routing and reporting for business operators.")
    go(page, "contacts", 3)
    click(page, '[data-go="contact-detail"]', 2.5)
    action(page, "op:evidence", 2.5)
    close_dialog(page)
    action(page, "op:stop", 2.5)
    action(page, "op:confirm-stop", 2.5)
    go(page, "campaigns", 2)
    click(page, '[data-go="campaign-review"]', 3)
    action(page, "op:campaign-test", 2.5)
    action(page, "op:test-preview", 1.7)
    action(page, "op:schedule-review", 2.5)
    action(page, "op:confirm-schedule", 2.5)
    action(page, "op:campaign-results", 3)
    close_dialog(page)
    go(page, "analytics", 4)
    card(page, "Live evidence required", "Use actual consent records, scheduled sends, delivery/read status webhooks, customer replies and reconciled report totals in the review recording.", True)


VIDEOS = [
    ("01_business_onboarding_and_number_control.mp4", onboarding),
    ("02_ai_messaging_and_human_handoff.mp4", automation_and_handoff),
    ("03_templates_catalogue_and_flows.mp4", business_assets),
    ("04_consent_campaigns_and_analytics.mp4", campaigns_and_reporting),
]


def webm_to_mp4(source: Path, destination: Path) -> None:
    with av.open(str(source), "r") as src, av.open(str(destination), "w", options={"movflags": "faststart"}) as dst:
        incoming = src.streams.video[0]
        outgoing = dst.add_stream("libx264", rate=25, options={"crf": "25", "preset": "medium"})
        outgoing.width, outgoing.height = incoming.width, incoming.height
        outgoing.pix_fmt = "yuv420p"
        for frame in src.decode(video=0):
            for packet in outgoing.encode(frame.reformat(format="yuv420p")):
                dst.mux(packet)
        for packet in outgoing.encode():
            dst.mux(packet)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=EDGE, headless=True, args=["--allow-file-access-from-files"])
        try:
            chosen = set(sys.argv[1:])
            for filename, journey in VIDEOS:
                if chosen and filename not in chosen and filename.removesuffix(".mp4") not in chosen:
                    continue
                print(f"Recording {filename}", flush=True)
                context = browser.new_context(viewport=SIZE, device_scale_factor=1, record_video_dir=str(OUT), record_video_size=SIZE)
                page = context.new_page()
                page.goto(URL + "#overview", wait_until="load")
                page.wait_for_function("window.WA && window.WA.screens['analytics']")
                install_recording_ui(page)
                pause(1)
                journey(page)
                context.close()
                webm = Path(page.video.path())
                mp4 = OUT / filename
                webm_to_mp4(webm, mp4)
                print(f"Created {mp4.name}: {mp4.stat().st_size:,} bytes", flush=True)
                webm.unlink()
        finally:
            browser.close()


if __name__ == "__main__":
    main()
