import { useEffect } from "react";
import {
  Box, Anchor, ArrowDownToLine, Layers, ChevronRight, FileCode, X,
  History, CheckCircle2, AlertCircle, Loader2,
} from "lucide-react";
import type { JobDTO } from "@/api/client";
import { api } from "@/api/client";
import { useProject, type BC } from "@/store/useProject";

export function LeftTree() {
  const project = useProject((s) => s.project);
  const faceCount = project?.faceCount ?? 0;
  const bcs = useProject((s) => s.bcs);
  const removeBc = useProject((s) => s.removeBc);

  const fixes = bcs.filter((b) => b.type === "fix");
  const loads = bcs.filter((b) => b.type === "load");

  return (
    <div className="panel flex h-full flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b border-stroke px-3 py-2">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-300">
          <Layers className="h-3.5 w-3.5" /> プロジェクト
        </div>
        <span className="chip">{project ? project.id.slice(0, 6) : "empty"}</span>
      </div>

      <div className="flex-1 overflow-y-auto p-2 text-sm">
        {project && (
          <div className="mb-2 flex items-center gap-2 rounded-lg bg-white/5 px-2 py-1.5">
            <FileCode className="h-4 w-4 text-slate-300" />
            <span className="flex-1 truncate text-slate-200">{project.filename}</span>
            <span className="font-mono text-[11px] text-slate-500">
              {project.triCount.toLocaleString()} tri
            </span>
          </div>
        )}
        <TreeRow icon={<Box className="h-4 w-4 text-cyan-300" />} label="Faces" count={faceCount} />

        <TreeRow
          icon={<Anchor className="h-4 w-4 text-emerald-300" />}
          label="拘束"
          count={fixes.length}
        />
        <div className="ml-5 space-y-1">
          {fixes.map((bc) => (
            <BCRow key={bc.id} bc={bc} onRemove={() => removeBc(bc.id)} />
          ))}
        </div>

        <TreeRow
          icon={<ArrowDownToLine className="h-4 w-4 text-violet-300" />}
          label="荷重"
          count={loads.length}
        />
        <div className="ml-5 space-y-1">
          {loads.map((bc) => (
            <BCRow key={bc.id} bc={bc} onRemove={() => removeBc(bc.id)} />
          ))}
        </div>

        <JobHistory />
      </div>

      <div className="border-t border-stroke p-2 text-[11px] text-slate-500">
        {project
          ? `bbox: ${fmt(project.bboxMin)} → ${fmt(project.bboxMax)}`
          : "STEP を読み込んでください"}
      </div>
    </div>
  );
}

function fmt(v: readonly [number, number, number]) {
  return `[${v.map((x) => x.toFixed(1)).join(", ")}]`;
}

function TreeRow({
  icon,
  label,
  count,
}: {
  icon: React.ReactNode;
  label: string;
  count: number;
}) {
  return (
    <div className="flex cursor-default items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-white/5">
      <ChevronRight className="h-3.5 w-3.5 text-slate-500" />
      {icon}
      <span className="flex-1 text-slate-200">{label}</span>
      <span className="font-mono text-[11px] text-slate-500">{count}</span>
    </div>
  );
}

function BCRow({ bc, onRemove }: { bc: BC; onRemove: () => void }) {
  const label = bc.type === "fix" ? fixLabel(bc.dofs) : loadLabel(bc);
  const tint =
    bc.type === "fix"
      ? "border-emerald-400/20 bg-emerald-400/5"
      : "border-violet-400/20 bg-violet-400/5";
  return (
    <div
      className={`group flex items-center gap-2 rounded-lg border ${tint} px-2 py-1 text-[11px]`}
    >
      <span className="truncate text-slate-300">{label}</span>
      <span className="ml-auto font-mono text-slate-500">{bc.faceIds.length}面</span>
      <button
        className="rounded p-0.5 text-slate-500 opacity-0 transition hover:bg-white/10 hover:text-rose-300 group-hover:opacity-100"
        onClick={onRemove}
        title="削除"
      >
        <X className="h-3 w-3" />
      </button>
    </div>
  );
}

function fixLabel(d: { x: boolean; y: boolean; z: boolean }) {
  const on = [d.x && "X", d.y && "Y", d.z && "Z"].filter(Boolean).join("");
  return on === "XYZ" ? "固定" : `${on}方向拘束`;
}

function loadLabel(bc: Extract<BC, { type: "load" }>) {
  const unit = bc.kind === "force" ? "N" : "MPa";
  const dir = bc.direction === "normal" ? "法線" : "XYZ指定";
  return `${bc.magnitude} ${unit} · ${dir}`;
}

function JobHistory() {
  const project = useProject((s) => s.project);
  const history = useProject((s) => s.history);
  const currentJob = useProject((s) => s.job);
  const loadJobResult = useProject((s) => s.loadJobResult);

  // On project change / mount: fetch server-side history for this project
  useEffect(() => {
    if (!project) return;
    let cancelled = false;
    api
      .listJobs(project.id)
      .then((list) => {
        if (cancelled) return;
        // merge: keep any WS-updated entries in place
        useProject.setState((s) => {
          const byId = new Map<string, JobDTO>();
          for (const j of list) byId.set(j.id, j);
          for (const j of s.history) byId.set(j.id, j); // prefer in-store (fresher)
          return { history: Array.from(byId.values()).sort((a, b) => (a.id < b.id ? 1 : -1)) };
        });
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [project?.id]);

  if (!project) return null;

  return (
    <div className="mt-4">
      <TreeRow
        icon={<History className="h-4 w-4 text-amber-300" />}
        label="ジョブ履歴"
        count={history.length}
      />
      <div className="ml-5 space-y-1">
        {history.length === 0 && (
          <div className="rounded-lg border border-dashed border-stroke bg-white/[0.02] p-2 text-center text-[11px] text-slate-500">
            まだ解析履歴がありません
          </div>
        )}
        {history.map((j) => (
          <JobRow
            key={j.id}
            job={j}
            active={currentJob?.id === j.id}
            onClick={() => j.status === "done" && loadJobResult(j.id)}
          />
        ))}
      </div>
    </div>
  );
}

function JobRow({
  job, active, onClick,
}: {
  job: JobDTO;
  active: boolean;
  onClick: () => void;
}) {
  const running = !["done", "failed", "cancelled"].includes(job.status);
  const canClick = job.status === "done";
  return (
    <button
      disabled={!canClick}
      onClick={onClick}
      className={`flex w-full items-center gap-2 rounded-lg border px-2 py-1 text-left text-[11px] transition ${
        active
          ? "border-cyan-400/40 bg-cyan-400/5"
          : "border-stroke/60 bg-white/[0.02]"
      } ${canClick ? "hover:bg-white/5" : "cursor-not-allowed opacity-70"}`}
    >
      {running && <Loader2 className="h-3 w-3 animate-spin text-cyan-300" />}
      {job.status === "done" && <CheckCircle2 className="h-3 w-3 text-emerald-300" />}
      {job.status === "failed" && <AlertCircle className="h-3 w-3 text-rose-300" />}
      {job.status === "cancelled" && <X className="h-3 w-3 text-slate-400" />}
      <span className="flex-1 truncate font-mono text-slate-300">{job.id.slice(0, 8)}</span>
      <span className="font-mono text-slate-500">
        {running ? `${Math.round(job.progress * 100)}%` : job.status}
      </span>
    </button>
  );
}
