import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, Biohazard, Search, ShieldPlus, Stethoscope, Users, X } from "lucide-react";
import { api, errorText } from "../api";
import { Card, ErrorNote, Page } from "../components/ui";

// Free symptom checker (no login): pick the animal, tick its signs, see likely diseases.
// Texts come from the knowledge base (ml/disease/kb) in English, Hindi and Hinglish.

type Lang = "en" | "hi" | "hl";
type Text = Record<Lang, string>;
type Species = "cow" | "goat" | "sheep" | "dog" | "cat";

interface Symptom {
  id: string;
  cat: string;
  name: Text;
  short: Text;
  detail: Text;
}

interface Kb {
  species: Species;
  categories: Record<string, Text>;
  symptoms: Symptom[];
  diseases: number;
}

interface Result {
  id: string;
  probability: number;
  match: "strong" | "possible" | "less likely";
  matched: string[];
  also_check: string[];
  name: Text;
  about: Text;
  action: Text;
  prevent: Text;
  urgency: "emergency" | "soon" | "manage";
  contagious: boolean;
  zoonotic: boolean;
}

interface Prediction {
  results: Result[];
  ask_about: string[];
  emergency: boolean;
}

const SPECIES: { id: Species; emoji: string; name: Text }[] = [
  { id: "cow", emoji: "🐄", name: { en: "Cow / Buffalo", hi: "गाय / भैंस", hl: "Gaay / Bhains" } },
  { id: "goat", emoji: "🐐", name: { en: "Goat", hi: "बकरी", hl: "Bakri" } },
  { id: "sheep", emoji: "🐑", name: { en: "Sheep", hi: "भेड़", hl: "Bhed" } },
  { id: "dog", emoji: "🐕", name: { en: "Dog", hi: "कुत्ता", hl: "Kutta" } },
  { id: "cat", emoji: "🐈", name: { en: "Cat", hi: "बिल्ली", hl: "Billi" } },
];

