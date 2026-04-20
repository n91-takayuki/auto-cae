import { useEffect, useRef } from "react";
import { Terminal } from "lucide-react";
import { useProject } from "@/store/useProject";

export function BottomLog() {
  const logs = useProject((s) => s.logs);
  const loading = useProject((s) => s.loading);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scroller.current?.scrollTo({ left: 1e9, behavior: "smooth" });
  }, [logs.length]);

  const last = logs[logs.length - 1];
  const statusColor = loading ? "bg-cyan-400" : last?.level === "error" ? "bg-rose-400" : "bg-emerald-400";

  return (
    <div className="panel flex h-full items-center gap-3 px-4">
      <Terminal className="h-4 w-4 text-slate-400" />
      <div
        ref={scroller}
        className="flex-1 overflow-x-auto whitespace-nowrap font-mono text-[12px] text-slate-400"
      >
        {logs.length === 0 ? (
          <>
            <span className="text-slate-500">[ready]</span>{" "}
            STEP を読み込んで解析を開始してください
          </>
        ) : (
          logs.slice(-8).map((l, i) => (
            <span key={i} className="mr-4">
              <span className="text-slate-600">
                [{new Date(l.ts).toLocaleTimeString()}]
              </span>{" "}
              <span className={l.level === "error" ? "text-rose-300" : "text-slate-300"}>
                {l.msg}
              </span>
            </span>
          ))
        )}
      </div>
      <div className="flex items-center gap-2">
        <span className="chip">
          <span className={`h-1.5 w-1.5 rounded-full ${statusColor}`} />
          {loading ? "busy" : "idle"}
        </span>
      </div>
    </div>
  );
}
