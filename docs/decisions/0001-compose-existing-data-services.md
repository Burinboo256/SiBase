# ADR 0001 — ประกอบบริการ data plane และสร้าง control plane ของ SiBase

วันที่ 13 กันยายน 2026 · สถานะ: ยอมรับสำหรับ Phase 0

## บริบท

เป้าหมายคือแพลตฟอร์มที่มี Database, Auth, APIs, Storage และ Realtime เชื่อมกัน ไม่ได้ต้องการพัฒนากลไกเหล่านี้ใหม่ทั้งหมด Repository ยังไม่มีโค้ดที่บังคับให้ใช้ framework เดิม

## การตัดสินใจ

ใช้ PostgreSQL + PostgREST + Supabase Auth/Storage/Realtime และสร้าง FastAPI control plane กับ React Dashboard ของ SiBase เองใน phase ถัดไป ทดสอบ data plane ผ่าน upstream JavaScript SDK ก่อนกำหนด public API compatibility

Docker Compose เป็น runtime ของ PoC และ local development; ไม่เริ่ม Kubernetes ในระยะนี้ Bootstrap CLI แทน provisioning worker เฉพาะ Phase 0

## ทางเลือกและผลตามมา

| ทางเลือก | ผลต่อ SiBase |
| --- | --- |
| เขียนบริการทั้งหมดเอง | ควบคุม contract ได้เต็มที่ แต่เพิ่มงาน token/session, schema API, policy enforcement และ event delivery |
| ใช้ Supabase self-hosted ทั้งชุด | เหมาะสำหรับหนึ่ง deployment ตาม upstream; ยังต้องสร้าง project management และ provisioning ที่ SiBase ต้องการ |
| ประกอบบริการที่เลือก | ทดสอบขอบเขตการเชื่อมต่อได้โดยตรง; ต้องดูแล version matrix และ bootstrap prerequisites |

ผลที่ต้องรับผิดชอบคือ service lifecycle, migrations, role grants และ gateway conventions เวลาประมาณการของ roadmap ตั้งอยู่บนการ reuse บริการเหล่านี้ หากเปลี่ยนไปสร้าง Auth/Storage/Realtime ใหม่ต้องประเมินเวลาอีกครั้ง

## การตรวจสอบ

ยึดผลทดสอบใน [Phase 0 report](../phase0-report.md) และ dependency lock เป็นหลัก ไม่ใช้เพียง `/health` เป็นหลักฐานว่าทุก migration หรือทุก event pipeline พร้อมใช้งาน

อ้างอิง: [Supabase architecture](https://supabase.com/docs/guides/getting-started/architecture), [upstream Docker stack](https://github.com/supabase/supabase/blob/master/docker/docker-compose.yml)
