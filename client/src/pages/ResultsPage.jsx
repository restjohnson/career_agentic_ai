import { useState, useCallback, useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import styles from './ResultsPage.module.css';
import { downloadReport } from '../reportTemplate';

/* ── Constants ──────────────────────────────────────────────────────── */

const CATEGORY_LABELS = {
  skill: 'Skill', task: 'Task', tech: 'Technology',
  hot_technology: 'Hot Tech', knowledge: 'Knowledge',
};

const GAP_TYPE_LABELS = {
  no_evidence: 'No Evidence',
  claimed_only: 'Claimed Only',
  partial: 'Partial',
  optional_gap: 'Optional Gap',
  met: 'Met',
  missing: 'Missing',
  weak: 'Weak',
  not_evidenced: 'Not Evidenced',
  irrelevant: 'Irrelevant',
};

const ROOT_CAUSE_LABELS = {
  missing_entirely: 'Missing entirely',
  no_theory: 'Has practice, lacks theory',
  no_practice: 'Has theory, lacks practice',
};

export const PHASE_COLORS = [
  '#3b82f6', '#8b5cf6', '#10b981', '#f59e0b', '#ef4444', '#ec4899',
];

const BLOOM_COLORS = {
  remember:   '#6b7280',
  understand: '#3b82f6',
  apply:      '#10b981',
  analyse:    '#f59e0b',
  evaluate:   '#ef4444',
  create:     '#8b5cf6',
};

const RESOURCE_ICONS = {
  tutorial:      '📚',
  project:       '🔨',
  open_source:   '⭐',
  workshop:      '🎓',
  certification: '🏆',
  internship:    '💼',
  online_course: '🎬',
  documentation: '📖',
};

const EVIDENCE_CONFIDENCE_HELP = 'Confidence estimates how strongly each evidence item demonstrates the skill: higher values indicate clearer, more direct proof; lower values indicate weaker or indirect proof.';

/* ── Helpers ─────────────────────────────────────────────────────────── */

function levelBar(value, max = 4) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className={styles.levelTrack}>
      <div className={styles.levelFill} style={{ width: `${pct}%` }} />
    </div>
  );
}

function extractData(finalState) {
  return {
    studentModel: finalState?.student_model ?? null,
    roleSpec:     finalState?.role_spec     ?? null,
    gapReport:    finalState?.gap_report    ?? null,
    plan:         finalState?.plan          ?? null,
    evidenceItems: finalState?.evidence_items ?? [],
    targetRole:   finalState?.desired_role  ?? 'Unknown Role',
  };
}

/* ══════════════════════════════════════════════════════════════════════
   Results Page
   ══════════════════════════════════════════════════════════════════════ */
