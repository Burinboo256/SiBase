# SiBase — Phase 0 Report

วันที่ตรวจรับ: 13 กันยายน 2026 · ผล: ผ่าน local technical PoC สำหรับทีมภายใน

## ข้อสรุป

ผู้ใช้ยืนยันว่ารุ่นแรกใช้กับ **ทีมภายในเพื่อสร้างแอปและระบบงาน** จึงเลือก database ต่อโปรเจกต์บน shared PostgreSQL cluster เป็นฐานของ MVP โดยแยก Auth, REST, Storage, Realtime, signing keys และ S3 identities ต่อโปรเจกต์ ตาม [ADR 0002](decisions/0002-project-isolation.md)

ชุดทดสอบผ่าน **17/17 กลุ่ม** ทั้ง runtime เดิมและการเริ่มจาก volumes ว่างของ Compose project `sibase-phase0-fresh` โดยรอบ fresh ใช้ bootstrap/migrations จาก source โดยไม่แก้ฐานข้อมูลด้วยมือ สามารถเริ่ม Phase 1 ตาม roadmap ได้ แต่ยังไม่ถือว่า MVP พร้อมใช้งานจริงหรือผ่าน security audit

## สิ่งที่ส่งมอบ

- [Product scope](product-scope.md): ผู้ใช้เป้าหมาย, user flow, permission matrix และสมมติฐาน workload/งบ/RPO/RTO
- [Architecture](architecture.md) และ [ADRs](decisions/0001-compose-existing-data-services.md): topology, trust boundaries และเหตุผลเลือกบริการ
- [Bootstrap CLI](../scripts/phase0.py), [project SQL](../poc/phase0/project.sql) และ [integration tests](../poc/phase0/verify.mjs)
- [Image locks](../poc/phase0/images.lock.json), [npm lock](../poc/phase0/package-lock.json) และ [component inventory](third-party-components.md)
- [Wireframes 7 หน้าจอ](wireframes/index.html) พร้อม [interaction/state contract](wireframes/README.md)

## หลักฐานและสภาพแวดล้อม

[ผลทดสอบ fresh-volume แบบ JSON](evidence/phase0-fresh-volume.json) บันทึกเวลา 02:45:07–02:45:30 UTC หรือ 09:45:07–09:45:30 เวลาไทย ชุดตรวจใช้ประมาณ 23 วินาที **ไม่รวมดาวน์โหลด/build/startup** และไม่ใช่ benchmark เพราะรวมช่วงรอ subscription และ signed URL หมดอายุ

ทดสอบบน macOS ผ่าน Docker Desktop, Linux/ARM64, Docker Engine 29.6.1, Compose 5.3.0 และ Python 3.14; Docker มี 8 CPUs และ RAM ประมาณ 7.75 GiB ใช้ PostgreSQL 17.6 + wal2json, Supabase JS 2.116.0 และ Node.js 22.23.2 ใน container เวอร์ชัน/digests ทั้งชุดอยู่ในไฟล์ lock; ยังไม่ได้ตรวจบน Linux/AMD64

การสุ่มวัด memory หลังรันทดสอบหนึ่งครั้งรวม 11 service containers ได้ประมาณ 1.24 GiB ไม่รวม test runner/บริการอื่น/VM overhead และไม่ใช่ peak memory หรือ capacity ต่อโปรเจกต์

## ผลทดสอบและขอบเขต SDK ที่พิสูจน์แล้ว

ใช้สองโปรเจกต์ (`alpha`, `beta`), สี่ผู้ใช้ และข้อมูลสังเคราะห์เท่านั้น

