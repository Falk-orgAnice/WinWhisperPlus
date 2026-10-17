"""Render reproducible feature screenshots without modifying user settings."""
from pathlib import Path
import os
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
root = Path(__file__).resolve().parents[1]
os.environ["APPDATA"] = str(root / "build/feature-preview-profile")
os.environ["LOCALAPPDATA"] = str(root / "build/feature-preview-profile")
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFontDatabase, QFont
from config.settings import Settings
import gui.settings_window as settings_module
from gui.history_window import HistoryWindow
from core.session import AudioJob, ResultVersion

app = QApplication([])
QFontDatabase.addApplicationFont("C:/Windows/Fonts/arial.ttf")
app.setFont(QFont("Arial", 10))
settings = Settings()
settings.correction_rules = [{"source": "Organize", "target": "orgAnice"}, {"source": "CRM System", "target": "CRM-System"}]
settings.save_rules()
settings_module.list_microphones = lambda: []
settings_module.list_vulkan_devices = lambda: [(0, "AMD Radeon RX 9070 XT")]
output = root / "docs/images/manual"
output.mkdir(parents=True, exist_ok=True)
window = settings_module.SettingsWindow(settings)
window.show()
app.processEvents()
for tab, name in [(0, "settings"), (1, "models"), (2, "corrections")]:
    window._tabs.setCurrentIndex(tab)
    app.processEvents()
    window.grab().save(str(output / f"{name}.png"))
history = HistoryWindow(settings=settings)
job = AudioJob(root / "build/preview.wav", duration=123)
job.versions = [ResultVersion("large", "de", None, raw_text="Wir verwenden Organize für unsere Kundenverwaltung.",
                              corrected_text="Wir verwenden orgAnice für unsere Kundenverwaltung.",
                              text="Wir verwenden orgAnice für unsere Kundenverwaltung.", status="complete"),
                ResultVersion("large-v3-turbo", "de", "en", raw_text="Wir verwenden Organize für unsere Kundenverwaltung.",
                              text="We use orgAnice for our customer management.", status="complete")]
history.set_jobs([job])
history.show()
app.processEvents()
history.grab().save(str(output / "audio-history.png"))
window.close()
history.close()
print("Rendered settings, models, corrections and audio history")
