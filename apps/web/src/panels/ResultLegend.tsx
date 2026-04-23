import { useProject } from "@/store/useProject";
import { Eye, EyeOff, Grid3x3, Download, FileText } from "lucide-react";

export function ResultLegend() {
  const result = useProject((s) => s.result);
  const project = useProject((s) => s.project);
  const showResult = useProject((s) => s.showResult);
  const setShowResult = useProject((s) => s.setShowResult);
  const dispScale = useProject((s) => s.dispScale);
  const setDispScale = useProject((s) => s.setDispScale);
  const showMeshEdges = useProject((s) => s.showMeshEdges);
  const setShowMeshEdges = useProject((s) => s.setShowMeshEdges);

  const job = useProject((s) => s.job);

  if (!result) return null;

  const { vonMisesMin, vonMisesMax, dispMax } = result.summary;
  const jobId = result.jobId || job?.id;

  // auto-scale baseline (bbox diag * 5%)
  let auto = 1;
  if (project && dispMax > 1e-12) {
    const sx = project.bboxMax[0] - project.bboxMin[0];
    const sy = project.bboxMax[1] - project.bboxMin[1];
    const sz = project.bboxMax[2] - project.bboxMin[2];
    const diag = Math.hypot(sx, sy, sz);
    auto = (diag * 0.05) / dispMax;
  }

  const mult = auto > 0 ? dispScale / auto : 1;

  return (
    <div className="pointer-events-auto flex flex-col items-end gap-2">
      <div className="panel flex items-center gap-2 rounded-full px-3 py-1.5 text-xs">
        <button
          className="rounded p-0.5 text-slate-300 transition hover:text-cyan-300"
          onClick={() => setShowResult(!showResult)}
          title={showResult ? "元モデルを表示" : "結果を表示"}
        >
          {showResult ? <Eye className="h-3.5 w-3.5" /> : <EyeOff className="h-3.5 w-3.5" />}
        </button>
        <button
          className={`rounded p-0.5 transition ${
            showMeshEdges ? "text-cyan-300" : "text-slate-500 hover:text-slate-300"
          }`}
          onClick={() => setShowMeshEdges(!showMeshEdges)}
          title={showMeshEdges ? "メッシュを非表示" : "メッシュを表示"}
          disabled={!showResult}
        >
          <Grid3x3 className="h-3.5 w-3.5" />
        </button>
        <span className="text-slate-400">変形倍率</span>
        <input
          type="range"
          min={0}
          max={4}
          step={0.05}
          value={Math.log10(Math.max(mult, 0.01)) + 2}   // 0..4 maps 0.01x .. 100x
          onChange={(e) => {
            const t = Number(e.target.value); // 0..4
            const m = Math.pow(10, t - 2);
            setDispScale(auto * m);
          }}
          className="w-28 accent-cyan-400"
          disabled={!showResult}
        />
        <span className="w-12 text-right font-mono text-slate-200">
          {mult < 10 ? mult.toFixed(2) : mult.toFixed(0)}×
        </span>
      </div>

      <div className="panel w-56 rounded-2xl p-3 text-xs">
        <div className="mb-2 flex items-center justify-between">
          <span className="font-semibold uppercase tracking-wider text-slate-300">
            von Mises
          </span>
          <span className="font-mono text-[10px] text-slate-500">MPa</span>
        </div>
        <div
          className="h-3 w-full rounded-full"
          style={{ background: VIRIDIS_CSS_GRADIENT }}
        />
        <div className="mt-1 flex justify-between font-mono text-[11px] text-slate-400">
          <span>{fmt(vonMisesMin)}</span>
          <span>{fmt((vonMisesMin + vonMisesMax) / 2)}</span>
          <span>{fmt(vonMisesMax)}</span>
        </div>
        <div className="mt-2 flex items-center justify-between text-[11px] text-slate-400">
          <span>|U|<sub>max</sub></span>
          <span className="font-mono text-slate-200">{dispMax.toExponential(2)} mm</span>
        </div>

        {jobId && (
          <div className="mt-3 flex gap-1.5 border-t border-stroke/60 pt-2">
            <a
              href={`/api/jobs/${jobId}/csv`}
              download={`${jobId}.csv`}
              className="flex flex-1 items-center justify-center gap-1 rounded-lg border border-stroke bg-white/5 px-2 py-1 text-[11px] text-slate-200 transition hover:bg-white/10"
              title="ノード座標+応力をCSVでダウンロード"
            >
              <Download className="h-3 w-3" /> CSV
            </a>
            <a
              href={`/api/jobs/${jobId}/inp`}
              download={`${jobId}.inp`}
              className="flex flex-1 items-center justify-center gap-1 rounded-lg border border-stroke bg-white/5 px-2 py-1 text-[11px] text-slate-200 transition hover:bg-white/10"
              title="CalculiX 入力ファイル(.inp)をダウンロード"
            >
              <FileText className="h-3 w-3" /> INP
            </a>
          </div>
        )}
      </div>
    </div>
  );
}

function fmt(v: number): string {
  if (!Number.isFinite(v)) return "-";
  const a = Math.abs(v);
  if (a === 0) return "0";
  if (a < 0.01 || a >= 1000) return v.toExponential(2);
  return v.toFixed(2);
}

// Matplotlib "jet" rainbow sampled at 11 stops (blue -> cyan -> green -> yellow -> red)
const VIRIDIS_CSS_GRADIENT =
  "linear-gradient(to right," +
  [
    "#00007f", "#0000ff", "#0080ff", "#00ffff", "#80ff80",
    "#ffff00", "#ffc000", "#ff8000", "#ff4000", "#ff0000", "#7f0000",
  ].join(",") +
  ")";
