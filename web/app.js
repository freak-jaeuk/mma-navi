"use strict";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

async function postJSON(url, body) {
  const r = await fetch(url, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return r.json();
}
async function getJSON(url) { return (await fetch(url)).json(); }
const splitList = (s) => (s || "").split(",").map((x) => x.trim()).filter(Boolean);

// https URL만 허용(방어: javascript:/data: 차단). 불허면 null.
function safeUrl(u) {
  try { const x = new URL(u, location.origin); return x.protocol === "https:" ? x.href : null; }
  catch (e) { return null; }
}
// 클릭 가능한 비-버튼 요소에 키보드 접근성 부여(Enter/Space).
function clickable(el, fn) {
  el.setAttribute("tabindex", "0");
  el.setAttribute("role", "button");
  el.addEventListener("click", fn);
  el.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fn(); }
  });
}

// --- 상태 배지 + 코호트 ----------------------------------------------------
async function initStatus() {
  try {
    const s = await getJSON("/api/status");
    if (!s.ok) return;
    const src = s.distribution_source === "real" ? "실데이터" : "샘플";
    $("statusBadges").innerHTML =
      `<span class="badge">분포 <b>${esc(src)}</b> · ${esc(Number(s.cohort_size).toLocaleString())}명</span>` +
      `<span class="badge">지방청 <b>${esc(Number(s.cohort_count))}</b></span>` +
      `<span class="badge">특기 <b>${esc(Number(s.teukgi_count))}</b></span>`;
  } catch (e) { /* 무시 */ }
}
async function initCohorts() {
  try {
    const r = await getJSON("/api/cohorts");
    if (!r.ok) return;
    $("cohort").innerHTML = r.cohorts
      .map((c) => `<option value="${esc(c)}">${esc(c.replace("2026_", ""))}</option>`).join("");
  } catch (e) { /* 무시 */ }
}

// --- 모드 토글(사용자/담당자) ----------------------------------------------
function setMode(admin) {
  $("modeUser").classList.toggle("active", !admin);
  $("modeAdmin").classList.toggle("active", admin);
  $("modeUser").setAttribute("aria-selected", String(!admin));
  $("modeAdmin").setAttribute("aria-selected", String(admin));
  $("adminPanel").hidden = !admin;
  if (admin) { loadB2G(); loadComplaints(); loadMetrics($("adminMetrics")); $("adminPanel").scrollIntoView({ behavior: "smooth" }); }
}

// --- 민원 유형 자동 분류 집계 ----------------------------------------------
async function loadComplaints() {
  const box = $("complaintsResult");
  box.innerHTML = `<div class="loading">불러오는 중…</div>`;
  let res;
  try { res = await getJSON("/api/complaints-stats"); }
  catch (e) { box.innerHTML = `<div class="err">민원 집계 로드 실패.</div>`; return; }
  if (!res.ok) { box.innerHTML = `<div class="err">${esc(res.error || "오류")}</div>`; return; }
  const dist = res.distribution || [];
  const maxc = Math.max(1, ...dist.map((d) => d.count));
  const bars = dist.map((d) => {
    const w = Math.round((d.count / maxc) * 100);
    return `<div class="distrow"><span class="distlabel">${esc(d.category)}</span>
      <span class="distbar"><i style="width:${w}%"></i></span>
      <span class="distval">${esc(d.count)}건 (${esc(d.pct)}%)</span></div>`;
  }).join("");
  box.innerHTML = `<div class="card">
    <div class="distsummary">총 <b>${esc(res.total)}</b>건 · 자동거부(위험질문) <b>${esc(res.auto_refuse)}</b>건 (${esc(res.auto_refuse_pct)}%) · 분류·응답 가능 <b>${esc(res.answerable)}</b>건</div>
    ${bars}
    <div class="note">※ ${esc(res.note)}</div></div>`;
}

