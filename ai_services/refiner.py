import io
import os
import gc
import logging
import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# 1. Set environment variables to limit thread usage BEFORE importing rembg (ONNX Runtime)
# For an 8GB RAM CPU-only system, 2 threads are optimal to prevent system freezes.
os.environ["OMP_NUM_THREADS"] = "2"
os.environ["MKL_NUM_THREADS"] = "2"
os.environ["OPENBLAS_NUM_THREADS"] = "2"
os.environ["VECLIB_MAXIMUM_THREADS"] = "2"
os.environ["NUMEXPR_NUM_THREADS"] = "2"

from rembg import new_session, remove

# 2. Pre-initialize the lightweight u2netp session globally to avoid re-creation overhead
try:
    SESSION = new_session("u2netp")
except Exception:
    SESSION = None

def refine_image(raw_image_file, enhancements=None):
    """
    Takes an uploaded file (raw_image_file is a file-like object, e.g. InMemoryUploadedFile)
    and an optional list of enhancements to apply.

    enhancements: list of strings from:
        'bg_removal'    – remove background, place on white
        'lighting_fix'  – CLAHE contrast/lighting correction
        'sharpness'     – unsharp mask sharpening
        'color_bal'     – saturation boost
        'auto_enhance'  – shortcut for all of the above

    If enhancements is None or empty, the raw image is returned as-is (just re-encoded as JPEG).
    Returns a BytesIO object.
    """
    if enhancements is None:
        enhancements = []
    
    # 'auto_enhance' expands to all other tools
    if 'auto_enhance' in enhancements:
        enhancements = ['bg_removal', 'lighting_fix', 'sharpness', 'color_bal']

    do_bg      = 'bg_removal'   in enhancements
    do_light   = 'lighting_fix' in enhancements
    do_sharp   = 'sharpness'    in enhancements
    do_color   = 'color_bal'    in enhancements
    # Reset stream pointer
    raw_image_file.seek(0)
    
    # Safely load the image and verify dimensions before full decompression to RGB
    try:
        input_image = Image.open(raw_image_file)
        
        MAX_SAFE_DIMENSION = 4096
        if max(input_image.size) > MAX_SAFE_DIMENSION:
            input_image.close()
            raise ValueError(f"Image dimensions {input_image.size} exceed the safe limit of {MAX_SAFE_DIMENSION}px")
            
        input_image = input_image.convert("RGB")
    except Image.DecompressionBombError as e:
        raise ValueError("Image exceeds maximum allowed pixel count (Decompression Bomb protection)") from e
        
    original_size = input_image.size  # (width, height)

    # --- If no enhancements selected, return raw image re-encoded as JPEG ---
    if not (do_bg or do_light or do_sharp or do_color):
        output_io = io.BytesIO()
        input_image.save(output_io, format="JPEG", quality=92)
        output_io.seek(0)
        input_image.close()
        gc.collect()
        return output_io

    # ---- Background Removal ----
    if do_bg:
        if SESSION is not None:
            MAX_REMBG_DIM = 800
            if max(original_size) > MAX_REMBG_DIM:
                ratio = MAX_REMBG_DIM / max(original_size)
                downscaled_size = (int(original_size[0] * ratio), int(original_size[1] * ratio))
                rembg_input = input_image.resize(downscaled_size, Image.Resampling.LANCZOS)
            else:
                rembg_input = input_image

            rgba_downscaled = remove(rembg_input, session=SESSION).convert("RGBA")
            if rembg_input is not input_image:
                rembg_input.close()

            if max(original_size) > MAX_REMBG_DIM:
                alpha_mask = rgba_downscaled.split()[3]
                alpha_mask_resized = alpha_mask.resize(original_size, Image.Resampling.BILINEAR)
                rgba_img = input_image.convert("RGBA")
                rgba_img.putalpha(alpha_mask_resized)
                alpha_mask.close()
                alpha_mask_resized.close()
            else:
                rgba_img = rgba_downscaled

            white_bg = Image.new("RGBA", rgba_img.size, (255, 255, 255, 255))
            white_bg.paste(rgba_img, (0, 0), rgba_img)
            working = white_bg.convert("RGB")
            rgba_img.close()
            rgba_downscaled.close()
            white_bg.close()
            input_image.close()
            input_image = working
        else:
            logger.warning("Background removal requested, but rembg SESSION is not initialized; skipping bg_removal step.")

    # ---- OpenCV-based enhancements (lighting, sharpness, color) ----
    if do_light or do_sharp or do_color:
        img_np  = np.array(input_image)
        img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

        if do_light:
            # CLAHE on L channel of LAB for lighting correction
            lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)
            l_ch, a_ch, b_ch = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            img_bgr = cv2.cvtColor(cv2.merge((clahe.apply(l_ch), a_ch, b_ch)), cv2.COLOR_LAB2BGR)

        if do_sharp:
            # Unsharp mask sharpening
            blur = cv2.GaussianBlur(img_bgr, (0, 0), 3)
            img_bgr = cv2.addWeighted(img_bgr, 1.5, blur, -0.5, 0)

        if do_color:
            # Mild saturation boost via HSV
            hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV).astype(np.float32)
            hsv[:, :, 1] = np.clip(hsv[:, :, 1] * 1.25, 0, 255)
            img_bgr = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

        corrected_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        refined_pil = Image.fromarray(corrected_rgb)
        input_image.close()
        input_image = refined_pil

    # ---- Save to BytesIO ----
    output_io = io.BytesIO()
    input_image.save(output_io, format="JPEG", quality=90)
    output_io.seek(0)
    input_image.close()

    gc.collect()
    return output_io

