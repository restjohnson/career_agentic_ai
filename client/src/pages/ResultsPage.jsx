import { Link } from 'react-router-dom';
import styles from './StubPage.module.css';

export default function ResultsPage() {
  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <span className={styles.icon} aria-hidden="true">🗺️</span>
        <h1 className={styles.title}>Your Career Pathway Plan</h1>
        <p className={styles.subtitle}>
          Your personalised, phased learning plan is ready — complete with curated
          resources, resume tips, gap explanations, and phase milestones.
        </p>
        <p className={styles.comingSoon}>Coming soon — plan display page in progress.</p>
        <Link to="/" className="btn btn-outline">← Back to Home</Link>
      </div>
    </div>
  );
}
