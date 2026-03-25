import { useEffect, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import styles from './LoadingPage.module.css';
import { createRun, streamRun } from '../api';

/* Map backend step names → UI labels (in order) */
const AGENT_STEPS = [
  { key: 'role_intake',        label: 'Matching role requirements from O*NET…' },
  { key: 'evidence_ingestion', label: 'Ingesting & analysing your evidence…' },
  { key: 'gap_analysis',       label: 'Performing gap analysis…' },
  { key: 'explanation',        label: 'Finalising your career blueprint…' },
];

export default function LoadingPage() {
  const [completedSteps, setCompletedSteps] = useState(new Set());
  const [activeStep,     setActiveStep]     = useState(AGENT_STEPS[0].key);
  const [runError,       setRunError]       = useState(null);
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    const { targetRole, evidenceDocIds = [], rawUserText } = location.state ?? {};
    const sessionToken = localStorage.getItem('session_token');
    let closeStream = null;

    createRun(sessionToken, targetRole, evidenceDocIds, rawUserText)
      .then(({ run_id }) => {
        closeStream = streamRun(sessionToken, run_id, (event) => {
          if (event.type === 'step') {
            // Mark step complete, advance active to the next one
            setCompletedSteps((prev) => new Set([...prev, event.step]));
            const idx = AGENT_STEPS.findIndex((s) => s.key === event.step);
            if (idx >= 0 && idx < AGENT_STEPS.length - 1) {
              setActiveStep(AGENT_STEPS[idx + 1].key);
            }
          } else if (event.type === 'done') {
            // All steps done — mark remaining and navigate
            setCompletedSteps(new Set(AGENT_STEPS.map((s) => s.key)));
            setTimeout(() => {
              navigate('/results', { state: { finalState: event.final_state } });
            }, 600);
          } else if (event.type === 'error') {
            setRunError(event.detail);
          }
        });
      })
      .catch((err) => setRunError(err.message));

    return () => { if (closeStream) closeStream(); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

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
        {runError ? (
          <p className={styles.subtitle} style={{ color: '#f87171' }}>
            Something went wrong: {runError}
          </p>
        ) : (
          <p className={styles.subtitle}>
            Our AI agent is building your personalised career blueprint.
            This usually takes under 60 seconds.
          </p>
        )}

        {/* ── Agent step list — driven by real SSE events ────────── */}
        <div className={styles.steps}>
          {AGENT_STEPS.map((step) => {
            const done   = completedSteps.has(step.key);
            const active = activeStep === step.key && !done;
            return (
              <div
                key={step.key}
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
