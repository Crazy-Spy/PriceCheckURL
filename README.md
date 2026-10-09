# PriceCheckURL 🚀

> **Monitor inteligente de preços e estoque de e-commerces com painel interativo no GitHub Pages, automação serverless via GitHub Actions e Extrator Studio Inteligente.**

[![Price Check & Auto Update](https://github.com/OWNER/PriceCheckURL/actions/workflows/check-prices.yml/badge.svg)](https://github.com/OWNER/PriceCheckURL/actions/workflows/check-prices.yml)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)
![Chart.js v4](https://img.shields.io/badge/charts-Chart.js%20v4-FF6384.svg)
![TailwindCSS](https://img.shields.io/badge/styling-Tailwind%20CSS-38B2AC.svg)
![Playwright](https://img.shields.io/badge/headless-Playwright-2EAD33.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

---

## 🌟 Principais Recursos

### 📊 Dashboard Interativo SPA (Modo Escuro)
* 🗂️ **Arquitetura por Containers (Produtos)**: Em vez de exibir dezenas de cards desorganizados, os produtos são agrupados em **Containers** (ex: *AMD Ryzen 7 5800X3D*, *RTX 5070 Ti*, *Fonte RM850e*, *Xbox Series X*). Cada container consolida as ofertas de lojas concorrentes (Kabum, Pichau, Terabyte, Amazon, Mercado Livre, etc.).
* 📈 **Gráfico Comparativo no Topo (Chart.js)**:
  * **Linha do Tempo Monotônica Estrita**: Cronologia temporal consistente e organizada do mais antigo ao mais recente, sem distorções no eixo temporal.
  * **Deduplicação Inteligente de Checagens**: Checagens consecutivas onde **nenhuma loja** teve alteração de preço não poluem o gráfico. Assim que qualquer loja tem variação de preço, o ponto é registrado e **todas as lojas são plotadas juntas** naquele instante para comparação direta.
  * **Filtros de Período**: Alterne com um clique entre **Tudo (Histórico Completo)**, **30 dias**, **15 dias**, **7 dias** ou **24 horas**.
  * **Isolamento de Curvas Interativo**: Clique diretamente sobre qualquer linha do gráfico (ou no botão da loja correspondente) para isolar a curva e analisar o histórico específico. Clique novamente na linha para restaurar todas as curvas.
  * **Tooltip Focado**: Ao passar o mouse sobre o gráfico, o balão exibe apenas os dados da oferta da linha sob o cursor.
  * **Linha de Preço-Alvo**: Linha tracejada destacando o valor desejado para compra.
* 🏷️ **Status de Estoque e Oportunidades**: Cálculo automático de melhores preços, alertas de oportunidade (*"Compra Certa"*, *"Preço Aceitável"*) e sinalização de itens esgotados.

### ⏱️ Automação Serverless (GitHub Actions)
* 🔄 **Execução Agendada**: Workflow pré-configurado executando **a cada 2 horas no minuto 22** (`22 */2 * * *`), garantindo monitoramento constante sem congestionar a fila global de horários cheios.
* 💾 **Persistência Automática**: Ao detectar alterações de preço, o bot do GitHub Actions realiza commit e push automático dos dados em `data/latest_prices.json`, `data/price_history.json` e `data/price_history.csv`.
* ⚡ **Disparo Manual**: Suporte a disparo instantâneo via botão *"Verificar Preços"* no painel web ou pela aba *Actions* do GitHub.

### 🧠 Extrator Studio & Assistente CLI Inteligente
* 🪄 **Assistente CLI (`extractor_wizard.py`)**: Basta fornecer a URL de um produto para inspecionar o DOM, sugerir automaticamente os melhores seletores de **Título**, **Preço (PIX/à vista)** e **Estoque**, testar em tempo real e salvar em `extractors/extractors.json`.
* 🎨 **Extrator Studio Web**: Interface integrada no painel (`index.html`) para testar, validar e cadastrar regras visuais de novas lojas.
* 🛡️ **Motor Resiliente com Fallback Headless**: Utiliza requisições HTTP ultrarrápidas (`httpx`) com fallback transparente para Chromium headless (`Playwright`) em páginas com renderização pesada via JavaScript ou proteções contra bots.
* 🌐 **Heurísticas Universais**: Suporte a dados estruturados Schema.org (`ld+json`), OpenGraph, Microdata e expressões regulares para moeda brasileira (BRL).

---

## 📁 Estrutura do Repositório

```text
PriceCheckURL/
├── .github/
│   └── workflows/
│       └── check-prices.yml      # Workflow GitHub Actions (agendamento a cada 2h:22)
├── data/
│   ├── latest_prices.json        # Preços e disponibilidade da última checagem
│   ├── price_history.json        # Histórico de preços consolidado
│   ├── price_history.csv         # Histórico em formato tabular CSV
│   └── data.js                   # Empacotamento para funcionamento offline / zero-CORS
├── extractors/
│   └── extractors.json           # Regras declarativas de extração por loja/domínio
├── scraper/
│   ├── __init__.py
│   ├── engine.py                 # Motor de scraping (HTTP + Playwright + Heurísticas)
│   ├── extractor_wizard.py       # Assistente interativo de configuração de extratores
│   ├── main.py                   # Script orquestrador executado pelas Actions
│   └── utils.py                  # Formatadores BRL, alertas de oportunidade e helpers
├── config.json                   # Definição dos Containers, Preços-Alvo e URLs
├── extractor_wizard.py           # Atalho raiz para execução direta do assistente CLI
├── index.html                    # Dashboard SPA completo (GitHub Pages)
├── requirements.txt              # Dependências Python (httpx, beautifulsoup4, playwright)
└── .gitignore                    # Arquivos e pastas ignorados pelo Git
```

---

## 🚀 Como Publicar no GitHub Pages

### 1. Subir o Projeto para o seu Repositório
```bash
git add .
git commit -m "feat: setup PriceCheckURL"
git branch -M main
git remote add origin https://github.com/<seu-usuario>/PriceCheckURL.git
git push -u origin main
```

### 2. Ativar o GitHub Pages
1. Acesse o repositório no GitHub e vá em **Settings** > **Pages**.
2. Na seção **Build and deployment** > **Source**, selecione **Deploy from a branch**.
3. Em **Branch**, selecione `main` e a pasta `/ (root)`.
4. Clique em **Save**. O painel estará disponível em:
   ```
   https://<seu-usuario>.github.io/PriceCheckURL/
   ```

### 3. Configurar Permissões do GitHub Actions
Para que o bot do GitHub Actions consiga atualizar o histórico de preços:
1. Vá em **Settings** > **Actions** > **General**.
2. Na seção **Workflow permissions**, selecione **Read and write permissions**.
3. Marque a opção **Allow GitHub Actions to create and approve pull requests**.
4. Clique em **Save**.

### 4. Ativar Alertas no Discord (Notificações Push)
Para receber alertas visuais no seu servidor do Discord quando um produto atingir o preço-alvo:
1. No seu Discord, vá nas configurações do canal > **Integrações** > **Webhooks** > **Novo Webhook** e copie o link.
2. No seu repositório no GitHub, vá em **Settings** > **Secrets and variables** > **Actions**.
3. Clique em **New repository secret**:
   * **Name**: `DISCORD_WEBHOOK_URL`
   * **Secret**: Cole a URL do Webhook do Discord.
4. Clique em **Add secret**. Pronto! A cada checagem, você receberá cards com link direto e detalhes das melhores ofertas.

---

## 🪄 Como Criar Extratores para Novas Lojas

### Opção 1: Via Assistente CLI (Recomendado)
Execute passando a URL do produto na nova loja:
```bash
python extractor_wizard.py "https://www.loja-exemplo.com.br/produto/item-123"
```
*(ou através do módulo: `python -m scraper.extractor_wizard "URL"`)*

O assistente interativo:
1. Conecta à URL e inspeciona o código HTML da página.
2. Destaca os melhores seletores CSS encontrados para **Título**, **Preço à Vista** e **Disponibilidade**.
3. Permite selecionar as opções sugeridas ou inserir um seletor CSS customizado.
4. Realiza um teste imediato e grava a regra em [extractors/extractors.json](file:///e:/_Git/PriceCheckURL/extractors/extractors.json).

> **Modo Automático:** Para gerar e salvar diretamente usando as melhores pontuações heurísticas, adicione a flag `--auto`:
> ```bash
> python extractor_wizard.py "https://www.loja-exemplo.com.br/produto/item-123" --auto
> ```

### Opção 2: Pelo Extrator Studio no Painel Web
1. Abra o `index.html` e acesse a aba **"Extrator Studio"**.
2. Digite a URL de teste, nome da loja e configure os seletores CSS.
3. Clique em **"Simular / Testar Extrator"** para conferir a extração visualmente.
4. Clique em **"Salvar Extrator"** para registrar a nova regra.

---

## 💻 Execução e Testes Locais

### 1. Instalar as Dependências
```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Rodar a Verificação de Preços Manualmente
```bash
python -m scraper.main
```

### 3. Visualizar o Painel Localmente
Inicie um servidor HTTP local simples:
```bash
python -m http.server 8080
```
Abra seu navegador em [http://localhost:8080](http://localhost:8080).

---

## ⚙️ Configuração dos Produtos (`config.json`)

Você pode cadastrar novos produtos e lojas diretamente pelo dashboard ou editando o arquivo `config.json`:

```json
{
  "containers": [
    {
      "id": "ryzen-7-5800x3d",
      "name": "AMD Ryzen 7 5800X3D",
      "category": "Processador",
      "targetPrice": 2050.00,
      "items": [
        {
          "id": "ryzen-tb-padrao",
          "name": "Ryzen 7 5800X3D (Padrão)",
          "store": "Terabyte",
          "url": "https://www.terabyteshop.com.br/produto/..."
        },
        {
          "id": "ryzen-kb-pof",
          "name": "Ryzen 7 5800X3D (POF)",
          "store": "Kabum",
          "url": "https://www.kabum.com.br/produto/..."
        }
      ]
    }
  ]
}
```

---

## 📝 Licença

Distribuído sob a licença MIT. Consulte `LICENSE` para mais detalhes.
