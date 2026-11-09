#!/usr/bin/env python3
"""Build cookbook.html from the recipe files in recipes/.

Run from the CookBook folder:  python build_cookbook.py
The page is fully self-contained, so you can double-click it to open.
"""
import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RECIPES = ROOT / "recipes"
OUT = ROOT / "cookbook.html"


def parse_value(v):
    v = v.strip()
    if v.startswith("[") and v.endswith("]"):
        return [x.strip() for x in v[1:-1].split(",") if x.strip()]
    if re.fullmatch(r"-?\d+(\.\d+)?", v):
        return float(v) if "." in v else int(v)
    return v


def strip_comment(line):
    # Remove trailing "# comment" (needs a space before #, so URLs are safe)
    return re.sub(r"\s+#.*$", "", line)


def parse_front_matter(text):
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.S)
    if not m:
        return {}, text
    meta, current = {}, None
    for raw in m.group(1).splitlines():
        line = strip_comment(raw).rstrip()
        if not line.strip():
            continue
        if raw.startswith((" ", "\t")) and current:
            k, _, v = line.strip().partition(":")
            meta[current][k.strip()] = parse_value(v)
            continue
        k, _, v = line.partition(":")
        k = k.strip()
        if v.strip() == "":
            meta[k] = {}
            current = k
        else:
            meta[k] = parse_value(v)
            current = None
    return meta, m.group(2)


def inline(s):
    s = html.escape(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])_(.+?)_(?![\w*])", r"<em>\1</em>", s)
    s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
    return s


FRAC = {"½": .5, "¼": .25, "¾": .75, "⅓": 1/3, "⅔": 2/3, "⅛": .125, "⅜": .375, "⅝": .625, "⅞": .875}
NUM = r"(?:\d+\s+[½¼¾⅓⅔⅛⅜⅝⅞]|\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?|[½¼¾⅓⅔⅛⅜⅝⅞])"
QTY_RE = re.compile(rf"^({NUM})(?:\s*[–-]\s*({NUM}))?(?=\s|$)")


def num_value(t):
    total = 0.0
    for part in t.split():
        if part in FRAC:
            total += FRAC[part]
        elif "/" in part:
            a, b = part.split("/")
            total += int(a) / int(b)
        elif part[-1] in FRAC:
            total += float(part[:-1]) + FRAC[part[-1]]
        else:
            total += float(part)
    return total


def scalable(item):
    """Wrap a leading quantity (e.g. '1 ½', '¾', '4–5') so the page can rescale it."""
    m = QTY_RE.match(item)
    if not m:
        return inline(item)
    lo = num_value(m.group(1))
    hi = num_value(m.group(2)) if m.group(2) else ""
    span = f'<span class="qty" data-q="{lo}" data-q2="{hi}">{html.escape(m.group(0))}</span>'
    return span + inline(item[m.end():])


UNITS = {
    "lb": "lb", "lbs": "lb", "pound": "lb", "pounds": "lb",
    "oz": "oz", "ounce": "oz", "ounces": "oz",
    "cup": "cup", "cups": "cup",
    "tbsp": "tbsp", "tablespoon": "tbsp", "tablespoons": "tbsp",
    "tsp": "tsp", "teaspoon": "tsp", "teaspoons": "tsp",
    "g": "g", "gram": "g", "grams": "g", "kg": "kg", "ml": "ml", "l": "l",
    "clove": "clove", "cloves": "clove", "bunch": "bunch", "bunches": "bunch",
    "can": "can", "cans": "can", "container": "container", "containers": "container",
    "package": "package", "packages": "package", "pkg": "package",
    "slice": "slice", "slices": "slice", "stick": "stick", "sticks": "stick",
    "pinch": "pinch", "dash": "dash", "head": "head", "heads": "head",
}


# Units in the same group are added together on the shopping list
UNIT_GROUP = {"tsp": "vol", "tbsp": "vol", "cup": "vol", "oz": "wt", "lb": "wt"}


def shop_key(name):
    k = re.sub(r"\(.*?\)", "", name.lower())
    k = re.sub(r"[^a-z ]", " ", k)
    words = k.split()
    if words and len(words[-1]) > 3 and words[-1].endswith("s") and not words[-1].endswith("ss"):
        words[-1] = words[-1][:-1]
    return " ".join(words)


def parse_ingredient(item):
    """Split an ingredient line into amount, unit and item for the shopping list."""
    item = re.sub(r"\*\*|`", "", item).strip()
    m = QTY_RE.match(item)
    q = q2 = None
    rest = item
    if m:
        q = num_value(m.group(1))
        q2 = num_value(m.group(2)) if m.group(2) else None
        rest = item[m.end():].strip()
    unit = ""
    if q is not None:
        w = re.match(r"^([A-Za-z]+)\.?\b\s*", rest)
        if w and w.group(1).lower() in UNITS:
            unit = UNITS[w.group(1).lower()]
            rest = rest[w.end():]
    # drop prep notes after a comma ("diced", "to taste") for the list name
    name = re.split(r",\s", rest, maxsplit=1)[0].strip() or rest
    return {"q": q, "q2": q2, "unit": unit, "name": name,
            "key": shop_key(name) + "|" + UNIT_GROUP.get(unit, unit), "raw": item}


