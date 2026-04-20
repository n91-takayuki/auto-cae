import { useEffect, useState } from "react";
import { AlertCircle, X } from "lucide-react";
import { useProject } from "@/store/useProject";

type Toast = { id: number; msg: string; ts: number };

export function Toasts() {
  const logs = useProject((s) => s.logs);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [seen, setSeen] = useState(0);

  // On new error log entries, push toasts.
  useEffect(() => {
    const errors = logs
      .map((l, i) => ({ l, i }))
      .filter(({ l }) => l.level === "error");
    if (errors.length === 0) return;
    const latestIdx = errors[errors.length - 1].i;
    if (latestIdx < seen) return;
    const newOnes = errors
      .filter(({ i }) => i >= seen)
      .map(({ l }) => ({ id: Math.random() * 1e9 | 0, msg: l.msg, ts: l.ts }));
    if (newOnes.length === 0) return;
    setSeen(latestIdx + 1);
    setToasts((t) => [...t, ...newOnes]);
    // auto-dismiss
    for (const nt of newOnes) {
      setTimeout(
        () => setToasts((t) => t.filter((x) => x.id !== nt.id)),
        6000
      );
    }
  }, [logs, seen]);

  if (toasts.length === 0) return null;

  return (
    <div className="pointer-events-none fixed right-4 top-20 z-50 flex flex-col gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          className="pointer-events-auto flex max-w-sm items-start gap-2 rounded-xl border border-rose-400/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-100 shadow-glass backdrop-blur-xl"
          role="alert"
        >
          <AlertCircle className="mt-0.5 h-4 w-4 flex-none text-rose-300" />
          <div className="flex-1 break-words">{t.msg}</div>
          <button
            onClick={() => setToasts((ts) => ts.filter((x) => x.id !== t.id))}
            className="rounded p-0.5 text-rose-200 transition hover:bg-white/10"
            title="閉じる"
          >
            <X className="h-3 w-3" />
          </button>
        </div>
      ))}
    </div>
  );
}
