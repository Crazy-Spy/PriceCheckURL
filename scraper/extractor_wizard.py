import os
import sys
import re
import json
import time
import argparse
from typing import Dict, Any, List, Optional
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

INJECTED_OVERLAY_SCRIPT = """
(() => {
    if (window.__PRICECHECK_WIZARD_ACTIVE__) return;
    window.__PRICECHECK_WIZARD_ACTIVE__ = true;

    // State
    const state = {
        step: 1, // 1: title, 2: price, 3: originalPrice, 4: stock, 5: image, 6: done
        title: { selector: '', text: '' },
        price: { selector: '', text: '', numeric: null },
        originalPrice: { selector: '', text: '' },
        stock: { type: 'keywords', selector: '', label: 'Palavras-Chave Universais' },
        image: { selector: '', src: '' }
    };

    // Helper: compute clean CSS selector
    function computeSelector(el) {
        if (!el || el === document.body || el === document.documentElement) return '';
        if (el.id && !el.id.match(/\\d{5,}/) && !el.id.match(/[\\:\\[\\]\\/]/)) {
            return '#' + CSS.escape(el.id);
        }
        const tag = el.tagName.toLowerCase();
        if (tag === 'h1') return 'h1';

        // Check clean classes
        if (el.classList && el.classList.length > 0) {
            const cleanClasses = Array.from(el.classList).filter(c => 
                !c.includes(':') && !c.includes('[') && !c.includes(']') && !c.includes('/') &&
                !c.match(/^css-/) && !c.match(/^[a-z0-9]{10,}$/i)
            );
            // Look for meaningful class names
            const good = cleanClasses.filter(c => 
                /(price|preco|val|tit|prod|amount|final|total|buy|comprar|indisponivel|esgotado)/i.test(c)
            );
            const chosen = good[0] || cleanClasses[0];
            if (chosen) {
                const sel = tag + '.' + CSS.escape(chosen);
                if (document.querySelectorAll(sel).length <= 3) return sel;
            }
        }

        // Parent context
        if (el.parentElement && el.parentElement !== document.body) {
            const parentSel = computeSelector(el.parentElement);
            if (parentSel && !parentSel.includes('>')) {
                return parentSel + ' ' + tag;
            }
        }
        return tag;
    }

    // Create floating UI
    const container = document.createElement('div');
    container.id = '__pc_wizard_container';
    container.innerHTML = `
        <div style="
            position: fixed; top: 12px; left: 50%; transform: translateX(-50%);
            z-index: 2147483647; width: 92%; max-width: 680px;
            background: rgba(11, 15, 25, 0.94); backdrop-filter: blur(12px);
            border: 1px solid rgba(99, 102, 241, 0.4); border-radius: 16px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.6); color: #f3f4f6;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            padding: 14px 18px; user-select: none; transition: all 0.2s ease;
        ">
            <!-- Header -->
            <div style="display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid rgba(255,255,255,0.08); padding-bottom: 8px; margin-bottom: 10px;">
                <div style="display: flex; align-items: center; gap: 8px;">
                    <div style="width: 26px; height: 26px; border-radius: 8px; background: #4f46e5; display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 14px;">🎯</div>
                    <div>
                        <div style="font-size: 13px; font-weight: 700; color: #fff;">PriceCheckURL &bull; Criador Visual de Extrator</div>
                        <div style="font-size: 11px; color: #9ca3af;" id="__pc_domain_label">Identificando loja...</div>
                    </div>
                </div>
                <div id="__pc_step_badge" style="font-size: 11px; font-weight: 600; padding: 3px 8px; border-radius: 20px; background: rgba(99,102,241,0.2); color: #818cf8; border: 1px solid rgba(99,102,241,0.3);">
                    Passo 1 de 5
                </div>
            </div>

            <!-- Instruction Box -->
            <div id="__pc_prompt" style="font-size: 13px; font-weight: 600; color: #38bdf8; margin-bottom: 6px; display: flex; align-items: center; gap: 6px;">
                👉 Passe o mouse e CLIQUE no TÍTULO do produto na página.
            </div>
            <div id="__pc_subprompt" style="font-size: 11px; color: #9ca3af; margin-bottom: 10px;">
                O elemento selecionado receberá uma borda verde ao clicar.
            </div>

            <!-- Stock Options Box (Step 4 only) -->
            <div id="__pc_stock_options" style="display: none; margin-bottom: 12px; gap: 6px; flex-direction: column;">
                <div style="font-size: 11px; color: #cbd5e1; font-weight: 600; margin-bottom: 4px;">Escolha como essa loja indica estoque:</div>
                <button type="button" id="__pc_stock_btn_buy" style="background: #1e293b; border: 1px solid #334155; color: #f1f5f9; padding: 7px 10px; border-radius: 8px; font-size: 11px; text-align: left; cursor: pointer; display: flex; align-items: center; gap: 6px;">
                    🛒 <strong>Opção 1:</strong> Clique no botão COMPRAR (Se sumir na página = Esgotado)
                </button>
                <button type="button" id="__pc_stock_btn_out" style="background: #1e293b; border: 1px solid #334155; color: #f1f5f9; padding: 7px 10px; border-radius: 8px; font-size: 11px; text-align: left; cursor: pointer; display: flex; align-items: center; gap: 6px;">
                    🚫 <strong>Opção 2:</strong> Clique no aviso de ESGOTADO (se o produto atual estiver esgotado)
                </button>
                <button type="button" id="__pc_stock_btn_keywords" style="background: #1e293b; border: 1px solid #334155; color: #f1f5f9; padding: 7px 10px; border-radius: 8px; font-size: 11px; text-align: left; cursor: pointer; display: flex; align-items: center; gap: 6px;">
                    ✨ <strong>Opção 3 (Padrão):</strong> Detecção Automática por Palavras ('Esgotado', 'Indisponível', etc.)
                </button>
            </div>

            <!-- Summary Table of Captured Values -->
            <div id="__pc_summary" style="background: rgba(0,0,0,0.3); border-radius: 10px; padding: 8px 12px; font-size: 11px; margin-bottom: 10px; display: grid; grid-template-columns: 1fr 1fr; gap: 6px;">
                <div><span style="color: #64748b;">Título:</span> <strong id="__pc_val_title" style="color: #e2e8f0;">--</strong></div>
                <div><span style="color: #64748b;">Preço:</span> <strong id="__pc_val_price" style="color: #34d399;">--</strong></div>
                <div><span style="color: #64748b;">Preço Original:</span> <strong id="__pc_val_oldprice" style="color: #94a3b8;">--</strong></div>
                <div><span style="color: #64748b;">Estoque:</span> <strong id="__pc_val_stock" style="color: #60a5fa;">Palavras-Chave</strong></div>
            </div>

            <!-- Action Buttons -->
            <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px;">
                <button type="button" id="__pc_btn_skip" style="background: #1e293b; hover: background: #334155; color: #94a3b8; border: 1px solid #334155; padding: 6px 12px; border-radius: 8px; font-size: 11px; font-weight: 600; cursor: pointer;">
                    Pular este passo
                </button>
                <button type="button" id="__pc_btn_finish" style="background: #10b981; color: #fff; border: none; padding: 7px 16px; border-radius: 8px; font-size: 12px; font-weight: 700; cursor: pointer; display: none;">
                    ✅ Concluir e Salvar Extrator
                </button>
            </div>
        </div>
    `;
    document.body.appendChild(container);

    // Hover Highlight Overlay Box
    const hoverBox = document.createElement('div');
    hoverBox.id = '__pc_hover_box';
    hoverBox.style.cssText = 'position: absolute; pointer-events: none; border: 2px dashed #38bdf8; background: rgba(56, 189, 248, 0.12); z-index: 2147483646; display: none; transition: all 0.05s ease; border-radius: 4px;';
    document.body.appendChild(hoverBox);

    // Selected Elements Highlights
    const selectedHighlights = [];
    function addSelectedHighlight(el, color = '#10b981') {
        const rect = el.getBoundingClientRect();
        const box = document.createElement('div');
        box.style.cssText = `position: absolute; pointer-events: none; border: 3px solid ${color}; background: rgba(16, 185, 129, 0.1); z-index: 2147483645; border-radius: 4px; top: ${rect.top + window.scrollY}px; left: ${rect.left + window.scrollX}px; width: ${rect.width}px; height: ${rect.height}px;`;
        document.body.appendChild(box);
        selectedHighlights.push(box);
    }

    let isSelectingStockButton = false;
    let isSelectingStockOut = false;

    // Hover Event
    document.addEventListener('mouseover', (e) => {
        if (container.contains(e.target) || e.target === hoverBox) return;
        const rect = e.target.getBoundingClientRect();
        hoverBox.style.display = 'block';
        hoverBox.style.top = (rect.top + window.scrollY) + 'px';
        hoverBox.style.left = (rect.left + window.scrollX) + 'px';
        hoverBox.style.width = rect.width + 'px';
        hoverBox.style.height = rect.height + 'px';
    }, true);

    // Click Event (Intercept all clicks on page elements)
    document.addEventListener('click', (e) => {
        if (container.contains(e.target)) return;
        e.preventDefault();
        e.stopPropagation();

        const el = e.target;
        const sel = computeSelector(el);
        const text = el.innerText ? el.innerText.trim() : '';

        if (state.step === 1) {
            // STEP 1: TITLE
            state.title = { selector: sel, text: text.substring(0, 80) };
            document.getElementById('__pc_val_title').innerText = state.title.text;
            addSelectedHighlight(el);
            goToStep(2);
        } else if (state.step === 2) {
            // STEP 2: PRICE
            state.price = { selector: sel, text: text.substring(0, 30) };
            document.getElementById('__pc_val_price').innerText = state.price.text;
            addSelectedHighlight(el);
            goToStep(3);
        } else if (state.step === 3) {
            // STEP 3: ORIGINAL PRICE
            state.originalPrice = { selector: sel, text: text.substring(0, 30) };
            document.getElementById('__pc_val_oldprice').innerText = state.originalPrice.text;
            addSelectedHighlight(el, '#94a3b8');
            goToStep(4);
        } else if (state.step === 4) {
            // STEP 4: STOCK SELECTION
            if (isSelectingStockButton) {
                state.stock = { type: 'inStockSelector', selector: sel, label: 'Botão Comprar (' + sel + ')' };
                document.getElementById('__pc_val_stock').innerText = 'Botão Comprar';
                addSelectedHighlight(el, '#60a5fa');
                isSelectingStockButton = false;
                goToStep(5);
            } else if (isSelectingStockOut) {
                state.stock = { type: 'outOfStockSelector', selector: sel, label: 'Selo Esgotado (' + sel + ')' };
                document.getElementById('__pc_val_stock').innerText = 'Selo Esgotado';
                addSelectedHighlight(el, '#ef4444');
                isSelectingStockOut = false;
                goToStep(5);
            }
        } else if (state.step === 5) {
            // STEP 5: IMAGE
            const src = el.tagName.toLowerCase() === 'img' ? el.src : (el.querySelector('img') ? el.querySelector('img').src : '');
            state.image = { selector: sel, src: src };
            addSelectedHighlight(el);
            goToStep(6);
        }
    }, true);

    function goToStep(s) {
        state.step = s;
        const prompt = document.getElementById('__pc_prompt');
        const subprompt = document.getElementById('__pc_subprompt');
        const badge = document.getElementById('__pc_step_badge');
        const stockOpts = document.getElementById('__pc_stock_options');
        const skipBtn = document.getElementById('__pc_btn_skip');
        const finishBtn = document.getElementById('__pc_btn_finish');

        badge.innerText = `Passo ${s} de 5`;
        stockOpts.style.display = 'none';
        isSelectingStockButton = false;
        isSelectingStockOut = false;

        if (s === 2) {
            prompt.innerHTML = '💰 Clique no PREÇO À VISTA / PIX na tela.';
            subprompt.innerText = 'Ex: R$ 2.229,99 (o sistema extrai o valor numérico automaticamente).';
            skipBtn.style.display = 'none';
        } else if (s === 3) {
            prompt.innerHTML = '🏷️ Clique no PREÇO ORIGINAL/PARCELADO (ou pule este passo).';
            subprompt.innerText = 'Ex: Preço de tabela ou parcelado no cartão.';
            skipBtn.style.display = 'inline-block';
        } else if (s === 4) {
            prompt.innerHTML = '📦 Como essa loja indica DISPONIBILIDADE/ESTOQUE?';
            subprompt.innerText = 'Escolha uma das opções abaixo para garantir que o sistema detecte quando esgotar.';
            stockOpts.style.display = 'flex';
            skipBtn.style.display = 'inline-block';
            skipBtn.innerText = 'Usar Palavras-chave Universais (Padrão)';
        } else if (s === 5) {
            prompt.innerHTML = '🖼️ Clique na IMAGEM principal do produto (ou pule este passo).';
            subprompt.innerText = 'Usado para exibir foto miniatura do produto nos cards.';
            skipBtn.style.display = 'inline-block';
            skipBtn.innerText = 'Pular este passo';
        } else if (s >= 6) {
            prompt.innerHTML = '🎉 Extrator Pronto! Tudo capturado com sucesso.';
            subprompt.innerText = 'Clique no botão verde abaixo para gravar a regra da loja.';
            skipBtn.style.display = 'none';
            finishBtn.style.display = 'inline-block';
            hoverBox.style.display = 'none';
        }
    }

    // Step 4 buttons handlers
    document.getElementById('__pc_stock_btn_buy').onclick = (e) => {
        e.stopPropagation();
        isSelectingStockButton = true;
        document.getElementById('__pc_prompt').innerHTML = '🛒 Agora clique no BOTÃO COMPRAR na página.';
        document.getElementById('__pc_subprompt').innerText = 'Quando este botão sumir em checagens futuras, o produto será marcado como Esgotado.';
        document.getElementById('__pc_stock_options').style.display = 'none';
    };

    document.getElementById('__pc_stock_btn_out').onclick = (e) => {
        e.stopPropagation();
        isSelectingStockOut = true;
        document.getElementById('__pc_prompt').innerHTML = '🚫 Clique no elemento de ESGOTADO / INDISPONÍVEL.';
        document.getElementById('__pc_subprompt').innerText = 'Sempre que este elemento aparecer, o produto será marcado como Esgotado.';
        document.getElementById('__pc_stock_options').style.display = 'none';
    };

    document.getElementById('__pc_stock_btn_keywords').onclick = (e) => {
        e.stopPropagation();
        state.stock = { type: 'keywords', label: 'Palavras-Chave Universais' };
        document.getElementById('__pc_val_stock').innerText = 'Palavras-Chave';
        goToStep(5);
    };

    document.getElementById('__pc_btn_skip').onclick = (e) => {
        e.stopPropagation();
        if (state.step === 3) goToStep(4);
        else if (state.step === 4) {
            state.stock = { type: 'keywords', label: 'Palavras-Chave Universais' };
            goToStep(5);
        } else if (state.step === 5) goToStep(6);
    };

    document.getElementById('__pc_btn_finish').onclick = (e) => {
        e.stopPropagation();
        if (window.__onVisualExtractorFinished) {
            window.__onVisualExtractorFinished(JSON.stringify(state));
        }
    };
})();
"""

