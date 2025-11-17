import cv2
import numpy as np
from PIL import Image
import pytesseract
import re
from unidecode import unidecode

def preprocess_for_ocr(pil_img: Image.Image) -> Image.Image:
    """Preprocesa imagen para mejorar OCR (gris + umbral adaptativo)."""
    # PIL -> OpenCV
    img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    bw = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 31, 15
    )
    # OpenCV -> PIL
    return Image.fromarray(bw)

def ocr_image(pil_img: Image.Image) -> str:
    """Ejecuta OCR con Tesseract (siempre en RGB/ndarray)."""
    # Asegura tipo y modo
    if not isinstance(pil_img, Image.Image):
        pil_img = Image.fromarray(pil_img)
    if pil_img.mode not in ("RGB", "L"):
        pil_img = pil_img.convert("RGB")

    arr = np.array(pil_img)  # pytesseract acepta ndarray
    return pytesseract.image_to_string(
        arr,
        lang="spa+eng",
        config="--oem 3 --psm 6"
    )

def extract_fields_safely(pil_img: Image.Image):
    """Intenta con y sin preprocesado y devuelve la mejor extracción."""
    base = pil_img
    if not isinstance(base, Image.Image):
        base = Image.fromarray(base)
    if base.mode not in ("RGB", "L"):
        base = base.convert("RGB")
    base = base.copy()  # evita issues de archivo cerrado

    # 1) Con preprocesado
    img_bw = preprocess_for_ocr(base)
    text1 = ocr_image(img_bw)
    s1, d1, t1 = extract_fields(text1)

    # 2) Sin preprocesado
    text2 = ocr_image(base)
    s2, d2, t2 = extract_fields(text2)

    score1 = sum(x is not None for x in (s1, d1, t1))
    score2 = sum(x is not None for x in (s2, d2, t2))

    if score2 > score1:
        return (s2, d2, t2, text2, False)
    else:
        return (s1, d1, t1, text1, True)

# --- Extractor básico (puedes mejorar luego) ---
RE_TOTAL = re.compile(r'(TOTAL|IMPORTE|A PAGAR|PAGO)[:\s\$]*([0-9]+[.,][0-9]{2})', re.IGNORECASE)
RE_DATE  = re.compile(r'(\d{2}[/-]\d{2}[/-]\d{2,4})')
RE_STORE = re.compile(r'^[A-ZÑÁÉÍÓÚ0-9 \-\.&]{4,}$', re.MULTILINE)

# Meses abreviados en español -> número
MONTHS = {
    "ene": "01", "feb": "02", "mar": "03", "abr": "04", "may": "05", "jun": "06",
    "jul": "07", "ago": "08", "sep": "09", "oct": "10", "nov": "11", "dic": "12"
}

def _normalize(s: str) -> str:
    """Quita acentos, pasa a minúsculas, elimina símbolos raros y colapsa espacios."""
    s = unidecode(s)
    s = s.lower()
    s = re.sub(r"[^\w\s\.\,\:\-/\$]", " ", s)  # deja letras, digitos y separadores comunes
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _find_total(text_norm: str):
    # Acepta 101 o 101.00 o 1,234.56; tolera basura entre palabra clave y número
    money_pat = r"(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})|\d{1,7})"
    pat = re.compile(rf"(total|importe|pagar|pagada|pago)[^\d]{{0,20}}{money_pat}", re.IGNORECASE)
    cands = []
    for m in pat.finditer(text_norm):
        val = m.group(2)
        # normaliza separadores: 1.234,56 -> 1234.56 ; 1,234.56 -> 1234.56 ; 101 -> 101.00
        v = val.replace(" ", "")
        if "," in v and "." in v:
            # si hay ambos, asume formato europeo 1.234,56
            if v.rfind(",") > v.rfind("."):
                v = v.replace(".", "").replace(",", ".")
            else:
                v = v.replace(",", "")  # 1,234.56
        elif "," in v and "." not in v:
            # 1234,56 -> 1234.56  ó  1,234 -> 1234.00 si era miles sin decimales
            if len(v.split(",")[-1]) == 2:
                v = v.replace(",", ".")
            else:
                v = v.replace(",", "")
        # si no tiene decimales, añádelos
        if re.fullmatch(r"\d+", v):
            v = v + ".00"
        try:
            cands.append(float(v))
        except:
            pass
    if cands:
        return f"{max(cands):.2f}"

    # Fallback: busca cualquier número con o sin decimales y toma el mayor
    any_money = re.findall(money_pat, text_norm)
    values = []
    for val in any_money:
        v = val.replace(" ", "")
        if "," in v and "." in v:
            if v.rfind(",") > v.rfind("."):
                v = v.replace(".", "").replace(",", ".")
            else:
                v = v.replace(",", "")
        elif "," in v and "." not in v:
            if len(v.split(",")[-1]) == 2:
                v = v.replace(",", ".")
            else:
                v = v.replace(",", "")
        if re.fullmatch(r"\d+", v):
            v = v + ".00"
        try:
            values.append(float(v))
        except:
            pass
    if values:
        return f"{max(values):.2f}"
    return None


