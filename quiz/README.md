# Lug'at musobaqasi (Kahoot uslubida)

O'qituvchi lug'at joylaydi, o'quvchilar telefondan ism yozib kiradi. Ekranda **o'zbekcha** so'z chiqadi, o'quvchilar **inglizchasini** yozadi. Tez va to'g'ri javob ko'proq ball beradi. Har savoldan keyin hamma o'z o'rnini va to'liq reytingni ko'radi.

- `/` — o'quvchilar sahifasi (ism yozib kiradi)
- `/host` — o'qituvchi paneli (parol bilan)

## Imkoniyatlar

- **Lug'at joylash:** har qatorda `inglizcha - o'zbekcha` (`-`, `=`, `:` yoki Excel'dan nusxa). `.txt`/`.csv` fayldan ham olish mumkin. Saqlashdan oldin jadval ko'rinishida tekshiriladi.
- **Bir nechta to'g'ri javob:** `big / large - katta`. `to`, `a`, `the` va katta-kichik harf hisobga olinmaydi, `(to) run` ham ishlaydi.
- **Lug'atni istalgan payt almashtirish:** keyingi savol yangi lug'atdan chiqadi, ballar saqlanadi.
- **Ball:** to'g'ri javob 500–1000 ball (qanchalik tez bo'lsa shuncha ko'p) + ketma-ket to'g'ri javob uchun bonus 🔥.
- **Sozlamalar:** savol vaqti (5–60 soniya), avtomatik keyingi savol, bitta harf xatosini qabul qilish.
- Hamma javob bersa, natija darhol chiqadi. O'qituvchi eng tezlarni va xato javoblarni ko'radi.
- O'quvchi sahifani yangilasa yoki internet uzilsa, ismi va bali saqlanib qoladi. Bir xil ism ikki marta olinmaydi. Noo'rin ismni o'qituvchi bitta bosish bilan chiqaradi.

## Render'da ishga tushirish

Bu alohida **Web Service** sifatida ishlaydi (Telegram botga tegmaydi).

1. Render → **New → Web Service** → shu repo.
2. **Root Directory:** `quiz`
3. **Build Command:** `pip install -r requirements.txt`
4. **Start Command:** `python server.py`
5. Environment: `HOST_PASSWORD` = o'zingiz o'ylagan parol (berilmasa standart `teacher123`).

Tayyor manzil (masalan `https://lugat.onrender.com`) ni o'quvchilarga bering, o'zingiz `.../host` ga kirasiz.

| O'zgaruvchi | Tavsif |
|---|---|
| `HOST_PASSWORD` | o'qituvchi paneli paroli |
| `DATA_DIR` | lug'atlar saqlanadigan papka (standart `quiz/data`) |
| `PORT` | Render o'zi beradi |

### Muhim

- Render bepul tarifida disk har deploy/qayta ishga tushishda tozalanadi. Shuning uchun **Lug'atlar → ⬇ Zaxira yuklab olish** tugmasi bilan lug'atlarni faylga saqlab qo'ying, kerak bo'lsa **⬆ Zaxiradan tiklash** bilan qaytaring. Pullik tarifda Disk ulab, `DATA_DIR` ni o'sha diskka yo'naltirsangiz, zaxira shart emas.
- Bepul tarifda servis 15 daqiqa ishlatilmasa uxlaydi, birinchi kirishda ~1 daqiqa uyg'onadi. Darsdan oldin `/host` ni ochib qo'ying.
- O'yin holati (o'yinchilar va ballar) xotirada turadi, server qayta ishga tushsa nolga tushadi.

## Kompyuterda sinash

```bash
cd quiz
pip install -r requirements.txt
python server.py        # http://localhost:8080 va http://localhost:8080/host
```
