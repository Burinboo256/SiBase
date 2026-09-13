# SiBase — Product Scope / Phase 0

ปรับปรุง 13 กันยายน 2026 · ยืนยันกลุ่มผู้ใช้แรก: ทีมภายในสำหรับสร้างแอปและระบบงาน

## ผู้ใช้และปัญหาที่แก้

ทีมพัฒนาแอปภายในต้องการ PostgreSQL, บัญชีผู้ใช้, API, พื้นที่เก็บไฟล์ และ Realtime ที่ใช้ร่วมกันได้โดยไม่ต้องตั้งค่าทุกบริการซ้ำในทุกแอป เจ้าของ workspace จัดการโปรเจกต์ผ่าน SiBase; ผู้ใช้ปลายทางเข้าสู่แอปที่ทีมสร้างขึ้น บัญชีสองกลุ่มนี้แยกกัน

แอปตัวอย่างคือ task board ที่ผู้ใช้มีรายการงานและไฟล์แนบส่วนตัว โดยเปิดสองหน้าต่างเพื่อเห็นข้อมูลเปลี่ยนตามกัน ข้อมูลใน PoC เป็นข้อมูลสังเคราะห์ทั้งหมด

## ขนาดและข้อจำกัดตั้งต้น

ผู้ใช้ยืนยันกลุ่มเป้าหมายแล้วเมื่อ 13 กันยายน 2026 ส่วนตัวเลขต่อไปนี้ยังเป็นสมมติฐานออกแบบ ไม่ใช่ capacity ที่ผ่าน load test งบที่อนุมัติ หรือราคาจากผู้ให้บริการ

| หัวข้อ | ขอบเขตเริ่มต้น |
| --- | --- |
| Pilot | 1 workspace, 2–3 แอป, เพดาน 5 โปรเจกต์ |
| ผู้ใช้ | 100 บัญชี/โปรเจกต์; 20 concurrent sessions/โปรเจกต์ |
| Database | 1 GB/โปรเจกต์ ในช่วง pilot |
| Storage | 5 GB/โปรเจกต์; ไฟล์ไม่เกิน 10 MB |
| Local | Docker Desktop; กำหนด RAM ให้ Docker อย่างน้อย 8 GB |
| Staging ที่จะประเมิน | 4 vCPU, RAM 8–16 GB, disk 80 GB, single region |
| งบตั้งต้น | เพดานเสนอ 3,000 บาท/เดือนสำหรับ pilot; ต้องเลือกเครื่องตามผลวัดและใบเสนอราคาจริงก่อนจัดซื้อ |
| Recovery target | RPO ≤24 ชั่วโมง; RTO ≤4 ชั่วโมง; ตรวจด้วย restore drill ใน Phase 8 |
| ทีม/เวลา | ใช้สมมติฐาน 2–3 นักพัฒนาจาก roadmap; Phase 0 เป็น technical spike |

Phase 0 ใช้ Docker บนเครื่องนี้และไม่สร้างทรัพยากรที่มีค่าใช้จ่ายภายนอก เมื่อมีจำนวนผู้ใช้/ข้อมูลจริงจึงปรับเพดานและงบ

## User Flow และการตรวจรับ MVP

| ลำดับ | การกระทำ | ผลลัพธ์ที่ผู้ใช้ต้องเห็น |
| --- | --- | --- |
| 1 | เจ้าของสร้าง workspace และโปรเจกต์ | Provisioning status, endpoint และ project reference |
| 2 | Developer สร้างตาราง `tasks` | Table Editor, schema และ policy template |
| 3 | ผู้ใช้สมัคร/เข้าสู่แอป | Session ของโปรเจกต์นั้นและข้อมูลบัญชี |
| 4 | แอปเพิ่ม/แก้ไขงานผ่าน REST | ข้อมูลเฉพาะที่ผู้ใช้มีสิทธิ์; error ระบุปัญหาได้ |
| 5 | แอปแนบไฟล์ private | เปิดไฟล์เองได้; แชร์ด้วย signed URL ที่หมดอายุได้ |
| 6 | เปิดแอปอีกหน้าต่าง | เห็นการเปลี่ยนแปลงผ่าน Realtime |
| 7 | ผู้ใช้อื่นลองเข้าถึงข้อมูล | API, Storage และ Realtime ปฏิเสธตาม policy |
| 8 | Owner ดูสถานะ/หมุน keys | ทราบว่าค่าใดใช้ใน browser และค่าใดเป็น server secret |

