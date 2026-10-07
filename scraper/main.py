import os
import sys
import csv
import json
import logging
from datetime import datetime
from typing import Dict, Any, List

# Ensure utf-8 output on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from .engine import ScraperEngine
from .utils import calculate_alert_tier

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger("PriceCheck")

def run_price_check(config_path: str = None, data_dir: str = None) -> None:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if not config_path:
        config_path = os.path.join(base_dir, "config.json")
    if not data_dir:
        data_dir = os.path.join(base_dir, "data")

    os.makedirs(data_dir, exist_ok=True)
    latest_file = os.path.join(data_dir, "latest_prices.json")
    history_file = os.path.join(data_dir, "price_history.json")
    csv_file = os.path.join(data_dir, "price_history.csv")
    data_js_file = os.path.join(data_dir, "data.js")

    if not os.path.exists(config_path):
        logger.error(f"Arquivo config.json não encontrado em: {config_path}")
        return

    with open(config_path, "r", encoding="utf-8-sig") as f:
        config = json.load(f)

    # Load existing latest prices to compute deltas
    prev_prices: Dict[str, Dict[str, Any]] = {}
    if os.path.exists(latest_file):
        try:
            with open(latest_file, "r", encoding="utf-8-sig") as f:
                for item in json.load(f):
                    if isinstance(item, dict) and "id" in item:
                        prev_prices[item["id"]] = item
        except Exception as e:
            logger.warning(f"Não foi possível ler {latest_file}: {e}")

    # Load existing history
    history_list: List[Dict[str, Any]] = []
    if os.path.exists(history_file):
        try:
            with open(history_file, "r", encoding="utf-8-sig") as f:
                history_list = json.load(f)
        except Exception:
            history_list = []

    engine = ScraperEngine()
    now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    now_br = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    containers = config.get("containers", [])
    logger.info(f"Iniciando verificação de {len(containers)} containers...")

    results = []
    new_history_entries = []

    for container in containers:
        c_id = container.get("id")
        c_name = container.get("name")
        c_target = float(container.get("targetPrice", 0))
        items = container.get("items", [])

        logger.info(f"--- Container: {c_name} (Alvo: R$ {c_target:.2f}) ---")

        for item in items:
            item_id = item.get("id")
            item_name = item.get("name")
            store = item.get("store")
            url = item.get("url")
            pref_method = item.get("preferredMethod")

            logger.info(f"Verificando: {item_name} [{store}]...")

            extractor = engine.find_extractor_for_url(url)
            driver = pref_method if pref_method else (extractor.get("driver") if extractor else "http")

            # Fetch & Parse
            html = engine.fetch_html(url, driver=driver)
            parsed = engine.parse(html, url, extractor=extractor)

            current_price = parsed.get("price")
            prev_record = prev_prices.get(item_id, {})
            prev_price = prev_record.get("price")

            # Calculate price delta
            price_change = 0.0
            price_change_pct = 0.0
            variation = "none"

            if current_price and prev_price and prev_price > 0:
                price_change = round(current_price - prev_price, 2)
                price_change_pct = round(((current_price - prev_price) / prev_price) * 100, 2)
                if price_change > 0:
                    variation = "up"
                elif price_change < 0:
                    variation = "down"

            alert_tier = calculate_alert_tier(current_price, c_target)

            result_item = {
                "id": item_id,
                "containerId": c_id,
                "containerName": c_name,
                "name": item_name,
                "store": store,
                "url": url,
                "rawTitle": parsed.get("title") or prev_record.get("rawTitle", ""),
                "price": current_price or prev_record.get("price"),
                "priceOriginal": parsed.get("priceOriginal") or prev_record.get("priceOriginal"),
                "previousPrice": prev_price or current_price,
                "priceChange": price_change,
                "priceChangePct": price_change_pct,
                "variationType": variation,
                "alertTier": alert_tier,
                "inStock": parsed.get("inStock", False),
                "availabilityText": parsed.get("availabilityText", "Desconhecido"),
                "imageUrl": parsed.get("imageUrl") or prev_record.get("imageUrl"),
                "sku": parsed.get("sku") or prev_record.get("sku"),
                "lastUpdated": now_iso,
                "status": parsed.get("status", "error")
            }

            if parsed.get("status") == "success" and current_price:
                logger.info(f"  [OK] R$ {current_price:.2f} ({result_item['availabilityText']})")
                new_history_entries.append({
                    "timestamp": now_iso,
                    "date": now_br,
                    "itemId": item_id,
                    "containerId": c_id,
                    "name": item_name,
                    "store": store,
                    "price": current_price,
                    "inStock": result_item["inStock"]
                })
            else:
                logger.warning(f"  [AVISO] Falha ao extrair ({parsed.get('error') or 'sem preço'}). Mantendo dados anteriores se houver.")
                # Preserve previous price if current fetch failed
                if prev_record.get("price"):
                    result_item["price"] = prev_record.get("price")
                    result_item["inStock"] = prev_record.get("inStock", False)
                    result_item["availabilityText"] = prev_record.get("availabilityText", "Desconhecido")
                    result_item["status"] = "cached"

            results.append(result_item)

    # 1. Save latest_prices.json
    with open(latest_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=4, ensure_ascii=False)
    logger.info(f"Salvo {latest_file} com {len(results)} itens.")

    # 2. Append to price_history.json
    history_list.extend(new_history_entries)
    # Keep last 15,000 entries max to prevent excessive file sizes
    if len(history_list) > 15000:
        history_list = history_list[-15000:]
    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(history_list, f, indent=2, ensure_ascii=False)

    # 3. Append to price_history.csv
    file_exists = os.path.exists(csv_file) and os.path.getsize(csv_file) > 0
    with open(csv_file, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["Timestamp", "Date", "ItemId", "ContainerId", "Name", "Store", "Price", "InStock"])
        for entry in new_history_entries:
            writer.writerow([
                entry["timestamp"], entry["date"], entry["itemId"],
                entry["containerId"], entry["name"], entry["store"],
                entry["price"], entry["inStock"]
            ])

    # 4. Generate data.js for zero-CORS static support
    with open(data_js_file, "w", encoding="utf-8") as f:
        f.write("// PriceCheckURL Static Bundle\n")
        f.write("window.PRICE_CHECK_CONFIG = " + json.dumps(config, ensure_ascii=False) + ";\n")
        f.write("window.PRICE_CHECK_LATEST = " + json.dumps(results, ensure_ascii=False) + ";\n")
        f.write("window.PRICE_CHECK_HISTORY = " + json.dumps(history_list, ensure_ascii=False) + ";\n")

    logger.info("Execução do PriceCheck concluída com sucesso!")

if __name__ == "__main__":
    run_price_check()
