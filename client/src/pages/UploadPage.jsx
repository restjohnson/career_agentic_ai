import { useState, useRef, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import styles from './UploadPage.module.css';
import { startSession, uploadEvidence } from '../api';

export default function UploadPage() {
  const [dragOver, setDragOver]         = useState(false);
  const [uploadedFile, setUploadedFile] = useState(null);
  const [consentLevel, setConsentLevel] = useState('derived_only');
  const [isUploading, setIsUploading]   = useState(false);
  const [uploadError, setUploadError]   = useState(null);
  const fileInputRef = useRef(null);
  const navigate     = useNavigate();

  useEffect(() => {
    startSession()
      .then(({ session_token, session_id }) => {
        localStorage.setItem('session_token', session_token);
        localStorage.setItem('session_id', session_id);
      })
      .catch((err) => setUploadError(`Could not start session: ${err.message}`));
  }, []);

  /* ── File handling ─────────────────────────────────────────────── */
  const acceptFile = (file) => {
    if (file) setUploadedFile(file);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    acceptFile(e.dataTransfer.files[0]);
  };

  const canContinue = uploadedFile !== null && !isUploading;

  const handleContinue = async () => {
    if (!canContinue) return;
    setUploadError(null);
    setIsUploading(true);
    try {
      const token = localStorage.getItem('session_token');
      const { document_id } = await uploadEvidence(token, uploadedFile, 'resume', consentLevel);
      navigate('/constraints', { state: { evidenceDocIds: [document_id] } });
    } catch (err) {
      setUploadError(err.message);
      setIsUploading(false);
    }
  };

  return (
    <div className={styles.page}>
      {/* ── Step progress bar ──────────────────────────────────────── */}
      <div className={styles.progressBar}>
        <div className={styles.progressTrack}>
          <div className={styles.progressFill} style={{ width: '50%' }} />
        </div>
        <div className={styles.progressSteps}>
          <span className={`${styles.progressStep} ${styles.progressStepActive}`}>
            <span className={styles.progressDot}>1</span>Upload Evidence
          </span>
          <span className={styles.progressStep}>
            <span className={styles.progressDot}>2</span>Set Constraints
          </span>
        </div>
      </div>

      <div className={styles.content}>
        <div className={styles.pageHeader}>
          <h1 className={styles.pageTitle}>Upload Your Evidence</h1>
          <p className={styles.pageSubtitle}>
            Share your resume and links to showcase your experience.
            All files are encrypted in transit.
          </p>
        </div>

        {/* ── Resume upload ──────────────────────────────────────── */}
        <div className={styles.uploadPanel}>
          <h2 className={styles.panelTitle}>
            <span className={styles.panelIcon}>📄</span>Resume / CV
          </h2>

          <div
            className={[
              styles.dropZone,
              dragOver      ? styles.dropZoneOver    : '',
              uploadedFile  ? styles.dropZoneSuccess : '',
            ].join(' ')}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={()  => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.doc,.docx"
              className={styles.fileInputHidden}
              onChange={(e) => acceptFile(e.target.files[0])}
            />

            {uploadedFile ? (
              <div className={styles.fileUploaded}>
                <span className={styles.fileUploadedIcon}>✅</span>
                <p className={styles.fileUploadedName}>{uploadedFile.name}</p>
                <p className={styles.fileUploadedSize}>
                  {(uploadedFile.size / 1024).toFixed(1)} KB
                </p>
                <button
                  className={styles.removeFileBtn}
                  onClick={(e) => { e.stopPropagation(); setUploadedFile(null); }}
                >
                  Remove
                </button>
              </div>
            ) : (
              <div className={styles.dropContent}>
                <div className={styles.dropIconWrap}>
                  <svg width="40" height="40" viewBox="0 0 24 24" fill="none"
                    stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"
                    strokeLinejoin="round">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/>
                  </svg>
                </div>
                <p className={styles.dropTitle}>Drag &amp; Drop your resume here</p>
                <p className={styles.dropSub}>or click to browse files</p>
                <span className={styles.dropFormats}>PDF, DOC, DOCX · Max 10 MB</span>
              </div>
            )}
          </div>

          <div className={styles.uploadNote}>
            <span>🔒</span>
            <span>Your file is only used to generate your personal career plan and is never shared.</span>
          </div>

          {/* ── Consent level ────────────────────────────────────── */}
          <div className={styles.consentGroup}>
            <label className={styles.consentTitle} htmlFor="consentSelect">Data Consent Level</label>
            <select
              id="consentSelect"
              className={styles.consentSelect}
              value={consentLevel}
              onChange={(e) => setConsentLevel(e.target.value)}
            >
              <option value="derived_only">Derived Only — never quotes your document</option>
              <option value="excerpt_ok">Excerpts OK — may include short snippets</option>
              <option value="raw_ok">Full Access — may reference any part</option>
            </select>
          </div>
        </div>

        {/* ── Actions ────────────────────────────────────────────── */}
        <div className={styles.actions}>
          {!uploadedFile && !isUploading && (
            <p className={styles.actionHint}>Please upload your resume to continue</p>
          )}
          {uploadError && (
            <p className={styles.actionHint} style={{ color: '#f87171' }}>{uploadError}</p>
          )}
          <div className={styles.actionBtns}>
            <Link to="/" className={styles.backBtn}>← Back</Link>
            <button
              className={`${styles.continueBtn} ${!canContinue ? styles.continueBtnDisabled : ''}`}
              disabled={!canContinue}
              onClick={handleContinue}
            >
              {isUploading ? 'Uploading…' : 'Continue to Set Goals →'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
