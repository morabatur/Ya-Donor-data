#!/usr/bin/env python3
"""
Витягує потребу у крові по центрах крові з donor.utcc.gov.ua.

Сайт віддає звичайний HTML (без JavaScript), тому браузер не потрібен —
достатньо завантажити сторінку і розібрати її регулярними виразами.

Використання:
    python3 fetch_blood_needs.py              # таблиця в консоль
    python3 fetch_blood_needs.py --json       # JSON у консоль
    python3 fetch_blood_needs.py --json -o needs.json
    python3 fetch_blood_needs.py --high       # тільки висока потреба
    python3 fetch_blood_needs.py --app -o needs.json   # формат для додатку
"""

import argparse
import datetime
import html
import os
import json
import re
import sys
import urllib.request

BASE = "https://donor.utcc.gov.ua/service_center"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"

# Центри розбиті по регіонах — на головній сторінці видно лише центральний,
# тому проходимо всі п'ять окремими сторінками.
REGIONS = {
    "centralnii": "Центральний",
    "pivdennii": "Південний",
    "sxidnii": "Східний",
    "pivnicnii": "Північний",
    "zaxidnii": "Західний",
}

# клас іконки на сайті -> зрозумілий рівень
ICON_LEVEL = {"hight": "high", "middle": "medium", "low": "low"}

# Підписи груп крові на сайті -> ключі, які очікує додаток.
# Увага: на сайті вжито українські літери І та V у римських цифрах.
GROUP_KEYS = {
    "0(І) Rh(+)": "O_POS", "0(І) Rh(-)": "O_NEG",
    "А(ІІ) Rh(+)": "A_POS", "А(ІІ) Rh(-)": "A_NEG",
    "В(ІІІ) Rh(+)": "B_POS", "В(ІІІ) Rh(-)": "B_NEG",
    "АВ(ІV) Rh(+)": "AB_POS", "АВ(ІV) Rh(-)": "AB_NEG",
}

MAPPING_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "utcc_mapping.json")


def app_payload(centers):
    """Перекласти зібрані дані у формат, який читає додаток.

    Назви центрів на сайті УЦТК і в довіднику додатку не збігаються, тому
    зіставлення лежить в utcc_mapping.json і складене руками.
    """
    with open(MAPPING_FILE, encoding="utf-8") as f:
        mapping = {k: v for k, v in json.load(f).items() if not k.startswith("_")}

    out, skipped, unknown = [], [], []
    for c in centers:
        if c["name"] not in mapping:
            unknown.append(c["name"])
            continue
        center_id = mapping[c["name"]]
        if center_id is None or not c["needs"]:
            skipped.append(c["name"])
            continue
        levels = {}
        for n in c["needs"]:
            key = GROUP_KEYS.get(n["group"])
            if key:
                levels[key] = n["level"].upper()
        if levels:
            out.append({"centerId": center_id, "needs": levels})

    for name in unknown:
        print(f"УВАГА: центру немає в utcc_mapping.json: {name}", file=sys.stderr)

    return {
        "version": 1,
        "generatedAt": datetime.date.today().isoformat(),
        "source": BASE,
        "centers": sorted(out, key=lambda x: x["centerId"]),
    }, skipped


def get(url):
    """Завантажити сторінку як текст."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", "replace")


def clean(s):
    """Прибрати HTML-теги, розкодувати &nbsp; і стиснути пробіли."""
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def first(pattern, text):
    """Перший збіг або None."""
    m = re.search(pattern, text, re.S)
    return clean(m.group(1)) if m else None


def parse_page(page_html):
    """Розібрати одну сторінку на список центрів."""
    centers = []

    # Кожен центр — блок <div class="service-center-accordion-wrap">.
    # split дає частини, кожна з яких починається з одного центру.
    for part in page_html.split('class="service-center-accordion-wrap"')[1:]:
        name = first(r'class="service-accordion-title">\s*<div>(.*?)</div>', part)
        if not name:
            continue

        needs = []
        # Кожна група крові — три вкладені div: іконка рівня, назва групи, текст рівня
        items = re.findall(
            r'requirement-item-icon\s+([a-z]+)".*?'
            r'requirement-item-title">(.*?)</div>.*?'
            r'requirement-item-description">(.*?)</div>',
            part,
            re.S,
        )
        for icon, group, description in items:
            needs.append({
                "group": clean(group),
                "level": ICON_LEVEL.get(icon, icon),
                "description": clean(description),
            })

        centers.append({
            "name": name,
            "address": first(r'class="address contact-info">(.*?)</div>', part),
            "phone": first(r'href="tel:([^"]*)"', part),
            "maps": first(r'class="address-link"[^>]*href="([^"]*)"', part),
            "needs": needs,
        })

    return centers


def fetch_all():
    """Пройти всі регіони і зібрати центри в один список."""
    all_centers = []
    seen = set()

    for slug, region in REGIONS.items():
        try:
            centers = parse_page(get(f"{BASE}/{slug}"))
        except Exception as e:
            print(f"Помилка на регіоні {region}: {e}", file=sys.stderr)
            continue

        for c in centers:
            if c["name"] in seen:
                continue
            seen.add(c["name"])
            c["region"] = region
            all_centers.append(c)

    return all_centers


LABEL = {"high": "ВИСОКА", "medium": "середня", "low": "достатньо"}


def print_table(centers):
    for c in centers:
        print(f"\n[{c.get('region', '—')}] {c['name']}")
        if c["address"]:
            print(f"  {c['address']}")
        if c["phone"]:
            print(f"  {c['phone']}")
        for n in c["needs"]:
            mark = "!" if n["level"] == "high" else " "
            print(f"  {mark} {n['group']:<14} {LABEL.get(n['level'], n['level'])}")
    print(f"\nУсього центрів: {len(centers)}")


def main():
    ap = argparse.ArgumentParser(description="Потреба у крові з donor.utcc.gov.ua")
    ap.add_argument("--json", action="store_true", help="вивести JSON")
    ap.add_argument("-o", "--out", help="записати у файл")
    ap.add_argument("--high", action="store_true", help="лишити тільки високу потребу")
    ap.add_argument("--app", action="store_true", help="формат needs.json для додатку")
    args = ap.parse_args()

    centers = fetch_all()

    if args.app:
        payload, skipped = app_payload(centers)
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(text)
            print(f"Записано {len(payload['centers'])} центрів у {args.out}")
        else:
            print(text)
        if skipped:
            print(f"Без даних у довіднику: {len(skipped)}", file=sys.stderr)
            for name in skipped:
                print(f"  - {name}", file=sys.stderr)
        return

    if args.high:
        for c in centers:
            c["needs"] = [n for n in c["needs"] if n["level"] == "high"]
        centers = [c for c in centers if c["needs"]]

    if args.json or args.out:
        text = json.dumps(centers, ensure_ascii=False, indent=2)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(text)
            print(f"Записано {len(centers)} центрів у {args.out}")
        else:
            print(text)
    else:
        print_table(centers)


if __name__ == "__main__":
    main()
