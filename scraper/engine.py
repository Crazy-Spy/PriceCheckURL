import os
import re
import json
import logging
from typing import Optional, Dict, Any, List
from bs4 import BeautifulSoup

from .utils import parse_price, get_domain

# Setup logging
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("PriceCheckEngine")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1"
}


class ScraperEngine:
    def __init__(self, extractors_path: Optional[str] = None):
        if not extractors_path:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            extractors_path = os.path.join(base_dir, "extractors", "extractors.json")
        self.extractors_path = extractors_path
        self.extractors = self.load_extractors()

    def load_extractors(self) -> List[Dict[str, Any]]:
        if os.path.exists(self.extractors_path):
            try:
                with open(self.extractors_path, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
                    return data.get("extractors", [])
            except Exception as e:
                logger.warning(f"Erro ao carregar extractors.json: {e}")
        return []

    def save_extractor(self, new_extractor: Dict[str, Any]) -> bool:
        """Adds or updates an extractor in extractors.json."""
        try:
            # Check if exists by ID or domain
            found = False
            for idx, ext in enumerate(self.extractors):
                if ext.get("id") == new_extractor.get("id") or any(
                    d in ext.get("domains", []) for d in new_extractor.get("domains", [])
                ):
                    self.extractors[idx] = new_extractor
                    found = True
                    break
            if not found:
                self.extractors.append(new_extractor)

            data = {"version": "2.0.0", "extractors": self.extractors}
            os.makedirs(os.path.dirname(self.extractors_path), exist_ok=True)
            with open(self.extractors_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error(f"Erro ao salvar extractor: {e}")
            return False

    def find_extractor_for_url(self, url: str) -> Optional[Dict[str, Any]]:
        domain = get_domain(url)
        for ext in self.extractors:
            for d in ext.get("domains", []):
                if d in domain or domain.endswith(d):
                    return ext
        return None

    def fetch_html(self, url: str, driver: str = "http", timeout: int = 30) -> Optional[str]:
        """
        Fetches HTML content either via HTTP client (fast) or Playwright headless browser.
        """
        if driver == "browser":
            html = self._fetch_browser(url, timeout)
            if html:
                return html
            # Fallback to HTTP if browser fails
            return self._fetch_http(url, timeout)
        else:
            html = self._fetch_http(url, timeout)
            # If Cloudflare detected, try browser fallback
            if html and ("Just a moment..." in html or "challenges.cloudflare.com" in html):
                logger.info(f"Cloudflare detectado em {url}. Acionando fallback browser...")
                browser_html = self._fetch_browser(url, timeout)
                if browser_html:
                    return browser_html
            return html

    def _fetch_http(self, url: str, timeout: int = 30) -> Optional[str]:
        try:
            import httpx
            with httpx.Client(headers=DEFAULT_HEADERS, follow_redirects=True, timeout=timeout, verify=False) as client:
                res = client.get(url)
                if res.status_code == 200 or len(res.text) > 2000:
                    return res.text
        except Exception as e:
            logger.debug(f"Falha no fetch HTTP: {e}")
        return None

    def _fetch_browser(self, url: str, timeout: int = 35) -> Optional[str]:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
                context = browser.new_context(
                    user_agent=DEFAULT_USER_AGENT,
                    locale="pt-BR"
                )
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
                # Wait briefly for dynamic client-side hydration
                page.wait_for_timeout(2000)
                content = page.content()
                browser.close()
                return content
        except ImportError:
            logger.debug("Playwright não instalado no ambiente local. Usando fallback HTTP.")
        except Exception as e:
            logger.warning(f"Erro no Playwright browser: {e}")
        return None

    def parse(self, html: str, url: str, extractor: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Parses page HTML using matching extractor or universal fallback heuristics.
        """
        result = {
            "title": "",
            "price": None,
            "priceOriginal": None,
            "inStock": False,
            "availabilityText": "Desconhecido",
            "imageUrl": None,
            "sku": None,
            "status": "error",
            "error": None
        }

        if not html or len(html.strip()) < 50:
            result["error"] = "Página vazia ou não carregada"
            return result

        soup = BeautifulSoup(html, "html.parser")

        # 1. Specialized Store Handlers if specified
        if extractor:
            handler = extractor.get("specialHandler")
            if handler == "kabum_next_data":
                parsed = self._handle_kabum_next_data(html, soup)
                if parsed.get("price"):
                    return parsed
            elif handler == "terabyte_datalayer":
                parsed = self._handle_terabyte(html, soup)
                if parsed.get("price"):
                    return parsed
            elif handler == "pichau_meta":
                parsed = self._handle_pichau(html, soup)
                if parsed.get("price"):
                    return parsed

            # 2. Declarative CSS/Regex Rules
            parsed_rules = self._apply_declarative_rules(html, soup, extractor.get("rules", {}))
            if parsed_rules.get("price"):
                return parsed_rules

        # 3. Universal Heuristics Fallback (JSON-LD -> Meta Tags -> Microdata -> DOM)
        universal_parsed = self._universal_heuristics(html, soup)
        if universal_parsed.get("price"):
            return universal_parsed

        result["error"] = "Preço não localizado com as regras atuais"
        return result

    def _apply_declarative_rules(self, html: str, soup: BeautifulSoup, rules: Dict[str, Any]) -> Dict[str, Any]:
        result = {
            "title": "",
            "price": None,
            "priceOriginal": None,
            "inStock": True,
            "availabilityText": "Em Estoque",
            "imageUrl": None,
            "sku": None,
            "status": "error",
            "error": None
        }

        # Title
        t_rule = rules.get("title", {})
        if t_rule.get("selector"):
            try:
                el = soup.select_one(t_rule["selector"])
                if el:
                    result["title"] = el.get_text(strip=True)
            except Exception:
                pass
        if not result["title"] and t_rule.get("fallback"):
            try:
                el = soup.select_one(t_rule["fallback"])
                if el:
                    result["title"] = el.get("content", el.get_text(strip=True))
            except Exception:
                pass

        # Price
        p_rule = rules.get("price", {})
        if p_rule.get("selector"):
            try:
                el = soup.select_one(p_rule["selector"])
                if el:
                    attr = p_rule.get("attribute")
                    raw_text = el.get(attr) if attr else el.get_text(strip=True)
                    if raw_text:
                        regex = p_rule.get("regex")
                        if regex:
                            m = re.search(regex, raw_text)
                            if m:
                                raw_text = m.group(1)
                        result["price"] = parse_price(raw_text)
            except Exception:
                pass

        # Original Price
        op_rule = rules.get("originalPrice", {})
        if op_rule.get("selector"):
            try:
                el = soup.select_one(op_rule["selector"])
                if el:
                    raw_text = el.get_text(strip=True)
                    regex = op_rule.get("regex")
                    if regex:
                        m = re.search(regex, raw_text)
                        if m:
                            raw_text = m.group(1)
                    result["priceOriginal"] = parse_price(raw_text)
            except Exception:
                pass

        # In Stock / Out of Stock
        stock_rule = rules.get("inStock", {})
        out_keywords = stock_rule.get("outOfStockKeywords", ["ESGOTADO", "INDISPONÍVEL", "OUT OF STOCK"])
        html_upper = html.upper()

        if any(kw.upper() in html_upper for kw in out_keywords):
            result["inStock"] = False
            result["availabilityText"] = "Esgotado"
        elif stock_rule.get("outOfStockSelector"):
            try:
                if soup.select_one(stock_rule["outOfStockSelector"]):
                    result["inStock"] = False
                    result["availabilityText"] = "Esgotado"
            except Exception:
                pass
        elif stock_rule.get("inStockSelector"):
            try:
                has_stock = bool(soup.select_one(stock_rule["inStockSelector"]))
                result["inStock"] = has_stock
                result["availabilityText"] = "Em Estoque" if has_stock else "Esgotado"
            except Exception:
                pass
        else:
            result["inStock"] = True
            result["availabilityText"] = "Em Estoque"

        # Image
        img_rule = rules.get("image", {})
        if img_rule.get("selector"):
            try:
                el = soup.select_one(img_rule["selector"])
                if el:
                    attr = img_rule.get("attribute", "src")
                    result["imageUrl"] = el.get(attr)
            except Exception:
                pass

        if result["price"]:
            result["status"] = "success"

        return result

    def _handle_kabum_next_data(self, html: str, soup: BeautifulSoup) -> Dict[str, Any]:
        result = {
            "title": "",
            "price": None,
            "priceOriginal": None,
            "inStock": False,
            "availabilityText": "Esgotado",
            "imageUrl": None,
            "sku": None,
            "status": "error",
            "error": None
        }
        script_tag = soup.find("script", id="__NEXT_DATA__")
        if not script_tag or not script_tag.string:
            return result
        try:
            data = json.loads(script_tag.string)
            page_props = data.get("props", {}).get("pageProps", {})
            prod = page_props.get("product") or page_props.get("productData") or {}

            if prod:
                result["title"] = prod.get("title") or prod.get("name") or ""
                result["sku"] = str(prod.get("id") or "")
                result["inStock"] = bool(prod.get("available", True))
                result["availabilityText"] = "Em Estoque" if result["inStock"] else "Esgotado"

                # Image
                if prod.get("thumbnail"):
                    result["imageUrl"] = prod["thumbnail"]
                elif prod.get("medias") and len(prod["medias"]) > 0:
                    result["imageUrl"] = prod["medias"][0].get("images", {}).get("g")

                # Price calculations
                prices = prod.get("prices", {})
                p_base = prices.get("priceWithDiscount") or prod.get("priceWithDiscount") or prod.get("price") or 0.0
                p_old = prices.get("oldPrice") or prod.get("oldPrice")
                if p_old:
                    result["priceOriginal"] = round(float(p_old), 2)

                # Prime cash savings
                save_prime = prod.get("savePrime") or prod.get("prime", {}).get("save") or 0.0
                if save_prime and p_base > save_prime:
                    result["price"] = round(float(p_base - save_prime), 2)
                elif p_base:
                    result["price"] = round(float(p_base), 2)

                if result["price"]:
                    result["status"] = "success"
        except Exception as e:
            logger.debug(f"Erro no parser KaBuM: {e}")
        return result

    def _handle_terabyte(self, html: str, soup: BeautifulSoup) -> Dict[str, Any]:
        result = {
            "title": "",
            "price": None,
            "priceOriginal": None,
            "inStock": True,
            "availabilityText": "Em Estoque",
            "imageUrl": None,
            "sku": None,
            "status": "error",
            "error": None
        }
        # dataLayer match
        m_price = re.search(r"'(?:value|price)'\s*:\s*([\d\.]+)", html)
        if m_price:
            result["price"] = parse_price(m_price.group(1))

        # Title
        m_title = re.search(r"'item_name'\s*:\s*'([^']+)'", html)
        if m_title:
            result["title"] = m_title.group(1)
        elif soup.find("h1"):
            result["title"] = soup.find("h1").get_text(strip=True)

        # Image
        img_el = soup.select_one("#img-produto, .img-fluid")
        if img_el:
            result["imageUrl"] = img_el.get("src")

        # Stock
        if "PRODUTO INDISPONIVEL" in html.upper() or soup.select_one("#indisponivel"):
            result["inStock"] = False
            result["availabilityText"] = "Esgotado"

        if result["price"]:
            result["status"] = "success"
        return result

    def _handle_pichau(self, html: str, soup: BeautifulSoup) -> Dict[str, Any]:
        result = {
            "title": "",
            "price": None,
            "priceOriginal": None,
            "inStock": True,
            "availabilityText": "Em Estoque",
            "imageUrl": None,
            "sku": None,
            "status": "error",
            "error": None
        }
        # Meta tags
        meta_price = soup.find("meta", attrs={"name": "product:price:amount"}) or soup.find(
            "meta", attrs={"name": "twitter:data1"}
        )
        if meta_price and meta_price.get("content"):
            result["price"] = parse_price(meta_price["content"])

        # Fallback text regex for à vista
        if not result["price"]:
            m_pix = re.search(r"(?:à|a)?\s*vista[^\d]{0,50}?R\$[\s\xa0]*([\d\.,]+)", html, re.IGNORECASE)
            if m_pix:
                result["price"] = parse_price(m_pix.group(1))

        # Title
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            result["title"] = og_title["content"]
        elif soup.find("h1"):
            result["title"] = soup.find("h1").get_text(strip=True)

        # Image
        og_img = soup.find("meta", property="og:image")
        if og_img and og_img.get("content"):
            result["imageUrl"] = og_img["content"]

        # Stock
        if any(w in html.upper() for w in ["INDISPONÍVEL", "ESGOTADO", "PRODUTO ESGOTADO"]):
            result["inStock"] = False
            result["availabilityText"] = "Esgotado"

        if result["price"]:
            result["status"] = "success"
        return result

    def _universal_heuristics(self, html: str, soup: BeautifulSoup) -> Dict[str, Any]:
        """
        Universal fallback: parses JSON-LD (Schema.org), OpenGraph, Microdata and DOM.
        """
        result = {
            "title": "",
            "price": None,
            "priceOriginal": None,
            "inStock": True,
            "availabilityText": "Em Estoque",
            "imageUrl": None,
            "sku": None,
            "status": "error",
            "error": None
        }

        # 1. JSON-LD Schema.org
        for script in soup.find_all("script", type="application/ld+json"):
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
                products = []
                if isinstance(data, list):
                    products = [p for p in data if isinstance(p, dict) and p.get("@type") == "Product"]
                elif isinstance(data, dict):
                    if data.get("@type") == "Product":
                        products.append(data)
                    elif "@graph" in data:
                        products.extend(
                            [p for p in data["@graph"] if isinstance(p, dict) and p.get("@type") == "Product"]
                        )

                for prod in products:
                    if prod.get("name"):
                        result["title"] = prod["name"]
                    if prod.get("image"):
                        img = prod["image"]
                        result["imageUrl"] = img[0] if isinstance(img, list) else img
                    if prod.get("sku"):
                        result["sku"] = str(prod["sku"])

                    offers = prod.get("offers")
                    if isinstance(offers, list) and offers:
                        offers = offers[0]
                    if isinstance(offers, dict):
                        if offers.get("price"):
                            result["price"] = parse_price(offers["price"])
                        avail = str(offers.get("availability", ""))
                        if "OutOfStock" in avail or "Discontinued" in avail:
                            result["inStock"] = False
                            result["availabilityText"] = "Esgotado"
                        elif "InStock" in avail:
                            result["inStock"] = True
                            result["availabilityText"] = "Em Estoque"

                    if result["price"]:
                        result["status"] = "success"
                        return result
            except Exception:
                continue

        # 2. OpenGraph / Twitter Meta Tags
        og_price = soup.find("meta", property="product:price:amount") or soup.find(
            "meta", attrs={"name": "product:price:amount"}
        )
        if og_price and og_price.get("content"):
            result["price"] = parse_price(og_price["content"])

        if not result["title"]:
            og_title = soup.find("meta", property="og:title")
            if og_title and og_title.get("content"):
                result["title"] = og_title["content"]
            elif soup.find("h1"):
                result["title"] = soup.find("h1").get_text(strip=True)

        if not result["imageUrl"]:
            og_img = soup.find("meta", property="og:image")
            if og_img and og_img.get("content"):
                result["imageUrl"] = og_img["content"]

        # 3. Microdata itemprop
        if not result["price"]:
            price_tag = soup.find(attrs={"itemprop": "price"})
            if price_tag:
                val = price_tag.get("content") or price_tag.get_text(strip=True)
                result["price"] = parse_price(val)

        # 4. Fallback DOM regex for BRL
        if not result["price"]:
            m = re.search(r"R\$[\s\xa0]*([\d\.,]+)", html)
            if m:
                result["price"] = parse_price(m.group(1))

        if any(w in html.upper() for w in ["INDISPONÍVEL", "ESGOTADO", "OUT OF STOCK", "CURRENTLY UNAVAILABLE"]):
            result["inStock"] = False
            result["availabilityText"] = "Esgotado"

        if result["price"]:
            result["status"] = "success"

        return result
