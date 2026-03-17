import { useState, useRef } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import styles from './UploadPage.module.css';

export default function UploadPage() {
  const [dragOver, setDragOver]         = useState(false);
  const [uploadedFile, setUploadedFile] = useState(null);
  const [projectLinks, setProjectLinks] = useState(['']);
  const [certifications, setCerts]      = useState(['']);
  const fileInputRef = useRef(null);
  const navigate     = useNavigate();

  /* ── File handling ─────────────────────────────────────────────── */
  const acceptFile = (file) => {
    if (file) setUploadedFile(file);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    acceptFile(e.dataTransfer.files[0]);
  };

  /* ── Project links ─────────────────────────────────────────────── */
  const addLink    = ()       => setProjectLinks((l) => [...l, '']);
  const updateLink = (i, v)   => setProjectLinks((l) => l.map((x, idx) => idx === i ? v : x));
  const removeLink = (i)      => setProjectLinks((l) => l.filter((_, idx) => idx !== i));

  /* ── Certifications ────────────────────────────────────────────── */
  const addCert    = ()       => setCerts((c) => [...c, '']);
  const updateCert = (i, v)   => setCerts((c) => c.map((x, idx) => idx === i ? v : x));
  const removeCert = (i)      => setCerts((c) => c.filter((_, idx) => idx !== i));

  const canContinue = uploadedFile !== null;

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

        {/* ── Split layout ───────────────────────────────────────── */}
        <div className={styles.splitLayout}>

          {/* Left — resume drag & drop */}
          <div className={styles.leftPanel}>
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
          </div>

          {/* Right — project links + certifications */}
          <div className={styles.rightPanel}>
            {/* Project links */}
            <div className={styles.fieldGroup}>
              <h2 className={styles.panelTitle}>
                <span className={styles.panelIcon}>🔗</span>Project Links
              </h2>
              <p className={styles.fieldHint}>
                GitHub repos, live demos, portfolio sites, or any relevant URLs
              </p>
              {projectLinks.map((link, i) => (
                <div key={i} className={styles.inputRow}>
                  <input
                    type="url"
                    value={link}
                    placeholder="https://github.com/you/project"
                    className={styles.textInput}
                    onChange={(e) => updateLink(i, e.target.value)}
                  />
                  {projectLinks.length > 1 && (
                    <button
                      className={styles.removeRowBtn}
                      onClick={() => removeLink(i)}
                      aria-label="Remove link"
                    >✕</button>
                  )}
                </div>
              ))}
              <button className={styles.addRowBtn} onClick={addLink}>
                + Add another link
              </button>
            </div>

            {/* Certifications */}
            <div className={styles.fieldGroup}>
              <h2 className={styles.panelTitle}>
                <span className={styles.panelIcon}>🏅</span>Certifications
              </h2>
              <p className={styles.fieldHint}>
                AWS, Google, Coursera, LinkedIn Learning, or other professional certificates
              </p>
              {certifications.map((cert, i) => (
                <div key={i} className={styles.inputRow}>
                  <input
                    type="text"
                    value={cert}
                    placeholder="e.g. AWS Solutions Architect – Associate"
                    className={styles.textInput}
                    onChange={(e) => updateCert(i, e.target.value)}
                  />
                  {certifications.length > 1 && (
                    <button
                      className={styles.removeRowBtn}
                      onClick={() => removeCert(i)}
                      aria-label="Remove certification"
                    >✕</button>
                  )}
                </div>
              ))}
              <button className={styles.addRowBtn} onClick={addCert}>
                + Add another certificate
              </button>
            </div>
          </div>
        </div>

        {/* ── Actions ────────────────────────────────────────────── */}
        <div className={styles.actions}>
          {!canContinue && (
            <p className={styles.actionHint}>Please upload your resume to continue</p>
          )}
          <div className={styles.actionBtns}>
            <Link to="/" className={styles.backBtn}>← Back</Link>
            <button
              className={`${styles.continueBtn} ${!canContinue ? styles.continueBtnDisabled : ''}`}
              disabled={!canContinue}
              onClick={() => canContinue && navigate('/constraints')}
            >
              Continue to Set Goals →
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
