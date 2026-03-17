import { Link } from 'react-router-dom';
import styles from './LandingPage.module.css';

/* ── Icon helpers (inline SVG so no icon lib needed) ─────────────────────── */
const Icon = ({ path, size = 24, color = 'currentColor' }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke={color}
    strokeWidth={2}
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <path d={path} />
  </svg>
);

const ICONS = {
  upload:   'M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12',
  target:   'M12 22c5.52 0 10-4.48 10-10S17.52 2 12 2 2 6.48 2 12s4.48 10 10 10zm0-6a4 4 0 1 0 0-8 4 4 0 0 0 0 8zm0-2a2 2 0 1 1 0-4 2 2 0 0 1 0 4',
  chart:    'M18 20V10M12 20V4M6 20v-6',
  map:      'M3 11l19-9-9 19-2-8-8-2z',
  check:    'M22 11.08V12a10 10 0 1 1-5.93-9.14M22 4 12 14.01l-3-3',
  arrow:    'M5 12h14M12 5l7 7-7 7',
  sparkle:  'M12 3l1.88 5.76H20l-4.94 3.59 1.88 5.76L12 14.52l-4.94 3.59 1.88-5.76L4 8.76h6.12L12 3z',
  brain:    'M12 2a4 4 0 0 1 4 4c1.66.56 3 2.13 3 4 0 1.23-.52 2.33-1.35 3.12A3.97 3.97 0 0 1 19 16a4 4 0 0 1-4 4H9a4 4 0 0 1-4-4c0-.83.25-1.6.68-2.24C4.73 12.86 4 11.51 4 10c0-1.87 1.34-3.44 3-4a4 4 0 0 1 4-4h1z',
  clock:    'M12 22c5.52 0 10-4.48 10-10S17.52 2 12 2 2 6.48 2 12s4.48 10 10 10zm0-6v-4l3-3',
  users:    'M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zm14 10v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75',
};

/* ── Features data ──────────────────────────────────────────────────────── */
const FEATURES = [
  {
    icon: 'brain',
    color: 'blue',
    title: 'AI-Powered Gap Analysis',
    description:
      'Our agent compares your skills, experiences, and education against real job requirements sourced from O*NET and live postings — surfacing exactly what you need to bridge.',
  },
  {
    icon: 'map',
    color: 'purple',
    title: 'Personalised Career Pathway',
    description:
      'Receive a week-by-week learning plan tailored to your academic level, available hours, and target goal — from first internship to full career change.',
  },
  {
    icon: 'chart',
    color: 'green',
    title: 'Evidence-Backed Insights',
    description:
      'Upload your resume, transcript, portfolio, or project links. Every recommendation traces back to your actual evidence, so the plan fits you — not a generic student.',
  },
];

/* ── Steps data ─────────────────────────────────────────────────────────── */
const STEPS = [
  {
    num: '01',
    icon: 'upload',
    title: 'Upload Your Evidence',
    description:
      'Share your resume, transcripts, portfolios, or any document that captures your skills and experiences. All uploads are encrypted and only used to build your plan.',
  },
  {
    num: '02',
    icon: 'target',
    title: 'Set Your Goals & Constraints',
    description:
      'Tell us your desired role, academic year, hours per week, and target date. The agent adapts the entire plan to your real-life schedule.',
  },
  {
    num: '03',
    icon: 'brain',
    title: 'Agent Analyses Your Profile',
    description:
      'Our multi-step AI agent performs role intake, evidence ingestion, gap analysis, and plan critique — all automatically and in seconds.',
  },
  {
    num: '04',
    icon: 'sparkle',
    title: 'Receive Your Career Plan',
    description:
      'Get a structured, phased pathway with curated resources, resume tips, and milestones. Track your progress and iterate as you grow.',
  },
];

/* ── Stats data ─────────────────────────────────────────────────────────── */
const STATS = [
  { value: '500+', label: 'Career Roles Covered' },
  { value: '94%', label: 'Plan Satisfaction Rate' },
  { value: '3×', label: 'Faster Gap Identification' },
  { value: '∞', label: 'Iterations Allowed' },
];

/* ══════════════════════════════════════════════════════════════════════════
   Landing Page Component
   ══════════════════════════════════════════════════════════════════════════ */