| ขอบเขต | สิ่งที่ตรวจจริง | ผล |
| --- | --- | --- |
| Bootstrap | บริการพร้อม, tenant migrations ครบ, application schemas และ RLS | ผ่าน |
| Authentication | SDK signup, password login, refresh และ logout ของทั้งสี่บัญชี | ผ่าน |
| REST/RLS | Insert/select/update; อีกคนอ่านหรือแก้แถวไม่ได้; ปลอม/เปลี่ยน owner และ anonymous access ถูกปฏิเสธ; ไม่ expose `auth` schema | ผ่าน |
| Storage | Private upload/download; ผู้ใช้อื่นอ่านหรือเขียน path ของเจ้าของไม่ได้; signed URL เปิดได้และใช้ไม่ได้หลังหมดอายุ | ผ่าน |
| Token/API keys | ใช้ token ผิดโปรเจกต์คู่กับ key ของปลายทาง และ key ผิดโปรเจกต์คู่กับ token ของปลายทาง ผ่าน REST/Auth/Storage ทั้งสองทิศทาง | ถูกปฏิเสธ |
| DB logins | ห้า LOGIN roles ต่อโปรเจกต์เข้า DB ตนเองได้ แต่เข้าอีกโปรเจกต์และ `postgres` ไม่ได้ | ผ่าน |
| Role privileges | ไม่มี project role เป็น SUPERUSER/CREATEDB/CREATEROLE; REST/owner สั่ง SET ROLE เป็น storage login, owner อีกโปรเจกต์ หรือ postgres ไม่ได้ | ผ่าน |
| S3 identities | เขียน bucket ตนเองได้ แต่ GET object ที่มีอยู่จริงใน bucket อีกโปรเจกต์ได้ 403 ทั้งสองทิศทาง | ผ่าน |
| Realtime | สองโปรเจกต์ subscribe พร้อมกัน; REST/SQL UPDATE ส่งถึงเจ้าของ แต่ไม่ถึงอีกคน; token ข้ามโปรเจกต์เกิด CHANNEL_ERROR | ผ่าน |

พบ replication slots สี่ชื่อ active พร้อมกัน ได้แก่ `supabase_realtime_replication_slot_alpha/beta` และ `supabase_realtime_messages_replication_slot_alpha/beta` จึงไม่มี slot-name collision ใน topology ที่ทดสอบ

ข้อจำกัดของหลักฐาน: หัวข้อ REST CRUD ใน raw report ทดสอบ insert/select/update แต่ยังไม่ทดสอบ REST delete; Realtime ตรวจเฉพาะ UPDATE และสังเกตการไม่ส่งข้อมูลให้อีกคนในช่วงเวลาของ test ไม่ใช่การพิสูจน์ทุก permission transition ส่วนการปฏิเสธ DB `postgres` เป็น administrative-database check ยังไม่มี platform database/control API จริง

## สิ่งที่ค้นพบและแก้ใน PoC

1. **Realtime migrations:** ต้องมี `dashboard_user` แบบ NOLOGIN, membership/inheritance ของ `supabase_realtime_admin` และสิทธิ์ `SET log_min_messages` เฉพาะ runtime role; health endpoint อย่างเดียวไม่เพียงพอ จึงตรวจ migration version และ event delivery
2. **Cluster-wide names:** กำหนด prefix ให้ LOGIN roles และ `SLOT_NAME_SUFFIX` ให้แต่ละโปรเจกต์
3. **JWT claims:** เพิ่ม compatibility `auth.uid()` ให้ policy อ่านได้ทั้ง legacy claim และ JSON claims จากบริการที่ใช้ร่วมกัน
4. **Gateway:** เพิ่ม map bucket size สำหรับ JWT ยาว, resolve Docker DNS ซ้ำหลัง container recreate และให้ signed/public object routes ส่งต่อไปตรวจสิทธิ์ที่ Storage โดยไม่บังคับ project key เพิ่ม
5. **Object storage:** ปรับ SeaweedFS local volume limit เป็น 32 เพื่อมีที่สำหรับ buckets และปิดบริการเสริมที่ PoC ไม่ใช้
6. **Subscription readiness:** รอ database subscription system message สถานะ `ok` ก่อนเขียนข้อมูล ไม่ใช้เพียง WebSocket `SUBSCRIBED` เป็นเกณฑ์

ทุกข้ออยู่ใน source/config generator แล้ว และถูกตรวจด้วย fresh-volume run

## Wireframe QA

เปิดผ่าน Safari ที่ `http://127.0.0.1:58100` ตรวจ Overview layout, navigation, Table Editor filter, dialog สร้างตารางตัวอย่าง, Realtime simulated event และเนื้อหาหน้า API Docs การสร้าง/อัปโหลด/บันทึกเป็น preview ไม่มี backend mutation และไม่มี secrets จริงในหน้าเว็บ ยังไม่ได้ทำ automated accessibility, cross-browser หรือ mobile viewport acceptance