def launch_visual_wizard(url: str) -> None:
    print("\n" + "=" * 65)
    print("   PRICECHECKURL - CRIADOR VISUAL DE EXTRATORES (POINT-AND-CLICK)")
    print("=" * 65)
    print(f"[*] Abrindo navegador para: {url}")
    print("[*] Aguarde o carregamento da página...")

    domain = get_domain(url)
    engine = ScraperEngine()
    store_name = domain.split(".")[0].capitalize()

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        # Launch real Chrome browser with UI
        browser = engine._get_playwright_browser(p, headless=False)
        if not browser:
            print("[X] Erro: Não foi possível abrir o navegador na máquina.")
            return

        context = browser.new_context(
            viewport={"width": 1366, "height": 850},
            locale="pt-BR"
        )
        page = context.new_page()

        captured_data = {}
        finish_flag = {"done": False}

        def on_finished(json_str: str):
            nonlocal captured_data
            try:
                captured_data = json.loads(json_str)
                finish_flag["done"] = True
            except Exception as e:
                print(f"[!] Erro ao decodificar dados: {e}")

        page.expose_function("__onVisualExtractorFinished", on_finished)

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
        except Exception as e:
            print(f"[!] Aviso durante carregamento da página: {e}")

        # Inject visual inspector overlay
        page.evaluate(INJECTED_OVERLAY_SCRIPT)
        # Update domain label
        page.evaluate(f"() => {{ document.getElementById('__pc_domain_label').innerText = 'Loja: {store_name} ({domain})'; }}")

        print("\n" + "-" * 60)
        print(">> O NAVEGADOR ESTÁ ABERTO NA SUA TELA!")
        print(">> Siga os passos na barra superior no topo da janela:")
        print("   1. Clique no TÍTULO do produto")
        print("   2. Clique no PREÇO À VISTA / PIX")
        print("   3. Clique no PREÇO ANTIGO (ou Pular)")
        print("   4. Escolha a REGRA DE ESTOQUE (Botão Comprar ou Palavras-chave)")
        print("   5. Clique em CONCLUIR E SALVAR")
        print("-" * 60 + "\n")

        # Wait until user finishes interacting with the overlay
        while not finish_flag["done"]:
            page.wait_for_timeout(500)
            if page.is_closed():
                print("[!] Janela do navegador foi fechada pelo usuário.")
                break

        browser.close()

    if not captured_data or not captured_data.get("price", {}).get("selector"):
        print("[!] Nenhum extrator gravado ou processo cancelado.")
        return

    # Build new declarative extractor object
    title_info = captured_data.get("title", {})
    price_info = captured_data.get("price", {})
    oldprice_info = captured_data.get("originalPrice", {})
    stock_info = captured_data.get("stock", {})
    img_info = captured_data.get("image", {})

    new_extractor = {
        "id": domain.replace(".", "_"),
        "name": store_name,
        "domains": [domain],
        "driver": "browser", # Use browser for guaranteed Cloudflare bypass
        "rules": {
            "title": {
                "selector": title_info.get("selector") or "h1",
                "fallback": "meta[property='og:title']"
            },
            "price": {
                "selector": price_info.get("selector") or ".val-prod",
                "regex": "R\\$\\s*([\\d\\.,]+)"
            },
            "inStock": {
                "outOfStockKeywords": ["ESGOTADO", "INDISPONÍVEL", "OUT OF STOCK", "AVISE-ME", "SEM ESTOQUE"]
            }
        }
    }

    # Stock configuration
    stock_type = stock_info.get("type")
    if stock_type == "inStockSelector" and stock_info.get("selector"):
        new_extractor["rules"]["inStock"]["inStockSelector"] = stock_info["selector"]
    elif stock_type == "outOfStockSelector" and stock_info.get("selector"):
        new_extractor["rules"]["inStock"]["outOfStockSelector"] = stock_info["selector"]

    if oldprice_info.get("selector"):
        new_extractor["rules"]["originalPrice"] = {
            "selector": oldprice_info["selector"],
            "regex": "R\\$\\s*([\\d\\.,]+)"
        }

    if img_info.get("selector"):
        new_extractor["rules"]["image"] = {
            "selector": img_info["selector"],
            "attribute": "src"
        }

    # Save to extractors.json
    saved = engine.save_extractor(new_extractor)
    if saved:
        print("\n" + "=" * 60)
        print(f"[OK] EXTRATOR VISUAL SALVO COM SUCESSO PARA A LOJA: {store_name} ({domain})!")
        print(f"  - Seletor do Título: {new_extractor['rules']['title']['selector']}")
        print(f"  - Seletor do Preço : {new_extractor['rules']['price']['selector']}")
        if "inStockSelector" in new_extractor["rules"]["inStock"]:
            print(f"  - Regra de Estoque : Presença do botão ({new_extractor['rules']['inStock']['inStockSelector']})")
        else:
            print("  - Regra de Estoque : Palavras-chave universais")
        print("=" * 60)
        print(f"\nAgora, qualquer link de {domain} no PriceCheckURL usará automaticamente essas regras!")
    else:
        print("[X] Erro ao gravar extractors.json.")

