import re
import unicodedata
from rapidfuzz import fuzz


def normalize_arabic(text: str) -> str:
    """Normalizes Arabic text for searching and indexing."""
    if not text or not isinstance(text, str):
        return ""
    t = unicodedata.normalize("NFKC", text.strip())
    t = t.replace('\u063e', 'ف')  # ؾ -> ف
    t = t.replace('\u063c', 'غ')  # ؼ -> غ
    t = t.replace('\u063d', 'غ')  # ؽ -> غ
    t = t.replace('\u063b', 'غ')  # ػ -> غ
    t = t.replace('Ž', 'ي')
    t = t.replace('ž', 'ي')
    t = t.replace('Œ', 'ني')
    t = t.replace('•', 'ي')
    t = t.replace('‡', 'س')
    t = t.replace('¦', 'ص')
    t = re.sub(r'\(\d+:dic\)', '', t)
    t = re.sub(r'[\[\]\\.\(\):–›̃̈̄\?«»·¥\d]+', ' ', t)
    t = re.sub(r"[\u064B-\u0652\u0670]", "", t)
    t = re.sub(r"\u0640", "", t)
    t = re.sub(r"[إأآٱ]", "ا", t)
    t = re.sub(r"[ىي]", "ي", t)
    t = re.sub(r"ة", "ه", t)
    t = re.sub(r'\bهللا\b', 'الله', t)
    t = re.sub(r'\bي عل\b', 'علي', t)
    t = re.sub(r'\bبش\s+جوخدار\s+ر\b', 'بشر جوخدار', t)
    t = re.sub(r'\bدمحم\b', 'محمد', t)
    t = re.sub(r'\bعالء\b', 'علاء', t)
    t = re.sub(r'\bبالل\b', 'بلال', t)
    t = re.sub(r'\bجالل\b', 'جلال', t)
    t = re.sub(r'\bهالل\b', 'هلال', t)
    t = re.sub(r'\bطالل\b', 'طلال', t)
    t = re.sub(r'\bحال\b', 'حلا', t)
    t = re.sub(r'\bالحالق\b', 'الحلاق', t)
    t = re.sub(r'\bحالوه\b', 'حلاوه', t)
    t = re.sub(r'\bوالء\b', 'ولاء', t)
    t = re.sub(r'\bالء\b', 'الاء', t)
    t = re.sub(r'\bيارس\b', 'ياسر', t)
    t = re.sub(r'\bايالف\b', 'ايلاف', t)
    t = re.sub(r'\bليالس\b', 'ليلاس', t)
    t = re.sub(r'\bالجاللي\b', 'الجلالي', t)
    t = re.sub(r'\bالعرج\b', 'الاعرج', t)
    t = re.sub(r'\bخاليلي\b', 'خلايلي', t)
    t = re.sub(r'\bعبدهللا\b', 'عبدالله', t)
    t = re.sub(r'\bعبد\s+', 'عبد', t)
    t = re.sub(r'\bابو\s+', 'ابو', t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def calculate_similarity(query: str, target: str) -> float:
    """Returns similarity percentage between two Arabic names (0.0 to 100.0)."""
    q = normalize_arabic(query)
    t = normalize_arabic(target)
    if not q or not t:
        return 0.0
    return fuzz.token_sort_ratio(q, t)


def decode_pdf_arabic(text: str) -> str:
    """Decodes corrupted visual LTR university PDF Arabic text."""
    if not text or not isinstance(text, str):
        return ""
    norm = unicodedata.normalize("NFKC", text.strip())
    lookup = {
        "حجان": "ناجح",
        "بسار": "راسب",
        "لوال": "الاول",
        "يناثلا": "الثاني",
    }
    if norm in lookup:
        return lookup[norm]
    words = norm.split()
    fixed_words = []
    for w in words:
        if re.search(r"[\u0600-\u06FF]", w):
            rev = w[::-1].replace("ٌ", "ي")
            rev = re.sub(r"\bاال", "ال", rev)
            fixed_words.append(lookup.get(rev, rev))
        else:
            fixed_words.append(w)
    return " ".join(fixed_words[::-1])
