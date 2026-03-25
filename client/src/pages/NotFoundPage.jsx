import { Link } from 'react-router-dom';
import styles from './StubPage.module.css';

export default function NotFoundPage() {
  return (
    <main className={styles.page}>
      <section className={styles.card} aria-labelledby="not-found-title">
        <div className={styles.icon} aria-hidden="true">404</div>
        <h1 id="not-found-title" className={styles.title}>Page not found</h1>
        <p className={styles.subtitle}>
          The page you are looking for does not exist or may have been moved.
        </p>
        <Link to="/" className={styles.comingSoon}>
          Return home
        </Link>
      </section>
    </main>
  );
}
