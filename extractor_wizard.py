"""
PriceCheckURL - Atalho conveniente para o Extractor Wizard.
Permite executar `python extractor_wizard.py <URL>` diretamente da raiz do projeto.
"""
import os
import sys

if __name__ == "__main__":
    root_dir = os.path.dirname(os.path.abspath(__file__))
    if root_dir not in sys.path:
        sys.path.insert(0, root_dir)
    from scraper.extractor_wizard import main
    main()
