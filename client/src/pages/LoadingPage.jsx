import { Link } from 'react-router-dom';
import styles from './StubPage.module.css';

export default function LoadingPage() {
  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <span className={styles.icon} aria-hidden="true">⚙️</span>
        <h1 className={styles.title}>Analysing Your Profile…</h1>
        <p className={styles.subtitle}>
          Our agentic AI is performing role intake, evidence ingestion, gap analysis,
          and plan critique. This usually takes under 60 seconds.
        </p>
        <p className={styles.comingSoon}>Coming soon — loading/progress animation in progress.</p>
        <Link to="/" className="btn btn-outline">← Back to Home</Link>
      </div>
    </div>
  );
}
