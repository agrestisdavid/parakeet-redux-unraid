# Ergebnis: Redux CPU versus bestehendes GPU-Whisper

**Messdatum: 26. Oktober 2026. Empfehlung für dieses Deployment: Whisper behalten.**

Nachtrag: Installiert ist inzwischen **0.1.1** mit vollständig eingefrorenen
Debian-Abhängigkeiten ([Details](../DEPENDENCIES.md)), ohne Änderung am ASR-Modell
oder an der Dekodierung. Die nachfolgenden Vergleichstabellen stammen weiterhin
aus dem dokumentierten 0.1.0-Lauf; 0.1.1 wurde zusätzlich mit 41 Tests und 17
Live-Protokollprüfungen verifiziert. Der aktuelle Testbestand umfasst 43 Tests.
Der **beidseitige Prozess-Kaltstartvergleich ist inzwischen ergänzt**: Für Whisper
hat der Betreiber anschließend ausdrücklich ein kurzes Wartungsfenster freigegeben.
Redux funktioniert als ressourcensparende CPU-Alternative, ist in dieser
Konfiguration aber weder schneller noch insgesamt genauer.

## Getestete Konfiguration

- Redux: dieses Image `0.1.0`, GHCR-Digest
  `sha256:1a2df7fa62e5a1250735100e81a6e83ea317c7f9ce26d5a8ad47f9d06c88a200`;
  Moondream Redux packed GGUF, SHA-256 siehe NOTICE; parakeet.cpp `43dce03`.
  CPU-only, zwei Threads auf zwei physischen Kernen, 2-CPU-Quota, 3 GiB RAM-Limit.
  Vierkern-x86-Host mit AVX2, ohne AVX-512; nebenläufige Anwendungen blieben aktiv.
- Whisper: bestehendes Faster-Whisper **large-v3-turbo**, CUDA **int8_float16**,
  Beam **3**, Sprache **de**; vorhandene NVIDIA-GPU und vorhandene HTTP-/Wyoming-
  Dienste im Haupt-Warmvergleich unverändert. Keine Whisper-Optimierung.
  Erst im gesondert freigegebenen Kaltstart-Nachtrag wurde ausschließlich der
  Whisper-Container neu gestartet, ohne Modell-/Image-/Konfigurationsänderung.
- 14 saubere Qwen3-TTS-Aufnahmen (13 Sohee, eine Serena), acht deterministische
  Rauschvarianten und eine Stillekontrolle. Drei Wiederholungen: **138 HTTP-Aufrufe**
  plus **36 zeitgetreu übertragene Wyoming-Aufnahmen**. Warmups separat, nicht mitgezählt.
- Lange Aufnahmen: **46,84 und 54,64 Sekunden**. Detaillierte Methode,
  Referenzkorrekturen und Einschränkungen: [README](README.md).

## Geschwindigkeit (warmer Betrieb)

| Messung | Redux CPU | Whisper GPU |
|---|---:|---:|
| Kurze HA-Befehle, HTTP, Median (18 Messungen je System) | 0,498 s | **0,417 s** |
| Nach Audioende bis Endtranskript, zeitgetreues Wyoming, Median (18 je System) | 0,477 s | **0,321 s** |
| Bereich derselben Wyoming-Endlatenz | 0,365–0,698 s | **0,274–0,371 s** |
| Lange Aufnahmen, HTTP, Median (6 je System) | 6,285 s | **1,484 s** |
| Bereich der langen HTTP-Aufnahmen | 5,462–9,568 s | **1,233–1,692 s** |
| Alle sauberen Dateien, HTTP, Median (42 je System) | 0,634 s | **0,452 s** |
| Saubere Dateien: Audiosekunden pro Verarbeitungssekunde, aggregiert | 7,66× | **19,84×** |

Bei langen Dateien war Whisper im Median rund **4,2-mal schneller**.
Bei kurzen Befehlen beträgt der zusätzliche Median nach Audioende nur rund
**156 ms**, relativ aber **49 %**. Das vorab gesetzte Kriterium für „ähnlich schnell“
(maximal 20 % **und** maximal 200 ms höhere Endlatenz) ist damit **nicht erfüllt**.
Das ist eine Bewertung dieses Zwei-Thread-Profils unter Bestandslast, kein Beweis,
dass Redux mit mehr CPU-Ressourcen grundsätzlich nicht gleichziehen könnte.

P95 der gemischten sauberen HTTP-Dateien: Redux 6,848 s, Whisper 1,649 s (42
Messungen je System). Wegen unterschiedlicher Dateilängen ist das kein sinnvoller
P95-Wert für einzelne kurze Sprachbefehle; dort wird bei nur 18 Messungen bewusst
kein belastbarer P95 behauptet. Min/Max, Einzelwerte und Warmups sind veröffentlicht.

### Ergänzter Prozess-Kaltstartvergleich

