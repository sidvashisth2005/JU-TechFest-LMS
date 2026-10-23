import type { ReactNode } from "react";
import { BrowserRouter as Router, Navigate, Route, Routes, useLocation } from "react-router-dom";
import Navigation from "./components/Navigation";
import { AuthProvider, useAuth } from "./auth";
import LandingPage from "./pages/LandingPage";
import Login from "./pages/Login";
import Herd from "./pages/Herd";
import AnimalDetail from "./pages/AnimalDetail";
import Alerts from "./pages/Alerts";
import Environment from "./pages/Environment";
import Rover from "./pages/Rover";
import Disease from "./pages/Disease";

function Protected({ children }: { children: ReactNode }) {
  const { loggedIn } = useAuth();
  const location = useLocation();
  if (!loggedIn) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <>{children}</>;
}

function Shell() {
  const location = useLocation();
  return (
    <div className="min-h-screen">
      {location.pathname !== "/login" && <Navigation />}
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/login" element={<Login />} />
        <Route path="/herd" element={<Protected><Herd /></Protected>} />
        <Route path="/animals/:id" element={<Protected><AnimalDetail /></Protected>} />
        <Route path="/alerts" element={<Protected><Alerts /></Protected>} />
        <Route path="/environment" element={<Protected><Environment /></Protected>} />
        <Route path="/rover" element={<Protected><Rover /></Protected>} />
        {/* free for everyone: no login */}
        <Route path="/disease" element={<Disease />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <Router>
        <Shell />
      </Router>
    </AuthProvider>
  );
}
