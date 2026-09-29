"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

/* The Insights tab: statistics over the same journeys the tracker lists.
   Everything is computed here from dates the API already returns, so the
   tab never disagrees with the table next to it. */

export type InsightJourney = {
  journey_id: string;
  status: string;
  applied_at: number | null;
  rejected_at: number | null;
  interviews: { interview_type: string; scheduled_at: number | null; created_at: number }[];
  events: { kind: string; occurred_at: number; created_at?: number }[];
};

/* Validated against the panel surface for colour-blind separation of adjacent
   series. Colour follows the entity: blue is always "you sent it", green always
   "they invited you", pink always a rejection. */
const C = {
  sub: "#3987e5",
  inv: "#199e70",
  rej: "#d55181",
  rejInt: "#c98500",
  offer: "#9085e9",
  drop: "#8a93a8",
  silent: "#59617a",
  wait: "#343b4f",
  grid: "#20263a",
  axis: "#343b4f",
  text: "#e6e8ee",
  panel: "#141822",
};

const DAY = 86_400_000;
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const FIRST_ROUNDS: Record<string, number> = { recruiter: 1, screening: 2 };

/* ---------- dates ---------- */

const midnight = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
const fromTs = (ts: number) => midnight(new Date(ts * 1000));
const addDays = (d: Date, n: number) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
const daysBetween = (a: Date, b: Date) => Math.round((+b - +a) / DAY);
const wdIdx = (d: Date) => (d.getDay() + 6) % 7;
const fmt = (d: Date) => `${d.getDate()} ${MON[d.getMonth()]} ${d.getFullYear()}`;
const earliest = (ds: (Date | null)[]) =>
  ds.reduce<Date | null>((m, d) => (d && (!m || d < m) ? d : m), null);

type Grain = "day" | "week" | "month" | "quarter";

/* Every period is named by the date it starts on. */
const GRAIN: Record<
  Grain,
  { start: (d: Date) => Date; next: (d: Date) => Date; label: (d: Date) => string; avg: number }
> = {
  day: { start: midnight, next: (d) => addDays(d, 1), label: fmt, avg: 7 },
  week: {
    start: (d) => addDays(midnight(d), -wdIdx(d)),
    next: (d) => addDays(d, 7),
    label: (d) => `Week of ${fmt(d)}`,
    avg: 4,
  },
  month: {
    start: (d) => new Date(d.getFullYear(), d.getMonth(), 1),
    next: (d) => new Date(d.getFullYear(), d.getMonth() + 1, 1),
    label: (d) => `${MON[d.getMonth()]} ${d.getFullYear()}`,
    avg: 3,
  },
  quarter: {
    start: (d) => new Date(d.getFullYear(), d.getMonth() - (d.getMonth() % 3), 1),
    next: (d) => new Date(d.getFullYear(), d.getMonth() + 3, 1),
    label: (d) => `Q${d.getMonth() / 3 + 1} ${d.getFullYear()}`,
    avg: 2,
  },
};
const AVG_LABEL: Record<Grain, string> = {
  day: "7-day average",
  week: "4-week average",
  month: "3-month average",
  quarter: "2-quarter average",
};

function periods(from: Date, to: Date, g: Grain) {
  const out: Date[] = [];
  for (let d = GRAIN[g].start(from); d <= to; d = GRAIN[g].next(d)) out.push(d);
  return out;
}
function indexer(ps: Date[], g: Grain) {
  const idx = new Map(ps.map((p, i) => [+p, i]));
  return (d: Date | null) => (d ? idx.get(+GRAIN[g].start(d)) : undefined);
}

/* ---------- the model ---------- */

type Cat = "offer" | "active" | "rej_int" | "rej_cv" | "dropped" | "silent" | "waiting";

type App = {
  status: string;
  applied: Date | null;
  /* Submission date, or — for a role a recruiter brought to you — the first thing
     that happened. What the range filter and the outcome bars group by. */
  anchor: Date;
  rejected: Date | null;
  rounds: { type: string; held: Date | null }[];
  firstInvite: Date | null;
  firstReply: Date | null;
  cat: Cat;
};

/* When you heard about it: the day you logged it, unless you logged it after it
   happened — then the day it happened. Imported rows only have the latter. */
const heardOn = (logged: number | undefined, happened: number | null) =>
  fromTs(happened && (!logged || logged > happened) ? happened : (logged ?? happened!));

function toApp(j: InsightJourney): App | null {
  if (j.status === "draft") return null; // never sent: not an application
  const applied = j.applied_at ? fromTs(j.applied_at) : null;
  const rejected = j.rejected_at ? fromTs(j.rejected_at) : null;
  const rounds = j.interviews.map((i) => ({
    type: i.interview_type,
    held: i.scheduled_at ? fromTs(i.scheduled_at) : null,
  }));
  const firstInvite = earliest([
    ...j.interviews.map((i) => heardOn(i.created_at, i.scheduled_at)),
    ...j.events.filter((e) => e.kind === "contact").map((e) => heardOn(e.created_at, e.occurred_at)),
  ]);
  const firstReply = earliest([firstInvite, rejected]);
  const anchor = applied ?? earliest([firstInvite, rejected, ...rounds.map((r) => r.held)]);
  if (!anchor) return null;
  const cat: Cat =
    j.status === "offer" ? "offer"
    : j.status === "rejected" ? (rounds.length ? "rej_int" : "rej_cv")
    : j.status === "dropped" ? "dropped"
    : j.status === "in_progress" || j.status === "on_hold" ? "active"
    : j.status === "silent" ? "silent"
    : "waiting";
  return { status: j.status, applied, anchor, rejected, rounds, firstInvite, firstReply, cat };
}

/* ---------- small helpers ---------- */

