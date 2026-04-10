/**
 * Generates a print-optimized HTML report from the final agent state.
 * Opens in a new window and triggers the browser's Save-as-PDF / Print dialog.
 */

const CATEGORY_LABELS = {
  skill: 'Skill', task: 'Task', tech: 'Technology',
  hot_technology: 'Hot Tech', knowledge: 'Knowledge',
};

const GAP_TYPE_LABELS = {
  missing: 'Missing', weak: 'Weak',
  not_evidenced: 'Not Evidenced', irrelevant: 'Irrelevant',
};

const RESOURCE_ICONS = {
  tutorial: '📚', project: '🔨', open_source: '⭐',
  workshop: '🎓', certification: '🏆', internship: '💼',
  online_course: '🎬', documentation: '📖',
};

// Phase colour palette (matches UI)
const PHASE_COLORS = ['#3b82f6', '#8b5cf6', '#10b981', '#f59e0b', '#ef4444', '#ec4899'];

function esc(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function levelDots(value, max = 4) {
  const filled = Math.round(Math.min(value, max));
  return (
    '<span style="color:#3b82f6;letter-spacing:1pt">' + '●'.repeat(filled) + '</span>' +
    '<span style="color:#cbd5e1;letter-spacing:1pt">' + '○'.repeat(Math.max(0, max - filled)) + '</span>'
  );
}

/* ── Pathway Plan HTML ──────────────────────────────────────────── */
function pathwaySectionHTML(plan) {
  if (!plan?.phases?.length) return '';

  const totalWeeks = plan.timeline_weeks ?? plan.phases.reduce((s, p) => s + (p.weeks ?? 0), 0);

  const phasesHTML = plan.phases.map((phase, i) => {
    const color       = PHASE_COLORS[i % PHASE_COLORS.length];
    const actions     = phase.learning_actions ?? [];
    const numeral     = i + 1;

    const actionsHTML = actions.length === 0 ? '' : `
      <div class="phase-actions-title">Step-by-Step Actions</div>
      <ol class="actions-ol">
        ${actions.map((a) => {
          const resources = (a.example_resources ?? []).slice(0, 3);
          const resHTML   = resources.length === 0 ? '' : `
            <div class="action-resources">
              ${resources.map(r => {
                const label = `${RESOURCE_ICONS[r.resource_type] ?? '📌'} ${esc(r.title)}${r.estimated_hours ? ` · ${r.estimated_hours}h` : ''}${r.is_free ? ' · Free' : ''}`;
                return r.url
                  ? `<a class="res-chip" href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">${label}</a>`
                  : `<span class="res-chip">${label}</span>`;
              }).join('')}
            </div>
          `;
          const stackHTML = a.stack?.length ? `
            <div class="action-stack">
              ${a.stack.map(tool => `<span class="stack-chip">${esc(tool)}</span>`).join('')}
            </div>
          ` : '';
          return `
            <li class="action-li">
              <div class="action-title">${esc(a.title)}</div>
              <div class="action-description">${esc(a.description)}</div>
              ${stackHTML}
              ${a.rationale ? `<div class="action-rationale">${esc(a.rationale)}</div>` : ''}
              ${resHTML}
            </li>
          `;
        }).join('')}
      </ol>
    `;

    const checkpointHTML = phase.checkpoint
      ? `<div class="checkpoint">✓ <em>${esc(phase.checkpoint)}</em></div>`
      : '';

    const resumeHTML = phase.resume_updates?.length
      ? `<div class="phase-section-label">Resume Updates</div>
         <ul class="resume-ul">
           ${phase.resume_updates.map(u => `<li>${esc(u)}</li>`).join('')}
         </ul>`
      : '';

    const gapsHTML = phase.addresses_gaps?.length
      ? `<div class="phase-section-label">Gaps Addressed</div>
         <div class="gap-chips">
           ${phase.addresses_gaps.map(g =>
             `<span class="gap-chip" style="border-color:${color};color:${color}">${esc(g)}</span>`
           ).join('')}
         </div>`
      : '';

    return `
      <div class="phase-block" style="border-left:3px solid ${color}">
        <div class="phase-header">
          <span class="phase-num" style="background:${color}">${numeral}</span>
          <div class="phase-header-body">
            <div class="phase-title">${esc(phase.title)}</div>
            <div class="phase-duration" style="color:${color}">${phase.weeks} ${phase.weeks === 1 ? 'week' : 'weeks'}</div>
          </div>
        </div>
        ${phase.outcome ? `<div class="phase-outcome" style="border-color:${color}">🎯 ${esc(phase.outcome)}</div>` : ''}
        ${phase.rationale ? `<div class="phase-rationale">${esc(phase.rationale)}</div>` : ''}
        ${actionsHTML}
        ${checkpointHTML}
        ${resumeHTML}
        ${gapsHTML}
      </div>
      ${i < plan.phases.length - 1 ? `<div class="phase-arrow" style="color:${PHASE_COLORS[(i + 1) % PHASE_COLORS.length]}">▼</div>` : ''}
    `;
  }).join('');

  return `
    <div class="section-break">
      <h2>Learning Pathway</h2>
      <p class="summary-text">${totalWeeks}-week plan · ${plan.phases.length} phases</p>
      ${phasesHTML}
      <div class="pathway-end">🎯 Career Ready</div>
    </div>
  `;
}

/* ── Main HTML generator ────────────────────────────────────────── */
export function generateReportHTML({ studentModel, roleSpec, gapReport, plan, targetRole }) {
  const roleName = esc(roleSpec?.canonical_role_title ?? targetRole ?? 'Unknown Role');
  const onet     = roleSpec?.matched_onet_code ? ` (O*NET ${esc(roleSpec.matched_onet_code)})` : '';
  const date     = new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });

  const skills      = (studentModel?.skills      ?? []).map(esc);
  const experiences = (studentModel?.experiences ?? []).map(esc);
  const education   = (studentModel?.education   ?? []).map(esc);
  const reqs        = [...(roleSpec?.requirements ?? [])].sort((a, b) => b.importance - a.importance);
  const gaps        = [...(gapReport?.gaps        ?? [])].sort((a, b) => b.weighted_gap - a.weighted_gap);

  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Career Report — ${roleName}</title>
