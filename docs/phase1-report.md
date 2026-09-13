# SiBase — Phase 1 Report

วันที่ตรวจ: 13 กันยายน 2026 · กลุ่มเป้าหมาย: ทีมภายในสร้างแอปและระบบงาน

สถานะ: **ใช้งานและผ่าน local checks แล้ว; รอ GitHub CI ก่อนปิด Phase 1** ผู้ใช้อนุมัติ commit/push แล้ว; ผล remote runner ยังรอยืนยัน

## สิ่งที่ส่งมอบ

- FastAPI Control API แบบอ่านอย่างเดียว: liveness, readiness, project/service overview และ OpenAPI
- React/TypeScript Dashboard: สถานะจริงของ Alpha/Beta, project selector, refresh, loading/error/empty/stale states และลิงก์ API reference
- Stack `sibase-dev` แยกพอร์ต, secrets และ volumes จาก Phase 0; hot reload สำหรับ API/Dashboard
- Platform PostgreSQL แยก instance พร้อม Alembic installation marker; API ใช้ reader credential ส่วน migration ใช้ owner credential
- Project LOGIN roles ทั้งหกใช้รหัสผ่านต่างกันต่อ role/โปรเจกต์ และเพิ่ม monitor role ที่ไม่มี grants อ่าน application tables
- แยก platform migration, project bootstrap/compatibility และ upstream migrations; ย้าย `auth.uid()` compatibility ออกจากการพึ่ง test fixture สำหรับ startup
- Python hash-locked dependencies, npm lockfile, Ruff/ESLint/Prettier, mypy/TypeScript, Make workflow และ GitHub Actions
- Structured request logs ที่ไม่บันทึก headers/body/query/raw exceptions และคำสั่งอ่าน logs ที่ปิดบัง generated secrets

## ผลตรวจจริง

| Gate | ผล |
| --- | --- |
| `make check` | ผ่าน lint, formatting, type checking, unit tests และ build |
| Backend pytest | 39/39 รวม launcher regression; statement coverage 100% ของ `src/sibase` (185 statements; threshold 80%) |
| Frontend Vitest | 7/7 component tests ใน jsdom |
| Fresh-volume integration | 19/19 กลุ่ม; สอง project databases และ platform instance แยก |
| HTTP smoke | ผ่านทั้ง stack ปกติและ fresh: HTML/JS modules, proxy, health, overview, OpenAPI, safe response และ POST rejection |
| Stop/start | แถว sentinel 2 แถวและ S3 objects 2 ไฟล์ยังตรงเดิม; ไม่พบ exit 137 |
| Phase 0 regression | 17/17 หลังปรับ shared generator/test runner |
| Safari desktop | ตรวจ Overview, Alpha/Beta selection, refresh timestamp, planned Database page และเปิด Swagger UI ได้ |
| GitHub CI | สร้าง workflow แล้ว แต่ยังไม่ได้รันบน GitHub |

หลักฐาน: [fresh-volume integration](evidence/phase1-fresh-volume.json), [lifecycle exit codes](evidence/phase1-lifecycle.json) ผล runtime ล่าสุดอยู่ `.local/<stack>/` และไม่ควรเผยแพร่โฟลเดอร์ทั้งชุด

ใช้ namespace ใหม่ `sibase-phase1-fresh` พร้อมพอร์ต 58300/58310/58301/58302 โดยตรวจว่าไม่มี named volumes ก่อนเริ่ม และ Docker สร้าง volumes ใหม่จริง ทดสอบจาก source ปัจจุบัน ไม่ใช่ fresh checkout จาก published commit หลังทดสอบหยุดเฉพาะ stack นี้และเก็บ volumes ไว้; `sibase-dev` ยังเปิดให้ทดลอง

## ปัญหาที่พบและแก้ในรอบนี้

- Vite proxy `/api` ดัก `api.ts` จนหน้าเว็บว่าง: จำกัดเป็น `/api/` และเพิ่ม HTTP regression ตรวจ JavaScript modules; proxy `/health/` รองรับ Swagger ผ่าน Dashboard ด้วย ([Vite proxy matching](https://vite.dev/config/server-options#server-proxy))
- Realtime health อาจตอบ HTTP 200 แต่ body ระบุไม่พร้อม: ตรวจ `data.healthy` เพิ่ม
- หลัง restart Storage ตอบ health ก่อน SeaweedFS ลงทะเบียน volume server: ตรวจ topology readiness และให้ persistence verifier retry เฉพาะ network/5xx แบบมีเวลาจำกัด; 404 หรือเนื้อหาไม่ตรงยัง fail
- ตั้ง graceful-stop periods, ใช้ init/direct entrypoint สำหรับ object storage และ bounded restart policy ของ upstream services
- แก้ ownership ของ `auth.uid()` ใน legacy test fixture ให้สอดคล้องกับ Auth schema owner
- ปิดข้อพบจาก pre-Phase-2 review: smoke/lifecycle อ่านพอร์ตจาก stack ที่เลือก ไม่ใช้พอร์ต default ของอีก stack; existing dev เก็บพอร์ตเดิมเว้นแต่มี explicit override
- `make dev` รอ Dashboard HTML, JavaScript modules และ API proxy ให้พร้อมด้วย ไม่ผ่านเพียงเพราะ backend พร้อม เพิ่ม regression tests สำหรับ Dashboard timeout/โหลดไม่ครบ และการเลือกพอร์ตผิด stack

## ขอบเขตและงานที่ยังไม่รับรอง

ยังไม่มี platform login/RBAC, workspace registry, provisioning worker, การสร้างโปรเจกต์หรือตารางผ่าน UI, key rotation, TLS, rate limits, production deployment หรือ backup/restore drill โปรเจกต์ Alpha/Beta เป็น fixed local projects และการทดสอบใช้ข้อมูลสังเคราะห์

Health probes ไม่ใช่หลักฐานว่า operations ทุกชนิดทำงานได้หรือผ่าน security/load audit; การแยกสิทธิ์รับรองเฉพาะ contracts ที่ทดสอบ ไม่ใช่ containment ของ privileged service compromise Coverage ข้างต้นไม่รวม launcher, migrations และ frontend และไม่ใช่ branch coverage

ยังไม่มี automated browser E2E หรือ mobile/cross-browser acceptance; HTTP smoke และ component tests ไม่ทดแทนการ render ใน browser การ build Dashboard ผ่านยังไม่ใช่ production hosting setup เอกสาร Swagger ปัจจุบันใช้ assets จาก CDN จึงต้องใช้อินเทอร์เน็ตเปิด UI ครั้งแรก

พบ deprecation warnings จาก Starlette/AnyIO test helpers และ transitive `uuid` ใน data-plane test runner แต่ไม่มี test failure ต้องประเมิน dependency updates/SBOM ก่อนเผยแพร่

## เริ่มใช้งานและงานต่อไป

ดู [Development Guide](development.md) และ [README](../README.md) เปิด Dashboard ที่ http://127.0.0.1:58200 ใช้ `make stop` เพื่อหยุดโดยไม่ลบข้อมูล ห้ามเปิดพอร์ตให้เครื่องอื่นเข้าถึงขณะยังไม่มี platform identity

ขั้นถัดไปเพื่อปิด Phase 1 คือตรวจ GitHub workflow จาก fresh checkout ตามการอนุมัติ commit/push เมื่อผ่านจึงเริ่ม Phase 2: platform identity, workspace/membership, project registry และ provisioning jobs ตาม [roadmap](development-roadmap.md) โดยยังไม่เริ่มงานเหล่านี้ใน Phase 1