export default function LandingPage() {
  return (
    <main>
      {/* ── Hero ───────────────────────────────────────────────────────── */}
      <section className={styles.hero}>
        {/* Background decoration */}
        <div className={styles.heroBg} aria-hidden="true">
          <div className={styles.blob1} />
          <div className={styles.blob2} />
          <div className={styles.grid} />
        </div>

        <div className={`container ${styles.heroContent}`}>
          <div className={styles.heroText}>
            <span className="badge badge-primary animate-fade-in-up">
              <Icon path={ICONS.sparkle} size={14} />
              AI-Powered Career Guidance
            </span>

            <h1 className={`${styles.heroHeading} animate-fade-in-up`} style={{ animationDelay: '0.1s' }}>
              Your personalised
              <span className={styles.gradient}> career pathway</span>
              <br />starts here
            </h1>

            <p className={`${styles.heroSubtitle} animate-fade-in-up`} style={{ animationDelay: '0.2s' }}>
              Upload your resume, set your goals, and let our agentic AI analyse the gap
              between where you are and where you want to be — then build a week-by-week
              plan to get you there.
            </p>

            <div className={`${styles.heroCtas} animate-fade-in-up`} style={{ animationDelay: '0.3s' }}>
              <Link to="/upload" className="btn btn-primary btn-lg">
                Build My Career Plan
                <Icon path={ICONS.arrow} size={18} />
              </Link>
              <a href="#how-it-works" className="btn btn-outline btn-lg">
                See How It Works
              </a>
            </div>

            <p className={`${styles.heroNote} animate-fade-in-up`} style={{ animationDelay: '0.4s' }}>
              <Icon path={ICONS.check} size={14} color="var(--color-success)" />
              Free to use &nbsp;·&nbsp; No account required &nbsp;·&nbsp; Results in under 60 seconds
            </p>
          </div>

          {/* Hero visual */}
          <div className={`${styles.heroVisual} animate-float`} aria-hidden="true">
            <HeroCard />
          </div>
        </div>
      </section>

      {/* ── Stats bar ──────────────────────────────────────────────────── */}
      <section className={styles.statsBar}>
        <div className={`container ${styles.statsGrid}`}>
          {STATS.map((s) => (
            <div key={s.label} className={styles.statItem}>
              <span className={styles.statValue}>{s.value}</span>
              <span className={styles.statLabel}>{s.label}</span>
            </div>
          ))}
        </div>
      </section>

      {/* ── Features ───────────────────────────────────────────────────── */}
      <section id="features" className={styles.section}>
        <div className="container">
          <div className={styles.sectionHeader}>
            <span className="badge badge-accent">What We Do</span>
            <h2 className={styles.sectionTitle}>
              Everything you need to navigate your career
            </h2>
            <p className={styles.sectionSubtitle}>
              Our agentic system combines occupational data, your personal evidence, and
              cutting-edge AI to create a truly adaptive guidance experience.
            </p>
          </div>

          <div className={styles.featuresGrid}>
            {FEATURES.map((f) => (
              <FeatureCard key={f.title} {...f} />
            ))}
          </div>
        </div>
      </section>

      {/* ── How It Works ───────────────────────────────────────────────── */}
      <section id="how-it-works" className={`${styles.section} ${styles.sectionAlt}`}>
        <div className="container">
          <div className={styles.sectionHeader}>
            <span className="badge badge-primary">The Process</span>
            <h2 className={styles.sectionTitle}>
              From evidence to action plan in four steps
            </h2>
            <p className={styles.sectionSubtitle}>
              A transparent, repeatable workflow designed with students and educators in mind.
            </p>
          </div>

          <div className={styles.stepsGrid}>
            {STEPS.map((step, i) => (
              <StepCard key={step.num} {...step} isLast={i === STEPS.length - 1} />
            ))}
          </div>
        </div>
      </section>

      {/* ── CTA Banner ─────────────────────────────────────────────────── */}
      <section id="about" className={styles.ctaBanner}>
        <div className={`container ${styles.ctaContent}`}>
          <div className={styles.ctaText}>
            <h2 className={styles.ctaTitle}>
              Ready to close the gap?
            </h2>
            <p className={styles.ctaSubtitle}>
              Join students who are already using CareerAI to land internships, switch
              careers, and build towards their dream roles.
            </p>
          </div>
          <div className={styles.ctaActions}>
            <Link to="/upload" className="btn btn-primary btn-lg">
              Start for Free
              <Icon path={ICONS.arrow} size={18} />
            </Link>
            <div className={styles.ctaMeta}>
              <Icon path={ICONS.check} size={14} color="rgba(255,255,255,0.8)" />
              <span>No credit card required</span>
            </div>
          </div>
        </div>
      </section>

      {/* ── Footer ─────────────────────────────────────────────────────── */}
      <footer className={styles.footer}>
        <div className={`container ${styles.footerInner}`}>
          <div className={styles.footerBrand}>
            <span className={styles.footerLogo}>🎯 Career<strong>AI</strong></span>
            <p className={styles.footerTagline}>
              Adaptive career guidance powered by agentic AI.
            </p>
          </div>
          <nav className={styles.footerLinks} aria-label="Footer navigation">
            <a href="#features" className={styles.footerLink}>Features</a>
            <a href="#how-it-works" className={styles.footerLink}>How It Works</a>
            <Link to="/upload" className={styles.footerLink}>Get Started</Link>
          </nav>
          <p className={styles.footerCopy}>
            © {new Date().getFullYear()} CareerAI · Built for students, by researchers.
          </p>
        </div>
      </footer>
    </main>
  );
}

