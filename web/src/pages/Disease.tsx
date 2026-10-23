import { useEffect, useMemo, useState } from "react";
import { Info, Search, Stethoscope, X } from "lucide-react";
import { api, errorText } from "../api";
import { Card, Empty, ErrorNote, Page } from "../components/ui";
import { titleCase } from "../format";
import { symptomDescriptions } from "../symptomInfo";

interface Prediction {
  predictions: { disease: string; probability: number }[];
  known: string[];
  unknown: string[];
  note: string;
}

interface ModelInfo {
  model: string;
  diseases: number;
  symptoms: number;
  partial_input_top3_accuracy: number;
  note: string;
}

export default function Disease() {
  const [all, setAll] = useState<string[]>([]);
  const [model, setModel] = useState<ModelInfo | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<Prediction | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get("/api/disease/symptoms")
      .then(({ data }) => {
        setAll(data.symptoms);
        setModel(data.model);
      })
      .catch((e) => setError(errorText(e)));
  }, []);

  const filtered = useMemo(
    () => all.filter((s) => s.toLowerCase().includes(query.toLowerCase().replace(/ /g, "_"))),
    [all, query],
  );

  const toggle = (s: string) => {
    setResult(null);
    setSelected((prev) => (prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s]));
  };

  const predict = async () => {
    setBusy(true);
    setError(null);
    try {
      const { data } = await api.post<Prediction>("/api/disease/predict", { symptoms: selected });
      setResult(data);
    } catch (e) {
      setResult(null);
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Page
      title="Disease checker"
      subtitle={
        model
          ? `Tick what you observe. ${model.diseases} diseases, ${model.symptoms} symptoms · right answer in the top 3 for ${Math.round(model.partial_input_top3_accuracy * 100)}% of cases with just 2–3 symptoms`
          : "Tick what you observe"
      }
    >
      <ErrorNote text={error} />
      <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
        <Card>
          <div className="mb-4 flex items-center gap-2 rounded-xl border bg-white px-3 py-2">
            <Search className="h-4 w-4 text-gray-400" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search symptoms…"
              className="w-full outline-none"
            />
          </div>
          <div className="grid max-h-[520px] grid-cols-1 gap-2 overflow-y-auto pr-1 sm:grid-cols-2">
            {filtered.map((s) => {
              const on = selected.includes(s);
              return (
                <label
                  key={s}
                  title={symptomDescriptions[s] ?? ""}
                  className={`flex cursor-pointer items-start gap-2 rounded-xl border px-3 py-2 text-sm transition ${
                    on ? "border-emerald-500 bg-emerald-50" : "bg-white/80 hover:bg-emerald-50/50"
                  }`}
                >
                  <input type="checkbox" checked={on} onChange={() => toggle(s)} className="mt-0.5" />
                  <span>{titleCase(s)}</span>
                </label>
              );
            })}
          </div>
        </Card>

        <div className="space-y-6">
          <Card>
            <h2 className="mb-3 text-xl font-semibold text-forest-800">Selected ({selected.length})</h2>
            {selected.length === 0 ? (
              <p className="text-sm text-gray-500">Pick at least two symptoms.</p>
            ) : (
              <div className="mb-4 flex flex-wrap gap-2">
                {selected.map((s) => (
                  <button
                    key={s}
                    onClick={() => toggle(s)}
                    className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-3 py-1 text-sm text-emerald-900"
                  >
                    {titleCase(s)} <X className="h-3 w-3" />
                  </button>
                ))}
              </div>
            )}
            <button
              onClick={predict}
              disabled={selected.length < 2 || busy}
              className="btn-primary mt-2 w-full justify-center disabled:opacity-50"
            >
              <Stethoscope className="h-4 w-4" />
              {busy ? "Checking…" : "Check"}
            </button>
          </Card>

          <Card>
            <h2 className="mb-3 text-xl font-semibold text-forest-800">Most likely</h2>
            {!result ? (
              <Empty>Results appear here.</Empty>
            ) : result.predictions.length === 0 ? (
              <Empty>None of these symptoms are known to the model.</Empty>
            ) : (
              <ol className="space-y-3">
                {result.predictions.map((p, i) => (
                  <li key={p.disease}>
                    <div className="mb-1 flex justify-between text-sm">
                      <span className={i === 0 ? "font-semibold text-forest-800" : "text-gray-800"}>
                        {i + 1}. {titleCase(p.disease)}
                      </span>
                      <span className="tabular-nums text-gray-600">{Math.round(p.probability * 100)}%</span>
                    </div>
                    <div className="h-2 rounded-full bg-gray-100">
                      <div
                        className="h-2 rounded-full bg-emerald-600"
                        style={{ width: `${Math.max(2, p.probability * 100)}%` }}
                      />
                    </div>
                  </li>
                ))}
              </ol>
            )}
            <p className="mt-4 flex gap-2 text-xs text-gray-500">
              <Info className="h-4 w-4 shrink-0" />
              {result?.note ?? model?.note ?? "Suggestions only — always confirm with a veterinarian."}
            </p>
          </Card>
        </div>
      </div>
    </Page>
  );
}
