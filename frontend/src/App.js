import React from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import LandingPage from './Pages/landing_page';
import AgentsReportPage from "./Pages/Agent_report_page";


function App() {
  return (
    <Router>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/Agent_report" element={<AgentsReportPage />} />
      </Routes>
    </Router>
  );
}

export default App;