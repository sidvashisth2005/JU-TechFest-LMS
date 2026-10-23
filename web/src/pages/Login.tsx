import { useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Leaf, LogIn } from "lucide-react";
import { useAuth } from "../auth";
import { errorText } from "../api";

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username, password);
      const to = (location.state as { from?: string } | null)?.from ?? "/herd";
      navigate(to, { replace: true });
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-hero-gradient px-4">
      <form onSubmit={submit} className="card-glass w-full max-w-sm rounded-2xl p-8 shadow-lg">
        <div className="mb-6 flex items-center gap-3">
          <div className="icon-box !h-12 !w-12">
            <Leaf className="h-6 w-6" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-forest-800">LMS</h1>
            <p className="text-sm text-[hsl(var(--muted-foreground))]">Livestock Monitoring System</p>
          </div>
        </div>
        <label className="mb-1 block text-sm font-medium text-forest-800" htmlFor="user">Username</label>
        <input
          id="user"
          className="mb-4 w-full rounded-xl border bg-white px-3 py-2 outline-none focus:ring-2 focus:ring-emerald-600"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
        />
        <label className="mb-1 block text-sm font-medium text-forest-800" htmlFor="pass">Password</label>
        <input
          id="pass"
          type="password"
          className="mb-4 w-full rounded-xl border bg-white px-3 py-2 outline-none focus:ring-2 focus:ring-emerald-600"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
          autoFocus
        />
        {error && <p className="mb-4 text-sm text-red-700">{error}</p>}
        <button type="submit" disabled={busy || !password} className="btn-primary w-full justify-center disabled:opacity-60">
          <LogIn className="h-4 w-4" />
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
