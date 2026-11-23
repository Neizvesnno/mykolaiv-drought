"""Фінальна презентація на 4 слайди: slides/presentation.pptx -> slides/presentation.pdf.

Що робить:
  1) збирає .pptx (16:9) бібліотекою python-pptx: тексти простою мовою для фермерів,
     рисунки з figures/*.png, детальні пояснення в нотатках доповідача;
  2) пише ті самі тексти в docs/slide_texts.md (щоб їх можна було читати і правити без PowerPoint);
  3) конвертує .pptx у PDF через LibreOffice (soffice --headless --convert-to pdf).
Звідки дані: data/processed/summary.json (частота посух), causes.json (спека, опади,
випаровування), yields.csv (пшениця, Держстат), season_oblast.csv (частка площі в посусі).
Кожне число на слайді читається з цих файлів і округлюється лише функцією fmt() під час показу.
Факти про страхування, воду і розмінування — з офіційних джерел у SOURCES_SLIDE4
(зміст слайда 4 затвердив Павло 23.11: orchestration/notes/slide4_approved.md).
Запуск з кореня репо: .venv/bin/python -m src.build_slides
"""
import io
import json
import subprocess
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pandas as pd
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

ROOT = Path(__file__).resolve().parent.parent
SUMMARY = ROOT / "data/processed/summary.json"
CAUSES = ROOT / "data/processed/causes.json"
YIELDS = ROOT / "data/processed/yields.csv"
OBLAST = ROOT / "data/processed/season_oblast.csv"
OUT_PPTX = ROOT / "slides/presentation.pptx"
OUT_PDF = ROOT / "slides/presentation.pdf"
OUT_MD = ROOT / "docs/slide_texts.md"

# --- макет (дюйми) і типографіка ---
SLIDE_W, SLIDE_H = 13.333, 7.5      # 16:9
MARGIN = 0.5
BULLET_INDENT = 0.3                 # відступ тексту від маркера списку
MAX_PX = 2000                       # довша сторона рисунка у файлі, щоб PDF був легким
FONT = "Arial"                      # є в Office і в LibreOffice, кирилиця без підміни
TITLE_PT, BODY_PT, SMALL_PT = 30, 18, 12
CARD_HEAD_PT, CARD_PT, SOURCE_PT = 17, 14, 10
WHEAT_PT = 16                       # пшениця — головне зауваження Павла, крупніше   # слайд 4 щільний: 14 pt — нижня межа для тексту
COLOR_TEXT = RGBColor(0x1F, 0x1F, 0x1F)
COLOR_GREY = RGBColor(0x5F, 0x5F, 0x5F)
COLOR_ACCENT = RGBColor(0xB8, 0x4A, 0x12)       # теплий помаранчевий, як посуха на рисунках
COLOR_OLD = RGBColor(0x7A, 0x7A, 0x7A)          # «було» на слайді 1 — сірий, як роки без посухи
COLOR_CARD_WARM = RGBColor(0xFB, 0xEF, 0xE6)    # тло картки «пшениця» і «цього сезону»
COLOR_CARD_COOL = RGBColor(0xEC, 0xF1, 0xEC)    # тло картки «на 3–10 років»

# роки пшениці для слайда 4 (найпоказовіші; решта — у методології)
WHEAT_YEARS = [2012, 2020]
WHEAT_NO_LOSS_YEARS = [2009, 2014]   # чесно: посуха була, а недобору майже немає
TONNES_PER_CENTNER = Decimal("0.1")  # 1 ц = 100 кг = 0,1 т

