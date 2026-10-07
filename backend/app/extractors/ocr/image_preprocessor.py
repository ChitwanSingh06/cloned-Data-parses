"""Non-geometric preprocessing only, so OCR bboxes stay in the original page coordinate space."""
import os

import numpy as np
from PIL import Image, ImageOps


def preprocess_image(img: Image.Image) -> Image.Image:
    g = ImageOps.grayscale(img)
    g = ImageOps.autocontrast(g, cutoff=1)
    if os.getenv("PARSE_OCR_DENOISE", "0") != "1":  # fastNlMeans is slow (~seconds/page); opt-in for noisy scans
        return g
    try:
        import cv2
        arr = np.array(g)
        arr = cv2.fastNlMeansDenoising(arr, None, h=7, templateWindowSize=7, searchWindowSize=21)
        return Image.fromarray(arr)
    except Exception:  # OpenCV is optional here
        return g
# TODO: deskew (needs inverse-rotating OCR boxes back into page space).