<style>
  @page { size: letter; margin: 0.65in 0.72in; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    font-size: 10pt;
    color: #1e293b;
    line-height: 1.5;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
    background: #fff;
  }
  .shell { max-width: 7.8in; margin: 0 auto; }

  /* ── Typography ── */
  h1 { font-size: 17pt; font-weight: 800; color: #0f172a; margin-bottom: 2pt; }
  h2 {
    font-size: 11.5pt; font-weight: 700; color: #1e40af;
    margin: 14pt 0 6pt;
    padding-bottom: 3pt;
    border-bottom: 2px solid #dbeafe;
  }
  h3 { font-size: 10pt; font-weight: 700; color: #334155; margin: 8pt 0 3pt; }
  .meta  { font-size: 9pt; color: #64748b; margin-bottom: 2pt; }
  .onet  { color: #6366f1; }
  .divider { border: none; border-top: 1px solid #e2e8f0; margin: 10pt 0; }

  /* ── Layout ── */
  .cols       { display: flex; gap: 16pt; }
  .col-left   { flex: 1; }
  .col-right  { flex: 1; }

  /* ── Tags ── */
  .tags { display: flex; flex-wrap: wrap; gap: 3pt; margin-top: 3pt; }
  .tag  { display: inline-block; padding: 1pt 6pt; border-radius: 3pt; font-size: 8.5pt; font-weight: 600; }
  .tag-green { background: #d1fae5; color: #065f46; }

  /* ── Requirements table ── */
  .req-table  { width: 100%; border-collapse: collapse; font-size: 8.5pt; }
  .req-table thead { display: table-header-group; }
  .req-table tr { break-inside: avoid; }
  .req-table th { text-align: left; font-weight: 700; color: #64748b; padding: 2pt 4pt; border-bottom: 1px solid #e2e8f0; font-size: 8pt; text-transform: uppercase; letter-spacing: 0.5pt; }
  .req-table td { padding: 2.5pt 4pt; border-bottom: 1px solid #f1f5f9; vertical-align: middle; }
  .cat { display: inline-block; padding: 0 4pt; border-radius: 2pt; font-size: 7.5pt; font-weight: 600; background: #f1f5f9; color: #475569; }

  /* ── Gap cards ── */
  .gap-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 7pt; margin-top: 4pt; }
  .gap-card { padding: 6pt 8pt; border: 1px solid #e2e8f0; border-radius: 4pt; background: #fafbfc; break-inside: avoid; }
  .gap-name { font-weight: 700; font-size: 9pt; margin-bottom: 2pt; }
  .gap-type { display: inline-block; font-size: 7.5pt; font-weight: 600; padding: 0 4pt; border-radius: 2pt; }
  .gap-type-missing      { background: #fee2e2; color: #991b1b; }
  .gap-type-weak         { background: #fef3c7; color: #92400e; }
  .gap-type-not_evidenced { background: #f1f5f9; color: #475569; }
  .gap-levels { display: flex; gap: 10pt; font-size: 8pt; color: #64748b; margin-top: 2pt; }

  .summary-text { font-size: 9pt; color: #475569; font-style: italic; margin-bottom: 6pt; }
  .footer { margin-top: 12pt; text-align: center; font-size: 7.5pt; color: #94a3b8; }

  /* ── Pathway plan ── */
  .section-break { break-before: page; }

  .phase-block {
    margin-bottom: 10pt;
    padding: 8pt 10pt 8pt 12pt;
    border-radius: 4pt;
    background: #fafbfc;
    border: 1px solid #e2e8f0;
    break-inside: avoid;
  }

  .phase-header { display: flex; align-items: flex-start; gap: 8pt; margin-bottom: 5pt; }

  .phase-num {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 20pt;
    height: 20pt;
    border-radius: 50%;
    color: #fff;
    font-size: 9pt;
    font-weight: 800;
    flex-shrink: 0;
  }

  .phase-header-body { flex: 1; }
  .phase-title    { font-size: 11pt; font-weight: 700; color: #0f172a; }
  .phase-duration { font-size: 8.5pt; font-weight: 600; margin-top: 1pt; }

  .phase-outcome {
    font-size: 9pt;
    color: #334155;
    font-weight: 500;
    padding: 4pt 8pt;
    border-radius: 3pt;
    border-left: 3px solid;
    background: #f8fafc;
    margin-bottom: 5pt;
  }

  .phase-rationale { font-size: 8.5pt; color: #64748b; font-style: italic; margin-bottom: 5pt; line-height: 1.5; }

  .phase-actions-title {
    font-size: 8pt;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.5pt;
    color: #64748b;
    margin: 5pt 0 3pt;
  }

  .actions-ol  { padding-left: 14pt; }
  .action-li   { margin-bottom: 5pt; break-inside: avoid; }
  .action-title   { font-size: 9pt; font-weight: 700; color: #1e293b; }
  .action-summary { font-size: 8.5pt; color: #475569; margin-top: 1pt; line-height: 1.4; }
  .action-rationale { font-size: 8pt; color: #94a3b8; font-style: italic; margin-top: 1pt; }

  .action-resources { display: flex; flex-wrap: wrap; gap: 3pt; margin-top: 2pt; }
  .res-chip {
    display: inline-block;
    padding: 1pt 5pt;
    border-radius: 2pt;
    background: #f1f5f9;
    color: #475569;
    font-size: 7.5pt;
    font-weight: 600;
    text-decoration: none;
  }
  a.res-chip {
    color: #2563eb;
    cursor: pointer;
  }
  a.res-chip:hover {
    text-decoration: underline;
  }

  .checkpoint {
    font-size: 8.5pt;
    color: #059669;
    margin: 5pt 0;
    padding: 3pt 8pt;
    background: #f0fdf4;
    border-radius: 3pt;
    border-left: 3px solid #10b981;
  }

  .phase-section-label {
    font-size: 7.5pt;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.5pt;
    color: #94a3b8;
    margin: 4pt 0 2pt;
  }

  .resume-ul { padding-left: 12pt; font-size: 8.5pt; color: #475569; }
  .resume-ul li { margin-bottom: 1.5pt; }

  .gap-chips { display: flex; flex-wrap: wrap; gap: 3pt; }
  .gap-chip {
    display: inline-block;
    padding: 1pt 5pt;
    border-radius: 10pt;
    border: 1px solid;
    font-size: 7.5pt;
    font-weight: 600;
  }

  .phase-arrow {
    text-align: center;
    font-size: 14pt;
    line-height: 1.2;
    margin: -2pt 0;
  }

  .pathway-end {
    text-align: center;
    font-size: 12pt;
    font-weight: 800;
    color: #3b82f6;
    margin-top: 8pt;
    padding: 8pt;
    border: 2px solid #3b82f6;
    border-radius: 6pt;
    background: #eff6ff;
  }

  @media print {
    .cols { display: block; }
    .col-right { margin-top: 10pt; }
    .gap-grid { grid-template-columns: 1fr; }
    h2, h3 { break-after: avoid; }
  }
</style>
</head>
<body>
<div class="shell">

  <h1>Career Report</h1>
  <p class="meta">Target Role: <strong>${roleName}</strong><span class="onet">${onet}</span></p>
  <p class="meta">Generated: ${date}</p>
  <hr class="divider">

  <!-- ── Profile & Requirements ── -->
  <div class="cols">
    <div class="col-left">
      <h2>Your Profile</h2>
      ${skills.length > 0 ? `
        <h3>Skills</h3>
        <div class="tags">${skills.map(s => `<span class="tag tag-green">${s}</span>`).join('')}</div>
      ` : ''}
      ${experiences.length > 0 ? `
        <h3>Experience</h3>
        <ul>${experiences.map(e => `<li>${e}</li>`).join('')}</ul>
      ` : ''}
      ${education.length > 0 ? `
        <h3>Education</h3>
        <ul>${education.map(e => `<li>${e}</li>`).join('')}</ul>
      ` : ''}
      ${!skills.length && !experiences.length && !education.length
        ? '<p style="color:#94a3b8;font-size:9pt">No profile data extracted.</p>'
        : ''}
    </div>

    <div class="col-right">
      <h2>Role Requirements</h2>
      ${reqs.length > 0 ? `
        <table class="req-table">
          <thead><tr><th>Requirement</th><th>Type</th><th>Level</th></tr></thead>
          <tbody>
            ${reqs.map(r => `
              <tr>
                <td>${esc(r.req_summary)}</td>
                <td><span class="cat">${CATEGORY_LABELS[r.category] ?? r.category}</span></td>
                <td>${levelDots(r.required_level)}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      ` : '<p style="color:#94a3b8;font-size:9pt">No requirements data.</p>'}
    </div>
  </div>

  <!-- ── Gap Analysis ── -->
  <h2>Gap Analysis</h2>
  ${gapReport?.summary ? `<p class="summary-text">${esc(gapReport.summary)}</p>` : ''}
  ${gaps.length > 0 ? `
    <div class="gap-grid">
      ${gaps.map(g => {
        const typeClass = g.gap_type === 'missing' ? 'gap-type-missing'
          : g.gap_type === 'weak' ? 'gap-type-weak'
          : 'gap-type-not_evidenced';
        return `
          <div class="gap-card">
            <div class="gap-name">
              ${esc(g.summary)}
              <span class="gap-type ${typeClass}">${GAP_TYPE_LABELS[g.gap_type] ?? g.gap_type}</span>
            </div>
            <div class="gap-levels">
              <span>Required: ${levelDots(g.required_level)}</span>
              <span>Current: ${levelDots(g.student_score)}</span>
            </div>
          </div>
        `;
      }).join('')}
    </div>
  ` : '<p style="color:#94a3b8;font-size:9pt">No gaps identified.</p>'}

  <!-- ── Pathway Plan ── -->
  ${pathwaySectionHTML(plan)}

  <div class="footer">CareerAI · AI-Powered Career Planning · ${date}</div>
</div>

<script>window.onload = function() { window.print(); }</script>
</body>
</html>`;
}

export function downloadReport(data) {
  const html = generateReportHTML(data);
  const w = window.open('', '_blank');
  if (w) {
    w.document.write(html);
    w.document.close();
  }
}