SOURCE_DATA = "Дані: TerraClimate (1958–2025)"
SOURCES_SLIDE4 = {
    "insurance_kmu": "https://www.kmu.gov.ua/news/taras-vysotskyi-ahrostrakhuvannia-z-derzhavnoiu-pidtrymkoiu-staie-novym-instrumentom-stabilnosti-dlia-ahrovyrobnykiv",
    "insurance_me": "https://me.gov.ua/News/Detail/0d6f3380-6fa3-4aaf-8f69-d4e549e72e61?lang=uk-UA",
    "kakhovka": "https://epravda.com.ua/news/2023/06/7/700892/",
    "mykolaiv_water": "https://www.kmu.gov.ua/news/minrozvytku-tsentralizovanu-podachu-prisnoi-vody-do-mykolaieva-vidnovleno-vpershe-z-2022-roku",
    "demining": "https://www.kmu.gov.ua/news/derzhprohrama-kompensatsii-rozminuvannia-ahrozemel-fermeram-povernuly-bilshe-dvokh-tysiach-hektariv-uhid",
}


def fmt(x, digits=2, sign=False):
    """Число -> рядок з комою і типографським мінусом.

    Округлення лише тут, і половинки вгору (як у школі): Decimal(str(x)) бере
    коротке десяткове подання числа, тож 38.55 з CSV стає «38,6», а не «38,5»
    (float 38.55 у пам'яті трохи менший за 38,55).
    """
    d = Decimal(str(x)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    s = f"{d:f}".replace(".", ",").replace("-", "−")
    return ("+" + s) if sign and d > 0 else s


def one_in(n_total, n_events):
    """«1 рік із N»: N = років / подій, 2 знаки."""
    return fmt(n_total / n_events, 2)


# ---------------- числа з файлів даних ----------------
S = json.loads(SUMMARY.read_text(encoding="utf-8"))
C = json.loads(CAUSES.read_text(encoding="utf-8"))
Y = pd.read_csv(YIELDS).set_index("year")
OB = pd.read_csv(OBLAST).set_index("year")

n_years = S["n_years"]
n_conf = S["for_farmers"]["drought_years_confirmed"]
n_pdsi = S["for_farmers"]["drought_years_pdsi"]
p1, p2 = S["periods"]["1958-1990"], S["periods"]["1991-2025"]
times_more = p2["share_confirmed_pct"] / p1["share_confirmed_pct"]   # ≈ 3,06 -> «утричі»
worst4 = [w["year"] for w in S["worst_years"][:4]]
worst_pdsi = {w["year"]: w["pdsi"] for w in S["worst_years"]}
full_cover = S["area_share_note"]["drought_years_with_share_1.0"]
worst4_full = all(OB.loc[y, "area_share_pdsi_le_-2"] == 1.0 for y in worst4)

diff = C["periods"]["difference"]
tmax_up = diff["tmax_c"]
ppt_down_pct = -diff["ppt_pct_of_first"]
pet_share_pct = diff["pet_mm"] / -diff["balance_mm"] * 100   # частка випаровування в погіршенні балансу

ray = S["spatial"]["rayons"]
ray_conf = C["rayons_frequency"]


def rayon_one_in(name):
    key = next(k for k in ray if k.startswith(name))
    return fmt(100 / ray[key]["mean_frequency_pct"], 2)


def wheat(year):
    """Три числа для фермера: зібрали, у сусідні звичайні роки, різниця (ц/га і %)."""
    r = Y.loc[year]
    got = Decimal(str(r["yield_c_ha"]))
    base = Decimal(str(r["baseline_c_ha"]))
    return {
        "got": fmt(got, 1),
        "base": fmt(base, 1),
        "less": fmt(base - got, 1),          # різниця з точних значень, а не з округлених
        "pct": fmt(r["loss_pct"], 2, sign=True),
        "tonnes": fmt(got * TONNES_PER_CENTNER, 2),
    }


W = {y: wheat(y) for y in WHEAT_YEARS}
no_loss = " і ".join(fmt(Y.loc[y, "loss_pct"], 2, sign=True) + " %" for y in WHEAT_NO_LOSS_YEARS)
base_years = {}
for y in WHEAT_YEARS:  # які роки увійшли в базу (несухі сусіди в межах ±3 роки)
    near = Y.loc[(Y.index >= y - 3) & (Y.index <= y + 3) & (Y["category"] == "немає")].index
    base_years[y] = ", ".join(str(int(v)) for v in near)

# ---------------- тексти слайдів ----------------
# Кожен слайд: title (сама думка), блоки тексту, рисунок, нотатки доповідача.
SLIDES = [
    {
        "title": "Посуха на Миколаївщині тепер буває втричі частіше",
        "figure": "figures/fig1_timeline.png",
        "stats": [
            ("1958–1990", f"{p1['drought_years_confirmed']} з {p1['n_years']}",
             f"сезонів посушливі: 1 рік із {fmt(p1['one_year_in_confirmed'])}", COLOR_OLD),
            ("1991–2025", f"{p2['drought_years_confirmed']} з {p2['n_years']}",
             f"сезонів посушливі: 1 рік із {fmt(p2['one_year_in_confirmed'])}", COLOR_ACCENT),
        ],
        "body": [
            f"Чому: квітень–вересень став спекотнішим на {fmt(tmax_up)} °C, а дощів поменшало на {fmt(ppt_down_pct)} %. "
            f"Дефіцит вологи зріс здебільшого через сильніше випаровування: це {fmt(pet_share_pct)} % приросту.",
        ],
        "footnote": (
            f"Посуха тут — сухий сезон квітень–вересень, підтверджений нестачею дощу або вологи в ґрунті. "
            f"Усього {n_conf} таких сезонів за {n_years} років: 1 рік із {one_in(n_years, n_conf)}. "
            f"Якщо рахувати лише за дощами, висновок той самий: "
            f"{p1['drought_years_confirmed_by_ppt']} з {p1['n_years']} проти {p2['drought_years_confirmed_by_ppt']} з {p2['n_years']}."
        ),
        "notes": (
            f"Головна думка: посушливих сезонів стало втричі більше. 1958–1990: {p1['drought_years_confirmed']} підтверджені посухи "
            f"із {p1['n_years']} сезонів ({fmt(p1['share_confirmed_pct'])} % років), 1991–2025: {p2['drought_years_confirmed']} за {p2['n_years']} "
            f"({fmt(p2['share_confirmed_pct'])} %); відношення {fmt(times_more)}. "
            f"Підтверджена посуха: індекс посухи Палмера (PDSI) за квітень–вересень ≤ −2 і опадів або вологи ґрунту щонайменше на 20 % менше "
            f"від норми 1991–2020. Ще {S['for_farmers']['inertial_years']} роки сухі лише за індексом — їх не рахуємо. "
            f"За самими опадами (незалежна перевірка, бо ґрунт і PDSI з однієї моделі): {p1['drought_years_confirmed_by_ppt']} з {p1['n_years']} "
            f"проти {p2['drought_years_confirmed_by_ppt']} з {p2['n_years']}. "
            f"Причини (causes.json): середня макс. температура сезону +{fmt(tmax_up)} °C, опади −{fmt(ppt_down_pct)} % "
            f"({fmt(diff['ppt_mm'])} мм), потенційне випаровування +{fmt(diff['pet_mm'])} мм; водний баланс погіршився на "
            f"{fmt(-diff['balance_mm'])} мм, з них {fmt(pet_share_pct)} % — випаровування. Ці дані показують збіг у часі, а не доводять причину."
        ),
    },
    {
        "title": "У найсухіші роки посуха накриває всю область",
        "figure": "figures/fig2_maps.png",
        "body": [
            f"Чотири найсухіші сезони за {n_years} років: {', '.join(map(str, worst4))}.",
            "У кожен із них посуха охопила всю область, від Первомайська до Миколаєва.",
            f"Так буває часто: посуха вкривала всю площу області в {full_cover} сухих роках із {n_pdsi}.",
            "Тому в сухий рік сусідній район чи поле не виручить.",
        ],
        "footnote": "Чим темніший колір на карті, тим сухіше. Число над картою — середній індекс посухи Палмера по області; нижче −2 — посуха.",
        "notes": (
            "Індекс посухи Палмера (PDSI) за квітень–вересень, середнє по області: "
            + ", ".join(f"{y}: {fmt(worst_pdsi[y])}" for y in worst4)
            + f". У всі чотири роки частка площі з PDSI ≤ −2 дорівнює 1 (season_oblast.csv). "
            f"З {n_pdsi} сухого за індексом року в {full_cover} посуха вкрила всю площу (summary.json, area_share_note). "
            "Посуха тут не місцева: вона приходить на всю область одночасно, тож розраховувати, що поле в іншому районі компенсує втрату, не варто."
        ),
    },
    {
        "title": "Посуха — проблема всієї області",
        "figure": "figures/fig3_frequency.png",
        "body": [
            f"У кожному районі сухий рік буває приблизно кожен третій: "
            f"від 1 року із {rayon_one_in('Баштанський')} (Баштанський) до 1 року із {rayon_one_in('Первомайський')} (Первомайський).",
            "Північ потерпає трохи частіше, але різниця мала: якщо рахувати лише підтверджені посухи, "
            "Миколаївський і Первомайський райони майже рівні.",
            f"Числа на карті більші, ніж «1 рік із {one_in(n_years, n_conf)}» на першому слайді, "
            "бо тут враховано і роки, сухі лише за індексом.",
        ],
        "footnote": None,
        "notes": (
            "Частота за індексом (PDSI ≤ −2 у клітинці), середнє по клітинках району: "
            + ", ".join(f"{k.split()[0]} {fmt(v['mean_frequency_pct'])} %" for k, v in ray.items())
            + ". Підтверджена по клітинці (індекс і нестача опадів або ґрунту в тій самій клітинці): "
            + ", ".join(f"{k.split()[0]} {fmt(v['frequency_confirmed_pct'])} %" for k, v in ray_conf.items() if not k.startswith("_"))
            + f". Різниця між районами за індексом {fmt(ray_conf['_spread_pp']['index'])} в.п., за підтвердженими "
            f"{fmt(ray_conf['_spread_pp']['confirmed'])} в.п.: вона меншає, але не зникає, Баштанський лишається найменшим. "
            "Тому не кажемо «на півночі посуха», а кажемо: посуха — проблема всієї області."
        ),
    },
]

wh_lines = [
    (str(y), f"зібрали {W[y]['got']} ц з гектара, а в сусідні звичайні роки — {W[y]['base']} ц. "
             f"Це на {W[y]['less']} ц менше ({W[y]['pct']} %).")
    for y in WHEAT_YEARS
]
SLIDE4 = {
    "title": "Плануйте кожен сезон з розрахунком на сухий рік",
    "wheat_head": "Пшениця в сухий рік",
    "wheat": wh_lines,
    "wheat_honest": f"Але не завжди: у {' і '.join(map(str, WHEAT_NO_LOSS_YEARS))} посуха врожаю майже не зменшила ({no_loss}).",
    "wheat_unit": (f"ц/га — центнерів зерна з гектара; 1 центнер = 100 кг. "
                   f"{W[WHEAT_YEARS[0]]['got']} ц/га = {W[WHEAT_YEARS[0]]['tonnes']} т з гектара."),
    "short_head": "Цього сезону (2027)",
    "short": [
        ("Плануйте сезон так, ніби він буде сухим.",
         f"З 1991 року посуха була {p2['drought_years_confirmed']} разів за {p2['n_years']} років: "
         "тримайте запас насіння й коштів, не ставте все на одну культуру."),
        ("Застрахуйте врожай з допомогою держави.",
         "Держава повертає до 60 % страхової премії у прифронтових громадах, іншим до 45 %. "
         "Заявки до 1 квітня, 1 серпня або 10 листопада; потрібна реєстрація в Державному аграрному реєстрі."),
        ("Бережіть вологу в ґрунті.",
         "Мінімальний обробіток, пожнивні рештки, чисті пари перед озимими. Що підійде вашому полю, вирішує агроном."),
    ],
    "long_head": "На 3–10 років",
    "long": [
        ("Відновлюйте полезахисні лісосмуги.",
         f"Дефіцит вологи росте здебільшого через випаровування ({fmt(pet_share_pct)} % приросту); смуги зменшують вітер і випаровування. "
         "Ефект через роки, тому садити варто вже зараз."),
        ("Розраховуйте на місцеву воду.",
         "Після підриву Каховської ГЕС без води лишилось 94 % зрошувальних систем Херсонщини. "
         "Реально: краплинне зрошення, ставки, тала вода; вкладайте лише в поле, обстежене на міни."),
    ],
    "source": ("Дані: TerraClimate (1958–2025); пшениця: Держстат; страхування: КМУ, Мінекономіки; "
               "Каховська ГЕС: Економічна правда. Посилання — у нотатках доповідача і методології."),
}
SLIDE4["notes"] = "\n".join([
    "ПШЕНИЦЯ. Урожайність пшениці загалом по області, усі категорії господарств (Держстат, табл. 2.6). "
    "Сухий рік порівнюємо не з «нормою», а із середнім сусідніх несухих років у межах ±3 роки: "
    "урожайність з роками росте (сорти, добрива, техніка), тому далекі роки порівнювати нечесно. "
    + " ".join(f"{y}: база — середнє {base_years[y]}." for y in WHEAT_YEARS)
    + f" {Y['loss_pct'].notna().sum()} посушливих років із базою дають у середньому {fmt(Y['loss_pct'].mean(), 2, sign=True)} %, розкид великий; "
    "повний список і застереження (база з 1–4 років, 2022 — війна) — у методології.",
    f"1. ПЛАНУВАННЯ. З 1991 року {p2['drought_years_confirmed']} підтверджених посух за {p2['n_years']} років: "
    f"1 рік із {fmt(p2['one_year_in_confirmed'])}. Запас насіння і коштів на поганий рік; частка посухостійких культур "
    "(сорго, ячмінь, соняшник) зменшує ризик. Конкретних норм і гібридів дані не підтверджують.",
    "2. СТРАХУВАННЯ. Мінекономіки (31.12.2025): у бюджеті 2026 року вперше передбачено кошти на агрострахування; держава компенсує "
    "до 60 % страхової премії агровиробникам у прифронтових громадах і до 45 % іншим; обов'язкова реєстрація в Державному аграрному реєстрі. "
    "КМУ (24.02.2026): заявки на компенсацію — до 1 квітня, до 1 серпня або до 10 листопада залежно від періоду укладання договору. "
    "Найближчий строк — 1 квітня 2027, якщо порядок не зміниться. Чи покриває договір посуху, уточнюйте у страховика: "
    "у цих двох джерелах перелік ризиків не наведено. "
    f"Джерела: {SOURCES_SLIDE4['insurance_me']} ; {SOURCES_SLIDE4['insurance_kmu']}",
    "3. ВОЛОГА В ҐРУНТІ. Мінімальний обробіток і пожнивні рештки зменшують випаровування; чисті пари перед озимими; ранні строки сівби ярих. "
    "Конкретну технологію (дози, строки в датах) підбирає агроном господарства.",
    f"4. ЛІСОСМУГИ. За 1991–2025 проти 1958–1990 водний баланс сезону погіршився на {fmt(-diff['balance_mm'])} мм; "
    f"{fmt(pet_share_pct)} % цього дало зростання випаровування (+{fmt(diff['pet_mm'])} мм), решту — менше опадів (causes.json). "
    "Полезахисні смуги зменшують вітер і випаровування з поля; ефект через роки, тому починати зараз.",
    "5. ВОДА І ВІЙНА. Після підриву Каховської ГЕС (червень 2023) без джерела води лишились 94 % зрошувальних систем Херсонщини, "
    "74 % Запоріжжя і 30 % Дніпропетровщини (Економічна правда, 07.06.2023), тож велике зрошення з Дніпра найближчими роками нереальне. "
    "Миколаїв не мав централізованої прісної води з 2022 року, коли підірвали магістральний водогін; у 2025 подачу відновили новим водогоном "
    "(~136 км, новина КМУ 07.10.2025). У посуху води на полив буде мало: реалістично краплинне зрошення, ставки, збір талої води. "
    "Будь-які вкладення в поле — лише після обстеження на міни. Держпрограма компенсує 100 % вартості розмінування агроземель "
    "(для тих, хто вирішив очистити ділянку після 15.04.2024); на Миколаївщині на 29.05.2025 очищено 501 га. "
    f"Джерела: {SOURCES_SLIDE4['kakhovka']} ; {SOURCES_SLIDE4['mykolaiv_water']} ; {SOURCES_SLIDE4['demining']}",
])


# ---------------- збирання .pptx ----------------
def emu(inches):
    return Emu(int(Inches(inches)))


def small_png(path):
    """PNG, зменшений у пам'яті до MAX_PX (файл у figures/ не змінюється)."""
    im = Image.open(ROOT / path).convert("RGB")
    k = MAX_PX / max(im.size)
    if k < 1:
        im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf, im.size


def add_picture_fit(slide, path, x, y, w, h, alt=""):
    """Рисунок у прямокутнику (дюйми) зі збереженням пропорцій, по центру."""
    buf, (pw, ph) = small_png(path)
    k = min(w / pw, h / ph)
    fw, fh = pw * k, ph * k
    pic = slide.shapes.add_picture(buf, emu(x + (w - fw) / 2), emu(y + (h - fh) / 2), emu(fw), emu(fh))
    pic.name = Path(path).stem
    pic._element.nvPicPr.cNvPr.set("descr", alt)   # опис для читачів з екрана
    return pic


def style_run(run, size, bold=False, color=COLOR_TEXT):
    run.font.name = FONT
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color


def nbsp(text):
    """Неперервний пробіл перед одиницями, щоб число не відривалось від «%», «°C», «ц»."""
    for unit in (" %", " °C", " ц ", " ц.", " ц/га", " т ", " центнер", " кг"):
        text = text.replace(unit, "\u00a0" + unit[1:])
    return text


def make_bullet(p):
    """Справжній маркер списку з відступом (другий рядок вирівняний по тексту, а не під «•»)."""
    ppr = p._p.get_or_add_pPr()
    ppr.set("marL", str(emu(BULLET_INDENT)))
    ppr.set("indent", str(-emu(BULLET_INDENT)))
    bu = ppr.makeelement(qn("a:buChar"), {"char": "•"})
    ppr.append(bu)


def add_textbox(slide, x, y, w, h, paragraphs, name, anchor=MSO_ANCHOR.TOP):
    """paragraphs: список абзаців; абзац = (список runs, space_before_pt); run = (текст, pt, bold, колір)."""
    tb = slide.shapes.add_textbox(emu(x), emu(y), emu(w), emu(h))
    tb.name = name
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    for i, (runs, space_before, *opt) in enumerate(paragraphs):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_before = Pt(space_before)
        if opt and opt[0]:
            make_bullet(p)
        p.line_spacing = 1.05
        for text, size, bold, color in runs:
            style_run(p.add_run(), size, bold, color)
            p.runs[-1].text = nbsp(text)
    return tb


def add_card(slide, x, y, w, h, color, name):
    shp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, emu(x), emu(y), emu(w), emu(h))
    shp.adjustments[0] = 0.04
    shp.fill.solid()
    shp.fill.fore_color.rgb = color
    shp.line.fill.background()
    shp.shadow.inherit = False
    shp.name = name
    return shp


