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


def send_discord_alert(
    webhook_url: str,
    item_name: str,
    store: str,
    url: str,
    current_price: float,
    target_price: float,
    alert_tier: Dict[str, Any],
    image_url: Optional[str] = None,
    container_name: Optional[str] = None,
    availability: str = "Em Estoque",
    mention: Optional[str] = None
) -> bool:
    """
    Dispara um alerta rico (Embed) para o webhook do Discord quando um produto
    atinge a categoria 'COMPRA CERTA' ou 'PREÇO ACEITÁVEL'.
    Suporta menção direta de usuário (<@ID>), cargo ou @here/@everyone.
    """
    if not webhook_url or not webhook_url.startswith("https://discord.com/api/webhooks/"):
        return False

    is_compra_certa = alert_tier.get("category") == "COMPRA CERTA"
    color = 0x10B981 if is_compra_certa else 0xF59E0B
    prefix = "🟢 COMPRA CERTA!" if is_compra_certa else "🟡 PREÇO ACEITÁVEL!"

    diff = current_price - target_price
    diff_pct = alert_tier.get("percentDiff", 0)

    if diff <= 0:
        margem_str = f"R$ {abs(diff):.2f} abaixo da sua meta ({diff_pct:.1f}%)"
    else:
        margem_str = f"R$ {diff:.2f} acima da sua meta (+{diff_pct:.1f}%)"

    embed = {
        "title": f"{prefix} {item_name}",
        "url": url,
        "description": f"Oferta monitorada em **{store}** atingiu condição de compra favorável!",
        "color": color,
        "fields": [
            {"name": "💰 Preço Atual", "value": f"**R$ {current_price:,.2f}**".replace(",", "X").replace(".", ",").replace("X", "."), "inline": True},
            {"name": "🎯 Preço-Alvo", "value": f"R$ {target_price:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."), "inline": True},
            {"name": "📉 Margem", "value": margem_str, "inline": True},
            {"name": "🏪 Loja", "value": store, "inline": True},
            {"name": "📦 Estoque", "value": availability, "inline": True},
            {"name": "📁 Grupo / Produto", "value": container_name or item_name, "inline": True},
            {"name": "🔗 Oferta", "value": f"[👉 Clique aqui para abrir a oferta na {store}]({url})", "inline": False}
        ],
        "footer": {
            "text": "PriceCheckURL • Monitor Inteligente de Preços"
        }
    }

    if image_url and str(image_url).startswith("http"):
        embed["thumbnail"] = {"url": image_url}

    payload = {
        "username": "PriceCheck Bot",
        "avatar_url": "https://raw.githubusercontent.com/twitter/twemoji/master/assets/72x72/1f4b0.png",
        "embeds": [embed],
        "allowed_mentions": {"parse": ["everyone", "users", "roles"]}
    }

    if mention:
        m = str(mention).strip()
        if m.isdigit():
            m = f"<@{m}>"
        payload["content"] = f"{m} 🔥 **Alerta de Oportunidade:** {item_name} em **{store}**!"

    try:
        import httpx
        with httpx.Client(timeout=10.0) as client:
            res = client.post(webhook_url, json=payload)
            return res.status_code in (200, 204)
    except Exception:
        return False


