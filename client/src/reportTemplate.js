/**
 * Generates a clean, print-optimized HTML report from the final state.
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

function esc(str) {
  if (!str) return '';
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function levelDots(value, max = 4) {
  const filled = Math.round(value);
  return '●'.repeat(filled) + '○'.repeat(Math.max(0, max - filled));
}

export function generateReportHTML({ studentModel, roleSpec, gapReport, plan, targetRole }) {
  const roleName = esc(roleSpec?.canonical_role_title ?? targetRole ?? 'Unknown Role');
  const onet = roleSpec?.matched_onet_code ? ` (O*NET ${esc(roleSpec.matched_onet_code)})` : '';
  const date = new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });

  // Student skills
  const skills = (studentModel?.skills ?? []).map(esc);
  const experiences = (studentModel?.experiences ?? []).map(esc);
  const education = (studentModel?.education ?? []).map(esc);

  const reqs = [...(roleSpec?.requirements ?? [])]
    .sort((a, b) => b.importance - a.importance)
    ;

  const gaps = [...(gapReport?.gaps ?? [])]
    .sort((a, b) => b.weighted_gap - a.weighted_gap)
    ;

  const phases = plan?.phases ?? [];
  const risks = plan?.risks ?? [];

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
  .printShell { max-width: 7.8in; margin: 0 auto; }
  h1 { font-size: 16pt; font-weight: 800; color: #0f172a; margin-bottom: 2pt; }
  h2 { font-size: 11.5pt; font-weight: 700; color: #1e40af; margin: 12pt 0 6pt; border-bottom: 1.5px solid #dbeafe; padding-bottom: 2pt; }
  h3 { font-size: 10pt; font-weight: 700; color: #334155; margin: 8pt 0 3pt; }
  .meta { font-size: 9pt; color: #64748b; margin-bottom: 2pt; }
  .onet { color: #6366f1; }
  .divider { border: none; border-top: 1px solid #e2e8f0; margin: 9pt 0; }

  /* Two-column layout */
  .cols { display: flex; gap: 16pt; }
  .col-left { flex: 1; }
  .col-right { flex: 1; }

  /* Tags */
  .tags { display: flex; flex-wrap: wrap; gap: 3pt; }
  .tag {
    display: inline-block; padding: 1pt 6pt; border-radius: 3pt;
    font-size: 8.5pt; font-weight: 600;
  }
  .tag-green { background: #d1fae5; color: #065f46; }
  .tag-blue  { background: #dbeafe; color: #1e40af; }

  /* Lists */
  ul { padding-left: 15pt; }
  li { margin-bottom: 2pt; }

  /* Requirements table */
  .req-table { width: 100%; border-collapse: collapse; font-size: 8.5pt; }
  .req-table thead { display: table-header-group; }
  .req-table tr { break-inside: avoid; }
  .req-table th { text-align: left; font-weight: 700; color: #64748b; padding: 2pt 4pt; border-bottom: 1px solid #e2e8f0; font-size: 8pt; text-transform: uppercase; letter-spacing: 0.5pt; }
  .req-table td { padding: 2.5pt 4pt; border-bottom: 1px solid #f1f5f9; }
  .cat { display: inline-block; padding: 0 4pt; border-radius: 2pt; font-size: 7.5pt; font-weight: 600; background: #f1f5f9; color: #475569; }
  .dots { font-size: 8pt; letter-spacing: 1pt; color: #3b82f6; }
  .dots-empty { color: #cbd5e1; }

  /* Gap cards */
  .gap-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8pt; }
  .gap-card { padding: 6pt 8pt; border: 1px solid #e2e8f0; border-radius: 4pt; background: #fafbfc; }
  .gap-card { break-inside: avoid; }
  .gap-name { font-weight: 700; font-size: 9pt; margin-bottom: 2pt; }
  .gap-type { display: inline-block; font-size: 7.5pt; font-weight: 600; padding: 0 4pt; border-radius: 2pt; }
  .gap-type-missing { background: #fee2e2; color: #991b1b; }
  .gap-type-weak { background: #fef3c7; color: #92400e; }
  .gap-type-not_evidenced { background: #f1f5f9; color: #475569; }
  .gap-levels { display: flex; gap: 10pt; font-size: 8pt; color: #64748b; margin-top: 2pt; }

  .summary-text { font-size: 9pt; color: #475569; font-style: italic; margin-bottom: 6pt; }

  .footer { margin-top: 10pt; text-align: center; font-size: 7.5pt; color: #94a3b8; }

  @media print {
    .cols { display: block; }
    .col-right { margin-top: 10pt; }
    .gap-grid { grid-template-columns: 1fr; }
    h2, h3 { break-after: avoid; }
  }
</style>
</head>
<body>
  <div class="printShell">
  <h1>Career Gap Analysis Report</h1>
  <p class="meta">Target Role: <strong>${roleName}</strong><span class="onet">${onet}</span></p>
  <p class="meta">Generated: ${date}</p>
  <hr class="divider">

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
      ${!skills.length && !experiences.length && !education.length ? '<p style="color:#94a3b8">No profile data extracted.</p>' : ''}
    </div>

    <div class="col-right">
      <h2>Role Requirements</h2>
      ${reqs.length > 0 ? `
        <table class="req-table">
          <thead><tr><th>Requirement</th><th>Type</th><th>Level</th></tr></thead>
          <tbody>
          ${reqs.map(r => {
            return `<tr>
              <td>${esc(r.req_summary)}</td>
              <td><span class="cat">${CATEGORY_LABELS[r.category] ?? r.category}</span></td>
              <td><span class="dots">${levelDots(r.required_level).replace(/○+/g, '')}</span><span class="dots dots-empty">${levelDots(r.required_level).replace(/●+/g, '')}</span></td>
            </tr>`;
          }).join('')}
          </tbody>
        </table>
      ` : '<p style="color:#94a3b8">No requirements data.</p>'}
    </div>
  </div>

  <h2>Gap Analysis</h2>
  ${gapReport?.summary ? `<p class="summary-text">${esc(gapReport.summary)}</p>` : ''}
  ${gaps.length > 0 ? `
    <div class="gap-grid">
      ${gaps.map(g => {
        const typeClass = g.gap_type === 'missing' ? 'gap-type-missing' : g.gap_type === 'weak' ? 'gap-type-weak' : 'gap-type-not_evidenced';
        return `<div class="gap-card">
          <div class="gap-name">${esc(g.summary)} <span class="gap-type ${typeClass}">${GAP_TYPE_LABELS[g.gap_type] ?? g.gap_type}</span></div>
          <div class="gap-levels">
            <span>Required: <span class="dots">${levelDots(g.required_level).replace(/○+/g, '')}</span><span class="dots dots-empty">${levelDots(g.required_level).replace(/●+/g, '')}</span></span>
            <span>Current: <span class="dots">${levelDots(g.student_score).replace(/○+/g, '')}</span><span class="dots dots-empty">${levelDots(g.student_score).replace(/●+/g, '')}</span></span>
          </div>
        </div>`;
      }).join('')}
    </div>
  ` : '<p style="color:#94a3b8">No gaps identified.</p>'}

  <h2>Pathway Plan</h2>
  ${phases.length > 0 ? `
    <p class="summary-text">Timeline: ${esc(plan?.timeline_weeks ?? '?')} weeks · Phases: ${phases.length}</p>
    ${phases.map((phase, idx) => `
      <div class="gap-card" style="margin-bottom:8pt;">
        <div class="gap-name">Phase ${idx + 1}: ${esc(phase.title)} <span class="cat">${esc(phase.weeks)} weeks</span></div>
        <p style="font-size:8.5pt;color:#475569;margin:2pt 0;"><strong>Rationale:</strong> ${esc(phase.rationale)}</p>
        <p style="font-size:8.5pt;color:#475569;margin:2pt 0;"><strong>Outcome:</strong> ${esc(phase.outcome)}</p>
        ${phase.checkpoint ? `<p style="font-size:8.5pt;color:#475569;margin:2pt 0;"><strong>Checkpoint:</strong> ${esc(phase.checkpoint)}</p>` : ''}
        ${phase.learning_actions?.length ? `
          <h3>Learning Actions</h3>
          <ul>${phase.learning_actions.map(a => `<li><strong>${esc(a.title)}</strong>: ${esc(a.summary)}</li>`).join('')}</ul>
        ` : ''}
        ${phase.resources?.length ? `
          <h3>Resources</h3>
          <ul>${phase.resources.map(r => `<li>${esc(r.title)}${r.provider ? ` (${esc(r.provider)})` : ''}</li>`).join('')}</ul>
        ` : ''}
        ${phase.resume_updates?.length ? `
          <h3>Resume Updates</h3>
          <ul>${phase.resume_updates.map(u => `<li>${esc(u)}</li>`).join('')}</ul>
        ` : ''}
      </div>
    `).join('')}
  ` : '<p style="color:#94a3b8">No pathway plan available for this run.</p>'}

  ${risks.length > 0 ? `
    <h3>Risks To Watch</h3>
    <ul>${risks.map(r => `<li>${esc(r)}</li>`).join('')}</ul>
  ` : ''}

  <div class="footer">CareerAI — AI-Powered Career Gap Analysis</div>
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
