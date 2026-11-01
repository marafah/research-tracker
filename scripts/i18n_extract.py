"""Tiny gettext extractor + compiler (no GNU gettext needed).

    python scripts/i18n_extract.py extract   # -> locale/messages.json (all msgids)
    python scripts/i18n_extract.py compile   # locale/ar.json -> locale/ar/LC_MESSAGES/django.po/.mo

Arabic translations live in locale/ar.json ({"msgid": "ترجمة"} and plurals as
{"msgid": ["singular", "plural"], ...}). Edit that file to improve wording.
Requires: Babel (pip install Babel).
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STR = r'"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\''


def norm_block(text):
    return re.sub(r"{{\s*([\w.]+)\s*}}", lambda m: "%(" + m.group(1) + ")s", text.replace("%", "%%"))


def extract():
    singles, plurals = {}, {}
    for f in (ROOT / "templates").rglob("*.html"):
        _scan_template(f.read_text(encoding="utf-8"), singles, plurals)
    for f in (ROOT / "templates").rglob("*.txt"):
        _scan_template(f.read_text(encoding="utf-8"), singles, plurals)
    for f in list((ROOT / "tracker").rglob("*.py")) + list((ROOT / "accounts").rglob("*.py")) + [ROOT / "config/settings.py"]:
        if "migrations" in f.parts or f.name == "tests.py":
            continue
        _scan_python(f.read_text(encoding="utf-8"), singles, plurals)
    return singles, plurals


def _scan_template(src, singles, plurals):
    for m in re.finditer(r"{%\s*trans\s+(?:" + STR + r")\s*(?:as\s+\w+\s*)?%}", src):
        singles[m.group(1) if m.group(1) is not None else m.group(2)] = 1
    for m in re.finditer(r"_\((?:" + STR + r")\)", src):
        singles[m.group(1) if m.group(1) is not None else m.group(2)] = 1
    for m in re.finditer(r"{%\s*blocktrans([^%]*)%}(.*?)(?:{%\s*plural\s*%}(.*?))?{%\s*endblocktrans\s*%}", src, re.S):
        if m.group(3) is not None:
            plurals[(norm_block(m.group(2)), norm_block(m.group(3)))] = 1
        else:
            singles[norm_block(m.group(2))] = 1


def _joined(chunk):
    return "".join(a or b for a, b in re.findall(STR, chunk)).replace('\\"', '"').replace("\\'", "'")


def _scan_python(src, singles, plurals):
    for m in re.finditer(r"\b(?:_|_l|gettext|gettext_lazy)\(\s*((?:(?:" + STR + r")\s*)+)\)", src):
        singles[_joined(m.group(1))] = 1
    for m in re.finditer(r"\bngettext\(\s*(" + STR + r")\s*,\s*(" + STR + r")", src):
        plurals[(_joined(m.group(1)), _joined(m.group(4)))] = 1


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "extract"
    singles, plurals = extract()
    if cmd == "extract":
        out = {"singles": sorted(singles), "plurals": sorted(plurals)}
        (ROOT / "locale/messages.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{len(singles)} strings, {len(plurals)} plurals")
        return
    from babel.messages.catalog import Catalog
    from babel.messages.mofile import write_mo
    from babel.messages.pofile import write_po

    ar = json.loads((ROOT / "locale/ar.json").read_text(encoding="utf-8"))
    cat = Catalog(locale="ar", project="Research Tracker", charset="utf-8")
    missing = []
    for s in sorted(singles):
        t = ar.get(s)
        if not t:
            missing.append(s)
        cat.add(s, t or "")
    for sg, pl in sorted(plurals):
        t = ar.get(sg)
        if not t:
            missing.append(sg)
        # Arabic has 6 plural forms; map: 0, 1, 2, few, many, other.
        if isinstance(t, list):
            forms = (t + [t[-1]] * 6)[:6] if len(t) >= 6 else [t[1], t[0], t[1], t[1], t[1], t[1]]
        else:
            forms = [""] * 6
        cat.add((sg, pl), tuple(forms))
    out = ROOT / "locale/ar/LC_MESSAGES"
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "django.po", "wb") as fh:
        write_po(fh, cat, width=0)
    with open(out / "django.mo", "wb") as fh:
        write_mo(fh, cat)
    print(f"compiled; missing translations: {len(missing)}")
    for s in missing:
        print("  MISSING:", repr(s))


if __name__ == "__main__":
    main()
