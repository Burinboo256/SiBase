# Phase 3 — Application Authentication & RLS

Phase 3 ต่อจาก stack `sibase-control` โดยแยกบัญชีผู้ใช้แอปออกจากบัญชีผู้ดูแล SiBase ทุกโปรเจกต์มี Auth schema, sessions และ JWT signing secret ของตนเอง ไม่ใช้ app token เข้าถึง Control API

## เริ่มใช้งาน local

ต้องมี Docker Compose และ Python 3.11+ ตามคู่มือ Phase 2:

```sh
make phase3-dev          # ใช้ volumes เดิม; migrate control metadata และเปิด Mailpit
make phase3-prepare      # สร้าง/เปิด Auth Sandbox และเปิดใช้ Auth/RLS แบบ Phase 3
make phase3-check        # lint, types, backend/frontend tests และ frontend build
make phase2-integration # เตรียม/ตรวจ Operations และ Inventory สำหรับ cross-project tests
make phase3-integration # เพิ่มผู้ใช้/ข้อมูลทดสอบ ยืนยันอีเมล และหมุน signing key ของ Sandbox
make phase3-e2e         # Chromium: desktop/mobile signup, recovery, RLS และ Dashboard mutations
make phase3-status
```

`integration` ต้องใช้ local Mailpit และควรรันหลัง `make phase2-integration` ใน fresh checkout: ชุดทดสอบใช้ Inventory เป็นโปรเจกต์ที่สองเพื่อตรวจ isolation ไม่ควรรันกับโปรเจกต์งานจริง การรันทิ้งข้อมูลสังเคราะห์ไว้สำหรับตรวจสอบ; ไม่ลบฐานข้อมูลหรือ volumes ใช้ `make phase2-stop` หยุดทั้ง stack

- Dashboard: `http://127.0.0.1:58400`; บัญชี `owner@sibase.local`, รหัสผ่านใน `.local/sibase-control/initial-owner.json`
- Mailpit: `http://127.0.0.1:58425`; inbox มี verification/recovery links จึงต้องถือเป็นข้อมูลลับ ไม่เปิดพอร์ตออกเครือข่าย
- Project endpoint: `http://127.0.0.1:58420/p/<project-ref>`

Owner/Admin เปิด Projects → Auth Sandbox → Application authentication มี Users, Sessions, Auth Settings และ Permission preview ส่วน Developer/Viewer เข้า metadata ผู้ใช้ไม่ได้ Users/Sessions เป็น read-only snapshot ไม่เกิน 100 รายการต่อประเภท เก็บโดย worker และอัปเดตประมาณทุก 10 วินาที Permission preview แสดงตาราง/policies/roles จริง ไม่ใช่เครื่องมือจำลอง SQL ภายใต้ทุกสิทธิ์

## เปิดใช้กับโปรเจกต์อื่น

Auth Settings → กำหนด callback URL กับ access-token lifetime → Enable/Apply แล้วรอสถานะ `ready` การเปลี่ยนนี้ต้องยืนยันก่อน เพราะจะ require email confirmation และ ENABLE/FORCE RLS กับ **ทุก public table** รวมตารางเดิม ไม่มี policy จะถูก default-deny; policy เดิมที่กว้างยังคงกว้างอยู่ ไม่แก้หรือลบข้อมูลเดิมโดยอัตโนมัติ

Operations/Inventory และโปรเจกต์ใหม่ที่ยังไม่ได้ opt in ยังคงพฤติกรรม Phase 2 เดิม ไม่ได้ถูก harden ทั้งหมดโดยปริยาย ช่วง provisioning gateway จะปฏิเสธ requests จนบริการและ migration พร้อม ไม่มีปุ่มย้อนกลับไปปิด hardening

## สัญญา Auth สำหรับนักพัฒนาแอป

ใช้ project endpoint และ **anon API key** กับ `@supabase/supabase-js` รุ่นที่ล็อกไว้ใน `poc/phase0/package.json` อย่านำ server key ไปไว้ใน browser ตัวอย่าง API ที่ทดสอบ:

```js
const app = createClient(projectEndpoint, anonKey);
await app.auth.signUp({ email, password }); // ไม่มี session ก่อนยืนยันอีเมล
await app.auth.signInWithPassword({ email, password });
await app.auth.resetPasswordForEmail(email, { redirectTo: appCallback });
// หลังแอปรับ recovery session จาก callback แล้ว:
await app.auth.updateUser({ password: newPassword });
await app.auth.refreshSession();
await app.auth.signOut();
```

