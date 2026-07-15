# hotdeals Telegram Bot V2

גרסה מקצועית של הבוט לחיפוש מוצרי AliExpress והפקת קישורי Affiliate.

## מה השתפר

- חיפוש בעברית ובאנגלית.
- זיהוי כוונות חיפוש נפוצות וסינון קשוח של תוצאות לא קשורות.
- דירוג תוצאות לפי התאמה במקום להציג את התוצאות הראשונות מה-API.
- שליחת **3 מוצרים** כברירת מחדל.
- קטגוריות Inline מתוך `/start`.
- גילוי נאות על קישורי Affiliate.
- Cache קצר להפחתת קריאות API כפולות.
- Rate limit בסיסי נגד ספאם.
- טיפול נפרד בשגיאות API, תרגום ושליחת תמונות.
- Webhook אוטומטי ב-Render; Polling בהרצה מקומית.
- לא נשלח קישור מוצר רגיל אם יצירת קישור Affiliate נכשלה.

## משתני סביבה חובה

```text
TELEGRAM_BOT_TOKEN
ALIEXPRESS_APP_KEY
ALIEXPRESS_APP_SECRET
ALIEXPRESS_TRACKING_ID
```

אין להכניס סודות לקוד או ל-GitHub.

## הפעלה מקומית

```bash
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
pip install -r requirements.txt
set FORCE_POLLING=true
python bot.py
```

macOS/Linux:

```bash
source .venv/bin/activate
pip install -r requirements.txt
export FORCE_POLLING=true
python bot.py
```

יש להגדיר את משתני הסביבה לפני ההרצה.

## הפעלה בחינם ב-Render

הפרויקט מותאם ל-Render Free Web Service באמצעות Webhook. הקובץ `render.yaml` מאפשר יצירה כ-Blueprint.

1. העלה את כל הקבצים ל-GitHub.
2. ב-Render בחר **New > Blueprint**.
3. חבר את ה-Repository ובחר `render.yaml`.
4. הזן את ארבעת הסודות כאשר Render מבקש.
5. אשר יצירה והמתן ל-Deploy.
6. לאחר שהסטטוס Live, שלח `/start` לבוט.

Render מגדיר אוטומטית `RENDER_EXTERNAL_URL` ו-`PORT`, והבוט רושם Webhook של Telegram בעצמו.

### מגבלת החינם

Render עשויה להרדים Web Service חינמי לאחר 15 דקות ללא תעבורה. הודעת Telegram חדשה מעירה את השירות, ולכן ההודעה הראשונה לאחר חוסר פעילות עלולה להתעכב בערך דקה. Telegram בדרך כלל מבצעת ניסיון חוזר למסירת webhook.

## בדיקת תקינות

```bash
python -m compileall bot.py app
python -m unittest discover -s tests
```

## הערה חשובה על AliExpress

אם לחשבון Affiliate יש Penalty או חסימה ליצירת Promotion Links, הבוט עשוי להיות Online אך לא להחזיר מוצרים. במצב כזה יש לבדוק את AliExpress Penalty Center ואת הרשאות ה-API; זו אינה תקלה ב-Telegram או ב-Render.
