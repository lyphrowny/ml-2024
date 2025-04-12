from pickletools import optimize
import pytesseract
import cv2
import numpy as np
from operator import itemgetter
import re
from datetime import datetime
from string import ascii_letters, digits
import re
from datetime import datetime

from string import ascii_letters, digits

from thefuzz import process
import json

from pathlib import Path

from .race_result import RaceResult

root = Path(__file__).parent
pytesseract.pytesseract.tesseract_cmd = root / "tesseract/tesseract.exe"
imgs_path = root / "race_photo_results"


participants = (
    (root / "participant_fullnames.txt").read_text(encoding="utf-8").splitlines()
)
race_types_ = (root / "race_types.txt").read_text(encoding="utf-8").splitlines()
race_types = {}
for race_type in race_types_:
    main_type, *rest = race_type.split(",")
    rest.append(race_type)
    for r in rest:
        race_types[r] = main_type


def find_closest_participant(ocr_participant):
    guesses = (
        (guess, process.extractOne(guess, participants))
        for guess in ocr_participant.strip().splitlines()
    )
    ocr_text, (guessed, confidence) = max(
        guesses, key=lambda g: g[1][1], default=(ocr_participant, ("", 0))
    )
    return guessed, reduce_confidence(ocr_text, confidence)


def reduce_confidence(ocr_participant, confidence):
    n_upper = (
        sum(ch.isupper() for ch in ocr_participant) - ocr_participant[~0:].isupper()
    )
    if n_upper < 2:
        confidence -= 15
        if len(ocr_participant) < 8:
            confidence -= 15
    return max(confidence, 0)


def find_closest_race_type(ocr_race_type):
    guess, confidence = process.extractOne(ocr_race_type.strip(), race_types.keys())
    return race_types[guess], confidence


