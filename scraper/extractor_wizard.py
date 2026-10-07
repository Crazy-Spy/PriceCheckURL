import sys
import re
import json
import argparse
from typing import Dict, Any, List
from bs4 import BeautifulSoup

# Ensure utf-8 output on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from .engine import ScraperEngine
from .utils import get_domain, parse_price

def clean_css_selector(tag_name: str, el) -> str:
    if not el:
        return tag_name
    if el.get("id"):
        safe_id = re.sub(r"[^\w-]", "", el["id"])
        if safe_id:
            return f"#{safe_id}"
    if tag_name.lower() in ["h1", "h2"]:
        return tag_name
    classes = el.get("class", [])
    safe_classes = [c for c in classes if re.match(r"^[a-zA-Z][a-zA-Z0-9_-]*$", c)]
    if safe_classes:
        good = [c for c in safe_classes if any(k in c.lower() for k in ["price", "preco", "val", "tit", "prod", "amount", "final", "total"])]
        chosen = good[0] if good else safe_classes[0]
        return f"{tag_name}.{chosen}"
    return tag_name

def discover_candidates(html: str) -> Dict[str, List[Dict[str, Any]]]:
    soup = BeautifulSoup(html, "html.parser")
    candidates = {
        "titles": [],
        "prices": [],
        "images": [],
        "stock": []
    }

    # 1. Title candidates
    seen_titles = set()
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        t = h1.get_text(strip=True)
        candidates["titles"].append({
            "selector": "h1",
            "value": t,
            "type": "css"
        })
        seen_titles.add(t)

    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content") and og_title["content"] not in seen_titles:
        candidates["titles"].append({
            "selector": "meta[property='og:title']",
            "value": og_title["content"],
            "type": "meta",
            "attribute": "content"
        })
        seen_titles.add(og_title["content"])

    # 2. Price candidates
    seen_prices = set()
    # Meta tag price
    meta_p = soup.find("meta", property="product:price:amount") or soup.find("meta", attrs={"name": "product:price:amount"})
    if meta_p and meta_p.get("content"):
        val = parse_price(meta_p["content"])
        if val:
            candidates["prices"].append({
                "selector": "meta[property='product:price:amount']",
                "attribute": "content",
                "value": f"R$ {val:.2f}",
                "numeric": val,
                "label": "Meta Tag Preço Oficial"
            })
            seen_prices.add(val)

    # Elements with class containing price/preco/val
    for el in soup.find_all(True, class_=re.compile(r"(price|preco|valor|val-prod)", re.I)):
        text = el.get_text(strip=True)
        if "R$" in text or re.search(r"\d+[\.,]\d{2}", text):
            m = re.search(r"R\$[\s\xa0]*([\d\.,]+)", text)
            p_val = parse_price(m.group(1)) if m else parse_price(text)
            if p_val and p_val not in seen_prices:
                sel = clean_css_selector(el.name, el)
                candidates["prices"].append({
                    "selector": sel,
                    "value": f"R$ {p_val:.2f}",
                    "numeric": p_val,
                    "raw": text[:60],
                    "label": "Elemento DOM com classe de preço"
                })
                seen_prices.add(p_val)

    # Fallback any element with R$
    if len(candidates["prices"]) < 2:
        for el in soup.find_all(string=re.compile(r"R\$[\s\xa0]*[\d\.,]+")):
            p_val = parse_price(el)
            if p_val and p_val not in seen_prices:
                parent = el.parent
                if parent:
                    sel = clean_css_selector(parent.name, parent)
                    candidates["prices"].append({
                        "selector": sel,
                        "value": f"R$ {p_val:.2f}",
                        "numeric": p_val,
                        "raw": str(el).strip()[:50],
                        "label": "Texto R$ encontrado"
                    })
                    seen_prices.add(p_val)

    # 3. Image candidates
    og_img = soup.find("meta", property="og:image")
    if og_img and og_img.get("content"):
        candidates["images"].append({
            "selector": "meta[property='og:image']",
            "attribute": "content",
            "value": og_img["content"]
        })

    for img in soup.find_all("img"):
        src = img.get("src")
        if src and any(k in (img.get("id", "") + " ".join(img.get("class", [])) + src).lower() for k in ["prod", "main", "foto", "image"]):
            candidates["images"].append({
                "selector": f"img.{'.'.join(img['class'])}" if img.get("class") else "img",
                "attribute": "src",
                "value": src
            })
            break

    # 4. Stock candidates
    out_of_stock_found = []
    for kw in ["ESGOTADO", "INDISPONÍVEL", "PRODUTO INDISPONÍVEL", "OUT OF STOCK", "AVISE-ME"]:
        if kw in html.upper():
            out_of_stock_found.append(kw)

    candidates["stock"] = {
        "outOfStockKeywordsDetected": out_of_stock_found,
        "likelyInStock": len(out_of_stock_found) == 0
    }

    return candidates

