import { useState } from "react";
import { Anchor, ArrowDownToLine, SlidersHorizontal, MousePointerClick } from "lucide-react";
import { useProject } from "@/store/useProject";
import { MATERIALS, type MaterialSpec } from "@/data/materials";

export function RightProps() {
  const selectedCount = useProject((s) => s.selectedFaceIds.size);
  const project = useProject((s) => s.project);

  return (
    <div className="panel flex h-full flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b border-stroke px-3 py-2">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-slate-300">
          <SlidersHorizontal className="h-3.5 w-3.5" /> プロパティ
        </div>
        {selectedCount > 0 && (
          <span className="chip text-cyan-300">
            <MousePointerClick className="h-3 w-3" />
            {selectedCount} 面
          </span>
        )}
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto p-3 text-sm">
        <Section title="選択">
          {!project ? (
            <Empty msg="STEP を読み込んでください" />
          ) : selectedCount === 0 ? (
            <Empty msg="3Dビューで面をクリック (Shift/Ctrl で追加選択)" />
          ) : (
            <BCCreator />
          )}
        </Section>

        <Section title="材料">
          <MaterialEditor />
        </Section>

        <Section title="解析設定">
          <Row label="種別" value="線形静解析" />
          <Row label="要素" value="Tet10" mono />
          <MeshSizeField />
        </Section>
      </div>
    </div>
  );
}

function BCCreator() {
  const addFix = useProject((s) => s.addFix);
  const addLoad = useProject((s) => s.addLoad);
  const [mode, setMode] = useState<"fix" | "load" | null>(null);

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-2">
        <button
          className={`btn ${mode === "fix" ? "ring-1 ring-emerald-400/60" : ""}`}
          onClick={() => setMode(mode === "fix" ? null : "fix")}
        >
          <Anchor className="h-4 w-4 text-emerald-300" /> 拘束
        </button>
        <button
          className={`btn ${mode === "load" ? "ring-1 ring-violet-400/60" : ""}`}
          onClick={() => setMode(mode === "load" ? null : "load")}
        >
          <ArrowDownToLine className="h-4 w-4 text-violet-300" /> 荷重
        </button>
      </div>
      {mode === "fix" && <FixForm onSubmit={addFix} />}
      {mode === "load" && <LoadForm onSubmit={addLoad} />}
    </div>
  );
}

function FixForm({ onSubmit }: { onSubmit: (dofs: { x: boolean; y: boolean; z: boolean }) => void }) {
  const [x, setX] = useState(true);
  const [y, setY] = useState(true);
  const [z, setZ] = useState(true);
  return (
    <div className="space-y-2 rounded-xl border border-stroke/60 bg-white/[0.02] p-3">
      <div className="text-[11px] uppercase tracking-wider text-slate-400">拘束する方向</div>
      <div className="flex gap-1">
        <DofChip label="X" value={x} onChange={setX} />
        <DofChip label="Y" value={y} onChange={setY} />
        <DofChip label="Z" value={z} onChange={setZ} />
      </div>
      <button
        className="btn-accent w-full"
        disabled={!x && !y && !z}
        onClick={() => onSubmit({ x, y, z })}
      >
        追加
      </button>
    </div>
  );
}

