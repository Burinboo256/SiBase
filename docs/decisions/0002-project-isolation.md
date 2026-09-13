# ADR 0002 — Database ต่อโปรเจกต์บน shared cluster สำหรับ MVP ภายใน

วันที่ 13 กันยายน 2026 · สถานะ: ยอมรับแบบมีขอบเขตสำหรับ MVP ทีมภายใน

## บริบท

การใช้ cluster ร่วมกันลดจำนวน database server processes แต่ PostgreSQL roles และ replication slot names มีขอบเขตทั้ง cluster การแยกชื่อ database อย่างเดียวจึงไม่ใช่ขอบเขตสิทธิ์ที่ครบถ้วน

## การตัดสินใจ

- แยก database และ service instance ต่อโปรเจกต์; API signing keys และ S3 identities แยกกัน
- LOGIN roles ใช้ prefix โปรเจกต์; common request roles เป็น NOLOGIN
- ถอน CONNECT/TEMP ของ PUBLIC; ให้ CONNECT เฉพาะ service/owner roles ของโปรเจกต์นั้น
- Runtime ทุกตัวไม่มี SUPERUSER/CREATEDB/CREATEROLE; Realtime เป็นบริการภายในที่มี REPLICATION/BYPASSRLS และ migration grants เฉพาะที่ตรวจพบ
- ไม่ส่ง service credentials ให้ frontend; platform identity แยกจาก app identity ใน Phase 2
- กำหนด `SLOT_NAME_SUFFIX` เป็น project reference เพื่อไม่ให้ replication slots ชนกัน

## หลักฐานและผลตัดสิน

[Phase 0](../phase0-report.md) ผ่าน 17/17 กลุ่มทดสอบทั้ง runtime เดิมและการเริ่มจาก volumes ว่าง โดย Realtime สองโปรเจกต์ทำงานพร้อมกัน จึงใช้แนวทางนี้เป็นฐานของ Phase 1 สำหรับทีมภายในที่ผู้ใช้ยืนยัน ไม่ถือเป็นการอนุมัติ public multi-tenant hosting

## เกณฑ์เลือกไปต่อ

ต้องผ่าน migrations และ workflow จริงของทั้งสอง database รวมทั้ง negative tests ของ database login, JWT, API key, S3 credential และสิทธิ์ผู้ใช้ภายในโปรเจกต์ ถ้าจำเป็นต้องมอบ superuser ให้บริการประจำโปรเจกต์ หรือทำให้ credentials เข้า database อื่นได้ ให้เลือก cluster ต่อโปรเจกต์และปรับ provisioning/resource budget

การที่ health endpoint ตอบสำเร็จ แต่ replication function หายจาก migration ที่ล้มเหลว ยังไม่ถือว่าผ่าน gate

## ข้อจำกัดของแนวทางนี้

สิทธิ์ที่ทดสอบแยกข้อมูลทาง API และ database connection แต่ไม่แยกทรัพยากรเครื่อง, cluster metadata หรือ failure domain และยังต้อง harden network/service privileges ก่อนเปิดให้บุคคลภายนอกใช้งาน การทดสอบ Phase 0 ไม่ใช่การตรวจ security ทุก attack surface

PoC ใช้รหัสผ่าน DB ร่วมกันระหว่าง LOGIN roles ภายในโปรเจกต์เดียว แม้แต่ละโปรเจกต์มีคนละรหัสผ่าน จึงยังห้ามแจก DB credentials ให้ผู้พัฒนาแอป ต้องแยก secret ต่อ role และทดสอบการเชื่อมต่อด้วย identity อื่นก่อนเปิด SQL Editor หรือ direct DB access

อ้างอิง: [PostgreSQL roles](https://www.postgresql.org/docs/current/database-roles.html), [database privileges](https://www.postgresql.org/docs/current/ddl-priv.html), [Realtime tenant migrations](https://github.com/supabase/realtime/tree/v2.134.10/lib/realtime/tenants/repo/migrations)