Je System **drei gemessene Container-/Modellprozess-Neustarts**, jeweils derselbe
kurze Befehl `cmd01` (identischer WAV-SHA-256). Danach je drei warme Folgeaufrufe.
Whisper wurde dafür nach **ausdrücklicher Wartungsfreigabe des Betreibers** neu
gestartet; seine Bridge blieb durchgehend aktiv.

| Messung, Median | Redux 0.1.1 CPU | Bestehendes Whisper GPU |
|---|---:|---:|
| Neustart bis Bereitschaft* | 2,002 s | 9,307 s |
| **Neustart bis erstes vollständiges Transkript** | **2,347 s** | **10,103 s** |
| Erster HTTP-Aufruf nach Bereitschaft | **0,355 s** | 0,796 s |
| Warme Folgeaufrufe nur für `cmd01` (9 je System) | **0,338 s** | 0,445 s |

*Redux: Modell geladen und HTTP bereit; Whisper: Wyoming-Protokoll antwortet
auf `describe`. Protokollbereitschaft beweist bei Whisper nicht, dass alle
Modellgewichte/Inferenz-Caches geladen sind. Deshalb ist vor allem die inklusive
Zeit **bis zum ersten tatsächlichen Transkript** relevant; sie enthält auch
Container-Initialisierung und gegebenenfalls verzögertes Modellladen.
Bereich dieser Gesamtzeit: Redux **2,192–2,462 s**, Whisper **9,481–12,465 s**.
Alle ersten und warmen Transkripte entsprachen dem Testbefehl.

**Redux gewinnt diesen Kaltstartvergleich.** Das ist ein Vergleich der konkreten
Dienste, kein isolierter Modell-Ladebenchmark. Er setzt die Aussage über den
breiteren Warmvergleich nicht außer Kraft: Nur dieser eine kurze Befehl war auch
in den warmen Folgeaufrufen des Nachtrags mit Redux schneller. Unterschiedliche
Clientpositionen, Satzlängen und Hintergrundlast dürfen nicht vermischt werden.

Rohdaten: [Redux](results/cold-start-redux-0.1.1.json),
[Whisper](results/cold-start-whisper-final.json). Skripte:
[cold_start.py](cold_start.py), [whisper_cold_start.py](whisper_cold_start.py).
Beide Nachtragsserien liefen vom Docker-Host, aber zeitlich getrennt, nicht vom
Windows-LAN-Client des Hauptvergleichs. Persistenter Modellcache und OS-Seitencache
blieben erhalten; kein globales Cache-Leeren und kein kompletter Server-Kaltboot.

Transparenz zum Ablauf: Eine erste Whisper-Serie mit drei Neustarts wurde wegen
eines Fehlalarms im abschließenden Schutzvergleich wiederholt. Docker lieferte
unveränderte Mounts in anderer Reihenfolge; kein anderer Dienst war verändert
oder neu gestartet worden. Der Vergleich wurde korrigiert, mit zwei Regressionstests
abgesichert und Messwerte werden jetzt nach jedem Durchlauf gespeichert. **Insgesamt
sechs autorisierte Whisper-Neustarts**, davon drei in der oben ausgewerteten finalen
Serie. Die fehlgeschlagene Vorserien-Abnahme wird nicht als bestandener Messlauf
gezählt. Nach der finalen Serie wurden laufender Whisper, korrekte Transkription,
unveränderte Konfigurationen/Ports und unveränderte Startzeiten aller anderen
geschützten Dienste erneut bestätigt.

## Genauigkeit in diesem kleinen synthetischen Korpus

Wortfehlerrate (WER) nach dokumentierter Normalisierung, niedriger ist besser:

| Bedingung | Redux | Whisper |
|---|---:|---:|
| 14 saubere Aufnahmen | 0,80 % | **0,00 %** |
| Vier Varianten mit synthetischem Rauschen, 10 dB | 0,00 % | 0,00 % |
| Vier Varianten mit starkem synthetischem Rauschen, 0 dB | 11,76 % | **7,84 %** |
| Alle 22 Sprachaufnahmen, ohne Stille | 1,88 % | **0,84 %** |

Zeichenfehlerrate (CER) sauber: Redux **0,14 %**, Whisper **0,00 %**;
über alle Sprachaufnahmen: **0,85 %** versus **0,33 %**.
Die wiederholten Ausgaben waren in den jeweiligen Testfällen gleich; dreimalige
Messung vergrößert nicht die Zahl unabhängiger Sätze.

- Alle sechs sauberen HA-Befehle wurden von **beiden** korrekt erkannt: 18/18
  normalisierte exakte Treffer und erforderliche Slots je System, auch über Wyoming.
- Beide Zahlenaufnahmen: bei beiden Systemen 6/6 korrekte Wiederholungen/Slots.
- Beide Namensaufnahmen: Whisper 6/6, Redux 3/6. Redux schrieb aus
  **„Jürgen Schneider“ → „Jügenschneider“**.
- Redux schrieb außerdem **„Bescheid“ → „bescheit“**. Dieser Rechtschreibfehler
  zählt in WER, obwohl die Bedeutung weitgehend verständlich bleibt.
