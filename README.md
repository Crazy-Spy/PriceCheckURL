# PriceCheckURL 🚀

> **Monitor inteligente de preços e estoque de e-commerces hospedado 100% no GitHub Pages com automação serverless via GitHub Actions e Extrator Studio Inteligente.**

---

## 🌟 Destaques do Projeto

* 🌐 **Hospedagem Gratuita & Estática (GitHub Pages)**: Painel responsivo em modo escuro com gráficos de histórico (Chart.js), cálculo de oportunidade e alertas de preço.
* ⏱️ **Verificação Automática a cada 4 horas (GitHub Actions)**: Workflow pré-configurado que roda em background, raspa as lojas, calcula variações, atualiza os dados e faz commit automático no repositório.
* 🧠 **Gerador de Extratores Inteligentes (Extractor Studio)**: Permite cadastrar **qualquer nova loja** sem precisar programar! A ferramenta analisa a estrutura do DOM, identifica candidatos a Título, Preço (à vista/PIX) e Estoque, testa em tempo real e salva regras reutilizáveis em `extractors.json`.
* 🛡️ **Heurísticas Universais de Fallback**: Mesmo sem regra customizada cadastrada, o motor analisa Schema.org (`application/ld+json`), OpenGraph, Microdata e padrões monetários brasileiros (BRL).
* 🔄 **Disparo Manual com 1 Clique**: No painel web, configure seu repositório e Personal Access Token (gravado localmente no seu navegador) para disparar a checagem no GitHub Actions a qualquer momento ou salvar novos containers e extratores diretamente no GitHub.

---

## 📁 Estrutura do Repositório

```text
PriceCheckURL/
├── .github/
│   └── workflows/
│       └── check-prices.yml     # Workflow do GitHub Actions (cron a cada 4 horas)
├── data/
│   ├── latest_prices.json       # Dados mais recentes de preços e estoque
│   ├── price_history.json       # Histórico de oscilação para os gráficos
│   ├── price_history.csv        # Histórico exportável em planilha CSV
│   └── data.js                  # Empacotamento estático para zero-CORS / offline
├── extractors/
│   └── extractors.json          # Regras declarativas das lojas cadastradas
├── scraper/
│   ├── __init__.py
│   ├── engine.py                # Motor de extração com suporte HTTP e Playwright
│   ├── extractor_wizard.py      # Assistente CLI inteligente para novas lojas
│   ├── main.py                  # Script principal executado pelo GitHub Actions
│   └── utils.py                 # Funções auxiliares (preço BRL, alertas, domínios)
├── index.html                   # Dashboard SPA moderno para o GitHub Pages
├── config.json                  # Containers, produtos e links monitorados
├── requirements.txt             # Dependências Python (httpx, beautifulsoup4, playwright)
├── .gitignore                   # Arquivos ignorados pelo Git
└── Old/                         # Backup do projeto anterior
```

---

## 🎯 Como Publicar no GitHub Pages

1. **Suba o código para o seu repositório no GitHub**:
   ```bash
   git add .
   git commit -m "feat: setup GitHub Pages & Actions price monitor"
   git branch -M main
   git remote add origin https://github.com/<seu-usuario>/PriceCheckURL.git
   git push -u origin main
   ```

2. **Ative o GitHub Pages**:
   * Vá em **Settings** > **Pages** no seu repositório do GitHub.
   * Em **Build and deployment** > **Source**, selecione **Deploy from a branch**.
   * Em **Branch**, selecione `main` e a pasta `/ (root)`.
   * Clique em **Save**. Em instantes seu painel estará online em:
     `https://<seu-usuario>.github.io/PriceCheckURL/`

3. **Permissões do GitHub Actions**:
   * Vá em **Settings** > **Actions** > **General**.
   * Em **Workflow permissions**, selecione **Read and write permissions**.
   * Marque a opção **Allow GitHub Actions to create and approve pull requests**.
   * Clique em **Save**. Isso garante que o bot do Actions consiga salvar os novos preços raspados automaticamente.

---

## 🪄 Como Criar Extratores para Novas Lojas

### Opção 1: Via Assistente Interativo (CLI)
Dê o link de qualquer produto da nova loja:
```bash
python -m scraper.extractor_wizard "https://www.nova-loja.com.br/produto/123"
```
O assistente irá:
1. Baixar a página e inspecionar os elementos.
2. Identificar os melhores candidatos a **Título**, **Preço à Vista/PIX** e **Estoque**.
3. Exibir uma lista numerada para você escolher ou digitar seletores CSS próprios.
4. Executar um teste ao vivo do resultado.
5. Gravar a nova regra em `extractors/extractors.json`. A partir desse momento, qualquer URL desse domínio saberá como ser raspada!

> *Dica*: Você também pode usar a flag `--auto` para gerar e salvar automaticamente usando as melhores heurísticas:
> ```bash
> python -m scraper.extractor_wizard "https://www.nova-loja.com.br/produto/123" --auto
> ```

### Opção 2: Pelo Extrator Studio no Painel Web (`index.html`)
1. Abra o painel no navegador e clique na aba **"Extrator Studio"**.
2. Preencha a URL de teste, nome da loja e ajuste os seletores visuais.
3. Clique em **"Simular / Testar Extrator"** para validar os dados capturados.
4. Clique em **"Salvar Extrator"**. Se seu GitHub Token estiver configurado, ele salva diretamente no repositório!

---

## 💻 Execução Local

Caso queira rodar localmente na sua máquina:

1. **Instalar dependências**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Executar a verificação de preços**:
   ```bash
   python -m scraper.main
   ```

3. **Abrir o painel**:
   Basta abrir o arquivo `index.html` com duplo clique no seu navegador ou iniciar um servidor estático local:
   ```bash
   python -m http.server 8080
   ```
   Acesse: `http://localhost:8080`