// --- B2G 14지방청 히트맵 ---------------------------------------------------
function heatColor(v, min, max) {
  if (v == null || max <= min) return "transparent";
  const t = Math.max(0, Math.min(1, (v - min) / (max - min)));
  return `rgba(255, ${Math.round(180 - 120 * t)}, ${Math.round(100 - 80 * t)}, ${0.18 + 0.5 * t})`;
}
async function loadB2G() {
  const box = $("b2gResult");
  const metric = $("b2gMetric").value;
  box.innerHTML = `<div class="loading">불러오는 중…</div>`;
  let res;
  try { res = await getJSON(`/api/b2g?metric=${encodeURIComponent(metric)}`); }
  catch (e) { box.innerHTML = `<div class="err">B2G 로드 실패 — 서버 연결을 확인하세요.</div>`; return; }
  if (!res.ok) { box.innerHTML = `<div class="err">${esc(res.error || "오류")}</div>`; return; }
  const rows = res.rows || [];
  if (!rows.length) { box.innerHTML = `<div class="note">표시할 지방청 데이터가 없습니다.</div>`; return; }
  const meds = rows.map((r) => r.median);
  const lo = Math.min(...meds), hi = Math.max(...meds);
  const isBmi = res.metric === "bmi";
  const head = `<tr><th>지방청</th><th>n</th><th>중앙 ${esc(res.label)}${esc(res.unit)}</th>` +
    (isBmi ? `<th>BMI≥25 %</th><th>BMI≥30 %</th>` : "") + `</tr>`;
  const body = rows.map((r) => {
    const bg = heatColor(r.median, lo, hi);
    return `<tr><td>${esc(r.cohort)}</td><td class="num">${esc(Number(r.n).toLocaleString())}</td>` +
      `<td class="num" style="background:${bg}">${esc(r.median)}</td>` +
      (isBmi ? `<td class="num">${esc(r.over25)}</td><td class="num">${esc(r.over30)}</td>` : "") + `</tr>`;
  }).join("");
  const n = res.national;
  const nat = n
    ? `전국(${esc(res.data_year || "")}) 중앙 <b>${esc(n.median)}${esc(res.unit)}</b>` +
      (isBmi && n.over25 != null ? ` · BMI≥25 <b>${esc(n.over25)}%</b> · BMI≥30 <b>${esc(n.over30)}%</b>` : "") +
      ` (n=${esc(Number(n.n).toLocaleString())})`
    : "";
  const ref = res.reference
    ? `<div class="note refbench">📊 외부 참고(같은 BMI≥25 기준): <b>${esc(res.reference.label)} ≈${esc(res.reference.rate_approx)}%</b>
        <span class="muted">↔ 병무청 전국 BMI≥25 ${esc(n && n.over25 != null ? n.over25 : "-")}% · 출처: ${esc(res.reference.source)} · ${esc(res.reference.caveat)}</span></div>`
    : "";
  box.innerHTML = `<div class="card"><div class="note">${nat}</div>
    <table class="heat"><thead>${head}</thead><tbody>${body}</tbody></table>
    ${ref}
    <div class="note">※ ${esc(res.note)}</div></div>`;
}

// --- 카드 생성 (단일 입력 → 백분위+특기+로드맵) -----------------------------
function profileFromForm() {
  return {
    height_cm: parseFloat($("height").value),
    weight_kg: parseFloat($("weight").value),
    cohort: $("cohort").value,
    majors: splitList($("majors").value),
    certificates: splitList($("certs").value),
    interests: splitList($("interests").value),
    preferred_branches: [...document.querySelectorAll(".branch:checked")].map((c) => c.value),
  };
}

async function runCard() {
  const btn = $("btnCard");
  btn.disabled = true; btn.textContent = "카드 만드는 중…";
  try {
    let res;
    try { res = await postJSON("/api/roadmap", profileFromForm()); }
    catch (e) {
      $("card").hidden = false;
      $("cardSummary").innerHTML = `<span class="err">카드 생성 실패 — 서버 연결을 확인하세요.</span>`;
      $("cardHealth").innerHTML = $("cardTeukgi").innerHTML = $("cardRoadmap").innerHTML = "";
      return;
    }
    if (!res.ok) {
      $("card").hidden = false;
      $("cardSummary").innerHTML = `<span class="err">${esc(res.error || "오류")}</span>`;
      $("cardHealth").innerHTML = $("cardTeukgi").innerHTML = $("cardRoadmap").innerHTML = "";
      return;
    }
    $("card").hidden = false;
    const p = res.profile;
    $("cardSummary").innerHTML =
      `입력: 신장 <b>${esc(p.height_cm)}</b>cm · 체중 <b>${esc(p.weight_kg)}</b>kg · BMI <b>${esc(p.bmi)}</b> · ` +
      `지방청 <b>${esc(String(p.cohort).replace("2026_", ""))}</b>`;
    renderHealth(res.percentile);
    renderTeukgi(res.teukgi);
    renderRoadmap(res.roadmap);
    $("card").scrollIntoView({ behavior: "smooth" });
  } finally {
    btn.disabled = false; btn.textContent = "내 준비 카드 만들기";
  }
}

