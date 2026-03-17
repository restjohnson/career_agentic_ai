import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import styles from './LoadingPage.module.css';

const AGENT_STEPS = [
  { id: 1, label: 'Ingesting your evidence…',           delay: 0    },
  { id: 2, label: 'Matching role requirements…',        delay: 2000 },
  { id: 3, label: 'Performing gap analysis…',           delay: 4000 },
  { id: 4, label: 'Generating personalised pathway…',   delay: 6500 },
  { id: 5, label: 'Finalising your career blueprint…',  delay: 9000 },
];

const NAVIGATE_AFTER_MS = 12000;

export default function LoadingPage() {
  const [completedIds, setCompletedIds] = useState([]);
  const [activeId,     setActiveId]     = useState(1);
  const navigate = useNavigate();

  useEffect(() => {
    const timers = AGENT_STEPS.map((step) =>
      setTimeout(() => {
        setCompletedIds((prev) => [...prev, step.id]);
        setActiveId(step.id + 1);
      }, step.delay + 1400)
    );

    const finalTimer = setTimeout(() => navigate('/results'), NAVIGATE_AFTER_MS);
    timers.push(finalTimer);

    return () => timers.forEach(clearTimeout);
  }, [navigate]);

  return (
    <div className={styles.page}>
      <div className={styles.content}>

        {/* ── Orbital loader ─────────────────────────────────────── */}
        <div className={styles.loaderWrap} aria-hidden="true">
          <div className={styles.coreGlow} />
          <div className={styles.core}>
            <span className={styles.coreIcon}>🧠</span>
          </div>
          <div className={styles.orbit1}>
            <div className={styles.orbitDot1} />
          </div>
          <div className={styles.orbit2}>
            <div className={styles.orbitDot2} />
          </div>
          <div className={styles.orbit3}>
            <div className={styles.orbitDot3} />
          </div>
        </div>

        <h1 className={styles.title}>Analysing Your Profile</h1>
        <p className={styles.subtitle}>
          Our AI agent is building your personalised career blueprint.
          This usually takes under 60 seconds.
        </p>

        {/* ── Agent step list ─────────────────────────────────────── */}
        <div className={styles.steps}>
          {AGENT_STEPS.map((step) => {
            const done   = completedIds.includes(step.id);
            const active = activeId === step.id && !done;
            return (
              <div
                key={step.id}
                className={[
                  styles.step,
                  done   ? styles.stepDone   : '',
                  active ? styles.stepActive : '',
                ].join(' ')}
              >
                <span className={styles.stepIcon}>
                  {done ? '✓' : active ? '◉' : '○'}
                </span>
                <span className={styles.stepLabel}>{step.label}</span>
                {active && <span className={styles.stepSpinner} aria-hidden="true" />}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
