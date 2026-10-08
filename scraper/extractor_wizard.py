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

    let selectionMode = false; // Starts in browse/interact mode so user can close popups first!
    let pendingElement = null;
    let pendingData = null;
    let isMinimized = false;

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
                if (document.querySelectorAll(sel).length <= 4) return sel;
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

    // Helper: extract price numbers
    function extractPriceText(text) {
        if (!text) return '';
        const m = text.match(/R\\$[\\s\\xa0]*[\\d\\.,]+/i) || text.match(/[\\d]+[\\.,][\\d]{2}/);
        return m ? m[0] : text.substring(0, 25);
    }

    // Create floating UI
    const container = document.createElement('div');
    container.id = '__pc_wizard_container';
    container.innerHTML = `
        <div id="__pc_panel" style="
            position: fixed; top: 16px; left: 50%; transform: translateX(-50%);
            z-index: 2147483647; width: 92%; max-width: 660px;
            background: rgba(11, 15, 25, 0.96); backdrop-filter: blur(14px);
            border: 1px solid rgba(99, 102, 241, 0.45); border-radius: 16px;
            box-shadow: 0 20px 50px rgba(0,0,0,0.7); color: #f3f4f6;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            padding: 14px 18px; user-select: none; transition: box-shadow 0.2s ease;
        ">
            <!-- Header (Draggable) -->
            <div id="__pc_drag_handle" style="display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid rgba(255,255,255,0.08); padding-bottom: 8px; margin-bottom: 10px; cursor: move;">
                <div style="display: flex; align-items: center; gap: 8px;">
                    <div style="width: 26px; height: 26px; border-radius: 8px; background: #4f46e5; display: flex; align-items: center; justify-content: center; font-weight: bold; font-size: 13px;">🎯</div>
                    <div>
                        <div style="font-size: 13px; font-weight: 700; color: #fff; display: flex; align-items: center; gap: 6px;">
                            <span>PriceCheckURL &bull; Extrator Visual</span>
                            <span style="font-size: 10px; color: #94a3b8; font-weight: 400;">(Arraste para mover)</span>
                        </div>
                        <div style="font-size: 11px; color: #818cf8;" id="__pc_domain_label">Identificando loja...</div>
                    </div>
                </div>
                <div style="display: flex; align-items: center; gap: 6px;">
                    <div id="__pc_step_badge" style="font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 20px; background: rgba(99,102,241,0.2); color: #a5b4fc; border: 1px solid rgba(99,102,241,0.3);">
                        Passo 1 de 5
                    </div>
                    <button type="button" id="__pc_btn_minimize" title="Minimizar janela" style="background: rgba(255,255,255,0.08); border: none; color: #94a3b8; border-radius: 6px; width: 22px; height: 22px; cursor: pointer; font-size: 13px; display: flex; align-items: center; justify-content: center;">
                        &minus;
                    </button>
                </div>
            </div>

            <!-- Content Area (Can collapse when minimized) -->
            <div id="__pc_content_area">
                <!-- Mode Toggle Banner (Allow closing popups and cookies freely) -->
                <div style="display: flex; align-items: center; justify-content: space-between; background: rgba(30, 41, 59, 0.7); border: 1px solid rgba(71, 85, 105, 0.4); border-radius: 10px; padding: 6px 10px; margin-bottom: 10px;">
                    <div style="font-size: 11px; color: #cbd5e1; display: flex; align-items: center; gap: 6px;">
                        <span id="__pc_mode_status_icon" style="width: 8px; height: 8px; border-radius: 50%; background: #f59e0b; display: inline-block;"></span>
                        <span id="__pc_mode_status_text">Modo Navegar: feche pop-ups ou cookies livremente</span>
                    </div>
                    <button type="button" id="__pc_btn_mode_toggle" style="background: #4f46e5; color: #fff; border: none; padding: 5px 12px; border-radius: 8px; font-size: 11px; font-weight: 600; cursor: pointer; transition: all 0.2s;">
                        🎯 Iniciar Seleção do Título
                    </button>
                </div>

                <!-- Instruction Box -->
                <div id="__pc_prompt" style="font-size: 13px; font-weight: 600; color: #38bdf8; margin-bottom: 4px; display: flex; align-items: center; gap: 6px;">
                    👉 Feche eventuais pop-ups da loja e clique em "Iniciar Seleção" acima.
                </div>
                <div id="__pc_subprompt" style="font-size: 11px; color: #9ca3af; margin-bottom: 10px;">
                    Quando ativar o modo seleção, basta clicar no elemento desejado na página.
                </div>

                <!-- Confirmation Box (Appears after user clicks an element) -->
                <div id="__pc_confirm_box" style="display: none; background: rgba(16, 185, 129, 0.12); border: 1px solid rgba(16, 185, 129, 0.35); border-radius: 12px; padding: 10px 14px; margin-bottom: 12px;">
                    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px;">
                        <span style="font-size: 12px; font-weight: 700; color: #34d399; display: flex; align-items: center; gap: 5px;">
                            <span>✨</span> Elemento Selecionado
                        </span>
                        <code id="__pc_confirm_selector" style="font-size: 11px; color: #a7f3d0; background: rgba(0,0,0,0.4); padding: 2px 6px; border-radius: 6px;">--</code>
                    </div>
                    <div id="__pc_confirm_text" style="font-size: 12px; color: #f1f5f9; font-weight: 500; margin-bottom: 10px; max-height: 48px; overflow: hidden; text-overflow: ellipsis;">
                        --
                    </div>
                    <div style="display: flex; align-items: center; gap: 8px;">
                        <button type="button" id="__pc_btn_confirm_ok" style="flex: 1; background: #10b981; color: #fff; border: none; padding: 7px 12px; border-radius: 8px; font-size: 11px; font-weight: 700; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 4px;">
                            ✅ Confirmar este Elemento
                        </button>
                        <button type="button" id="__pc_btn_confirm_retry" style="background: rgba(239, 68, 68, 0.15); color: #fca5a5; border: 1px solid rgba(239, 68, 68, 0.3); padding: 7px 12px; border-radius: 8px; font-size: 11px; font-weight: 600; cursor: pointer;">
                            🔄 Escolher Outro
                        </button>
                    </div>
                </div>

                <!-- Stock Options Box (Step 4 only) -->
                <div id="__pc_stock_options" style="display: none; margin-bottom: 12px; gap: 6px; flex-direction: column;">
                    <div style="font-size: 11px; color: #cbd5e1; font-weight: 600; margin-bottom: 4px;">Como essa loja indica estoque?</div>
                    <button type="button" id="__pc_stock_btn_buy" style="background: #1e293b; border: 1px solid #334155; color: #f1f5f9; padding: 7px 10px; border-radius: 8px; font-size: 11px; text-align: left; cursor: pointer; display: flex; align-items: center; gap: 6px;">
                        🛒 <strong>Opção 1:</strong> O botão COMPRAR só existe quando há estoque (clique nele na página)
                    </button>
                    <button type="button" id="__pc_stock_btn_out" style="background: #1e293b; border: 1px solid #334155; color: #f1f5f9; padding: 7px 10px; border-radius: 8px; font-size: 11px; text-align: left; cursor: pointer; display: flex; align-items: center; gap: 6px;">
                        🚫 <strong>Opção 2:</strong> A loja exibe um aviso quando ESGOTADO (clique no aviso na página)
                    </button>
                    <button type="button" id="__pc_stock_btn_keywords" style="background: #1e293b; border: 1px solid #334155; color: #f1f5f9; padding: 7px 10px; border-radius: 8px; font-size: 11px; text-align: left; cursor: pointer; display: flex; align-items: center; gap: 6px;">
                        ✨ <strong>Opção 3 (Padrão):</strong> Detecção Automática por Palavras ('Esgotado', 'Indisponível', etc.)
                    </button>
                </div>

                <!-- Summary Table of Captured Values -->
                <div id="__pc_summary" style="background: rgba(0,0,0,0.35); border-radius: 10px; padding: 8px 12px; font-size: 11px; margin-bottom: 10px; display: grid; grid-template-columns: 1fr 1fr; gap: 6px;">
                    <div><span style="color: #64748b;">Título:</span> <strong id="__pc_val_title" style="color: #e2e8f0;">--</strong></div>
                    <div><span style="color: #64748b;">Preço:</span> <strong id="__pc_val_price" style="color: #34d399;">--</strong></div>
                    <div><span style="color: #64748b;">Preço Original:</span> <strong id="__pc_val_oldprice" style="color: #94a3b8;">--</strong></div>
                    <div><span style="color: #64748b;">Estoque:</span> <strong id="__pc_val_stock" style="color: #60a5fa;">Palavras-Chave</strong></div>
                </div>

                <!-- Footer Navigation Buttons -->
                <div style="display: flex; align-items: center; justify-content: space-between; gap: 8px;">
                    <div style="display: flex; gap: 6px;">
                        <button type="button" id="__pc_btn_back" style="display: none; background: rgba(255,255,255,0.06); color: #94a3b8; border: 1px solid rgba(255,255,255,0.1); padding: 6px 10px; border-radius: 8px; font-size: 11px; font-weight: 600; cursor: pointer;">
                            &larr; Voltar
                        </button>
                        <button type="button" id="__pc_btn_skip" style="background: #1e293b; color: #94a3b8; border: 1px solid #334155; padding: 6px 12px; border-radius: 8px; font-size: 11px; font-weight: 600; cursor: pointer; display: none;">
                            Pular este passo
                        </button>
                    </div>
                    <button type="button" id="__pc_btn_finish" style="background: #10b981; color: #fff; border: none; padding: 8px 18px; border-radius: 8px; font-size: 12px; font-weight: 700; cursor: pointer; display: none; box-shadow: 0 4px 12px rgba(16,185,129,0.3);">
                        ✅ Concluir e Salvar Extrator
                    </button>
                </div>
            </div>
        </div>
    `;
    document.body.appendChild(container);

    const panel = document.getElementById('__pc_panel');
    const dragHandle = document.getElementById('__pc_drag_handle');
    const contentArea = document.getElementById('__pc_content_area');
    const minimizeBtn = document.getElementById('__pc_btn_minimize');
    const modeBtn = document.getElementById('__pc_btn_mode_toggle');
    const modeStatusIcon = document.getElementById('__pc_mode_status_icon');
    const modeStatusText = document.getElementById('__pc_mode_status_text');
    const confirmBox = document.getElementById('__pc_confirm_box');
    const confirmSelectorEl = document.getElementById('__pc_confirm_selector');
    const confirmTextEl = document.getElementById('__pc_confirm_text');

    // 1. DRAG AND DROP MECHANISM
    let isDragging = false;
    let dragStartX = 0, dragStartY = 0, initialLeft = 0, initialTop = 0;

    dragHandle.addEventListener('mousedown', (e) => {
        if (e.target.tagName === 'BUTTON') return;
        isDragging = true;
        dragStartX = e.clientX;
        dragStartY = e.clientY;
        const rect = panel.getBoundingClientRect();
        initialLeft = rect.left;
        initialTop = rect.top;
        panel.style.transform = 'none';
        panel.style.left = initialLeft + 'px';
        panel.style.top = initialTop + 'px';
        e.preventDefault();
    });

    window.addEventListener('mousemove', (e) => {
        if (!isDragging) return;
        const deltaX = e.clientX - dragStartX;
        const deltaY = e.clientY - dragStartY;
        const newLeft = Math.max(10, Math.min(window.innerWidth - panel.offsetWidth - 10, initialLeft + deltaX));
        const newTop = Math.max(10, Math.min(window.innerHeight - panel.offsetHeight - 10, initialTop + deltaY));
        panel.style.left = newLeft + 'px';
        panel.style.top = newTop + 'px';
    });

    window.addEventListener('mouseup', () => {
        isDragging = false;
    });

    // 2. MINIMIZE TOGGLE
    minimizeBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        isMinimized = !isMinimized;
        if (isMinimized) {
            contentArea.style.display = 'none';
            panel.style.padding = '8px 14px';
            minimizeBtn.innerHTML = '&plus;';
            dragHandle.style.marginBottom = '0';
            dragHandle.style.borderBottom = 'none';
        } else {
            contentArea.style.display = 'block';
            panel.style.padding = '14px 18px';
            minimizeBtn.innerHTML = '&minus;';
            dragHandle.style.marginBottom = '10px';
            dragHandle.style.borderBottom = '1px solid rgba(255,255,255,0.08)';
        }
    });

    // 3. HOVER HIGHLIGHT BOX
    const hoverBox = document.createElement('div');
    hoverBox.id = '__pc_hover_box';
    hoverBox.style.cssText = 'position: absolute; pointer-events: none; border: 2px dashed #38bdf8; background: rgba(56, 189, 248, 0.12); z-index: 2147483646; display: none; transition: all 0.05s ease; border-radius: 4px;';
    document.body.appendChild(hoverBox);

    // Pending Selection Highlight Box
    const pendingHighlightBox = document.createElement('div');
    pendingHighlightBox.id = '__pc_pending_box';
    pendingHighlightBox.style.cssText = 'position: absolute; pointer-events: none; border: 3px solid #10b981; background: rgba(16, 185, 129, 0.15); z-index: 2147483645; display: none; border-radius: 4px; box-shadow: 0 0 15px rgba(16,185,129,0.4);';
    document.body.appendChild(pendingHighlightBox);

    function highlightElement(el, targetBox) {
        if (!el) {
            targetBox.style.display = 'none';
            return;
        }
        const rect = el.getBoundingClientRect();
        targetBox.style.display = 'block';
        targetBox.style.top = (rect.top + window.scrollY) + 'px';
        targetBox.style.left = (rect.left + window.scrollX) + 'px';
        targetBox.style.width = rect.width + 'px';
        targetBox.style.height = rect.height + 'px';
    }

    // 4. MODE TOGGLE (SELECTION vs BROWSING/POPUPS)
    function setSelectionMode(enabled) {
        selectionMode = enabled;
        if (enabled) {
            modeStatusIcon.style.background = '#10b981';
            modeStatusText.innerHTML = '<strong style="color:#34d399">Modo Seleção Ativo:</strong> passe o mouse e clique no elemento';
            modeBtn.innerHTML = '⏸️ Pausar (Fechar Pop-ups)';
            modeBtn.style.background = '#334155';
            modeBtn.style.color = '#cbd5e1';
            updatePromptsForStep();
        } else {
            modeStatusIcon.style.background = '#f59e0b';
            modeStatusText.innerHTML = '<strong style="color:#fbbf24">Modo Navegar:</strong> você pode clicar para fechar pop-ups normalmente';
            modeBtn.innerHTML = '🎯 Iniciar Seleção';
            modeBtn.style.background = '#4f46e5';
            modeBtn.style.color = '#fff';
            hoverBox.style.display = 'none';
        }
    }

    modeBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        setSelectionMode(!selectionMode);
    });

    // 5. HOVER LISTENER (only when selectionMode is true)
    document.addEventListener('mouseover', (e) => {
        if (!selectionMode) return;
        if (panel.contains(e.target) || e.target === hoverBox || e.target === pendingHighlightBox) return;
        highlightElement(e.target, hoverBox);
    }, true);

    // 6. CLICK INTERCEPTOR
    let isSelectingStockButton = false;
    let isSelectingStockOut = false;

    document.addEventListener('click', (e) => {
        if (panel.contains(e.target)) return;

        // If in browse mode, let user click naturally to close modals/cookies!
        if (!selectionMode) return;

        // Selection mode: intercept click!
        e.preventDefault();
        e.stopPropagation();

        const el = e.target;
        const sel = computeSelector(el);
        const text = el.innerText ? el.innerText.trim() : (el.value || '');

        pendingElement = el;
        highlightElement(el, pendingHighlightBox);
        hoverBox.style.display = 'none';

        if (state.step === 1) {
            // STEP 1: TITLE
            pendingData = { selector: sel, text: text.substring(0, 90) };
            confirmSelectorEl.innerText = sel;
            confirmTextEl.innerText = `Título: "${pendingData.text}"`;
            confirmBox.style.display = 'block';
        } else if (state.step === 2) {
            // STEP 2: PRICE
            const pClean = extractPriceText(text);
            pendingData = { selector: sel, text: pClean };
            confirmSelectorEl.innerText = sel;
            confirmTextEl.innerText = `Preço identificado: "${pClean}"`;
            confirmBox.style.display = 'block';
        } else if (state.step === 3) {
            // STEP 3: ORIGINAL PRICE
            const pClean = extractPriceText(text);
            pendingData = { selector: sel, text: pClean };
            confirmSelectorEl.innerText = sel;
            confirmTextEl.innerText = `Preço original/tabela: "${pClean}"`;
            confirmBox.style.display = 'block';
        } else if (state.step === 4) {
            // STEP 4: STOCK SELECTION
            if (isSelectingStockButton) {
                pendingData = { type: 'inStockSelector', selector: sel, label: 'Botão Comprar (' + sel + ')' };
                confirmSelectorEl.innerText = sel;
                confirmTextEl.innerText = `Botão de Compra: "${text.substring(0, 40) || sel}" (Se sumir = Esgotado)`;
                confirmBox.style.display = 'block';
            } else if (isSelectingStockOut) {
                pendingData = { type: 'outOfStockSelector', selector: sel, label: 'Aviso Esgotado (' + sel + ')' };
                confirmSelectorEl.innerText = sel;
                confirmTextEl.innerText = `Aviso de Indisponível: "${text.substring(0, 40) || sel}"`;
                confirmBox.style.display = 'block';
            }
        } else if (state.step === 5) {
            // STEP 5: IMAGE
            const src = el.tagName.toLowerCase() === 'img' ? el.src : (el.querySelector('img') ? el.querySelector('img').src : '');
            pendingData = { selector: sel, src: src };
            confirmSelectorEl.innerText = sel;
            confirmTextEl.innerText = src ? `Imagem do produto: ${src.substring(0, 50)}...` : `Elemento de Imagem: ${sel}`;
            confirmBox.style.display = 'block';
        }
    }, true);

    // CONFIRM BUTTON: User validates the chosen element!
    document.getElementById('__pc_btn_confirm_ok').addEventListener('click', (e) => {
        e.stopPropagation();
        if (!pendingData) return;

        confirmBox.style.display = 'none';
        pendingHighlightBox.style.display = 'none';

        if (state.step === 1) {
            state.title = pendingData;
            document.getElementById('__pc_val_title').innerText = state.title.text;
            goToStep(2);
        } else if (state.step === 2) {
            state.price = pendingData;
            document.getElementById('__pc_val_price').innerText = state.price.text;
            goToStep(3);
        } else if (state.step === 3) {
            state.originalPrice = pendingData;
            document.getElementById('__pc_val_oldprice').innerText = state.originalPrice.text;
            goToStep(4);
        } else if (state.step === 4) {
            state.stock = pendingData;
            document.getElementById('__pc_val_stock').innerText = state.stock.label;
            isSelectingStockButton = false;
            isSelectingStockOut = false;
            goToStep(5);
        } else if (state.step === 5) {
            state.image = pendingData;
            goToStep(6);
        }

        pendingElement = null;
        pendingData = null;
    });

    // RETRY BUTTON: User wants to pick another element
    document.getElementById('__pc_btn_confirm_retry').addEventListener('click', (e) => {
        e.stopPropagation();
        confirmBox.style.display = 'none';
        pendingHighlightBox.style.display = 'none';
        pendingElement = null;
        pendingData = null;
    });

    function updatePromptsForStep() {
        const prompt = document.getElementById('__pc_prompt');
        const subprompt = document.getElementById('__pc_subprompt');
        const s = state.step;

        if (s === 1) {
            prompt.innerHTML = '👉 Passe o mouse e clique no TÍTULO do produto.';
            subprompt.innerText = 'Ao clicar, confira a confirmação na janela antes de avançar.';
        } else if (s === 2) {
            prompt.innerHTML = '💰 Clique no PREÇO À VISTA / PIX na página.';
            subprompt.innerText = 'Ex: R$ 2.229,99 (o sistema extrai o valor numérico após sua confirmação).';
        } else if (s === 3) {
            prompt.innerHTML = '🏷️ Clique no PREÇO ORIGINAL/DE (ou pule este passo).';
            subprompt.innerText = 'Usado para comparar descontos. Se não houver, clique em "Pular".';
        } else if (s === 4) {
            prompt.innerHTML = '📦 Como essa loja indica DISPONIBILIDADE/ESTOQUE?';
            subprompt.innerText = 'Escolha uma das 3 opções abaixo:';
        } else if (s === 5) {
            prompt.innerHTML = '🖼️ Clique na IMAGEM principal do produto (ou pule este passo).';
            subprompt.innerText = 'A imagem aparecerá no card do produto no painel.';
        } else if (s >= 6) {
            prompt.innerHTML = '🎉 Extrator Pronto! Tudo capturado com sucesso.';
            subprompt.innerText = 'Clique no botão verde abaixo para salvar as regras da loja.';
        }
    }

    function goToStep(s) {
        state.step = s;
        const badge = document.getElementById('__pc_step_badge');
        const stockOpts = document.getElementById('__pc_stock_options');
        const backBtn = document.getElementById('__pc_btn_back');
        const skipBtn = document.getElementById('__pc_btn_skip');
        const finishBtn = document.getElementById('__pc_btn_finish');

        badge.innerText = `Passo ${s} de 5`;
        stockOpts.style.display = 'none';
        confirmBox.style.display = 'none';
        pendingHighlightBox.style.display = 'none';
        isSelectingStockButton = false;
        isSelectingStockOut = false;

        backBtn.style.display = (s > 1 && s <= 5) ? 'inline-block' : 'none';

        if (s === 2) {
            skipBtn.style.display = 'none';
            setSelectionMode(true);
        } else if (s === 3) {
            skipBtn.style.display = 'inline-block';
            skipBtn.innerText = 'Pular este passo';
            setSelectionMode(true);
        } else if (s === 4) {
            stockOpts.style.display = 'flex';
            skipBtn.style.display = 'none';
            setSelectionMode(false); // In step 4 user chooses an option first
        } else if (s === 5) {
            skipBtn.style.display = 'inline-block';
            skipBtn.innerText = 'Pular este passo';
            setSelectionMode(true);
        } else if (s >= 6) {
            skipBtn.style.display = 'none';
            finishBtn.style.display = 'inline-block';
            setSelectionMode(false);
            hoverBox.style.display = 'none';
        }

        updatePromptsForStep();
    }

    // Step 4 Buttons
    document.getElementById('__pc_stock_btn_buy').onclick = (e) => {
        e.stopPropagation();
        isSelectingStockButton = true;
        setSelectionMode(true);
        document.getElementById('__pc_prompt').innerHTML = '🛒 Agora clique no BOTÃO COMPRAR na página.';
        document.getElementById('__pc_subprompt').innerText = 'Quando este botão sumir em checagens futuras, o produto será considerado Esgotado.';
        document.getElementById('__pc_stock_options').style.display = 'none';
    };

    document.getElementById('__pc_stock_btn_out').onclick = (e) => {
        e.stopPropagation();
        isSelectingStockOut = true;
        setSelectionMode(true);
        document.getElementById('__pc_prompt').innerHTML = '🚫 Clique no elemento de ESGOTADO / INDISPONÍVEL.';
        document.getElementById('__pc_subprompt').innerText = 'Sempre que este elemento aparecer na página, o produto será marcado como Esgotado.';
        document.getElementById('__pc_stock_options').style.display = 'none';
    };

    document.getElementById('__pc_stock_btn_keywords').onclick = (e) => {
        e.stopPropagation();
        state.stock = { type: 'keywords', label: 'Palavras-Chave Universais' };
        document.getElementById('__pc_val_stock').innerText = 'Palavras-Chave';
        goToStep(5);
    };

    // Back & Skip
    document.getElementById('__pc_btn_back').onclick = (e) => {
        e.stopPropagation();
        if (state.step > 1) {
            goToStep(state.step - 1);
        }
    };

    document.getElementById('__pc_btn_skip').onclick = (e) => {
        e.stopPropagation();
        if (state.step === 3) goToStep(4);
        else if (state.step === 5) goToStep(6);
    };

    // Finish
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
        print(">> NOVIDADES:")
        print("   1. ARRASTE A JANELA: Você pode clicar e arrastar a barra superior para qualquer lugar da tela!")
        print("   2. FECHAR POP-UPS: Começa no Modo Navegar para você fechar cookies/popups livremente.")
        print("   3. CONFIRMAÇÃO: Cada clique mostra o seletor e pede sua confirmação antes de avançar.")
        print("   4. VOLTAR: Botão para voltar ao passo anterior a qualquer momento.")
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
        elif "outOfStockSelector" in new_extractor["rules"]["inStock"]:
            print(f"  - Regra de Estoque : Presença do aviso ({new_extractor['rules']['inStock']['outOfStockSelector']})")
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
        from .engine import ScraperEngine
        engine = ScraperEngine()
        domain = get_domain(url)
        store_name = domain.split(".")[0].capitalize()
        html = engine.fetch_html(url, driver="browser")
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