const UI: Record<string, Text> = {
  title: { en: "Animal disease checker", hi: "पशु रोग जांच", hl: "Pashu rog jaanch" },
  subtitle: {
    en: "Free for every animal owner. Pick your animal, tick the signs you see, and get the likely diseases with what to do now.",
    hi: "हर पशुपालक के लिए मुफ्त। अपना पशु चुनें, जो लक्षण दिखें उन पर निशान लगाएं, और संभावित बीमारियां व अभी क्या करें जानें।",
    hl: "Har pashupaalak ke liye muft. Apna pashu chunein, jo lakshan dikhein un par nishaan lagaayein, aur sambhavit bimariyan va abhi kya karein jaanein.",
  },
  disclaimer: {
    en: "This is a guide, not a diagnosis. Always confirm with a veterinarian; call one at once if the animal is down, bleeding, struggling to breathe, or several animals fall sick.",
    hi: "यह एक मार्गदर्शन है, निदान नहीं। हमेशा पशु चिकित्सक से पुष्टि करें; अगर पशु बैठ गया हो, खून बह रहा हो, सांस में तकलीफ हो या कई पशु बीमार हों तो तुरंत डॉक्टर बुलाएं।",
    hl: "Ye ek margdarshan hai, nidaan nahi. Hamesha pashu doctor se pushti karein; agar pashu baith gaya ho, khoon beh raha ho, saans me takleef ho ya kai pashu beemar hon to turant doctor bulayein.",
  },
  pickAnimal: { en: "1. Which animal?", hi: "1. कौन सा पशु?", hl: "1. Kaun sa pashu?" },
  pickSigns: { en: "2. What signs do you see?", hi: "2. कौन से लक्षण दिख रहे हैं?", hl: "2. Kaun se lakshan dikh rahe hain?" },
  search: { en: "Search signs…", hi: "लक्षण खोजें…", hl: "Lakshan khojein…" },
  selected: { en: "selected", hi: "चुने गए", hl: "chune gaye" },
  clear: { en: "Clear", hi: "हटाएं", hl: "Hataayein" },
  seeResults: { en: "See results", hi: "नतीजे देखें", hl: "Nateeje dekhein" },
  results: { en: "3. Likely diseases", hi: "3. संभावित बीमारियां", hl: "3. Sambhavit bimariyan" },
  noneYet: {
    en: "Tick at least one sign above. Two or three signs give a much better answer.",
    hi: "ऊपर कम से कम एक लक्षण चुनें। दो-तीन लक्षणों से जवाब बहुत बेहतर मिलता है।",
    hl: "Upar kam se kam ek lakshan chunein. Do-teen lakshanon se jawaab bahut behtar milta hai.",
  },
  emergency: {
    en: "One of the likely diseases is an emergency. Call a veterinarian now.",
    hi: "संभावित बीमारियों में से एक आपातकाल है। अभी पशु चिकित्सक को बुलाएं।",
    hl: "Sambhavit bimariyon me se ek emergency hai. Abhi pashu doctor ko bulayein.",
  },
  askAbout: {
    en: "Also look for these signs; ticking them sharpens the result:",
    hi: "ये लक्षण भी देखें; चुनने से नतीजा और सटीक होगा:",
    hl: "Ye lakshan bhi dekhein; chunne se nateeja aur sateek hoga:",
  },
  matched: { en: "Matches your signs", hi: "आपके लक्षणों से मेल", hl: "Aapke lakshanon se mel" },
  alsoCheck: { en: "Also check for", hi: "यह भी देखें", hl: "Ye bhi dekhein" },
  doNow: { en: "What to do now", hi: "अभी क्या करें", hl: "Abhi kya karein" },
  prevent: { en: "Prevention", hi: "बचाव", hl: "Bachaav" },
  strong: { en: "Strong match", hi: "मज़बूत मेल", hl: "Mazboot mel" },
  possible: { en: "Possible", hi: "संभव", hl: "Sambhav" },
  "less likely": { en: "Less likely", hi: "कम संभावना", hl: "Kam sambhavna" },
  emergencyTag: { en: "Emergency: call vet now", hi: "आपातकाल: अभी डॉक्टर", hl: "Emergency: abhi doctor" },
  soonTag: { en: "See a vet soon", hi: "जल्दी डॉक्टर दिखाएं", hl: "Jaldi doctor dikhaayein" },
  manageTag: { en: "Usually manageable", hi: "आमतौर पर संभलने योग्य", hl: "Aam taur par sambhalne yogya" },
  contagious: { en: "Spreads to other animals", hi: "दूसरे पशुओं में फैलता है", hl: "Doosre pashuon me failta hai" },
  zoonotic: { en: "Can infect people", hi: "इंसानों को हो सकता है", hl: "Insaanon ko ho sakta hai" },
  diseasesKnown: { en: "diseases covered", hi: "बीमारियां शामिल", hl: "bimariyan shaamil" },
  moreInfo: { en: "More about this sign", hi: "इस लक्षण के बारे में और", hl: "Is lakshan ke baare me aur" },
};

const LANGS: { id: Lang; label: string }[] = [
  { id: "en", label: "English" },
  { id: "hi", label: "हिंदी" },
  { id: "hl", label: "Hinglish" },
];

function savedLang(): Lang {
  try {
    const v = localStorage.getItem("lms_disease_lang");
    if (v === "en" || v === "hi" || v === "hl") return v;
  } catch {
    /* private mode: fall back to English */
  }
  return "en";
}

const URGENCY_STYLE = {
  emergency: "bg-red-600 text-white",
  soon: "bg-amber-100 text-amber-900 border border-amber-300",
  manage: "bg-emerald-50 text-emerald-800 border border-emerald-200",
};