export default function ResultsPage() {
  const location  = useLocation();
  const navigate  = useNavigate();
  const storedFinalState = (() => {
    try { return JSON.parse(sessionStorage.getItem('career_flow_final_state') ?? 'null'); }
    catch { return null; }
  })();
  const finalState = location.state?.finalState ?? storedFinalState;
  const { studentModel, roleSpec, gapReport, plan, evidenceItems, targetRole } = extractData(finalState);

  const [activeTab, setActiveTab] = useState('career');

  useEffect(() => {
    if (!finalState) navigate('/upload', { replace: true });
  }, [finalState, navigate]);

  const handleDownload = useCallback(() => {
    downloadReport({ studentModel, roleSpec, gapReport, plan, targetRole });
  }, [studentModel, roleSpec, gapReport, plan, targetRole]);

  const gapCount    = gapReport?.gaps?.length ?? 0;
  const phaseCount  = plan?.phases?.length ?? 0;

  const tabs = [
    { key: 'career',  label: 'Career Profile', badge: null },
    { key: 'gaps',    label: 'Gap Analysis',   badge: gapCount   > 0 ? gapCount   : null },
    { key: 'pathway', label: 'Pathway Plan',   badge: phaseCount > 0 ? phaseCount : null },
  ];

  return (
    <div className={styles.page}>
      {/* ── Header ─────────────────────────────────────────────────── */}
      <div className={styles.pageHeader}>
        <div className={styles.headerInner}>
          <div className={styles.headerRow}>
            <div>
              <span className={styles.headerBadge}>Analysis Complete</span>
              <h1 className={styles.pageTitle}>Your Career Report</h1>
              <p className={styles.pageMeta}>
                Target Role: <strong>{targetRole}</strong>
                {roleSpec?.matched_onet_code && roleSpec.confidence_role_match >= 0.95 && (
                  <span className={styles.onetCode}> · O*NET {roleSpec.matched_onet_code}</span>
                )}
              </p>
            </div>
            <div className={styles.headerActions}>
              <button type="button" onClick={handleDownload} className={styles.downloadBtn}>
                ↓ Download PDF
              </button>
              <button type="button" onClick={() => {
                sessionStorage.removeItem('career_flow_evidence_ids');
                sessionStorage.removeItem('career_flow_constraints');
                sessionStorage.removeItem('career_flow_final_state');
                sessionStorage.removeItem('career_flow_run_id');
                localStorage.removeItem('session_token');
                localStorage.removeItem('session_id');
                navigate('/upload', { replace: true });
              }} className={styles.restartBtn}>Start Over</button>
            </div>
          </div>

          <div className={styles.tabBar}>
            {tabs.map(t => (
              <button
                key={t.key}
                className={`${styles.tab} ${activeTab === t.key ? styles.tabActive : ''}`}
                onClick={() => setActiveTab(t.key)}
              >
                {t.label}
                {t.badge !== null && (
                  <span className={`${styles.tabBadge} ${activeTab === t.key ? styles.tabBadgeActive : ''}`}>
                    {t.badge}
                  </span>
                )}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* ── Content ────────────────────────────────────────────────── */}
      <div className={styles.container}>
        {activeTab === 'career'  && <CareerPlanTab studentModel={studentModel} roleSpec={roleSpec} targetRole={targetRole} />}
        {activeTab === 'gaps'    && <GapAnalysisTab gapReport={gapReport} evidenceItems={evidenceItems} />}
        {activeTab === 'pathway' && <PathwayPlanTab plan={plan} />}
      </div>
    </div>
  );
}

/* ══════════════════════════════════════════════════════════════════════
   Career Profile Tab — Student Model + Role Requirements
   ══════════════════════════════════════════════════════════════════════ */
function CareerPlanTab({ studentModel, roleSpec, targetRole }) {
  return (
    <div className={styles.careerGrid}>
      {/* Student Profile */}
      <div className={styles.card}>
        <h2 className={styles.cardTitle}><span className={styles.dotBlue} />Student Profile</h2>
        <p className={styles.cardSubtitle}>Extracted from your uploaded evidence</p>
        {studentModel ? (
          <>
            {studentModel.skills?.length > 0 && (
              <div className={styles.section}>
                <h3 className={styles.sectionTitle}>Skills</h3>
                <ul className={styles.tagList}>
                  {studentModel.skills.map(s => (
                    <li key={s} className={`${styles.tag} ${styles.tagGreen}`}>{s}</li>
                  ))}
                </ul>
              </div>
            )}
            {studentModel.experiences?.length > 0 && (
              <div className={styles.section}>
                <h3 className={styles.sectionTitle}>Experiences</h3>
                <ul className={styles.bulletList}>
                  {studentModel.experiences.map(e => <li key={e} className={styles.bulletItem}>{e}</li>)}
                </ul>
              </div>
            )}
            {studentModel.education?.length > 0 && (
              <div className={styles.section}>
                <h3 className={styles.sectionTitle}>Education</h3>
                <ul className={styles.bulletList}>
                  {studentModel.education.map(e => <li key={e} className={styles.bulletItem}>{e}</li>)}
                </ul>
              </div>
            )}
          </>
        ) : (
          <p className={styles.emptyNote}>No student profile data available.</p>
        )}
      </div>

      {/* Role Requirements */}
      <div className={styles.card}>
        <h2 className={styles.cardTitle}><span className={styles.dotPurple} />Role Requirements</h2>
        <p className={styles.cardSubtitle}>
          {roleSpec
            ? `${roleSpec.requirements?.length ?? 0} requirements for ${targetRole}`
            : 'From the role intake agent'}
        </p>
        {roleSpec?.requirements?.length > 0 ? (
          <div className={styles.reqTable}>
            <div className={styles.reqHeader}>
              <span className={styles.reqColName}>Requirement</span>
              <span className={styles.reqColCat}>Category</span>
              <span className={styles.reqColLevel}>Required Level</span>
            </div>
            {[...roleSpec.requirements]
              .sort((a, b) => b.importance - a.importance)
              .map((req, i) => (
                <div key={i} className={styles.reqRow}>
                  <span className={styles.reqColName}>
                    {req.req_summary}
                    {req.optional && <span className={styles.optionalBadge}>Optional</span>}
                  </span>
                  <span className={styles.reqColCat}>
                    <span className={styles.catBadge}>{CATEGORY_LABELS[req.category] ?? req.category}</span>
                  </span>
                  <span className={styles.reqColLevel}>
                    {levelBar(req.required_level)}
                    <span className={styles.levelNum}>{req.required_level.toFixed(1)}</span>
                  </span>
                </div>
              ))}
          </div>
        ) : (
          <p className={styles.emptyNote}>No role requirements data available.</p>
        )}
        {roleSpec?.assumptions?.length > 0 && (
          <div className={styles.section}>
            <h3 className={styles.sectionTitle}>Assumptions</h3>
            <ul className={styles.bulletList}>
              {roleSpec.assumptions.map((a, i) => <li key={i} className={styles.bulletItem}>{a}</li>)}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

/* ══════════════════════════════════════════════════════════════════════
   Gap Analysis Tab
   ══════════════════════════════════════════════════════════════════════ */
function GapAnalysisTab({ gapReport, evidenceItems }) {
  const evidenceById = new Map(
    (evidenceItems ?? [])
      .filter((item) => item?.id)
      .map((item) => [item.id, item])
  );

  return (
    <div className={styles.gapTabWrap}>
      <div className={styles.gapTabHeader}>
        <h2 className={styles.gapTabTitle}>Gap Analysis</h2>
        <p className={styles.gapTabSubtitle}>
          Skills and knowledge gaps identified between your profile and the target role
        </p>
        {gapReport?.summary && (
          <p className={styles.gapSummary}>{gapReport.summary}</p>
        )}
      </div>

      {gapReport?.gaps?.length > 0 ? (
        <div className={styles.gapGrid}>
          {[...gapReport.gaps]
            .sort((a, b) => b.weighted_gap - a.weighted_gap)
            .map((gap, i) => (
              (() => {
                const evidenceIds = gap.evidence_item_ids ?? [];
                const matchedEvidence = evidenceIds
                  .map((id) => evidenceById.get(id))
                  .filter(Boolean);

                return (
              <div key={i} className={styles.gapCard}>
                <div className={styles.gapCardHeader}>
                  <h3 className={styles.gapCardTitle}>{gap.summary}</h3>
                  <span className={`${styles.gapTypeBadge} ${styles[`gapType_${gap.gap_type}`] ?? ''}`}>
                    {GAP_TYPE_LABELS[gap.gap_type] ?? gap.gap_type}
                  </span>
                </div>
                <div className={styles.gapMeta}>
                  <span className={styles.catBadge}>{CATEGORY_LABELS[gap.category] ?? gap.category}</span>
                  {gap.gap_root_cause && (
                    <span className={styles.rootCause}>{ROOT_CAUSE_LABELS[gap.gap_root_cause] ?? gap.gap_root_cause}</span>
                  )}
                </div>
                <div className={styles.gapLevels}>
                  <div className={styles.gapLevelRow}>
                    <span className={styles.gapLevelLabel}>Required</span>
                    {levelBar(gap.required_level)}
                    <span className={styles.levelNum}>{gap.required_level.toFixed(1)}</span>
                  </div>
                  <div className={styles.gapLevelRow}>
                    <span className={styles.gapLevelLabel}>Current</span>
                    {levelBar(gap.student_level)}
                    <span className={styles.levelNum}>{gap.student_level.toFixed(1)}</span>
                  </div>
                </div>
                <div className={styles.evidenceBlock}>
                  <div className={styles.evidenceLabelRow}>
                    <span className={styles.evidenceLabel}>Supporting Evidence</span>
                    <span
                      className={styles.infoHint}
                      role="img"
                      aria-label={EVIDENCE_CONFIDENCE_HELP}
                      title={EVIDENCE_CONFIDENCE_HELP}
                    >
                      <svg
                        className={styles.infoHintIcon}
                        viewBox="0 0 24 24"
                        aria-hidden="true"
                      >
                        <circle cx="12" cy="12" r="9" />
                        <line x1="12" y1="10" x2="12" y2="16" />
                        <circle cx="12" cy="7" r="1" />
                      </svg>
                    </span>
                  </div>
                  {matchedEvidence.length > 0 ? (
                    <ul className={styles.evidenceList}>
                      {matchedEvidence.map((item, evIdx) => (
                        <li
                          key={item.id ?? `${i}-${evIdx}`}
                          className={styles.evidenceItem}
                        >
                          <div className={styles.evidenceItemHeader}>
                            <span className={styles.evidenceType}>{item.item_type ?? 'claim'}</span>
                            {typeof item.confidence === 'number' && (
                              <span className={styles.evidenceConfidence}>
                                {Math.round(item.confidence * 100)}% confidence
                              </span>
                            )}
                          </div>
                          <p className={styles.evidenceText}>{item.summary}</p>
                          {item.snippet && (
                            <p className={styles.evidenceSnippet}>{item.snippet}</p>
                          )}
                        </li>
                      ))}
                    </ul>
                  ) : evidenceIds.length > 0 ? (
                    <p className={styles.evidenceMissing}>
                      Evidence is linked for this gap, but details were not available in the final state.
                    </p>
                  ) : (
                    <p className={styles.evidenceMissing}>No direct evidence linked to this gap.</p>
                  )}
                </div>
                {gap.knowledge_prerequisites?.length > 0 && (
                  <div className={styles.prereqs}>
                    <span className={styles.prereqLabel}>Prerequisites:</span>
                    <ul className={styles.prereqList}>
                      {gap.knowledge_prerequisites.map((kp, j) => (
                        <li key={j} className={styles.prereqItem}>
                          {kp.concept}
                          {kp.is_foundational && (
                            <span className={styles.foundationalBadge}>foundational</span>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
                );
              })()
            ))}
        </div>
      ) : (
        <p className={styles.emptyNote}>No gap analysis data available.</p>
      )}
    </div>
  );
}

/* ══════════════════════════════════════════════════════════════════════
   Pathway Plan Tab — Visual step-by-step roadmap
   ══════════════════════════════════════════════════════════════════════ */
function PathwayPlanTab({ plan }) {
  const phases = plan?.phases ?? [];

  const [openPhases, setOpenPhases] = useState(() => new Set(phases.map((_, i) => i)));

  const toggle = (idx) => setOpenPhases(prev => {
    const next = new Set(prev);
    next.has(idx) ? next.delete(idx) : next.add(idx);
    return next;
  });

  const expandAll  = () => setOpenPhases(new Set(phases.map((_, i) => i)));
  const collapseAll = () => setOpenPhases(new Set());

  if (phases.length === 0) {
    return (
      <div className={styles.placeholderWrap}>
        <div className={styles.placeholderCard}>
          <div className={styles.placeholderIcon}>
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
            </svg>
          </div>
          <h2 className={styles.placeholderTitle}>No Pathway Plan Available</h2>
          <p className={styles.placeholderText}>
            The pathway planning agent did not generate a plan for your profile.
            Ensure your constraints are set correctly and try again.
          </p>
        </div>
      </div>
    );
  }

  const totalActions  = phases.reduce((s, p) => s + (p.learning_actions?.length ?? 0), 0);
  const totalWeeks    = plan.timeline_weeks ?? phases.reduce((s, p) => s + (p.weeks ?? 0), 0);

  return (
    <div className={styles.pathwayWrap}>

      {/* ── Summary banner ───────────────────────────────────────── */}
      <div className={styles.pathwaySummary}>
        <div className={styles.pathwaySummaryLeft}>
          <span className={styles.pathwaySummaryBadge}>Your Roadmap</span>
          <h2 className={styles.pathwaySummaryTitle}>{totalWeeks}-Week Learning Pathway</h2>
          <p className={styles.pathwaySummaryMeta}>
            {phases.length} phases · {totalActions} learning actions
          </p>
        </div>

        {/* Phase pill nav */}
        <div className={styles.phasePills}>
          {phases.map((phase, i) => (
            <button
              key={i}
              className={styles.phasePill}
              style={{ '--pc': PHASE_COLORS[i % PHASE_COLORS.length] }}
              onClick={() =>
                document.getElementById(`phase-${i}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
              }
              title={phase.title}
            >
              <span className={styles.phasePillNum}>{i + 1}</span>
              <span className={styles.phasePillWeeks}>{phase.weeks}w</span>
            </button>
          ))}
        </div>

        <div className={styles.pathwayControls}>
          <button className={styles.ctrlBtn} onClick={expandAll}>Expand All</button>
          <button className={styles.ctrlBtn} onClick={collapseAll}>Collapse All</button>
        </div>
      </div>

      {/* ── Timeline ────────────────────────────────────────────── */}
      <div className={styles.timeline}>
        {phases.map((phase, phaseIdx) => {
          const color   = PHASE_COLORS[phaseIdx % PHASE_COLORS.length];
          const isOpen  = openPhases.has(phaseIdx);
          const actions = phase.learning_actions ?? [];

          return (
            <div key={phaseIdx} className={styles.timelineEntry}>

              {/* Phase card */}
              <div
                id={`phase-${phaseIdx}`}
                className={styles.phaseCard}
                style={{ '--pc': color }}
              >
                {/* Clickable header */}
                <button
                  className={styles.phaseToggle}
                  onClick={() => toggle(phaseIdx)}
                  aria-expanded={isOpen}
                >
                  <div className={styles.phaseNode} style={{ background: color }}>
                    {phaseIdx + 1}
                  </div>

                  <div className={styles.phaseToggleBody}>
                    <div className={styles.phaseToggleMeta}>
                      <span className={styles.phaseWeekBadge} style={{ background: `${color}18`, color }}>
                        {phase.weeks} {phase.weeks === 1 ? 'week' : 'weeks'}
                      </span>
                      {actions.length > 0 && (
                        <span className={styles.phaseActionsBadge}>
                          {actions.length} {actions.length === 1 ? 'action' : 'actions'}
                        </span>
                      )}
                    </div>
                    <h3 className={styles.phaseCardTitle}>{phase.title}</h3>
                    {!isOpen && phase.outcome && (
                      <p className={styles.phasePreview}>{phase.outcome}</p>
                    )}
                  </div>

                  <span className={`${styles.chevron} ${isOpen ? styles.chevronOpen : ''}`}>
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="6 9 12 15 18 9" />
                    </svg>
                  </span>
                </button>

                {/* Collapsible body */}
                {isOpen && (
                  <div className={styles.phaseBody}>

                    {/* Goal callout */}
                    {phase.outcome && (
                      <div className={styles.outcomeCallout} style={{ borderColor: color, background: `${color}0a` }}>
                        <span className={styles.outcomeIcon} style={{ color }}>🎯</span>
                        <div>
                          <span className={styles.outcomeLabel}>Phase Goal</span>
                          <p className={styles.outcomeText}>{phase.outcome}</p>
                        </div>
                      </div>
                    )}

                    {/* Rationale */}
                    {phase.rationale && (
                      <div className={styles.rationaleBlock}>
                        <span className={styles.blockLabel}>Why this phase</span>
                        <p className={styles.rationaleText}>{phase.rationale}</p>
                      </div>
                    )}

                    {/* Learning actions — numbered steps */}
                    {actions.length > 0 && (
                      <div className={styles.stepsBlock}>
                        <h4 className={styles.blockTitle}>
                          <span className={styles.blockTitleDot} style={{ background: color }} />
                          Step-by-Step Actions
                        </h4>
                        <div className={styles.stepsList}>
                          {actions.map((action, ai) => (
                            <div key={ai} className={styles.stepItem}>
                              <div className={styles.stepNumWrap}>
                                <div className={styles.stepNum} style={{ background: `${color}15`, color }}>
                                  {ai + 1}
                                </div>
                                {ai < actions.length - 1 && (
                                  <div className={styles.stepConnector} style={{ background: `${color}30` }} />
                                )}
                              </div>
                              <div className={styles.stepContent}>
                                <div className={styles.stepHeader}>
                                  <h5 className={styles.stepTitle}>{action.title}</h5>
                                  {action.bloom_level && (
                                    <span
                                      className={styles.bloomBadge}
                                      style={{ background: BLOOM_COLORS[action.bloom_level] ?? '#6b7280' }}
                                    >
                                      {action.bloom_level}
                                    </span>
                                  )}
                                </div>
                                {action.description && (
                                  <p className={styles.stepSummary}>{action.description}</p>
                                )}
                                {action.stack?.length > 0 && (
                                  <div className={styles.stackBlock}>
                                    {action.stack.map((tool, ti) => (
                                      <span
                                        key={ti}
                                        className={styles.stackChip}
                                        style={{ background: `${color}15`, color, borderColor: `${color}30` }}
                                      >
                                        {tool}
                                      </span>
                                    ))}
                                  </div>
                                )}
                                {action.rationale && (
                                  <p className={styles.stepRationale} style={{ borderLeftColor: color }}>
                                    {action.rationale}
                                  </p>
                                )}
                                {action.example_resources?.length > 0 && (
                                  <div className={styles.stepResources}>
                                    {action.example_resources.map((r, ri) => (
                                      <ResourceChip key={ri} resource={r} />
                                    ))}
                                  </div>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Checkpoint */}
                    {phase.checkpoint && (
                      <div className={styles.checkpointBlock} style={{ borderColor: color, background: `${color}06` }}>
                        <span className={styles.checkpointIcon} style={{ background: color }}>✓</span>
                        <div>
                          <span className={styles.checkpointLabel}>Checkpoint</span>
                          <p className={styles.checkpointText}>{phase.checkpoint}</p>
                        </div>
                      </div>
                    )}

                    {/* Resume updates */}
                    {phase.resume_updates?.length > 0 && (
                      <div className={styles.resumeBlock}>
                        <h4 className={styles.blockTitle}>
                          <span className={styles.blockTitleDot} style={{ background: '#10b981' }} />
                          Resume Updates
                        </h4>
                        <ul className={styles.resumeList}>
                          {phase.resume_updates.map((u, i) => (
                            <li key={i} className={styles.resumeItem}>{u}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {/* Gaps addressed */}
                    {phase.addresses_gaps?.length > 0 && (
                      <div className={styles.gapsAddressedBlock}>
                        <h4 className={styles.blockTitle}>
                          <span className={styles.blockTitleDot} style={{ background: '#f59e0b' }} />
                          Gaps Addressed
                        </h4>
                        <div className={styles.gapTags}>
                          {phase.addresses_gaps.map((g, i) => (
                            <span
                              key={i}
                              className={styles.gapTag}
                              style={{ borderColor: `${color}40`, background: `${color}08`, color }}
                            >
                              {g}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* Connector between phases */}
              {phaseIdx < phases.length - 1 && (
                <div className={styles.phaseConnector}>
                  <div
                    className={styles.connectorLine}
                    style={{
                      background: `linear-gradient(to bottom, ${color}, ${PHASE_COLORS[(phaseIdx + 1) % PHASE_COLORS.length]})`,
                    }}
                  />
                  <div
                    className={styles.connectorArrow}
                    style={{ borderTopColor: PHASE_COLORS[(phaseIdx + 1) % PHASE_COLORS.length] }}
                  />
                </div>
              )}
            </div>
          );
        })}

        {/* End node */}
        <div className={styles.pathwayEnd}>
          <div className={styles.pathwayEndCircle}>🎯</div>
          <span className={styles.pathwayEndLabel}>Career Ready</span>
        </div>
      </div>
    </div>
  );
}

/* ── Resource chip ───────────────────────────────────────────────────── */
function ResourceChip({ resource }) {
  const icon = RESOURCE_ICONS[resource.resource_type] ?? '📌';
  return (
    <a
      href={resource.url || '#'}
      target={resource.url ? '_blank' : undefined}
      rel={resource.url ? 'noopener noreferrer' : undefined}
      className={styles.resourceChip}
      title={resource.provider ? `${resource.provider} · ${resource.resource_type}` : resource.resource_type}
    >
      <span>{icon}</span>
      <span className={styles.chipTitle}>{resource.title}</span>
      {resource.is_free && <span className={styles.chipFree}>Free</span>}
      {resource.estimated_hours && (
        <span className={styles.chipHours}>{resource.estimated_hours}h</span>
      )}
    </a>
  );
}
