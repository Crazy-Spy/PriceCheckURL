import re
from urllib.parse import urlparse
from typing import Optional, Dict, Any

def parse_price(value: Any) -> Optional[float]:
    """
    Converts various currency strings into a float (e.g. 'R$ 2.450,90' -> 2450.90).
    Handles standard Brazilian BRL formatting and US/international formatting.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    
    val_str = str(value).strip()
    if not val_str:
        return None

    # Remove non-numeric characters except comma and period
    # Match patterns like: 1.234,56 or 1234,56 or 1,234.56 or 1234.56
    cleaned = re.sub(r"[^\d,\.]", "", val_str)
    if not cleaned:
        return None

    # Case 1: Both period and comma present
    if "." in cleaned and "," in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            # Brazilian format: 1.234,56
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            # US format: 1,234.56
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        # Only comma: e.g. 1234,56 -> replace with period
        cleaned = cleaned.replace(",", ".")
    elif "." in cleaned:
        # Only period: could be 1.234 (thousands) or 1234.56 (decimal)
        parts = cleaned.split(".")
        if len(parts) == 2 and len(parts[1]) == 3:
            # Likely thousands separator: e.g. 1.250 -> 1250.00
            cleaned = cleaned.replace(".", "")

    try:
        res = float(cleaned)
        return round(res, 2) if res > 0 else None
    except ValueError:
        return None

def get_domain(url: str) -> str:
    """
    Extracts root domain from a URL (e.g. 'https://www.kabum.com.br/produto/1' -> 'kabum.com.br').
    """
    try:
        netloc = urlparse(url).netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        # Remove port if present
        if ":" in netloc:
            netloc = netloc.split(":")[0]
        return netloc
    except Exception:
        return ""

def calculate_alert_tier(price: Optional[float], target_price: Optional[float]) -> Dict[str, Any]:
    """
    Calculates badge, category and action based on target price percentage diff.
    """
    if price is None or price <= 0:
        return {
            "action": "Indisponível",
            "targetPrice": target_price or 0,
            "percentDiff": 0,
            "badge": "N/A",
            "category": "Sem Preço",
            "theme": "muted"
        }

    if not target_price or target_price <= 0:
        return {
            "action": "Monitorando preço",
            "targetPrice": 0,
            "percentDiff": 0,
            "badge": "Monitorando",
            "category": "MONITORANDO",
            "theme": "info"
        }

    diff_pct = round(((price - target_price) / target_price) * 100, 2)

    if diff_pct <= 0:
        return {
            "action": "Preço atingiu ou ficou abaixo do seu preço-alvo. Excelente hora para comprar!",
            "targetPrice": target_price,
            "percentDiff": diff_pct,
            "badge": "Compra Certa",
            "category": "COMPRA CERTA",
            "theme": "compra_certa"
        }
    elif diff_pct <= 8.0:
        return {
            "action": f"Até 8% acima do preço-alvo (+{diff_pct}%). Pode valer a compra dependendo da urgência.",
            "targetPrice": target_price,
            "percentDiff": diff_pct,
            "badge": f"Aceitável (+{diff_pct}%)",
            "category": "PREÇO ACEITÁVEL",
            "theme": "aceitavel"
        }
    elif diff_pct <= 15.0:
        return {
            "action": f"Preço acima do ideal (+{diff_pct}%). Recomendável aguardar novas promoções.",
            "targetPrice": target_price,
            "percentDiff": diff_pct,
            "badge": f"Acima (+{diff_pct}%)",
            "category": "ACIMA DO IDEAL",
            "theme": "acima_ideal"
        }
    else:
        return {
            "action": f"Preço muito elevado (+{diff_pct}% acima do alvo). Aguarde redução significativa.",
            "targetPrice": target_price,
            "percentDiff": diff_pct,
            "badge": f"Muito Alto (+{diff_pct}%)",
            "category": "MUITO ALTO",
            "theme": "muito_alto"
        }
