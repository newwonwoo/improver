import { useState } from "react";
import { RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, Radar, ResponsiveContainer } from "recharts";
import { ChevronDown, ChevronRight, Clock, ExternalLink, CheckSquare, Building2 } from "lucide-react";

/* ── 실제 스캔 결과 (scanner.py → 주택도시기금법_scan.json에서 추출) ── */
const SCAN = {
  law: "주택도시기금법", grade: "심각", score: 83.1,
  articles: 43, findings: 35, cited: 41,
  enacted: "2015-01-06", amended: "2025-12-02", effective: "2026-03-03",
  cats: {
    "구조": { crd: 181.4, cnt: 14 },
    "공정성": { crd: 151.2, cnt: 8 },
    "적법성": { crd: 65.1, cnt: 4 },
    "거버넌스": { crd: 111.6, cnt: 6 },
    "효율성": { crd: 41.9, cnt: 3 },
  },
};

const ISSUES = [
  { id: 1, sev: "심각", cat: "거버넌스", art: "제31조", title: "감독 항목·주기·방법·공개·시정권 — 5가지 모두 없음",
    what: "국토교통부장관이 기금을 '감독한다'는 한 줄만 있습니다. 뭘 보는지, 얼마나 자주 보는지, 결과를 어디에 공개하는지, 문제가 있으면 어떻게 시정하는지 — 전부 비어 있습니다.",
    sub: ["감독 범위 ✗", "감독 주기 ✗", "감독 방법 ✗", "결과 공개 ✗", "시정 명령권 ✗"],
    cases: [
      { ag: "감사원", dt: "2024.8.13", tg: "국토교통부", rs: "시정 요구", desc: "HUG가 전세보증 한도 하향을 16차례 요청했으나 국토부가 2년간 방치. 전세사기 피해 확대의 직접 원인으로 지목", url: "https://www.economidaily.com/view/20240813162350756" },
      { ag: "국회 국감", dt: "2024.10", tg: "국토부·HUG", rs: "전방위 제도개선 요구", desc: "국토위원장이 '종감까지 대책 안 나오면 국회에서 추가 조치'라고 경고", url: "https://www.sisaweek.com/news/articleView.html?idxno=218859" },
    ]},
  { id: 2, sev: "심각", cat: "거버넌스", art: "법령 전체", title: "내부통제 5대 요소가 모두 빠져 있음",
    what: "기금 수탁기관에 '업무지침을 정하라'고만 되어 있습니다. 감사원이 내부통제 기준으로 보는 5가지(윤리기준, 위험평가, 승인절차, 보고체계, 자체점검) 중 아무것도 법에 없습니다.",
    sub: ["통제환경 ✗", "위험평가 ✗", "통제활동 ✗", "정보소통 ✗", "모니터링 ✗"],
    cases: [
      { ag: "감사원", dt: "2024.8", tg: "HUG", rs: "위험관리체계 미흡", desc: "담보인정비율 100%로 올린 후 대위변제액이 2017년 34억→2024년 4조 4,896억으로 폭증", url: "https://www.khan.co.kr/article/202510091436001" },
      { ag: "국회 국감", dt: "2024.10", tg: "HUG", rs: "감정평가 부실 추궁", desc: "감정평가 부실로 인한 보증사고가 전체의 42.8%. '관리 책임은 HUG'라고 질의", url: "https://www.sisaweek.com/news/articleView.html?idxno=218859" },
    ]},
  { id: 3, sev: "심각", cat: "공정성", art: "제10·32·34조의2", title: "'필요하다고 인정하면' 아무 기준 없이 재량 행사 가능 (3건)",
    what: "장관이나 공사가 '필요하다고 인정하는 경우'에 할 수 있다고만 되어 있고, 구체적으로 어떤 상황인지 기준이 없습니다. 3개 조문에서 동일 패턴이 반복됩니다.",
    sub: ["제10조 — 기금 운용 변경 재량", "제32조 — 보증공사 업무 재량", "제34조의2 — 추가 재량"],
    cases: [
      { ag: "감사원", dt: "2024.8.13", tg: "국토교통부", rs: "감독 소홀", desc: "기준 없는 재량이 '아무것도 안 해도 위법이 아닌' 상황을 만들었다는 지적", url: "https://www.economidaily.com/view/20240813162350756" },
    ]},
  { id: 4, sev: "심각", cat: "구조", art: "법령 전체", title: "법 구조가 누더기 — 삽입조 7개, 깊이 7단계",
    what: "제28조의2, 제34조의2~7 등 나중에 끼워넣은 조문이 7개이고, 가장 깊은 건 '제34조의7'입니다. 법 전체를 다시 정리할 필요가 있습니다.",
    sub: ["삽입조 비율 16%", "최대 깊이 7 (제34조의7)"],
    cases: []},
  { id: 5, sev: "경고", cat: "거버넌스", art: "제10·13·15·34조", title: "보고 의무는 있지만 주기·양식·방법·제재가 전부 빠짐 (4건)",
    what: "'보고하여야 한다' '제출하여야 한다'라고만 되어 있고, 언제(주기), 어떤 양식으로, 어떻게(전자/서면), 안 하면 어떻게 되는지(제재)가 전부 빠져 있습니다.",
    sub: ["제10조 — 0/4 충족", "제13조 — 0/4 충족", "제15조 — 0/4 충족", "제34조 — 0/4 충족"],
    cases: []},
  { id: 6, sev: "경고", cat: "공정성", art: "제13·25·33·34조의2·34조의7", title: "권리를 제한하면서 이의제기·청문 등 구제수단이 없음 (5건)",
    what: "'할 수 없다' '아니 된다'로 국민의 권리를 제한하는데, 같은 조문이나 근처에 이의신청·청문·소명 기회가 규정되어 있지 않습니다.",
    sub: ["제13조", "제25조", "제33조", "제34조의2", "제34조의7"],
    cases: []},
  { id: 7, sev: "경고", cat: "적법성", art: "제2·5·9·33조", title: "하나의 조문에 5개 이상 다른 법률을 인용 — 읽기 어려움 (4건)",
    what: "제9조는 한 조문에서 14개 법률을 인용합니다. 이 정도면 해당 조문만 읽어서는 내용을 이해할 수 없습니다.",
    sub: ["제2조 — 5개 법률", "제5조 — 6개 법률", "제9조 — 14개 법률", "제33조 — 9개 법률"],
    cases: []},
  { id: 8, sev: "경고", cat: "구조", art: "제5·6·9·32·33·34조", title: "'필요하다고 인정' '그 밖에' 등 모호 표현이 의무 조항에 반복 (6건)",
    what: "핵심 의무를 정하는 조문에 '필요한 경우' '그 밖에' 같은 표현이 들어 있어서, 실제로 무엇을 해야 하는지 불명확합니다.",
    sub: ["제32조 — 3개 모호 표현 (심각)", "제34조 — 2개 (심각)", "제5·6·9·33조 — 각 2개 (경고)"],
    cases: []},
];

