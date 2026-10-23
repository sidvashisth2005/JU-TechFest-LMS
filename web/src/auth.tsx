import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, getToken, setToken } from "./api";

interface AuthState {
  loggedIn: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [loggedIn, setLoggedIn] = useState(() => Boolean(getToken()));

  useEffect(() => {
    const onLogout = () => setLoggedIn(false);
    window.addEventListener("lms:logout", onLogout);
    return () => window.removeEventListener("lms:logout", onLogout);
  }, []);

  const login = async (username: string, password: string) => {
    const { data } = await api.post("/api/auth/login", { username, password });
    setToken(data.token);
    setLoggedIn(true);
  };

  const logout = () => {
    setToken(null);
    setLoggedIn(false);
  };

  return <AuthContext.Provider value={{ loggedIn, login, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
