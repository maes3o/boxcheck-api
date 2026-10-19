# BoxCheck — backend

Preflight-перевірка PDF-макетів упаковки та поліграфії перед друком: виліт, безпечна зона, роздільна здатність, товщина ліній, шрифти, spot-кольори, overprint, геометрія сторінок, покриття фарбою.

*Preflight checker for packaging/prepress PDF files: bleed, safe zone, resolution, line weight, fonts, spot colours, overprint, page geometry, ink coverage.*

Це API-частина (FastAPI + PyMuPDF). Сервіс stateless, бази даних немає.

## Запуск / Run

Потрібні Python 3.10+ і системний Ghostscript (`gs`) для рендеру spot-сепарацій.

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # необов'язково: значення за потреби заповніть самі
uvicorn main:app --host 127.0.0.1 --port 8001
```

Тести: `pip install pytest && pytest tests/`

`.env` лише для необов'язкових сповіщень (Telegram, вебхук) і платіжних даних сторінки «Виправте за мене»; без нього перевірка PDF працює.

## Ліцензія / License

GNU Affero General Public License v3.0 (AGPL-3.0). Повний текст — у файлі [LICENSE](LICENSE). Якщо ви запускаєте змінену версію як мережевий сервіс, ви зобов'язані надати користувачам її вихідний код.