const CHECKLIST = [
  "수탁기관 내부통제기준서 신규 작성 (감사원 5대 요소 반영)",
  "감독 규정에 범위·주기·방법·결과공개·시정권 명시",
  "보고 규정에 주기(분기)·양식·전자적 방법·미보고 시 제재 추가",
  "제10·32·34조의2 재량 조항에 발동 요건 열거 (다음 각 호)",
  "권리 제한 조항(5건)에 이의제기·청문·소명 절차 추가",
  "제9조 등 과다 인용 조문은 별도 표로 분리하여 가독성 확보",
  "삽입조 7개를 포함하여 법령 전체 조문번호 재정리 검토",
];

const SEV = {
  "심각": { bg: "#fef2f2", bd: "#fca5a5", tx: "#991b1b", dot: "#dc2626" },
  "경고": { bg: "#fffbeb", bd: "#fde68a", tx: "#92400e", dot: "#f59e0b" },
  "주의": { bg: "#eff6ff", bd: "#bfdbfe", tx: "#1e40af", dot: "#3b82f6" },
  "개선": { bg: "#f9fafb", bd: "#d1d5db", tx: "#4b5563", dot: "#9ca3af" },
};

const TABS = ["종합", "문제점", "일정", "전체"];
const RADAR = Object.entries(SCAN.cats).map(([k, v]) => ({ axis: k, value: Math.min(v.crd, 200), cnt: v.cnt }));