// ① 건강 백분위
function percentileCard(b) {
  if (b.ok) {
    const rank = b.percentile_rank;
    const w = Math.max(2, Math.min(100, Number(rank) || 0));
    return `<div class="card ok">
      <div class="ttl"><h3>${esc(b.label)} = ${esc(b.value)}${esc(b.unit || "")}</h3>
        <span class="tag info">백분위 ${esc(rank)}</span></div>
      <div class="bar"><i style="width:${w}%"></i></div>
      <div class="msg">${esc(b.message)}</div></div>`;
  }
  return `<div class="card abstain">
    <div class="ttl"><h3>${esc(b.label)} = ${esc(b.value)}${esc(b.unit || "")}</h3>
      <span class="tag warn">판단 보류</span></div>
    <div class="msg">${esc(b.message)}</div></div>`;
}
function renderHealth(pc) {
  let html = `<h3 class="sectitle">① 건강 백분위 — 현재 내 위치<span class="inline-badge">결정론 계산 · 환각 불가</span></h3>`;
  if (!pc || !pc.ok) { html += `<div class="note">백분위를 계산할 수 없습니다.</div>`; }
  else {
    html += pc.blocks.map(percentileCard).join("");
    html += `<div class="note">⚠ ${esc(pc.disclaimer)}</div>`;
  }
  $("cardHealth").innerHTML = html;
}

// ② 특기
const STATUS_TAG = {
  ok: ["ok", "검증 충족"], unknown: ["warn", "본인 확인 필요"],
  grade: ["warn", "등급 미달·확인"], no_match: ["info", "관련도"],
};
function renderTeukgi(tk) {
  let html = `<h3 class="sectitle">② 지원 자격 검토 가능 특기 — 도달 가능 목적지</h3>`;
  if (!tk || !tk.ok) {
    html += `<div class="note">전공·자격·관심사를 입력하면 지원 자격을 검토할 수 있는 모집병 특기를 추천받을 수 있어요.</div>`;
  } else if (!tk.matches.length) {
    html += `<div class="note">조건에 맞는 특기를 찾지 못했습니다. 전공·자격을 더 입력해 보세요.</div>`;
  } else {
    html += tk.matches.map((m) => {
      const [cls, label] = STATUS_TAG[m.status] || STATUS_TAG.no_match;
      const c = m.competition;
      const comp = c
        ? `<div class="note comp">모집 경쟁률 <b>${esc(c.rate)}</b>:1 (${esc(c.yy)}년 기준 · 접수 ${esc(c.jeopsu)}/선발 ${esc(c.seonbal)}) — 병무청 접수현황, 참고·예측 아님</div>`
        : "";
      return `<div class="card ${m.status === "ok" ? "ok" : ""}">
        <div class="ttl"><h3>${esc(m.teukgi_name)} <span class="note">(${esc(m.branch)})</span></h3>
          <span class="tag ${cls}">${label}</span></div>
        <div class="msg">${esc(m.reason)}</div>
        <div class="note">자격요건: ${esc(m.qualification || "-")}${m.grade_req ? " · 등급 " + esc(m.grade_req) : ""} · 관련도 ${esc(m.relevance)}</div>
        ${comp}
      </div>`;
    }).join("");
    html += `<div class="note">⚠ ${esc(tk.disclaimer || "자격충족은 검증값이며 선발/합격을 보장하지 않습니다.")}</div>`;
  }
  $("cardTeukgi").innerHTML = html;
}

