# ADR 0003 — S3-compatible Storage โดยใช้ SeaweedFS สำหรับ PoC

วันที่ 13 กันยายน 2026 · สถานะ: ยอมรับสำหรับการทดสอบ local

## การตัดสินใจ

ใช้ Supabase Storage เก็บ metadata และบังคับ policy ใน PostgreSQL โดยเก็บ bytes ที่ SeaweedFS 4.46 ผ่าน S3 API แยก backend bucket และ scoped credential ต่อโปรเจกต์ ใช้ AWS S3 SDK ทดสอบ credential isolation โดยตรงนอก Storage API อีกชั้นหนึ่ง

เลือก SeaweedFS เพราะมี S3 interface และ source license Apache-2.0 ส่วน MinIO ที่เคยยกเป็นตัวเลือกใน roadmap มี source license AGPL-3.0 และ repository ปัจจุบันถูก archive จึงไม่เลือกเป็นฐาน local ใหม่ในแผนนี้ ([SeaweedFS release](https://github.com/seaweedfs/seaweedfs/releases/tag/4.46), [SeaweedFS license](https://github.com/seaweedfs/seaweedfs/blob/4.46/LICENSE), [MinIO repository/license](https://github.com/minio/minio/blob/master/LICENSE))

## ขอบเขต

PoC ใช้ single-node server mode มี volume เพียงพอสำหรับ internal metadata และสอง bucket ปิด telemetry และ endpoints ที่ไม่ใช้ ข้อมูลและ configuration อยู่เฉพาะเครื่องพัฒนา

การผ่าน upload/download และ signed URL ใน PoC ไม่ได้แปลว่า S3 feature ทุกอย่างรองรับ ก่อนเลือก backend สำหรับ production ต้องทดสอบ multipart/resumable upload, consistency, backup/restore, quota และอายุ version ของไฟล์

Staging เลือก SeaweedFS หรือ managed S3-compatible provider ได้โดยรักษา Storage API contract เดิม ต้องประเมินค่าใช้จ่ายจริงและ resource limits ใน Phase 5/8