แอปจริงต้องสร้างหน้า callback/password recovery ของตนเอง สำหรับ local มี `/app-test` พร้อมหน้า recovery เพื่อทดสอบครบ flow เมื่อบันทึก project ref/anon key แล้ว `/auth/callback` จะล้าง URL secrets และส่ง session เข้าแอปทดสอบใน memory; หากไม่มี public configuration จะแสดง safe landing **ไม่สร้าง session ผู้ดูแล** ดู [วิธีทดสอบ browser](browser-acceptance.md) ใช้ HTTPS callback บน staging; HTTP อนุญาตเฉพาะ localhost/127.0.0.1 การอนุญาต browser origins ที่ gateway ยังยึด local Dashboard origin ตาม Phase 2; ต้องออกแบบ allowlist สำหรับ app origins ก่อน staging

- Password ขั้นต่ำ 12 ตัวอักษร; confirmation/recovery token อายุ 600 วินาที และใช้ซ้ำไม่ได้
- Access JWT: HS256, issuer `<gateway>/p/<ref>/auth/v1`, audience `authenticated`, role `authenticated`; lifetime 300–3600 วินาที (default 900; Sandbox 300)
- Gateway ตรวจ issuer/audience/expiry/project binding; Realtime ตรวจ JWT ใน join/token-update frames และ watchdog ตรวจซ้ำ รวมการ revoke API key/project suspend
- Refresh rotation เปิดใช้และ grace interval 0 แต่ upstream ยอมรับ immediate-parent token เป็น retry ได้ การใช้ grandparent/stale token ซ้ำเพิกถอน session family ตามชุดทดสอบ
- Logout เพิกถอน refresh tokens; access JWT ที่ออกแล้วใช้ได้จนหมดอายุ ไม่อ้างว่า revoke access ทันที
- Rotate project signing key เป็น hard cut: JWT เก่าใช้ไม่ได้และบริการ restart ชั่วคราว; opaque API keys และ refresh sessions เดิมยังอยู่ ผู้ใช้ขอ access JWT ใหม่ด้วย refresh/sign-in ได้ ไม่มี grace overlap

## RLS และขอบเขตความปลอดภัย

`migrations/projects/0002_app_rls.sql` ติดตั้ง template `public.phase3_tasks` พร้อม policy `owner_id = auth.uid()` ทั้ง `USING` และ `WITH CHECK` ผู้ใช้สร้าง/อ่าน/แก้/ลบแถวของตนเองได้ แต่เปลี่ยนเจ้าของแถวไปผู้อื่นไม่ได้ anon ไม่มีสิทธิ์ ส่วน `service_role` เป็น trusted bypass สำหรับ server เท่านั้น

Event trigger บังคับ ENABLE/FORCE RLS เมื่อสร้างหรือ ALTER public ordinary/partitioned tables รวมการพยายามปิด RLS ด้วย table owner ตัว REST login/anon/authenticated ไม่ใช่ superuser หรือ BYPASSRLS แต่ project owner ยังแก้ policies ได้ จึงเป็น trusted schema administrator ไม่ใช่ขอบเขตป้องกัน admin ที่ประสงค์ร้าย

ยังไม่ครอบคลุมความปลอดภัยของ views, SECURITY DEFINER RPC, schemas อื่น หรือ Realtime row-event policy matrix ทั้งหมด งานเหล่านี้อยู่ Phase 4/6 Storage/Realtime internal roles เป็น privileged upstream services ต้องไม่แจก credentials ให้แอป

## SMTP configuration

Local default ใช้ Mailpit (internal SMTP 1025, ไม่ auth) มี persistent inbox จำกัด 500 messages สำหรับ staging operator สร้าง `.local/sibase-control/smtp.json` แบบ private ก่อน `make phase3-dev`:

```json
{
    "smtp_host": "smtp.example.com",
    "smtp_port": 587,
    "smtp_user": "replace-me",
    "smtp_password": "replace-me",
    "smtp_sender": "noreply@example.com"
}
```

จำกัดสิทธิ์ไฟล์ `chmod 600 .local/sibase-control/smtp.json` ค่าถูกส่งเฉพาะ worker/project Auth ไม่ผ่าน Dashboard/Control API ต้องยืนยัน STARTTLS, sender/DNS, callback/origin allowlists, deliverability และ rate limits กับผู้ให้บริการจริงก่อน staging **รอบนี้ยังไม่ได้ส่งอีเมลผ่าน SMTP ภายนอก** integration runner ใช้ Mailpit เท่านั้น อย่ารันร่วมกับ credentials ส่งเมลจริง

## อ้างอิง

- [Supabase Auth: configuration และ logout behavior](https://github.com/supabase/auth)
- [Pinned Auth API routes](https://github.com/supabase/auth/blob/v2.196.0/internal/api/api.go): Users ใช้ admin API; Sessions อ่านตาราง upstream ผ่าน read-only adapter เพราะรุ่นนี้ไม่มี admin session-list API
- [PostgreSQL row security](https://www.postgresql.org/docs/current/ddl-rowsecurity.html)
- [Mailpit Docker configuration](https://mailpit.axllent.org/docs/install/docker/)