def _find_date(text_norm: str):
    # Formato numérico: dd/mm/aaaa o dd-mm-aa
    m = re.search(r"\b([0-3]?\d)[/\-]([01]?\d)[/\-](\d{2,4})\b", text_norm)
    if m:
        d, mo, y = m.groups()
        if len(y) == 2: y = "20" + y
        return f"{int(d):02d}/{int(mo):02d}/{y}"

    # Variantes con mes textual: “12 nov 2025”, “nov 12 '25”, incluso OCR raros tipo “novi2'25”
    # Normaliza casos donde el OCR confunde 1 con i/l/|
    text_norm2 = re.sub(r"(ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)\s*([iIl\|])", r"\1 1", text_norm)

    # (1) “12 nov 2025” o “12 nov 25”
    m = re.search(r"\b([0-3]?\d)\s*(ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)\w*\s*(\d{2,4})\b", text_norm2)
    if m:
        d, mon, y = m.groups()
        mon = MONTHS[mon[:3]]
        if len(y) == 2: y = "20" + y
        return f"{int(d):02d}/{mon}/{y}"

    # (2) “nov 12 '25” o “nov 12 2025”
    m = re.search(r"\b(ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)\w*\s*([0-3]?\d)\s*[' ]?\s*(\d{2,4})\b", text_norm2)
    if m:
        mon, d, y = m.groups()
        mon = MONTHS[mon[:3]]
        if len(y) == 2: y = "20" + y
        return f"{int(d):02d}/{mon}/{y}"

    return None

def _canonical_brand(line_norm: str):
    # Mapea marcas a un nombre fijo si aparecen en la línea normalizada
    BRAND_MAP = {
        "starbucks": "Starbucks",
        "oxxo": "OXXO",
        "walmart": "Walmart",
        "soriana": "Soriana",
        "heb": "HEB",
        "7-eleven": "7-Eleven",
        "seven": "7-Eleven",
        "chedraui": "Chedraui",
        "farmacia": "Farmacia",
        "the home depot": "The Home Depot",
        "costco": "Costco",
        "sam s": "Sam's Club",
        "sams": "Sam's Club",
    }
    for k, v in BRAND_MAP.items():
        if k in line_norm:
            return v
    return None

def _pretty_line(s: str) -> str:
    # Quita símbolos raros y espacios duplicados; aplica Title Case suave
    s = re.sub(r"[^\w\s\.\-&]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # Evita "Corfree INE" etc. por ahora, mejor devolvemos marca canónica si aplica
    return s.title()

def _find_store(text_raw: str):
    lines = [ln.strip() for ln in text_raw.splitlines() if ln.strip()]
    for ln in lines[:6]:
        ln_norm = _normalize(ln)
        brand = _canonical_brand(ln_norm)
        if brand:
            return brand  # ← nombre limpio
    # Si no hay marca conocida, toma primera línea “prometedora” que no sea dirección
    blacklist = ["calle", "av", "avenida", "col", "cp", "local", "manzana", "monterrey", "nuevo", "leon"]
    for ln in lines[:6]:
        ln_norm = _normalize(ln)
        if not any(w in ln_norm for w in blacklist) and re.search(r"[a-zA-Z]{3,}", ln):
            return _pretty_line(ln)[:60]
    return None


def extract_fields(text: str):
    text_norm = _normalize(text)
    total = _find_total(text_norm)
    date = _find_date(text_norm)
    store = _find_store(text)
    return store, date, total


if __name__ == "__main__":
    # Solo se ejecuta si corres: python ocr.py
    print("Módulo ocr.py listo.")
