import { useState, useCallback, useEffect } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import styles from './ResultsPage.module.css';
import { downloadReport } from '../reportTemplate';

/* ── Helpers ────────────────────────────────────────────────────────── */

const CATEGORY_LABELS = {
  skill: 'Skill',
  task: 'Task',
  tech: 'Technology',
  hot_technology: 'Hot Tech',
  knowledge: 'Knowledge',
};

const GAP_TYPE_LABELS = {
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

function levelBar(value, max = 4) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className={styles.levelTrack}>
      <div className={styles.levelFill} style={{ width: `${pct}%` }} />
    </div>
  );
}

/* ── Data extraction from finalState ────────────────────────────────── */

function extractData(finalState) {
  const studentModel = finalState?.student_model ?? null;
  const roleSpec = finalState?.role_spec ?? null;
  const gapReport = finalState?.gap_report ?? null;
  const plan = finalState?.plan ?? null;
  const targetRole = finalState?.desired_role ?? 'Unknown Role';

  return { studentModel, roleSpec, gapReport, plan, targetRole };
}

/* ══════════════════════════════════════════════════════════════════════
   Results Page
   ══════════════════════════════════════════════════════════════════════ */
export default function ResultsPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const storedFinalState = (() => {
    try {
      return JSON.parse(sessionStorage.getItem('career_flow_final_state') ?? 'null');
    } catch {
      return null;
    }
  })();
  const finalState = location.state?.finalState ?? storedFinalState;
  const { studentModel, roleSpec, gapReport, plan, targetRole } =
    extractData(finalState);

  useEffect(() => {
    if (!finalState) {
      navigate('/upload', { replace: true });
    }
  }, [finalState, navigate]);

  const [activeTab, setActiveTab] = useState('career');

  const handleDownloadReport = useCallback(() => {
    downloadReport({ studentModel, roleSpec, gapReport, targetRole });
  }, [studentModel, roleSpec, gapReport, targetRole]);

  return (
    <div className={styles.page}>
      {/* ── Page header ──────────────────────────────────────────── */}
      <div className={styles.pageHeader}>
        <div className={styles.headerInner}>
          <div className={styles.headerRow}>
            <div>
              <span className={styles.headerBadge}>Analysis Complete</span>
              <h1 className={styles.pageTitle}>Your Career Report</h1>
              <p className={styles.pageMeta}>
                Target Role: <strong>{roleSpec?.canonical_role_title ?? targetRole}</strong>
                {roleSpec?.matched_onet_code && (
                  <span className={styles.onetCode}> (O*NET {roleSpec.matched_onet_code})</span>
                )}
              </p>
            </div>
            <div className={styles.headerActions}>
              <button
                type="button"
                onClick={handleDownloadReport}
                className={styles.downloadBtn}
              >
                Download Report
              </button>
              <Link to="/upload" className={styles.restartBtn}>Start Over</Link>
            </div>
          </div>

          {/* ── Tab bar ──────────────────────────────────────────── */}
          <div className={styles.tabBar}>
            <button
              className={`${styles.tab} ${activeTab === 'career' ? styles.tabActive : ''}`}
              onClick={() => setActiveTab('career')}
            >
              Career Plan
            </button>
            <button
              className={`${styles.tab} ${activeTab === 'pathway' ? styles.tabActive : ''}`}
              onClick={() => setActiveTab('pathway')}
            >
              Pathway Plan
            </button>
          </div>
        </div>
      </div>

      {/* ── Tab content ──────────────────────────────────────────── */}
      <div className={styles.container}>
        {activeTab === 'career' ? (
          <CareerPlanTab
            studentModel={studentModel}
            roleSpec={roleSpec}
            gapReport={gapReport}
          />
        ) : (
          <PathwayPlanTab plan={plan} />
        )}
      </div>
    </div>
  );
}

/* ══════════════════════════════════════════════════════════════════════
   Career Plan Tab
   ══════════════════════════════════════════════════════════════════════ */
