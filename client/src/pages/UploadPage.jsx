import { Link } from 'react-router-dom';
import styles from './StubPage.module.css';

export default function UploadPage() {
  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <span className={styles.icon} aria-hidden="true">📎</span>
        <h1 className={styles.title}>Upload Your Evidence</h1>
        <p className={styles.subtitle}>
          Upload your resume, transcript, portfolio, or any document that captures
          your skills and experiences. All files are encrypted in transit.
        </p>
        <p className={styles.comingSoon}>Coming soon — full upload flow in progress.</p>
        <Link to="/" className="btn btn-outline">← Back to Home</Link>
      </div>
    </div>
  );
}