function LoadForm({
  onSubmit,
}: {
  onSubmit: (v: {
    magnitude: number;
    kind: "force" | "pressure";
    direction: "normal" | { x: number; y: number; z: number };
  }) => void;
}) {
  const [kind, setKind] = useState<"force" | "pressure">("force");
  const [magnitude, setMagnitude] = useState("100");
  const [dirMode, setDirMode] = useState<"normal" | "xyz">("normal");
  const [dx, setDx] = useState("0");
  const [dy, setDy] = useState("0");
  const [dz, setDz] = useState("-1");

  const submit = () => {
    const m = Number(magnitude);
    if (!Number.isFinite(m) || m === 0) return;
    const direction =
      dirMode === "normal"
        ? "normal"
        : { x: Number(dx) || 0, y: Number(dy) || 0, z: Number(dz) || 0 };
    onSubmit({ magnitude: m, kind, direction });
  };

  return (
    <div className="space-y-2 rounded-xl border border-stroke/60 bg-white/[0.02] p-3">
      <div className="flex gap-1">
        <ToggleChip active={kind === "force"} onClick={() => setKind("force")}>
          合力 [N]
        </ToggleChip>
        <ToggleChip active={kind === "pressure"} onClick={() => setKind("pressure")}>
          圧力 [MPa]
        </ToggleChip>
      </div>
      <NumInput label="大きさ" value={magnitude} onChange={setMagnitude} />
      <div className="text-[11px] uppercase tracking-wider text-slate-400 pt-1">方向</div>
      <div className="flex gap-1">
        <ToggleChip active={dirMode === "normal"} onClick={() => setDirMode("normal")}>
          面法線
        </ToggleChip>
        <ToggleChip active={dirMode === "xyz"} onClick={() => setDirMode("xyz")}>
          XYZ
        </ToggleChip>
      </div>
      {dirMode === "xyz" && (
        <div className="grid grid-cols-3 gap-1">
          <NumInput label="X" value={dx} onChange={setDx} compact />
          <NumInput label="Y" value={dy} onChange={setDy} compact />
          <NumInput label="Z" value={dz} onChange={setDz} compact />
        </div>
      )}
      <button className="btn-accent w-full" onClick={submit}>
        追加
      </button>
    </div>
  );
}

function DofChip({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      onClick={() => onChange(!value)}
      className={`flex-1 rounded-lg border px-2 py-1 font-mono text-xs transition ${
        value
          ? "border-emerald-400/60 bg-emerald-400/10 text-emerald-200"
          : "border-stroke bg-white/[0.03] text-slate-500"
      }`}
    >
      {label}
    </button>
  );
}