## วิธีรันซ้ำ

จาก repository root:

```sh
python3 scripts/phase0.py up
python3 scripts/phase0.py test
python3 scripts/phase0.py status
```

ผลล่าสุดอยู่ `.local/phase0/test-report.json` และมีไฟล์แยกตาม run ID การทดสอบเพิ่มผู้ใช้/แถว/ไฟล์ตัวอย่างใหม่ทุกครั้ง ไม่ลบข้อมูลจากรอบก่อน Secrets/config อยู่ `.local/phase0/` ซึ่งถูก gitignore; ห้ามเผยแพร่โฟลเดอร์นี้หรือ Compose config ที่มีค่าจริง

สำหรับตรวจ bootstrap ใหม่ ให้เลือก namespace ที่ยังไม่มี volumes และหยุด runtime ปกติก่อนเพราะใช้พอร์ตเดียวกัน ตัวอย่างนี้ต้องเปลี่ยน suffix หากเคยใช้แล้ว; คำสั่ง `volume ls` ต้องไม่พบ volumes ก่อน `up` จึงจะนับว่า fresh:

```sh
python3 scripts/phase0.py prepare
python3 scripts/phase0.py stop
docker volume ls --filter label=com.docker.compose.project=sibase-phase0-fresh-check-01
docker compose -p sibase-phase0-fresh-check-01 -f .local/phase0/compose.json up -d --build
docker compose -p sibase-phase0-fresh-check-01 -f .local/phase0/compose.json run --rm --no-deps -e POC_RUN_LABEL=fresh-volume test sh -c 'npm ci --ignore-scripts --no-audit --no-fund && node verify.mjs'
docker compose -p sibase-phase0-fresh-check-01 -f .local/phase0/compose.json stop
python3 scripts/phase0.py up
```

รอบตรวจรับจริงใช้ namespace `sibase-phase0-fresh`; หยุดชุดนั้นและเปิด `sibase-phase0` กลับแล้ว จากนั้นรัน `python3 scripts/phase0.py test` ตาม README ผ่านอีกครั้ง 17/17 กลุ่ม เก็บ volumes ทั้งสองชุดไว้ ไม่ลบข้อมูลหรือหยุดบริการของโปรเจกต์อื่น

## ข้อจำกัดและงานส่งต่อ

- ยังไม่มี Control API, project provisioning ผ่าน UI, platform authentication, CI หรือ Dashboard ที่เชื่อมข้อมูลจริง
- **ห้ามใช้ production:** HTTP/loopback, email auto-confirm และ shared DB password ระหว่างห้า service/owner logins ภายในแต่ละโปรเจกต์เป็นข้อจำกัดของ PoC ห้ามแจก DB credentials; ต้องแยก secret ต่อ role ก่อนเปิด SQL Editor/direct DB access
- Shared cluster ไม่แยก CPU/memory/disk, cluster catalogs หรือ failure domain; privileged-service compromise ยังไม่ได้ตรวจครบทุกช่องทาง
- ยังไม่ทดสอบ email verification/reset, full CRUD/pagination, public-bucket policy, file-size abuse, Realtime INSERT/DELETE/reconnect, token expiry/key rotation, restore, HA หรือ load/capacity ตามเป้าหมาย
- การสั่งหยุดชุด fresh พบ Realtime และ S3 exit 137 โดย Docker ระบุ `OOMKilled=false`; ยังไม่ผ่าน graceful-shutdown acceptance ต้องทบทวน stop grace period และทดสอบความคงทนของข้อมูลก่อน pilot
- API keys ของ PoC อายุ 30 วัน; ไม่มี rotation workflow การ logout ไม่รับรองการ revoke access JWT ที่ยังไม่หมดอายุทันที
- Inventory ไม่ใช่ SBOM/vulnerability audit; ต้องประเมินชุดเวอร์ชันและ LICENSE/NOTICE ก่อนเผยแพร่

ขั้นถัดไปคือ **Phase 1: repository/toolchain, FastAPI + React scaffold, health checks และ CI** โดยนำ bootstrap ที่พิสูจน์แล้วไปจัดระเบียบ แยก secrets ต่อ role และวาง regression tests ต่อเนื่อง ยังไม่เริ่มงาน Phase 1 ในรอบนี้
