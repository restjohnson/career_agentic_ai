import { useNavigate } from "react-router-dom";
import "./landing_page.css";

function LandingPage() {

  const navigate = useNavigate();

  return (
    <div className="landing-container">

      {/* Navbar */}
      <nav className="navbar">
        <h2 className="logo">CareerPath AI</h2>

        <button
          className="nav-button"
          onClick={() => navigate("/student_evidence")}
        >
          Get Started
        </button>
      </nav>


      {/* Hero Section */}
      <section className="hero">

        <span className="tag">AI-Powered Career Planning</span>

        <h1>
          Your Personalized Path to <br />
          <span className="highlight">Career Success</span>
        </h1>

        <p>
          Upload your resume, share your constraints, and let our AI
          agent create a customized career development plan tailored
          to your goals and availability.
        </p>

        <button
          className="cta-button"
          onClick={() => navigate("/Agent_report")}
        >
          Start Your Career Journey
        </button>

      </section>


      {/* Features */}
      <section className="features">

        <div className="card">
          <h3>Gap Analysis</h3>
          <p>
            Identify skill and experience gaps between
            your current state and dream career.
          </p>
        </div>

        <div className="card">
          <h3>Career Roadmap</h3>
          <p>
            Get a personalized roadmap with actionable
            steps to reach your career goals.
          </p>
        </div>

        <div className="card">
          <h3>Flexible Planning</h3>
          <p>
            Plans adapted to your schedule—whether
            you're studying, working, or both.
          </p>
        </div>

      </section>


      {/* How it works */}
      <section className="how-it-works">

        <h2>How It Works</h2>

        <div className="steps">

          <div className="step">
            <div className="circle">1</div>
            <h4>Upload Resume</h4>
            <p>Share your current experience and skills</p>
          </div>

          <div className="step">
            <div className="circle">2</div>
            <h4>Set Constraints</h4>
            <p>Define your availability and academic level</p>
          </div>

          <div className="step">
            <div className="circle">3</div>
            <h4>AI Analysis</h4>
            <p>Our agent analyzes your profile and goals</p>
          </div>

          <div className="step">
            <div className="circle">4</div>
            <h4>Get Your Plan</h4>
            <p>Receive a personalized career pathway</p>
          </div>

        </div>

      </section>


      {/* Footer */}
      <footer className="footer">
        <p>
          © 2026 CareerPath AI. Empowering your career journey
          with intelligent planning.
        </p>
      </footer>

    </div>
  );
}

export default LandingPage;
