import { useRef } from "react";
import { Upload, Play, RotateCcw, Settings2, Loader2 } from "lucide-react";
import { useProject } from "@/store/useProject";

const PHASE_LABEL: Record<string, string> = {
  queued: "待機中",
  meshing: "メッシュ生成",
  solving: "解析中",
  postprocess: "後処理",
  done: "完了",
  failed: "失敗",
  cancelled: "キャンセル",
};

export function Toolbar() {
  const inputRef = useRef<HTMLInputElement>(null);
  const uploadStep = useProject((s) => s.uploadStep);
  const reset = useProject((s) => s.reset);
  const loading = useProject((s) => s.loading);
  const project = useProject((s) => s.project);
  const bcs = useProject((s) => s.bcs);
  const job = useProject((s) => s.job);
  const runAnalysis = useProject((s) => s.runAnalysis);

  const running =
    !!job && !["done", "failed", "cancelled"].includes(job.status);
  const hasFix = bcs.some((b) => b.type === "fix");
  const hasLoad = bcs.some((b) => b.type === "load");
  const canRun = !!project && bcs.length > 0 && hasFix && hasLoad && !running;

  const onPick = () => inputRef.current?.click();

  const onChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    await uploadStep(file);
    if (inputRef.current) inputRef.current.value = "";
  };

  return (
    <div className="pointer-events-auto flex items-center gap-2 rounded-full border border-stroke bg-white/5 px-2 py-1.5 backdrop-blur-xl shadow-glass">
      <input
        ref={inputRef}
        type="file"
        accept=".step,.stp"
        onChange={onChange}
        className="hidden"
      />
      <button className="btn" onClick={onPick} disabled={loading}>
        {loading ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <Upload className="h-4 w-4" />
        )}
        STEP 読込
      </button>
      <button className="btn" onClick={reset} disabled={!project}>
        <RotateCcw className="h-4 w-4" /> リセット
      </button>
      <button className="btn" disabled>
        <Settings2 className="h-4 w-4" /> 設定
      </button>
      <div className="mx-1 h-5 w-px bg-stroke" />
      <button
        className="btn-accent"
        disabled={!canRun}
        onClick={() => runAnalysis()}
        title={
          !project
            ? "STEP を読み込んでください"
            : bcs.length === 0
            ? "境界条件を追加してください"
            : !hasFix
            ? "少なくとも1つの拘束が必要です"
            : !hasLoad
            ? "少なくとも1つの荷重が必要です(無いと応力は常に0)"
            : ""
        }
      >
        {running ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <Play className="h-4 w-4" />
        )}
        解析実行
      </button>

      {job && (
        <div className="ml-2 flex min-w-[180px] items-center gap-2">
          <div className="flex-1">
            <div className="h-1.5 overflow-hidden rounded-full bg-white/10">
              <div
                className="h-full bg-gradient-to-r from-cyan-400 to-violet-500 transition-[width] duration-200"
                style={{ width: `${Math.round((job.progress ?? 0) * 100)}%` }}
              />
            </div>
            <div className="mt-0.5 flex justify-between text-[10px] text-slate-400">
              <span>{PHASE_LABEL[job.status] ?? job.status}</span>
              <span className="font-mono">
                {Math.round((job.progress ?? 0) * 100)}%
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
