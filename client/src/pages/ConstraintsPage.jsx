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

const TARGET_GOALS = [
  { id: 'first_internship', label: 'First Internship',          desc: 'Land your first internship' },
  { id: 'graduation',       label: 'Graduation',                desc: 'Be prepared before you graduate' },
  { id: 'job_ready',        label: 'Job Ready',                 desc: 'Ready for full-time roles' },
  { id: 'career_change',    label: 'Career Change',             desc: 'Transition from another field' },
];

const ACADEMIC_LEVEL_TO_GOAL = {
  freshman:             'first_internship',
  sophomore:            'first_internship',
  junior:               'graduation',
  senior:               'graduation',
  grad:                 'job_ready',
  bootcamp:             'job_ready',
  self_taught:          'job_ready',
  working_professional: 'career_change',
};

const LEARNING_MODES = [
  { id: 'structured',    label: 'Structured',    desc: 'Guided courses with set schedules' },
  { id: 'project_based', label: 'Project-Based', desc: 'Learning through building real projects' },
  { id: 'self_paced',    label: 'Self-Paced',    desc: 'Flexible timing at your own speed' },
  { id: 'mixed',         label: 'Mixed',         desc: 'Combination of all approaches' },
];

/**
 * Returns an error string if the custom role looks like jargon or gibberish,
 * or null if it appears to be a valid role title.
 */
function validateCustomRole(role) {
  const trimmed = role.trim();
  if (trimmed.length < 3) return 'Role title must be at least 3 characters.';
  if (trimmed.length > 80) return 'Role title is too long.';
  if (/^\d+$/.test(trimmed)) return 'Please enter a real job title, not a number.';
  // Excessive special characters / symbols
  if (/[^a-zA-Z0-9\s\-\/&,.'()]+/.test(trimmed))
    return 'Role title contains invalid characters. Please enter a real job title.';
  // Gibberish detection: consecutive consonants (5+) unlikely in English
  if (/[^aeiou\s]{5,}/i.test(trimmed.replace(/[^a-zA-Z\s]/g, '')))
    return 'That doesn\u2019t look like a valid role. Please enter a recognizable job title.';
  // Must contain at least one word with 2+ alphabetic chars
  if (!/[a-zA-Z]{2,}/.test(trimmed))
    return 'Please enter a real job title.';
  // Single repeated character (e.g. "aaaa")
  if (/^(.)\1+$/.test(trimmed.replace(/\s/g, '')))
    return 'That doesn\u2019t look like a valid role. Please enter a recognizable job title.';
  return null;
}

export default function ConstraintsPage() {
  const [academicLevel, setAcademicLevel] = useState('freshman');
  const [targetGoal,    setTargetGoal]    = useState('first_internship');
  const [targetRole,    setTargetRole]    = useState('');
  const [customRole,    setCustomRole]    = useState('');
  const [customRoleError, setCustomRoleError] = useState(null);
  const [hoursPerWeek,  setHoursPerWeek]  = useState(10);
const [targetDate,    setTargetDate]    = useState('');
const today = new Date().toISOString().split('T')[0];
const targetWeeks = targetDate
  ? Math.max(1, Math.round((new Date(targetDate) - new Date()) / (7 * 24 * 60 * 60 * 1000)))
  : 26;
  const [learningMode,  setLearningMode]  = useState('mixed');

  // Auto-update targetGoal when academicLevel changes
  useEffect(() => {
    setTargetGoal(ACADEMIC_LEVEL_TO_GOAL[academicLevel] ?? 'job_ready');
  }, [academicLevel]);

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
  const canSubmit =
    targetRole === 'Other'
      ? customRole.trim() !== '' && !validateCustomRole(customRole)
      : targetRole.trim() !== '';

  useEffect(() => {
    // Guard: if results already generated, redirect forward.
    const existingFinal = sessionStorage.getItem('career_flow_final_state');
    if (existingFinal) { navigate('/results', { replace: true }); return; }

    if (!evidenceDocIds.length) {
      navigate('/upload', { replace: true });
    }
  }, [evidenceDocIds.length, navigate]);

  const handleSubmit = () => {
    if (!canSubmit) return;

    const finalTargetRole = targetRole === 'Other' ? customRole : targetRole;

    const rawUserText = [
      `Academic level: ${academicLevel}`,
      `Target goal: ${targetGoal}`,
      `Hours per week: ${hoursPerWeek}`,
      `Target date: ${targetDate || 'not set'}`,
      `Learning mode: ${learningMode}`,
    ].join('. ');

    //const targetDate = new Date();
    //targetDate.setDate(targetDate.getDate() + targetWeeks * 7);
    const studentConstraints = {
      academic_level: academicLevel,
      hours_per_week: hoursPerWeek,
      target_goal: targetGoal,
      target_date: targetDate || null,
      preferred_learning_mode: learningMode,
    };

    sessionStorage.setItem(
      'career_flow_constraints',
      JSON.stringify({ targetRole: finalTargetRole, evidenceDocIds, rawUserText, studentConstraints })
    );

    navigate('/loading', {
      replace: true,
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
              <>
                <input
                  type="text"
                  placeholder="Enter your target role"
                  value={customRole}
                  onChange={(e) => {
                    setCustomRole(e.target.value);
                    setCustomRoleError(validateCustomRole(e.target.value));
                  }}
                  onBlur={() => setCustomRoleError(validateCustomRole(customRole))}
                  className={`${styles.textInput} ${customRoleError ? styles.textInputError : ''}`}
                  style={{ marginTop: '12px' }}
                />
                {customRoleError && (
                  <p className={styles.fieldError}>{customRoleError}</p>
                )}
              </>
            )}
          </div>

          {/* Target Goal */}
          <div className={styles.card}>
            <h2 className={styles.cardTitle}>Target Goal</h2>
            <div className={styles.modesGrid}>
              {TARGET_GOALS.map((goal) => (
                <button
                  key={goal.id}
                  className={`${styles.modeCard} ${targetGoal === goal.id ? styles.modeCardActive : ''}`}
                  onClick={() => setTargetGoal(goal.id)}
                >
                  <span className={styles.modeName}>{goal.label}</span>
                  <span className={styles.modeDesc}>{goal.desc}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Estimated time to goal */}
          <div className={styles.card}>
  <div className={styles.sliderHeader}>
    <h2 className={styles.cardTitle}>Estimated Time to Goal</h2>
    {targetDate && (
      <span className={styles.sliderValue}>{targetWeeks} weeks</span>
    )}
  </div>
  <input
    type="date"
    min={today}
    value={targetDate}
    onChange={e => setTargetDate(e.target.value)}
    className={styles.textInput}
  />
  {targetDate && (
    <p className={styles.calHint}>
      Starting today · {targetWeeks} weeks until{' '}
      {new Date(targetDate).toLocaleDateString('en-US', {
        month: 'long', day: 'numeric', year: 'numeric'
      })}
    </p>
  )}
</div>

          {/* Hours per week — Calendar */}
          <div className={`${styles.card} ${styles.cardFull}`}>
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
            <Link to="/upload" className={styles.startOverBtn}>Start Over</Link>
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