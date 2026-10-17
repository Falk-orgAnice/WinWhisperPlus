# WinWhisperPlus Benutzerhandbuch

Dieses Handbuch beschreibt die Bedienung von WinWhisperPlus Version 1.2.5. WinWhisperPlus ist ein Windows-Tool fÃ¼r lokale Spracherkennung mit Whisper. Die Aufnahme wird lokal verarbeitet; nach der Erkennung kann der Text automatisch in das aktive Eingabefeld eingefÃ¼gt werden.

## Ãœberblick

WinWhisperPlus lÃ¤uft im Hintergrund und zeigt ein kleines Statusfenster sowie ein Symbol im Windows-Infobereich. Die wichtigsten Aufgaben sind:

- Sprache aufnehmen und in Text umwandeln.
- Den erkannten Text automatisch per Zwischenablage einfÃ¼gen.
- Zwischen Deutsch, Polnisch, Englisch, FranzÃ¶sisch und NiederlÃ¤ndisch als Diktiersprache wechseln.
- Hotkeys, Mikrofon, OberflÃ¤chensprache und Whisper-Modelle konfigurieren.
- Den finalen Text bei Bedarf vollstÃ¤ndig lokal mit KI strukturieren und bereinigen.
- Vorherige Transkriptionen aus dem Verlauf erneut einfÃ¼gen.
- Nutzungsstatistiken fÃ¼r erfolgreiche finale Transkriptionen anzeigen.

## Installation und erster Start

WinWhisperPlus kann pro Windows-Benutzer nur einmal laufen, auch bei unterschiedlichen Programmordnern sowie Debug- und Release-Builds. Ein weiterer Start zeigt den Hinweis `WinWhisperPlus lÃ¤uft bereits` und beendet sich vor dem Laden von Einstellungen, Modellen oder Hotkeys. PrÃ¼fen Sie bei Bedarf den Infobereich der Taskleiste. Bereits laufende Ã¤ltere EXE-Versionen werden ebenfalls erkannt. Nach dem Beenden oder einem Absturz gibt Windows die Sperre automatisch frei.

Verwenden Sie das bereitgestellte Setup. Nach der Installation starten Sie `WinWhisperPlus.exe`. Beim ersten Start kann Whisper das ausgewÃ¤hlte Modell herunterladen; dafÃ¼r ist einmalig Internetzugriff erforderlich. Danach liegen Modell, Einstellungen und Statistikdaten lokal.

Nach dem Start erscheint das kleine Statusfenster. Die Anwendung bleibt aktiv, auch wenn kein groÃŸes Hauptfenster geÃ¶ffnet ist.

![Statusfenster: Bereit](images/manual/status-ready.png)

## Statusfenster und MenÃ¼

Das Statusfenster zeigt den aktuellen Zustand der Anwendung:

- `Bereit`: WinWhisperPlus wartet auf eine Aufnahme.
- `Aufnahme lÃ¤uft`: Das Mikrofon wird aufgenommen.
- `Verarbeitung lÃ¤uft`: Die Aufnahme wird transkribiert.
- `Text eingefÃ¼gt`: Der erkannte Text wurde eingefÃ¼gt.
- `Initialisierung` oder `Modelle laden...`: Die App oder Whisper-Modelle werden vorbereitet.

Im unteren Bereich des Statusfensters steht der Aufnahme-Hotkey. Mit Rechtsklick auf das Statusfenster oder Ã¼ber das Tray-Symbol Ã¶ffnen Sie das MenÃ¼ mit diesen EintrÃ¤gen:

- `Aufnahme starten` oder `Aufnahme stoppen`
- `Verlauf...`
- `Statistiken...`
- `Einstellungen...`
- `Beenden`

![Statusfenster: Aufnahme lÃ¤uft](images/manual/status-recording.png)

## Aufnahme starten und stoppen

StandardmÃ¤ÃŸig starten oder stoppen Sie eine Aufnahme mit `Ctrl+Alt+H`. Alternativ verwenden Sie den MenÃ¼punkt `Aufnahme starten` im KontextmenÃ¼. WÃ¤hrend der Aufnahme spricht man den gewÃ¼nschten Text ein; beim Stoppen wird die Aufnahme final transkribiert.