function ToggleChip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex-1 rounded-lg border px-2 py-1 text-xs transition ${
        active
          ? "border-cyan-400/60 bg-cyan-400/10 text-cyan-200"
          : "border-stroke bg-white/[0.03] text-slate-400"
      }`}
    >
      {children}
    </button>
  );
}

function NumInput({
  label,
  value,
  onChange,
  compact = false,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  compact?: boolean;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className={`text-[10px] uppercase tracking-wider text-slate-500 ${compact ? "" : ""}`}>
        {label}
      </span>
      <input
        type="number"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-lg border border-stroke bg-black/30 px-2 py-1 font-mono text-sm text-slate-200 outline-none focus:border-cyan-400/60"
      />
    </label>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
        {title}
      </div>
      <div className="space-y-1.5">{children}</div>
    </div>
  );
}

function Empty({ msg }: { msg: string }) {
  return (
    <div className="rounded-xl border border-dashed border-stroke bg-white/[0.02] p-4 text-center text-[12px] text-slate-500">
      {msg}
    </div>
  );
}

function Row({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-stroke/60 bg-white/[0.02] px-2.5 py-1.5">
      <span className="text-[12px] text-slate-400">{label}</span>
      <span className={`text-[12px] text-slate-200 ${mono ? "font-mono" : ""}`}>{value}</span>
    </div>
  );
}

function MeshSizeField() {
  const factor = useProject((s) => s.meshSizeFactor);
  const setFactor = useProject((s) => s.setMeshSizeFactor);
  const project = useProject((s) => s.project);

  // Auto target = bbox diagonal / 20
  let approxMm: number | null = null;
  if (project) {
    const sx = project.bboxMax[0] - project.bboxMin[0];
    const sy = project.bboxMax[1] - project.bboxMin[1];
    const sz = project.bboxMax[2] - project.bboxMin[2];
    const diag = Math.hypot(sx, sy, sz);
    approxMm = (diag / 20) * factor;
  }

  return (
    <div className="rounded-lg border border-stroke/60 bg-white/[0.02] px-2.5 py-1.5">
      <div className="flex items-center justify-between">
        <span className="text-[12px] text-slate-400">メッシュサイズ</span>
        <span className="font-mono text-[12px] text-slate-200">
          {factor.toFixed(2)}×
          {approxMm !== null && (
            <span className="ml-1 text-slate-500">≈ {approxMm.toFixed(2)} mm</span>
          )}
        </span>
      </div>
      <input
        type="range"
        min={0.3}
        max={3.0}
        step={0.05}
        value={factor}
        onChange={(e) => setFactor(Number(e.target.value))}
        className="mt-1 w-full accent-cyan-400"
      />
      <div className="flex justify-between text-[9px] uppercase tracking-wider text-slate-500">
        <span>細かい</span>
        <span>標準</span>
        <span>粗い</span>
      </div>
    </div>
  );
}

function MaterialEditor() {
  const material = useProject((s) => s.material);
  const setMaterial = useProject((s) => s.setMaterial);
  const isCustom = material.key === "custom";

  const onPreset = (key: string) => {
    const preset = MATERIALS.find((m) => m.key === key);
    if (!preset) return;
    // "custom" preserves current numeric values but flips to editable
    if (key === "custom") {
      setMaterial({ ...material, key: "custom", name: "カスタム" });
    } else {
      setMaterial(preset);
    }
  };

  const patch = (p: Partial<MaterialSpec>) =>
    setMaterial({ ...material, ...p, key: "custom", name: "カスタム" });

  return (
    <div className="space-y-1.5">
      <label className="flex items-center justify-between gap-3 rounded-lg border border-stroke/60 bg-white/[0.02] px-2.5 py-1.5">
        <span className="text-[12px] text-slate-400">プリセット</span>
        <select
          value={material.key}
          onChange={(e) => onPreset(e.target.value)}
          className="flex-1 rounded-md border border-stroke/60 bg-black/30 px-1.5 py-0.5 text-[12px] text-slate-200 outline-none focus:border-cyan-400/60"
        >
          {MATERIALS.map((m) => (
            <option key={m.key} value={m.key}>{m.name}</option>
          ))}
        </select>
      </label>
      <MatField
        label="ヤング率"
        unit="MPa"
        value={material.young}
        editable={isCustom}
        onChange={(v) => patch({ young: v })}
      />
      <MatField
        label="ポアソン比"
        unit=""
        value={material.poisson}
        editable={isCustom}
        onChange={(v) => patch({ poisson: v })}
        step={0.01}
      />
      <MatField
        label="密度"
        unit="t/mm³"
        value={material.density}
        editable={isCustom}
        onChange={(v) => patch({ density: v })}
        expFmt
      />
    </div>
  );
}

function MatField({
  label, unit, value, editable, onChange, step = 1, expFmt = false,
}: {
  label: string;
  unit: string;
  value: number;
  editable: boolean;
  onChange: (v: number) => void;
  step?: number;
  expFmt?: boolean;
}) {
  const display = expFmt
    ? value.toExponential(2)
    : value.toLocaleString("en-US", { maximumFractionDigits: 4 });
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-stroke/60 bg-white/[0.02] px-2.5 py-1.5">
      <span className="text-[12px] text-slate-400">{label}</span>
      {editable ? (
        <div className="flex flex-1 items-center justify-end gap-1">
          <input
            type="number"
            step={step}
            value={value}
            onChange={(e) => {
              const v = Number(e.target.value);
              if (Number.isFinite(v)) onChange(v);
            }}
            className="w-24 rounded-md border border-stroke/60 bg-black/30 px-1.5 py-0.5 text-right font-mono text-[12px] text-slate-200 outline-none focus:border-cyan-400/60"
          />
          {unit && <span className="font-mono text-[11px] text-slate-500">{unit}</span>}
        </div>
      ) : (
        <span className="font-mono text-[12px] text-slate-200">
          {display}{unit && <span className="ml-1 text-slate-500">{unit}</span>}
        </span>
      )}
    </div>
  );
}