def find_contours(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    thresh = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 11, 2
    )
    # Detect horizontal/vertical lines
    kernel_h = np.ones((1, 20), np.uint8)
    kernel_v = np.ones((20, 1), np.uint8)
    horizontal = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel_h)
    vertical = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel_v)

    # Combine lines
    grid = cv2.add(horizontal, vertical)

    # Find contours of cells
    contours, _ = cv2.findContours(grid, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    return contours


def filter_cnt(gray_img, cnt):
    x, y, w, h = cv2.boundingRect(cnt)
    iw, ih = gray_img.shape
    return (
        w > h
        and 11 < w / h < 20
        and 130 < np.median(gray[y : y + h, x : x + w]) < 230
        and 0.9 < w * h / (iw * ih) * 100 < 2.9
    )


def find_header_contours(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)

    # Create horizontal kernel to merge text in same line
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (20, 1))
    dilated = cv2.dilate(thresh, kernel, iterations=1)

    # Find contours of text blocks
    contours, _ = cv2.findContours(dilated, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    return img


def filter_header_cnt(himg, cnt):
    x, y, w, h = cv2.boundingRect(cnt)
    iw, ih, _ = himg.shape
    gray = cv2.cvtColor(himg, cv2.COLOR_BGR2GRAY)
    return w > h and 4 < w / h < 35 and 0.3 < w * h / (iw * ih) * 100 < 6


def _ocr(img_part, chars=None, lang="rus"):
    if chars is None:
        chars = "абвгдеёжзийклмнопрстуфхцчшщъыэюя"
        chars += chars.upper() + " "
    return pytesseract.image_to_string(
        img_part,
        config=f"-c tessedit_char_whitelist={chars} -c preserve_interword_spaces=1",
        lang=lang,
    )


def _ocr_with_fallback(img, slices, resize_to, optional_stage=None, **ocr_params):
    optional_stage = (lambda t: t) if optional_stage is None else optional_stage

    def parse_text():
        text = _ocr(t_img, **ocr_params)
        return optional_stage(text).strip()

    t_img = img[*slices].copy()
    text = parse_text()
    if not text:
        t_img = cv2.resize(t_img, resize_to, interpolation=cv2.INTER_CUBIC)
        text = parse_text()
    return text


def match_date(orc_date):
    date_match = re.search(r"\b\d{2}\.\d{2}\.\d{4}\b", ocr_date.strip())
    try:
        race_date = (
            datetime.strptime(date_match.group(0), "%d.%m.%Y").date()
            if date_match
            else ocr_date.strip()
        )
    except ValueError:
        race_date = ""
    return race_date


def parse_header(img, upper_y_cell):
    x, y, w, h = cv2.boundingRect(upper_y_cell)
    ih, iw, _ = img.shape
    y_b = 0
    if y / ih > 0.18:
        # make the header 18% at max of the image height
        y_b = int(ih * (y / ih - 0.18))
    himg = img[y_b:y].copy()

    contours = find_header_contours(himg)
    contours = sorted(
        (cnt for cnt in contours if filter_header_cnt(himg, cnt)),
        key=lambda c: cv2.boundingRect(c)[1::-1],
    )

    race_type_cnt = contours[0]
    race_date_cnt = contours[2]

    margin = 3
    race_type_margin = 6
    date_margin = 2  # px

    x, y, w, h = cv2.boundingRect(race_type_cnt)
    y_slice = slice(y - race_type_margin, y + h + race_type_margin)
    x_slice = slice(x - margin, x + w + margin)
    race_type = _ocr_with_fallback(
        himg,
        (y_slice, x_slice),
        resize_to=(w * 2, h * 2),
        optional_stage=find_closest_race_type,
        chars=f"{ascii_letters}{digits}-/",
        lang="eng",
    )
    # t_img = himg[y_slice, x_slice]
    # ocr_race_type = _ocr(t_img, f"{ascii_letters}{digits}-/", lang="eng")
    # race_type = find_closest_race_type(ocr_race_type)

    x, y, w, h = cv2.boundingRect(race_date_cnt)
    y_slice = slice(y - date_margin, y + h + date_margin)
    x_slice = slice(x + w // 3 - margin, x + w + margin)
    rh, rw, _ = himg[y_slice, x_slice].shape
    race_date = _ocr_with_fallback(
        himg,
        (y_slice, x_slice),
        resize_to=(rw, rh),
        optional_stage=mathc_date,
        chars=f"{ascii_letters}{digits}-/",
        lang="end",
    )

    # t_img = himg[y_slice, x_slice].copy()
    # ocr_date = _ocr(t_img, f"{digits}.", lang="eng")

    # race_date = match_date(ocr_date)

    # ocr_date = _ocr(t_img, f"{digits}.", lang="eng")

    # date_match = re.search(r"\b\d{2}\.\d{2}\.\d{4}\b", ocr_date.strip())
    # try:
    #     race_date = (
    #         datetime.strptime(date_match.group(0), "%d.%m.%Y").date()
    #         if date_match
    #         else ocr_date.strip()
    #     )
    # except ValueError:
    #     race_date = ""
    # if not race_date:
    #     h, w, _ = t_img.shape
    #     t_img = cv2.resize(t_img, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)
    #     ocr_date = _ocr(t_img, f"{digits}.", lang="eng")

    #     race_date = match_date(ocr_date)

    return race_type, race_date


def parse_participants(img, margin=3, resize_coeff=2):
    cells = []
    ih, iw, _ = img.shape
    # Find contours of cells
    contours = find_contours(img)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    contours = sorted(
        (cnt for cnt in contours if filter_cnt(gray, cnt)),
        key=lambda c: cv2.boundingRect(c)[1::-1],
    )
    n_cnt = 0
    success = 0

    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        n_cnt += 1

        y_slice = slice(y + margin, y + h - margin)
        x_slice = slice(x + margin, x + w // 2 - margin)
        resize_to = (w // 2 * resize_coeff, h * resize_coeff)
        line_text = _ocr_with_fallback(img, (y_slice, x_slice), resize_coeff)

        # t_img = img[
        #     y + margin : y + h - margin, x + margin : x + int(w / 2) - margin
        # ].copy()
        # line_text = _ocr(t_img)

        # if not line_text.strip():
        #     t_img = cv2.resize(
        #         t_img,
        #         (int(w / 2) * resize_coeff, h * resize_coeff),
        #         interpolation=cv2.INTER_CUBIC,
        #     )
        #     line_text = _ocr(t_img)

        # print(f"{line_text.strip()!r}, {find_closest_participant(line_text)}")
        if line_text.strip():
            success += 1
    # print(f"success rate {success} / {n_cnt} ({success / n_cnt:.2%})")
    # print(n_cnt)
    # print(es24_img)
    # print()


def ocr_image(img_path):
    img = cv2.imread(img_path)

    participants, upper_y_cell = parse_participants(img)
    race_type, race_date = parse_header(img, upper_y_cell)

    return RaceResult(race_type, race_date, participants)
