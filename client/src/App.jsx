import { BrowserRouter, Routes, Route, useLocation } from 'react-router-dom';
import Navbar from './components/Navbar';
import LandingPage from './pages/LandingPage';
import UploadPage from './pages/UploadPage';
import ConstraintsPage from './pages/ConstraintsPage';
import LoadingPage from './pages/LoadingPage';
import ResultsPage from './pages/ResultsPage';

/* Navbar is hidden on the landing page per design spec */
function AppInner() {
  const { pathname } = useLocation();
  const showNav = pathname !== '/';
  return (
    <>
      {showNav && <Navbar />}
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/upload" element={<UploadPage />} />
        <Route path="/constraints" element={<ConstraintsPage />} />
        <Route path="/loading" element={<LoadingPage />} />
        <Route path="/results" element={<ResultsPage />} />
      </Routes>
    </>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppInner />
    </BrowserRouter>
  );
}