Wenn `Text automatisch einfÃ¼gen` aktiviert ist, setzt WinWhisperPlus den erkannten Text per `Ctrl+V` in das aktuell aktive Eingabefeld ein. Klicken Sie daher vor dem Stoppen oder vor dem finalen EinfÃ¼gen in das Zielprogramm, zum Beispiel Editor, E-Mail, Browser oder Fachanwendung.

Der Hotkey `Alt+Shift+S` schaltet die Diktiersprache in der Reihenfolge Deutsch, Polnisch, Englisch, FranzÃ¶sisch, NiederlÃ¤ndisch um. Nach dem Umschalten zeigt das Statusfenster kurz die neue Sprache an.

## Einstellungen

Ã–ffnen Sie `Einstellungen...`, um das Verhalten der Anwendung anzupassen.

![Einstellungen](images/manual/settings.png)

Die wichtigsten Optionen:

- `Aufnahme starten/stoppen`: Hotkey fÃ¼r die Aufnahme. Klicken Sie in das Feld und drÃ¼cken Sie die gewÃ¼nschte Tastenkombination.
- `Sprache umschalten`: Hotkey fÃ¼r den Wechsel der Diktiersprache.
- `Diktiersprache`: Sprache, in der Whisper die Aufnahme interpretieren soll.
- `OberflÃ¤chensprache`: Sprache der BenutzeroberflÃ¤che. VerfÃ¼gbar sind Deutsch, Polnisch und Englisch.
- `Mikrofon`: EingabegerÃ¤t. `System-Standard` verwendet das Windows-Standardmikrofon.
- `Live (schnell)`: Modell fÃ¼r laufende Live-Erkennung. `tiny` und `base` sind fÃ¼r kurze Latenz vorgesehen.
- `Final (genau)`: Modell fÃ¼r die abschlieÃŸende Transkription. GrÃ¶ÃŸere Modelle sind genauer, brauchen aber mehr Zeit und Leistung.
- `Text automatisch einfÃ¼gen`: FÃ¼gt erkannte Texte automatisch in das aktive Eingabefeld ein.
- `Laufende Erkennung und laufendes EinfÃ¼gen aktivieren`: FÃ¼gt stabile Zwischenergebnisse wÃ¤hrend der Aufnahme ein.
- `Emoji-Modus`: ErgÃ¤nzt bekannte SchlÃ¼sselwÃ¶rter im erkannten Text mit passenden Emojis.
- `Lokale Textoptimierung`: Ist standardmÃ¤ÃŸig ausgeschaltet. Wenn sie aktiviert ist, verarbeitet das mitgelieferte Qwen3-Modell nur die finale Transkription auf diesem Computer. Die Optionen lassen sich frei kombinieren:
  - `Struktur und Zeichensetzung verbessern`: ergÃ¤nzt Satzzeichen, sinnvolle AbsÃ¤tze und bei Bedarf einfache Listen.
  - `Eindeutige Wiederholungen und FÃ¼llwÃ¶rter entfernen`: bereinigt nur klar Ã¼berflÃ¼ssige Teile.
  - `Lesbarkeit vorsichtig redigieren`: formuliert den Inhalt behutsam klarer und knapper.
  - `In eine andere Diktiersprache Ã¼bersetzen`: Ã¼bersetzt den Endtext wahlweise nach Deutsch, Polnisch, Englisch, FranzÃ¶sisch oder NiederlÃ¤ndisch. Die Ãœbersetzung bleibt lokal und wird Ã¼bersprungen, wenn Quell- und Zielsprache gleich sind.

Die Ausgabe bleibt Klartext mit AbsÃ¤tzen und `-`-AufzÃ¤hlungen. Namen, Zahlen, Fakten und unklare Textstellen dÃ¼rfen nicht erfunden oder ergÃ¤nzt werden. Ãœbersetzung ist unabhÃ¤ngig von Formatierung und Bereinigung auswÃ¤hlbar. Bei Fehlern bleibt das Originaltranskript im Verlauf verfÃ¼gbar. Eine fehlgeschlagene Ãœbersetzung wird ausdrÃ¼cklich gekennzeichnet und nicht automatisch als fertiges Ergebnis eingefÃ¼gt.

