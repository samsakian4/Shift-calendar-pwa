# تقویم شیفت و PM

اپ تحت وب فارسی (PWA) برای تقویم شمسی شیفت ۱۲ ساعته‌ی پرسنل و برنامه‌ی PM، کنترل و نگهداری دستگاه‌ها.
فرانت‌اند: یک فایل HTML بدون build. بک‌اند: Supabase (ورود + دیتابیس + همگام‌سازی زنده). میزبانی: Netlify. نصب روی گوشی: PWA یا TWA.

```
web/                 ← فقط همین پوشه روی Netlify منتشر می‌شود
  index.html         اپ
  config.js          آدرس و کلید عمومی Supabase (باید پر شود)
  sw.js              آفلاین شدن پوسته‌ی برنامه
  manifest.webmanifest, icons/
  vendor/            supabase-js و فونت‌ها (بدون CDN؛ برای ایران مطمئن‌تر)
  .well-known/assetlinks.json   برای TWA
supabase/schema.sql  جدول‌ها، RLS و تابع ادغام
twa-manifest.json    قالب Bubblewrap
netlify.toml
```

## راه‌اندازی (۵ مرحله)

**۱. Supabase** — پروژه‌ی `shift-calendar` ساخته و `schema.sql` رویش اجرا شده است (برای پروژه‌ی دیگر، فایل را در SQL Editor اجرا کنید). این کارها باقی مانده:
- Authentication › Users › Add user: برای هر نفر ایمیل و رمز بسازید.
- Authentication › Sign In / Providers › **Allow new users to sign up** را خاموش کنید (وگرنه هر کسی می‌تواند حساب بسازد و داده‌ها را ببیند).
- ویرایشگرها (کسانی که حق تغییر دارند، مثلاً سرپرست‌ها):
  ```sql
  insert into public.shift_editors (user_id)
  select id from auth.users where email in ('you@example.com')
  on conflict do nothing;
  ```
  بقیه‌ی کاربران فقط می‌بینند.

**۲. config.js** — آدرس و کلید publishable همین پروژه از قبل داخلش است. برای پروژه‌ی دیگر از Project Settings › API عوض کنید. کلید `service_role` را هرگز نگذارید.

**۳. GitHub** — پوشه را در یک repo بگذارید و push کنید.

**۴. Netlify** — Add new site › Import from Git › همین repo. مقدار publish از `netlify.toml` (`web`) خوانده می‌شود و build command لازم نیست.

**۵. نصب** — سایت را در Chrome گوشی باز کنید › Install app / Add to Home screen.

## TWA (اپ اندروید از روی PWA)

1. سایت باید روی HTTPS زنده باشد و PWA بودنش در Chrome (Install) تأیید شود.
2. ساخت APK با یکی از دو راه:
   - **PWABuilder** (pwabuilder.com): آدرس سایت › Package for Android › نام بسته را عوض کنید. خروجی شامل APK/AAB، کلید امضا و `assetlinks.json` است.
   - **Bubblewrap**: `npm i -g @bubblewrap/cli` سپس `bubblewrap init --manifest=https://SITE/manifest.webmanifest` و `bubblewrap build` (به JDK 17 و Android SDK نیاز دارد؛ Android Studio لازم نیست).
3. مقدار `sha256_cert_fingerprints` و `package_name` را در `web/.well-known/assetlinks.json` بگذارید و دوباره deploy کنید. بدون این مرحله، اپ با نوار آدرس مرورگر باز می‌شود.
4. فایل keystore را جای امن نگه دارید و در Git نگذارید. با گم شدنش نمی‌توانید به‌روزرسانی بدهید.
5. اگر فروشگاه (بازار/مایکت) APK را با کلید خودش دوباره امضا کند، fingerprint آن کلید را هم به `assetlinks.json` اضافه کنید.

## نکته‌ها
- **به‌روزرسانی کش:** بعد از تغییر فایل‌ها، `VERSION` را در `sw.js` زیاد کنید.
- **آفلاین:** برنامه و آخرین داده‌ی دیده‌شده باز می‌شود، ولی تغییر جدید بدون اینترنت ذخیره نمی‌شود (پیام «خطا در ذخیره» می‌آید).
- **اولین استفاده:** در ماه جاری، روزهای قبل از امروز «عقب‌افتاده» حساب می‌شوند. اگر وسط ماه شروع می‌کنید، می‌توانید آن‌ها را یک‌جا تیک بزنید یا ماه بعد شروع کنید.
