import { useEffect, useState } from 'react';
import { fetchOverview, type Overview, type Service } from './api';

const pages = [
    { id: 'overview', title: 'Overview', mark: '◫', phase: 1 },
    { id: 'database', title: 'Database', mark: '▤', phase: 4 },
    { id: 'authentication', title: 'Authentication', mark: '◎', phase: 3 },
    { id: 'storage', title: 'Storage', mark: '▱', phase: 5 },
    { id: 'realtime', title: 'Realtime', mark: 'ϟ', phase: 6 },
    { id: 'api', title: 'API Docs', mark: '⌘', phase: 1 },
    { id: 'settings', title: 'Settings', mark: '⚙', phase: 2 },
];

function Status({ service }: { service: Service }) {
    return (
        <span className={'status ' + service.status}>
            <span aria-hidden="true" className="dot" />
            {service.status === 'up' ? 'Operational' : 'Unavailable'}
        </span>
    );
}

export default function App() {
    const [page, setPage] = useState('overview');
    const [selected, setSelected] = useState('alpha');
    const [data, setData] = useState<Overview | null>(null);
    const [error, setError] = useState(false);
    const [loading, setLoading] = useState(true);
    const [refresh, setRefresh] = useState(0);
    useEffect(() => {
        const controller = new AbortController();
        let active = true;
        setLoading(true);
        setError(false);
        fetchOverview(controller.signal)
            .then((result) => {
                if (active) setData(result);
            })
            .catch(() => {
                if (active) setError(true);
            })
            .finally(() => {
                if (active) setLoading(false);
            });
        return () => {
            active = false;
            controller.abort();
        };
    }, [refresh]);
    const project = data?.projects.find((p) => p.ref === selected) ?? data?.projects[0];
    const current = pages.find((p) => p.id === page)!;
    const healthy = project?.services.filter((s) => s.status === 'up').length ?? 0;
    const stale = loading || error;

    return (
        <div className="shell">
            <a className="skip" href="#content">
                Skip to content
            </a>
            <aside>
                <a href="#content" className="brand" onClick={() => setPage('overview')}>
                    <span className="brand-icon">S</span> SiBase<span className="brand-dot">.</span>
                </a>
                <div className="workspace">
                    <span className="workspace-icon">IT</span>
                    <div>
                        Internal team<small>Local development</small>
                    </div>
                </div>
                <p className="nav-label">PROJECT</p>
                <nav aria-label="Main navigation">
                    {pages.map((item) => (
                        <button
                            key={item.id}
                            onClick={() => setPage(item.id)}
                            aria-current={page === item.id ? 'page' : undefined}
                        >
                            <span aria-hidden="true">{item.mark}</span>
                            {item.title}
                        </button>
                    ))}
                </nav>
                <div className="side-footer">
                    <span className="phase-label">PHASE 01</span>
                    <p>
                        A foundation for
                        <br />
                        your next internal app.
                    </p>
                    <small>Self-hosted · Local only</small>
                </div>
            </aside>
            <div className="workspace-main">
                <header>
                    <div className="breadcrumbs">
                        Internal team <span>/</span>
                        <label className="sr-only" htmlFor="project">
                            Project
                        </label>
                        <select
                            id="project"
                            value={project?.ref ?? ''}
                            disabled={!data?.projects.length || stale}
                            onChange={(e) => setSelected(e.target.value)}
                        >
                            {!data?.projects.length && <option value="">No projects</option>}
                            {data?.projects.map((p) => (
                                <option key={p.ref} value={p.ref}>
                                    {p.name}
                                </option>
                            ))}
                        </select>
                    </div>
                    <span className="local-badge">
                        <span className="dot" />
                        LOCAL
                    </span>
                    <span className="avatar" aria-label="Development environment">
                        SB
                    </span>
                </header>
                <main id="content">
                    <div className="page-heading">
                        <div>
                            <div className="eyebrow">PROJECT / {current.title.toUpperCase()}</div>
                            <h1>
                                {current.title === 'Overview' ? 'Project overview' : current.title}
                            </h1>
                            <p>พื้นที่พัฒนาแอปและระบบงานของทีม พร้อมบริการ backend ในที่เดียว</p>
                        </div>
                        <button
                            className="refresh"
                            disabled={loading}
                            onClick={() => setRefresh((v) => v + 1)}
                        >
                            {loading ? 'Checking…' : '↻  Refresh status'}
                        </button>
                    </div>
                    <div className="notice">
                        <span aria-hidden="true">ⓘ</span>
                        <p>
                            <strong>Development foundation</strong> —
                            แสดงสถานะบริการจริงแบบอ่านอย่างเดียว
                            ยังไม่มีระบบสมาชิกหรือสร้างโปรเจกต์ผ่าน Dashboard
                        </p>
                    </div>
                    {error && (
                        <div role="alert" className="error">
                            <strong>เชื่อมต่อ Control API ไม่ได้</strong>
                            <p>
                                ตรวจว่า backend เปิดอยู่ แล้วลอง Refresh status อีกครั้ง ข้อมูลเดิม
                                (ถ้ามี) ยังไม่ได้รับการยืนยัน
                            </p>
                        </div>
                    )}
                    {loading && (
                        <p role="status" className="muted">
                            กำลังตรวจสอบสถานะบริการ…
                        </p>
                    )}
                    {data && page === 'overview' && (
                        <div className={stale ? 'stale' : ''} aria-busy={loading}>
                            <section className="metrics" aria-label="Project summary">
                                <article>
                                    <span className="metric-label">PROJECT REFERENCE</span>
                                    <strong className="mono">{project?.ref ?? '—'}</strong>
                                    <small>Fixed local project · Phase 1</small>
                                </article>
                                <article>
                                    <span className="metric-label">SERVICES AVAILABLE</span>
                                    <strong>
                                        {healthy}
                                        <em> / {project?.services.length ?? 0}</em>
                                    </strong>
                                    <small>
                                        {stale
                                            ? 'Status awaiting verification'
                                            : project?.status === 'healthy'
                                              ? 'All project probes succeeded'
                                              : 'Some services need attention'}
                                    </small>
                                </article>
                                <article>
                                    <span className="metric-label">PLATFORM DATABASE</span>
                                    <strong className="metric-status">
                                        {data.platform.status === 'up'
                                            ? 'Connected'
                                            : 'Unavailable'}
                                    </strong>
                                    <small>Separate control-plane database</small>
                                </article>
                            </section>
                            <section className="panel">
                                <div className="panel-heading">
                                    <div>
                                        <h2>Service health</h2>
                                        <p>
                                            Live availability checks · ไม่ใช่ผล load test หรือ SLA
                                        </p>
                                    </div>
                                    <span
                                        className={
                                            'health-label ' +
                                            (project?.status === 'healthy' ? '' : 'warn')
                                        }
                                    >
                                        {stale
                                            ? 'Unverified'
                                            : project?.status === 'healthy'
                                              ? 'All systems operational'
                                              : 'Needs attention'}
                                    </span>
                                </div>
                                {!project && (
                                    <p className="empty">ยังไม่มีโปรเจกต์ใน configuration</p>
                                )}
                                {project?.services.map((service, i) => (
                                    <div className="service-row" key={service.id}>
                                        <span className="service-icon" aria-hidden="true">
                                            {['▤', '◎', '⌘', '▱', 'ϟ'][i]}
                                        </span>
                                        <div className="service-name">
                                            <strong>{service.name}</strong>
                                            <small>{service.detail}</small>
                                        </div>
                                        <code>{service.latency_ms} ms</code>
                                        <Status service={service} />
                                    </div>
                                ))}
                                <div className="panel-footer">
                                    Last checked{' '}
                                    <time>{new Date(data.checked_at).toLocaleString()}</time>
                                    <span>Probe latency, not request performance</span>
                                </div>
                            </section>
                            <div className="bottom-grid">
                                <section className="panel connection">
                                    <span className="eyebrow">CONNECT YOUR APPLICATION</span>
                                    <h2>Your project endpoint</h2>
                                    <p>Endpoint สำหรับ Auth, REST, Storage และ Realtime</p>
                                    <code>{project?.endpoint ?? 'No project configured'}</code>
                                    <button className="text-button" onClick={() => setPage('api')}>
                                        Explore API documentation <span>↗</span>
                                    </button>
                                </section>
                                <section className="panel next">
                                    <span className="eyebrow">WHAT’S NEXT</span>
                                    <h2>From local stack to workspace</h2>
                                    <p>
                                        Phase 2 จะเพิ่มสมาชิกทีมและการสร้างโปรเจกต์ พร้อมสถานะ
                                        provisioning และสิทธิ์การจัดการ
                                    </p>
                                    <span className="future">PLANNED · PHASE 02</span>
                                </section>
                            </div>
                        </div>
                    )}
                    {page === 'api' && (
                        <section className="panel docs">
                            <span className="eyebrow">CONTROL PLANE / READ ONLY</span>
                            <h2>API reference</h2>
                            <p>
                                เปิดเอกสารของ FastAPI เพื่อดู response schema และทดลอง health
                                endpoints
                            </p>
                            <a
                                className="primary-link"
                                href="/api/docs"
                                target="_blank"
                                rel="noreferrer"
                            >
                                Open Control API docs ↗
                            </a>
                            <pre>
                                {
                                    'GET /api/v1/overview\nGET /api/v1/health\nGET /health/live\nGET /health/ready'
                                }
                            </pre>
                            <p className="muted">
                                บัญชีแพลตฟอร์มและ key management ยังไม่พร้อมใช้งาน
                                ห้ามเปิดพอร์ตนี้สู่เครือข่ายภายนอก
                            </p>
                        </section>
                    )}
                    {!['overview', 'api'].includes(page) && (
                        <section className="panel upcoming">
                            <div className="upcoming-icon" aria-hidden="true">
                                {current.mark}
                            </div>
                            <span className="eyebrow">PLANNED · PHASE {current.phase}</span>
                            <h2>{current.title} is on the roadmap</h2>
                            <p>
                                หน้านี้เป็นโครง navigation ยังไม่เชื่อมการจัดการข้อมูลจริง
                                <br />
                                กลับไป Overview เพื่อตรวจสถานะบริการที่เปิดใช้งานแล้ว
                            </p>
                            <button className="refresh" onClick={() => setPage('overview')}>
                                Back to overview
                            </button>
                        </section>
                    )}
                    <footer>
                        SiBase Studio <span>Phase 1 · Internal development environment</span>
                    </footer>
                </main>
            </div>
        </div>
    );
}