function CareerPlanTab({ studentModel, roleSpec, gapReport }) {
  return (
    <div className={styles.careerGrid}>
      {/* ── Student Model ─────────────────────────────────────────── */}
      <div className={styles.card}>
        <h2 className={styles.cardTitle}>
          <span className={styles.dotBlue} />Student Profile
        </h2>
        <p className={styles.cardSubtitle}>Extracted from your uploaded evidence</p>

        {studentModel ? (
          <>
            {studentModel.skills?.length > 0 && (
              <div className={styles.section}>
                <h3 className={styles.sectionTitle}>Skills</h3>
                <ul className={styles.tagList}>
                  {studentModel.skills.map((s) => (
                    <li key={s} className={`${styles.tag} ${styles.tagGreen}`}>{s}</li>
                  ))}
                </ul>
              </div>
            )}

            {studentModel.experiences?.length > 0 && (
              <div className={styles.section}>
                <h3 className={styles.sectionTitle}>Experiences</h3>
                <ul className={styles.bulletList}>
                  {studentModel.experiences.map((e) => (
                    <li key={e} className={styles.bulletItem}>{e}</li>
                  ))}
                </ul>
              </div>
            )}

            {studentModel.education?.length > 0 && (
              <div className={styles.section}>
                <h3 className={styles.sectionTitle}>Education</h3>
                <ul className={styles.bulletList}>
                  {studentModel.education.map((e) => (
                    <li key={e} className={styles.bulletItem}>{e}</li>
                  ))}
                </ul>
              </div>
            )}
          </>
        ) : (
          <p className={styles.emptyNote}>No student model data available.</p>
        )}
      </div>

      {/* ── Role Requirements ─────────────────────────────────────── */}
      <div className={styles.card}>
        <h2 className={styles.cardTitle}>
          <span className={styles.dotPurple} />Role Requirements
        </h2>
        <p className={styles.cardSubtitle}>
          {roleSpec
            ? `${roleSpec.requirements?.length ?? 0} requirements identified for ${roleSpec.canonical_role_title}`
            : 'From the role intake agent'}
        </p>

        {roleSpec?.requirements?.length > 0 ? (
          <div className={styles.reqTable}>
            <div className={styles.reqHeader}>
              <span className={styles.reqColName}>Requirement</span>
              <span className={styles.reqColCat}>Category</span>
              <span className={styles.reqColLevel}>Level</span>
            </div>
            {roleSpec.requirements
              .sort((a, b) => b.importance - a.importance)
              .map((req, i) => (
                <div key={i} className={styles.reqRow}>
                  <span className={styles.reqColName}>
                    {req.req_summary}
                    {req.optional && <span className={styles.optionalBadge}>Optional</span>}
                  </span>
                  <span className={styles.reqColCat}>
                    <span className={styles.catBadge}>
                      {CATEGORY_LABELS[req.category] ?? req.category}
                    </span>
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
              {roleSpec.assumptions.map((a, i) => (
                <li key={i} className={styles.bulletItem}>{a}</li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* ── Gap Analysis ──────────────────────────────────────────── */}
      <div className={`${styles.card} ${styles.cardFull}`}>
        <h2 className={styles.cardTitle}>
          <span className={styles.dotOrange} />Gap Analysis
        </h2>
        {gapReport?.summary && (
          <p className={styles.gapSummary}>{gapReport.summary}</p>
        )}

        {gapReport?.gaps?.length > 0 ? (
          <div className={styles.gapGrid}>
            {gapReport.gaps
              .sort((a, b) => b.weighted_gap - a.weighted_gap)
              .map((gap, i) => (
                <div key={i} className={styles.gapCard}>
                  <div className={styles.gapCardHeader}>
                    <h3 className={styles.gapCardTitle}>{gap.summary}</h3>
                    <span className={`${styles.gapTypeBadge} ${styles[`gapType_${gap.gap_type}`] ?? ''}`}>
                      {GAP_TYPE_LABELS[gap.gap_type] ?? gap.gap_type}
                    </span>
                  </div>

                  <div className={styles.gapMeta}>
                    <span className={styles.catBadge}>
                      {CATEGORY_LABELS[gap.category] ?? gap.category}
                    </span>
                    {gap.gap_root_cause && (
                      <span className={styles.rootCause}>
                        {ROOT_CAUSE_LABELS[gap.gap_root_cause] ?? gap.gap_root_cause}
                      </span>
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
                      {levelBar(gap.student_score)}
                      <span className={styles.levelNum}>{gap.student_score.toFixed(1)}</span>
                    </div>
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
              ))}
          </div>
        ) : (
          <p className={styles.emptyNote}>No gap analysis data available.</p>
        )}
      </div>
    </div>
  );
}

/* ══════════════════════════════════════════════════════════════════════
   Pathway Plan Tab
   ══════════════════════════════════════════════════════════════════════ */

const RESOURCE_TYPE_ICONS = {
  tutorial: '📚',
  project: '🔨',
  open_source: '⭐',
  workshop: '🎓',
  certification: '🏆',
  internship: '💼',
  online_course: '🎬',
  documentation: '📖',
};

const BLOOM_LEVEL_COLORS = {
  remember: '#6b7280',
  understand: '#3b82f6',
  apply: '#10b981',
  analyse: '#f59e0b',
  evaluate: '#ef4444',
  create: '#8b5cf6',
};

function PathwayPlanTab({ plan }) {
  if (!plan || !plan.phases || plan.phases.length === 0) {
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
            This may occur if all requirements are already met or if the agent
            encountered an issue during planning.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.pathwayContainer}>
      {/* ── Timeline overview ──────────────────────────────────────── */}
      <div className={styles.card}>
        <h2 className={styles.cardTitle}>
          <span className={styles.dotPurple} />Learning Pathway
        </h2>
        <p className={styles.cardSubtitle}>
          {plan.timeline_weeks}-week plan with {plan.phases.length} phases
        </p>
      </div>

      {/* ── Phases ─────────────────────────────────────────────────── */}
      <div className={styles.phasesTimeline}>
        {plan.phases.map((phase, phaseIdx) => (
          <div key={phaseIdx} className={styles.phaseBlock}>
            {/* Phase header */}
            <div className={styles.phaseHeader}>
              <div className={styles.phaseNumber}>{phaseIdx + 1}</div>
              <div className={styles.phaseInfo}>
                <h3 className={styles.phaseTitle}>{phase.title}</h3>
                <p className={styles.phaseDuration}>
                  {phase.weeks} {phase.weeks === 1 ? 'week' : 'weeks'}
                </p>
              </div>
            </div>

            {/* Phase details */}
            <div className={styles.phaseBody}>
              {phase.rationale && (
                <div className={styles.phaseSection}>
                  <h4 className={styles.phaseSectionTitle}>Rationale</h4>
                  <p className={styles.phaseSectionText}>{phase.rationale}</p>
                </div>
              )}

              {phase.outcome && (
                <div className={styles.phaseSection}>
                  <h4 className={styles.phaseSectionTitle}>Outcome</h4>
                  <p className={styles.phaseSectionText}>{phase.outcome}</p>
                </div>
              )}

              {phase.checkpoint && (
                <div className={styles.phaseSection}>
                  <h4 className={styles.phaseSectionTitle}>Checkpoint</h4>
                  <p className={styles.phaseSectionText}>{phase.checkpoint}</p>
                </div>
              )}

              {/* Learning actions */}
              {phase.learning_actions && phase.learning_actions.length > 0 && (
                <div className={styles.phaseSection}>
                  <h4 className={styles.phaseSectionTitle}>Learning Actions</h4>
                  <div className={styles.actionsList}>
                    {phase.learning_actions.map((action, actionIdx) => (
                      <div key={actionIdx} className={styles.actionCard}>
                        <div className={styles.actionHeader}>
                          <h5 className={styles.actionTitle}>{action.title}</h5>
                          <span
                            className={styles.bloomBadge}
                            style={{ backgroundColor: BLOOM_LEVEL_COLORS[action.bloom_level] || '#6b7280' }}
                          >
                            {action.bloom_level}
                          </span>
                        </div>
                        <p className={styles.actionSummary}>{action.summary}</p>
                        {action.rationale && (
                          <p className={styles.actionRationale}>{action.rationale}</p>
                        )}

                        {/* Resources for this action */}
                        {action.example_resources && action.example_resources.length > 0 && (
                          <div className={styles.resourcesList}>
                            <span className={styles.resourcesLabel}>Recommended resources:</span>
                            <div className={styles.resourceItems}>
                              {action.example_resources.map((resource, resIdx) => (
                                <ResourceTag key={resIdx} resource={resource} />
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Resume updates */}
              {phase.resume_updates && phase.resume_updates.length > 0 && (
                <div className={styles.phaseSection}>
                  <h4 className={styles.phaseSectionTitle}>Resume Updates</h4>
                  <ul className={styles.bulletList}>
                    {phase.resume_updates.map((update, idx) => (
                      <li key={idx} className={styles.bulletItem}>{update}</li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Gaps addressed */}
              {phase.addresses_gaps && phase.addresses_gaps.length > 0 && (
                <div className={styles.phaseSection}>
                  <h4 className={styles.phaseSectionTitle}>Gaps Addressed</h4>
                  <ul className={styles.gapsList}>
                    {phase.addresses_gaps.map((gap, idx) => (
                      <li key={idx} className={styles.gapItem}>{gap}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ResourceTag({ resource }) {
  const icon = RESOURCE_TYPE_ICONS[resource.resource_type] || '📌';

  return (
    <a
      href={resource.url || '#'}
      target={resource.url ? '_blank' : undefined}
      rel={resource.url ? 'noopener noreferrer' : undefined}
      className={styles.resourceTag}
      title={resource.provider ? `${resource.provider} • ${resource.resource_type}` : resource.resource_type}
    >
      <span className={styles.resourceIcon}>{icon}</span>
      <span className={styles.resourceTitle}>{resource.title}</span>
      {resource.is_free && <span className={styles.freeLabel}>Free</span>}
      {resource.estimated_hours && (
        <span className={styles.hoursLabel}>{resource.estimated_hours}h</span>
      )}
    </a>
  );
}
