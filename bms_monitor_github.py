"""
╔══════════════════════════════════════════════════════════════╗
║    BookMyShow Monitor — GitHub Actions + WhatsApp Edition    ║
║  Runs every 5 min via GitHub Actions, alerts via CallMeBot   ║
╚══════════════════════════════════════════════════════════════╝

Config is read from GitHub Secrets (no hardcoded values needed).
"""

import os
import time
import requests
import json
from datetime import datetime
from urllib.parse import quote
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ── Config from environment variables (GitHub Secrets) ────────
WHATSAPP_PHONE   = os.environ["+14376635396"]    # e.g. +919876543210
CALLMEBOT_APIKEY = os.environ["4995068"]  # e.g. 4829301
BMS_URL = "https://in.bookmyshow.com/sports/icc-men-s-t20-world-cup-2026-semi-final-2/ET00474271"
STATE_FILE = "last_status.json"                    # Persists status between runs
# ──────────────────────────────────────────────────────────────


# ── WhatsApp via CallMeBot ────────────────────────────────────
def send_whatsapp(message: str):
    encoded = quote(message)
    url = (
        f"https://api.callmebot.com/whatsapp.php"
        f"?phone={WHATSAPP_PHONE}&text={encoded}&apikey={CALLMEBOT_APIKEY}"
    )
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200 and "Message Sent" in resp.text:
            print(f"[WhatsApp ✓] Sent: {message[:60]}...")
        else:
            print(f"[WhatsApp ✗] {resp.status_code}: {resp.text[:100]}")
    except Exception as e:
        print(f"[WhatsApp ✗] Exception: {e}")


# ── State management (read/write last known status) ───────────
def read_last_status() -> str:
    try:
        with open(STATE_FILE, "r") as f:
            data = json.load(f)
            return data.get("status", "unknown")
    except Exception:
        return "unknown"  # First run


def write_status(status: str):
    with open(STATE_FILE, "w") as f:
        json.dump({
            "status": status,
            "updated_at": datetime.utcnow().isoformat()
        }, f)


# ── Browser setup (headless Chrome for GitHub Actions) ────────
def create_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--log-level=3")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
    # GitHub Actions has Chrome pre-installed — no webdriver-manager needed
    driver = webdriver.Chrome(options=options)
    return driver


# ── Page check ────────────────────────────────────────────────
def check_page(driver) -> dict:
    try:
        driver.get(BMS_URL)
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        time.sleep(4)  # Wait for JS to render

        page_source = driver.page_source.lower()
        button_text = ""

        # Try known BMS selectors
        for selector in [
            "button.__buy-btn", "a.__buy-btn",
            "[class*='buy-btn']", "[class*='book-btn']",
            ".__primary-btn", "[data-testid='buyButton']",
            "button[class*='btn']",
        ]:
            try:
                els = driver.find_elements(By.CSS_SELECTOR, selector)
                if els:
                    button_text = els[0].text.strip()
                    if button_text:
                        break
            except Exception:
                continue

        # Fallback: scan all buttons
        if not button_text:
            for btn in driver.find_elements(By.TAG_NAME, "button"):
                txt = btn.text.strip()
                if txt and len(txt) < 50:
                    button_text = txt
                    break

        bt = button_text.lower()

        if any(x in bt for x in ["book now", "buy now", "buy tickets", "book tickets", "get tickets"]):
            return {"status": "book_now", "button_text": button_text}
        elif any(x in bt for x in ["coming soon", "notify me", "sold out", "houseful"]):
            return {"status": "coming_soon", "button_text": button_text}
        elif any(x in page_source for x in ["book now", "buy now", "buy tickets"]):
            return {"status": "book_now", "button_text": "detected in page source"}
        elif "coming soon" in page_source:
            return {"status": "coming_soon", "button_text": "Coming Soon (page source)"}
        else:
            return {"status": "unknown", "button_text": button_text or "No button found"}

    except Exception as e:
        return {"status": "error", "button_text": str(e)}


# ── Main (runs once per GitHub Actions trigger) ───────────────
def main():
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{now}] BMS Monitor triggered by GitHub Actions")

    last_status = read_last_status()
    print(f"[State] Last known status: {last_status}")

    print("[Browser] Launching headless Chrome...")
    driver = create_driver()

    try:
        result = check_page(driver)
        current_status = result["status"]
        button_text = result["button_text"]
        print(f"[Check] Status: {current_status!r} | Button: {button_text!r}")

        # ── TICKETS JUST WENT LIVE ─────────────────────────────
        if current_status == "book_now" and last_status != "book_now":
            send_whatsapp(
                "🚨🏏 TICKETS ARE LIVE! 🏏🚨\n\n"
                "ICC Men's T20 World Cup 2026\n"
                "Semi Final 2 — BOOK NOW!\n\n"
                f"👉 {BMS_URL}\n\n"
                f"⏰ Detected at: {datetime.utcnow().strftime('%d %b %Y, %H:%M UTC')}"
            )
            print("[🎉] TICKETS LIVE — WhatsApp alert sent!")

        # ── WENT BACK TO COMING SOON (sold out?) ──────────────
        elif current_status == "coming_soon" and last_status == "book_now":
            send_whatsapp(
                "⚠️ BMS status changed back to Coming Soon.\n"
                "Tickets may have sold out.\n"
                f"Button: {button_text}"
            )

        # ── UNKNOWN / ERROR — worth flagging ──────────────────
        elif current_status in ("unknown", "error") and last_status == "coming_soon":
            send_whatsapp(
                f"⚠️ BMS page returned unexpected status: {current_status}\n"
                f"Button text: {button_text}\n"
                f"Check manually: {BMS_URL}"
            )

        # ── STILL COMING SOON — no alert needed ───────────────
        else:
            print(f"[OK] No change in status ({current_status}). No alert sent.")

        # Save current status for next run
        write_status(current_status)

    finally:
        driver.quit()
        print("[Browser] Chrome closed. Run complete.")


if __name__ == "__main__":
    main()