Speichern Ã¼bernimmt die Einstellungen sofort und registriert die Hotkeys neu.

## Live-Erkennung

Die Live-Erkennung ist optional. Wenn sie aktiviert ist, transkribiert WinWhisperPlus wÃ¤hrend der laufenden Aufnahme Ã¼berlappende AudiostÃ¼cke und fÃ¼gt stabile Zwischenergebnisse ein. Beim Stoppen ersetzt die finale Transkription den Live-Textblock durch das endgÃ¼ltige Ergebnis.

Ist die lokale Textoptimierung aktiv, lÃ¤uft sie erst nach dieser finalen Transkription. Der vorlÃ¤ufige Live-Text wird anschlieÃŸend durch den optimierten Endtext ersetzt.

FÃ¼r Live-Erkennung ohne schnelle GPU sind kleine Modelle sinnvoll. Beginnen Sie mit `tiny`; wenn die QualitÃ¤t nicht reicht, testen Sie `base`.

## Verlauf

Der Verlauf zeigt Aufnahmen und importierte Audios der aktuellen Sitzung, einschlieÃŸlich fehlgeschlagener Erkennungen. Der neueste Eintrag steht oben. WÃ¤hlen Sie eine Aufnahme und eine Ergebnisversion. Originaltranskript und Ergebnis stehen in getrennten Registern zur VerfÃ¼gung. Mit `Kopieren`, `Text exportieren` oder `EinfÃ¼gen` verwenden Sie den Text des aktuell geÃ¶ffneten Registers.

![Audioverlauf mit Ergebnisversionen](images/manual/audio-history.png)

Mit `Abspielen` hÃ¶ren Sie das Audio an. `Audio exportieren` speichert eine dauerhafte WAV-Datei auÃŸerhalb des Sitzungsspeichers. `Erneut erkennen` bietet Modell, Quellsprache und optionale Zielsprache zur Auswahl und legt eine weitere Ergebnisversion an. Der bisherige Text bleibt erhalten. Neu berechnete Ergebnisse werden zunÃ¤chst angezeigt, ohne bereits eingefÃ¼gten Text in anderen Anwendungen zu verÃ¤ndern.

WÃ¤hrend der Verarbeitung kÃ¶nnen Sie `Abbrechen` wÃ¤hlen. `Fehlgeschlagene Abschnitte wiederholen` verwendet die erfolgreichen Abschnitte desselben Auftrags weiter. Mit `LÃ¶schen` entfernen Sie eine abgeschlossene Aufnahme aus dem Verlauf. Beim regulÃ¤ren Beenden werden sÃ¤mtliche Sitzungsaudios gelÃ¶scht. Nach einem Absturz werden verwaiste Sitzungen beim nÃ¤chsten Start bereinigt; Audios anderer laufender Instanzen bleiben erhalten. Exportieren Sie benÃ¶tigte Aufnahmen vor dem Beenden.

## Korrekturregeln

Ã–ffnen Sie `Einstellungen` und das Register `Korrekturregeln`. Mit `HinzufÃ¼gen` legen Sie eine Zeile an. Tragen Sie beispielsweise unter `Erkannt` den Text `Organize` und unter `Ersetzen durch` die Schreibweise `orgAnice` ein. Das HÃ¤kchen `Aktiv` schaltet die einzelne Regel ein oder aus; `Korrekturregeln anwenden` steuert alle Regeln unabhÃ¤ngig von der Textoptimierung.

![Editierbare Korrekturregeln](images/manual/corrections.png)

