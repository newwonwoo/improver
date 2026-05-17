import { useMemo, useState } from "react";
import {
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
  ResponsiveContainer,
} from "recharts";
import {
  ChevronDown,
  ChevronRight,
  Building2,
  CheckSquare,
  Clock,
  ExternalLink,
} from "lucide-react";

/* engine/schema.py AnalysisResult JSON에 직접 바인딩.
   P-01~P-10 (gap_analysis §3 패턴 규칙) 적용. */

const SEV = {
  심각: { bg: "#fef2f2", bd: "#fca5a5", tx: "#991b1b", dot: "#dc2626", chip: "심각" },
  경고: { bg: "#fffbeb", bd: "#fde68a", tx: "#92400e", dot: "#f59e0b", chip: "경고" },
  주의: { bg: "#eff6ff", bd: "#bfdbfe", tx: "#1e40af", dot: "#3b82f6", chip: "주의" },
  개선: { bg: "#f9fafb", bd: "#d1d5db", tx: "#4b5563", dot: "#9ca3af", chip: "개선" },
  양호: { bg: "#f0fdf4", bd: "#bbf7d0", tx: "#166534", dot: "#22c55e", chip: "양호" },
};

const FIX_ICONS = {
  delete: { icon: "✂️", label: "문제 표현 삭제" },
  replace: { icon: "🔄", label: "대체 문구로 교체" },
  proviso: { icon: "📎", label: "단서 조항 추가" },
  add_paragraph: { icon: "➕", label: "새 항 신설" },
  sub_legislation: { icon: "📋", label: "시행령·고시로 보완" },
};

const CATEGORY_ORDER = ["구조", "공정성", "적법성", "거버넌스", "효율성"];

function Badge({ severity }) {
  const s = SEV[severity] || SEV["개선"];
  return (
    <span
      style={{
        display: "inline-block",
        padding: "2px 8px",
        background: s.bg,
        border: `1px solid ${s.bd}`,
        color: s.tx,
        borderRadius: 4,
        fontSize: 11,
        fontWeight: 600,
      }}
    >
      {s.chip}
    </span>
  );
}

function StatCard({ label, value, hint }) {
  /* P-01: 라벨은 "~가 ~이다" 평서문, 전문 용어 금지 */
  return (
    <div
      style={{
        background: "#fff",
        border: "1px solid #e5e7eb",
        borderRadius: 8,
        padding: 14,
      }}
    >
      <div style={{ fontSize: 11, color: "#6b7280" }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 800, marginTop: 6 }}>{value}</div>
      {hint && (
        <div style={{ fontSize: 11, color: "#9ca3af", marginTop: 4 }}>{hint}</div>
      )}
    </div>
  );
}

function CategoryAccordion({ title, items, color }) {
  /* P-02: 카테고리는 이름+건수+최고등급색상 헤더, 상세는 접이식 */
  const [open, setOpen] = useState(false);
  const maxSev = items.length
    ? items.reduce((acc, f) => {
        const order = ["양호", "개선", "주의", "경고", "심각"];
        return order.indexOf(f.severity) > order.indexOf(acc) ? f.severity : acc;
      }, "양호")
    : "양호";
  const s = SEV[maxSev];
  return (
    <div
      style={{
        border: `1px solid ${s.bd}`,
        borderRadius: 8,
        marginBottom: 8,
        overflow: "hidden",
      }}
    >
      <button
        onClick={() => setOpen(!open)}
        style={{
          width: "100%",
          padding: "10px 14px",
          background: s.bg,
          border: "none",
          color: s.tx,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          cursor: "pointer",
          fontWeight: 700,
          fontSize: 13,
        }}
      >
        <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          {title}
        </span>
        <span style={{ fontSize: 12 }}>
          {items.length}건 · 최고 {maxSev}
        </span>
      </button>
      {open && (
        <div style={{ background: "#fff", padding: 12 }}>
          {items.length === 0 ? (
            <div style={{ fontSize: 12, color: "#9ca3af" }}>이슈 없음</div>
          ) : (
            items.map((f) => <FindingCard key={f.finding_id} f={f} />)
          )}
        </div>
      )}
    </div>
  );
}