/** The "!" next to a sign: hover (or tap on a phone) shows the detailed explanation. */
function InfoBang({ text, label }: { text: string; label: string }) {
  // hover and tap kept apart: a tap on a phone fires a hover first, which must not cancel it
  const [hover, setHover] = useState(false);
  const [pinned, setPinned] = useState(false);
  const open = hover || pinned;
  return (
    <span className="relative inline-flex" onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}>
      <button
        type="button"
        aria-label={label}
        aria-expanded={open}
        onClick={(e) => {
          e.stopPropagation();
          setPinned((p) => !p);
        }}
        onBlur={() => {
          setPinned(false);
          setHover(false);
        }}
        className="flex h-5 w-5 items-center justify-center rounded-full bg-amber-500 text-xs font-bold text-white hover:bg-amber-600 focus:outline-none focus:ring-2 focus:ring-amber-300"
      >
        !
      </button>
      {open && (
        <span
          role="tooltip"
          className="absolute right-0 top-7 z-30 w-64 rounded-xl border border-gray-200 bg-white p-3 text-left text-xs leading-relaxed text-gray-800 shadow-xl sm:w-72"
        >
          {text}
        </span>
      )}
    </span>
  );
}

export default function Disease() {
  const [lang, setLangState] = useState<Lang>(savedLang);
  const [species, setSpecies] = useState<Species | null>(null);
  const [kb, setKb] = useState<Kb | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<Prediction | null>(null);
  const [error, setError] = useState<string | null>(null);
  const resultsRef = useRef<HTMLDivElement>(null);
  const t = (key: string) => UI[key][lang];

  const setLang = (l: Lang) => {
    setLangState(l);
    try {
      localStorage.setItem("lms_disease_lang", l);
    } catch {
      /* not saved; fine */
    }
  };

  useEffect(() => {
    if (!species) return;
    setKb(null);
    setSelected([]);
    setResult(null);
    api
      .get<Kb>("/api/public/disease/kb", { params: { species } })
      .then(({ data }) => setKb(data))
      .catch((e) => setError(errorText(e)));
  }, [species]);

  useEffect(() => {
    if (!species || selected.length === 0) {
      setResult(null);
      return;
    }
    const timer = window.setTimeout(() => {
      api
        .post<Prediction>("/api/public/disease/predict", { species, symptoms: selected })
        .then(({ data }) => {
          setResult(data);
          setError(null);
        })
        .catch((e) => setError(errorText(e)));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [species, selected]);

  const byId = useMemo(() => new Map((kb?.symptoms ?? []).map((s) => [s.id, s])), [kb]);
  const toggle = (id: string) => setSelected((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]));
  const add = (id: string) => setSelected((cur) => (cur.includes(id) ? cur : [...cur, id]));

  const groups = useMemo(() => {
    if (!kb) return [];
    const q = query.trim().toLowerCase();
    const match = (s: Symptom) =>
      !q || (["en", "hi", "hl"] as Lang[]).some((l) => s.name[l].toLowerCase().includes(q) || s.short[l].toLowerCase().includes(q));
    return Object.entries(kb.categories)
      .map(([cat, label]) => ({ cat, label, items: kb.symptoms.filter((s) => s.cat === cat && match(s)) }))
      .filter((g) => g.items.length);
  }, [kb, query]);

  const signName = (id: string) => byId.get(id)?.name[lang] ?? id;

  return (
    <Page
      title={t("title")}
      subtitle={t("subtitle")}
      actions={
        <div className="flex gap-1 rounded-xl bg-white/80 p-1 text-sm shadow-sm" role="group" aria-label="Language">
          {LANGS.map((l) => (
            <button
              key={l.id}
              onClick={() => setLang(l.id)}
              aria-pressed={lang === l.id}
              className={`rounded-lg px-3 py-1 ${lang === l.id ? "bg-forest-600 text-white" : "text-forest-800 hover:bg-forest-100"}`}
            >
              {l.label}
            </button>
          ))}
        </div>
      }
    >
      <ErrorNote text={error} />
      <div className="mb-6 flex gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        <p>{t("disclaimer")}</p>
      </div>

      <Card className="mb-6">
        <h2 className="mb-3 text-lg font-semibold text-forest-800">{t("pickAnimal")}</h2>
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-5">
          {SPECIES.map((s) => (
            <button
              key={s.id}
              onClick={() => setSpecies(s.id)}
              aria-pressed={species === s.id}
              className={`flex flex-col items-center gap-1 rounded-xl border px-2 py-3 text-sm transition ${
                species === s.id
                  ? "border-transparent bg-forest-600 text-white shadow"
                  : "border-gray-200 bg-white/80 text-forest-800 hover:bg-forest-50"
              }`}
            >
              <span className="text-3xl" aria-hidden>
                {s.emoji}
              </span>
              {s.name[lang]}
            </button>
          ))}
        </div>
        {kb && (
          <p className="mt-3 text-xs text-gray-500">
            {kb.diseases} {t("diseasesKnown")}
          </p>
        )}
      </Card>

      {kb && (
        <Card className="mb-6">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-lg font-semibold text-forest-800">{t("pickSigns")}</h2>
            <div className="relative w-full sm:w-64">
              <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-gray-400" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t("search")}
                className="w-full rounded-xl border border-gray-200 bg-white py-2 pl-9 pr-3 text-sm focus:border-forest-500 focus:outline-none"
              />
            </div>
          </div>
          <div className="space-y-5">
            {groups.map((g) => (
              <section key={g.cat}>
                <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-forest-700">{g.label[lang]}</h3>
                <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {g.items.map((s) => {
                    const on = selected.includes(s.id);
                    return (
                      <div
                        key={s.id}
                        className={`flex items-start gap-2 rounded-xl border p-3 transition ${
                          on ? "border-forest-500 bg-forest-50" : "border-gray-200 bg-white/70 hover:border-forest-300"
                        }`}
                      >
                        <label className="flex flex-1 cursor-pointer items-start gap-2">
                          <input
                            type="checkbox"
                            checked={on}
                            onChange={() => toggle(s.id)}
                            aria-label={s.name[lang]}
                            aria-describedby={`sign-${s.id}`}
                            className="mt-1 h-4 w-4 shrink-0 accent-forest-600"
                          />
                          <span>
                            <span className="block text-sm font-medium text-forest-800">{s.name[lang]}</span>
                            <span id={`sign-${s.id}`} className="block text-xs text-gray-600">
                              {s.short[lang]}
                            </span>
                          </span>
                        </label>
                        <InfoBang text={s.detail[lang]} label={`${t("moreInfo")}: ${s.name[lang]}`} />
                      </div>
                    );
                  })}
                </div>
              </section>
            ))}
          </div>
        </Card>
      )}

      {kb && (
        <div ref={resultsRef}>
          <Card>
            <h2 className="mb-3 text-lg font-semibold text-forest-800">{t("results")}</h2>
            {!result || result.results.length === 0 ? (
              <p className="text-sm text-gray-600">{t("noneYet")}</p>
            ) : (
              <div className="space-y-4">
                {result.emergency && (
                  <div className="flex gap-2 rounded-xl bg-red-600 px-4 py-3 text-sm font-semibold text-white">
                    <AlertTriangle className="h-5 w-5 shrink-0" /> {t("emergency")}
                  </div>
                )}
                {result.ask_about.length > 0 && (
                  <div className="text-sm">
                    <p className="mb-2 text-gray-700">{t("askAbout")}</p>
                    <div className="flex flex-wrap gap-2">
                      {result.ask_about.map((id) => (
                        <button
                          key={id}
                          onClick={() => add(id)}
                          className="rounded-full border border-forest-300 bg-white px-3 py-1 text-xs text-forest-800 hover:bg-forest-50"
                        >
                          + {signName(id)}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                {result.results.map((r, i) => (
                  <article key={r.id} className="rounded-2xl border border-gray-200 bg-white/80 p-4">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <h3 className="text-lg font-semibold text-forest-800">
                        {i + 1}. {r.name[lang]}
                      </h3>
                      <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${URGENCY_STYLE[r.urgency]}`}>
                        {t(`${r.urgency}Tag`)}
                      </span>
                    </div>
                    <div className="mt-2 flex items-center gap-3">
                      <div className="h-2 flex-1 overflow-hidden rounded-full bg-gray-100">
                        <div
                          className={`h-full rounded-full ${r.match === "strong" ? "bg-forest-600" : r.match === "possible" ? "bg-amber-500" : "bg-gray-400"}`}
                          style={{ width: `${Math.max(4, Math.round(r.probability * 100))}%` }}
                        />
                      </div>
                      <span className="w-28 text-right text-xs font-medium text-gray-700">
                        {t(r.match)} · {Math.round(r.probability * 100)}%
                      </span>
                    </div>
                    <p className="mt-2 text-sm text-gray-700">{r.about[lang]}</p>
                    <div className="mt-2 flex flex-wrap gap-2 text-xs">
                      {r.contagious && (
                        <span className="inline-flex items-center gap-1 rounded-full bg-orange-50 px-2 py-0.5 text-orange-800">
                          <Users className="h-3 w-3" /> {t("contagious")}
                        </span>
                      )}
                      {r.zoonotic && (
                        <span className="inline-flex items-center gap-1 rounded-full bg-red-50 px-2 py-0.5 text-red-800">
                          <Biohazard className="h-3 w-3" /> {t("zoonotic")}
                        </span>
                      )}
                    </div>
                    {r.matched.length > 0 && (
                      <p className="mt-3 text-xs text-gray-600">
                        <span className="font-semibold text-forest-800">{t("matched")}:</span>{" "}
                        {r.matched.map(signName).join(", ")}
                      </p>
                    )}
                    {r.also_check.length > 0 && (
                      <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs">
                        <span className="font-semibold text-forest-800">{t("alsoCheck")}:</span>
                        {r.also_check.map((id) => (
                          <button
                            key={id}
                            onClick={() => add(id)}
                            className="rounded-full border border-gray-300 px-2 py-0.5 text-gray-700 hover:bg-forest-50"
                          >
                            + {signName(id)}
                          </button>
                        ))}
                      </div>
                    )}
                    <div className="mt-3 grid gap-2 sm:grid-cols-2">
                      <div className="rounded-xl bg-forest-50 p-3 text-sm">
                        <div className="mb-1 flex items-center gap-1 font-semibold text-forest-800">
                          <Stethoscope className="h-4 w-4" /> {t("doNow")}
                        </div>
                        <p className="text-gray-700">{r.action[lang]}</p>
                      </div>
                      <div className="rounded-xl bg-sky-50 p-3 text-sm">
                        <div className="mb-1 flex items-center gap-1 font-semibold text-sky-900">
                          <ShieldPlus className="h-4 w-4" /> {t("prevent")}
                        </div>
                        <p className="text-gray-700">{r.prevent[lang]}</p>
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </Card>
        </div>
      )}

      {selected.length > 0 && (
        <div className="fixed inset-x-0 bottom-0 z-40 border-t border-gray-200 bg-white/95 px-4 py-3 shadow-lg backdrop-blur">
          <div className="mx-auto flex max-w-6xl items-center gap-3">
            <span className="text-sm font-medium text-forest-800">
              {selected.length} {t("selected")}
            </span>
            <button
              onClick={() => setSelected([])}
              className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-sm text-gray-600 hover:bg-gray-100"
            >
              <X className="h-4 w-4" /> {t("clear")}
            </button>
            <button
              onClick={() => resultsRef.current?.scrollIntoView({ behavior: "smooth" })}
              className="ml-auto rounded-xl bg-forest-600 px-4 py-2 text-sm font-semibold text-white shadow hover:bg-forest-700"
            >
              {t("seeResults")} {result?.results[0] ? `· ${result.results[0].name[lang]}` : ""}
            </button>
          </div>
        </div>
      )}
      {selected.length > 0 && <div className="h-16" aria-hidden />}
    </Page>
  );
}
