import io
import os
import gc
import cv2
import numpy as np
from PIL import Image

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

def refine_image(raw_image_file):
    """
    Takes an uploaded file (raw_image_file is a file-like object, e.g. InMemoryUploadedFile)
    and returns a BytesIO object representing the refined, white-background, CLAHE-enhanced JPEG.
    """
    # Reset stream pointer just in case
    raw_image_file.seek(0)
    
    # Load image from file object
    input_image = Image.open(raw_image_file)
    original_size = input_image.size  # (width, height)
    
    # 3. Downscale large images for rembg processing to prevent OOM
    MAX_REMBG_DIM = 800
    if max(original_size) > MAX_REMBG_DIM:
        ratio = MAX_REMBG_DIM / max(original_size)
        downscaled_size = (int(original_size[0] * ratio), int(original_size[1] * ratio))
        rembg_input = input_image.resize(downscaled_size, Image.Resampling.LANCZOS)
    else:
        rembg_input = input_image
    
    # Run rembg to remove background (returns transparent RGBA) on the optimized size
    rgba_downscaled = remove(rembg_input, session=SESSION)
    rgba_downscaled = rgba_downscaled.convert("RGBA")
    
    # Clean up downscaled input image if we created one
    if rembg_input is not input_image:
        rembg_input.close()
    
    # 4. Upscale the alpha mask back to original resolution and apply to the original image
    if max(original_size) > MAX_REMBG_DIM:
        alpha_mask = rgba_downscaled.split()[3]
        alpha_mask_resized = alpha_mask.resize(original_size, Image.Resampling.BILINEAR)
        rgba_img = input_image.convert("RGBA")
        rgba_img.putalpha(alpha_mask_resized)
        
        # Clean up intermediate mask images
        alpha_mask.close()
        alpha_mask_resized.close()
    else:
        rgba_img = rgba_downscaled
    
    # Create white background
    white_bg = Image.new("RGBA", rgba_img.size, (255, 255, 255, 255))
    white_bg.paste(rgba_img, (0, 0), rgba_img)
    final_img = white_bg.convert("RGB")
    
    # Clean up intermediate rgba images
    rgba_img.close()
    rgba_downscaled.close()
    
    # Convert to OpenCV numpy array (BGR)
    img_np = np.array(final_img)
    img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
    
    # Apply CLAHE on L channel of LAB space for lighting correction
    lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    cl = clahe.apply(l_channel)
    
    limg = cv2.merge((cl, a_channel, b_channel))
    corrected_bgr = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)
    
    # Convert back to RGB for PIL saving
    corrected_rgb = cv2.cvtColor(corrected_bgr, cv2.COLOR_BGR2RGB)
    refined_pil = Image.fromarray(corrected_rgb)
    
    # Save to memory buffer
    output_io = io.BytesIO()
    refined_pil.save(output_io, format="JPEG", quality=90)
    output_io.seek(0)
    
    # Clean up PIL image resources
    refined_pil.close()
    final_img.close()
    white_bg.close()
    input_image.close()
    
    # 5. Explicitly invoke garbage collection to release memory back to the OS
    gc.collect()
    
    return output_io