def interactive_wizard(url: str, auto_mode: bool = False) -> None:
    print("\n" + "=" * 60)
    print("   PRICECHECKURL - ASSISTENTE INTELIGENTE DE EXTRATORES")
    print("=" * 60)
    print(f"[*] Analisando URL: {url}")

    domain = get_domain(url)
    print(f"[OK] Domínio extraído: {domain}")

    engine = ScraperEngine()
    existing = engine.find_extractor_for_url(url)
    if existing:
        print(f"[!] Já existe um extrator para este domínio ({existing.get('name')}). Ele será atualizado se você prosseguir.")

    print("\n[*] Baixando página para inspeção visual do DOM...")
    html = engine.fetch_html(url, driver="http")
    driver_choice = "http"

    if not html or len(html) < 2000 or "Just a moment..." in html:
        print("[!] Requisição HTTP direta bloqueada ou incompleta. Tentando navegador headless...")
        html = engine.fetch_html(url, driver="browser")
        driver_choice = "browser"

    if not html:
        print("[X] Falha: Não foi possível obter o HTML da página. Verifique se o link está acessível.")
        return

    print(f"[OK] Página carregada com sucesso ({len(html)} bytes).")
    candidates = discover_candidates(html)

    # 1. Title selection
    print("\n" + "-" * 50)
    print("1. SELEÇÃO DO TÍTULO DO PRODUTO:")
    title_options = candidates["titles"]
    selected_title_sel = "h1"
    selected_title_attr = None

    if title_options:
        for idx, opt in enumerate(title_options, 1):
            print(f"  [{idx}] {opt['selector']} -> \"{opt['value'][:60]}\"")
        if auto_mode:
            chosen_t = 1
        else:
            ans = input(f"Escolha uma opção [1-{len(title_options)}] ou digite um seletor CSS [Enter para 1]: ").strip()
            chosen_t = int(ans) if ans.isdigit() and 1 <= int(ans) <= len(title_options) else (1 if not ans else ans)

        if isinstance(chosen_t, int):
            selected_title_sel = title_options[chosen_t - 1]["selector"]
            selected_title_attr = title_options[chosen_t - 1].get("attribute")
        else:
            selected_title_sel = chosen_t
    else:
        print("  [!] Nenhum título evidente encontrado.")
        if not auto_mode:
            selected_title_sel = input("Digite o seletor CSS para o título (ex: h1): ").strip() or "h1"

    # 2. Price selection
    print("\n" + "-" * 50)
    print("2. SELEÇÃO DO PREÇO À VISTA / PRINCIPAL:")
    price_options = candidates["prices"]
    selected_price_sel = None
    selected_price_attr = None

    if price_options:
        for idx, opt in enumerate(price_options, 1):
            lbl = f" ({opt.get('raw', '')})" if opt.get('raw') else ""
            print(f"  [{idx}] {opt['selector']} -> {opt['value']}{lbl}")
        if auto_mode:
            chosen_p = 1
        else:
            ans = input(f"Escolha a opção de preço [1-{len(price_options)}] ou digite seletor CSS [Enter para 1]: ").strip()
            chosen_p = int(ans) if ans.isdigit() and 1 <= int(ans) <= len(price_options) else (1 if not ans else ans)

        if isinstance(chosen_p, int):
            selected_price_sel = price_options[chosen_p - 1]["selector"]
            selected_price_attr = price_options[chosen_p - 1].get("attribute")
        else:
            selected_price_sel = chosen_p
    else:
        print("  [!] Nenhum valor com 'R$' detectado de imediato.")
        if not auto_mode:
            selected_price_sel = input("Digite o seletor CSS do preço (ex: .price): ").strip()

    # 3. Stock verification
    print("\n" + "-" * 50)
    print("3. DISPONIBILIDADE E ESTOQUE:")
    stock_info = candidates["stock"]
    if stock_info["outOfStockKeywordsDetected"]:
        print(f"  [!] Palavras de esgotado encontradas na página: {stock_info['outOfStockKeywordsDetected']}")
    else:
        print("  [OK] Produto aparenta estar em estoque (nenhum termo 'Esgotado' identificado).")

    # 4. Image
    img_sel = "meta[property='og:image']"
    img_attr = "content"
    if candidates["images"]:
        img_sel = candidates["images"][0]["selector"]
        img_attr = candidates["images"][0].get("attribute", "src")

    # Build new extractor definition
    store_name = domain.split(".")[0].capitalize()
    new_extractor = {
        "id": domain.replace(".", "_"),
        "name": store_name,
        "domains": [domain],
        "driver": driver_choice,
        "rules": {
            "title": {
                "selector": selected_title_sel,
                "fallback": "meta[property='og:title']"
            },
            "price": {
                "selector": selected_price_sel or "h1",
                "regex": "R\\$\\s*([\\d\\.,]+)"
            },
            "inStock": {
                "outOfStockKeywords": ["ESGOTADO", "INDISPONÍVEL", "OUT OF STOCK", "AVISE-ME"]
            },
            "image": {
                "selector": img_sel,
                "attribute": img_attr
            }
        }
    }
    if selected_price_attr:
        new_extractor["rules"]["price"]["attribute"] = selected_price_attr

    # Test extraction with the newly generated extractor!
    print("\n" + "=" * 50)
    print("TESTANDO EXTRATOR GERADO:")
    parsed = engine.parse(html, url, extractor=new_extractor)

    print(f"  Título extraído : {parsed.get('title')}")
    print(f"  Preço extraído  : R$ {parsed.get('price')}")
    print(f"  Estoque         : {parsed.get('availabilityText')} ({parsed.get('inStock')})")
    print(f"  Imagem          : {parsed.get('imageUrl')}")
    print(f"  Status          : {parsed.get('status').upper()}")
    print("=" * 50)

    if not auto_mode:
        confirm = input(f"\nDeseja salvar este extrator para '{domain}' em extractors.json? [S/n]: ").strip().lower()
        if confirm in ["", "s", "sim", "y", "yes"]:
            engine.save_extractor(new_extractor)
            print(f"[OK] Extrator para '{domain}' salvo com sucesso! Qualquer nova URL desta loja usará esta regra.")
        else:
            print("[*] Operação cancelada pelo usuário.")
    else:
        engine.save_extractor(new_extractor)
        print(f"[OK] Extrator para '{domain}' salvo automaticamente em modo --auto.")

def main():
    parser = argparse.ArgumentParser(description="Assistente para criação de extratores personalizados do PriceCheckURL.")
    parser.add_argument("url", nargs="?", help="URL do produto para inspecionar e criar o extrator")
    parser.add_argument("--auto", action="store_true", help="Gera e salva o extrator automaticamente usando as melhores heurísticas")
    args = parser.parse_args()

    url = args.url
    if not url:
        print("Digite a URL do produto na nova loja:")
        url = input("URL: ").strip()

    if not url:
        print("URL não fornecida. Encerrando.")
        sys.exit(1)

    interactive_wizard(url, auto_mode=args.auto)

if __name__ == "__main__":
    main()
