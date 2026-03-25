import { Link } from 'react-router-dom';
import styles from './LandingPage.module.css';

/* ── Inline SVG Icon ─────────────────────────────────────────────────── */
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
  arrow:   'M5 12h14M12 5l7 7-7 7',
  check:   'M22 11.08V12a10 10 0 1 1-5.93-9.14M22 4 12 14.01l-3-3',
  upload:  'M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12',
  target:  'M12 22c5.52 0 10-4.48 10-10S17.52 2 12 2 2 6.48 2 12s4.48 10 10 10zm0-6a4 4 0 1 0 0-8 4 4 0 0 0 0 8zm0-2a2 2 0 1 1 0-4 2 2 0 0 1 0 4',
  brain:   'M12 2a4 4 0 0 1 4 4c1.66.56 3 2.13 3 4 0 1.23-.52 2.33-1.35 3.12A3.97 3.97 0 0 1 19 16a4 4 0 0 1-4 4H9a4 4 0 0 1-4-4c0-.83.25-1.6.68-2.24C4.73 12.86 4 11.51 4 10c0-1.87 1.34-3.44 3-4a4 4 0 0 1 4-4h1z',
  sparkle: 'M12 3l1.88 5.76H20l-4.94 3.59 1.88 5.76L12 14.52l-4.94 3.59 1.88-5.76L4 8.76h6.12L12 3z',
  map:     'M3 11l19-9-9 19-2-8-8-2z',
  chart:   'M18 20V10M12 20V4M6 20v-6',
};

/* ── Animated Roadmap SVG ─────────────────────────────────────────── */
function RoadmapVisual() {
  return (
    <svg viewBox="0 0 520 390" className={styles.roadmapSvg} aria-hidden="true">
      <defs>
        <linearGradient id="route" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#60a5fa" />
          <stop offset="100%" stopColor="#6366f1" />
        </linearGradient>
        <linearGradient id="routeSoft" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="rgba(96,165,250,0.2)" />
          <stop offset="100%" stopColor="rgba(99,102,241,0.2)" />
        </linearGradient>
        <filter id="roadGlow" x="-25%" y="-25%" width="150%" height="150%">
          <feGaussianBlur stdDeviation="4" result="blur" />
          <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>

      <path
        d="M34 320 C 90 260, 130 285, 180 225 S 270 165, 320 195 S 400 250, 486 84"
        stroke="url(#routeSoft)"
        strokeWidth="18"
        fill="none"
        strokeLinecap="round"
      />

      <path
        d="M34 320 C 90 260, 130 285, 180 225 S 270 165, 320 195 S 400 250, 486 84"
        className={styles.routePath}
        stroke="url(#route)"
        strokeWidth="6"
        fill="none"
        strokeLinecap="round"
        strokeDasharray="9 9"
      />

      <circle cx="34" cy="320" r="14" className={styles.milestone} />
      <circle cx="180" cy="225" r="12" className={styles.milestone} />
      <circle cx="320" cy="195" r="12" className={styles.milestone} />
      <circle cx="486" cy="84" r="14" className={styles.milestoneGoal} />

      <g className={styles.mapLabel}>
        <text x="20" y="350">Start</text>
        <text x="148" y="255">Skill Build</text>
        <text x="285" y="225">Projects</text>
        <text x="438" y="70">Target Role</text>
      </g>

      <circle className={styles.routePulse} r="6" fill="#93c5fd" filter="url(#roadGlow)">
        <animateMotion
          dur="6s"
          repeatCount="indefinite"
          rotate="auto"
          path="M34 320 C 90 260, 130 285, 180 225 S 270 165, 320 195 S 400 250, 486 84"
        />
      </circle>
    </svg>
  );
}

/* ── Data ───────────────────────────────────────────────────────────── */
const FEATURES = [
  {
    icon: 'brain', color: 'blue',
    title: 'AI-Powered Gap Analysis',
    description: 'Compare your skills and education against real job requirements — surfacing exactly what you need to bridge for your target role.',
  },
  {
    icon: 'map', color: 'cyan',
    title: 'Personalised Career Pathway',
    description: 'Receive a week-by-week plan tailored to your academic level, available hours, and target goal — from first internship to full career change.',
  },
  {
    icon: 'chart', color: 'green',
    title: 'Evidence-Backed Insights',
    description: 'Upload your resume, transcript, or project links. Every recommendation traces back to your actual evidence.',
  },
];

const STEPS = [
  { num: '01', icon: 'upload',  title: 'Upload Your Evidence',       description: 'Share your resume, transcripts, or portfolios. All uploads are encrypted in transit.' },
  { num: '02', icon: 'target',  title: 'Set Your Goals',             description: 'Tell us your desired role, hours per week, and target timeline.' },
  { num: '03', icon: 'brain',   title: 'AI Analyses Your Profile',   description: 'Our multi-step agent performs role intake, gap analysis, and plan critique automatically.' },
  { num: '04', icon: 'sparkle', title: 'Receive Your Career Plan',   description: 'Get a structured, phased pathway with curated resources, resume tips, and milestones.' },
];

