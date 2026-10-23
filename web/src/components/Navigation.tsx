import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { Bell, Bot, Cloud, LayoutGrid, Leaf, LogOut, Menu, Stethoscope, X } from "lucide-react";
import { useAuth } from "../auth";

const navItems = [
  { path: "/herd", label: "Herd", icon: LayoutGrid },
  { path: "/alerts", label: "Alerts", icon: Bell },
  { path: "/environment", label: "Barn", icon: Cloud },
  { path: "/rover", label: "Rover", icon: Bot },
  { path: "/disease", label: "Disease check", icon: Stethoscope },
];

const Navigation = () => {
  const [isOpen, setIsOpen] = useState(false);
  const location = useLocation();
  const { loggedIn, logout } = useAuth();
  const active = (path: string) => location.pathname === path || location.pathname.startsWith(`${path}/`);
  // the disease checker is free for everyone; the rest needs a login
  const items = loggedIn ? navItems : navItems.filter((i) => i.path === "/disease");

  return (
    <nav className="fixed left-1/2 top-4 z-50 w-[95%] max-w-6xl -translate-x-1/2">
      <div className="nav-floating rounded-2xl px-4 sm:px-6 lg:px-8">
        <div className="flex h-16 items-center justify-between">
          <Link to="/" className="group flex items-center space-x-2">
            <div className="icon-box !h-10 !w-10 transition-transform duration-300 group-hover:scale-110">
              <Leaf className="h-5 w-5 text-white" />
            </div>
            <span className="font-display text-xl font-bold text-forest-800">
              <span className="hidden sm:inline">LiveStock Monitoring System</span>
              <span className="sm:hidden">LMS</span>
            </span>
          </Link>

          <div className="hidden items-center space-x-1 lg:flex">
            {items.map(({ path, label, icon: Icon }) => (
              <Link
                key={path}
                to={path}
                className={`nav-link flex items-center space-x-2 rounded-xl px-3 py-2 text-sm font-medium transition-all duration-300 ${
                  active(path) ? "bg-forest-600 shadow-lg" : "text-forest-700 hover:bg-forest-100"
                }`}
              >
                <Icon className="h-4 w-4" />
                <span>{label}</span>
              </Link>
            ))}
            {loggedIn ? (
              <button onClick={logout} className="nav-link text-sm text-forest-700" title="Sign out">
                <LogOut className="h-4 w-4" />
              </button>
            ) : (
              <Link to="/login" className="nav-link text-sm font-medium text-forest-700">
                Sign in
              </Link>
            )}
          </div>

          <button
            onClick={() => setIsOpen(!isOpen)}
            className="inline-flex items-center justify-center rounded-xl p-2 text-forest-800 hover:bg-forest-100 lg:hidden"
            aria-label="Menu"
          >
            {isOpen ? <X className="h-6 w-6" /> : <Menu className="h-6 w-6" />}
          </button>
        </div>

        {isOpen && (
          <div className="space-y-1 pb-4 lg:hidden">
            {items.map(({ path, label, icon: Icon }) => (
              <Link
                key={path}
                to={path}
                onClick={() => setIsOpen(false)}
                className={`flex items-center space-x-3 rounded-xl px-4 py-3 text-base font-medium ${
                  active(path) ? "bg-forest-600" : "text-forest-700 hover:bg-forest-100"
                }`}
              >
                <Icon className="h-5 w-5" />
                <span>{label}</span>
              </Link>
            ))}
            {loggedIn ? (
              <button
                onClick={() => {
                  logout();
                  setIsOpen(false);
                }}
                className="flex w-full items-center space-x-3 rounded-xl px-4 py-3 text-base font-medium text-forest-700 hover:bg-forest-100"
              >
                <LogOut className="h-5 w-5" />
                <span>Sign out</span>
              </button>
            ) : (
              <Link to="/login" onClick={() => setIsOpen(false)} className="block rounded-xl px-4 py-3 text-forest-700">
                Sign in
              </Link>
            )}
          </div>
        )}
      </div>
    </nav>
  );
};

export default Navigation;
