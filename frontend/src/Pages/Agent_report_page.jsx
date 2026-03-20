import { useState } from "react";
import "./Agent_report_page.css";

function AgentsReportPage() {
  const [activeTab, setActiveTab] = useState("career");

  const currentSkills = ["JavaScript", "React", "HTML/CSS", "Basic Python", "Git"];
  const requiredSkills = [
    "Advanced TypeScript/JavaScript",
    "System Design",
    "Cloud Architecture (AWS/Azure)",
    "Database Optimization",
    "CI/CD & DevOps",
  ];

  const skillGaps = [
    { title: "System Design", priority: "high", timeframe: "3-6 months" },
    { title: "Cloud Architecture (AWS)", priority: "high", timeframe: "4-8 months" },
    { title: "Advanced TypeScript", priority: "medium", timeframe: "2-4 months" },
    { title: "Database Optimization", priority: "medium", timeframe: "3-5 months" },
    { title: "CI/CD & DevOps", priority: "low", timeframe: "2-3 months" },
  ];

  return (
    <div className="report-container">
      <div className="report-content">
        <div className="header">
          <span className="plan-badge">Your Personalized Career Plan</span>
          <h1>Path to Software Developer</h1>
          <p>
            Software developers design, develop, and maintain scalable software
            systems with strong performance and reliability.
          </p>

          <div className="tabs">
            <button
              className={activeTab === "career" ? "active" : ""}
              onClick={() => setActiveTab("career")}
            >
              Career Plan
            </button>

            <button
              className={activeTab === "pathway" ? "active" : ""}
              onClick={() => setActiveTab("pathway")}
            >
              Pathway Plan
            </button>
          </div>
        </div>

        {activeTab === "career" && (
          <div className="sections">
            <div className="card">
              <div className="card-heading">
                <div className="icon-box blue-light">▥</div>
                <div>
                  <h2>Current State</h2>
                  <p className="subtext">Where you are today</p>
                </div>
              </div>

              <div className="three-column">
                <div>
                  <h3>Skills</h3>
                  <div className="tag-wrap">
                    {currentSkills.map((skill) => (
                      <span key={skill} className="soft-tag">
                        {skill}
                      </span>
                    ))}
                  </div>
                </div>

                <div>
                  <h3>Experience</h3>
                  <p className="plain-text">Masters</p>
                </div>

                <div>
                  <h3>Education</h3>
                  <p className="plain-text">B.S. Computer Science (In Progress)</p>
                </div>
              </div>
            </div>

            <div className="card target-card">
              <div className="card-heading">
                <div className="icon-box blue-strong">◎</div>
                <div>
                  <h2>Target Role</h2>
                  <p className="subtext">Your career destination</p>
                </div>
              </div>

              <h3 className="role-title">Software Developer</h3>
              <p className="role-description">
                Responsible for designing and maintaining scalable software
                systems with strong performance and reliability.
              </p>

              <h3>Required Skills</h3>
              <div className="tag-wrap">
                {requiredSkills.map((skill) => (
                  <span key={skill} className="blue-tag">
                    {skill}
                  </span>
                ))}
              </div>
            </div>

            <div className="card">
              <div className="card-heading">
                <div className="icon-box purple-light">◌</div>
                <div>
                  <h2>Gap Analysis</h2>
                  <p className="subtext">What you need to develop to reach your goal</p>
                </div>
              </div>

              <h3>Skill Gaps to Address</h3>

              <div className="gap-list">
                {skillGaps.map((gap) => (
                  <div key={gap.title} className="gap-item">
                    <div className="gap-row">
                      <span className="gap-title">{gap.title}</span>
                      <span className={`priority ${gap.priority}`}>
                        {gap.priority} priority
                      </span>
                    </div>
                    <p className="gap-time">Estimated timeframe: {gap.timeframe}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {activeTab === "pathway" && (
          <div className="card">
            <div className="card-heading">
              <div className="icon-box purple-light">⇄</div>
              <div>
                <h2>Pathway Planning</h2>
                <p className="subtext">
                  The pathway planning agent has not been implemented yet.
                </p>
              </div>
            </div>

            <p className="pathway-text">
              This section is reserved for future pathway planning output such as
              learning phases, milestones, and timeline-based guidance.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

export default AgentsReportPage;
