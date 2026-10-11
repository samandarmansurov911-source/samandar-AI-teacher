# Türkçe Okuyorum 1 — interaktiv HTML

`index.html` — kitobning 26 ta matni/dialogi (Hakan Yılmaz, Dilmer Yayınları) interaktiv shaklda:

- istalgan so'z ustiga bosing → o'zbekcha tarjimasi va asos shakli (masalan, *gidiyorsun → boryapsan; gitmek — bormoq*);
- har bir matn tepasidagi **▶ O'qib berish** tugmasi matnni turkcha ovozda o'qiydi (brauzerning Speech Synthesis API, `tr-TR` ovozi kerak);
- har bir matn tagida shu matnda ishlatilgan so'zlar lug'ati va javoblari bilan mashqlar.

Faylni brauzerda (Chrome, Safari) to'g'ridan-to'g'ri ochish kifoya — internet kerak emas.

## Qayta yig'ish

Matnlar, lug'at va javoblar `src/` papkasida:

- `texts.txt` — matnlar (`S|Gapiruvchi|matn`, `P|paragraf`, `Q|savol`, `D|to'g'ri/noto'g'ri`)
- `answers.txt` — javoblar kaliti
- `dict*.txt`, `names.txt` — lug'at (`@asos = tarjima`, keyin uning shakllari)
- `template.html` — sahifa shabloni

```
python3 src/build.py   # index.html ni qayta yaratadi, lug'atda yo'q so'zlarni ko'rsatadi
```
