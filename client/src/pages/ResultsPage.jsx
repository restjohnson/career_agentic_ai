import { useState, useCallback } from 'react';
import { Link, useLocation } from 'react-router-dom';
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
  const targetRole = finalState?.desired_role ?? 'Unknown Role';

  return { studentModel, roleSpec, gapReport, targetRole };
}

/* ══════════════════════════════════════════════════════════════════════
   Results Page
   ══════════════════════════════════════════════════════════════════════ */
export default function ResultsPage() {
  const location = useLocation();
  const finalState = location.state?.finalState ?? null;
  const { studentModel, roleSpec, gapReport, targetRole } =
    extractData(finalState);

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
          <PathwayPlanTab />
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
   Pathway Plan Tab  (placeholder)
   ══════════════════════════════════════════════════════════════════════ */
function PathwayPlanTab() {
  return (
    <div className={styles.placeholderWrap}>
      <div className={styles.placeholderCard}>
        <div className={styles.placeholderIcon}>
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
          </svg>
        </div>
        <h2 className={styles.placeholderTitle}>Pathway Plan Coming Soon</h2>
        <p className={styles.placeholderText}>
          The pathway planning agent is currently being designed. Once complete,
          this tab will contain your personalised learning pathway with
          recommended courses, projects, milestones, and a week-by-week schedule
          to close your identified gaps.
        </p>
      </div>
    </div>
  );
}
