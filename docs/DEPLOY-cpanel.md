# راهنمای دیپلوی روی هاست پایتون cPanel (LiteSpeed)

این هاست از Python + PostgreSQL + Redis + Node.js + SSH + SSL رایگان پشتیبانی می‌کند،
پس کل پروژه قابل اجراست. Docker نداریم؛ به‌جایش از بخش **Setup Python App** سی‌پنل استفاده می‌کنیم.

## معماری روی این هاست

- **بک‌اند (Django)** → یک **Python App** روی زیر‌دامنه `api.YOUR-DOMAIN.com`
- **فرانت (Vue، فایل‌های ساخته‌شده)** → فایل‌های استاتیک روی دامنه‌ی اصلی `YOUR-DOMAIN.com`
- **دیتابیس** → PostgreSQL (از cPanel می‌سازیم)

> جدا کردن API روی زیر‌دامنه، تمیزترین راه روی cPanel است.

---

## گام ۱ — دیتابیس PostgreSQL

1. cPanel → **PostgreSQL Databases**: یک دیتابیس بساز (مثلاً `user_bi`) + یک کاربر با رمز قوی و به دیتابیس اضافه‌اش کن.
2. رشته‌ی اتصال را یادداشت کن:
   `postgres://DBUSER:DBPASS@localhost:5432/DBNAME`

## گام ۲ — زیر‌دامنه‌ی API

cPanel → **Subdomains**: زیر‌دامنه‌ی `api` بساز (`api.YOUR-DOMAIN.com`). یک پوشه‌ی docroot می‌سازد مثل `/home/USER/api.YOUR-DOMAIN.com`.

## گام ۳ — آپلود کد بک‌اند (SSH)

```bash
ssh USER@YOUR-DOMAIN.com
cd ~
git clone https://github.com/Fazelhf/bi-platform.git
```

## گام ۴ — ساخت Python App

cPanel → **Setup Python App** → **Create Application**:
- Python version: جدیدترین ۳.x موجود
- **Application root:** `bi-platform/backend`
- **Application URL:** `api.YOUR-DOMAIN.com`
- **Application startup file:** `passenger_wsgi.py`
- **Application Entry point:** `application`

Create را بزن. یک virtualenv می‌سازد و دستور فعال‌سازی‌اش را نشان می‌دهد (`source ...activate`).

## گام ۵ — نصب وابستگی‌ها (SSH)

دستور activate که cPanel داد را اجرا کن، بعد:

```bash
cd ~/bi-platform/backend
pip install -r requirements.txt
```

## گام ۶ — فایل `.env` بک‌اند

در `~/bi-platform/backend/.env`:

```env
DEBUG=False
SECRET_KEY=یک-رشته-تصادفی-بلند-بگذار
ALLOWED_HOSTS=api.YOUR-DOMAIN.com
DATABASE_URL=postgres://DBUSER:DBPASS@localhost:5432/DBNAME
CORS_ALLOWED_ORIGINS=https://YOUR-DOMAIN.com
CSRF_TRUSTED_ORIGINS=https://YOUR-DOMAIN.com,https://api.YOUR-DOMAIN.com
REDIS_URL=redis://localhost:6379/0
CELERY_TASK_ALWAYS_EAGER=True

# --- پیامک (ورود دو مرحله‌ای) ---
SMS_MODE=shared
SMS_USERNAME=نام-کاربری-پنل-ملی‌پیامک
SMS_PASSWORD=ApiKey-پنل
SMS_BODY_ID=کد-الگوی-تأییدشده
```

> `CELERY_TASK_ALWAYS_EAGER=True` یعنی فعلاً بدون worker جدا کار می‌کند (کافی است).