// Feel free to update these stats with real data once you have it!
const STATS = [
  { value: '500+', label: 'Career Roles Covered' },
  { value: '94%',  label: 'Plan Satisfaction Rate' },
  { value: '3×',   label: 'Faster Gap Identification' },
  { value: '∞',    label: 'Iterations Allowed' },
];

/* ══════════════════════════════════════════════════════════════════════
   Landing Page Component
   ══════════════════════════════════════════════════════════════════════ */
export default function LandingPage() {
  return (
    <main className={styles.main}>

      {/* ── Hero ──────────────────────────────────────────────────────── */}
      <section className={styles.hero}>
        <div className={styles.heroGlow}  aria-hidden="true" />
        <div className={styles.heroGrid}  aria-hidden="true" />

        <div className={`container ${styles.heroInner}`}>
          <div className={styles.heroText}>
            <span className={styles.heroBadge}>
              <Icon path={ICONS.sparkle} size={13} color="#93c5fd" />
              AI-Powered Career Guidance
            </span>

            <h1 className={styles.heroHeading}>
              Map Your<br />
              <span className={styles.heroGradient}>Career Blueprint</span>
            </h1>

            <p className={styles.heroSubtitle}>
              Upload your resume, set your goals, and let our agentic AI close the gap
              between where you are and your dream role — with a personalised week-by-week plan.
            </p>

            <Link to="/upload" className={styles.heroCta}>
              Get Started
              <Icon path={ICONS.arrow} size={18} color="#fff" />
            </Link>

            <p className={styles.heroNote}>
              <Icon path={ICONS.check} size={14} color="#34d399" />
              Free to use &nbsp;·&nbsp; No account required &nbsp;·&nbsp; Results in under 60 s
            </p>
          </div>

          <div className={styles.heroVisual} aria-hidden="true">
            <div className={styles.roadmapWrap}>
              <RoadmapVisual />
            </div>
          </div>
        </div>
      </section>

      {/* ── Stats bar ─────────────────────────────────────────────────── */}
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

      {/* ── Features ──────────────────────────────────────────────────── */}
      <section id="features" className={styles.section}>
        <div className="container">
          <div className={styles.sectionHeader}>
            <span className={styles.sectionBadgePurple}>What We Do</span>
            <h2 className={styles.sectionTitle}>Everything you need to navigate your career</h2>
            <p className={styles.sectionSubtitle}>
              Our agentic system combines occupational data, your personal evidence, and
              cutting-edge AI to create a truly adaptive guidance experience.
            </p>
          </div>
          <div className={styles.featuresGrid}>
            {FEATURES.map((f) => <FeatureCard key={f.title} {...f} />)}
          </div>
        </div>
      </section>

      {/* ── How It Works ──────────────────────────────────────────────── */}
      <section id="how-it-works" className={`${styles.section} ${styles.sectionDarker}`}>
        <div className="container">
          <div className={styles.sectionHeader}>
            <span className={styles.sectionBadgeBlue}>The Process</span>
            <h2 className={styles.sectionTitle}>From evidence to action plan in four steps</h2>
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

      {/* ── CTA Banner ────────────────────────────────────────────────── */}
      <section id="about" className={styles.ctaBanner}>
        <div className={`container ${styles.ctaContent}`}>
          <h2 className={styles.ctaTitle}>Ready to close the gap?</h2>
          <p className={styles.ctaSubtitle}>
            Join students who are already using CareerAI to land internships, switch careers,
            and build towards their dream roles.
          </p>
          <Link to="/upload" className={styles.ctaBtn}>
            Start for Free
            <Icon path={ICONS.arrow} size={18} color="#0a1628" />
          </Link>
        </div>
      </section>

      {/* ── Footer ────────────────────────────────────────────────────── */}
      <footer className={styles.footer}>
        <div className={`container ${styles.footerInner}`}>
          <span className={styles.footerLogo}>🎯 Career<strong>AI</strong></span>
          <nav className={styles.footerLinks} aria-label="Footer navigation">
            <a href="#features"    className={styles.footerLink}>Features</a>
            <a href="#how-it-works" className={styles.footerLink}>How It Works</a>
            <Link to="/upload"     className={styles.footerLink}>Get Started</Link>
          </nav>
          <p className={styles.footerCopy}>
            © {new Date().getFullYear()} CareerAI · Built for students, by researchers.
          </p>
        </div>
      </footer>
    </main>
  );
}

/* ── Sub-components ──────────────────────────────────────────────────── */

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
          <Icon path={ICONS[icon]} size={20} color="#60a5fa" />
        </div>
        {!isLast && <div className={styles.stepConnector} aria-hidden="true" />}
      </div>
      <span className={styles.stepNum}>{num}</span>
      <h3 className={styles.stepTitle}>{title}</h3>
      <p className={styles.stepDesc}>{description}</p>
    </div>
  );
}
