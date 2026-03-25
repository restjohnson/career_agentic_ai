import { Link, useLocation } from 'react-router-dom';
import styles from './ResultsPage.module.css';

/* ── Mock fallback data ──────────────────────────────────────────── */
const MOCK_SKILLS_FOUND  = ['Python', 'React', 'Git', 'REST APIs', 'SQL basics', 'Agile / Scrum'];
const MOCK_SKILLS_NEEDED = ['System Design', 'Docker / CI-CD', 'TypeScript', 'Cloud (AWS)', 'GraphQL', 'Testing (Jest)'];
const MOCK_PATHWAY = [
  { phase: 1, title: 'Foundations',             duration: '4 weeks', status: 'complete', items: ['Python deep-dive (OOP, async)', 'SQL & relational data modelling', 'Git workflow & branching strategy'] },
  { phase: 2, title: 'Core Engineering',         duration: '6 weeks', status: 'active',   items: ['TypeScript fundamentals', 'REST → GraphQL API design', 'Testing strategies (Jest, Pytest)'] },
  { phase: 3, title: 'Cloud & DevOps',           duration: '5 weeks', status: 'upcoming', items: ['Docker & containerisation', 'AWS core services (S3, EC2, Lambda)', 'CI/CD pipeline setup'] },
  { phase: 4, title: 'System Design & Portfolio', duration: '4 weeks', status: 'upcoming', items: ['System design patterns', 'Capstone project build', 'Resume & portfolio final review'] },
];

function derivePhaseStatus(index, total) {
  if (index === 0) return 'complete';
  if (index === 1) return 'active';
  return 'upcoming';
}

function buildFromFinalState(finalState) {
  const skillsFound  = finalState?.student_model?.skills ?? MOCK_SKILLS_FOUND;
  const skillsNeeded = finalState?.gap_report?.gaps?.map((g) => g.summary) ?? MOCK_SKILLS_NEEDED;
  const targetRole   = finalState?.desired_role ?? 'Software Engineer';
  const timelineWeeks = finalState?.plan?.timeline_weeks ?? 19;

  const phases = finalState?.plan?.phases?.length
    ? finalState.plan.phases.map((p, i, arr) => ({
        phase:    i + 1,
        title:    p.title,
        duration: `${p.weeks} week${p.weeks !== 1 ? 's' : ''}`,
        status:   derivePhaseStatus(i, arr.length),
        items:    p.learning_actions?.map((a) => a.title) ?? p.resources?.map((r) => r.title) ?? [],
      }))
    : MOCK_PATHWAY;

  const totalSkills   = skillsFound.length + skillsNeeded.length;
  const readinessPct  = totalSkills > 0 ? Math.round((skillsFound.length / totalSkills) * 100) : 42;

  return { skillsFound, skillsNeeded, targetRole, timelineWeeks, phases, readinessPct };
}

/* ══════════════════════════════════════════════════════════════════
   Results Page Component
   ══════════════════════════════════════════════════════════════════ */
export default function ResultsPage() {
  const location   = useLocation();
  const finalState = location.state?.finalState ?? null;
  const { skillsFound, skillsNeeded, targetRole, timelineWeeks, phases, readinessPct } =
    buildFromFinalState(finalState);

  return (
    <div className={styles.page}>

      {/* ── Page header ──────────────────────────────────────────── */}
      <div className={styles.pageHeader}>
        <div className="container">
          <div className={styles.headerRow}>
            <div>
              <span className={styles.headerBadge}>🎯 Career Plan Ready</span>
              <h1 className={styles.pageTitle}>Your Career Blueprint</h1>
              <p className={styles.pageMeta}>
                Target Role: <strong>{targetRole}</strong>
                &nbsp;·&nbsp; {timelineWeeks} weeks
              </p>
            </div>
            <div className={styles.headerActions}>
              <button className={styles.downloadBtn}>⬇ Download PDF</button>
              <Link to="/upload" className={styles.restartBtn}>Start Over</Link>
            </div>
          </div>
        </div>
      </div>

      {/* ── Dashboard ────────────────────────────────────────────── */}
      <div className="container">
        <div className={styles.dashboard}>

          {/* Left column — Gap Analysis */}
          <div className={styles.leftCol}>

            {/* Readiness score */}
            <div className={styles.card}>
              <h2 className={styles.cardTitle}>Overall Readiness</h2>
              <div className={styles.readinessRow}>
                <div className={styles.readinessScore}>{readinessPct}%</div>
                <div className={styles.readinessRight}>
                  <div className={styles.readinessTrack}>
                    <div className={styles.readinessFill} style={{ width: `${readinessPct}%` }} />
                  </div>
                  <p className={styles.readinessNote}>
                    Strong foundations — gap-filling plan ready.
                  </p>
                </div>
              </div>
            </div>

            {/* Skills found */}
            <div className={styles.card}>
              <h2 className={styles.cardTitle}>
                <span className={styles.dotGreen} />Skills Found
              </h2>
              <ul className={styles.skillList}>
                {skillsFound.map((s) => (
                  <li key={s} className={`${styles.skillTag} ${styles.skillTagGreen}`}>
                    <span className={styles.skillDot}>✓</span>{s}
                  </li>
                ))}
              </ul>
            </div>

            {/* Skills to acquire */}
            <div className={styles.card}>
              <h2 className={styles.cardTitle}>
                <span className={styles.dotOrange} />Skills to Acquire
              </h2>
              <ul className={styles.skillList}>
                {skillsNeeded.map((s) => (
                  <li key={s} className={`${styles.skillTag} ${styles.skillTagOrange}`}>
                    <span className={styles.skillDot}>+</span>{s}
                  </li>
                ))}
              </ul>
            </div>

          </div>

          {/* Right column — Pathway timeline */}
          <div className={styles.rightCol}>
            <div className={styles.card}>
              <h2 className={styles.cardTitle}>Pathway Plan</h2>
              <div className={styles.timeline}>
                {phases.map((phase) => (
                  <PhaseCard key={phase.phase} {...phase} />
                ))}
              </div>
            </div>
          </div>

        </div>
      </div>
    </div>
  );
}

/* ── PhaseCard ───────────────────────────────────────────────────── */
function PhaseCard({ phase, title, duration, status, items }) {
  const statusMeta = {
    complete: { cls: styles.phaseComplete, label: '✓ Complete',     dot: styles.phaseDotGreen  },
    active:   { cls: styles.phaseActive,   label: '◉ In Progress',  dot: styles.phaseDotBlue   },
    upcoming: { cls: styles.phaseUpcoming, label: '○ Upcoming',     dot: styles.phaseDotGrey   },
  }[status];

  return (
    <div className={`${styles.phase} ${statusMeta.cls}`}>
      <div className={styles.phaseLeft}>
        <div className={`${styles.phaseDot} ${statusMeta.dot}`}>{phase}</div>
        <div className={styles.phaseLine} />
      </div>
      <div className={styles.phaseBody}>
        <div className={styles.phaseTop}>
          <h3 className={styles.phaseTitle}>{title}</h3>
          <div className={styles.phaseTags}>
            <span className={styles.phaseDuration}>{duration}</span>
            <span className={`${styles.phaseStatus} ${statusMeta.cls}`}>{statusMeta.label}</span>
          </div>
        </div>
        <ul className={styles.phaseItems}>
          {items.map((item) => (
            <li key={item} className={styles.phaseItem}>
              <span className={styles.phaseItemBullet} />
              {item}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
