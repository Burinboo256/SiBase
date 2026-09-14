# SiBase

แพลตฟอร์ม Backend-as-a-Service ที่วางแผนรวม PostgreSQL, Authentication, REST APIs, Storage และ Realtime พร้อม Dashboard

**Phase 2 มีระบบ Control Plane ที่ทดสอบ local แล้ว** (14 กันยายน 2026): บัญชีแพลตฟอร์ม, workspace/สมาชิก, สร้างโปรเจกต์จริง, API keys และ durable worker ดู [รายงาน Phase 2](docs/phase2-report.md) สำหรับผลตรวจและรายการที่ยังรอรับงาน ยังไม่ใช่ production; ผล GitHub CI ที่ยืนยันแล้วเป็นของ [Phase 1](https://github.com/Burinboo256/SiBase/actions/runs/34765727009)

## Phase 3 — Auth และ RLS

เพิ่ม Auth แบบ opt-in รายโปรเจกต์: ยืนยันอีเมล/กู้รหัสผ่าน, refresh/logout, signing-key rotation, forced RLS และหน้า Users/Sessions/Auth Settings/Permission preview ใช้โปรเจกต์ `Auth Sandbox` แยกจาก Operations/Inventory ดู [คู่มือ](docs/phase3-development.md) และ [ผลตรวจ/ข้อจำกัด](docs/phase3-report.md)

```sh
make phase3-dev
make phase3-prepare
make phase3-check
# บน fresh checkout ให้รัน make phase2-integration ก่อน:
make phase3-integration
```

Dashboard ใช้พอร์ต 58400 และบัญชีผู้ดูแลเดิม; inbox ทดสอบอยู่ `http://127.0.0.1:58425` integration จะเพิ่มข้อมูลสังเคราะห์และหมุน signing key ของ Sandbox ไม่ใช่คำสั่งสำหรับ production ยังไม่มีผล GitHub CI ของ Phase 2–3 หรือการทดสอบ SMTP staging จริง

## เริ่ม Phase 2

```sh
make phase2-dev
make phase2-check
make phase2-integration  # สร้างข้อมูล/บัญชีทดสอบและทดสอบ suspend/restore
make phase2-recovery     # หยุด worker กลางงานแล้วตรวจการกู้คืน
```

เปิด http://127.0.0.1:58400 ใช้ `owner@sibase.local` และรหัสผ่านที่สุ่มไว้ใน `.local/sibase-control/initial-owner.json` ห้ามส่งไฟล์นี้ขึ้น GitHub ส่วน Control API ใช้ 58410 และ project gateway ใช้ 58420

Stack `sibase-control` แยก volumes, credentials และ migrations จาก Phase 0–1 ใช้ `make phase2-status` ดูสถานะ และ `make phase2-stop` หยุดโดยเก็บข้อมูลไว้ คู่มือ [Phase 2 development](docs/phase2-development.md) อธิบายการเพิ่มสมาชิก ตารางสิทธิ์ และข้อจำกัดของ local pilot

## เริ่ม Phase 1

ต้องมี Python 3.11+ และ Docker Desktop/Engine พร้อม Compose v2+; แนะนำจัดสรร RAM ให้ Docker ประมาณ 8 GB สำหรับพัฒนา การติดตั้งครั้งแรกต้องใช้อินเทอร์เน็ต ไม่ต้องติดตั้ง Node หรือ Python packages บน host

```sh
make setup
make dev
make check
make integration
make smoke
```

เปิด Dashboard ที่ http://127.0.0.1:58200 และ Control API docs ที่ http://127.0.0.1:58210/api/docs ส่วน Alpha/Beta gateway ใช้พอร์ต 58201/58202 เปลี่ยนพอร์ตได้ตาม [.env.example](.env.example) โดยไม่แก้ source

Overview, project selector, refresh และ API reference ใช้งานได้; หน้า Database/Auth/Storage/Realtime management ยังเป็น navigation สำหรับ phase ถัดไป โปรเจกต์สองชุดสร้างด้วย local launcher ไม่ใช่ provisioning ผ่าน UI

```sh
make status
make lifecycle  # หลัง integration: ทดสอบหยุด/เปิดและตรวจข้อมูลเดิม
make logs       # logs ที่ปิดบัง generated secrets
make stop       # เก็บ volumes และ secrets ไว้
```

Stack `sibase-dev` แยกจาก Phase 0; secrets อยู่ `.local/sibase-dev/` ซึ่งถูก gitignore ห้ามเผยแพร่โฟลเดอร์นี้หรือ Docker environment/config output และห้ามเปิดพอร์ตออกสู่เครือข่ายภายนอก เพราะยังไม่มีบัญชี/สิทธิ์แพลตฟอร์ม ดู [คู่มือพัฒนา](docs/development.md) สำหรับโครงสร้างและคำสั่งทั้งหมด

## เอกสาร

- [Development roadmap](docs/development-roadmap.md) — phases และเกณฑ์ตรวจรับ
- [Development guide](docs/development.md) — setup, commands, coding/testing และ configuration
- [Phase 1 report](docs/phase1-report.md) — สิ่งที่ส่งมอบ ผลตรวจ local/GitHub CI และข้อจำกัด
- [Product scope](docs/product-scope.md) — MVP, workload, pilot และ recovery targets
- [Architecture](docs/architecture.md) — ขอบเขตบริการและสิทธิ์
- [Phase 0 report](docs/phase0-report.md) — หลักฐาน ผลทดสอบ และข้อจำกัด
- [Architecture decisions](docs/decisions/0001-compose-existing-data-services.md)
- [Third-party inventory](docs/third-party-components.md)

## รัน PoC เดิม — Phase 0

ต้องมี Python 3.11+ และ Docker Desktop/Engine พร้อม Compose จัดสรร RAM ให้ Docker อย่างน้อย 8 GB การรันครั้งแรกต้องมี internet สำหรับ container images และ npm packages; ไม่ต้องติดตั้ง Node.js บน host

```sh
python3 scripts/phase0.py up
python3 scripts/phase0.py test
python3 scripts/phase0.py status
```

PoC สร้าง Compose project `sibase-phase0` และฐานข้อมูล `alpha`/`beta` โดยใช้ loopback endpoints `http://127.0.0.1:58101` และ `http://127.0.0.1:58102` สคริปต์ทดสอบใช้ข้อมูลสังเคราะห์และเพิ่มผู้ใช้/แถว/ไฟล์ใหม่ที่มี run ID ทุกครั้ง สามารถรันซ้ำกับ volume เดิมได้

Secrets สร้างแบบสุ่มและเก็บใน `.local/phase0/` ที่ถูก gitignore; อย่าส่งโฟลเดอร์นี้หรือ output ของ `docker compose config` ให้ผู้อื่น API keys ของ PoC มีอายุ 30 วัน; การเริ่มระบบซ้ำไม่หมุน secrets ที่ผูกกับ volume เดิม

ผลทดสอบอยู่ `.local/phase0/test-report.json` ไม่มี token หรือรหัสผ่าน ตัวอย่างข้อมูลหน้า wireframe ไม่ใช่ข้อมูลจาก test runner

## Wireframes

```sh
python3 -m http.server 58100 --bind 127.0.0.1 --directory docs/wireframes
```

เปิด `http://127.0.0.1:58100` เพื่อทดลอง Overview, Table Editor, Authentication, Storage, Realtime, API Docs และ Settings การสร้างตาราง/อัปโหลด/บันทึกใน wireframe เป็น preview เท่านั้น

## ตรวจปัญหาและหยุดระบบ

```sh
python3 scripts/phase0.py logs --service realtime-alpha --tail 100
python3 scripts/phase0.py stop
```

คำสั่ง logs ปิดบัง secrets ที่สร้างโดย bootstrap; อย่าใช้ logs เป็นที่เก็บข้อมูลจริง คำสั่ง stop หยุดเฉพาะ containers ของ PoC และเก็บ volumes ไว้ สคริปต์ไม่มีคำสั่งลบ volumes และไม่แก้ไข `AGENTS.md`

หากพอร์ต 58101/58102 ถูกใช้อยู่ ให้ปรับ mapping ใน `scripts/phase0.py` ก่อนสร้าง configuration อย่าหยุดบริการอื่นเพื่อแย่งพอร์ต ตรวจข้อจำกัดและสิ่งที่ยังไม่ผ่านในรายงานก่อนนำ PoC ไปต่อยอด