> **بدون بخش پیامک، ورود دو مرحله‌ای و «فراموشی رمز» خاموش می‌مانند** — کاربر
> در پروفایلش پیام «سرویس پیامک روی سرور پیکربندی نشده است» را می‌بیند. این
> عمدی است: بهتر است گزینه خاکستری بماند تا اینکه کسی 2FA را روشن کند و بعد
> هیچ کدی به دستش نرسد.
>
> دو نکته که تنظیم‌نکردنشان همین‌جا وقت می‌گیرد:
> - `SMS_PASSWORD` باید **ApiKey** باشد نه رمز عبور حساب (پنل به رمز عبور پاسخ `-110` می‌دهد).
> - **آی‌پی ثابت سرور** باید در «آی‌پی‌های مجاز» پنل ثبت شود، وگرنه هر فراخوانی
>   — حتی آن‌هایی که چیزی نمی‌فرستند — با `-111` رد می‌شود.
>
> بعد از تنظیم، صحتش را روی خود سرور بسنجید:
>
> ```bash
> python manage.py smstest              # فقط تنظیمات و اعتبار، بدون ارسال
> python manage.py smstest --to 0912...  # یک پیامک واقعی
> ```

## گام ۷ — دیتابیس + استاتیک + داده‌ی اولیه (SSH)

```bash
cd ~/bi-platform/backend
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py seed_sales
python manage.py seed_production
python manage.py seed_formulas
python manage.py loaddata fixtures/seed_data.json   # داده واقعی اردیبهشت ۱۴۰۵ + کاربران
```

سپس در **Setup Python App** دکمه‌ی **Restart** را بزن.
تست: `https://api.YOUR-DOMAIN.com/api/docs/` باید Swagger را نشان دهد.

## گام ۸ — build و آپلود فرانت

روی کامپیوتر خودت:

```bash
cd frontend
echo "VITE_API_URL=https://api.YOUR-DOMAIN.com/api" > .env.production
npm install
npm run build
```

محتویات پوشه‌ی `frontend/dist/` را در docroot دامنه‌ی اصلی آپلود کن
(`/home/USER/public_html/`) — از طریق File Manager یا FTP.

در همان پوشه یک فایل **`.htaccess`** بساز تا مسیرهای SPA کار کنند:

```apache
RewriteEngine On
RewriteBase /
RewriteRule ^index\.html$ - [L]
RewriteCond %{REQUEST_FILENAME} !-f
RewriteCond %{REQUEST_FILENAME} !-d
RewriteRule . /index.html [L]
```

## گام ۹ — SSL

cPanel → **SSL/TLS Status** → برای هر دو `YOUR-DOMAIN.com` و `api.YOUR-DOMAIN.com`
گزینه‌ی **Run AutoSSL** را بزن (Let's Encrypt رایگان).

---

## تمام شد ✅

- سایت: `https://YOUR-DOMAIN.com`
- ورود اولیه: کاربر `admin` یا `ceo` با رمز `demo12345`
- **حتماً بعد از اولین ورود، رمزها را از پنل ادمین عوض کن و `SECRET_KEY` را تغییر بده.**

## به‌روزرسانی بعدی

روی سرور فقط این کافی است:

```bash
bash ~/bi-platform/deploy.sh
```

> ⚠️ **اگر فرانت را تغییر داده‌اید، قبلش حتماً روی ویندوز `build-spa.bat` را اجرا کنید.**
> `deploy.sh` روی سرور فرانت را build **نمی‌کند** — نسخه‌ی بیلدشده در `backend/spa/`
> داخل مخزن است و با گیت منتقل می‌شود. اگر این مرحله را رد کنید، دیپلوی بدون خطا
> تمام می‌شود ولی سایت همان فرانت قدیمی را نشان می‌دهد.

ترتیب درست برای هر تغییر فرانت:

```bash
build-spa.bat        # روی ویندوز: build + کپی در backend/spa
git add -A && git commit -m "..." && git push
# سپس روی سرور:
bash ~/bi-platform/deploy.sh
```

## عیب‌یابی سریع

- **۵۰۰ در API:** فایل `~/bi-platform/backend/stderr.log` یا لاگ Python App را ببین؛ معمولاً `.env` یا اتصال دیتابیس است.
- **CSS پنل ادمین نمی‌آید:** `collectstatic` را دوباره اجرا کن و Restart بزن (WhiteNoise سرو می‌کند).
- **خطای CORS در مرورگر:** مطمئن شو `CORS_ALLOWED_ORIGINS` دقیقاً `https://YOUR-DOMAIN.com` باشد.
- **صفحه‌ی سفید بعد از رفرش در مسیر داخلی:** فایل `.htaccess` را چک کن.