export default function Report() {
  const [tab, setTab] = useState("종합");
  const [open, setOpen] = useState(null);
  const toggle = id => setOpen(open === id ? null : id);

  return (
    <div style={{ background: "#f8f9fb", minHeight: "100vh", fontFamily: "'Pretendard','Noto Sans KR',sans-serif", color: "#1a1a2e" }}>
      <link href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css" rel="stylesheet" />

      {/* 표지 */}
      <header style={{ background: "linear-gradient(135deg,#1e293b,#0f172a)", color: "#fff", padding: "32px 24px 28px" }}>
        <div style={{ fontSize: 11, color: "#94a3b8", letterSpacing: 1.5, marginBottom: 4 }}>규정 진단 리포트</div>
        <h1 style={{ fontSize: 22, fontWeight: 800, margin: "0 0 6px" }}>「{SCAN.law}」</h1>
        <div style={{ fontSize: 12, color: "#94a3b8" }}>법률 · 시행 {SCAN.effective} · 최종 개정 {SCAN.amended} · 총 {SCAN.articles}개 조문</div>
        <div style={{ display: "flex", alignItems: "center", gap: 14, marginTop: 16, padding: "14px 16px", background: "rgba(220,38,38,0.12)", borderRadius: 10, border: "1px solid rgba(220,38,38,0.3)" }}>
          <span style={{ fontSize: 36, fontWeight: 900, color: "#ef4444", lineHeight: 1 }}>심각</span>
          <div>
            <div style={{ fontSize: 13, fontWeight: 600, color: "#fca5a5" }}>{SCAN.score}점 · 발견 {SCAN.findings}건</div>
            <div style={{ fontSize: 11, color: "#a8a29e", marginTop: 2 }}>심각 {ISSUES.filter(i => i.sev === "심각").length} · 경고 {ISSUES.filter(i => i.sev === "경고").length} · 인용 법령 {SCAN.cited}개</div>
          </div>
        </div>
      </header>

      {/* 탭 */}
      <nav style={{ background: "#fff", borderBottom: "1px solid #e5e7eb", display: "flex", position: "sticky", top: 0, zIndex: 10 }}>
        {TABS.map(t => (
          <button key={t} onClick={() => setTab(t)} style={{ flex: 1, background: "none", border: "none", padding: "11px 6px", fontSize: 13, fontWeight: tab === t ? 700 : 400, color: tab === t ? "#1e293b" : "#94a3b8", borderBottom: tab === t ? "2px solid #1e293b" : "2px solid transparent", cursor: "pointer" }}>{t}</button>
        ))}
      </nav>

      <main style={{ padding: "16px 16px 40px", maxWidth: 640, margin: "0 auto" }}>

        {/* ── 종합 ── */}
        {tab === "종합" && <>
          <div style={{ background: "#fff", borderRadius: 12, padding: 18, marginBottom: 14, border: "1px solid #e5e7eb" }}>
            <h2 style={{ fontSize: 15, fontWeight: 700, margin: "0 0 10px" }}>한 줄 요약</h2>
            <p style={{ fontSize: 13, lineHeight: 1.8, margin: 0, color: "#374151" }}>
              이 법은 <b>기금 관리·감독 체계가 거의 비어 있습니다.</b> 100조원이 넘는 기금인데
              내부통제 기준·감독 항목·보고 주기가 모두 미비합니다.
              <b style={{ color: "#dc2626" }}> 2024년 감사원이 국토부의 기금 감독 소홀을 직접 지적했고,
              같은 해 국정감사에서는 HUG 미회수금 6조원이 추궁되었습니다.</b>
            </p>
          </div>

          {/* 레이더 */}
          <div style={{ background: "#fff", borderRadius: 12, padding: 18, marginBottom: 14, border: "1px solid #e5e7eb" }}>
            <h2 style={{ fontSize: 15, fontWeight: 700, margin: "0 0 2px" }}>카테고리별 위험도</h2>
            <p style={{ fontSize: 11, color: "#94a3b8", margin: "0 0 6px" }}>수치가 높을수록 문제가 많습니다</p>
            <ResponsiveContainer width="100%" height={220}>
              <RadarChart data={RADAR}>
                <PolarGrid stroke="#e5e7eb" />
                <PolarAngleAxis dataKey="axis" tick={{ fill: "#64748b", fontSize: 12 }} />
                <PolarRadiusAxis angle={90} domain={[0, 200]} tick={false} />
                <Radar dataKey="value" stroke="#dc2626" fill="#dc2626" fillOpacity={0.12} strokeWidth={2} dot={{ fill: "#dc2626", r: 3 }} />
              </RadarChart>
            </ResponsiveContainer>
            {Object.entries(SCAN.cats).map(([c, v]) => (
              <div key={c} style={{ display: "flex", justifyContent: "space-between", fontSize: 12, padding: "4px 0", borderBottom: "1px solid #f1f5f9" }}>
                <span style={{ color: "#475569" }}>{c}</span>
                <span style={{ color: v.crd >= 100 ? "#dc2626" : v.crd >= 50 ? "#f59e0b" : "#16a34a", fontWeight: 600 }}>{v.cnt}건</span>
              </div>
            ))}
          </div>

          <button onClick={() => setTab("문제점")} style={{ width: "100%", padding: 12, background: "#1e293b", color: "#fff", border: "none", borderRadius: 8, fontSize: 14, fontWeight: 600, cursor: "pointer" }}>
            문제점 상세 보기 →
          </button>
        </>}

        {/* ── 문제점 ── */}
        {tab === "문제점" && <>
          <h2 style={{ fontSize: 15, fontWeight: 700, margin: "0 0 14px" }}>주요 문제점 {ISSUES.length}건</h2>
          {ISSUES.map(issue => {
            const S = SEV[issue.sev];
            const isOpen = open === issue.id;
            return (
              <div key={issue.id} style={{ background: "#fff", borderRadius: 12, marginBottom: 10, border: `1px solid ${S.bd}`, overflow: "hidden" }}>
                <button onClick={() => toggle(issue.id)} style={{ width: "100%", background: "none", border: "none", padding: "14px 16px", cursor: "pointer", textAlign: "left" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
                    <span style={{ width: 7, height: 7, borderRadius: "50%", background: S.dot, flexShrink: 0 }} />
                    <span style={{ fontSize: 11, color: S.tx, fontWeight: 600 }}>{issue.sev}</span>
                    <span style={{ fontSize: 11, color: "#94a3b8" }}>{issue.cat} · {issue.art}</span>
                    {isOpen ? <ChevronDown size={14} color="#94a3b8" style={{ marginLeft: "auto" }} /> : <ChevronRight size={14} color="#94a3b8" style={{ marginLeft: "auto" }} />}
                  </div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: "#1e293b", lineHeight: 1.4 }}>{issue.title}</div>
                </button>

                {isOpen && (
                  <div style={{ padding: "0 16px 16px", borderTop: `1px solid ${S.bd}` }}>
                    <p style={{ fontSize: 13, lineHeight: 1.7, color: "#374151", margin: "12px 0" }}>{issue.what}</p>

                    {/* 서브체크 */}
                    <div style={{ background: S.bg, borderRadius: 8, padding: 12, marginBottom: 12 }}>
                      <div style={{ fontSize: 11, fontWeight: 700, color: S.tx, marginBottom: 6 }}>점검 항목</div>
                      {issue.sub.map((s, i) => (
                        <div key={i} style={{ fontSize: 12, color: "#475569", padding: "2px 0" }}>• {s}</div>
                      ))}
                    </div>

                    {/* 제재 사례 */}
                    {issue.cases.length > 0 && (
                      <div>
                        <div style={{ fontSize: 11, fontWeight: 700, color: "#64748b", marginBottom: 6 }}>실제 제재 사례</div>
                        {issue.cases.map((c, i) => (
                          <div key={i} style={{ background: "#fefce8", border: "1px solid #fde68a", borderRadius: 8, padding: 12, marginBottom: 6, fontSize: 12, lineHeight: 1.7 }}>
                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 4 }}>
                              <b style={{ color: "#92400e" }}><Building2 size={11} style={{ verticalAlign: "middle", marginRight: 3 }} />{c.ag}</b>
                              <span style={{ color: "#dc2626", fontWeight: 600, fontSize: 10, background: "#fef2f2", padding: "1px 6px", borderRadius: 3, whiteSpace: "nowrap" }}>{c.rs}</span>
                            </div>
                            <div style={{ color: "#78716c", fontSize: 10 }}>{c.dt} · {c.tg}</div>
                            <div style={{ color: "#374151", marginTop: 3 }}>{c.desc}</div>
                            <a href={c.url} target="_blank" rel="noopener noreferrer" style={{ color: "#92400e", fontSize: 10, textDecoration: "underline", marginTop: 4, display: "inline-block" }}>
                              <ExternalLink size={10} style={{ verticalAlign: "middle", marginRight: 2 }} />출처
                            </a>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </>}

        {/* ── 일정 ── */}
        {tab === "일정" && <>
          <h2 style={{ fontSize: 15, fontWeight: 700, margin: "0 0 14px" }}>개선 일정</h2>
          {[
            { ph: "30일", sev: "심각", color: "#dc2626", ids: [1, 2, 3, 4] },
            { ph: "90일", sev: "경고", color: "#f59e0b", ids: [5, 6, 7, 8] },
          ].map((p, pi) => (
            <div key={pi} style={{ position: "relative", paddingLeft: 24, marginBottom: 20 }}>
              {pi < 1 && <div style={{ position: "absolute", left: 8, top: 24, bottom: -20, width: 2, background: "#e5e7eb" }} />}
              <div style={{ position: "absolute", left: 0, top: 3, width: 18, height: 18, borderRadius: "50%", background: `${p.color}15`, border: `2px solid ${p.color}`, display: "flex", alignItems: "center", justifyContent: "center" }}>
                <div style={{ width: 6, height: 6, borderRadius: "50%", background: p.color }} />
              </div>
              <div style={{ background: "#fff", borderRadius: 12, border: "1px solid #e5e7eb", padding: 14, borderLeft: `3px solid ${p.color}` }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: p.color, marginBottom: 8 }}>
                  <Clock size={13} style={{ verticalAlign: "middle", marginRight: 4 }} />
                  {p.ph} 이내 — {p.sev} 개선
                </div>
                {p.ids.map(id => {
                  const issue = ISSUES.find(i => i.id === id);
                  return (
                    <div key={id} style={{ fontSize: 12, color: "#374151", padding: "4px 0", borderTop: id !== p.ids[0] ? "1px solid #f1f5f9" : "none" }}>
                      <b>{issue.art}</b> {issue.title.split("—")[0]}
                    </div>
                  );
                })}
              </div>
            </div>
          ))}

          {/* 체크리스트 */}
          <div style={{ background: "#fff", borderRadius: 12, border: "1px solid #e5e7eb", padding: 16, marginTop: 8 }}>
            <h3 style={{ fontSize: 14, fontWeight: 700, margin: "0 0 10px" }}>
              <CheckSquare size={14} style={{ verticalAlign: "middle", marginRight: 4 }} />
              사내규정 반영 체크리스트
            </h3>
            {CHECKLIST.map((item, i) => (
              <div key={i} style={{ fontSize: 12, color: "#475569", padding: "5px 0", display: "flex", gap: 6, borderBottom: "1px solid #f8f9fb" }}>
                <span style={{ color: "#d1d5db" }}>□</span> {item}
              </div>
            ))}
          </div>
        </>}

        {/* ── 전체 ── */}
        {tab === "전체" && <>
          <h2 style={{ fontSize: 15, fontWeight: 700, margin: "0 0 14px" }}>전체 {ISSUES.length}건</h2>
          <div style={{ background: "#fff", borderRadius: 12, border: "1px solid #e5e7eb", overflow: "hidden" }}>
            {ISSUES.map((issue, i) => {
              const S = SEV[issue.sev];
              return (
                <div key={issue.id} style={{ padding: "12px 14px", borderBottom: i < ISSUES.length - 1 ? "1px solid #f1f5f9" : "none", cursor: "pointer" }} onClick={() => { setOpen(issue.id); setTab("문제점"); }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 3 }}>
                    <span style={{ width: 7, height: 7, borderRadius: "50%", background: S.dot }} />
                    <span style={{ fontSize: 11, fontWeight: 600, color: S.tx }}>{issue.sev}</span>
                    <span style={{ fontSize: 11, color: "#94a3b8" }}>{issue.cat} · {issue.art}</span>
                    {issue.cases.length > 0 && <span style={{ fontSize: 9, color: "#92400e", background: "#fef3c7", padding: "1px 4px", borderRadius: 3 }}>사례{issue.cases.length}</span>}
                  </div>
                  <div style={{ fontSize: 12, color: "#374151" }}>{issue.title}</div>
                </div>
              );
            })}
          </div>
          <div style={{ marginTop: 12, padding: 12, background: "#f8f9fb", borderRadius: 8, fontSize: 11, color: "#94a3b8", lineHeight: 1.6 }}>
            본 리포트는 legalize-kr 레포의 법률 원문(1,051줄)을 scanner.py(22패턴)로 분석한 결과입니다.
            판례·유권해석·실무관행은 별도 검토가 필요합니다.
          </div>
        </>}
      </main>
    </div>
  );
}