function FindingCard({ f, sameArticleCount = 0 }) {
  /* P-03 교차 패턴 / P-04 위임 첫 문장 / P-06 기관 근거 / P-08 수정 유형 아이콘 */
  const s = SEV[f.severity];
  const fix = FIX_ICONS[f.fix_type] || null;
  const rec = f.recommendation || {};
  let firstSentence = rec.contextual || rec.template || f.summary;
  if (f.pattern_id === "S-02" && firstSentence && !firstSentence.startsWith("위임 자체")) {
    /* P-04: 위임 이슈 첫 문장 고정 */
    firstSentence = `위임 자체는 정상입니다. 문제는 시행령이 해당 사항을 빠뜨린 것입니다. ${firstSentence}`;
  }
  return (
    <div
      style={{
        padding: 10,
        marginBottom: 8,
        border: "1px solid #e5e7eb",
        borderRadius: 6,
        background: "#fff",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <Badge severity={f.severity} />
        <span style={{ fontWeight: 700 }}>{f.article_number}</span>
        <span style={{ fontSize: 11, color: "#6b7280" }}>
          {f.pattern_id} {f.pattern_name}
        </span>
        {fix && (
          <span style={{ fontSize: 11, color: "#4b5563" }}>
            {fix.icon} {fix.label}
          </span>
        )}
        {sameArticleCount > 1 && (
          <span style={{ fontSize: 11, color: "#b45309" }}>
            🔗 이 조문에 다른 문제도 {sameArticleCount - 1}건
          </span>
        )}
      </div>
      <div style={{ marginTop: 8, fontSize: 13, lineHeight: 1.6 }}>{f.summary}</div>
      {firstSentence && firstSentence !== f.summary && (
        <div
          style={{
            marginTop: 8,
            fontSize: 12,
            padding: 8,
            background: "#f9fafb",
            borderRadius: 4,
            color: "#374151",
          }}
        >
          💡 {firstSentence}
        </div>
      )}
      {rec.reference_note && (
        /* P-06: 제재 사례 + 기관 근거 1줄 */
        <div style={{ marginTop: 6, fontSize: 11, color: "#6b7280" }}>
          📐 근거: {rec.reference_note}
        </div>
      )}
    </div>
  );
}

function ChecklistSection({ findings }) {
  /* P-05: 통합 체크리스트 — 심각·경고 finding의 권고를 체크박스화 */
  const items = useMemo(() => {
    return findings
      .filter((f) => ["심각", "경고"].includes(f.severity))
      .map((f) => {
        const rec = f.recommendation || {};
        return rec.contextual || rec.template || f.summary;
      })
      .filter(Boolean);
  }, [findings]);
  if (!items.length) return null;
  return (
    <div
      style={{
        background: "#fff",
        border: "1px solid #e5e7eb",
        borderRadius: 8,
        padding: 16,
        marginTop: 16,
      }}
    >
      <div
        style={{
          fontWeight: 700,
          marginBottom: 10,
          display: "flex",
          alignItems: "center",
          gap: 6,
        }}
      >
        <CheckSquare size={16} /> 사내규정 반영 체크리스트
      </div>
      <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
        {items.map((t, i) => (
          <li
            key={i}
            style={{ padding: "6px 0", fontSize: 13, borderBottom: "1px dashed #f3f4f6" }}
          >
            ☐ {t}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Roadmap({ findings }) {
  /* P-09: 각 단계에 관련 기관 1줄 */
  const buckets = {
    "즉시 (30일)": findings.filter((f) => f.severity === "심각"),
    "단기 (90일)": findings.filter((f) => f.severity === "경고"),
    "중기 (1년)": findings.filter((f) => f.severity === "주의"),
  };
  return (
    <div style={{ marginTop: 16 }}>
      {Object.entries(buckets).map(([label, items]) => (
        <div
          key={label}
          style={{
            marginBottom: 12,
            background: "#fff",
            border: "1px solid #e5e7eb",
            borderRadius: 8,
            padding: 12,
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              fontWeight: 700,
              marginBottom: 6,
            }}
          >
            <Clock size={14} /> {label} · {items.length}건
          </div>
          <div style={{ fontSize: 11, color: "#6b7280", marginBottom: 8 }}>
            <Building2 size={11} style={{ display: "inline" }} /> 관련: 법제처(체계정비),
            감사원(후속점검), 주무부처(시행령 정비)
          </div>
          {items.slice(0, 5).map((f) => (
            <div
              key={f.finding_id}
              style={{ fontSize: 12, padding: "2px 0", color: "#374151" }}
            >
              · {f.article_number} {f.pattern_name}: {f.summary}
            </div>
          ))}
          {items.length > 5 && (
            <div style={{ fontSize: 11, color: "#9ca3af", marginTop: 4 }}>
              … 외 {items.length - 5}건
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

export default function Report({ result }) {
  const [tab, setTab] = useState("종합");

  const law = result.law;
  const findings = result.findings || [];
  const issuesByArticle = useMemo(() => {
    const m = {};
    findings.forEach((f) => {
      if (f.is_false_positive) return;
      (m[f.article_number] = m[f.article_number] || []).push(f);
    });
    return m;
  }, [findings]);

  const issuesByCategory = useMemo(() => {
    const m = {};
    CATEGORY_ORDER.forEach((c) => (m[c] = []));
    findings.forEach((f) => {
      if (f.is_false_positive) return;
      m[f.category]?.push(f);
    });
    return m;
  }, [findings]);

  const radarData = CATEGORY_ORDER.map((cat) => ({
    axis: cat,
    value: Math.min(result.category_scores[cat]?.crd || 0, 200),
    cnt: result.category_scores[cat]?.finding_count || 0,
  }));

  const issueArticles = Object.keys(issuesByArticle).length;
  const severeFindings = findings.filter((f) => f.severity === "심각" && !f.is_false_positive);
  const warningFindings = findings.filter((f) => f.severity === "경고" && !f.is_false_positive);

  return (
    <div
      style={{
        background: "#f8f9fb",
        minHeight: "100vh",
        fontFamily: "'Pretendard','Noto Sans KR',sans-serif",
        color: "#1a1a2e",
      }}
    >
      {/* 표지 — P-07: 법령종류 · 시행일 · 개정일 · 조문수 순서 고정 */}
      <header
        style={{
          background: "linear-gradient(135deg,#1e293b,#0f172a)",
          color: "#fff",
          padding: "32px 24px 28px",
        }}
      >
        <div
          style={{
            fontSize: 11,
            color: "#94a3b8",
            letterSpacing: 1.5,
            marginBottom: 4,
          }}
        >
          규정 진단 리포트
        </div>
        <h1 style={{ fontSize: 22, fontWeight: 800, margin: "0 0 6px" }}>
          「{law.name}」
        </h1>
        <div style={{ fontSize: 12, color: "#94a3b8" }}>
          {law.type} · 시행 {law.effective_date || "-"} · 최종 개정{" "}
          {law.last_amended_date || "-"} · 총 {law.articles.length}개 조문
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 14,
            marginTop: 16,
            padding: "14px 16px",
            background: "rgba(220,38,38,0.12)",
            borderRadius: 10,
            border: "1px solid rgba(220,38,38,0.3)",
          }}
        >
          <span
            style={{ fontSize: 36, fontWeight: 900, color: "#ef4444", lineHeight: 1 }}
          >
            {result.law_grade}
          </span>
          <div>
            <div style={{ fontSize: 13, fontWeight: 600, color: "#fca5a5" }}>
              {result.law_score}점 · 발견 {findings.length}건
            </div>
            <div style={{ fontSize: 11, color: "#a8a29e", marginTop: 2 }}>
              심각 {severeFindings.length} · 경고 {warningFindings.length}
            </div>
          </div>
        </div>
      </header>

      {/* 탭 */}
      <div
        style={{
          display: "flex",
          background: "#fff",
          borderBottom: "1px solid #e5e7eb",
          padding: "0 12px",
        }}
      >
        {["종합", "문제점", "일정", "전체"].map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              background: "none",
              border: "none",
              padding: "12px 16px",
              fontSize: 13,
              fontWeight: tab === t ? 800 : 500,
              color: tab === t ? "#1a1a2e" : "#6b7280",
              borderBottom: tab === t ? "2px solid #1a1a2e" : "2px solid transparent",
              cursor: "pointer",
            }}
          >
            {t}
          </button>
        ))}
      </div>

      <div style={{ padding: 16 }}>
        {tab === "종합" && (
          <>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(2,1fr)",
                gap: 10,
                marginBottom: 12,
              }}
            >
              {/* P-01: 평서문 라벨 */}
              <StatCard
                label="이슈가 있는 조문"
                value={`${issueArticles}개`}
                hint={`전체 ${law.articles.length}개 중`}
              />
              <StatCard
                label="총 발견 건수"
                value={`${findings.length}건`}
                hint={`심각 ${severeFindings.length} · 경고 ${warningFindings.length}`}
              />
              <StatCard
                label="종합 등급"
                value={result.law_grade}
                hint={`${result.law_score}점`}
              />
              <StatCard
                label="분석 범위"
                value="모든 항목 점검 완료"
                hint="20 패턴"
              />
            </div>

            <div
              style={{
                background: "#fff",
                border: "1px solid #e5e7eb",
                borderRadius: 8,
                padding: 12,
                marginBottom: 12,
              }}
            >
              <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8 }}>
                카테고리별 리스크 분포
              </div>
              <ResponsiveContainer width="100%" height={220}>
                <RadarChart data={radarData}>
                  <PolarGrid />
                  <PolarAngleAxis dataKey="axis" tick={{ fontSize: 11 }} />
                  <PolarRadiusAxis tick={false} domain={[0, 200]} />
                  <Radar
                    dataKey="value"
                    stroke="#ef4444"
                    fill="#ef4444"
                    fillOpacity={0.3}
                  />
                </RadarChart>
              </ResponsiveContainer>
            </div>

            {CATEGORY_ORDER.map((cat) => (
              <CategoryAccordion
                key={cat}
                title={cat}
                items={issuesByCategory[cat] || []}
              />
            ))}
          </>
        )}

        {tab === "문제점" && (
          <div>
            {findings
              .filter((f) => !f.is_false_positive)
              .sort(
                (a, b) =>
                  ["양호", "개선", "주의", "경고", "심각"].indexOf(b.severity) -
                  ["양호", "개선", "주의", "경고", "심각"].indexOf(a.severity),
              )
              .map((f) => (
                <FindingCard
                  key={f.finding_id}
                  f={f}
                  sameArticleCount={
                    issuesByArticle[f.article_number]?.length || 0
                  }
                />
              ))}
          </div>
        )}

        {tab === "일정" && (
          <>
            <Roadmap findings={findings.filter((f) => !f.is_false_positive)} />
            <ChecklistSection findings={findings} />
          </>
        )}

        {tab === "전체" && (
          <div style={{ background: "#fff", borderRadius: 8, padding: 12 }}>
            <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid #e5e7eb", textAlign: "left" }}>
                  <th style={{ padding: 6 }}>조문</th>
                  <th style={{ padding: 6 }}>패턴</th>
                  <th style={{ padding: 6 }}>등급</th>
                  <th style={{ padding: 6 }}>요약</th>
                </tr>
              </thead>
              <tbody>
                {findings.map((f) => (
                  <tr
                    key={f.finding_id}
                    style={{ borderBottom: "1px dashed #f3f4f6", opacity: f.is_false_positive ? 0.4 : 1 }}
                  >
                    <td style={{ padding: 6 }}>{f.article_number}</td>
                    <td style={{ padding: 6 }}>
                      {f.pattern_id} {f.pattern_name}
                    </td>
                    <td style={{ padding: 6 }}>
                      <Badge severity={f.severity} />
                    </td>
                    <td style={{ padding: 6 }}>{f.summary}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div
          style={{
            marginTop: 24,
            padding: 12,
            fontSize: 11,
            color: "#9ca3af",
            textAlign: "center",
          }}
        >
          엔진 v{result.engine_version} · 패턴 P-01~P-10 적용 ·{" "}
          <a
            href="https://www.law.go.kr"
            style={{ color: "#9ca3af" }}
          >
            국가법령정보센터 <ExternalLink size={10} style={{ display: "inline" }} />
          </a>
        </div>
      </div>
    </div>
  );
}