- Beide sauberen Diktate waren bei beiden Systemen vollständig korrekt.
- Unter starkem Rauschen hatte Redux unter anderem „Disseldorf anzuwenden“ statt
  „Düsseldorf anzurufen“; Whisper machte ebenfalls Fehler, aber insgesamt weniger.
- Drei Sekunden absolute Stille: Redux lieferte **3/3 leere Transkripte**;
  Whisper erzeugte **3/3 „Untertitelung des ZDF, 2020“**. Das ist ein realer
  Negativtestbefund für den vorhandenen Whisper-Dienst, aber kein allgemeiner
  Halluzinationsvergleich. Hier wurde bewusst direkt ohne HA-Spracherkennung/VAD
  eingespeist; in Assist sollte VAD solche Aufnahmen normalerweise verhindern.

Die Referenzen wurden technisch und mit einem separaten lokalen Whisper-small-
Decoder geprüft, **nicht von einem Menschen abgehört**. Zwei fehlerhafte TTS-
Referenzen aus dem Pilot wurden vor dem finalen Vergleich neu erzeugt und erneut
geprüft. Die automatisierte Prüfung mit einem Whisper-Familienmodell kann die
Korpusauswahl zugunsten dieser Familie verzerren. Deshalb gilt die Aussage nur
für diese veröffentlichten Aufnahmen, nicht allgemein für Deutsch, Akzente,
Dialekte, reale Mikrofone oder Namen.

## Ressourcen und Betriebsprüfung

- Redux nutzt **keinen GPU-Speicher**. RAM während der überwachten finalen Läufe:
  etwa **922–999 MiB**, cgroup-Speichermaximum bis dahin **1,066 GiB**.
- Bestehendes Whisper: etwa **1,32–1,38 GiB RAM**; zugeordneter GPU-Prozess
  etwa **1206 MiB VRAM**. Bei einem späteren vollständigen Stop ließe sich dieser
  GPU-Speicher voraussichtlich freigeben; dieser Stop wurde **nicht** durchgeführt.
- 77 Ressourcenstichproben, etwa alle vier Sekunden. Redux erreichte bis ca.
  **178 % Docker-CPU** (100 % entspricht einem logischen CPU-Kern). CPU-Mediane
  über die Gesamtlaufzeit enthalten erhebliche Leerlaufzeiten und werden nicht
  als Inferenzkosten ausgegeben. Stichproben können kurze Lastspitzen verpassen.
- Konkurrierende Anwendungen liefen weiter und belasteten CPU/GPU. Keine
  kontrollierte Labor-Leerlaufumgebung und keine Leistungs-/Energiegarantie.
- Anonymer GHCR-Pull erfolgreich; Healthcheck gesund; eigener Neustart und
  Cache-Wiederverwendung geprüft. CPU-only-Build, nicht privilegiert, Benutzer
  99:100, read-only Root-Dateisystem und begrenzter temporärer Speicher.
- **43 Python-Tests** (inklusive Benchmark-/Dateiintegrität und Mountvergleich), **5 native Tests** und **17 Live-Prüfungen** erfolgreich.
  Live-Prüfung umfasst Discovery, echte Audio-Chunks, 8/16/24/48 kHz,
  Mono/Stereo, zwei Aufnahmen pro Verbindung, fehlerhafte Eingaben,
  Wiederverbindung, Verbindungsabbruch während nativer Inferenz mit Erholung
  und Überlastablehnung. Keine Teilergebnisse vor `audio-stop`.
- HA-Konfiguration sowie vorhandene Container-Identitäten, Images, Modelle,
  Konfigurationen und Ports blieben unverändert. Einzige spätere Ausnahme am
  Betriebszustand: die ausdrücklich genehmigten Whisper-Neustarts für die
  Kaltstartmessung. TTS, Frigate, HA, Bridge und Redux wurden dabei nicht neu
  gestartet. Keine Community-Applications-Einreichung und kein Whisper-Portwechsel.

## Entscheidung und spätere Wechseloption

**Whisper bleibt die Empfehlung**, wenn Geschwindigkeit und Erkennungsqualität
Priorität haben. **Redux ist eine brauchbare CPU-Ausweichlösung**, wenn etwa
1,2 GiB GPU-Speicher wichtiger sind als die gemessenen Nachteile.

Ein späterer Wechsel wäre eine **separate Entscheidung**: zunächst HTTP-Client-
Kompatibilität und echte HA-/Mikrofon-End-to-End-Tests, dann bisherige Portbelegung
sichern, alte Dienste kontrolliert stoppen und Redux auf die freigegebenen Ports
legen. Rückweg: Redux von diesen Ports nehmen und die unveränderten bisherigen
Container starten. Keine Parallelbelegung derselben Ports, keine automatische
Migration. Das Protokoll ist geprüft, aber eine tatsächliche HA-Assist-Sitzung
wurde noch nicht umgestellt oder getestet.