// ③ 로드맵 (접착제)
function renderRoadmap(rm) {
  let html = `<h3 class="sectitle">③ 나의 로드맵 — 다음 행동</h3>`;
  if (!rm || !rm.ok) { $("cardRoadmap").innerHTML = html + `<div class="note">로드맵을 만들 수 없습니다.</div>`; return; }
  html += `<div class="roadmap">` + rm.steps.map((s) => {
    const tone = ["ok", "warn"].includes(s.tone) ? s.tone : "";
    const url = s.link && safeUrl(s.link.url);
    const link = url
      ? `<a class="rlink" href="${esc(url)}" target="_blank" rel="noopener">${esc(s.link.label)} ↗</a>` : "";
    const ask = s.ask ? `<button type="button" class="rask" data-q="${esc(s.ask)}">이 단계 더 물어보기</button>` : "";
    const ag = s.agencies;
    const agBlock = (ag && ag.items && ag.items.length)
      ? `<div class="agencies"><div class="agcap">${esc(ag.region)} 관할 사회복무 복무기관 <b>${esc(Number(ag.total).toLocaleString())}</b>곳 · <span class="agsrc">${esc(ag.source)}</span></div>`
        + `<table class="agtable"><thead><tr><th>기관</th><th>시군구</th><th>선발제한 속성(기관)</th></tr></thead><tbody>`
        + ag.items.map((a) => `<tr><td>${esc(a.nm)}</td><td>${esc(a.sigungu)}</td><td>${a.restrict ? "제한 있음" : "제한 없음"}</td></tr>`).join("")
        + `</tbody></table><div class="agnote">${esc(ag.caveat || "")}</div></div>`
      : "";
    const v = s.vacancies;
    const vacBlock = v
      ? `<div class="agnote">📌 ${esc(v.region)} 본인선택 공석 <b>${esc(Number(v.records).toLocaleString())}</b>건(배정 ${esc(Number(v.baejeong).toLocaleString())}명) · ${esc(v.source)} — ${esc(v.caveat)}</div>`
      : "";
    const ct = s.centers;
    const ctBlock = (ct && ct.centers && ct.centers.length)
      ? `<div class="agencies"><div class="agcap">${esc(ct.region)} 관할 병역진로설계센터${ct.as_of ? " (" + esc(ct.as_of) + " 기준)" : ""} · <span class="agsrc">${esc(ct.source)}</span></div>`
        + `<table class="agtable"><thead><tr><th>센터</th><th>주소</th><th>전화</th></tr></thead><tbody>`
        + ct.centers.map((c) => `<tr><td>${esc(c.name)}</td><td>${esc(c.addr)}</td><td>${esc(c.tel)}</td></tr>`).join("")
        + `</tbody></table></div>`
      : "";
    return `<div class="rstep ${tone}">
      <div class="rnum">${esc(s.n)}</div>
      <div class="rbody"><h4>${esc(s.title)}</h4>
        <div class="rtext">${esc(s.text)}</div>
        ${agBlock}${vacBlock}${ctBlock}
        <div class="rmeta">${link}${ask}</div></div>
    </div>`;
  }).join("") + `</div>`;
  html += `<div class="note">⚠ ${esc(rm.note || "")}</div>`;
  $("cardRoadmap").innerHTML = html;
  // '이 단계 더 물어보기' → 후속 상담 프리필+실행
  $("cardRoadmap").querySelectorAll(".rask").forEach((b) =>
    b.addEventListener("click", () => { $("query").value = b.dataset.q; runConsult(); $("cardConsult").scrollIntoView({ behavior: "smooth" }); }));
}

// ④ 후속 상담 + 거부(우회로)
const ALT_ANCHOR = (alt) => {
  if (alt.includes("백분위")) return "cardHealth";
  if (alt.includes("자격") || alt.includes("특기")) return "cardTeukgi";
  if (alt.includes("검사") || alt.includes("상담") || alt.includes("누리집") || alt.includes("경쟁률")) return "cardRoadmap";
  return null;
};
function sourcesHtml(sources) {
  if (!sources || !sources.length) return "";
  return `<div class="sources"><h4>근거 출처 (${sources.length})</h4>` +
    sources.map((d) =>
      `<div class="src"><b>${esc(d.source)}</b> · 관련도 ${esc(d.score)}<br>${esc(d.snippet)}</div>`
    ).join("") + `</div>`;
}
async function showCategory(q) {
  try {
    const c = await postJSON("/api/classify", { query: q });
    $("consultCat").innerHTML = (c.ok && c.category && c.category !== "미상")
      ? `질문 분류: <span class="tag info">${esc(c.category)}</span>` : "";
  } catch (e) { $("consultCat").innerHTML = ""; }
}
async function runConsult() {
  const box = $("consultResult");
  const q = $("query").value.trim();
  if (!q) { box.innerHTML = `<div class="err">질문을 입력하세요.</div>`; return; }
  box.innerHTML = `<div class="loading">검토 중…</div>`;
  showCategory(q);
  let res;
  try { res = await postJSON("/api/consult", { query: q }); }
  catch (e) { box.innerHTML = `<div class="err">상담 요청 실패 — 서버 연결을 확인하세요.</div>`; return; }
  if (!res.ok) { box.innerHTML = `<div class="err">${esc(res.error || "오류")}</div>`; return; }

  if (res.answered) {
    box.innerHTML = `<div class="card ok">
      <div class="ttl"><h3>답변</h3><span class="tag ok">${esc(res.trust_status)}</span></div>
      <div class="msg">${esc(res.answer)}</div>
      <div class="note">공공데이터·공식 안내를 근거로 작성했습니다 (출처 아래).</div>
      ${sourcesHtml(res.sources)}</div>`;
  } else {
    const alts = (res.alternatives || []).map((a) => {
      const anc = ALT_ANCHOR(a);
      return anc
        ? `<span class="alt clickable" data-anchor="${anc}">${esc(a)} ↳</span>`
        : `<span class="alt">${esc(a)}</span>`;
    }).join("");
    box.innerHTML = `<div class="card refuse">
      <div class="ttl"><h3>답변 거부</h3><span class="tag bad">${esc(res.refusal_reason)}</span></div>
      <div class="msg">${esc(res.refusal_message)}</div>
      ${alts ? `<div class="note">대신 도와드릴 수 있어요 (클릭하면 해당 섹션으로):</div><div class="alts">${alts}</div>` : ""}
    </div>`;
    box.querySelectorAll(".alt.clickable").forEach((el) =>
      clickable(el, () => { const t = $(el.dataset.anchor); if (t) t.scrollIntoView({ behavior: "smooth" }); }));
  }
}

