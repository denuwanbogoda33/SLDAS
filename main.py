"""
SLDAS Ultimate — Sri Lankan Atmospheric Alert System
=====================================================
This build merges the two earlier SLDAS prototypes into one app:

  - The "modern glassmorphism" dashboard, Climate Outlook, Weather
    Graphics, Advisories and Settings pages.
  - The "minimalist" build's Emergency Hub (hotlines + SOPs) and
    Live Radar (Windy embed) pages.
  - A single, reusable AI Analysis page (Gemini-powered) that replaces
    the three separate AI code paths from the two originals.

Bug fixed from the previous build
----------------------------------
The screenshot you sent showed raw Markdown ("### **Day 1:**" etc.)
printed literally on screen. That happened because the AI text was
being shown in a plain QLabel, which cannot render Markdown — it just
prints the ** and # characters as-is. Every place that shows AI text
now uses a small `MarkdownView` widget (a borderless, read-only,
auto-growing QTextEdit) that actually renders Markdown into bold text,
headings and bullet lists.

Other fixes
-----------
  - Removed the hardcoded Gemini API key that was sitting in plain
    text in one of the source files (see the chat reply for why that
    matters — please rotate that key).
  - Removed a paragraph of fabricated "2026 El Niño" forecast text
    that was hardcoded into the dashboard as if it were live data.
  - "Simple Mode" toggle: AI explanations can be written in plain,
    teenager-friendly language, or a more technical/detailed mode.
  - Small color-coded Risk badges (Low / Moderate / High) so the
    numbers are easy to read at a glance, not just raw figures.

Requirements
------------
    pip install PyQt5 requests --break-system-packages
    # optional, for PDF thumbnail previews:
    pip install pymupdf --break-system-packages
    # optional, for the Live Radar page:
    pip install PyQtWebEngine --break-system-packages

Run
---
    python sldas_ultimate.py
"""

import hashlib
import json
import os
import re
import sys
from datetime import datetime

import requests

from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize, QSettings, QUrl, QPointF
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QColor, QMovie, QImage, QPen, QPolygonF
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton, QVBoxLayout,
    QHBoxLayout, QGridLayout, QFrame, QScrollArea, QStackedWidget,
    QTextEdit, QLineEdit, QSystemTrayIcon, QMenu, QAction, QSizePolicy,
    QGraphicsDropShadowEffect, QComboBox, QFormLayout, QCheckBox,
    QDialog,
)

try:
    from PyQt5.QtWebEngineWidgets import QWebEngineView
    HAS_WEBENGINE = True
except ImportError:
    QWebEngineView = None
    HAS_WEBENGINE = False

try:
    import fitz  # PyMuPDF - optional, used to render a PDF first-page thumbnail
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False

try:
    from PyQt5 import sip
except ImportError:
    import sip  # some PyQt5 builds expose sip as a top-level module

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

DATA_URL = "https://meteo.gov.lk/content.json"
BASE_SITE = "https://meteo.gov.lk/"
LOCAL_CACHE_FILE = os.path.join(os.path.expanduser("~"), ".sldas_cache.json")

MEDIA_CACHE_DIR = os.path.join(os.path.expanduser("~"), ".sldas_media_cache")
os.makedirs(MEDIA_CACHE_DIR, exist_ok=True)

OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

SRI_LANKA_CITIES = [
    ("Thelijjawila", 6.7475, 80.1975),
    ("Colombo", 6.9271, 79.8612),
    ("Sri Jayawardenepura Kotte", 6.8833, 79.9072),
    ("Kandy", 7.2906, 80.6337),
    ("Galle", 6.0535, 80.2210),
    ("Jaffna", 9.6615, 80.0255),
    ("Negombo", 7.2008, 79.8737),
    ("Trincomalee", 8.5874, 81.2152),
    ("Batticaloa", 7.7310, 81.6747),
    ("Anuradhapura", 8.3114, 80.4037),
    ("Kurunegala", 7.4863, 80.3647),
    ("Ratnapura", 6.6828, 80.4014),
    ("Badulla", 6.9934, 81.0550),
    ("Matara", 5.9549, 80.5550),
    ("Nuwara Eliya", 6.9497, 80.7891),
    ("Dambulla", 7.8742, 80.6511),
    ("Matale", 7.4675, 80.6234),
    ("Kalmunai", 7.4167, 81.8167),
    ("Vavuniya", 8.7514, 80.4971),
    ("Hambantota", 6.1241, 81.1185),
    ("Puttalam", 8.0362, 79.8283),
]

PRIMARY_CLIMATE_LOCATION = {
    "name": "Thelijjawila, Sri Lanka",
    "latitude": 6.7475,
    "longitude": 80.1975,
}

WEATHER_CODE_MAP = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    56: "Light freezing drizzle", 57: "Dense freezing drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    66: "Light freezing rain", 67: "Dense freezing rain",
    71: "Slight snow fall", 73: "Moderate snow fall", 75: "Heavy snow fall",
    77: "Snow grains",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}

DEFAULT_AI_GEMINI_API_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent"

FONT_SCALE_OPTIONS = {
    "Small": 0.85,
    "Medium": 1.0,
    "Large (Recommended)": 1.2,
    "Extra Large": 1.4,
}

AI_LANGUAGE_OPTIONS = {
    "English": "English",
    "සිංහල": "Sinhala",
}

REFRESH_INTERVAL_OPTIONS = {
    "Every 5 minutes": 5 * 60 * 1000,
    "Every 10 minutes": 10 * 60 * 1000,
    "Every 15 minutes": 15 * 60 * 1000,
    "Every 30 minutes": 30 * 60 * 1000,
}

EMERGENCY_HOTLINES = [
    ("Disaster Management Center", "117"),
    ("Police Emergency", "119"),
    ("Ambulance", "1990"),
    ("Fire & Rescue", "110"),
]

SAFETY_SOPS = [
    ("Tsunami", "Move to high ground (10m+) or 2km inland immediately if you feel a strong quake or hear a siren. Don't wait for an official announcement if the ground is still shaking."),
    ("Flash floods", "Never drive or walk through moving water — 15cm can knock you off your feet, 30cm can float a car. Move to higher floors or higher ground."),
    ("Lightning", "Unplug electronics, stay off balconies, and avoid open fields, isolated trees and metal fences until 30 minutes after the last thunder you hear."),
    ("Heavy rain / landslide risk", "If you live on a slope and see new cracks in the ground, tilting trees, or muddy water from a hillside, evacuate — don't wait to 'see if it gets worse'."),
]

# --------------------------------------------------------------------------- #
# Color palette
# --------------------------------------------------------------------------- #

COL_BG          = "#0f1420"
COL_BG_2        = "#141b2b"
COL_SIDEBAR     = "#0b0f18"
COL_CARD        = "#1a2334"
COL_CARD_HOVER  = "#212c42"
COL_CARD_BORDER = "#26314a"
COL_ACCENT      = "#4fd1c5"
COL_ACCENT_2    = "#5b8def"
COL_WARN        = "#f6ad55"
COL_DANGER      = "#f56565"
COL_TEXT        = "#e8ecf3"
COL_TEXT_DIM    = "#8a93a6"
COL_TEXT_FAINT  = "#5c6478"


def build_qss(scale=1.0):
    def px(n):
        return f"{round(n * scale)}px"

    return f"""
QMainWindow {{ background-color: {COL_BG}; }}

QWidget#Sidebar {{
    background-color: {COL_SIDEBAR};
    border-right: 1px solid {COL_CARD_BORDER};
}}

QLabel#LogoTitle {{ color: {COL_ACCENT}; font-size: {px(22)}; font-weight: 700; }}
QLabel#LogoSub {{ color: {COL_TEXT_FAINT}; font-size: {px(11)}; }}

QPushButton#NavBtn {{
    text-align: left;
    color: {COL_TEXT_DIM};
    background-color: transparent;
    border: none;
    padding: 12px 16px;
    font-size: {px(14)};
    border-radius: 8px;
    margin: 2px 10px;
}}
QPushButton#NavBtn:hover {{ background-color: {COL_CARD}; color: {COL_TEXT}; }}
QPushButton#NavBtn:checked {{
    background-color: {COL_CARD};
    color: {COL_ACCENT};
    font-weight: 600;
    border-left: 3px solid {COL_ACCENT};
}}

QWidget#TopBar {{ background-color: {COL_BG_2}; border-bottom: 1px solid {COL_CARD_BORDER}; }}
QLabel#PageTitle {{ color: {COL_TEXT}; font-size: {px(19)}; font-weight: 700; }}
QLabel#Countdown {{ color: {COL_TEXT_FAINT}; font-size: {px(12)}; }}
QLabel#LastUpdated {{ color: {COL_TEXT_DIM}; font-size: {px(12)}; }}

QPushButton#RefreshBtn {{
    background-color: {COL_ACCENT};
    color: #04211f;
    border: none;
    border-radius: 8px;
    padding: 10px 20px;
    font-weight: 700;
    font-size: {px(13)};
}}
QPushButton#RefreshBtn:hover {{ background-color: {COL_ACCENT_2}; color: white; }}
QPushButton#RefreshBtn:pressed {{ background-color: #3fb6ab; }}

QPushButton.ActionBtn {{
    background-color: {COL_CARD_HOVER};
    color: {COL_TEXT};
    border: 1px solid {COL_CARD_BORDER};
    border-radius: 8px;
    padding: 10px 18px;
    font-size: {px(13)};
    font-weight: 600;
}}
QPushButton.ActionBtn:hover {{ border: 1px solid {COL_ACCENT}; color: {COL_ACCENT}; }}
QPushButton.ActionBtn:disabled {{ color: {COL_TEXT_FAINT}; border: 1px solid {COL_CARD_BORDER}; }}

QWidget#Content {{ background-color: {COL_BG}; }}

QFrame.Card {{
    background-color: {COL_CARD};
    border: 1px solid {COL_CARD_BORDER};
    border-radius: 12px;
}}
QFrame.DangerCard {{
    background-color: #241417;
    border: 1px solid #3d1c22;
    border-radius: 12px;
}}

QLabel.SectionTitle {{ color: {COL_TEXT}; font-size: {px(22)}; font-weight: 700; }}
QLabel.SectionSubtitle {{ color: {COL_TEXT_DIM}; font-size: {px(13)}; }}

QLabel.CardHeading {{ color: {COL_ACCENT}; font-size: {px(16)}; font-weight: 700; }}
QLabel.DangerHeading {{ color: {COL_DANGER}; font-size: {px(16)}; font-weight: 700; }}
QLabel.CardLabel {{ color: {COL_TEXT}; font-size: {px(14)}; font-weight: 600; }}
QLabel.CardStatus {{ color: {COL_TEXT_DIM}; font-size: {px(13)}; }}
QLabel.CardIcon {{ font-size: {px(26)}; }}
QLabel.Body {{ color: {COL_TEXT}; font-size: {px(14)}; }}
QLabel.Faint {{ color: {COL_TEXT_FAINT}; font-size: {px(12)}; }}

QLabel.LinkLabel {{ color: {COL_ACCENT_2}; font-size: {px(15)}; text-decoration: underline; }}
QLabel.LinkLabel:hover {{ color: {COL_ACCENT}; }}
QLabel.LinkDisabled {{ color: {COL_TEXT_FAINT}; font-size: {px(15)}; }}

QTextEdit {{
    background-color: transparent;
    color: {COL_TEXT};
    border: none;
    font-size: {px(14)};
    padding: 8px;
}}

QScrollArea {{ background-color: {COL_BG}; border: none; }}
QScrollBar:vertical {{ background: {COL_BG}; width: 10px; margin: 0px; border-radius: 5px; }}
QScrollBar::handle:vertical {{ background: {COL_CARD_BORDER}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {COL_ACCENT}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}

QComboBox {{
    background-color: {COL_CARD};
    color: {COL_TEXT};
    border: 1px solid {COL_CARD_BORDER};
    border-radius: 8px;
    padding: 8px 12px;
    font-size: {px(13)};
    min-width: 200px;
}}
QComboBox:hover {{ border: 1px solid {COL_ACCENT}; }}
QComboBox QAbstractItemView {{
    background-color: {COL_CARD};
    color: {COL_TEXT};
    selection-background-color: {COL_ACCENT};
    selection-color: #04211f;
    border: 1px solid {COL_CARD_BORDER};
    outline: none;
}}

QLineEdit {{
    background-color: {COL_CARD};
    color: {COL_TEXT};
    border: 1px solid {COL_CARD_BORDER};
    border-radius: 8px;
    padding: 8px 12px;
    font-size: {px(13)};
}}
QLineEdit:focus {{ border: 1px solid {COL_ACCENT}; }}

QCheckBox {{ color: {COL_TEXT}; font-size: {px(13)}; spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid {COL_CARD_BORDER}; background-color: {COL_CARD};
}}
QCheckBox::indicator:checked {{ background-color: {COL_ACCENT}; border: 1px solid {COL_ACCENT}; }}
"""


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def resolve_url(path):
    if not path:
        return None
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return BASE_SITE + path.lstrip("/")


