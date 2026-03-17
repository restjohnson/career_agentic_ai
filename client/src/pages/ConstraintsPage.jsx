import { Link } from 'react-router-dom';
import styles from './StubPage.module.css';

export default function ConstraintsPage() {
  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <span className={styles.icon} aria-hidden="true">🎯</span>
        <h1 className={styles.title}>Set Your Goals & Constraints</h1>
        <p className={styles.subtitle}>
          Tell us your desired role, academic year, hours available per week, and
          target date. The AI adapts the entire plan to your real-life schedule.
        </p>
        <p className={styles.comingSoon}>Coming soon — constraints form in progress.</p>
        <Link to="/" className="btn btn-outline">← Back to Home</Link>
      </div>
    </div>
  );
}
