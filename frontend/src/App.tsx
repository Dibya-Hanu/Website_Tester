import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  Cpu,
  FileBarChart2,
  History as HistoryIcon,
  Moon,
  Plus,
  ShieldCheck,
  Sun,
  CircleHelp,
} from "lucide-react";
import {
  BrowserRouter,
  Link,
  NavLink,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import { SystemStatus } from "./components/Common";
import Home from "./pages/Home";
import History from "./pages/History";
import Report from "./pages/Report";
import Progress from "./pages/Progress";
import Models from "./pages/Models";

function Workspace() {
  const location = useLocation();
  const [system, setSystem] = useState(false);
  const closeSystem = useCallback(() => setSystem(false), []);

  const [theme, setTheme] = useState<"dark" | "light">(() => {
    try {
      const saved = localStorage.getItem("autotester_theme");
      if (saved === "light" || saved === "dark") return saved;
      if (window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches) {
        return "light";
      }
    } catch {
      // ignore
    }
    return "dark";
  });

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    document.body.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("autotester_theme", theme);
    } catch {
      // ignore
    }
  }, [theme]);

  const toggleTheme = useCallback(() => {
    setTheme((prev) => (prev === "dark" ? "light" : "dark"));
  }, []);

  const activeSection = location.pathname.startsWith("/models")
    ? "AI Models"
    : location.pathname.startsWith("/history")
      ? "History"
      : location.pathname.startsWith("/reports")
        ? "Reports"
        : location.pathname.startsWith("/tests")
          ? "Live diagnostic"
          : "New scan";

  return (
    <div className={`workspace redesigned-shell theme-${theme}`}>
      <a className="skip-link" href="#main-content">Skip to content</a>
      <header className="topbar redesigned-topbar">
        <Link to="/" className="topbar-brand" aria-label="Universal Website Tester workspace">
          <span className="topbar-brand-mark"><ShieldCheck size={23} strokeWidth={1.8} /></span>
          <span className="topbar-brand-copy">
            <strong>universal</strong>
            <small>WEBSITE TESTER</small>
          </span>
          <span className="topbar-brand-divider" />
          <span className="topbar-workspace-name">Diagnostic workspace</span>
        </Link>

        <nav className="primary-nav" aria-label="Primary navigation">
          <NavLink end to="/" className={({ isActive }) => `primary-nav-link ${isActive || location.pathname.startsWith("/tests/") ? "active" : ""}`}>
            <Plus size={16} /> <span>New scan</span>
          </NavLink>
          <NavLink to="/reports" className={({ isActive }) => `primary-nav-link ${isActive ? "active" : ""}`}>
            <FileBarChart2 size={16} /> <span>Reports</span>
          </NavLink>
          <NavLink to="/history" className={({ isActive }) => `primary-nav-link ${isActive ? "active" : ""}`}>
            <HistoryIcon size={16} /> <span>History</span>
          </NavLink>
          <NavLink to="/models" className={({ isActive }) => `primary-nav-link ${isActive ? "active" : ""}`}>
            <Cpu size={16} /> <span>AI models</span>
          </NavLink>
        </nav>

        <div className="topbar-utilities">
          <div className="topbar-runtime"><span className="runtime-pulse" /><span>LOCAL-FIRST</span></div>
          <button
            className="topbar-theme-toggle"
            onClick={toggleTheme}
            aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
            title={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
          >
            {theme === "dark" ? (
              <>
                <Sun size={15} className="theme-toggle-icon theme-sun" />
                <span className="theme-toggle-label">Light mode</span>
              </>
            ) : (
              <>
                <Moon size={15} className="theme-toggle-icon theme-moon" />
                <span className="theme-toggle-label">Dark mode</span>
              </>
            )}
          </button>
          <button className="topbar-help" onClick={() => setSystem(true)} aria-label="Open system and tool status" title="System and tool status">
            <Activity size={16} /><span>System status</span>
          </button>
          <button className="topbar-icon-help" onClick={() => setSystem(true)} aria-label="Help and system status" title="Help and system status">
            <CircleHelp size={17} />
          </button>
        </div>
      </header>

      <div className="workspace-content redesigned-content">
        <div className="route-context" aria-label="Current section">
          <span>WORKSPACE</span><i>/</i><strong>{activeSection}</strong>
        </div>
        <main id="main-content" className="redesigned-main">
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/history" element={<History />} />
            <Route path="/reports" element={<History reportsOnly />} />
            <Route path="/reports/:id" element={<Report />} />
            <Route path="/tests/:id" element={<Progress />} />
            <Route path="/models" element={<Models />} />
            <Route path="*" element={<div className="state-panel"><h1>Page not found</h1><Link className="btn btn-primary" to="/">Back to your workspace</Link></div>} />
          </Routes>
        </main>
      </div>
      {system && <SystemStatus close={closeSystem} />}
    </div>
  );
}

export default function App() {
  return <BrowserRouter><Workspace /></BrowserRouter>;
}