const pct = (a: number, b: number) => (b ? Math.round((100 * a) / b) : 0);
const median = (a: number[]) => {
  if (!a.length) return null;
  const b = [...a].sort((x, y) => x - y);
  return b[Math.floor((b.length - 1) / 2)];
};
const quantile = (a: number[], q: number) => {
  const b = [...a].sort((x, y) => x - y);
  return b[Math.min(b.length - 1, Math.floor(q * b.length))];
};
function niceMax(v: number): [number, number] {
  for (const step of [1, 2, 4, 5, 10, 20, 25, 50]) if (step * 4 >= v) return [step * Math.ceil(v / step), step];
  return [Math.ceil(v / 50) * 50, 50];
}
const rgba = (hex: string, a: number) =>
  `rgba(${parseInt(hex.slice(1, 3), 16)},${parseInt(hex.slice(3, 5), 16)},${parseInt(hex.slice(5, 7), 16)},${a})`;

/* A bar with a rounded data end and a square foot on the baseline. */
function barPath(x: number, y: number, w: number, h: number, down = false) {
  if (h <= 0 || w <= 0) return "";
  const r = Math.min(4, w / 2, h);
  return down
    ? `M${x},${y} h${w} v${h - r} q0,${r} ${-r},${r} h${-(w - 2 * r)} q${-r},0 ${-r},${-r} Z`
    : `M${x},${y + h} v${-(h - r)} q0,${-r} ${r},${-r} h${w - 2 * r} q${r},0 ${r},${r} v${h - r} Z`;
}

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setWidth(Math.floor(e.contentRect.width)));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, width] as const;
}

type TipRow = [color: string, label: string, value: string | number];
type Tip = { x: number; y: number; title: string; rows: TipRow[] } | null;
type ShowTip = (e: React.MouseEvent, title: string, rows: TipRow[]) => void;

function Seg<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: [T, string][];
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div role="group" aria-label={label} className="inline-flex border border-border rounded overflow-hidden shrink-0">
      {options.map(([key, text]) => (
        <button
          key={key}
          onClick={() => onChange(key)}
          aria-pressed={value === key}
          className={`text-xs px-2.5 py-1 ${
            value === key ? "bg-panel2 text-text" : "text-subtle hover:text-text"
          }`}
        >
          {text}
        </button>
      ))}
    </div>
  );
}

function Panel({
  title,
  question,
  controls,
  children,
}: {
  title: string;
  question: string;
  controls?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="rounded-xl border border-border bg-panel p-4 space-y-3 min-w-0">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold">{title}</h2>
          <p className="text-xs text-subtle mt-0.5">{question}</p>
        </div>
        {controls}
      </div>
      {children}
    </section>
  );
}

function Legend({ items }: { items: [string, string, ("box" | "line")?][] }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-subtle">
      {items.map(([color, label, shape]) => (
        <span key={label} className="inline-flex items-center gap-1.5">
          <i
            className={shape === "line" ? "inline-block w-3.5 h-0.5 rounded" : "inline-block w-2.5 h-2.5 rounded-sm"}
            style={{ background: color }}
          />
          {label}
        </span>
      ))}
    </div>
  );
}

function Readout({ children }: { children: ReactNode }) {
  return <p className="text-[13px] leading-relaxed [&_strong]:font-semibold">{children}</p>;
}

const AXIS_TEXT = "fill-[#6b7388] text-[11px] tabular-nums";

/* ---------- the tab ---------- */

const RANGES: [string, string][] = [
  ["0", "All time"],
  ["12", "12 months"],
  ["6", "6 months"],
];

