#!/usr/bin/env python3
"""
SaaS Screencast Recorder
Записывает screencast сайта по инструкции через Playwright + Xvfb + ffmpeg
Использует постоянный Chrome-профиль с уже сохранённой авторизацией.
"""
import subprocess
import sys
import time
import os
import json
import signal
from pathlib import Path

OUTPUT_DIR = "/root/HermesWorkspace/screencast/output"
PROFILE_DIR = "/root/HermesWorkspace/screencast/chrome-profile"
WIDTH = 1920
HEIGHT = 1080


def start_xvfb(display=":99"):
    proc = subprocess.Popen([
        "Xvfb", display,
        "-screen", "0", f"{WIDTH}x{HEIGHT}x24",
        "-ac",
        "-nocursor"
    ])
    time.sleep(1)
    # Скрыть системный курсор X11 полностью
    os.environ["DISPLAY"] = display
    subprocess.Popen(["unclutter", "-display", display, "-idle", "0", "-root"])
    time.sleep(0.3)
    # Увести физическую мышь за пределы экрана
    subprocess.run(["xdotool", "mousemove", "9999", "9999"],
                   env={**os.environ, "DISPLAY": display},
                   capture_output=True)
    return proc


def start_recording(output_file, display=":99"):
    proc = subprocess.Popen([
        "ffmpeg", "-y",
        "-f", "x11grab",
        "-r", "30",
        "-s", f"{WIDTH}x{HEIGHT}",
        "-i", f"{display}.0",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "23",
        output_file
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)
    return proc


def js_click(page, selector):
    """Execute click via JavaScript to bypass intercepting elements."""
    escaped = selector.replace("\\", "\\\\").replace("'", "\\'")
    return page.evaluate(f"""
        (() => {{
            // Try CSS selector first
            let el = document.querySelector('{escaped}');
            
            // If not found, try finding by text content
            if (!el) {{
                const allElements = document.querySelectorAll('a, button, [role=button], [role=link]');
                for (const e of allElements) {{
                    if (e.textContent.trim().includes('{escaped}')) {{
                        el = e;
                        break;
                    }}
                }}
            }}
            
            if (!el) return false;
            const rect = el.getBoundingClientRect();
            const x = rect.left + rect.width / 2;
            const y = rect.top + rect.height / 2;
            
            // Dispatch click events
            ['mousedown', 'mouseup', 'click'].forEach(type => {{
                const event = new MouseEvent(type, {{
                    bubbles: true,
                    cancelable: true,
                    view: window,
                    clientX: x,
                    clientY: y
                }});
                el.dispatchEvent(event);
            }});
            
            return {{x, y, found: true}};
        }})()
    """)


def js_hover(page, selector):
    """Execute hover via JavaScript to bypass intercepting elements."""
    escaped = selector.replace("\\", "\\\\").replace("'", "\\'")
    return page.evaluate(f"""
        (() => {{
            // Try CSS selector first
            let el = document.querySelector('{escaped}');
            
            // If not found, try finding by text content
            if (!el) {{
                const allElements = document.querySelectorAll('a, button, [role=button], [role=link]');
                for (const e of allElements) {{
                    if (e.textContent.trim().includes('{escaped}')) {{
                        el = e;
                        break;
                    }}
                }}
            }}
            
            if (!el) return false;
            const rect = el.getBoundingClientRect();
            const x = rect.left + rect.width / 2;
            const y = rect.top + rect.height / 2;
            
            // Dispatch mouseenter and mouseover events
            ['mouseenter', 'mouseover', 'mousemove'].forEach(type => {{
                const event = new MouseEvent(type, {{
                    bubbles: true,
                    cancelable: true,
                    view: window,
                    clientX: x,
                    clientY: y
                }});
                el.dispatchEvent(event);
            }});
            
            // Also trigger CSS :hover via class
            el.classList.add('__js_hover');
            
            return {{x, y, found: true}};
        }})()
    """)


def get_center(page, selector):
    """Координаты центра элемента или None, если элемент не найден."""
    print(f"  [DEBUG] get_center ищет селектор: {selector!r}")
    # Try Playwright locator first
    try:
        box = page.locator(selector).first.bounding_box()
        if box:
            return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    except:
        pass
    # Fallback: use JavaScript to get position
    escaped = selector.replace("\\", "\\\\").replace("'", "\\'")
    result = page.evaluate(f"""
        (() => {{
            const el = document.querySelector('{escaped}');
            if (!el) return null;
            const rect = el.getBoundingClientRect();
            return {{x: rect.left + rect.width / 2, y: rect.top + rect.height / 2}};
        }})()
    """)
    if result:
        return result["x"], result["y"]
    return None


def move_cursor_to(page, x, y, steps=25, step_delay=0.012):
    """Плавно двигает и реальный, и визуальный курсор по одной траектории —
    без рывков, без опоры на CSS-transition."""
    print(f"  [DEBUG] move_cursor_to вызван: x={x:.1f} y={y:.1f}")
    try:
        start = page.evaluate(
            "({x: parseFloat(window.__cursor.style.left)||0, "
            "y: parseFloat(window.__cursor.style.top)||0})"
        )
        sx, sy = start.get("x", x), start.get("y", y)
    except Exception:
        sx, sy = x, y

    page.evaluate("window.__cursor.style.transition='none'")
    for i in range(1, steps + 1):
        ix = sx + (x - sx) * i / steps
        iy = sy + (y - sy) * i / steps
        page.mouse.move(ix, iy)
        page.evaluate(
            f"window.__cursor.style.left='{ix}px'; window.__cursor.style.top='{iy}px'"
        )
        time.sleep(step_delay)
def record_saas(script_file):
    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

    with open(script_file) as f:
        script = json.load(f)

    url = script["url"]
    title = script.get("title", "screencast")
    steps = script["steps"]
    output_file = f"{OUTPUT_DIR}/{title}_{int(time.time())}.mp4"

    print(f"🎬 Запись: {title}")
    print(f"🌐 URL: {url}")
    print(f"📁 Файл: {output_file}")

    click_events = []

    xvfb = start_xvfb()
    os.environ["DISPLAY"] = ":99"

    start_time = time.time()
    ffmpeg = start_recording(output_file)

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            # Постоянный профиль вместо storage_state — сохранённая сессия внутри
            context = p.chromium.launch_persistent_context(
                PROFILE_DIR,
                headless=False,
                viewport={"width": WIDTH, "height": HEIGHT},
                locale="ru-RU",
                args=[
                    "--display=:99",
                    "--no-sandbox",
                    "--window-size=1920,1080",
                    "--start-maximized",
                    "--disable-infobars",
                ]
            )
            page = context.pages[0] if context.pages else context.new_page()

            page.add_init_script("""
                const __hideCursorStyle = document.createElement('style');
                __hideCursorStyle.textContent = '*, *::before, *::after { cursor: none !important; }';
                document.addEventListener('DOMContentLoaded', ()=>document.head.appendChild(__hideCursorStyle));
                if (document.head) document.head.appendChild(__hideCursorStyle.cloneNode(true));

                window.__cursor = document.createElement('div');
                Object.assign(window.__cursor.style, {
                    position:'fixed', width:'22px', height:'22px', zIndex:999999,
                    pointerEvents:'none', transition:'left .2s ease-out, top .2s ease-out',
                    clipPath: 'polygon(0 0, 0 70%, 25% 55%, 40% 90%, 55% 83%, 40% 50%, 70% 50%)',
                    background:'#000000',
                    filter:'drop-shadow(1px 1px 1px rgba(255,255,255,0.9)) drop-shadow(-1px -1px 0px rgba(255,255,255,0.9))',
                    left:'-100px', top:'-100px'
                });
                document.addEventListener('DOMContentLoaded', ()=>document.body.appendChild(window.__cursor));

                window.__clickRipple = function(x, y) {
                    const ripple = document.createElement('div');
                    Object.assign(ripple.style, {
                        position:'fixed', left:(x-10)+'px', top:(y-10)+'px',
                        width:'20px', height:'20px', borderRadius:'50%',
                        border:'2px solid rgba(255,80,80,0.9)', zIndex:999998,
                        pointerEvents:'none', animation:'none'
                    });
                    document.body.appendChild(ripple);
                    let scale = 1;
                    const iv = setInterval(() => {
                        scale += 0.15;
                        ripple.style.transform = 'scale(' + scale + ')';
                        ripple.style.opacity = Math.max(0, 1 - scale/2.5);
                        if (scale > 2.5) { clearInterval(iv); ripple.remove(); }
                    }, 16);
                };
            """)

            print(f"→ Открываем {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)

            # Измеряем реальную высоту шапки браузера (вкладки+адресная строка),
            # чтобы координаты кликов для зума совпадали с полноэкранной записью x11grab
            chrome_offset = page.evaluate(
                "({x: window.outerWidth - window.innerWidth, "
                "y: window.outerHeight - window.innerHeight})"
            )
            offset_x = chrome_offset.get("x", 0)
            offset_y = chrome_offset.get("y", 0)
            print(f"  [DEBUG] Смещение шапки браузера: x={offset_x} y={offset_y}")

            for i, step in enumerate(steps):
                action = step.get("action")
                pause = step.get("pause", 2)
                print(f"  [{i+1}/{len(steps)}] {action}: {step.get('description', '')}")

                if action == "wait":
                    time.sleep(step.get("seconds", 2))

                elif action == "scroll_to":
                    y = step.get("y", 500)
                    page.evaluate(f"window.scrollTo({{top: {y}, behavior: 'smooth'}})")
                    time.sleep(pause)

                elif action == "scroll_down":
                    amount = step.get("amount", 500)
                    page.evaluate(f"window.scrollBy({{top: {amount}, behavior: 'smooth'}})")
                    time.sleep(pause)

                elif action == "click":
                    selector = step.get("selector")
                    try:
                        center = get_center(page, selector)
                        if center:
                            x, y = center
                            move_cursor_to(page, x, y)
                            page.evaluate(f"window.__clickRipple({x}, {y})")
                            click_events.append({
                                "time": time.time() - start_time,
                                "x": x + offset_x, "y": y + offset_y
                            })
                        time.sleep(0.15)
                        page.click(selector, timeout=5000)
                    except Exception as e:
                        print(f"  ⚠️ Клик по '{selector}' не удался, пробую JS клик: {e}")
                        # Fallback: try JS click
                        try:
                            result = js_click(page, selector)
                            if result and result.get("found"):
                                x, y = result["x"], result["y"]
                                move_cursor_to(page, x, y)
                                page.evaluate(f"window.__clickRipple({x}, {y})")
                                click_events.append({
                                    "time": time.time() - start_time,
                                    "x": x, "y": y
                                })
                        except Exception as e2:
                            print(f"  ⚠️ JS клик тоже не удался: {e2}")
                    time.sleep(pause)

                elif action == "hover":
                    selector = step.get("selector")
                    try:
                        center = get_center(page, selector)
                        if center:
                            x, y = center
                            move_cursor_to(page, x, y)
                            click_events.append({
                                "time": time.time() - start_time,
                                "x": x + offset_x, "y": y + offset_y
                            })
                        # Use JavaScript hover to bypass intercepting elements
                        result = js_hover(page, selector)
                        if not result:
                            raise Exception("Element not found via JS hover")
                    except Exception as e:
                        print(f"  ⚠️ Ховер по '{selector}' не удался, пробую fallback через JS: {e}")
                        # Fallback: try JS hover anyway
                        try:
                            result = js_hover(page, selector)
                        except Exception as e2:
                            print(f"  ⚠️ JS ховер тоже не удался: {e2}")
                    time.sleep(pause)

                elif action == "goto":
                    target_url = step.get("url")
                    page.goto(target_url, wait_until="domcontentloaded")
                    time.sleep(pause)

                elif action == "highlight":
                    selector = step.get("selector")
                    # Escape single quotes and backslashes for JavaScript string
                    escaped_selector = selector.replace("\\", "\\\\").replace("'", "\\'")
                    page.evaluate(f"""
                        const el = document.querySelector('{escaped_selector}');
                        if (el) {{
                            el.style.outline = '3px solid #ff0000';
                            el.style.outlineOffset = '2px';
                        }}
                    """)
                    time.sleep(pause)

                elif action == "type":
                    selector = step.get("selector")
                    text = step.get("text", "")
                    page.fill(selector, text)
                    time.sleep(pause)

            time.sleep(3)
            context.close()

    finally:
        ffmpeg.send_signal(signal.SIGTERM)
        ffmpeg.wait()
        xvfb.terminate()
        xvfb.wait()

    events_file = output_file.replace(".mp4", "_events.json")
    with open(events_file, "w") as f:
        json.dump(click_events, f)
    print(f"✅ Лог событий сохранен: {events_file} ({len(click_events)} событий)")

    final_file = output_file
    if click_events:
        print("→ Запуск плавного зум-эффекта...")
        zoom_result = subprocess.run([
            "/usr/local/lib/hermes-agent/venv/bin/python",
            "/root/HermesWorkspace/screencast/apply_zoom.py",
            output_file,
            events_file
        ], capture_output=True, text=True)
        if zoom_result.returncode == 0:
            zoomed_file = output_file.replace(".mp4", "_zoomed.mp4")
            if os.path.exists(zoomed_file):
                final_file = zoomed_file
        else:
            print(f"  ⚠️ Зум не применился: {zoom_result.stderr[-500:]}")
    else:
        print("→ Кликов/ховеров не было, зум пропущен")

    print(f"✅ Готово: {final_file}")
    return final_file


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python record_saas.py script.json")
        sys.exit(1)
    record_saas(sys.argv[1])
