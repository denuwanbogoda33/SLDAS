# SLDAS Ultimate — Sri Lankan Atmospheric Alert System

**SLDAS Ultimate** is a desktop atmospheric monitoring and weather alert application tailored for Sri Lanka. Built using **PyQt5**, it integrates weather data, climate metrics, live radar streams, emergency hotlines, and Gemini AI analysis into a modern dashboard interface.

---

## Key Features

* **Unified Weather Dashboard**: Real-time meteorological data and forecasts fetched from `meteo.gov.lk` and Open-Meteo.
* **Smart Risk Badges**: Visual indicators (Low / Moderate / High) calculated from live rainfall and wind metrics.
* **AI Analysis (Powered by Gemini)**:
  * Generates daily weather summaries, customized city updates, and practical action checklists.
  * Interactive chat assistant for custom weather inquiries.
  * **Simple Mode**: Toggle plain-language explanations for non-technical users.
  * **Language Support**: AI insights delivered in English or Sinhala.
* **Live Radar & Emergency Hub**:
  * Embedded Windy live radar view.
  * Direct access to emergency contacts (Disaster Management Center, Police, Ambulance, Fire & Rescue) and safety SOPs for tsunamis, flash floods, landslides, and lightning.
* **Weather Graphics & Advisories**:
  * Animated GIF weather map previews.
  * Built-in PDF viewer for official advisory documents.
* **System Tray Integration**: Minimized background operation with native system tray notifications.

---

## Dependencies & Requirements

Ensure you have Python 3.8+ installed. You can install the required packages using `pip`:

```bash
# Core Dependencies
pip install PyQt5 requests --break-system-packages

# Optional: PDF Document Previewing (Advisories)
pip install pymupdf --break-system-packages

# Optional: Embedded Live Radar Page
pip install PyQtWebEngine --break-system-packages
