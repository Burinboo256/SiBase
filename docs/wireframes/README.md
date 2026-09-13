# SiBase — Phase 0 Wireframes

เปิด [index.html](index.html) ผ่าน local server ตาม README หลัก Prototype ใช้ HTML/CSS/JavaScript และข้อมูลตัวอย่าง ไม่มีการเรียก backend หรือเก็บ secrets

## หน้าจอและ Interaction

| หน้าจอ | สิ่งที่ตรวจได้ | งานที่จะเชื่อมบริการจริง |
| --- | --- | --- |
| Overview | Cards, service status และปุ่มไป workflow ถัดไป | Project registry/metrics ใน Phase 2 |
| Table Editor | ตารางตัวอย่าง, filter และ dialog ตั้งชื่อตาราง | Introspection, migration, row editor ใน Phase 4 |
| Authentication | รายชื่อผู้ใช้และ session summary | Auth admin API ใน Phase 3 |
| Storage | Bucket/file browser และตัวอย่าง share/upload action | Upload progress และ signed URLs ใน Phase 5 |
| Realtime | เพิ่ม simulated event ผ่านปุ่ม | Live subscription/inspector ใน Phase 6 |
| API Docs | Endpoint ตามโปรเจกต์และ copy JavaScript example | Endpoint/schema/key จาก project registry ใน Phase 4/7 |
| Settings | Project reference, membership context และชนิด keys | Control API และ rotation workflow ใน Phase 2/3 |

Project selector เปลี่ยน reference และ endpoint ระหว่าง alpha/beta; ข้อมูลตาราง/สถิติยังเป็น sample data ชุดเดียวกัน ปุ่มที่ยังไม่เชื่อม backend แสดงข้อความอธิบายว่าเป็น preview

## States ที่ต้องมีใน Dashboard จริง

- Project: provisioning, ready, failed พร้อม retry, suspended และ archived
- Table: loading, ไม่มีตาราง, ไม่มีแถวตาม filter, validation error และ permission denied
- Auth: pending verification, active, banned, session expired และ email delivery failed
- Storage: ไม่มี bucket/file, uploading พร้อม progress, over quota และ signed URL expired
- Realtime: connecting, subscribed, disconnected, reconnecting และสิทธิ์ถูกเพิกถอน
- Settings: saving, saved, error และขั้นตอนยืนยันก่อน rotation/archive

ใน Phase 0 แสดงหน้า ready/sample เป็นหลัก รายการ states เป็น UI contract สำหรับ phase ถัดไป ไม่อ้างว่า prototype จำลองครบทุกกรณี

## การตรวจหน้าจอ

ใช้ semantic headings, table, labels, focus indicator และ layout ที่ปรับจาก sidebar เป็น navigation แนวนอนเมื่อหน้าจอแคบ การตรวจด้วย browser ที่ทำจริงระบุใน [รายงาน Phase 0](../phase0-report.md)
