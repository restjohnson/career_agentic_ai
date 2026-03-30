import { useEffect, useState } from 'react';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import styles from './ConstraintsPage.module.css';

const ACADEMIC_LEVELS = [
  { id: 'freshman',             label: 'Freshman' },
  { id: 'sophomore',            label: 'Sophomore' },
  { id: 'junior',               label: 'Junior' },
  { id: 'senior',               label: 'Senior' },
  { id: 'grad',                 label: 'Graduate' },
  { id: 'bootcamp',             label: 'Bootcamp' },
  { id: 'self_taught',          label: 'Self-Taught' },
  { id: 'working_professional', label: 'Working Professional' },
];

const TARGET_ROLES = [
  'Software Engineer',
  'Frontend Developer',
  'Backend Developer',
  'Full-Stack Developer',
  'Data Analyst',
  'Data Scientist',
  'Machine Learning Engineer',
  'DevOps Engineer',
  'Cloud Engineer',
  'Cybersecurity Analyst',
  'Product Manager',
  'UX Designer',
  'Business Analyst',
  'Project Manager',
  'Systems Administrator',
  'Other',
];

const LEARNING_MODES = [
  { id: 'structured',    label: 'Structured',    desc: 'Guided courses with set schedules' },
  { id: 'project_based', label: 'Project-Based', desc: 'Learning through building real projects' },
  { id: 'self_paced',    label: 'Self-Paced',    desc: 'Flexible timing at your own speed' },
  { id: 'mixed',         label: 'Mixed',         desc: 'Combination of all approaches' },
];

export default function ConstraintsPage() {
  const [academicLevel, setAcademicLevel] = useState('freshman');
  const [targetRole,    setTargetRole]    = useState('');
  const [customRole,    setCustomRole]    = useState('');
  const [targetWeeks,   setTargetWeeks]   = useState(26);
  const [hoursPerWeek,  setHoursPerWeek]  = useState(10);
  const [learningMode,  setLearningMode]  = useState('mixed');

  const navigate  = useNavigate();
  const location  = useLocation();

  const storedEvidenceDocIds = (() => {
    try {
      return JSON.parse(sessionStorage.getItem('career_flow_evidence_ids') ?? '[]');
    } catch {
      return [];
    }
  })();

  const evidenceDocIds = location.state?.evidenceDocIds ?? storedEvidenceDocIds;
  const canSubmit = targetRole === 'Other' ? customRole.trim() !== '' : targetRole.trim() !== '';

  useEffect(() => {
    if (!evidenceDocIds.length) {
      navigate('/upload', { replace: true });
    }
  }, [evidenceDocIds.length, navigate]);

  const ACADEMIC_LEVEL_MAP = {
    Undergraduate: 'junior',
    Graduate: 'grad',
    Professional: 'working_professional',
  };
  const TARGET_GOAL_MAP = {
    Undergraduate: 'first_internship',
    Graduate: 'job_ready',
    Professional: 'career_change',
  };

  const handleSubmit = () => {
    if (!canSubmit) return;

    const finalTargetRole = targetRole === 'Other' ? customRole : targetRole;

    const rawUserText = [
      `Academic level: ${academicLevel}`,
      `Hours per week: ${hoursPerWeek}`,
      `Target weeks: ${targetWeeks}`,
      `Learning mode: ${learningMode}`,
    ].join('. ');

    const targetDate = new Date();
    targetDate.setDate(targetDate.getDate() + targetWeeks * 7);
    const studentConstraints = {
      academic_level: ACADEMIC_LEVEL_MAP[academicLevel] ?? 'junior',
      hours_per_week: hoursPerWeek,
      target_goal: TARGET_GOAL_MAP[academicLevel] ?? 'job_ready',
      target_date: targetDate.toISOString().split('T')[0],
      preferred_learning_mode: learningMode,
    };

    sessionStorage.setItem(
      'career_flow_constraints',
      JSON.stringify({ targetRole: finalTargetRole, evidenceDocIds, rawUserText, studentConstraints })
    );

    navigate('/loading', {
      state: {
        targetRole: finalTargetRole,
        evidenceDocIds,
        rawUserText,
        studentConstraints,
      },
    });
  };

  return (
    <div className={styles.page}>
      {/* ── Step progress bar ─────────────────────────────────── */}
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
            No pressure — Just tell us where you are and where you're headed — we'll handle the rest.
          </p>
        </div>

        <div className={styles.formGrid}>

          {/* Academic Level */}
          <div className={styles.card}>
            <h2 className={styles.cardTitle}>Academic Level</h2>
            <div className={styles.segmented}>
              {ACADEMIC_LEVELS.map((level) => (
                <button
                  key={level.id}
                  className={`${styles.segBtn} ${academicLevel === level.id ? styles.segBtnActive : ''}`}
                  onClick={() => setAcademicLevel(level.id)}
                >
                  {level.label}
                </button>
              ))}
            </div>
          </div>

          {/* Target Role */}
          <div className={styles.card}>
            <h2 className={styles.cardTitle}>Target Role</h2>
            <select
              value={targetRole}
              onChange={(e) => setTargetRole(e.target.value)}
              className={styles.selectInput}
            >
              <option value="" disabled>Select your target role</option>
              {TARGET_ROLES.map((role) => (
                <option key={role} value={role}>{role}</option>
              ))}
            </select>
            {targetRole === 'Other' && (
              <input
                type="text"
                placeholder="Enter your target role"
                value={customRole}
                onChange={(e) => setCustomRole(e.target.value)}
                className={styles.textInput}
                style={{ marginTop: '12px' }}
              />
            )}
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
              Please select your target role to continue
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