def main():
    parser = argparse.ArgumentParser(description="Criador Visual Inteligente de Extratores (Point-and-Click).")
    parser.add_argument("url", nargs="?", help="URL do produto na loja para inspecionar")
    parser.add_argument("--auto", action="store_true", help="Gera extrator automaticamente em modo headless sem interface")
    args = parser.parse_args()

    url = args.url
    if not url:
        print("Informe a URL do produto que deseja mapear:")
        url = input("URL: ").strip()

    if not url:
        print("URL vazia. Encerrando.")
        sys.exit(1)

    if args.auto:
        # Non-interactive mode
        from .engine import ScraperEngine
        engine = ScraperEngine()
        domain = get_domain(url)
        store_name = domain.split(".")[0].capitalize()
        html = engine.fetch_html(url, driver="browser")
        parsed = engine.parse(html, url)
        new_extractor = {
            "id": domain.replace(".", "_"),
            "name": store_name,
            "domains": [domain],
            "driver": "browser",
            "rules": {
                "title": { "selector": "h1", "fallback": "meta[property='og:title']" },
                "price": { "selector": "meta[property='product:price:amount'], .val-prod, .price", "regex": "R\\$\\s*([\\d\\.,]+)" },
                "inStock": { "outOfStockKeywords": ["ESGOTADO", "INDISPONÍVEL", "AVISE-ME"] }
            }
        }
        engine.save_extractor(new_extractor)
        print(f"[OK] Extrator para '{domain}' salvo em modo --auto.")
    else:
        launch_visual_wizard(url)

if __name__ == "__main__":
    main()
