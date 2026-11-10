"""Regressão visual opcional do tema com Auto Dark emulado no Chromium.

Com a API local e Chrome CDP em execução:
    python tests/browser/verify_theme_rendering.py --cdp http://127.0.0.1:9222

Ferramentas de QA: Playwright e Pillow. Não são dependências da aplicação.
Usa contextos privados próprios, sem criar conta ou ler registros de usuários.
O padrão emula sistema escuro; --system-preference light permite investigar
o comportamento específico do navegador com sistema claro e Auto Dark forçado.
"""

import argparse
from io import BytesIO
import json
from pathlib import Path
import tempfile
from urllib.parse import urlsplit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--cdp", default="http://127.0.0.1:9222")
    parser.add_argument("--system-preference", choices=("light", "dark"), default="dark")
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.width < 320:
        parser.error("Use uma largura de pelo menos 320 CSS px.")
    for url in (args.url, args.cdp):
        if urlsplit(url).hostname not in {"127.0.0.1", "localhost", "::1"}:
            parser.error("Use apenas a aplicação e o navegador locais de teste.")

    try:
        from PIL import Image
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise SystemExit("Esta verificação opcional requer Playwright e Pillow.") from error

    output = args.output or Path(tempfile.mkdtemp(prefix="rhythmmind-theme-qa-"))
    output.mkdir(parents=True, exist_ok=True)
    results = []
    failures = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(args.cdp)
        for mode in ("light", "dark"):
            for auto_dark in (False, True):
                context = browser.new_context(
                    viewport={"width": args.width, "height": 1000},
                    color_scheme=args.system_preference, reduced_motion="reduce",
                )
                try:
                    context.add_init_script(
                        'localStorage.setItem("rhythmmind.theme",' + json.dumps(mode) + ')'
                    )
                    page = context.new_page()
                    cdp = context.new_cdp_session(page)
                    cdp.send("Emulation.setAutoDarkModeOverride", {"enabled": auto_dark})
                    response = page.goto(args.url, wait_until="networkidle")
                    assert response.status == 200, response.status
                    actual = page.evaluate("""() => ({
                        theme: document.documentElement.dataset.theme,
                        scheme: getComputedStyle(document.body).colorScheme,
                        meta: document.querySelector('meta[name="color-scheme"]').content,
                        background: getComputedStyle(document.body).backgroundColor
                    })""")
                    png = page.screenshot()
                    # A amostra fica na margem externa à área de conteúdo.
                    # getComputedStyle sozinho não detecta a inversão de pintura do UA.
                    pixel = Image.open(BytesIO(png)).convert("RGB").getpixel((5, 200))
                    filename = f"{mode}-auto-dark-{str(auto_dark).lower()}.png"
                    (output / filename).write_bytes(png)
                    passed = actual["theme"] == mode and (
                        actual["meta"] == "only light" and min(pixel) >= 220
                        if mode == "light" else
                        actual["background"] == "rgb(11, 19, 41)" and pixel == (11, 19, 41)
                    )
                    results.append({**actual, "auto_dark": auto_dark, "pixel": pixel,
                                    "system_preference": args.system_preference,
                                    "width": args.width, "passed": passed,
                                    "screenshot": filename})
                    if not passed:
                        failures.append(filename)
                finally:
                    context.close()
    (output / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(f"{len(results)} combinações verificadas. Evidências: {output}")
    if failures:
        raise SystemExit("Pintura divergente; confira os PNGs e results.json: " + ", ".join(failures))


if __name__ == "__main__":
    main()