def clickable_link(text, url, parent=None):
    lbl = QLabel(parent)
    if url:
        lbl.setText(f'<a href="{url}" style="color:{COL_ACCENT_2}; text-decoration:none;">{text}</a>')
        lbl.setTextFormat(Qt.RichText)
        lbl.setTextInteractionFlags(Qt.TextBrowserInteraction)
        lbl.setOpenExternalLinks(True)
        lbl.setProperty("class", "LinkLabel")
    else:
        lbl.setText(f"{text}  (unavailable)")
        lbl.setProperty("class", "LinkDisabled")
    lbl.setCursor(Qt.PointingHandCursor if url else Qt.ArrowCursor)
    return lbl


def add_drop_shadow(widget, blur=20, alpha=70, y_offset=4):
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, y_offset)
    effect.setColor(QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(effect)


def risk_level(rain_mm=0, wind_kmh=0):
    """Turns raw numbers into a plain-language risk badge — Low / Moderate / High."""
    rain_mm = rain_mm or 0
    wind_kmh = wind_kmh or 0
    if rain_mm >= 50 or wind_kmh >= 60:
        return "High risk", COL_DANGER
    if rain_mm >= 15 or wind_kmh >= 35:
        return "Moderate risk", COL_WARN
    return "Low risk", COL_ACCENT


def risk_badge(rain_mm=0, wind_kmh=0):
    text, color = risk_level(rain_mm, wind_kmh)
    lbl = QLabel(f"\u25CF {text}")
    lbl.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: 700;")
    return lbl


class Card(QFrame):
    def __init__(self, parent=None, danger=False):
        super().__init__(parent)
        self.setProperty("class", "DangerCard" if danger else "Card")
        add_drop_shadow(self)


class MarkdownView(QTextEdit):
    """
    A read-only, borderless, auto-growing text view that actually renders
    Markdown (bold, headings, bullet lists). This replaces the plain QLabels
    that were previously used to show AI output — QLabel doesn't understand
    Markdown, so **bold** and ### headings used to show up as literal
    asterisks and hashes on screen.
    """

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setLineWrapMode(QTextEdit.WidgetWidth)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)
        self.setStyleSheet(
            f"background: transparent; border: none; color: {COL_TEXT}; font-size: 16px; line-height: 1.4;"
        )
        self.document().setDocumentMargin(0)
        self.document().documentLayout().documentSizeChanged.connect(self._adjust_height)
        self.setMinimumHeight(120)
        self.set_markdown(text)

    def set_markdown(self, text):
        text = text or ""
        try:
            self.setMarkdown(text)
        except AttributeError:
            # Fallback for Qt builds without Markdown support: strip the
            # symbols so it's at least readable, rather than showing raw "**".
            plain = re.sub(r'[*_#`]', '', text)
            self.setPlainText(plain)
        self.document().setTextWidth(self.viewport().width())
        self._adjust_height()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.document().setTextWidth(self.viewport().width())
        self._adjust_height()

    def _adjust_height(self, *_args):
        doc_height = self.document().size().height()
        self.setFixedHeight(int(doc_height) + 16)


class Sparkline(QFrame):
    def __init__(self, values=None, color=COL_ACCENT, parent=None):
        super().__init__(parent)
        self.values = values or []
        self.color = QColor(color)
        self.setMinimumHeight(90)
        self.setStyleSheet("background-color: #101622; border-radius: 12px;")

    def setValues(self, values):
        self.values = values or []
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.values:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        values = list(self.values)
        minv, maxv = min(values), max(values)
        if minv == maxv:
            minv -= 1
            maxv += 1
        count = len(values)
        points = []
        for index, value in enumerate(values):
            x = 12 + (w - 24) * index / max(1, count - 1)
            y = 12 + (h - 24) * (1 - (value - minv) / (maxv - minv))
            points.append(QPointF(x, y))
        painter.setPen(QPen(self.color, 2))
        painter.drawPolyline(QPolygonF(points))
        for pt in points:
            painter.setBrush(self.color)
            painter.drawEllipse(pt, 3, 3)


def section_title(text, subtitle=None):
    wrap = QWidget()
    layout = QVBoxLayout(wrap)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)
    title = QLabel(text)
    title.setProperty("class", "SectionTitle")
    layout.addWidget(title)
    if subtitle:
        sub = QLabel(subtitle)
        sub.setProperty("class", "SectionSubtitle")
        layout.addWidget(sub)
    return wrap


def scroll_wrap(inner_widget):
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(inner_widget)
    scroll.setFrameShape(QFrame.NoFrame)
    return scroll


def placeholder_page(title, sub="Not available right now.", icon="\U0001F326"):
    wrap = QWidget()
    wrap.setObjectName("Content")
    outer = QVBoxLayout(wrap)
    outer.addStretch(1)
    icon_lbl = QLabel(icon)
    icon_lbl.setAlignment(Qt.AlignCenter)
    icon_lbl.setStyleSheet(f"font-size: 60px; color: {COL_TEXT_FAINT};")
    outer.addWidget(icon_lbl)
    title_lbl = QLabel(title)
    title_lbl.setAlignment(Qt.AlignCenter)
    title_lbl.setStyleSheet(f"font-size: 21px; font-weight: 700; color: {COL_TEXT_DIM}; margin-top: 10px;")
    outer.addWidget(title_lbl)
    sub_lbl = QLabel(sub)
    sub_lbl.setAlignment(Qt.AlignCenter)
    sub_lbl.setStyleSheet(f"font-size: 14px; color: {COL_TEXT_FAINT}; margin-top: 4px;")
    outer.addWidget(sub_lbl)
    outer.addStretch(1)
    return wrap


# --------------------------------------------------------------------------- #
# Media preview widgets (gif / pdf) — used by Weather Graphics & Advisories
# --------------------------------------------------------------------------- #

_ACTIVE_MEDIA_WORKERS = []  # keeps QThreads alive until they finish


def _track_worker(worker):
    _ACTIVE_MEDIA_WORKERS.append(worker)

    def _cleanup():
        if worker in _ACTIVE_MEDIA_WORKERS:
            _ACTIVE_MEDIA_WORKERS.remove(worker)

    worker.finished.connect(_cleanup)


def _media_cache_path(url):
    ext = ".pdf" if url.lower().endswith(".pdf") else (".gif" if url.lower().endswith(".gif") else ".bin")
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return os.path.join(MEDIA_CACHE_DIR, key + ext)


class MediaFetchWorker(QThread):
    finished_ok = pyqtSignal(str, bytes)
    finished_err = pyqtSignal(str, str)

    def __init__(self, url, parent=None):
        super().__init__(parent)
        self.url = url

    def run(self):
        cache_path = _media_cache_path(self.url)
        try:
            resp = requests.get(self.url, timeout=20, headers={"User-Agent": "SLDAS-Ultimate/1.0"})
            resp.raise_for_status()
            data = resp.content
            try:
                with open(cache_path, "wb") as f:
                    f.write(data)
            except OSError:
                pass
            self.finished_ok.emit(self.url, data)
        except Exception as e:
            if os.path.exists(cache_path):
                try:
                    with open(cache_path, "rb") as f:
                        self.finished_ok.emit(self.url, f.read())
                        return
                except OSError:
                    pass
            self.finished_err.emit(self.url, str(e))


class GifPreview(QFrame):
    def __init__(self, url, max_width=900, parent=None):
        super().__init__(parent)
        self.url = url
        self.max_width = max_width
        self._movie = None
        self._worker = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.img_label = QLabel("Loading preview\u2026")
        self.img_label.setProperty("class", "Faint")
        self.img_label.setAlignment(Qt.AlignCenter)
        self.img_label.setMinimumHeight(320)
        self.img_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.img_label.setStyleSheet(f"background-color: {COL_BG_2}; border-radius: 8px;")
        layout.addWidget(self.img_label)

        if url:
            self._worker = MediaFetchWorker(url)
            self._worker.finished_ok.connect(self._on_ok)
            self._worker.finished_err.connect(self._on_err)
            _track_worker(self._worker)
            self._worker.start()
        else:
            self.img_label.setText("No preview available")

    def _on_ok(self, url, data):
        if sip.isdeleted(self):
            return
        cache_path = _media_cache_path(url)
        self._movie = QMovie(cache_path)
        self._apply_movie_size()
        self.img_label.setMovie(self._movie)
        self._movie.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._movie:
            self._apply_movie_size()

    def _apply_movie_size(self):
        width = min(max(100, self.width()), self.max_width)
        height = int(width * 0.62)
        self._movie.setScaledSize(QSize(width, height))
        self.img_label.setMinimumHeight(height)

    def _on_err(self, url, err):
        if sip.isdeleted(self):
            return
        self.img_label.setText(f"Preview unavailable ({err})")


class PdfPreview(QFrame):
    def __init__(self, url, max_width=130, parent=None):
        super().__init__(parent)
        self.url = url
        self.max_width = max_width
        self._worker = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.img_label = QLabel("Loading\u2026" if HAS_FITZ else "No preview")
        self.img_label.setProperty("class", "Faint")
        self.img_label.setAlignment(Qt.AlignCenter)
        self.img_label.setMinimumHeight(160)
        self.img_label.setStyleSheet(f"background-color: {COL_BG_2}; border-radius: 8px;")
        layout.addWidget(self.img_label)

        if url and HAS_FITZ:
            self._worker = MediaFetchWorker(url)
            self._worker.finished_ok.connect(self._on_ok)
            self._worker.finished_err.connect(self._on_err)
            _track_worker(self._worker)
            self._worker.start()
        elif not url:
            self.img_label.setText("No document")

    def _on_ok(self, url, data):
        if sip.isdeleted(self):
            return
        try:
            doc = fitz.open(stream=data, filetype="pdf")
            page = doc.load_page(0)
            zoom = self.max_width / page.rect.width
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
            self.img_label.setPixmap(QPixmap.fromImage(img))
            self.img_label.setStyleSheet("border-radius: 8px;")
            doc.close()
        except Exception as e:
            self.img_label.setText(f"Preview failed ({e})")

    def _on_err(self, url, err):
        if sip.isdeleted(self):
            return
        self.img_label.setText(f"Unavailable ({err})")


