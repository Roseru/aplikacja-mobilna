# Analiza zdjęcia0.8.16 — zrzuty testowe

Źródło aplikacji: `a4447e436724cdc9eae926c681318e590c6ce8e8`. Syntetyczny provider mock i Banan120g,
bez rzeczywistego API, Google lub prywatnego dziennika użytkownika.
Zrzuty z trzech końcowych testów PhotoUploadScreenTest:3/3PASS po pełnym223native.
Wąski viewport320dp i tekst150% to przypadek dostępności, nie rozmiar całego urządzenia.

- [Zgoda — jasny motyw](consent-light.png)
- [Niepewna próba — ciemny motyw, duży tekst](queue-dark-large-text.png)
- [Wynik — ciemny motyw, duży tekst](result-dark-large-text.png)

Pierwsze zrzuty zasłaniało okno ANR System UI emulatora; nie są publikowane.
Po jednorazowym wyborze obserwowanego Wait odczyt hierarchii potwierdził brak
okna, powtórzono3 testy na identycznych APK i ręcznie obejrzano wszystkie PNG.
Nie retuszowano obrazów, nie czyszczono danych ani nie restartowano komputera.