def set_title(slide, text):
    t = slide.shapes.title
    t.left, t.top, t.width, t.height = emu(MARGIN), emu(0.35), emu(SLIDE_W - 2 * MARGIN), emu(0.85)
    tf = t.text_frame
    tf.margin_left = tf.margin_right = 0
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = 1  # ліворуч
    r = p.add_run()
    r.text = text
    style_run(r, TITLE_PT, bold=True)


def set_notes(slide, text):
    slide.notes_slide.notes_text_frame.text = text


def bullets(items, size=BODY_PT, gap=14):
    return [([(t, size, False, COLOR_TEXT)], 0 if i == 0 else gap, True) for i, t in enumerate(items)]


def build_slide1(prs, d):
    s = prs.slides.add_slide(prs.slide_layouts[5])
    set_title(s, d["title"])
    add_picture_fit(s, d["figure"], MARGIN, 1.35, 8.1, 4.75, alt=d["title"])
    x, w = 8.95, SLIDE_W - MARGIN - 8.95
    paras = []
    for i, (label, big, small, color) in enumerate(d["stats"]):
        paras += [([(label, 16, True, COLOR_GREY)], 0 if i == 0 else 16),
                  ([(big, 40, True, color)], 0),
                  ([(small, 16, False, COLOR_TEXT)], 0)]
    paras.append(([(d["body"][0], 16, False, COLOR_TEXT)], 20))
    add_textbox(s, x, 1.45, w, 4.75, paras, "Підсумок")
    add_textbox(s, MARGIN, 6.35, SLIDE_W - 2 * MARGIN, 0.75,
                [([(d["footnote"], SMALL_PT, False, COLOR_GREY)], 0)], "Примітка", MSO_ANCHOR.BOTTOM)
    set_notes(s, d["notes"])


