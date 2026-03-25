import { useState } from 'react';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import styles from './ConstraintsPage.module.css';

const ACADEMIC_LEVELS = ['Undergraduate', 'Graduate', 'Professional'];

const LEARNING_MODES = [
  { id: 'structured',    label: 'Structured',     desc: 'Guided courses with set schedules' },
  { id: 'project_based', label: 'Project-Based',  desc: 'Learning through building real projects' },
  { id: 'self_paced',    label: 'Self-Paced',     desc: 'Flexible timing at your own speed' },
  { id: 'mixed',         label: 'Mixed',           desc: 'Combination of all approaches' },
];

export default function ConstraintsPage() {
  const [academicLevel,  setAcademicLevel]  = useState('Undergraduate');
  const [degreeProgram,  setDegreeProgram]  = useState('');
  const [targetRole,     setTargetRole]     = useState('');
  const [targetWeeks,    setTargetWeeks]    = useState(26);
  const [hoursPerWeek,   setHoursPerWeek]   = useState(10);
  const [learningMode,   setLearningMode]   = useState('mixed');

  const navigate   = useNavigate();
  const location   = useLocation();
  const evidenceDocIds = location.state?.evidenceDocIds ?? [];
  const canSubmit  = degreeProgram.trim() !== '' && targetRole.trim() !== '';

  const handleSubmit = () => {
    if (!canSubmit) return;
    const rawUserText = [
      `Academic level: ${academicLevel}`,
      `Degree/Program: ${degreeProgram}`,
      `Hours per week: ${hoursPerWeek}`,
      `Target weeks: ${targetWeeks}`,
      `Learning mode: ${learningMode}`,
    ].join('. ');
    navigate('/loading', {
      state: {
        targetRole,
        evidenceDocIds,
        rawUserText,
      },
    });
  };

  return (
    <div className={styles.page}>
      {/* ── Step progress bar ──────────────────────────────────────── */}
      <div className={styles.progressBar}>
        <div className={styles.progressTrack}>
          <div className={styles.progressFill} style={{ width: '100%' }} />
        </div>
        <div className={styles.progressSteps}>
          <span className={styles.progressStep}>
            <span className={styles.progressDotDone}>✓</span>Upload Evidence
          </span>
          <span className={`${styles.progressStep} ${styles.progressStepActive}`}>
            <span className={styles.progressDot}>2</span>Set Constraints
          </span>
        </div>
      </div>

      <div className={styles.content}>
        <div className={styles.pageHeader}>
          <h1 className={styles.pageTitle}>Set Your Goals &amp; Constraints</h1>
          <p className={styles.pageSubtitle}>
            Tell us about your situation so we can tailor your career plan precisely to you.
          </p>
        </div>

        <div className={styles.formGrid}>

          {/* Academic Level */}
          <div className={styles.card}>
            <h2 className={styles.cardTitle}>Academic Level</h2>
            <div className={styles.segmented}>
              {ACADEMIC_LEVELS.map((level) => (
                <button
                  key={level}
                  className={`${styles.segBtn} ${academicLevel === level ? styles.segBtnActive : ''}`}
                  onClick={() => setAcademicLevel(level)}
                >
                  {level}
                </button>
              ))}
            </div>
          </div>

          {/* Degree / Program */}
          <div className={styles.card}>
            <h2 className={styles.cardTitle}>Degree / Program</h2>
            <input
              type="text"
              value={degreeProgram}
              onChange={(e) => setDegreeProgram(e.target.value)}
              placeholder="e.g. BSc Computer Science"
              className={styles.textInput}
            />
          </div>

          {/* Target Role */}
          <div className={styles.card}>
            <h2 className={styles.cardTitle}>Target Role</h2>
            <input
              type="text"
              value={targetRole}
              onChange={(e) => setTargetRole(e.target.value)}
              placeholder="e.g. Software Engineer, Data Analyst"
              className={styles.textInput}
            />
          </div>

          {/* Estimated time to goal */}
          <div className={styles.card}>
            <div className={styles.sliderHeader}>
              <h2 className={styles.cardTitle}>Estimated Time to Goal</h2>
              <span className={styles.sliderValue}>{targetWeeks} weeks</span>
            </div>
            <input
              type="range"
              min={4} max={104} step={2}
              value={targetWeeks}
              onChange={(e) => setTargetWeeks(Number(e.target.value))}
              className={styles.slider}
            />
            <div className={styles.sliderLabels}>
              <span>4 weeks</span>
              <span>~2 years</span>
            </div>
          </div>

          {/* Hours per week */}
          <div className={styles.card}>
            <div className={styles.sliderHeader}>
              <h2 className={styles.cardTitle}>Hours per Week</h2>
              <span className={styles.sliderValue}>{hoursPerWeek} hrs</span>
            </div>
            <input
              type="range"
              min={1} max={40} step={1}
              value={hoursPerWeek}
              onChange={(e) => setHoursPerWeek(Number(e.target.value))}
              className={styles.slider}
            />
            <div className={styles.sliderLabels}>
              <span>1 hr</span>
              <span>40 hrs</span>
            </div>
          </div>

          {/* Learning Mode */}
          <div className={`${styles.card} ${styles.cardFull}`}>
            <h2 className={styles.cardTitle}>Preferred Learning Mode</h2>
            <div className={styles.modesGrid}>
              {LEARNING_MODES.map((mode) => (
                <button
                  key={mode.id}
                  className={`${styles.modeCard} ${learningMode === mode.id ? styles.modeCardActive : ''}`}
                  onClick={() => setLearningMode(mode.id)}
                >
                  <span className={styles.modeName}>{mode.label}</span>
                  <span className={styles.modeDesc}>{mode.desc}</span>
                </button>
              ))}
            </div>
          </div>

        </div>

        {/* Actions */}
        <div className={styles.actions}>
          {!canSubmit && (
            <p className={styles.actionHint}>
              Please fill in your degree program and target role to continue
            </p>
          )}
          <div className={styles.actionBtns}>
            <Link to="/upload" className={styles.backBtn}>← Back</Link>
            <button
              className={`${styles.submitBtn} ${!canSubmit ? styles.submitBtnDisabled : ''}`}
              disabled={!canSubmit}
              onClick={handleSubmit}
            >
              Generate My Career Plan →
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