// --- AI 신뢰도 메트릭 (푸터/담당자 — 강등됨) --------------------------------
function refusalRow(tag, r) {
  if (!r) return "";
  const b = r.intent_gate_refusal;
  if (!b) return "";
  if (b.answer_only) {
    return `<tr><td>${esc(tag)}</td><td>위험질문 자동거부 (답변형 n=${esc(r.n)})</td>
      <td class="num">불필요 거부 ${esc(b.fp)}/${esc(r.n)}</td><td class="num">정확도 ${esc(b.answer_accuracy)}</td></tr>`;
  }
  const mf = r.by_category ? r.by_category.macro_f1 : "-";
  return `<tr><td>${esc(tag)}</td><td>위험질문 자동거부 (n=${esc(r.n)})</td>
    <td class="num">정밀도 ${esc(b.precision)} / 재현율 ${esc(b.recall)} / F1 ${esc(b.f1)}</td>
    <td class="num">사유분류 F1 ${esc(mf)}</td></tr>`;
}
function classifyRow(tag, c) {
  if (!c) return "";
  return `<tr><td>${esc(tag)}</td><td>민원 분류 (n=${esc(c.n)})</td>
    <td class="num">정확도 ${esc(c.accuracy)}</td><td class="num">평균 F1 ${esc(c.macro_f1)}</td></tr>`;
}
async function loadMetrics(box) {
  if (box.dataset.loaded) return;
  box.innerHTML = `<div class="loading">불러오는 중…</div>`;
  let res;
  try { res = await getJSON("/api/metrics"); }
  catch (e) { box.innerHTML = `<div class="err">평가 리포트 로드 실패 — 서버 연결을 확인하세요.</div>`; return; }
  if (!res.ok) { box.innerHTML = `<div class="err">${esc(res.error || "오류")}</div>`; return; }
  const rep = res.report, dev = rep.dev || {}, hold = rep.holdout || {};
  box.innerHTML = `<div class="card">
    <table><thead><tr><th>구분</th><th>과제</th><th>지표</th><th>보조</th></tr></thead>
      <tbody>
        ${refusalRow("개발셋", dev.refusal)}${classifyRow("개발셋", dev.classify)}
        ${refusalRow("미사용셋", hold.refusal)}${classifyRow("미사용셋", hold.classify)}
      </tbody></table>
    <div class="note">• <b>거부 성능은 질문의도 자동판별 단독 측정</b> (실제 상담 답변 연결은 다음 단계).</div>
    <div class="note">• 학습에 쓰지 않은 <b>미사용 검증셋으로 실제 일반화 성능을 정직하게 공개</b> — "측정·검증한 AI".</div>
  </div>`;
  box.dataset.loaded = "1";
}

// --- 바인딩 ----------------------------------------------------------------
$("btnCard").addEventListener("click", runCard);
$("btnConsult").addEventListener("click", runConsult);
$("btnPrint").addEventListener("click", () => window.print());
$("modeUser").addEventListener("click", () => setMode(false));
$("modeAdmin").addEventListener("click", () => setMode(true));
$("b2gMetric").addEventListener("change", loadB2G);
$("query").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) runConsult();
});
document.querySelectorAll("#consultExamples .chip").forEach((c) =>
  clickable(c, () => { $("query").value = c.dataset.q; runConsult(); }));
$("trustReport").addEventListener("toggle", (e) => { if (e.target.open) loadMetrics($("metricsResult")); });

initStatus();
initCohorts();