Die Suche ignoriert GroÃŸ-/Kleinschreibung und erfasst vollstÃ¤ndige WÃ¶rter oder Wortgruppen. Bei Ã¼berlappenden Regeln gewinnt die lÃ¤ngste passende Wortgruppe. Ersetzungen lÃ¶sen keine weiteren Ersetzungen aus. Eine leere Ersatzschreibweise entfernt den Treffer; ein leerer Suchtext oder doppelte Suchtexte sind nicht zulÃ¤ssig. `Speichern` Ã¼bernimmt die Regeln dauerhaft und atomisch, `Abbrechen` verwirft Ã„nderungen. Speicherfehler werden angezeigt. Die vorlÃ¤ufige Liveanzeige wird noch nicht korrigiert; Korrekturen greifen im finalen Text.

Die Regeln liegen standardmÃ¤ÃŸig unter `%APPDATA%\WinWhisperPlus\correction-rules.json`. Alle aktualisierten Installationen und Debug-/Release-Builds desselben Windows-Benutzers verwenden diesen Speicherort unabhÃ¤ngig vom Programmordner. Bisher eingebettete Regeln werden automatisch Ã¼bernommen; eine vorhandene Regeldatei hat Vorrang.

Das Feld `Regeldatei` zeigt den vollstÃ¤ndigen Pfad und lÃ¤sst sich bearbeiten. Mit `â€¦` wÃ¤hlen Sie eine Datei. Der kompakte Ordnerbutton hat den Tooltip `Datei im Explorer anzeigen` und markiert die Datei im Explorer. Existiert sie noch nicht, Ã¶ffnet er den vorhandenen Zielordner. Fehlende Ordner werden erst beim Speichern angelegt.

Eine vorhandene Datei wird als Vorschau geladen. Bei einem neuen Pfad werden die Tabellenregeln erst mit `Speichern` dorthin kopiert; die bisherige Datei bleibt erhalten. Relative Pfade beziehen sich auf den Konfigurationsordner. `Abbrechen` Ã¤ndert den aktiven Pfad nicht und erzeugt keine neue Datei.

Die Datei ist eingerÃ¼cktes UTF-8-JSON und kann in einem Texteditor bearbeitet werden:

```json
{
  "schema_version": 1,
  "rules": [
    {
      "enabled": true,
      "source": "Organize",
      "target": "orgAnice"
    }
  ]
}
```

Speichern Sie externe Ã„nderungen vor dem nÃ¤chsten Diktat oder Erkennungsauftrag. Die Regeln werden beim Aufnahmestart beziehungsweise Auftragsstart eingelesen. Laufende AuftrÃ¤ge und die Wiederholung fehlgeschlagener Abschnitte behalten ihre ursprÃ¼nglichen Regeln. Im Dialog Ã¼bernimmt `Neu laden` den aktuellen Dateiinhalt; ungespeicherte Ã„nderungen mÃ¼ssen zuvor bestÃ¤tigt werden.

Beim Speichern erkennt der Dialog externe DateiÃ¤nderungen und verlangt vor dem Ãœberschreiben eine BestÃ¤tigung. Fehler nennen Datei und gegebenenfalls JSON-Zeile oder Regelnummer. Bei Lesefehlern werden die zuletzt gÃ¼ltigen Regeln mit einem Hinweis weiterverwendet. Ohne gÃ¼ltigen Bestand starten bei aktivierten Korrekturen keine neuen AuftrÃ¤ge; reparieren Sie die Datei oder deaktivieren Sie Korrekturen. Das automatische Speichern anderer Einstellungen Ã¼berschreibt die Regeldatei nicht. Ã„ltere Programmversionen kennen die neue Datei noch nicht.

## Audiodateien Ã¶ffnen und Ã¼bersetzen

WÃ¤hlen Sie im TraymenÃ¼ oder Verlauf `Audiodatei Ã¶ffnen â€¦`. UnterstÃ¼tzt werden WAV, MP3, M4A und FLAC. WÃ¤hlen Sie die Quellsprache oder automatische Spracherkennung, ein Erkennungsmodell und optional eine Zielsprache. Deutsch, Polnisch, Englisch, FranzÃ¶sisch und NiederlÃ¤ndisch stehen als Zielsprachen zur VerfÃ¼gung. Die Konvertierung und Erkennung erfolgen lokal; die Originaldatei bleibt unverÃ¤ndert.

