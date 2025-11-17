import os, glob
from PIL import Image
from ocr import preprocess_for_ocr, ocr_image, extract_fields  # o desde ocr_utils si lo renombraste
import pillow_heif
from ocr import _normalize
from ocr import extract_fields_safely
from db_utils import save_ticket


pillow_heif.register_heif_opener()

# 1) Cambia esto si quieres forzar un archivo concreto:
IMAGE_NAME = None  # ej. "IMG_0964.jpg"  (None = buscar automáticamente)

def pick_image():
    """Si no especificas IMAGE_NAME, busca el primer .jpg/.jpeg/.png en la carpeta."""
    if IMAGE_NAME:
        return IMAGE_NAME
    candidates = []
    for ext in ("*.jpg", "*.jpeg", "*.png"):
        candidates += glob.glob(ext)
    return candidates[0] if candidates else None

def main():
    print("hola mundo en el main")
    print("📂 Carpeta actual:", os.getcwd())
    print("📄 Archivos:", os.listdir("."))

    img_path = pick_image()
    if not img_path:
        print("❌ No encontré ninguna imagen (.jpg/.jpeg/.png) en esta carpeta.")
        print("👉 Pon tu foto junto a main.py o asigna IMAGE_NAME = 'tu_archivo.jpg'")
        return
    print("🖼️ Usando imagen:", img_path)

    # 2) Abrir imagen
    try:
        img = Image.open(img_path).convert("RGB")
    except Exception as e:
        print("❌ No pude abrir la imagen:", e)
        print("Si es .HEIC conviértela a .JPG/.PNG o instala 'pillow-heif'.")
        return

    # Extraer campos de manera segura
    store, date, total, text, preprocessed = extract_fields_safely(img)
    print("\n— Resultados de la extracción —")
    print(f"🏬 Tienda: {store or '—'}")
    print(f"📅 Fecha:  {date or '—'}")
    print(f"💵 Total:  {total or '—'}")

    # 3) Preprocesar y guardar vista previa
    img_bw = preprocess_for_ocr(img)
    try:
        img_bw.save("preprocesada.png")
        print("💾 Guardé 'preprocesada.png' para que veas cómo quedó el binarizado.")
    except Exception as e:
        print("⚠️ No pude guardar preprocesada.png:", e)

    # 4) OCR
    text = ocr_image(img_bw)
    print("\n✅ OCR (primeros 600 caracteres):\n")
    print(text[:600])

    # 5) Extraer campos
    try:
        store, date, total = extract_fields(text)
        print("\n— Campos detectados —")
        print(f"🏬 Tienda: {store or '—'}")
        print(f"📅 Fecha:  {date or '—'}")
        print(f"💵 Total:  {total or '—'}")
        # 6) Guardar en BD
        save_ticket(store, date, total, "MXN", text)
    except Exception as e:
        print("\nℹ️ No se pudieron extraer campos básicos:", e)

if __name__ == "__main__":
    main()