class PdfViewerDialog(QDialog):
    """A simple in-app PDF viewer that renders PDF pages with PyMuPDF and
    allows basic page navigation. Falls back to an error message if rendering
    fails or PyMuPDF is not installed.
    """

    def __init__(self, url, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PDF Viewer")
        self.resize(920, 700)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.viewer_label = QLabel("Loading PDF…")
        self.viewer_label.setAlignment(Qt.AlignCenter)
        self.viewer_label.setProperty("class", "Body")
        self.viewer_label.setMinimumHeight(360)
        self.viewer_label.setStyleSheet(f"background-color: {COL_BG_2}; border-radius: 8px;")
        layout.addWidget(self.viewer_label, 1)

        nav = QHBoxLayout()
        self.prev_btn = QPushButton("◀ Prev")
        self.next_btn = QPushButton("Next ▶")
        self.page_lbl = QLabel("")
        self.prev_btn.setEnabled(False)
        self.next_btn.setEnabled(False)
        nav.addWidget(self.prev_btn)
        nav.addStretch(1)
        nav.addWidget(self.page_lbl)
        nav.addStretch(1)
        nav.addWidget(self.next_btn)
        layout.addLayout(nav)

        self.pages = []
        self.page_index = 0

        if not HAS_FITZ:
            self.viewer_label.setText("PDF preview requires 'pymupdf' (PyMuPDF) to be installed.")
            return

        self._worker = MediaFetchWorker(url)
        self._worker.finished_ok.connect(self._on_ok)
        self._worker.finished_err.connect(self._on_err)
        _track_worker(self._worker)
        self._worker.start()

        self.prev_btn.clicked.connect(self._show_prev)
        self.next_btn.clicked.connect(self._show_next)

    def _on_ok(self, url, data):
        try:
            doc = fitz.open(stream=data, filetype="pdf")
            self.pages = []
            for pno in range(doc.page_count):
                page = doc.load_page(pno)
                # render at a reasonable zoom for the dialog width
                zoom = max(1.0, (self.width() - 80) / page.rect.width)
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
                img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
                self.pages.append(QPixmap.fromImage(img))
            doc.close()
            if self.pages:
                self.page_index = 0
                self.prev_btn.setEnabled(True)
                self.next_btn.setEnabled(True if len(self.pages) > 1 else False)
                self._update_view()
        except Exception as e:
            self.viewer_label.setText(f"Preview failed: {e}")

    def _on_err(self, url, err):
        self.viewer_label.setText(f"Failed to load: {err}")

    def _update_view(self):
        if not self.pages:
            return
        pix = self.pages[self.page_index]
        self.viewer_label.setPixmap(pix.scaled(self.viewer_label.width(), self.viewer_label.height(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.page_lbl.setText(f"Page {self.page_index + 1} / {len(self.pages)}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.pages:
            self._update_view()

    def _show_prev(self):
        if self.page_index > 0:
            self.page_index -= 1
            self._update_view()

    def _show_next(self):
        if self.page_index < len(self.pages) - 1:
            self.page_index += 1
            self._update_view()


# --------------------------------------------------------------------------- #
# Background data workers
# --------------------------------------------------------------------------- #

class FetchWorker(QThread):
    """Pulls the main meteo.gov.lk feed."""
    finished_ok = pyqtSignal(dict)
    finished_err = pyqtSignal(str, dict)

    def run(self):
        try:
            resp = requests.get(
                DATA_URL,
                headers={"User-Agent": "SLDAS-Ultimate/1.0 (+meteo alert client)"},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            try:
                with open(LOCAL_CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
            except OSError:
                pass
            self.finished_ok.emit(data)
        except Exception as e:
            cached = self._load_cache()
            self.finished_err.emit(str(e), cached or {})

    @staticmethod
    def _load_cache():
        if os.path.exists(LOCAL_CACHE_FILE):
            try:
                with open(LOCAL_CACHE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return None
        return None


class WeatherFetchWorker(QThread):
    """Pulls Open-Meteo forecast data for one city."""
    finished_ok = pyqtSignal(dict)
    finished_err = pyqtSignal(str)

    def __init__(self, latitude, longitude, parent=None):
        super().__init__(parent)
        self.latitude = latitude
        self.longitude = longitude

    def run(self):
        try:
            self.finished_ok.emit(_fetch_open_meteo_data(self.latitude, self.longitude))
        except Exception as e:
            self.finished_err.emit(str(e))


def _fetch_open_meteo_data(latitude, longitude):
    resp = requests.get(
        OPEN_METEO_FORECAST_URL,
        params={
            "latitude": latitude,
            "longitude": longitude,
            "current_weather": True,
            "daily": ",".join([
                "temperature_2m_max", "temperature_2m_min", "precipitation_sum", "sunrise", "sunset",
            ]),
            "hourly": ",".join([
                "temperature_2m", "relativehumidity_2m", "precipitation", "surface_pressure",
                "windspeed_10m", "winddirection_10m",
            ]),
            "timezone": "auto",
        },
        timeout=12,
        headers={"User-Agent": "SLDAS-Ultimate/1.0 (+OpenMeteo)"},
    )
    resp.raise_for_status()
    return resp.json()


def _format_weather_summary(data, location_name):
    if not data:
        return f"{location_name}: no forecast data available."
    current = data.get("current_weather", {})
    daily = data.get("daily", {})
    temp = current.get("temperature")
    speed = current.get("windspeed")
    code = current.get("weathercode")
    condition = WEATHER_CODE_MAP.get(code, "Unknown conditions")
    lines = [f"{location_name}: {condition}"]
    if temp is not None:
        lines.append(f"Current {temp:.1f}\u00b0C")
    if speed is not None:
        lines.append(f"wind {speed:.1f} km/h")
    highs = daily.get("temperature_2m_max", [])
    lows = daily.get("temperature_2m_min", [])
    rain = daily.get("precipitation_sum", [])
    if highs and lows and rain:
        outlook = []
        for i in range(min(3, len(highs))):
            outlook.append(f"Day {i + 1}: high {highs[i]:.1f}\u00b0C, low {lows[i]:.1f}\u00b0C, rain {rain[i]:.1f} mm")
        lines.append("; ".join(outlook))
    return ". ".join(lines)


# --------------------------------------------------------------------------- #
# Gemini AI call — one generic worker + prompt builder used everywhere
# --------------------------------------------------------------------------- #

SIMPLE_MODE_INSTRUCTION = (
    "Explain this like you're talking to a curious teenager in Sri Lanka who has "
    "never studied meteorology. Use short sentences and everyday words, skip "
    "technical jargon (or explain it in one simple phrase if you must use it), "
    "and keep the whole thing friendly and easy to skim."
)
ADVANCED_MODE_INSTRUCTION = (
    "Provide a precise, technically detailed meteorological analysis suitable for "
    "a reader who is comfortable with weather terminology."
)


def build_ai_prompt(mode, simple_mode, national_summary, city_name, city_summary, question=None, language="English"):
    tone = SIMPLE_MODE_INSTRUCTION if simple_mode else ADVANCED_MODE_INSTRUCTION
    language_instruction = (
        "Write the answer in Sinhala. Use natural Sinhala language and keep the tone friendly and easy to understand."
        if language == "Sinhala" else "Write the answer in English."
    )
    context = (
        f"{tone}\n\n"
        f"{language_instruction}\n\n"
        f"National (Sri Lanka) weather summary: {national_summary}\n"
        f"{city_name} forecast: {city_summary}\n\n"
    )
    if mode == "summary":
        context += (
            "Task: In a short Markdown bulleted list, summarize today's weather and "
            "the next couple of days for this city. Keep it under 120 words."
        )
    elif mode == "action_plan":
        context += (
            "Task: Give a short, practical Markdown bulleted checklist of what someone "
            "living here should actually DO today because of this forecast (e.g. bring "
            "an umbrella, avoid the beach, charge devices in case of outages). Keep it "
            "under 100 words and skip anything not clearly justified by the data above."
        )
    elif mode == "chat":
        context += f"The user asked: \"{question}\"\nAnswer using the context above where it's relevant."
    return context


def _extract_gemini_text_from_contents(contents):
    texts = []
    for item in contents:
        for part in item.get("parts") or []:
            text = part.get("text")
            if text:
                texts.append(text)
    return "\n".join(texts).strip()


def _extract_gemini_text_from_candidates(candidates):
    texts = []
    for candidate in candidates:
        content = candidate.get("content") or {}
        if isinstance(content, str):
            texts.append(content)
            continue
        if isinstance(content, dict):
            if "parts" in content:
                for part in content.get("parts") or []:
                    text = part.get("text")
                    if text:
                        texts.append(text)
            elif "text" in content:
                texts.append(content.get("text", ""))
    return "\n".join(texts).strip()


def _call_ai_model(prompt, gemini_key, gemini_endpoint):
    if not gemini_key:
        raise ValueError("Add your Gemini API key in Settings first.")
    if not gemini_endpoint:
        raise ValueError("Add a Gemini API endpoint in Settings first.")

    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {"X-goog-api-key": gemini_key, "Content-Type": "application/json"}
    resp = requests.post(gemini_endpoint, headers=headers, json=payload, timeout=25)
    resp.raise_for_status()
    body = resp.json()
    if isinstance(body, dict):
        if "candidates" in body:
            text = _extract_gemini_text_from_candidates(body.get("candidates", []))
            if text:
                return text
        if "contents" in body:
            text = _extract_gemini_text_from_contents(body.get("contents", []))
            if text:
                return text
    raise ValueError("Gemini returned an unexpected response format.")


class AIWorker(QThread):
    """One generic worker for every Gemini call in the app (summary, action
    plan, or free-form chat question)."""
    finished_ok = pyqtSignal(str)
    finished_err = pyqtSignal(str)

    def __init__(self, prompt, gemini_endpoint, gemini_key, parent=None):
        super().__init__(parent)
        self.prompt = prompt
        self.gemini_endpoint = gemini_endpoint
        self.gemini_key = gemini_key

    def run(self):
        try:
            self.finished_ok.emit(_call_ai_model(self.prompt, self.gemini_key, self.gemini_endpoint))
        except Exception as e:
            self.finished_err.emit(str(e))


# --------------------------------------------------------------------------- #
# Main window
# --------------------------------------------------------------------------- #

class SLDASApp(QMainWindow):

    NAV_ITEMS = [
        ("Dashboard", "\u2302"),
        ("Public Forecast", "\u2601"),
        ("Climate Outlook", "\U0001F4C8"),
        ("Marine & Fleet", "\u26F5"),
        ("AI Analysis", "\u2728"),
        ("Live Radar", "\U0001F5FA"),
        ("Emergency Hub", "\u26A8"),
        ("Advisories & Links", "\u26A0"),
        ("Weather Graphics", "\U0001F5FA"),
        ("Settings", "\u2699"),
    ]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("SLDAS Ultimate \u2014 Sri Lankan Atmospheric Alert System")
        self.resize(1360, 860)
        self.setMinimumSize(1080, 700)

        self.settings = QSettings("SLDAS", "SLDASUltimate")
        self.font_scale_name = self.settings.value("font_scale_name", "Large (Recommended)", type=str)
        if self.font_scale_name not in FONT_SCALE_OPTIONS:
            self.font_scale_name = "Large (Recommended)"
        self.refresh_interval_name = self.settings.value("refresh_interval_name", "Every 10 minutes", type=str)
        if self.refresh_interval_name not in REFRESH_INTERVAL_OPTIONS:
            self.refresh_interval_name = "Every 10 minutes"
        self.refresh_interval_ms = REFRESH_INTERVAL_OPTIONS[self.refresh_interval_name]

        self.gemini_api_endpoint = self.settings.value("gemini_api_endpoint", DEFAULT_AI_GEMINI_API_ENDPOINT, type=str)
        self.gemini_api_key = self.settings.value("gemini_api_key", "", type=str)
        self.simple_mode = self.settings.value("simple_mode", True, type=bool)
        self.ai_language_name = self.settings.value("ai_language_name", "English", type=str)
        if self.ai_language_name not in AI_LANGUAGE_OPTIONS:
            self.ai_language_name = "English"

        self.setStyleSheet(build_qss(FONT_SCALE_OPTIONS[self.font_scale_name]))

        self.data = {}
        self.last_updated = None
        self.last_error = None
        self.last_advisories_hash = ""
        self.seconds_to_refresh = self.refresh_interval_ms // 1000
        self.worker = None
        self.ai_worker = None
        self.weather_worker = None

        self.nav_buttons = {}
        self.page_widgets = {}

        self._build_ui()
        self._build_tray()

        self.countdown_timer = QTimer(self)
        self.countdown_timer.timeout.connect(self._tick_countdown)
        self.countdown_timer.start(1000)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh_now)
        self.refresh_timer.start(self.refresh_interval_ms)

        self.refresh_now()

    # ------------------------------------------------------------------ #
    # Settings application
    # ------------------------------------------------------------------ #
    def apply_font_scale(self, scale_name):
        self.font_scale_name = scale_name
        self.settings.setValue("font_scale_name", scale_name)
        self.setStyleSheet(build_qss(FONT_SCALE_OPTIONS[scale_name]))

    def apply_refresh_interval(self, interval_name):
        self.refresh_interval_name = interval_name
        self.refresh_interval_ms = REFRESH_INTERVAL_OPTIONS[interval_name]
        self.settings.setValue("refresh_interval_name", interval_name)
        self.refresh_timer.setInterval(self.refresh_interval_ms)
        self.seconds_to_refresh = self.refresh_interval_ms // 1000

    def apply_gemini_settings(self):
        endpoint = self.gemini_endpoint_input.text().strip()
        api_key = self.gemini_key_input.text().strip()
        if endpoint:
            self.gemini_api_endpoint = endpoint
            self.settings.setValue("gemini_api_endpoint", endpoint)
        if api_key:
            self.gemini_api_key = api_key
            self.settings.setValue("gemini_api_key", api_key)

    def apply_simple_mode(self, state):
        self.simple_mode = bool(state)
        self.settings.setValue("simple_mode", self.simple_mode)

    def apply_ai_language(self, language_name):
        if language_name not in AI_LANGUAGE_OPTIONS:
            return
        self.ai_language_name = language_name
        self.settings.setValue("ai_language_name", language_name)

    # ------------------------------------------------------------------ #
    # UI construction
    # ------------------------------------------------------------------ #
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_sidebar())

        main_col = QWidget()
        main_layout = QVBoxLayout(main_col)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(self._build_topbar())

        self.stack = QStackedWidget()
        self.stack.setObjectName("Content")
        main_layout.addWidget(self.stack, 1)

        root.addWidget(main_col, 1)

        self._build_pages()
        self.show_page("Dashboard")

    def _build_sidebar(self):
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(230)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 24, 0, 18)
        layout.setSpacing(0)

        logo_wrap = QWidget()
        logo_layout = QVBoxLayout(logo_wrap)
        logo_layout.setContentsMargins(20, 0, 20, 20)
        logo_layout.setSpacing(4)
        title = QLabel("\u26C8  SLDAS")
        title.setObjectName("LogoTitle")
        logo_layout.addWidget(title)
        sub = QLabel("Sri Lankan Atmospheric\nAlert System")
        sub.setObjectName("LogoSub")
        logo_layout.addWidget(sub)
        layout.addWidget(logo_wrap)

        for name, icon in self.NAV_ITEMS:
            btn = QPushButton(f"   {icon}    {name}")
            btn.setObjectName("NavBtn")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _, n=name: self.show_page(n))
            layout.addWidget(btn)
            self.nav_buttons[name] = btn

        layout.addStretch(1)

        status_wrap = QWidget()
        status_layout = QHBoxLayout(status_wrap)
        status_layout.setContentsMargins(20, 10, 20, 6)
        self.status_dot = QLabel("\u25CF")
        self.status_dot.setStyleSheet(f"color: {COL_TEXT_FAINT}; font-size: 11px;")
        status_layout.addWidget(self.status_dot)
        self.status_text = QLabel("Initializing...")
        self.status_text.setStyleSheet(f"color: {COL_TEXT_FAINT}; font-size: 9px;")
        status_layout.addWidget(self.status_text, 1)
        layout.addWidget(status_wrap)

        return sidebar

    def _build_topbar(self):
        topbar = QWidget()
        topbar.setObjectName("TopBar")
        topbar.setFixedHeight(60)
        layout = QHBoxLayout(topbar)
        layout.setContentsMargins(24, 0, 20, 0)

        self.page_title_lbl = QLabel("Dashboard")
        self.page_title_lbl.setObjectName("PageTitle")
        layout.addWidget(self.page_title_lbl)
        layout.addStretch(1)

        self.last_updated_lbl = QLabel("Never updated")
        self.last_updated_lbl.setObjectName("LastUpdated")
        layout.addWidget(self.last_updated_lbl)

        layout.addSpacing(16)

        self.countdown_lbl = QLabel("")
        self.countdown_lbl.setObjectName("Countdown")
        layout.addWidget(self.countdown_lbl)

        layout.addSpacing(16)

        refresh_btn = QPushButton("\u21BB  Refresh Now")
        refresh_btn.setObjectName("RefreshBtn")
        refresh_btn.setCursor(Qt.PointingHandCursor)
        refresh_btn.clicked.connect(self.refresh_now)
        layout.addWidget(refresh_btn)

        return topbar

    def _build_tray(self):
        self.tray = QSystemTrayIcon(self)
        pix = QPixmap(32, 32)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        painter.setBrush(QColor(COL_ACCENT))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(2, 2, 28, 28)
        painter.end()
        self.tray.setIcon(QIcon(pix))
        self.tray.setToolTip("SLDAS Ultimate")

        menu = QMenu()
        show_action = QAction("Show SLDAS", self)
        show_action.triggered.connect(self.showNormal)
        refresh_action = QAction("Refresh Now", self)
        refresh_action.triggered.connect(self.refresh_now)
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(QApplication.quit)
        menu.addAction(show_action)
        menu.addAction(refresh_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.show()

    def show_page(self, name):
        self.stack.setCurrentWidget(self.page_widgets[name])
        self.page_title_lbl.setText(name)
        for n, btn in self.nav_buttons.items():
            btn.setChecked(n == name)

    # ------------------------------------------------------------------ #
    # Page construction
    # ------------------------------------------------------------------ #
    def _build_pages(self):
        pages = [
            ("Dashboard", self._page_dashboard()),
            ("Public Forecast", self._page_public_forecast()),
            ("Climate Outlook", self._page_climate_outlook()),
            ("Marine & Fleet", self._page_marine_fleet()),
            ("AI Analysis", self._page_ai_analysis()),
            ("Live Radar", self._page_live_radar()),
            ("Emergency Hub", self._page_emergency_hub()),
            ("Advisories & Links", self._page_advisories()),
            ("Weather Graphics", self._page_graphics()),
            ("Settings", self._page_settings()),
        ]
        for name, widget in pages:
            self.page_widgets[name] = widget
            self.stack.addWidget(widget)

    # ---------------- Dashboard ---------------- #
    def _page_dashboard(self):
        inner = QWidget()
        inner.setObjectName("Content")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(14)

        layout.addWidget(section_title("Live Overview", "Auto-refreshing feed from meteo.gov.lk"))

        self.dash_banner = Card()
        banner_layout = QHBoxLayout(self.dash_banner)
        banner_layout.setContentsMargins(20, 16, 20, 16)
        self.dash_banner_lbl = QLabel("Fetching latest data...")
        self.dash_banner_lbl.setProperty("class", "Body")
        self.dash_banner_lbl.setWordWrap(True)
        banner_layout.addWidget(self.dash_banner_lbl)
        layout.addWidget(self.dash_banner)

        cards_row = QGridLayout()
        cards_row.setSpacing(14)
        self.dash_cards = {}
        card_defs = [
            ("public_weather_forecast", "Public Forecast", "\u2601"),
            ("sea_weather_forecast", "Sea Forecast", "\u26F5"),
            ("fleet_shipping_forecast", "Fleet / Shipping", "\U0001F6A2"),
            ("severe_weather_advisory", "Severe Weather", "\u26A0"),
        ]
        for i, (key, label, icon) in enumerate(card_defs):
            c = Card()
            c_layout = QVBoxLayout(c)
            c_layout.setContentsMargins(14, 18, 14, 18)
            c_layout.setSpacing(4)
            icon_lbl = QLabel(icon)
            icon_lbl.setProperty("class", "CardIcon")
            icon_lbl.setStyleSheet(f"color: {COL_ACCENT};")
            icon_lbl.setAlignment(Qt.AlignCenter)
            c_layout.addWidget(icon_lbl)
            name_lbl = QLabel(label)
            name_lbl.setProperty("class", "CardLabel")
            name_lbl.setAlignment(Qt.AlignCenter)
            c_layout.addWidget(name_lbl)
            status_lbl = QLabel("\u2013")
            status_lbl.setProperty("class", "CardStatus")
            status_lbl.setAlignment(Qt.AlignCenter)
            c_layout.addWidget(status_lbl)
            cards_row.addWidget(c, 0, i)
            self.dash_cards[key] = status_lbl
        layout.addLayout(cards_row)

        alert_row = QHBoxLayout()
        alert_row.setSpacing(14)

        self.dash_el_nino_card = Card()
        el_nino_layout = QVBoxLayout(self.dash_el_nino_card)
        el_nino_layout.setContentsMargins(14, 18, 14, 18)
        el_nino_layout.setSpacing(6)
        el_nino_icon = QLabel("\U0001F30A")
        el_nino_icon.setAlignment(Qt.AlignCenter)
        el_nino_icon.setStyleSheet(f"color: {COL_ACCENT_2}; font-size: 34px;")
        el_nino_layout.addWidget(el_nino_icon)
        el_nino_title = QLabel("El Niño update")
        el_nino_title.setProperty("class", "CardLabel")
        el_nino_title.setAlignment(Qt.AlignCenter)
        el_nino_layout.addWidget(el_nino_title)
        self.dash_el_nino_text = QLabel("Checking for El Niño updates...")
        self.dash_el_nino_text.setProperty("class", "Body")
        self.dash_el_nino_text.setWordWrap(True)
        el_nino_layout.addWidget(self.dash_el_nino_text)
        self.dash_el_nino_link = clickable_link("Open El Niño bulletin", None)
        self.dash_el_nino_link.setProperty("class", "LinkLabel")
        el_nino_layout.addWidget(self.dash_el_nino_link)
        self.dash_el_nino_link.hide()
        alert_row.addWidget(self.dash_el_nino_card, 2)

        self.dash_severe_alert_card = Card(danger=True)
        severe_layout = QVBoxLayout(self.dash_severe_alert_card)
        severe_layout.setContentsMargins(14, 18, 14, 18)
        severe_layout.setSpacing(6)
        severe_icon = QLabel("\u26A0")
        severe_icon.setAlignment(Qt.AlignCenter)
        severe_icon.setStyleSheet(f"color: {COL_DANGER}; font-size: 38px;")
        severe_layout.addWidget(severe_icon)
        severe_title = QLabel("Severe Alerts")
        severe_title.setProperty("class", "CardLabel")
        severe_title.setAlignment(Qt.AlignCenter)
        severe_layout.addWidget(severe_title)
        self.dash_severe_alert_text = QLabel("No active severe weather advisories.")
        self.dash_severe_alert_text.setProperty("class", "Body")
        self.dash_severe_alert_text.setWordWrap(True)
        severe_layout.addWidget(self.dash_severe_alert_text)
        alert_row.addWidget(self.dash_severe_alert_card, 3)

        layout.addLayout(alert_row)

        layout.addWidget(section_title("Know What To Do", "A quick reminder, always visible"))
        tip_card = Card()
        tip_layout = QVBoxLayout(tip_card)
        tip_layout.setContentsMargins(18, 14, 18, 14)
        tip_layout.setSpacing(6)
        tip_heading = QLabel("\U0001F4A1 Safety basics")
        tip_heading.setProperty("class", "CardHeading")
        tip_layout.addWidget(tip_heading)
        tip_body = QLabel(
            "Heavy rain forecast? Keep your phone charged and know your nearest higher ground. "
            "Check the Emergency Hub tab any time for hotlines and step-by-step advice."
        )
        tip_body.setWordWrap(True)
        tip_body.setProperty("class", "Body")
        tip_layout.addWidget(tip_body)
        layout.addWidget(tip_card)

        layout.addWidget(section_title("Quick Links", "Jump straight to official resources"))
        self.dash_links_card = Card()
        self.dash_links_layout = QVBoxLayout(self.dash_links_card)
        self.dash_links_layout.setContentsMargins(18, 14, 18, 14)
        self.dash_links_layout.setSpacing(8)
        layout.addWidget(self.dash_links_card)

        layout.addStretch(1)
        return scroll_wrap(inner)

    # ---------------- Public Forecast ---------------- #
    def _page_public_forecast(self):
        inner = QWidget()
        inner.setObjectName("Content")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(14)

        layout.addWidget(section_title("Public Weather Forecast", "Issued by the Department of Meteorology, Sri Lanka"))

        forecast_card = Card()
        card_layout = QVBoxLayout(forecast_card)
        card_layout.setContentsMargins(4, 4, 4, 4)
        self.forecast_text = QTextEdit()
        self.forecast_text.setReadOnly(True)
        self.forecast_text.setText("Loading...")
        card_layout.addWidget(self.forecast_text)
        layout.addWidget(forecast_card, 1)
        return inner

    # ---------------- Climate Outlook ---------------- #
    def _page_climate_outlook(self):
        inner = QWidget()
        inner.setObjectName("Content")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(14)

        layout.addWidget(section_title("Climate Outlook", "City-by-city forecast, powered by Open-Meteo"))

        self.location_info = QLabel("Selected location: Thelijjawila, Sri Lanka")
        self.location_info.setProperty("class", "Body")
        layout.addWidget(self.location_info)

        self.climate_status = QLabel("Loading forecast\u2026")
        self.climate_status.setProperty("class", "Faint")
        layout.addWidget(self.climate_status)

        quick_row = QHBoxLayout()
        quick_row.setSpacing(14)

        def stat_card(label_text, initial):
            card = Card()
            l = QVBoxLayout(card)
            l.setContentsMargins(18, 16, 18, 16)
            l.setSpacing(6)
            lbl = QLabel(label_text)
            lbl.setProperty("class", "CardLabel")
            val = QLabel(initial)
            val.setProperty("class", "SectionTitle")
            l.addWidget(lbl)
            l.addWidget(val)
            return card, val

        self.temp_stat_card, self.temp_stat_value = stat_card("Temperature", "-- \u00b0C")
        self.humidity_stat_card, self.humidity_stat_value = stat_card("Humidity", "-- %")
        self.wind_stat_card, self.wind_stat_value = stat_card("Wind Speed", "-- km/h")
        self.precip_stat_card, self.precip_stat_value = stat_card("Precipitation", "-- mm")
        for c in (self.temp_stat_card, self.humidity_stat_card, self.wind_stat_card, self.precip_stat_card):
            quick_row.addWidget(c, 1)
        layout.addLayout(quick_row)

        # Risk badge row — turns raw numbers into plain "Low / Moderate / High"
        risk_card = Card()
        risk_layout = QHBoxLayout(risk_card)
        risk_layout.setContentsMargins(18, 12, 18, 12)
        risk_label = QLabel("Today's overall risk:")
        risk_label.setProperty("class", "CardLabel")
        risk_layout.addWidget(risk_label)
        self.climate_risk_badge = risk_badge(0, 0)
        risk_layout.addWidget(self.climate_risk_badge)
        risk_layout.addStretch(1)
        layout.addWidget(risk_card)

        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(14)
        self.feels_card, self.feels_stat_value = stat_card("Feels Like", "-- \u00b0C")
        self.pressure_card, self.pressure_stat_value = stat_card("Pressure", "-- hPa")
        self.direction_card, self.direction_stat_value = stat_card("Wind Direction", "--")
        self.rain_today_card, self.rain_today_value = stat_card("Rain Today", "-- mm")
        self.sun_card, self.sun_stat_value = stat_card("Sunrise / Sunset", "-- / --")
        for c in (self.feels_card, self.pressure_card, self.direction_card, self.rain_today_card, self.sun_card):
            metrics_row.addWidget(c, 1)
        layout.addLayout(metrics_row)

        spark_row = QHBoxLayout()
        spark_row.setSpacing(14)

        temp_spark_card = Card()
        temp_spark_layout = QVBoxLayout(temp_spark_card)
        temp_spark_layout.setContentsMargins(18, 16, 18, 16)
        temp_title = QLabel("5-Day Temp Trend")
        temp_title.setProperty("class", "CardLabel")
        temp_spark_layout.addWidget(temp_title)
        self.temp_sparkline = Sparkline(color=COL_ACCENT)
        temp_spark_layout.addWidget(self.temp_sparkline)
        spark_row.addWidget(temp_spark_card, 1)

        rain_spark_card = Card()
        rain_spark_layout = QVBoxLayout(rain_spark_card)
        rain_spark_layout.setContentsMargins(18, 16, 18, 16)
        rain_title = QLabel("5-Day Rain Trend")
        rain_title.setProperty("class", "CardLabel")
        rain_spark_layout.addWidget(rain_title)
        self.rain_sparkline = Sparkline(color=COL_WARN)
        rain_spark_layout.addWidget(self.rain_sparkline)
        spark_row.addWidget(rain_spark_card, 1)

        layout.addLayout(spark_row)

        row = QHBoxLayout()
        row.setSpacing(14)

        self.current_weather_card = Card()
        current_layout = QVBoxLayout(self.current_weather_card)
        current_layout.setContentsMargins(18, 16, 18, 16)
        current_layout.setSpacing(8)
        heading = QLabel("Current Conditions")
        heading.setProperty("class", "CardHeading")
        current_layout.addWidget(heading)
        self.current_weather_text = QLabel("Fetching current temperature, wind and humidity...")
        self.current_weather_text.setWordWrap(True)
        self.current_weather_text.setProperty("class", "Body")
        current_layout.addWidget(self.current_weather_text)
        row.addWidget(self.current_weather_card, 1)

        self.daily_weather_card = Card()
        daily_layout = QVBoxLayout(self.daily_weather_card)
        daily_layout.setContentsMargins(18, 16, 18, 16)
        daily_layout.setSpacing(8)
        heading2 = QLabel("5-Day Outlook")
        heading2.setProperty("class", "CardHeading")
        daily_layout.addWidget(heading2)
        self.daily_weather_text = QLabel("Waiting for location forecast...")
        self.daily_weather_text.setWordWrap(True)
        self.daily_weather_text.setProperty("class", "Body")
        daily_layout.addWidget(self.daily_weather_text)
        row.addWidget(self.daily_weather_card, 1)

        layout.addLayout(row, 1)

        cities_card = Card()
        cities_layout = QGridLayout(cities_card)
        cities_layout.setContentsMargins(18, 16, 18, 16)
        cities_layout.setSpacing(12)
        cities_title = QLabel("Sri Lanka City Selection")
        cities_title.setProperty("class", "CardHeading")
        cities_layout.addWidget(cities_title, 0, 0, 1, 3)

        for index, (city, lat, lon) in enumerate(SRI_LANKA_CITIES):
            btn = QPushButton(city)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setProperty("class", "ActionBtn")
            btn.clicked.connect(lambda checked, c=city, la=lat, lo=lon: self._load_climate_location(c, la, lo))
            cities_layout.addWidget(btn, (index // 3) + 1, index % 3)

        layout.addWidget(cities_card)
        layout.addStretch(1)

        self._load_climate_location(
            PRIMARY_CLIMATE_LOCATION["name"], PRIMARY_CLIMATE_LOCATION["latitude"], PRIMARY_CLIMATE_LOCATION["longitude"]
        )
        return scroll_wrap(inner)

    def _load_climate_location(self, display_name, latitude, longitude):
        self.location_info.setText(f"Selected location: {display_name}")
        self.climate_status.setText("Fetching forecast\u2026")
        self.weather_worker = WeatherFetchWorker(latitude, longitude)
        self.weather_worker.finished_ok.connect(self._on_weather_ok)
        self.weather_worker.finished_err.connect(self._on_weather_err)
        _track_worker(self.weather_worker)
        self.weather_worker.start()

    def _on_weather_ok(self, data):
        current = data.get("current_weather", {})
        daily = data.get("daily", {})
        hourly = data.get("hourly", {})

        temp = current.get("temperature")
        wind_speed = current.get("windspeed")
        wind_dir = current.get("winddirection")
        weather_code = current.get("weathercode")
        condition_text = WEATHER_CODE_MAP.get(weather_code, "Clear skies")

        if current:
            self.current_weather_text.setText(
                f"{condition_text}. Temperature: {temp}\u00b0C, Wind: {wind_speed} km/h at {wind_dir}\u00b0."
            )
        else:
            self.current_weather_text.setText("Current weather unavailable.")

        humidity = rain_today = pressure = None
        if hourly:
            humidity_values = hourly.get("relativehumidity_2m", [])
            precipitation_values = hourly.get("precipitation", [])
            pressure_values = hourly.get("surface_pressure", [])
            if humidity_values:
                humidity = humidity_values[0]
            if precipitation_values:
                rain_today = sum(precipitation_values[:24])
            if pressure_values:
                pressure = pressure_values[0]

        self.temp_stat_value.setText(f"{temp}\u00b0C" if temp is not None else "-- \u00b0C")
        self.humidity_stat_value.setText(f"{round(humidity)} %" if humidity is not None else "-- %")
        self.wind_stat_value.setText(f"{wind_speed} km/h" if wind_speed is not None else "-- km/h")
        self.precip_stat_value.setText(f"{rain_today:.1f} mm" if rain_today is not None else "-- mm")

        feels_like = temp
        if temp is not None and humidity is not None:
            feels_like = temp + 0.33 * humidity - 4.0
        self.feels_stat_value.setText(f"{feels_like:.1f}\u00b0C" if feels_like is not None else "-- \u00b0C")
        self.direction_stat_value.setText(self._wind_direction_text(wind_dir))
        self.rain_today_value.setText(f"{rain_today:.1f} mm" if rain_today is not None else "-- mm")
        self.pressure_stat_value.setText(f"{pressure / 100:.1f} hPa" if pressure is not None else "-- hPa")
        self.sun_stat_value.setText(self._format_sun_times(daily))

        new_badge = risk_badge(rain_today or 0, wind_speed or 0)
        old_layout = self.climate_risk_badge.parentWidget().layout()
        old_layout.replaceWidget(self.climate_risk_badge, new_badge)
        self.climate_risk_badge.deleteLater()
        self.climate_risk_badge = new_badge

        if daily:
            temps = daily.get("temperature_2m_max", [])
            lows = daily.get("temperature_2m_min", [])
            rain = daily.get("precipitation_sum", [])
            outlook_lines = []
            for i in range(min(5, len(temps))):
                low_temp = lows[i] if i < len(lows) else "--"
                outlook_lines.append(f"Day {i + 1}: high {temps[i]}\u00b0C, low {low_temp}\u00b0C, rain {rain[i]} mm")
            self.daily_weather_text.setText("\n".join(outlook_lines))
            self.temp_sparkline.setValues(temps[:5])
            self.rain_sparkline.setValues(rain[:5])
        else:
            self.daily_weather_text.setText("Daily forecast unavailable.")
            self.temp_sparkline.setValues([])
            self.rain_sparkline.setValues([])

        self.climate_status.setText("Forecast loaded.")

    def _wind_direction_text(self, degrees):
        try:
            deg = float(degrees)
        except (TypeError, ValueError):
            return "--"
        directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW", "N"]
        return directions[round(deg / 45) % 8]

    def _format_sun_times(self, daily):
        sunrise = (daily.get("sunrise") or [None])[0]
        sunset = (daily.get("sunset") or [None])[0]
        if sunrise and sunset:
            return f"{sunrise.split('T')[-1]} / {sunset.split('T')[-1]}"
        return "-- / --"

    def _on_weather_err(self, error):
        self.climate_status.setText(f"Forecast fetch failed: {error}")
        self.current_weather_text.setText("Unable to load weather data.")
        self.daily_weather_text.setText("Unable to load forecast data.")

    # ---------------- Marine & Fleet ---------------- #
    def _page_marine_fleet(self):
        inner = QWidget()
        inner.setObjectName("Content")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(14)

        layout.addWidget(section_title("Marine & Fleet Weather", "Sea conditions, fleet forecast & shipping report"))

        row = QHBoxLayout()
        row.setSpacing(14)

        sea_card = Card()
        sea_layout = QVBoxLayout(sea_card)
        sea_layout.setContentsMargins(16, 14, 16, 14)
        heading = QLabel("\u26F5  Sea Weather Forecast (24h)")
        heading.setProperty("class", "CardHeading")
        sea_layout.addWidget(heading)
        self.sea_text = QTextEdit()
        self.sea_text.setReadOnly(True)
        self.sea_text.setText("Loading...")
        sea_layout.addWidget(self.sea_text, 1)
        row.addWidget(sea_card, 1)

        fleet_card = Card()
        fleet_layout = QVBoxLayout(fleet_card)
        fleet_layout.setContentsMargins(16, 14, 16, 14)
        heading2 = QLabel("\U0001F6A2  Fleet & Shipping Forecast")
        heading2.setProperty("class", "CardHeading")
        fleet_layout.addWidget(heading2)
        self.fleet_text = QTextEdit()
        self.fleet_text.setReadOnly(True)
        self.fleet_text.setText("Loading...")
        fleet_layout.addWidget(self.fleet_text, 1)
        row.addWidget(fleet_card, 1)

        layout.addLayout(row, 1)
        return inner

    # ---------------- AI Analysis (fixed Markdown rendering) ---------------- #
    def _page_ai_analysis(self):
        inner = QWidget()
        inner.setObjectName("Content")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(14)

        layout.addWidget(section_title("AI Weather Analysis", "Gemini reads the live forecast and explains it for you"))

        control_card = Card()
        control_layout = QVBoxLayout(control_card)
        control_layout.setContentsMargins(18, 16, 18, 16)
        control_layout.setSpacing(10)

        self.ai_status_lbl = QLabel("Choose a city and tap a button to get started.")
        self.ai_status_lbl.setProperty("class", "Faint")
        self.ai_status_lbl.setWordWrap(True)
        control_layout.addWidget(self.ai_status_lbl)

        row = QHBoxLayout()
        row.setSpacing(12)
        self.ai_city_combo = QComboBox()
        self.ai_city_combo.addItem("Sri Lanka (regional summary)", None)
        for city, lat, lon in SRI_LANKA_CITIES:
            self.ai_city_combo.addItem(city, (city, lat, lon))
        row.addWidget(self.ai_city_combo, 1)

        self.ai_simple_toggle = QCheckBox("Simple mode (plain language)")
        self.ai_simple_toggle.setChecked(self.simple_mode)
        self.ai_simple_toggle.stateChanged.connect(self.apply_simple_mode)
        row.addWidget(self.ai_simple_toggle)
        control_layout.addLayout(row)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self.ai_summary_btn = QPushButton("Summarize Conditions")
        self.ai_summary_btn.setProperty("class", "ActionBtn")
        self.ai_summary_btn.setCursor(Qt.PointingHandCursor)
        self.ai_summary_btn.clicked.connect(lambda: self._run_ai_task("summary"))
        btn_row.addWidget(self.ai_summary_btn)

        self.ai_plan_btn = QPushButton("Generate Action Plan")
        self.ai_plan_btn.setProperty("class", "ActionBtn")
        self.ai_plan_btn.setCursor(Qt.PointingHandCursor)
        self.ai_plan_btn.clicked.connect(lambda: self._run_ai_task("action_plan"))
        btn_row.addWidget(self.ai_plan_btn)
        btn_row.addStretch(1)
        control_layout.addLayout(btn_row)

        layout.addWidget(control_card)

        self.ai_result_card = Card()
        result_layout = QVBoxLayout(self.ai_result_card)
        result_layout.setContentsMargins(18, 16, 18, 16)
        result_layout.setSpacing(10)
        heading = QLabel("Result")
        heading.setProperty("class", "CardHeading")
        result_layout.addWidget(heading)
        self.ai_result_view = MarkdownView("Nothing here yet — pick a city above and tap a button.")
        result_layout.addWidget(self.ai_result_view)
        layout.addWidget(self.ai_result_card)

        self.ai_chat_card = Card()
        chat_layout = QVBoxLayout(self.ai_chat_card)
        chat_layout.setContentsMargins(18, 16, 18, 16)
        chat_layout.setSpacing(10)
        heading3 = QLabel("Ask a follow-up question")
        heading3.setProperty("class", "CardHeading")
        chat_layout.addWidget(heading3)
        self.ai_chat_output = MarkdownView("Ask about Sri Lanka weather, a specific city, or what any of this means.")
        chat_layout.addWidget(self.ai_chat_output)

        ask_row = QHBoxLayout()
        ask_row.setSpacing(10)
        self.ai_user_input = QLineEdit()
        self.ai_user_input.setPlaceholderText("e.g. Should I cancel my beach trip tomorrow?")
        self.ai_user_input.returnPressed.connect(self._start_ai_chat)
        ask_row.addWidget(self.ai_user_input, 1)
        ask_btn = QPushButton("Ask")
        ask_btn.setProperty("class", "ActionBtn")
        ask_btn.setCursor(Qt.PointingHandCursor)
        ask_btn.clicked.connect(self._start_ai_chat)
        ask_row.addWidget(ask_btn)
        chat_layout.addLayout(ask_row)
        layout.addWidget(self.ai_chat_card)

        layout.addStretch(1)
        return scroll_wrap(inner)

    def _current_ai_city(self):
        selection = self.ai_city_combo.currentData()
        if selection is None:
            return PRIMARY_CLIMATE_LOCATION["name"], PRIMARY_CLIMATE_LOCATION["latitude"], PRIMARY_CLIMATE_LOCATION["longitude"]
        return selection

    def _set_ai_buttons_enabled(self, enabled):
        self.ai_summary_btn.setEnabled(enabled)
        self.ai_plan_btn.setEnabled(enabled)

    def _run_ai_task(self, mode):
        city_name, lat, lon = self._current_ai_city()
        self.ai_status_lbl.setText("Fetching the latest forecast and asking Gemini\u2026")
        self._set_ai_buttons_enabled(False)
        try:
            national_data = _fetch_open_meteo_data(
                PRIMARY_CLIMATE_LOCATION["latitude"], PRIMARY_CLIMATE_LOCATION["longitude"]
            )
            city_data = _fetch_open_meteo_data(lat, lon)
        except Exception as e:
            self.ai_status_lbl.setText(f"Couldn't fetch forecast data: {e}")
            self._set_ai_buttons_enabled(True)
            return

        national_summary = _format_weather_summary(national_data, "Sri Lanka regional")
        city_summary = _format_weather_summary(city_data, city_name)
        prompt = build_ai_prompt(
            mode,
            self.simple_mode,
            national_summary,
            city_name,
            city_summary,
            language=AI_LANGUAGE_OPTIONS[self.ai_language_name],
        )

        self.ai_worker = AIWorker(prompt, self.gemini_api_endpoint, self.gemini_api_key)
        self.ai_worker.finished_ok.connect(self._on_ai_task_ok)
        self.ai_worker.finished_err.connect(self._on_ai_task_err)
        _track_worker(self.ai_worker)
        self.ai_worker.start()

    def _on_ai_task_ok(self, text):
        self.ai_result_view.set_markdown(text)
        self.ai_status_lbl.setText("Done. You can ask a follow-up question below.")
        self._set_ai_buttons_enabled(True)

    def _on_ai_task_err(self, error):
        self.ai_result_view.set_markdown(f"**Couldn't get an AI analysis:** {error}")
        self.ai_status_lbl.setText("Something went wrong — check your Gemini API key in Settings.")
        self._set_ai_buttons_enabled(True)

    def _start_ai_chat(self):
        question = self.ai_user_input.text().strip()
        if not question:
            return
        self.ai_user_input.clear()
        self.ai_chat_output.set_markdown(f"**You asked:** {question}\n\n*Thinking\u2026*")

        city_name, lat, lon = self._current_ai_city()
        try:
            national_data = _fetch_open_meteo_data(
                PRIMARY_CLIMATE_LOCATION["latitude"], PRIMARY_CLIMATE_LOCATION["longitude"]
            )
            city_data = _fetch_open_meteo_data(lat, lon)
            national_summary = _format_weather_summary(national_data, "Sri Lanka regional")
            city_summary = _format_weather_summary(city_data, city_name)
        except Exception:
            national_summary = "unavailable"
            city_summary = "unavailable"

        prompt = build_ai_prompt(
            "chat",
            self.simple_mode,
            national_summary,
            city_name,
            city_summary,
            question=question,
            language=AI_LANGUAGE_OPTIONS[self.ai_language_name],
        )
        self.ai_chat_worker = AIWorker(prompt, self.gemini_api_endpoint, self.gemini_api_key)
        self.ai_chat_worker.finished_ok.connect(lambda text, q=question: self.ai_chat_output.set_markdown(f"**You asked:** {q}\n\n{text}"))
        self.ai_chat_worker.finished_err.connect(lambda err, q=question: self.ai_chat_output.set_markdown(f"**You asked:** {q}\n\n*Couldn't get an answer: {err}*"))
        _track_worker(self.ai_chat_worker)
        self.ai_chat_worker.start()

    # ---------------- Live Radar ---------------- #
    def _page_live_radar(self):
        inner = QWidget()
        inner.setObjectName("Content")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(0, 0, 0, 0)

        if not HAS_WEBENGINE:
            return placeholder_page(
                "Interactive Radar Unavailable",
                "Install PyQtWebEngine to enable this page:\npip install PyQtWebEngine --break-system-packages",
                icon="\U0001F5FA",
            )

        view = QWebEngineView()
        windy_url = (
            "https://embed.windy.com/embed.html?type=map&location=coordinates"
            "&metricRain=mm&metricTemp=%C2%B0C&metricWind=km/h&zoom=7"
            "&overlay=rain&product=ecmwf&level=surface&lat=7.873&lon=80.772"
        )
        view.setUrl(QUrl(windy_url))
        layout.addWidget(view)
        return inner

    # ---------------- Emergency Hub ---------------- #
    def _page_emergency_hub(self):
        inner = QWidget()
        inner.setObjectName("Content")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(16)

        layout.addWidget(section_title("Emergency Hub", "Immediate action points and contact numbers"))

        self.emergency_status_card = Card(danger=True)
        es_layout = QVBoxLayout(self.emergency_status_card)
        es_layout.setContentsMargins(20, 16, 20, 16)
        es_heading = QLabel("Current alert status")
        es_heading.setProperty("class", "DangerHeading")
        es_layout.addWidget(es_heading)
        self.emergency_status_text = QLabel("Checking for active advisories\u2026")
        self.emergency_status_text.setWordWrap(True)
        self.emergency_status_text.setProperty("class", "Body")
        es_layout.addWidget(self.emergency_status_text)
        layout.addWidget(self.emergency_status_card)

        hotline_card = Card()
        hl = QVBoxLayout(hotline_card)
        hl.setContentsMargins(24, 24, 24, 24)
        hl.setSpacing(10)
        h1 = QLabel("National Emergency Hotlines")
        h1.setProperty("class", "CardHeading")
        hl.addWidget(h1)
        grid = QGridLayout()
        grid.setSpacing(15)
        for i, (name, num) in enumerate(EMERGENCY_HOTLINES):
            lbl = QLabel(name)
            lbl.setProperty("class", "Body")
            val = QLabel(num)
            val.setStyleSheet(f"color: {COL_TEXT}; font-size: 20px; font-weight: 800;")
            grid.addWidget(lbl, i // 2, (i % 2) * 2)
            grid.addWidget(val, i // 2, (i % 2) * 2 + 1)
        hl.addLayout(grid)
        layout.addWidget(hotline_card)

        sop_card = Card()
        sl = QVBoxLayout(sop_card)
        sl.setContentsMargins(24, 24, 24, 24)
        sl.setSpacing(12)
        h2 = QLabel("What To Do — By Situation")
        h2.setProperty("class", "CardHeading")
        sl.addWidget(h2)
        for title, body in SAFETY_SOPS:
            row_title = QLabel(f"\u2022 {title}")
            row_title.setStyleSheet(f"color: {COL_ACCENT}; font-size: 14px; font-weight: 700;")
            sl.addWidget(row_title)
            row_body = QLabel(body)
            row_body.setWordWrap(True)
            row_body.setProperty("class", "Body")
            sl.addWidget(row_body)
        layout.addWidget(sop_card)

        layout.addStretch(1)
        return scroll_wrap(inner)

    # ---------------- Advisories & Links ---------------- #
    def _page_advisories(self):
        inner = QWidget()
        inner.setObjectName("Content")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(14)

        layout.addWidget(section_title("Severe Weather Advisories", "Official PDF bulletins (opens in your browser)"))
        self.advisory_card = Card()
        self.advisory_layout = QVBoxLayout(self.advisory_card)
        self.advisory_layout.setContentsMargins(18, 14, 18, 14)
        self.advisory_layout.setSpacing(14)
        layout.addWidget(self.advisory_card)

        layout.addWidget(section_title("Other Bulletins & Documents", "Weekly / national / drought / agromet reports"))
        self.bulletins_card = Card()
        self.bulletins_layout = QVBoxLayout(self.bulletins_card)
        self.bulletins_layout.setContentsMargins(18, 14, 18, 14)
        self.bulletins_layout.setSpacing(14)
        layout.addWidget(self.bulletins_card)

        layout.addWidget(section_title("Useful Web Resources", "Official portals and mobile apps"))
        self.weblinks_card = Card()
        self.weblinks_layout = QVBoxLayout(self.weblinks_card)
        self.weblinks_layout.setContentsMargins(18, 14, 18, 14)
        self.weblinks_layout.setSpacing(8)
        layout.addWidget(self.weblinks_card)

        layout.addStretch(1)
        return scroll_wrap(inner)

    # ---------------- Weather Graphics ---------------- #
    def _page_graphics(self):
        inner = QWidget()
        inner.setObjectName("Content")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(14)

        layout.addWidget(section_title("Weather Graphics", "Analysis, forecast, marine & aviation charts"))

        self.graphics_container = QVBoxLayout()
        self.graphics_container.setSpacing(14)
        layout.addLayout(self.graphics_container)
        layout.addStretch(1)
        return scroll_wrap(inner)

    # ---------------- Settings ---------------- #
    def _page_settings(self):
        inner = QWidget()
        inner.setObjectName("Content")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(14)

        layout.addWidget(section_title("Settings & Preferences", "Customize how SLDAS looks and behaves"))

        display_card = Card()
        display_layout = QVBoxLayout(display_card)
        display_layout.setContentsMargins(20, 18, 20, 18)
        display_layout.setSpacing(14)
        heading = QLabel("\U0001F5A5  Display")
        heading.setProperty("class", "CardHeading")
        display_layout.addWidget(heading)

        form = QFormLayout()
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignLeft)
        font_label = QLabel("App font size")
        font_label.setProperty("class", "Body")
        self.font_size_combo = QComboBox()
        self.font_size_combo.addItems(list(FONT_SCALE_OPTIONS.keys()))
        self.font_size_combo.setCurrentText(self.font_scale_name)
        self.font_size_combo.currentTextChanged.connect(self.apply_font_scale)
        form.addRow(font_label, self.font_size_combo)
        display_layout.addLayout(form)
        layout.addWidget(display_card)

        data_card = Card()
        data_layout = QVBoxLayout(data_card)
        data_layout.setContentsMargins(20, 18, 20, 18)
        data_layout.setSpacing(14)
        heading2 = QLabel("\U0001F504  Data & Refresh")
        heading2.setProperty("class", "CardHeading")
        data_layout.addWidget(heading2)

        form2 = QFormLayout()
        form2.setSpacing(12)
        form2.setLabelAlignment(Qt.AlignLeft)
        refresh_label = QLabel("Auto-refresh interval")
        refresh_label.setProperty("class", "Body")
        self.refresh_interval_combo = QComboBox()
        self.refresh_interval_combo.addItems(list(REFRESH_INTERVAL_OPTIONS.keys()))
        self.refresh_interval_combo.setCurrentText(self.refresh_interval_name)
        self.refresh_interval_combo.currentTextChanged.connect(self.apply_refresh_interval)
        form2.addRow(refresh_label, self.refresh_interval_combo)
        data_layout.addLayout(form2)

        source_note = QLabel(f"Data source: {DATA_URL}")
        source_note.setProperty("class", "Faint")
        source_note.setWordWrap(True)
        data_layout.addWidget(source_note)

        pdf_note = QLabel(
            "PDF thumbnail previews require the optional 'pymupdf' package."
            + (" (currently installed)" if HAS_FITZ else " (not installed \u2014 links will still work)")
        )
        pdf_note.setProperty("class", "Faint")
        pdf_note.setWordWrap(True)
        data_layout.addWidget(pdf_note)

        radar_note = QLabel(
            "Live Radar requires the optional 'PyQtWebEngine' package."
            + (" (currently installed)" if HAS_WEBENGINE else " (not installed \u2014 that page will show install instructions)")
        )
        radar_note.setProperty("class", "Faint")
        radar_note.setWordWrap(True)
        data_layout.addWidget(radar_note)
        layout.addWidget(data_card)

        ai_card = Card()
        ai_layout = QVBoxLayout(ai_card)
        ai_layout.setContentsMargins(20, 18, 20, 18)
        ai_layout.setSpacing(14)
        heading3 = QLabel("\U0001F4AC  AI Analysis")
        heading3.setProperty("class", "CardHeading")
        ai_layout.addWidget(heading3)

        simple_row = QCheckBox("Use simple, teenager-friendly language by default")
        simple_row.setChecked(self.simple_mode)
        simple_row.stateChanged.connect(self.apply_simple_mode)
        ai_layout.addWidget(simple_row)

        language_label = QLabel("AI output language")
        language_label.setProperty("class", "Body")
        self.ai_language_combo = QComboBox()
        self.ai_language_combo.addItems(list(AI_LANGUAGE_OPTIONS.keys()))
        self.ai_language_combo.setCurrentText(self.ai_language_name)
        self.ai_language_combo.currentTextChanged.connect(self.apply_ai_language)
        api_form = QFormLayout()
        api_form.setSpacing(12)
        api_form.setLabelAlignment(Qt.AlignLeft)
        api_form.addRow(language_label, self.ai_language_combo)

        endpoint_label = QLabel("Gemini API Endpoint")
        endpoint_label.setProperty("class", "Body")
        self.gemini_endpoint_input = QLineEdit(self.gemini_api_endpoint)
        self.gemini_endpoint_input.setPlaceholderText(DEFAULT_AI_GEMINI_API_ENDPOINT)
        self.gemini_endpoint_input.editingFinished.connect(self.apply_gemini_settings)
        api_form.addRow(endpoint_label, self.gemini_endpoint_input)

        key_label = QLabel("Gemini API Key")
        key_label.setProperty("class", "Body")
        self.gemini_key_input = QLineEdit(self.gemini_api_key)
        self.gemini_key_input.setEchoMode(QLineEdit.Password)
        self.gemini_key_input.setPlaceholderText("AIzaSy...")
        self.gemini_key_input.editingFinished.connect(self.apply_gemini_settings)
        api_form.addRow(key_label, self.gemini_key_input)
        ai_layout.addLayout(api_form)

        api_note = QLabel(
            "Your key is stored locally on this device only (never bundled into the app "
            "code) and is only sent directly to Google's API."
        )
        api_note.setProperty("class", "Faint")
        api_note.setWordWrap(True)
        ai_layout.addWidget(api_note)
        layout.addWidget(ai_card)

        about_card = Card()
        about_layout = QVBoxLayout(about_card)
        about_layout.setContentsMargins(20, 18, 20, 18)
        about_layout.setSpacing(6)
        heading4 = QLabel("\u2139  About")
        heading4.setProperty("class", "CardHeading")
        about_layout.addWidget(heading4)
        about_text = QLabel(
            "SLDAS Ultimate \u2014 Sri Lankan Atmospheric Alert System\n"
            "Built on top of the public Department of Meteorology feed and Open-Meteo.\n"
            "Settings are saved automatically and persist between launches."
        )
        about_text.setProperty("class", "Body")
        about_text.setWordWrap(True)
        about_layout.addWidget(about_text)
        layout.addWidget(about_card)

        layout.addStretch(1)
        return scroll_wrap(inner)

    # ------------------------------------------------------------------ #
    # Refresh logic
    # ------------------------------------------------------------------ #
    def refresh_now(self):
        if self.worker is not None and self.worker.isRunning():
            return
        self.status_dot.setStyleSheet(f"color: {COL_WARN}; font-size: 11px;")
        self.status_text.setText("Refreshing...")
        self.seconds_to_refresh = self.refresh_interval_ms // 1000

        self.worker = FetchWorker()
        self.worker.finished_ok.connect(self._on_fetch_ok)
        self.worker.finished_err.connect(self._on_fetch_err)
        self.worker.start()

    def _on_fetch_ok(self, data):
        self.data = data
        self.last_updated = datetime.now()
        self.last_error = None
        self.status_dot.setStyleSheet(f"color: {COL_ACCENT}; font-size: 11px;")
        self.status_text.setText("Live \u2013 connected")
        self._after_fetch()

    def _on_fetch_err(self, err_msg, cached_data):
        self.last_error = err_msg
        if cached_data:
            self.data = cached_data
            self.last_updated = self.last_updated or datetime.now()
            self.status_dot.setStyleSheet(f"color: {COL_WARN}; font-size: 11px;")
            self.status_text.setText("Using cached data")
        else:
            self.status_dot.setStyleSheet(f"color: {COL_DANGER}; font-size: 11px;")
            self.status_text.setText("Offline \u2013 no data")
        self._after_fetch()

    def _after_fetch(self):
        if self.last_updated:
            self.last_updated_lbl.setText(f"Last updated: {self.last_updated.strftime('%Y-%m-%d %H:%M:%S')}")
        if self.data:
            self._populate_pages()

    def _tick_countdown(self):
        if self.seconds_to_refresh > 0:
            self.seconds_to_refresh -= 1
        mins, secs = divmod(max(self.seconds_to_refresh, 0), 60)
        self.countdown_lbl.setText(f"Next auto-refresh in {mins:02d}:{secs:02d}")

    # ------------------------------------------------------------------ #
    # Populate widgets from fetched data
    # ------------------------------------------------------------------ #
    def _populate_pages(self):
        d = self.data
        self._populate_dashboard(d)
        self._populate_forecast(d)
        self._populate_marine(d)
        self._populate_advisories(d)
        self._populate_graphics(d)
        self._populate_emergency_hub(d)

    @staticmethod
    def _first_line(text):
        for line in (text or "").splitlines():
            line = line.strip()
            if line:
                return line
        return ""

    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _add_link_row(self, layout, label_text, url):
        row = QHBoxLayout()
        row.setSpacing(8)
        icon = QLabel("\U0001F517" if url else "\u2013")
        icon.setStyleSheet(f"color: {COL_ACCENT if url else COL_TEXT_FAINT}; font-size: 11px;")
        row.addWidget(icon)
        row.addWidget(clickable_link(label_text, url), 1)
        wrap = QWidget()
        wrap.setLayout(row)
        layout.addWidget(wrap)

    def _add_pdf_row(self, layout, label_text, url):
        row = QHBoxLayout()
        row.setSpacing(14)
        preview = PdfPreview(url, max_width=130)
        preview.setFixedWidth(130)
        row.addWidget(preview)

        text_col = QVBoxLayout()
        text_col.setSpacing(4)
        title_lbl = QLabel(label_text)
        title_lbl.setProperty("class", "CardLabel")
        text_col.addWidget(title_lbl)
        # Keep the original external link but add an "Open in app" button that
        # launches the in-app PdfViewerDialog when pymupdf is available.
        link_row = QHBoxLayout()
        link_row.setSpacing(8)
        link_row.addWidget(clickable_link("\u25B8 Open full PDF", url))
        open_btn = QPushButton("Open in app")
        open_btn.setProperty("class", "ActionBtn")
        if not HAS_FITZ:
            open_btn.setEnabled(False)
            open_btn.setToolTip("Install pymupdf to enable in-app PDF viewing")
        else:
            open_btn.clicked.connect(lambda _checked=False, u=url: PdfViewerDialog(u, parent=self).exec_())
        link_row.addWidget(open_btn)
        link_wrap = QWidget()
        link_wrap.setLayout(link_row)
        text_col.addWidget(link_wrap)
        text_col.addStretch(1)
        row.addLayout(text_col, 1)

        wrap = QWidget()
        wrap.setLayout(row)
        layout.addWidget(wrap)

    def _active_advisories(self, d):
        adv = d.get("severe_weather_advisory", {}) or {}
        labels = {
            "tsunami_pdf": "Tsunami Advisory",
            "land_pdf": "Land Weather Advisory",
            "lighting_pdf": "Lightning Advisory",
            "sea_pdf": "Sea Weather Advisory",
            "heat_pdf": "Heat Advisory",
        }
        return [labels[k] for k in labels if adv.get(k)]

    def _populate_dashboard(self, d):
        if self.last_error and not d:
            banner = self.last_error
        elif self.last_error:
            banner = f"Showing cached data \u2014 {self.last_error}"
        else:
            issued_line = self._first_line(d.get("public_weather_forecast", ""))
            banner = issued_line or "Data loaded successfully."
        self.dash_banner_lbl.setText(banner)

        active = self._active_advisories(d)
        mapping = {
            "public_weather_forecast": "Updated" if d.get("public_weather_forecast") else "No data",
            "sea_weather_forecast": "Updated" if d.get("sea_weather_forecast") else "No data",
            "fleet_shipping_forecast": "Updated" if d.get("fleet_shipping_forecast") else "No data",
            "severe_weather_advisory": f"{len(active)} active" if active else "No active advisories",
        }
        for key, lbl in self.dash_cards.items():
            lbl.setText(mapping.get(key, "\u2013"))

        el_nino = d.get("el_nino_updates", {}) or {}
        el_nino_pdf = el_nino.get("pdf")
        if el_nino_pdf:
            el_nino_url = resolve_url(el_nino_pdf)
            self.dash_el_nino_text.setText(
                "NOAA-style El Niño warning available. Open the latest bulletin for the official update."
            )
            self.dash_el_nino_link.setText(f'<a href="{el_nino_url}" style="color:{COL_ACCENT_2}; text-decoration:none;">Open El Niño bulletin</a>')
            self.dash_el_nino_link.setOpenExternalLinks(True)
            self.dash_el_nino_link.show()
        else:
            self.dash_el_nino_text.setText("No El Niño bulletin found in the latest data feed.")
            self.dash_el_nino_link.hide()

        if active:
            self.dash_severe_alert_text.setText(
                "Active weather alerts now: " + ", ".join(active) +
                ". Open the Advisories tab for the full documents."
            )
        else:
            self.dash_severe_alert_text.setText(
                "No active severe weather advisories from the Department of Meteorology right now."
            )

        self._clear_layout(self.dash_links_layout)
        web = d.get("web_gis", {}) or {}
        self._add_link_row(self.dash_links_layout, "Web GIS Weather Portal", web.get("web_gis_portal"))
        self._add_link_row(self.dash_links_layout, "Anawaki Mobile App (Play Store)", web.get("anawaki"))
        self._add_link_row(self.dash_links_layout, "PRISM Drought/Climate Info (WFP)", d.get("prism"))

    def _populate_forecast(self, d):
        self.forecast_text.setPlainText(d.get("public_weather_forecast", "") or "No forecast text available.")

    def _populate_marine(self, d):
        self.sea_text.setPlainText(d.get("sea_weather_forecast", "") or "No data available.")
        self.fleet_text.setPlainText(d.get("fleet_shipping_forecast", "") or "No data available.")

    def _populate_emergency_hub(self, d):
        active = self._active_advisories(d)
        new_hash = hashlib.md5("|".join(sorted(active)).encode()).hexdigest() if active else ""
        if new_hash and new_hash != self.last_advisories_hash:
            self.tray.showMessage("SLDAS Alert", "New weather advisories have been issued.", QSystemTrayIcon.Warning, 8000)
        self.last_advisories_hash = new_hash

        if active:
            self.emergency_status_text.setText(
                "\u26A0 Active right now: " + ", ".join(active) +
                ".\nCheck the Advisories tab for the full documents, and follow the steps below."
            )
        else:
            self.emergency_status_text.setText("\u2705 No active severe weather advisories from the Department of Meteorology right now.")

    def _populate_advisories(self, d):
        self._clear_layout(self.advisory_layout)
        adv = d.get("severe_weather_advisory", {}) or {}
        labels = {
            "tsunami_pdf": "Tsunami Advisory",
            "land_pdf": "Land Weather Advisory",
            "lighting_pdf": "Lightning Advisory",
            "sea_pdf": "Sea Weather Advisory",
            "heat_pdf": "Heat Advisory",
        }
        any_advisory = False
        for key, label in labels.items():
            url = resolve_url(adv.get(key))
            if url:
                self._add_pdf_row(self.advisory_layout, label, url)
                any_advisory = True
        if not any_advisory:
            empty_lbl = QLabel("No active advisories in the current feed.")
            empty_lbl.setProperty("class", "Faint")
            self.advisory_layout.addWidget(empty_lbl)

        self._clear_layout(self.bulletins_layout)
        wd = d.get("weather_data", {}) or {}
        bulletin_labels = {
            "newsLetter_pdf": "Newsletter",
            "weekly_pdf": "Weekly Bulletin",
            "national_pdf": "National Report",
            "agromet_pdf": "Agromet Bulletin",
            "drought_pdf": "Drought Bulletin",
            "twentyfour_pdf": "24-Hour Data",
            "volume3": "Data Volume 3",
            "volume5": "Data Volume 5",
        }
        for key, label in bulletin_labels.items():
            url = resolve_url(wd.get(key))
            if url:
                self._add_pdf_row(self.bulletins_layout, label, url)
        extra_docs = [
            ("9/15-Day Forecast", resolve_url((d.get("nine_day_forecast_link") or {}).get("pdf"))),
            ("City Weather Forecast", resolve_url((d.get("city_weather_forecast") or {}).get("pdf"))),
            ("Multi-day Boats Bulletin", resolve_url((d.get("multiday_boats") or {}).get("pdf"))),
        ]
        for label, url in extra_docs:
            if url:
                self._add_pdf_row(self.bulletins_layout, label, url)

        self._clear_layout(self.weblinks_layout)
        web = d.get("web_gis", {}) or {}
        self._add_link_row(self.weblinks_layout, "Web GIS Weather Portal", web.get("web_gis_portal"))
        self._add_link_row(self.weblinks_layout, "Anawaki App on Google Play", web.get("anawaki"))
        self._add_link_row(self.weblinks_layout, "PRISM (Drought & Climate Info)", d.get("prism"))

    def _populate_graphics(self, d):
        self._clear_layout(self.graphics_container)
        graphics = d.get("weather_graphics", {}) or {}
        categories = [
            ("analysis", "\U0001F4CA Surface Analysis"),
            ("forecast", "\U0001F326 Forecast Charts"),
            ("marine", "\u26F5 Marine Charts"),
            ("aviation", "\u2708 Aviation Charts"),
        ]
        any_cat = False
        for cat_key, cat_title in categories:
            cat_data = graphics.get(cat_key, {}) or {}
            entries = [v for v in cat_data.values() if isinstance(v, dict) and v.get("url")]
            if not entries:
                continue
            any_cat = True
            card = Card()
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(16, 14, 16, 14)
            card_layout.setSpacing(6)
            heading = QLabel(cat_title)
            heading.setProperty("class", "CardHeading")
            card_layout.addWidget(heading)
            for entry in entries:
                title = entry.get("title") or "Untitled chart"
                url = resolve_url(entry.get("url"))
                desc = entry.get("description", "")

                entry_wrap = QVBoxLayout()
                entry_wrap.setSpacing(6)
                title_lbl = QLabel(title)
                title_lbl.setProperty("class", "CardLabel")
                entry_wrap.addWidget(title_lbl)

                gif_preview = GifPreview(url, max_width=900)
                gif_preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                entry_wrap.addWidget(gif_preview)

                if desc:
                    desc_lbl = QLabel(desc[:240] + ("..." if len(desc) > 240 else ""))
                    desc_lbl.setWordWrap(True)
                    desc_lbl.setProperty("class", "Faint")
                    entry_wrap.addWidget(desc_lbl)

                entry_wrap.addWidget(clickable_link("\u25B8 Open full size in browser", url))

                entry_widget = QWidget()
                entry_widget.setLayout(entry_wrap)
                card_layout.addWidget(entry_widget)
            self.graphics_container.addWidget(card)

        if not any_cat:
            empty_lbl = QLabel("No graphics available in current feed.")
            empty_lbl.setProperty("class", "Faint")
            self.graphics_container.addWidget(empty_lbl)

    # ------------------------------------------------------------------ #
    def closeEvent(self, event):
        event.ignore()
        self.hide()
        self.tray.showMessage(
            "SLDAS", "Still running in the background \u2014 click the tray icon to reopen.",
            QSystemTrayIcon.Information, 3000,
        )


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("SLDAS Ultimate")

    window = SLDASApp()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