Der Auftrag erscheint mit Fortschritt im Verlauf. Originaltranskript und Ergebnis lassen sich getrennt anzeigen, kopieren und als UTF-8-Text exportieren. Dateiimporte fÃ¼gen niemals automatisch Text in ein fremdes Programm ein und interpretieren ein gesprochenes `Enter` als normalen Text.

## Lange Aufnahmen

Mikrofonaufnahmen werden fortlaufend auf die Festplatte geschrieben. Die Erkennung verarbeitet Abschnitte von hÃ¶chstens 30 Sekunden mit einer Sekunde Ãœberlappung und bevorzugt ruhige Schnittstellen. Silero erkennt SprachaktivitÃ¤t. Doppelte Erkennung wird nur im zeitlich Ã¼berlappenden Bereich entfernt. Auch der letzte kurze Abschnitt wird verarbeitet.

Textbearbeitung und Ãœbersetzung werden an Satz- oder Absatzgrenzen aufgeteilt und gegen das Tokenbudget des tatsÃ¤chlich verwendeten Modells geprÃ¼ft. Abgeschnittene Antworten werden in kleineren Abschnitten erneut versucht. Wiederholungsschleifen werden markiert und einmal ohne vorherigen Kontext erneut erkannt; bei fortbestehendem Fehler steht der Abschnitt zur erneuten Verarbeitung bereit. Das Rohtranskript bleibt zur Diagnose erhalten.

## Modelle verwalten

Im Register `Modelle` wÃ¤hlen Sie Live- und finales Erkennungsmodell sowie das Textmodell getrennt aus. `large` bezeichnet weiterhin `large-v3`. Turbo-Varianten und alternative Qwen-Modelle sind zusÃ¤tzliche Vergleichskandidaten; ein neueres Modell garantiert nicht automatisch bessere Ergebnisse fÃ¼r Ihre Aufnahmen.

![Modellverwaltung](images/manual/models.png)

`Nach Aktualisierungen suchen` prÃ¼ft den von WinWhisperPlus verÃ¶ffentlichten Modellkatalog. Neue Modelle und neue Revisionen installierter Modelle werden getrennt angezeigt. `Herunterladen` lÃ¤dt die ausgewÃ¤hlte feste Revision und prÃ¼ft GrÃ¶ÃŸe und SHA-256. Ein Abbruch oder fehlerhafter Download ersetzt kein vorhandenes Modell. Bei noch ungeprÃ¼ften lokalen Dateien zeigt die Tabelle `PrÃ¼fung erforderlich`. Bereits heruntergeladene Modelle kÃ¶nnen offline verwendet werden.

Der mitgelieferte Qwen3-4B bleibt auswÃ¤hlbar. Laufzeitupdates werden mit Programmupdates ausgeliefert; inkompatible Modelle zeigen die erforderliche Programmversion an. Falls der neue Modellkatalog noch nicht als Release-Anhang verÃ¶ffentlicht wurde, kann die OnlineprÃ¼fung mit HTTP 404 scheitern. Der mitgelieferte Katalog bleibt nutzbar.

## Statistiken

Die Statistik zeigt erfolgreiche finale Transkriptionen nach Tag, Woche und Monat. Angezeigt werden Anzahl Starts, Gesamtdauer und Durchschnittsdauer.

![Aufnahme-Statistik](images/manual/statistics.png)

Die Werte helfen dabei, die Nutzung einzuschÃ¤tzen und zu erkennen, ob viele kurze oder wenige lange Diktate verarbeitet wurden.

## Speicherorte

WinWhisperPlus speichert Benutzerdaten unter:

```text
%APPDATA%\WinWhisperPlus
```

Wichtige Dateien:

- `settings.json`: Hotkeys, Sprachen, Mikrofon, Modelle und weitere Einstellungen.
- `correction-rules.json`: Korrekturregeln als editierbares UTF-8-JSON, sofern kein eigener Speicherort gewÃ¤hlt wurde.
- `statistics.json`: Statistikdaten erfolgreicher finaler Transkriptionen.
- `winwhisperplus.log`: Laufzeitmeldungen und Fehlerhinweise.

