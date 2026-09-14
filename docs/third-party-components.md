# Third-party Components — Phase 0–3

ตรวจ source/version วันที่ 12–13 กันยายน 2026 ตารางนี้เป็น inventory ของ upstream หลัก ไม่ใช่ SBOM ครบทุก package ใน container

| Component | Version pin | Source license / อ้างอิง |
| --- | --- | --- |
| PostgreSQL | 17.6 / `postgres:17.6-bookworm` | [PostgreSQL License](https://www.postgresql.org/about/licence/) |
| wal2json | `postgresql-17-wal2json` 2.6-4.pgdg12+1 | [BSD-3-Clause](https://github.com/eulerto/wal2json/blob/master/LICENSE) |
| PostgREST | v14.17 | [MIT](https://github.com/PostgREST/postgrest/blob/v14.17/LICENSE) |
| Supabase Auth | v2.196.0 | [MIT](https://github.com/supabase/auth/blob/v2.196.0/LICENSE) |
| Supabase Storage | v1.74.0 | [Apache-2.0](https://github.com/supabase/storage/blob/v1.74.0/LICENSE) |
| Supabase Realtime | v2.134.10 | [Apache-2.0](https://github.com/supabase/realtime/blob/v2.134.10/LICENSE) |
| SeaweedFS | 4.46 | [Apache-2.0](https://github.com/seaweedfs/seaweedfs/blob/4.46/LICENSE) |
| Nginx | 1.28.0-alpine | [BSD-2-Clause](https://nginx.org/LICENSE) |
| Node.js | 22.23.2-alpine | [MIT + bundled notices](https://github.com/nodejs/node/blob/v22.23.2/LICENSE) |
| Supabase JS | 2.116.0 | [MIT](https://github.com/supabase/supabase-js/blob/master/LICENSE) |
| AWS SDK for S3 | 3.883.0 | [Apache-2.0](https://github.com/aws/aws-sdk-js-v3/blob/main/LICENSE) |
| node-postgres | 8.16.3 | [MIT](https://github.com/brianc/node-postgres/blob/master/LICENSE) |

Npm dependencies และ transitive dependencies ถูก lock ใน [package-lock.json](../poc/phase0/package-lock.json) ส่วน Docker images pin ทั้ง tag และ digest ใน [images.lock.json](../poc/phase0/images.lock.json) และ [PostgreSQL Dockerfile](../poc/phase0/postgres.Dockerfile) ผลทดสอบชุดนี้อยู่ใน [รายงาน Phase 0](phase0-report.md); เป็นชุดที่ตรวจร่วมกัน ไม่ใช่คำรับรองว่าเป็นเวอร์ชันล่าสุดหรือผ่าน vulnerability audit แล้ว

ก่อนเผยแพร่ distribution ของ SiBase ให้สร้าง SBOM, เก็บ LICENSE/NOTICE ที่เกี่ยวข้องกับชุดที่แจกจ่าย และตรวจ dependency/security updates ตามเวอร์ชันนั้น เงื่อนไขของ source repository ไม่ได้แทนเงื่อนไขทุก dependency ที่รวมอยู่ใน image

## Phase 1 application toolchain

เพิ่มเติมจาก data-plane pins เดิม โดยระบุเวอร์ชันที่ติดตั้งและทดสอบใน repository ไม่ใช่การรับรองว่าเป็นรุ่นล่าสุด:

| Component | Version pin |
| --- | --- |
| Python container | 3.13.7-slim-bookworm + digest ใน `infra/api.Dockerfile` |
| FastAPI / Uvicorn | 0.141.1 / 0.52.4 |
| SQLAlchemy / Alembic / Psycopg | 2.0.52 / 1.20.0 / 3.3.5 |
| React / Vite / TypeScript | 19.3.0 / 8.3.0 / 5.9.3 |
| pytest / Vitest | 9.1.1 / 5.0.0 |
| Ruff / ESLint | 0.16.7 / 10.10.0 |

Python dependencies พร้อม hashes อยู่ใน [requirements.lock](../requirements.lock) และ [requirements-dev.lock](../requirements-dev.lock); frontend อยู่ใน [package-lock.json](../src/dashboard/package-lock.json) การตรวจ licenses/transitive notices และ security audit ครบชุดยังเป็นงานก่อนเผยแพร่

ยังไม่กำหนด license สำหรับโค้ด SiBase; ให้เจ้าของโครงการกำหนดก่อนเผยแพร่ source/package สู่ภายนอก

## Phase 3 local email testing

ใช้ Mailpit `v1.31.1` image digest `sha256:98b916bd3c8d61f7633a52d3ea2f58d00620cb01ca57ab59edde68c347a95365` โดย pin ใน `scripts/phase2.py` ตรวจและทดสอบ local วันที่ 14 กันยายน 2026 ดู [official Docker configuration](https://mailpit.axllent.org/docs/install/docker/) เพิ่ม component นี้ใน SBOM/license/security review ก่อนแจกจ่าย; ไม่ใช่ production mail delivery service