def build_text_figure(prs, d, text_w, fig_box):
    s = prs.slides.add_slide(prs.slide_layouts[5])
    set_title(s, d["title"])
    add_textbox(s, MARGIN, 1.55, text_w, 4.6, bullets(d["body"]), "Текст")
    if d["footnote"]:
        add_textbox(s, MARGIN, 6.15, text_w, 0.95,
                    [([(d["footnote"], SMALL_PT, False, COLOR_GREY)], 0)], "Примітка", MSO_ANCHOR.BOTTOM)
    add_picture_fit(s, d["figure"], *fig_box, alt=d["title"])
    set_notes(s, d["notes"])


def numbered(items, start, size=CARD_PT, gap=9):
    paras = []
    for i, (head, text) in enumerate(items):
        paras.append(([(f"{start + i}. ", size, True, COLOR_ACCENT), (head + " ", size, True, COLOR_TEXT),
                       (text, size, False, COLOR_TEXT)], 0 if i == 0 else gap))
    return paras


def build_slide4(prs, d):
    s = prs.slides.add_slide(prs.slide_layouts[5])
    set_title(s, d["title"])
    top, bottom = 1.35, 6.8
    pad = 0.22
    # ліва картка: ризик для пшениці
    lx, lw = MARGIN, 4.3
    add_card(s, lx, top, lw, bottom - top, COLOR_CARD_WARM, "Картка пшениця")
    paras = [([(d["wheat_head"], CARD_HEAD_PT, True, COLOR_ACCENT)], 0)]
    for year, text in d["wheat"]:
        paras.append(([(year + ": ", WHEAT_PT, True, COLOR_TEXT), (text, WHEAT_PT, False, COLOR_TEXT)], 14))
    paras.append(([(d["wheat_unit"], CARD_PT, False, COLOR_TEXT)], 14))
    paras.append(([(d["wheat_honest"], CARD_PT, False, COLOR_GREY)], 14))
    add_textbox(s, lx + pad, top + pad, lw - 2 * pad, bottom - top - 2 * pad, paras, "Пшениця")
    # права частина: дві картки рішень
    rx = lx + lw + 0.3
    rw = SLIDE_W - MARGIN - rx
    split = 4.45   # межа між картками (дюйми від верху слайда)
    add_card(s, rx, top, rw, split - top - 0.12, COLOR_CARD_WARM, "Картка цього сезону")
    add_textbox(s, rx + pad, top + 0.15, rw - 2 * pad, split - top - 0.4,
                [([(d["short_head"], CARD_HEAD_PT, True, COLOR_ACCENT)], 0)] + numbered(d["short"], 1),
                "Цього сезону")
    add_card(s, rx, split + 0.12, rw, bottom - split - 0.12, COLOR_CARD_COOL, "Картка на роки")
    add_textbox(s, rx + pad, split + 0.27, rw - 2 * pad, bottom - split - 0.4,
                [([(d["long_head"], CARD_HEAD_PT, True, COLOR_ACCENT)], 0)] + numbered(d["long"], 1 + len(d["short"])),
                "На роки")
    add_textbox(s, MARGIN, 6.92, SLIDE_W - 2 * MARGIN, 0.3,
                [([(d["source"], SOURCE_PT, False, COLOR_GREY)], 0)], "Джерела", MSO_ANCHOR.BOTTOM)
    set_notes(s, d["notes"])


