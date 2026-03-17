import { Link } from 'react-router-dom';
import styles from './ResultsPage.module.css';

/* ── Mock data ───────────────────────────────────────────────────── */
const SKILLS_FOUND = [
  'Python', 'React', 'Git', 'REST APIs', 'SQL basics', 'Agile / Scrum',
];

const SKILLS_NEEDED = [
  'System Design', 'Docker / CI-CD', 'TypeScript', 'Cloud (AWS)', 'GraphQL', 'Testing (Jest)',
];

const PATHWAY = [
  {
    phase: 1,
    title: 'Foundations',
    duration: '4 weeks',
    status: 'complete',
    items: [
      'Python deep-dive (OOP, async)',
      'SQL & relational data modelling',
      'Git workflow & branching strategy',
    ],
  },
  {
    phase: 2,
    title: 'Core Engineering',
    duration: '6 weeks',
    status: 'active',
    items: [
      'TypeScript fundamentals',
      'REST → GraphQL API design',
      'Testing strategies (Jest, Pytest)',
    ],
  },
  {
    phase: 3,
    title: 'Cloud & DevOps',
    duration: '5 weeks',
    status: 'upcoming',
    items: [
      'Docker & containerisation',
      'AWS core services (S3, EC2, Lambda)',
      'CI/CD pipeline setup',
    ],
  },
  {
    phase: 4,
    title: 'System Design & Portfolio',
    duration: '4 weeks',
    status: 'upcoming',
    items: [
      'System design patterns',
      'Capstone project build',
      'Resume & portfolio final review',
    ],
  },
];

/* ══════════════════════════════════════════════════════════════════
   Results Page Component
   ══════════════════════════════════════════════════════════════════ */
export default function ResultsPage() {
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
                Target Role: <strong>Software Engineer</strong>
                &nbsp;·&nbsp; 19 weeks &nbsp;·&nbsp; 10 hrs / week
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
                <div className={styles.readinessScore}>42%</div>
                <div className={styles.readinessRight}>
                  <div className={styles.readinessTrack}>
                    <div className={styles.readinessFill} style={{ width: '42%' }} />
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
                {SKILLS_FOUND.map((s) => (
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
                {SKILLS_NEEDED.map((s) => (
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
                {PATHWAY.map((phase) => (
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