/* ── Sub-components ─────────────────────────────────────────────────────── */

function FeatureCard({ icon, color, title, description }) {
  return (
    <div className={`${styles.featureCard} ${styles[`featureCard--${color}`]}`}>
      <div className={`${styles.featureIcon} ${styles[`featureIcon--${color}`]}`}>
        <Icon path={ICONS[icon]} size={22} />
      </div>
      <h3 className={styles.featureTitle}>{title}</h3>
      <p className={styles.featureDesc}>{description}</p>
    </div>
  );
}

function StepCard({ num, icon, title, description, isLast }) {
  return (
    <div className={styles.stepCard}>
      <div className={styles.stepHead}>
        <div className={styles.stepIconWrap}>
          <Icon path={ICONS[icon]} size={20} color="var(--color-primary)" />
        </div>
        {!isLast && <div className={styles.stepConnector} aria-hidden="true" />}
      </div>
      <div className={styles.stepBody}>
        <span className={styles.stepNum}>{num}</span>
        <h3 className={styles.stepTitle}>{title}</h3>
        <p className={styles.stepDesc}>{description}</p>
      </div>
    </div>
  );
}

function HeroCard() {
  return (
    <div className={styles.heroCard}>
      <div className={styles.heroCardHeader}>
        <div className={styles.heroCardDot} style={{ background: '#ef4444' }} />
        <div className={styles.heroCardDot} style={{ background: '#f59e0b' }} />
        <div className={styles.heroCardDot} style={{ background: '#10b981' }} />
        <span className={styles.heroCardTitle}>Career Plan Preview</span>
      </div>
      <div className={styles.heroCardBody}>
        <div className={styles.heroCardRole}>
          <span className={styles.heroCardLabel}>Target Role</span>
          <span className={styles.heroCardValue}>Software Engineer</span>
        </div>

        <div className={styles.heroCardPhases}>
          <PhaseBar label="Phase 1 — Foundations" weeks={4} pct={100} color="#10b981" />
          <PhaseBar label="Phase 2 — Projects"    weeks={6} pct={65}  color="#2563eb" />
          <PhaseBar label="Phase 3 — Portfolio"   weeks={4} pct={20}  color="#7c3aed" />
        </div>

        <div className={styles.heroCardGaps}>
          <span className={styles.heroCardLabel}>Top Gaps Identified</span>
          <div className={styles.heroCardTags}>
            <span className={styles.heroTag}>System Design</span>
            <span className={styles.heroTag}>SQL</span>
            <span className={styles.heroTag}>CI/CD</span>
          </div>
        </div>

        <div className={styles.heroCardProgress}>
          <span className={styles.heroCardLabel}>Overall Readiness</span>
          <div className={styles.progressBar}>
            <div className={styles.progressFill} style={{ width: '42%' }} />
          </div>
          <span className={styles.progressPct}>42%</span>
        </div>
      </div>
    </div>
  );
}

function PhaseBar({ label, weeks, pct, color }) {
  return (
    <div className={styles.phaseBar}>
      <div className={styles.phaseBarTop}>
        <span className={styles.phaseLabel}>{label}</span>
        <span className={styles.phaseWeeks}>{weeks}w</span>
      </div>
      <div className={styles.phaseTrack}>
        <div
          className={styles.phaseFill}
          style={{ width: `${pct}%`, background: color }}
        />
      </div>
    </div>
  );
}