def build_pptx():
    prs = Presentation()
    prs.slide_width, prs.slide_height = emu(SLIDE_W), emu(SLIDE_H)
    prs.core_properties.title = "Посуха на Миколаївщині"
    prs.core_properties.language = "uk-UA"
    build_slide1(prs, SLIDES[0])
    build_text_figure(prs, SLIDES[1], 5.6, (6.4, 1.3, SLIDE_W - MARGIN - 6.4, 5.85))
    build_text_figure(prs, SLIDES[2], 4.9, (5.7, 1.3, SLIDE_W - MARGIN - 5.7, 5.85))
    build_slide4(prs, SLIDE4)
    OUT_PPTX.parent.mkdir(exist_ok=True)
    prs.save(OUT_PPTX)


def write_md():
    """Ті самі тексти в Markdown для перегляду і рецензії."""
    out = ["# Тексти слайдів (фінальна презентація)", "",
           "Згенеровано `src/build_slides.py` з `summary.json`, `causes.json`, `yields.csv`, `season_oblast.csv`; "
           "не редагуйте вручну — правте тексти в скрипті і перезапустіть `.venv/bin/python -m src.build_slides`.", ""]
    for i, d in enumerate(SLIDES, 1):
        out += [f"## Слайд {i}. {d['title']}", "", f"Рисунок: `{d['figure']}`", ""]
        for label, big, small, _ in d.get("stats", []):
            out.append(f"- **{label}:** {big} {small}")
        out += [f"- {t}" for t in d["body"]]
        if d["footnote"]:
            out += ["", f"Примітка на слайді: {d['footnote']}"]
        out += ["", f"Нотатки доповідача: {d['notes']}", ""]
    d = SLIDE4
    out += [f"## Слайд 4. {d['title']}", "", f"### {d['wheat_head']}", ""]
    out += [f"- **{y}:** {t}" for y, t in d["wheat"]] + [f"- {d['wheat_honest']}", f"- {d['wheat_unit']}", ""]
    out += [f"### {d['short_head']}", ""] + [f"{i}. **{h}** {t}" for i, (h, t) in enumerate(d["short"], 1)] + [""]
    out += [f"### {d['long_head']}", ""] + [f"{i}. **{h}** {t}" for i, (h, t) in enumerate(d["long"], 1 + len(d["short"]))]
    out += ["", f"Джерела на слайді: {d['source']}", "", "Нотатки доповідача:", ""]
    out += [f"- {line}" for line in d["notes"].split("\n")]
    OUT_MD.write_text("\n".join(out) + "\n", encoding="utf-8")


def to_pdf():
    """PDF з .pptx через LibreOffice; саме PDF надсилаємо роботодавцю."""
    subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(OUT_PDF.parent), str(OUT_PPTX)],
                   check=True, capture_output=True)


def main():
    assert worst4_full, "очікували, що 4 найсухіші роки вкривають усю область (season_oblast.csv)"
    build_pptx()
    write_md()
    to_pdf()
    for p in (OUT_PPTX, OUT_PDF, OUT_MD):
        print(f"Збережено {p.relative_to(ROOT)} ({p.stat().st_size / 1e6:.2f} МБ)")


if __name__ == "__main__":
    main()
