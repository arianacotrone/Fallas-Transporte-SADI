"""
Scraper - Perturbaciones del SADI (CAMMESA)
==========================================
Requisitos:
    pip install selenium webdriver-manager

Uso:
    python scraper_perturbaciones_cammesa.py
"""

import json
import csv
import time
import logging
import random
from datetime import date, timedelta
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# ── Configuración ──────────────────────────────────────────────────────────────

DATE_START = date(2024, 1, 1)
DATE_END   = date(2024, 1, 31)

#date.today()

# URL directa al iframe — evita navegar por la página principal
URL_IFRAME = "https://microfe.cammesa.com/visorpubespeciales/#/reportes?nemo=PERTURBACIONES_SADI_UNIF"

OUTPUT_JSON = Path("perturbaciones_sadi.json")
OUTPUT_CSV  = Path("perturbaciones_sadi.csv")
LOG_FILE    = Path("errores_scraping.log")

WAIT_MIN = 4
WAIT_MAX = 8
MAX_RETRIES = 2

# ── Logging ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.WARNING,
    format="%(asctime)s  %(levelname)s  %(message)s",
)

# ── Driver ─────────────────────────────────────────────────────────────────────

def build_driver(headless: bool = False) -> webdriver.Chrome:
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1400,900")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=opts)


# ── Navegación ─────────────────────────────────────────────────────────────────

def load_page(driver: webdriver.Chrome) -> None:
    """Carga la URL directa y espera que Angular/DevExtreme terminen de renderizar."""
    driver.get(URL_IFRAME)
    wait = WebDriverWait(driver, 30)
    wait.until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, "input.dx-texteditor-input[aria-haspopup='true']")
    ))
    time.sleep(2)


def set_date_js(driver: webdriver.Chrome, target: date) -> None:
    """
    Setea la fecha interactuando de forma nativa con el teclado sobre el input de DevExpress.
    """
    # 1. Importaciones locales necesarias por si acaso
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    
    # 2. Formatear la fecha del bucle al formato que necesita el input (DD/MM/YYYY)
    fecha_formateada = target.strftime("%d/%m/%Y")
    
    # 3. Esperar a que el input esté listo e interactuar
    wait = WebDriverWait(driver, 10)
    fecha_input = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "input.dx-texteditor-input")))
    
    fecha_input.click()
    
    # Seleccionar todo y borrar de manera limpia
    fecha_input.send_keys(Keys.COMMAND + "a")  # Si usas Windows/Linux, podés cambiar COMMAND por CONTROL
    fecha_input.send_keys(Keys.BACKSPACE)
    fecha_input.send_keys(Keys.DELETE)
    
    # Escribir la fecha correspondiente al día actual del bucle y confirmar
    fecha_input.send_keys(fecha_formateada)
    fecha_input.send_keys(Keys.ENTER)
    
    # Pequeña pausa para permitir que la tabla asimile el cambio de fecha
    time.sleep(3)




def extract_rows(driver: webdriver.Chrome, target: date) -> list[dict]:
    """Extrae filas del dx-data-grid de perturbaciones."""
    results = []
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "dx-data-grid"))
        )
        rows = driver.find_elements(By.CSS_SELECTOR, "dx-data-grid .dx-data-row")
        for row in rows:
            cells = row.find_elements(By.CSS_SELECTOR, "td[role='gridcell']")
            if len(cells) < 2:
                continue
            fecha_texto = cells[0].text.strip() if len(cells) > 0 else str(target)
            descripcion = cells[1].text.strip() if len(cells) > 1 else ""
            causa       = cells[2].text.strip() if len(cells) > 2 else ""
            if not descripcion:
                continue
            results.append({
                "fecha_perturbacion":  fecha_texto or str(target),
                "fecha_consulta":      str(target),
                "descripcion":         descripcion,
                "causa_observaciones": causa,
            })
    except Exception as e:
        logging.warning(f"{target}: error extrayendo filas - {e}")
    return results


# ── Loop principal ─────────────────────────────────────────────────────────────

def scrape_range(date_start: date, date_end: date, headless: bool = True) -> list[dict]:
    all_events: list[dict] = []
    scraped_dates: set[str] = set()

    if OUTPUT_JSON.exists():
        with open(OUTPUT_JSON, encoding="utf-8") as f:
            all_events = json.load(f)
        scraped_dates = {e["fecha_consulta"] for e in all_events}
        print(f"Retomando: {len(scraped_dates)} dias ya procesados.")

    driver = build_driver(headless=headless)

    try:
        load_page(driver)

        current    = date_start
        total_days = (date_end - date_start).days + 1
        day_count  = 0

        while current <= date_end:
            day_count += 1
            date_str = str(current)

            if date_str in scraped_dates:
                current += timedelta(days=1)
                continue

            print(f"[{day_count}/{total_days}] {date_str}...", end=" ", flush=True)

            events = []
            for attempt in range(MAX_RETRIES + 1):
                try:
                    set_date_js(driver, current)
                    events = extract_rows(driver, current)
                    break
                except Exception as e:
                    if attempt < MAX_RETRIES:
                        print(f"reintento {attempt+1}...", end=" ", flush=True)
                        time.sleep(4)
                        try:
                            load_page(driver)
                        except Exception:
                            pass
                    else:
                        logging.warning(f"{date_str}: {e}")
                        print(f"ERROR - {e}")

            if events:
                all_events.extend(events)
                print(f"{len(events)} evento(s)")
            else:
                print("sin perturbaciones")

            with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
                json.dump(all_events, f, ensure_ascii=False, indent=2)

            current += timedelta(days=1)
            time.sleep(random.uniform(WAIT_MIN, WAIT_MAX))

    finally:
        driver.quit()

    return all_events


# ── Export CSV ─────────────────────────────────────────────────────────────────

def export_csv(events: list[dict]) -> None:
    if not events:
        print("Sin eventos para exportar.")
        return
    fieldnames = ["fecha_perturbacion", "fecha_consulta", "descripcion", "causa_observaciones"]
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(events)
    print(f"CSV exportado: {OUTPUT_CSV} ({len(events)} filas)")


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # False = ver Chrome mientras corre (recomendado para primera prueba)
    HEADLESS = False

    print(f"Scrapeando perturbaciones del SADI: {DATE_START} -> {DATE_END}")
    print(f"Pausa entre requests: {WAIT_MIN}-{WAIT_MAX}s | Headless: {HEADLESS}\n")

    events = scrape_range(DATE_START, DATE_END, headless=HEADLESS)
    export_csv(events)

    print(f"\nListo. Total eventos: {len(events)}")
    print(f"JSON: {OUTPUT_JSON}")
    print(f"Log de errores: {LOG_FILE}")