export default function Insights({
  journeys,
  quietDays,
  onShowStatus,
}: {
  journeys: InsightJourney[];
  quietDays: number;
  onShowStatus: (status: string) => void;
}) {
  const [range, setRange] = useState("0");
  const [tip, setTip] = useState<Tip>(null);
  const today = useMemo(() => midnight(new Date()), []);

  const all = useMemo(() => journeys.map(toApp).filter((a): a is App => a !== null), [journeys]);
  const cutoff = useMemo(() => {
    const months = Number(range);
    if (months) return new Date(today.getFullYear(), today.getMonth() - months + 1, 1);
    return earliest(all.map((a) => a.anchor)) ?? today;
  }, [range, all, today]);
  const apps = useMemo(() => all.filter((a) => a.anchor >= cutoff), [all, cutoff]);

  const showTip: ShowTip = (e, title, rows) => setTip({ x: e.clientX, y: e.clientY, title, rows });
  const hideTip = () => setTip(null);

  if (!all.length) {
    return <p className="text-sm text-subtle">No sent applications yet. Statistics appear once you have some.</p>;
  }

  const props = { apps, all, cutoff, today, quietDays, showTip, hideTip };
  return (
    <div className="space-y-5" onMouseLeave={hideTip}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-subtle max-w-2xl">
          How the search is going: the pace you keep, what becomes of each application, and how
          long employers take to answer.
        </p>
        <Seg label="Submitted within" value={range} options={RANGES} onChange={setRange} />
      </div>

      <Summary apps={apps} quietDays={quietDays} onShowStatus={onShowStatus} />
      <Cadence {...props} />
      <PeriodTable {...props} />
      <Outcomes {...props} />
      <Delays {...props} />
      <Waiting {...props} />
      <Weekdays {...props} />

      {tip && (
        <div
          className="fixed z-50 pointer-events-none bg-panel2 border border-border rounded-lg px-2.5 py-2 text-xs shadow-xl max-w-[260px]"
          style={{
            left: Math.min(tip.x + 14, window.innerWidth - 270),
            top: Math.min(tip.y + 14, window.innerHeight - 120),
          }}
        >
          <div className="font-semibold mb-0.5">{tip.title}</div>
          {tip.rows.map(([color, label, value]) => (
            <div key={label} className="flex items-center gap-2 text-subtle">
              <i className="inline-block w-2 h-2 rounded-sm" style={{ background: color }} />
              <span>{label}</span>
              <span className="ml-auto pl-3 text-text tabular-nums">{value}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

type ChartProps = {
  apps: App[];
  all: App[];
  cutoff: Date;
  today: Date;
  quietDays: number;
  showTip: ShowTip;
  hideTip: () => void;
};

/* ---------- headline: rates, then your sheet's counts ---------- */

function Summary({
  apps,
  quietDays,
  onShowStatus,
}: {
  apps: App[];
  quietDays: number;
  onShowStatus: (status: string) => void;
}) {
  const sent = apps.filter((a) => a.applied);
  const replied = sent.filter((a) => a.firstReply).length;
  const invited = sent.filter((a) => a.rounds.length).length;
  const rejDays = sent.filter((a) => a.rejected).map((a) => daysBetween(a.applied!, a.rejected!));
  const count = (...s: string[]) => apps.filter((a) => s.includes(a.status)).length;
  const rounds = apps.flatMap((a) => a.rounds.filter((r) => r.held));
  const roundCount = (f: (t: string) => boolean) => rounds.filter((r) => f(r.type)).length;

  const tiles: [string, string, string][] = [
    ["Heard back", `${pct(replied, sent.length)}%`, `${replied} of ${sent.length} submitted`],
    ["Invited to a round", `${pct(invited, sent.length)}%`, `${invited} of ${sent.length} submitted`],
    [
      "Median wait for a rejection",
      rejDays.length ? `${median(rejDays)} days` : "–",
      rejDays.length ? `80% arrive within ${quantile(rejDays, 0.8)} days` : "no rejections yet",
    ],
  ];

  /* The five status lines partition the total, as the sheet's list did. A line
     that is exactly one tracker status links to it. */
  const appLines: [string, number, string | null, boolean?][] = [
    ["Applications", apps.length, "all"],
    ["Open", count("applied", "silent", "in_progress"), null],
    [`no reply for ${quietDays}+ days`, count("silent"), "silent", true],
    ["On hold", count("on_hold"), "on_hold"],
    ["Rejected", count("rejected"), "rejected"],
    ["without any interview", apps.filter((a) => a.cat === "rej_cv").length, null, true],
    ["Withdrawn", count("dropped"), "dropped"],
    ["Offers", count("offer"), "offer"],
  ];
  const roundLines: [string, number, null, boolean?][] = [
    ["Recruiter", roundCount((t) => t === "recruiter"), null],
    ["Screening", roundCount((t) => t === "screening"), null],
    ["Second stage", roundCount((t) => !FIRST_ROUNDS[t]), null],
    ["case studies", roundCount((t) => t === "case_study"), null, true],
  ];

  const ledger = (heading: string, lines: [string, number, string | null, boolean?][]) => (
    <div>
      <h3 className="text-[10px] uppercase tracking-widest text-subtle mb-1">{heading}</h3>
      <dl className="grid grid-cols-[1fr_auto] text-sm tabular-nums">
        {lines.map(([label, value, status, sub]) => (
          <div key={label} className="contents">
            <dt className={`py-1 border-b border-[#20263a] ${sub ? "pl-4 text-subtle" : ""}`}>
              {status ? (
                <button onClick={() => onShowStatus(status)} className="hover:text-accent text-left">
                  {label} <span className="text-subtle">→</span>
                </button>
              ) : (
                label
              )}
            </dt>
            <dd className={`py-1 border-b border-[#20263a] text-right ${sub ? "text-subtle" : "font-semibold"}`}>
              {value}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {tiles.map(([k, v, s]) => (
          <div key={k} className="rounded-xl border border-border bg-panel px-4 py-3">
            <div className="text-[10px] uppercase tracking-widest text-subtle">{k}</div>
            <div className="text-2xl font-semibold mt-1">{v}</div>
            <div className="text-xs text-subtle mt-1">{s}</div>
          </div>
        ))}
      </div>
      <div className="rounded-xl border border-border bg-panel p-4 grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-4">
        {ledger("Applications", appLines)}
        {ledger("Interview rounds held", roundLines)}
      </div>
    </div>
  );
}

/* ---------- applications over time ---------- */

function Cadence({ apps, all, cutoff, today, showTip, hideTip }: ChartProps) {
  const [grain, setGrain] = useState<Grain>("week");
  const [ref, W] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);

  const data = useMemo(() => {
    const ps = periods(cutoff, today, grain);
    const at = indexer(ps, grain);
    const sub = ps.map(() => 0);
    const rej = ps.map(() => 0);
    apps.forEach((a) => {
      const i = at(a.applied);
      if (i !== undefined) sub[i]++;
    });
    all.forEach((a) => {
      const i = at(a.rejected);
      if (i !== undefined) rej[i]++;
    });
    const k = GRAIN[grain].avg;
    const avg = sub.map((_, i) => {
      const win = sub.slice(Math.max(0, i - k + 1), i + 1);
      return win.reduce((x, y) => x + y, 0) / win.length;
    });
    // The sentence under the chart speaks in weeks whatever the grouping.
    const wps = periods(cutoff, today, "week");
    const wat = indexer(wps, "week");
    const wk = wps.map(() => 0);
    apps.forEach((a) => {
      const i = wat(a.applied);
      if (i !== undefined) wk[i]++;
    });
    const w4 = wk.map((_, i) => wk.slice(Math.max(0, i - 3), i + 1).reduce((x, y) => x + y, 0) / Math.min(4, i + 1));
    let longest = 0;
    let run = 0;
    wk.forEach((v) => {
      run = v ? 0 : run + 1;
      longest = Math.max(longest, run);
    });
    return { ps, sub, rej, avg, now: w4[w4.length - 1] ?? 0, best: Math.max(0, ...w4), longest };
  }, [apps, all, cutoff, today, grain]);

  const H = 240, L = 30, R = 8, T = 8, B = 22;
  const n = data.ps.length;
  const pw = Math.max(0, W - L - R);
  const bw = n ? pw / n : 0;
  const [ymax, step] = niceMax(Math.max(1, ...data.sub, ...data.rej));
  const zero = T + (H - T - B) / 2;
  const half = (H - T - B) / 2;
  const y = (v: number) => zero - (v / ymax) * half;
  const gap = bw > 4 ? Math.min(2, bw * 0.2) : 0;

  const ticks: number[] = [];
  for (let v = -ymax; v <= ymax; v += step) ticks.push(v);
  const monthLabels: [number, string][] = [];
  let lastX = -99;
  let lastYear = -1;
  data.ps.forEach((d, i) => {
    if (i && data.ps[i - 1].getMonth() === d.getMonth()) return;
    const x = L + i * bw;
    if (x - lastX < 46) return;
    const newYear = d.getFullYear() !== lastYear;
    lastYear = d.getFullYear();
    lastX = x;
    monthLabels.push([x, MON[d.getMonth()] + (newYear ? ` ${String(d.getFullYear()).slice(2)}` : "")]);
  });

  return (
    <Panel
      title="Applications over time"
      question="What you sent goes up; the rejections that arrived in the same period go down."
      controls={
        <Seg
          label="Group by"
          value={grain}
          onChange={setGrain}
          options={[["day", "Day"], ["week", "Week"], ["month", "Month"]]}
        />
      }
    >
      <Legend
        items={[
          [C.sub, "Submitted"],
          [C.rej, "Rejections received"],
          [C.text, `${AVG_LABEL[grain]} of submissions`, "line"],
        ]}
      />
      <div ref={ref} className="w-full">
        {W > 0 && (
          <svg width={W} height={H} className="block overflow-visible">
            {ticks.map((v) => (
              <g key={v}>
                <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke={v ? C.grid : C.axis} />
                <text x={L - 6} y={y(v) + 3.5} textAnchor="end" className={AXIS_TEXT}>
                  {Math.abs(v)}
                </text>
              </g>
            ))}
            {monthLabels.map(([x, label]) => (
              <text key={x} x={x} y={H - 6} className={AXIS_TEXT}>
                {label}
              </text>
            ))}
            {hover !== null && (
              <rect x={L + hover * bw} y={T} width={Math.max(bw, 2)} height={H - T - B} fill={C.text} opacity={0.07} />
            )}
            {data.sub.map((v, i) => (
              <path key={`s${i}`} d={barPath(L + i * bw + gap / 2, y(v), bw - gap, zero - y(v) - 1)} fill={C.sub} />
            ))}
            {data.rej.map((v, i) => (
              <path key={`r${i}`} d={barPath(L + i * bw + gap / 2, zero + 1, bw - gap, y(-v) - zero - 1, true)} fill={C.rej} />
            ))}
            <path
              d={data.avg.map((v, i) => `${i ? "L" : "M"}${L + (i + 0.5) * bw},${y(v)}`).join("")}
              fill="none"
              stroke={C.text}
              strokeWidth={grain === "day" ? 1.5 : 2}
              strokeLinejoin="round"
              opacity={0.85}
            />
            <rect
              x={L}
              y={T}
              width={pw}
              height={H - T - B}
              fill="transparent"
              onMouseMove={(e) => {
                const i = Math.max(0, Math.min(n - 1, Math.floor((e.nativeEvent.offsetX - L) / bw)));
                setHover(i);
                showTip(e, GRAIN[grain].label(data.ps[i]) + (i === n - 1 && grain !== "day" ? " (so far)" : ""), [
                  [C.sub, "Submitted", data.sub[i]],
                  [C.rej, "Rejections received", data.rej[i]],
                  [C.text, AVG_LABEL[grain], data.avg[i].toFixed(1)],
                ]);
              }}
              onMouseLeave={() => {
                setHover(null);
                hideTip();
              }}
            />
          </svg>
        )}
      </div>
      <Readout>
        Right now you send <strong>{data.now.toFixed(1)} a week</strong> (4-week average), against a best
        stretch of {data.best.toFixed(1)}. Longest gap: <strong>{data.longest} week{data.longest === 1 ? "" : "s"}</strong>{" "}
        without a submission.
      </Readout>
    </Panel>
  );
}

/* ---------- the spreadsheet heatmap ---------- */

const TABLE_COLS: [string, string][] = [
  ["Submitted", C.sub],
  ["Recruiter", C.inv],
  ["Screening", C.inv],
  ["Second stage", C.inv],
  ["Rejections", C.rej],
];

/* Counts each event in the period it happened, as the spreadsheet did: a March
   rejection counts in March whenever you applied. */
function PeriodTable({ all, cutoff, today }: ChartProps) {
  const [grain, setGrain] = useState<Grain>("month");
  const wrap = useRef<HTMLDivElement>(null);

  const { ps, rows, max, total } = useMemo(() => {
    const ps = periods(cutoff, today, grain);
    const at = indexer(ps, grain);
    const rows = ps.map(() => [0, 0, 0, 0, 0]);
    const add = (d: Date | null, c: number) => {
      const i = at(d);
      if (i !== undefined) rows[i][c]++;
    };
    all.forEach((a) => {
      add(a.applied, 0);
      a.rounds.forEach((r) => add(r.held, FIRST_ROUNDS[r.type] ?? 3));
      add(a.rejected, 4);
    });
    const max = TABLE_COLS.map((_, c) => Math.max(1, ...rows.map((r) => r[c])));
    const total = TABLE_COLS.map((_, c) => rows.reduce((s, r) => s + r[c], 0));
    return { ps, rows, max, total };
  }, [all, cutoff, today, grain]);

  // Newest at the bottom, like the sheet; open there.
  useEffect(() => {
    if (wrap.current) wrap.current.scrollTop = wrap.current.scrollHeight;
  }, [ps]);

  const label = (d: Date) =>
    grain === "week" ? `${d.getDate()} ${MON[d.getMonth()]} ${String(d.getFullYear()).slice(2)}` : GRAIN.month.label(d);

  return (
    <Panel
      title={grain === "week" ? "Week by week" : "Month by month"}
      question="Each column is shaded against its own busiest period."
      controls={
        <Seg label="Group by" value={grain} onChange={setGrain} options={[["week", "Week"], ["month", "Month"]]} />
      }
    >
      <div ref={wrap} className="overflow-auto max-h-[560px]">
        <table className="w-full min-w-[480px] border-separate [border-spacing:2px] tabular-nums text-[13px]">
          <thead>
            <tr>
              {[grain === "week" ? "Week of" : "Month", ...TABLE_COLS.map(([h]) => h)].map((h, i) => (
                <th
                  key={h}
                  className={`sticky top-0 bg-panel text-[11px] font-medium text-subtle px-2 py-1 whitespace-nowrap ${
                    i ? "text-right" : "text-left"
                  }`}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={+ps[i]}>
                <td className="px-2 py-1 text-subtle whitespace-nowrap">
                  {label(ps[i])}
                  {i === rows.length - 1 && <span className="text-[11px] text-[#6b7388]"> · so far</span>}
                </td>
                {r.map((v, c) => (
                  <td
                    key={c}
                    title={v ? `${GRAIN[grain].label(ps[i])} · ${TABLE_COLS[c][0]}: ${v}` : undefined}
                    className={`px-2 py-1 text-right rounded ${v ? "" : "text-[#6b7388]"}`}
                    style={v ? { background: rgba(TABLE_COLS[c][1], 0.14 + (0.66 * v) / max[c]) } : undefined}
                  >
                    {v}
                  </td>
                ))}
              </tr>
            ))}
            <tr className="font-semibold">
              <td className="sticky bottom-0 bg-panel px-2 py-1 border-t border-border">Total</td>
              {total.map((v, c) => (
                <td key={c} className="sticky bottom-0 bg-panel px-2 py-1 text-right border-t border-border">
                  {v}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

/* ---------- what became of each period's applications ---------- */

function Outcomes({ apps, cutoff, today, quietDays, showTip, hideTip }: ChartProps) {
  const [grain, setGrain] = useState<Grain>("month");
  const [ref, W] = useWidth<HTMLDivElement>();
  const cats: [Cat, string, string][] = [
    ["offer", "Offer", C.offer],
    ["active", "Interviewing or on hold", C.inv],
    ["rej_int", "Rejected after interviews", C.rejInt],
    ["rej_cv", "Rejected without an interview", C.rej],
    ["dropped", "Withdrawn", C.drop],
    ["silent", `Silent ${quietDays}+ days`, C.silent],
    ["waiting", `Waiting, under ${quietDays} days`, C.wait],
  ];

  const { ps, by } = useMemo(() => {
    const ps = periods(cutoff, today, grain);
    const at = indexer(ps, grain);
    const by: App[][] = ps.map(() => []);
    apps.forEach((a) => {
      const i = at(a.anchor);
      if (i !== undefined) by[i].push(a);
    });
    return { ps, by };
  }, [apps, cutoff, today, grain]);

  // Settled = old enough that most replies are in; compare this year's with before.
  const settled = apps.filter((a) => daysBetween(a.anchor, today) > 90);
  const split = new Date(today.getFullYear(), 0, 1);
  const early = settled.filter((a) => a.anchor < split);
  const late = settled.filter((a) => a.anchor >= split);
  const rate = (xs: App[]) => pct(xs.filter((a) => a.rounds.length).length, xs.length);

  const rowH = grain === "quarter" ? 30 : 22;
  const L = 70, R = 34;
  const pw = Math.max(0, W - L - R);

  return (
    <Panel
      title="What became of each period's applications"
      question="Grouped by when you applied, sorted by how far each application got."
      controls={
        <Seg label="Group by" value={grain} onChange={setGrain} options={[["month", "Month"], ["quarter", "Quarter"]]} />
      }
    >
      <Legend items={cats.map(([, label, color]) => [color, label])} />
      <div ref={ref} className="w-full">
        {W > 0 && (
          <svg width={W} height={ps.length * rowH + 4} className="block overflow-visible">
            {ps.map((p, ri) => {
              const js = by[ri];
              const y = ri * rowH + 3;
              const h = rowH - 7;
              const segs = cats.map(([k, label, color]) => [label, color, js.filter((a) => a.cat === k).length] as const).filter(([, , v]) => v);
              let x = L;
              return (
                <g key={+p}>
                  <text x={0} y={y + h / 2 + 4} className="fill-subtle text-[11px]">
                    {GRAIN[grain].label(p)}
                  </text>
                  <text x={W} y={y + h / 2 + 4} textAnchor="end" className={AXIS_TEXT}>
                    {js.length}
                  </text>
                  {segs.map(([label, color, v], si) => {
                    const w = (v / js.length) * pw;
                    const rect = (
                      <rect
                        key={label}
                        x={x}
                        y={y}
                        width={Math.max(1, w - (si < segs.length - 1 ? 2 : 0))}
                        height={h}
                        rx={3}
                        fill={color}
                        onMouseMove={(e) =>
                          showTip(e, `Applied in ${GRAIN[grain].label(p)}`, [[color, label, `${v} of ${js.length} · ${pct(v, js.length)}%`]])
                        }
                        onMouseLeave={hideTip}
                      />
                    );
                    x += w;
                    return rect;
                  })}
                </g>
              );
            })}
          </svg>
        )}
      </div>
      <Readout>
        {early.length && late.length ? (
          <>
            Of applications old enough to have settled, <strong>{rate(late)}%</strong> sent this year
            reached an interview, against <strong>{rate(early)}%</strong> before.
          </>
        ) : (
          "Choose a longer range to compare earlier and recent applications."
        )}
      </Readout>
    </Panel>
  );
}

/* ---------- how long until they answer ---------- */

const MAX_DAYS = 112;

function Histogram({
  series,
  title,
  marks,
  bin,
  showTip,
  hideTip,
}: {
  series: [values: number[], color: string, label: string][];
  title: string;
  marks: [day: number | null, label: string, dashed?: boolean][];
  bin: number;
  showTip: ShowTip;
  hideTip: () => void;
}) {
  const [ref, W] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const nb = MAX_DAYS / bin;
  const counts = series.map(([vals]) => {
    const c = Array(nb).fill(0);
    vals.forEach((v) => c[Math.min(nb - 1, Math.floor(v / bin))]++);
    return c;
  });
  const totals = counts[0].map((_, i) => counts.reduce((s, c) => s + c[i], 0));
  const [ymax, step] = niceMax(Math.max(1, ...totals));
  const H = 130, L = 30, R = 8, T = 18, B = 20;
  const pw = Math.max(0, W - L - R);
  const bw = pw / nb;
  const gap = bw > 4 ? 2 : 0.5;
  const y = (v: number) => H - B - (v / ymax) * (H - T - B);
  const x = (d: number) => L + (d / bin) * bw;
  const ticks: number[] = [];
  for (let v = 0; v <= ymax; v += step) ticks.push(v);
  const binLabel = (i: number) =>
    i === nb - 1 ? `${i * bin}+ days` : bin === 1 ? `Day ${i}` : `${i * bin}–${i * bin + bin - 1} days`;

  return (
    <div ref={ref} className="w-full">
      {W > 0 && (
        <svg width={W} height={H} className="block overflow-visible">
          <text x={0} y={11} className="fill-subtle text-[11px]">
            {title}
          </text>
          {ticks.map((v) => (
            <g key={v}>
              <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke={v ? C.grid : C.axis} />
              <text x={L - 6} y={y(v) + 3.5} textAnchor="end" className={AXIS_TEXT}>
                {v}
              </text>
            </g>
          ))}
          {Array.from({ length: MAX_DAYS / 14 }, (_, k) => k * 14).map((d) => (
            <text key={d} x={x(d)} y={H - 5} textAnchor="middle" className={AXIS_TEXT}>
              {d}
            </text>
          ))}
          <text x={W - R} y={H - 5} textAnchor="end" className={AXIS_TEXT}>
            {MAX_DAYS - bin}+ days
          </text>
          {hover !== null && (
            <rect x={L + hover * bw} y={T} width={Math.max(bw, 2)} height={H - T - B} fill={C.text} opacity={0.07} />
          )}
          {counts[0].map((_, i) => {
            let base = 0;
            return (
              <g key={i}>
                {counts.map((c, si) => {
                  if (!c[i]) return null;
                  const top = base + c[i];
                  const isTop = counts.slice(si + 1).every((cc) => !cc[i]);
                  const h = y(base) - y(top) - (base ? 2 : 0);
                  const bx = L + i * bw + gap / 2;
                  base = top;
                  return isTop ? (
                    <path key={si} d={barPath(bx, y(top), bw - gap, h)} fill={series[si][1]} />
                  ) : (
                    <rect key={si} x={bx} y={y(top)} width={Math.max(0, bw - gap)} height={Math.max(0, h)} fill={series[si][1]} />
                  );
                })}
              </g>
            );
          })}
          {marks.map(([d, label, dashed]) =>
            d === null ? null : (
              <g key={label}>
                <line
                  x1={x(d)}
                  x2={x(d)}
                  y1={T - 4}
                  y2={H - B}
                  stroke={dashed ? "#8a93a8" : C.text}
                  strokeDasharray={dashed ? "3 3" : undefined}
                  strokeWidth={1.5}
                />
                <text x={x(d) + 4} y={T + 4} className={`text-[11px] ${dashed ? "fill-subtle" : "fill-text"}`}>
                  {label}
                </text>
              </g>
            )
          )}
          <rect
            x={L}
            y={T}
            width={pw}
            height={H - T - B}
            fill="transparent"
            onMouseMove={(e) => {
              const i = Math.max(0, Math.min(nb - 1, Math.floor((e.nativeEvent.offsetX - L) / bw)));
              setHover(i);
              showTip(e, binLabel(i), series.map(([, color, label], si) => [color, label, counts[si][i]]));
            }}
            onMouseLeave={() => {
              setHover(null);
              hideTip();
            }}
          />
        </svg>
      )}
    </div>
  );
}

function Delays({ apps, quietDays, showTip, hideTip }: ChartProps) {
  const [grain, setGrain] = useState<"day" | "week">("week");
  const sent = apps.filter((a) => a.applied);
  const after = (d: Date | null, a: App) => (d ? daysBetween(a.applied!, d) : -1);
  const inv = sent.map((a) => after(a.firstInvite, a)).filter((v) => v >= 0);
  const rejCv = sent.filter((a) => !a.rounds.length).map((a) => after(a.rejected, a)).filter((v) => v >= 0);
  const rejInt = sent.filter((a) => a.rounds.length).map((a) => after(a.rejected, a)).filter((v) => v >= 0);
  const mInv = median(inv);
  const mRej = median(rejCv);
  const bin = grain === "day" ? 1 : 7;
  const quiet: [number, string, boolean] = [quietDays, `${quietDays} d`, true];

  return (
    <Panel
      title="How long until they answer"
      question="Days from submission to the first reply of each kind."
      controls={
        <Seg label="Bar width" value={grain} onChange={setGrain} options={[["day", "Day"], ["week", "Week"]]} />
      }
    >
      <Legend
        items={[
          [C.inv, "Invitation or recruiter contact"],
          [C.rej, "Rejected without an interview"],
          [C.rejInt, "Rejected after interviews"],
        ]}
      />
      <Histogram
        series={[[inv, C.inv, "Invitations"]]}
        title={`Until the first invitation or contact · ${inv.length}`}
        marks={[[mInv, `median ${mInv} d`], quiet]}
        bin={bin}
        showTip={showTip}
        hideTip={hideTip}
      />
      <Histogram
        series={[
          [rejCv, C.rej, "Without an interview"],
          [rejInt, C.rejInt, "After interviews"],
        ]}
        title={`Until a rejection · ${rejCv.length + rejInt.length}`}
        marks={[[mRej, `median ${mRej} d`], quiet]}
        bin={bin}
        showTip={showTip}
        hideTip={hideTip}
      />
      {mInv !== null && mRej !== null && (
        <Readout>
          Half of all invitations came within <strong>{mInv} days</strong>,{" "}
          {pct(inv.filter((v) => v <= 21).length, inv.length)}% within three weeks. Rejections without an
          interview took a median <strong>{mRej} days</strong>.
        </Readout>
      )}
    </Panel>
  );
}

/* ---------- still worth waiting? ---------- */

const SETTLED_DAYS = 120;
const WAIT_DAYS = 90;

function Waiting({ apps, today, quietDays, showTip, hideTip }: ChartProps) {
  const [ref, W] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);

  /* Only applications old enough that a late reply would have arrived by now,
     or the youngest ones would drag every rate down. */
  const pts = useMemo(() => {
    const pool = apps.filter((a) => a.applied && daysBetween(a.applied, today) >= SETTLED_DAYS);
    return Array.from({ length: WAIT_DAYS + 1 }, (_, n) => {
      const still = pool.filter((a) => !a.firstReply || daysBetween(a.applied!, a.firstReply) > n);
      const any = still.filter((a) => a.firstReply).length;
      const inv = still.filter((a) => a.firstInvite && daysBetween(a.applied!, a.firstInvite) > n).length;
      return { n, pool: still.length, any: still.length ? (100 * any) / still.length : 0, inv: still.length ? (100 * inv) / still.length : 0 };
    });
  }, [apps, today]);

  const H = 200, L = 34, R = 12, T = 10, B = 22;
  const pw = Math.max(0, W - L - R);
  const x = (n: number) => L + (n / WAIT_DAYS) * pw;
  const y = (v: number) => H - B - (v / 100) * (H - T - B);
  const mark = Math.min(quietDays, WAIT_DAYS);
  const enough = pts[0].pool >= 20;
  const at3w = pts[21];
  const atQ = pts[mark];

  return (
    <Panel
      title="Still worth waiting?"
      question="Of the applications that had heard nothing after this many days, how many heard something later."
    >
      <Legend
        items={[
          [C.text, "Any reply later", "line"],
          [C.inv, "An invitation later", "line"],
        ]}
      />
      <div ref={ref} className="w-full">
        {W > 0 && !enough && (
          <p className="text-sm text-subtle">Needs applications at least {SETTLED_DAYS} days old. Choose a longer range.</p>
        )}
        {W > 0 && enough && (
          <svg width={W} height={H} className="block overflow-visible">
            {[0, 25, 50, 75, 100].map((v) => (
              <g key={v}>
                <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke={v ? C.grid : C.axis} />
                <text x={L - 6} y={y(v) + 3.5} textAnchor="end" className={AXIS_TEXT}>
                  {v}%
                </text>
              </g>
            ))}
            {[0, 15, 30, 45, 60, 75, 90].map((n) => (
              <text key={n} x={x(n)} y={H - 5} textAnchor="middle" className={AXIS_TEXT}>
                {n ? `${n} d` : "0"}
              </text>
            ))}
            <line x1={x(mark)} x2={x(mark)} y1={T} y2={H - B} stroke="#8a93a8" strokeDasharray="3 3" />
            <text x={x(mark) + 4} y={T + 10} className="fill-subtle text-[11px]">
              silent after {quietDays} d
            </text>
            <path d={pts.map((p, i) => `${i ? "L" : "M"}${x(p.n)},${y(p.any)}`).join("")} fill="none" stroke={C.text} strokeWidth={2} />
            <path d={pts.map((p, i) => `${i ? "L" : "M"}${x(p.n)},${y(p.inv)}`).join("")} fill="none" stroke={C.inv} strokeWidth={2} />
            {[
              [atQ.any, C.text],
              [atQ.inv, C.inv],
            ].map(([v, color]) => (
              <circle key={color as string} cx={x(mark)} cy={y(v as number)} r={4} fill={color as string} stroke={C.panel} strokeWidth={2} />
            ))}
            {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={T} y2={H - B} stroke="#8a93a8" />}
            <rect
              x={L}
              y={T}
              width={pw}
              height={H - T - B}
              fill="transparent"
              onMouseMove={(e) => {
                const n = Math.max(0, Math.min(WAIT_DAYS, Math.round(((e.nativeEvent.offsetX - L) / pw) * WAIT_DAYS)));
                const p = pts[n];
                setHover(n);
                showTip(e, `After ${n} days of silence`, [
                  [C.text, "Heard something later", `${Math.round(p.any)}%`],
                  [C.inv, "Invited later", `${Math.round(p.inv)}%`],
                  [C.wait, "Still silent then", `${p.pool} applications`],
                ]);
              }}
              onMouseLeave={() => {
                setHover(null);
                hideTip();
              }}
            />
          </svg>
        )}
      </div>
      {enough && (
        <Readout>
          After three weeks of silence, <strong>{Math.round(at3w.any)}%</strong> still heard back and{" "}
          <strong>{Math.round(at3w.inv)}%</strong> were invited. After {quietDays} days:{" "}
          <strong>{Math.round(atQ.any)}%</strong> and <strong>{Math.round(atQ.inv)}%</strong>. Counts only
          applications at least {SETTLED_DAYS} days old, so late replies have had time to arrive.
        </Readout>
      )}
    </Panel>
  );
}

/* ---------- across the week ---------- */

function WeekdayBars({
  dates,
  color,
  under,
  showTip,
  hideTip,
}: {
  dates: Date[];
  color: string;
  under?: { n: number; replied: number }[];
  showTip: ShowTip;
  hideTip: () => void;
}) {
  const [ref, W] = useWidth<HTMLDivElement>();
  const c = Array(7).fill(0);
  dates.forEach((d) => c[wdIdx(d)]++);
  const H = under ? 150 : 124, L = 4, R = 4, T = 14, B = under ? 48 : 20;
  const bw = Math.max(0, W - L - R) / 7;
  const max = Math.max(1, ...c);
  const y = (v: number) => T + (H - T - B) * (1 - v / max);
  return (
    <div ref={ref} className="w-full">
      {W > 0 && (
        <svg width={W} height={H} className="block overflow-visible">
          <line x1={L} x2={W - R} y1={H - B} y2={H - B} stroke={C.axis} />
          {c.map((v, i) => {
            const cx = L + i * bw + bw / 2;
            return (
              <g key={i}>
                <path d={barPath(L + i * bw + 3, y(v), bw - 6, H - B - y(v))} fill={color} />
                <text x={cx} y={y(v) - 4} textAnchor="middle" className="fill-subtle text-[11px] tabular-nums">
                  {v}
                </text>
                <text x={cx} y={H - B + 14} textAnchor="middle" className={AXIS_TEXT}>
                  {WD[i]}
                </text>
                {under && (
                  <>
                    <text x={cx} y={H - B + 30} textAnchor="middle" className="fill-text text-[11px] tabular-nums">
                      {under[i].n ? `${pct(under[i].replied, under[i].n)}%` : "–"}
                    </text>
                    <text x={cx} y={H - B + 43} textAnchor="middle" className={AXIS_TEXT}>
                      n={under[i].n}
                    </text>
                  </>
                )}
                <rect
                  x={L + i * bw}
                  y={T}
                  width={bw}
                  height={H - T - B}
                  fill="transparent"
                  onMouseMove={(e) =>
                    showTip(e, WD[i], [
                      [color, "Count", v],
                      ...(under ? [[C.text, "Heard back", `${under[i].replied} of ${under[i].n}`] as TipRow] : []),
                    ])
                  }
                  onMouseLeave={hideTip}
                />
              </g>
            );
          })}
        </svg>
      )}
    </div>
  );
}

function Weekdays({ apps, today, showTip, hideTip }: ChartProps) {
  const sent = apps.filter((a) => a.applied);
  const settled = sent.filter((a) => daysBetween(a.applied!, today) > 60);
  const under = WD.map((_, i) => {
    const xs = settled.filter((a) => wdIdx(a.applied!) === i);
    return { n: xs.length, replied: xs.filter((a) => a.firstReply).length };
  });
  const rejections = apps.filter((a) => a.rejected).map((a) => a.rejected!);
  const rc = Array(7).fill(0);
  rejections.forEach((d) => rc[wdIdx(d)]++);
  const rates = under.filter((u) => u.n >= 10).map((u) => pct(u.replied, u.n));
  const spread = rates.length > 1 ? Math.max(...rates) - Math.min(...rates) : 0;

  const small = (label: string, color: string, dates: Date[], withRates = false) => (
    <div className="min-w-0">
      <h3 className="text-xs text-subtle mb-1.5 flex items-center gap-1.5">
        <i className="inline-block w-2.5 h-2.5 rounded-sm" style={{ background: color }} />
        {label}
      </h3>
      <WeekdayBars dates={dates} color={color} under={withRates ? under : undefined} showTip={showTip} hideTip={hideTip} />
    </div>
  );

  return (
    <Panel title="Across the week" question="When you apply, and when employers write back.">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {small("You submit", C.sub, sent.map((a) => a.applied!), true)}
        {small("Invitations arrive", C.inv, apps.filter((a) => a.firstInvite).map((a) => a.firstInvite!))}
        {small("Rejections arrive", C.rej, rejections)}
      </div>
      {rejections.length > 0 && (
        <Readout>
          Rejections arrive most often on <strong>{WD[rc.indexOf(Math.max(...rc))]}</strong>. The percentages
          under &ldquo;You submit&rdquo; are the share that heard back, for applications older than 60 days
          {rates.length > 1
            ? spread < 15
              ? `. They range from ${Math.min(...rates)}% to ${Math.max(...rates)}%, a spread this sample size can produce by chance.`
              : `. They range from ${Math.min(...rates)}% to ${Math.max(...rates)}%; check each day's n before reading much into it.`
            : "."}
        </Readout>
      )}
    </Panel>
  );
}