Modelle und PrÃ¼fnachweise liegen unter `%LOCALAPPDATA%\WinWhisperPlus\models`. TemporÃ¤re Sitzungsaudios liegen unter `%LOCALAPPDATA%\WinWhisperPlus\sessions`. Exportierte Audio- und Textdateien werden an Ihrem gewÃ¤hlten Speicherort abgelegt und nicht automatisch gelÃ¶scht.

Eine alte Konfiguration aus `%APPDATA%\MyWhisper\settings.json` kann beim Start Ã¼bernommen werden, wenn noch keine neue WinWhisperPlus-Konfiguration existiert.

## Fehlerbehebung

### Das Modell wird beim ersten Start geladen

Beim ersten Einsatz eines Whisper-Modells kann ein Download notwendig sein. Warten Sie, bis die Initialisierung abgeschlossen ist. Wenn der Download blockiert wird, prÃ¼fen Sie Internetzugang, Proxy, Virenschutz und Firewall.

Das Standard-Textmodell wird mit dem Installer ausgeliefert. Alternative Textmodelle kÃ¶nnen Ã¼ber die Modellverwaltung heruntergeladen werden und benÃ¶tigen mehrere GB Speicherplatz. Alle Modelle laufen ausschlieÃŸlich lokal; erkannter Text wird nicht an einen Cloud-Dienst Ã¼bertragen.

### Das Mikrofon fehlt in der Liste

Ã–ffnen Sie die Einstellungen und klicken Sie auf die Aktualisieren-SchaltflÃ¤che neben der Mikrofonliste. PrÃ¼fen Sie auÃŸerdem, ob Windows das Mikrofon erkennt und ob die Datenschutzfreigabe fÃ¼r Mikrofonzugriff aktiv ist.

### Der Hotkey funktioniert nicht

Ein Hotkey kann von einer anderen Anwendung belegt sein oder unter Windows nicht global registriert werden. WÃ¤hlen Sie in den Einstellungen eine andere Kombination und speichern Sie erneut.

### Der Text wird nicht eingefÃ¼gt

Klicken Sie vor dem Stoppen der Aufnahme in das Ziel-Eingabefeld. Wenn das Zielprogramm EinfÃ¼gen per Zwischenablage blockiert, deaktivieren Sie testweise `Text automatisch einfÃ¼gen` und kopieren Sie den Text aus dem Verlauf.

### Die Transkription schlÃ¤gt fehl

Ã–ffnen Sie `%APPDATA%\WinWhisperPlus\winwhisperplus.log` und prÃ¼fen Sie die letzten Fehlermeldungen. Typische Ursachen sind ein nicht verfÃ¼gbares Mikrofon, ein fehlgeschlagener Modell-Download oder zu wenig Speicher fÃ¼r ein groÃŸes Whisper-Modell.

### Die Erkennung ist zu langsam

WÃ¤hlen Sie ein kleineres finales Modell, zum Beispiel `base` oder `small`. FÃ¼r Live-Erkennung verwenden Sie `tiny` oder `base`. Eine Vulkan-fÃ¤hige GPU kann die Verarbeitung deutlich beschleunigen, ist aber fÃ¼r die Grundfunktion nicht zwingend erforderlich.

### Die Textoptimierung schlÃ¤gt fehl

Der Originaltext bleibt im Verlauf erhalten. Fehlgeschlagene Ãœbersetzungen werden ausdrÃ¼cklich gekennzeichnet. PrÃ¼fen Sie `%APPDATA%\WinWhisperPlus\winwhisperplus.log` und wiederholen Sie die Verarbeitung bei Bedarf. HÃ¤ufige Ursachen sind zu wenig freier RAM/Grafikspeicher, ein beschÃ¤digtes Release-Paket oder ein nicht verfÃ¼gbarer Vulkan-Treiber. Modelldateien werden vor der Verwendung per SHA-256 geprÃ¼ft.