ใน Phase 0 ข้อ 1–2 ใช้ bootstrap script/SQL และ mock wireframe; control API, provisioning UI, table UI ที่ทำงานจริงอยู่ Phase 1–4

## สิทธิ์ในแพลตฟอร์ม

| งาน | Owner | Admin | Developer | Viewer |
| --- | --- | --- | --- | --- |
| ดู schema/status/docs | ได้ | ได้ | ได้ | ได้ |
| เปลี่ยน schema/policy/SQL | ได้ | ได้ | ได้ | ไม่ได้ |
| จัดการ app users และ buckets | ได้ | ได้ | ได้ | ไม่ได้ |
| สมาชิกและ rotation ของ server secrets | ได้ | ได้ | ไม่ได้ | ไม่ได้ |
| ลบ workspace/โอน ownership | ได้ | ไม่ได้ | ไม่ได้ | ไม่ได้ |

นี่เป็น permission contract ของ control plane ที่จะทำใน Phase 2 ไม่ใช่สิทธิ์ของผู้ใช้แอป ผู้ใช้แอปถูกควบคุมด้วย RLS และ tokens ของแต่ละโปรเจกต์

## สิ่งที่ Phase 0 ต้องพิสูจน์

- Auth ออก token จริงและเรียก REST/Storage/Realtime ได้ผ่าน Supabase JS SDK ที่ pin เวอร์ชัน
- PostgreSQL สองฐานข้อมูลใช้ migrations และบริการขนานกันได้ โดยไม่มี role collision ที่ทำให้สิทธิ์รั่ว
- Token, API key, database login และ S3 credential ของ A เข้า B ไม่ได้ทั้งสองทิศทาง
- ผู้ใช้คนที่สองในโปรเจกต์เดียวกันอ่าน/แก้ไข/รับ event หรือเปิดไฟล์ส่วนตัวของคนแรกไม่ได้
- เขียนข้อมูลผ่าน REST และ SQL แล้ว Realtime ทำงานทั้งสองกรณี
- ผู้พัฒนาอื่นสามารถเริ่ม stack และรันชุดตรวจซ้ำตาม README

## Workload และเกณฑ์ในระยะถัดไป

Phase 0 เป็น functional contract test: สองโปรเจกต์, สี่ผู้ใช้, แถวงานและไฟล์ขนาดเล็ก โดยทดสอบ Realtime ของสองโปรเจกต์พร้อมกัน ผลผ่าน 17/17 กลุ่ม รวมการเริ่มจาก volumes ว่าง ดู [รายงาน Phase 0](phase0-report.md) ไม่สรุป throughput/SLA จากผลนี้

ก่อน private beta ให้ทดสอบอย่างน้อย 10,000 แถว/โปรเจกต์, REST 20 requests/วินาที/โปรเจกต์ และ 20 WebSocket connections/โปรเจกต์ โดยตั้งเป้าหมาย REST p95 <500 ms และ event lag p95 <2 วินาทีบนเครื่อง staging ที่ระบุ รวมทั้งทดสอบเกินเพดานและการกู้คืน ต้องปรับเป้าหมายตามผลวัด ไม่เปิดใช้งานเกิน capacity ที่ตรวจรับ

## สิ่งที่อยู่นอก Phase 0

ยังไม่ทำ billing, public signup, OAuth/SSO, GraphQL, Edge Functions, HA, production deployment หรือระบบสำรองข้อมูลจริง Email auto-confirm เปิดเฉพาะ PoC เพื่อไม่ต้องส่งอีเมลออกภายนอก; email delivery/verification และ recovery flows เต็มรูปแบบอยู่ Phase 3