def ingredient_list(md):
    out = []
    for line in md.splitlines():
        t = line.strip()
        if t.startswith(("- ", "* ")):
            out.append(parse_ingredient(t[2:]))
    return out


def md_to_html(md, scale=False):
    out, mode = [], None

    def close():
        nonlocal mode
        if mode:
            out.append(f"</{mode}>")
            mode = None

    for line in md.splitlines():
        t = line.strip()
        if not t:
            close()
            continue
        if t.startswith("|"):
            continue  # tables (nutrition) are rendered from structured data
        if re.match(r"^\d+\.\s", t):
            if mode != "ol":
                close(); out.append("<ol>"); mode = "ol"
            out.append("<li>" + inline(re.sub(r"^\d+\.\s+", "", t)) + "</li>")
        elif t.startswith(("- ", "* ")):
            if mode != "ul":
                close(); out.append("<ul>"); mode = "ul"
            out.append("<li>" + (scalable(t[2:]) if scale else inline(t[2:])) + "</li>")
        elif re.fullmatch(r"\*\*(.+)\*\*", t):
            close(); out.append("<h4>" + inline(t[2:-2]) + "</h4>")
        else:
            close(); out.append("<p>" + inline(t) + "</p>")
    close()
    return "\n".join(out)


def split_sections(body):
    intro, sections, cur = [], {}, None
    for line in body.splitlines():
        if line.startswith("# "):
            continue
        h = re.match(r"^##\s+(.*)", line)
        if h:
            cur = h.group(1).strip()
            sections[cur] = []
        elif cur:
            sections[cur].append(line)
        else:
            intro.append(line)
    return "\n".join(intro).strip(), {k: "\n".join(v).strip() for k, v in sections.items()}


def minutes(t):
    if not isinstance(t, str):
        return int(t or 0)
    total = 0
    for n, unit in re.findall(r"(\d+)\s*(hr|hour|h|min|m)", t.lower()):
        total += int(n) * (60 if unit.startswith("h") else 1)
    return total


def as_list(v):
    if v in (None, "", {}):
        return []
    return v if isinstance(v, list) else [str(v)]


def load():
    recipes = []
    for f in sorted(RECIPES.glob("*.md")):
        meta, body = parse_front_matter(f.read_text(encoding="utf-8"))
        intro, sec = split_sections(body)
        nutrition_note = ""
        for k in list(sec):
            if k.lower().startswith("nutrition"):
                notes = [l.strip() for l in sec.pop(k).splitlines()
                         if l.strip() and not l.strip().startswith("|")]
                nutrition_note = md_to_html("\n".join(notes))
        n = meta.get("nutrition_per_serving") or {}
        src = str(meta.get("source", ""))
        recipes.append({
            "id": f.stem,
            "file": f"recipes/{f.name}",
            "title": meta.get("title", f.stem),
            "meal_type": as_list(meta.get("meal_type")),
            "flavor": as_list(meta.get("flavor")),
            "cuisine": as_list(meta.get("cuisine")),
            "complexity": str(meta.get("complexity", "")),
            "prep_time": str(meta.get("prep_time", "")),
            "cook_time": str(meta.get("cook_time", "")),
            "prep_min": minutes(meta.get("prep_time", "")),
            "total_min": minutes(meta.get("prep_time", "")) + minutes(meta.get("cook_time", "")),
            "servings": meta.get("servings", ""),
            "source": src,
            "source_is_url": src.startswith("http"),
            "nutrition": {
                "calories": n.get("calories"),
                "protein": n.get("protein_g"),
                "carbs": n.get("carbs_g"),
                "fat": n.get("fat_g"),
            },
            "intro": md_to_html(intro),
            "shopping": ingredient_list(sec.get("Ingredients", "")),
            "ingredients": md_to_html(sec.get("Ingredients", ""), scale=True),
            "equipment": md_to_html(sec.get("Equipment", "")),
            "instructions": md_to_html(sec.get("Instructions", "")),
            "nutrition_note": nutrition_note,
            "notes": md_to_html(sec.get("Notes", "")),
        })
    return recipes


def main():
    recipes = load()
    template = (ROOT / "cookbook_template.html").read_text(encoding="utf-8")
    data = json.dumps(recipes, ensure_ascii=False).replace("</", "<\\/")
    OUT.write_text(template.replace("/*__RECIPES__*/[]", data), encoding="utf-8")
    print(f"Built {OUT.name} with {len(recipes)} recipes.")


if __name__ == "__main__":
    main()
