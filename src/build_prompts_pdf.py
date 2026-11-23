"""Збирає prompts.pdf з prompts.md: PDF із текстом промптів (вимога завдання).

Що робить:
  1. Читає prompts.md. Файл не змінює: промпти дослівні, а розділи 3 «Зведення»
     і 7 «Висновки» автор заповнює пізніше, тому PDF перезбирається цим самим скриптом.
  2. Прибирає HTML-коментарі (шаблон нового запису), щоб вони не потрапили в PDF.
  3. Перетворює markdown на HTML (пакет markdown, розширення tables і fenced_code)
     зі стилями для друку: рамки таблиць, блоки коду з переносом рядків, кирилиця.
  4. Конвертує HTML у PDF через LibreOffice без вікна (soffice --headless)
     і кладе результат у корінь репозиторію: prompts.pdf.
Звідки дані: prompts.md.
Потрібно: пакет markdown у .venv, LibreOffice (команда soffice у PATH).
Запуск з кореня репозиторію: .venv/bin/python -m src.build_prompts_pdf
"""

import html
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import markdown

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src import config  # noqa: E402

MD_FILE = config.ROOT / "prompts.md"
PDF_FILE = config.ROOT / "prompts.pdf"
SOFFICE = "soffice"
# Фільтр імпорту HTML у Writer (а не Writer/Web): тоді діють розміри сторінки й поля.
SOFFICE_INFILTER = "HTML (StarWriter)"
# Шаблон запису в prompts.md сам містить блок коду з «```», тому коментарі
# прибираємо до markdown, інакше розмітка шаблону зламає наступний текст.
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
NBSP = " "
# Список без порожнього рядка перед ним: GitHub його розпізнає, python-markdown ні.
LIST_START_RE = re.compile(r"^\s*(?:[-*] |\d+\. )")
# Кольорові емодзі (✅ ❌ ➖ ⏳) LibreOffice у PDF не малює: лишається порожнє місце.
# Тому в PDF показуємо їхні однотонні відповідники з кольором за змістом;
# сам prompts.md не змінюється.
SYMBOL_MAP = {
    "✅": ("✔", "#1a7f37"),   # перевірено, збіг
    "⚠": ("⚠", "#b35c00"),   # застереження
    "❌": ("✘", "#c62828"),   # не підтвердилось
    "➖": ("–", "#555555"),   # не перевіряв
    "⏳": ("○", "#555555"),   # у процесі
}
VARIATION_SELECTOR = "\ufe0f"

# Стилі для друку: A4, шрифт 9 pt. Блоки коду — звичайні абзаци зі своїм шрифтом
# (див. pre_to_paragraphs): LibreOffice не переносить рядки в <pre>.
CSS = """
@page { size: A4; margin: 1.5cm 1.6cm; }
body { font-family: 'Helvetica Neue', Arial, sans-serif; font-size: 9pt; line-height: 1.3; }
h1 { font-size: 15pt; margin: 0 0 5pt 0; }
h2 { font-size: 12pt; margin: 10pt 0 3pt 0; }
h3 { font-size: 10.5pt; margin: 8pt 0 3pt 0; }
h4 { font-size: 9.5pt; margin: 6pt 0 2pt 0; }
p, li { margin: 0 0 3pt 0; }
blockquote { margin: 3pt 0 3pt 10pt; }
table { border-collapse: collapse; margin: 3pt 0 5pt 0; width: 100%; }
th, td { border: 0.5pt solid #888888; padding: 1pt 4pt; font-size: 8pt; vertical-align: top; }
th { background: #e8e8e8; }
code { font-family: Menlo, 'Courier New', monospace; font-size: 8pt; }
p.codeblock { font-family: Menlo, 'Courier New', monospace; font-size: 8pt;
  background: #f2f2f2; margin: 2pt 0 4pt 0; padding: 3pt 5pt; }
a { color: #1a4f8b; }
"""


def pre_to_paragraphs(body):
    """Замінює <pre><code>…</code></pre> на абзац, де рядки розділені <br>.

    Звичайний абзац LibreOffice переносить по краю сторінки, а <pre> — ні
    (довгий промпт обрізався б). Пробіли на початку рядків і подвійні пробіли
    зберігаємо нерозривними, щоб відступи не зникли.
    """
    def repl(m):
        code = html.unescape(m.group(1)).rstrip("\n")
        lines = []
        for line in code.split("\n"):
            lead = len(line) - len(line.lstrip(" "))
            line = NBSP * lead + line.lstrip(" ").replace("  ", NBSP + " ")
            lines.append(html.escape(line, quote=False))
        return '<p class="codeblock">' + "<br>".join(lines) + "</p>"
    return re.sub(r"<pre><code[^>]*>(.*?)</code></pre>", repl, body, flags=re.DOTALL)


def blank_line_before_lists(text):
    """Додає порожній рядок перед списком, що йде одразу після абзацу (поза блоками коду)."""
    out, in_code, prev = [], False, ""
    for line in text.split("\n"):
        if line.startswith("```"):
            in_code = not in_code
        elif (not in_code and LIST_START_RE.match(line) and prev.strip()
              and not LIST_START_RE.match(prev) and not prev.startswith(" ")):
            out.append("")
        if not in_code and re.match(r"^ {2}(?:[-*] |\d+\. )", line):
            line = "  " + line   # python-markdown вкладає списки лише з відступом 4 пробіли
        out.append(line)
        prev = line
    return "\n".join(out)


def build_html(text):
    text = blank_line_before_lists(COMMENT_RE.sub("", text))
    # nl2br: рядки шапки (завдання, вакансія, автор) в prompts.md без порожніх рядків між ними.
    body = markdown.markdown(text, extensions=["tables", "fenced_code", "nl2br"],
                             output_format="html")
    body = body.replace(VARIATION_SELECTOR, "")
    for emoji, (glyph, color) in SYMBOL_MAP.items():
        body = body.replace(emoji, f'<span style="color: {color}">{glyph}</span>')
    body = pre_to_paragraphs(body)
    # LibreOffice не бере рамки таблиць із CSS, тому задаємо їх атрибутами HTML.
    body = body.replace("<table>", '<table border="1" cellspacing="0" cellpadding="3" width="100%">')
    return ("<!DOCTYPE html><html lang='uk'><head><meta charset='utf-8'>"
            "<title>Журнал роботи з AI: посуха в Миколаївській області</title>"
            f"<style>{CSS}</style></head><body>{body}</body></html>")


def to_pdf(page):
    if shutil.which(SOFFICE) is None:
        sys.exit("Немає soffice у PATH: встановіть LibreOffice.")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "prompts.html"
        src.write_text(page, encoding="utf-8")
        cmd = [SOFFICE, "--headless", f"--infilter={SOFFICE_INFILTER}",
               "--convert-to", "pdf:writer_pdf_Export", "--outdir", tmp, str(src)]
        subprocess.run(cmd, check=True, capture_output=True, timeout=180)
        shutil.move(str(Path(tmp) / "prompts.pdf"), PDF_FILE)


def main():
    to_pdf(build_html(MD_FILE.read_text(encoding="utf-8")))
    print(f"Готово: {PDF_FILE.relative_to(config.ROOT)}")


if __name__ == "__main__":
    main()
