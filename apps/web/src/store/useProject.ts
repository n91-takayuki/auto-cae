import { create } from "zustand";
import type {
  BCInput,
  GeometryDTO,
  JobDTO,
  LoadApplication,
  ProjectDTO,
  ResultDTO,
} from "@/api/client";
import { api } from "@/api/client";
import { DEFAULT_MATERIAL, type MaterialSpec } from "@/data/materials";

type LogEntry = { level: "info" | "error"; msg: string; ts: number };

export type FixBC = {
  id: string;
  type: "fix";
  faceIds: number[];
  dofs: { x: boolean; y: boolean; z: boolean };
};

export type LoadBC = {
  id: string;
  type: "load";
  faceIds: number[];
  magnitude: number;
  kind: "force" | "pressure";
  direction: "normal" | { x: number; y: number; z: number };
  application: LoadApplication;
};

export type PlacementMode = "point" | "region" | null;

export type BC = FixBC | LoadBC;

type State = {
  project: ProjectDTO | null;
  geometry: GeometryDTO | null;
  loading: boolean;
  error: string | null;
  logs: LogEntry[];

  hoveredFaceId: number | null;
  selectedFaceIds: Set<number>;
  bcs: BC[];

  job: JobDTO | null;
  result: ResultDTO | null;
  dispScale: number;
  showResult: boolean;

  material: MaterialSpec;
  history: JobDTO[];

  meshSizeFactor: number;
  showMeshEdges: boolean;

  placementMode: PlacementMode;
  placementPoint: [number, number, number] | null;
  placementRadius: number;

  setPlacementMode: (m: PlacementMode) => void;
  setPlacementPoint: (p: [number, number, number] | null) => void;
  setPlacementRadius: (r: number) => void;
  clearPlacement: () => void;

  setDispScale: (v: number) => void;
  setShowResult: (v: boolean) => void;
  setMaterial: (m: MaterialSpec) => void;
  setMeshSizeFactor: (v: number) => void;
  setShowMeshEdges: (v: boolean) => void;
  loadJobResult: (jobId: string) => Promise<void>;

  uploadStep: (file: File) => Promise<void>;
  reset: () => void;
  log: (level: LogEntry["level"], msg: string) => void;

  setHovered: (id: number | null) => void;
  toggleSelect: (id: number, additive: boolean) => void;
  clearSelection: () => void;

  addFix: (dofs?: { x: boolean; y: boolean; z: boolean }) => void;
  addLoad: (input: Omit<LoadBC, "id" | "type" | "faceIds" | "application"> & {
    application?: LoadApplication;
  }) => void;
  removeBc: (id: string) => void;

  runAnalysis: () => Promise<void>;
};

const mkId = () => Math.random().toString(36).slice(2, 10);

export const useProject = create<State>((set, get) => ({
  project: null,
  geometry: null,
  loading: false,
  error: null,
  logs: [],

  hoveredFaceId: null,
  selectedFaceIds: new Set(),
  bcs: [],

  job: null,
  result: null,
  dispScale: 1,
  showResult: true,
  material: DEFAULT_MATERIAL,
  history: [],
  meshSizeFactor: 1.0,
  showMeshEdges: false,

  placementMode: null,
  placementPoint: null,
  placementRadius: 1.0,

  setPlacementMode: (m) => set({ placementMode: m }),
  setPlacementPoint: (p) => set({ placementPoint: p }),
  setPlacementRadius: (r) => set({ placementRadius: r }),
  clearPlacement: () =>
    set({ placementMode: null, placementPoint: null }),

  setDispScale: (v) => set({ dispScale: v }),
  setShowResult: (v) => set({ showResult: v }),
  setMaterial: (m) => set({ material: m }),
  setMeshSizeFactor: (v) => set({ meshSizeFactor: v }),
  setShowMeshEdges: (v) => set({ showMeshEdges: v }),
  loadJobResult: async (jobId) => {
    try {
      const r = await api.getResult(jobId);
      const proj = get().project;
      let autoScale = 1;
      if (proj && r.summary.dispMax > 1e-12) {
        const sx = proj.bboxMax[0] - proj.bboxMin[0];
        const sy = proj.bboxMax[1] - proj.bboxMin[1];
        const sz = proj.bboxMax[2] - proj.bboxMin[2];
        autoScale = (Math.hypot(sx, sy, sz) * 0.05) / r.summary.dispMax;
      }
      set({ result: r, showResult: true, dispScale: autoScale });
      get().log("info", `履歴から結果をロード: ${jobId}`);
    } catch (e) {
      get().log("error", `結果取得失敗: ${e instanceof Error ? e.message : String(e)}`);
    }
  },

  log: (level, msg) =>
    set((s) => ({
      logs: [...s.logs.slice(-199), { level, msg, ts: Date.now() }],
    })),

  uploadStep: async (file) => {
    set({ loading: true, error: null });
    get().log("info", `uploading ${file.name} (${(file.size / 1024).toFixed(1)} KB)`);
    try {
      const project = await api.uploadStep(file);
      get().log("info", `parsed: ${project.faceCount} faces, ${project.triCount} triangles`);
      const geometry = await api.getGeometry(project.id);
      set({
        project,
        geometry,
        loading: false,
        hoveredFaceId: null,
        selectedFaceIds: new Set(),
        bcs: [],
        job: null,
        result: null,
        showResult: true,
        dispScale: 1,
        placementMode: null,
        placementPoint: null,
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      set({ error: msg, loading: false });
      get().log("error", msg);
    }
  },

  reset: () =>
    set({
      project: null,
      geometry: null,
      error: null,
      hoveredFaceId: null,
      selectedFaceIds: new Set(),
      bcs: [],
      job: null,
      result: null,
      showResult: true,
      dispScale: 1,
      placementMode: null,
      placementPoint: null,
    }),

  setHovered: (id) => set({ hoveredFaceId: id }),

  toggleSelect: (id, additive) => {
    const cur = get().selectedFaceIds;
    const next = new Set(additive ? cur : []);
    if (cur.has(id)) next.delete(id);
    else next.add(id);
    set({ selectedFaceIds: next });
  },

  clearSelection: () => set({ selectedFaceIds: new Set() }),

  addFix: (dofs = { x: true, y: true, z: true }) => {
    const ids = Array.from(get().selectedFaceIds);
    if (ids.length === 0) return;
    const bc: FixBC = { id: mkId(), type: "fix", faceIds: ids, dofs };
    set((s) => ({ bcs: [...s.bcs, bc], selectedFaceIds: new Set() }));
    get().log("info", `拘束追加: ${ids.length} 面 (${dofName(dofs)})`);
  },

  addLoad: ({ magnitude, kind, direction, application }) => {
    const ids = Array.from(get().selectedFaceIds);
    if (ids.length === 0) return;
    const app: LoadApplication = application ?? { mode: "face" };
    const bc: LoadBC = {
      id: mkId(),
      type: "load",
      faceIds: ids,
      magnitude,
      kind,
      direction,
      application: app,
    };
    set((s) => ({
      bcs: [...s.bcs, bc],
      selectedFaceIds: new Set(),
      placementMode: null,
      placementPoint: null,
    }));
    const appLabel =
      app.mode === "face"
        ? "面全体"
        : app.mode === "point"
          ? "点"
          : `範囲 r=${app.radius.toFixed(2)}mm`;
    get().log(
      "info",
      `荷重追加: ${ids.length} 面 · ${appLabel} · ${magnitude} ${kind === "force" ? "N" : "MPa"}`
    );
  },

  removeBc: (id) => set((s) => ({ bcs: s.bcs.filter((b) => b.id !== id) })),

  runAnalysis: async () => {
    const s = get();
    if (!s.project) return;
    if (s.bcs.length === 0) {
      s.log("error", "境界条件がありません");
      return;
    }
    if (!s.bcs.some((b) => b.type === "fix")) {
      s.log("error", "少なくとも1つの拘束条件が必要です");
      return;
    }

    const bcInputs: BCInput[] = s.bcs.map((b) =>
      b.type === "fix"
        ? { type: "fix", faceIds: b.faceIds, dofs: b.dofs }
        : {
            type: "load",
            faceIds: b.faceIds,
            magnitude: b.magnitude,
            kind: b.kind,
            direction: b.direction,
            application: b.application,
          }
    );

    set({ result: null, error: null });
    try {
      const mat = s.material;
      const job = await api.createJob({
        projectId: s.project.id,
        bcs: bcInputs,
        material: {
          name: mat.name,
          young: mat.young,
          poisson: mat.poisson,
          density: mat.density,
        },
        mesh: { sizeFactor: s.meshSizeFactor },
      });
      set({ job, history: [job, ...get().history.slice(0, 19)] });
      get().log("info", `ジョブ送信: ${job.id} · ${mat.name}`);

      // WebSocket subscribe
      const ws = api.jobWs(job.id);
      ws.onmessage = (ev) => {
        try {
          const payload = JSON.parse(ev.data) as JobDTO;
          set((st) => ({
            job: payload,
            history: st.history.map((h) => (h.id === payload.id ? payload : h)),
          }));
          if (payload.status === "failed") {
            get().log("error", `解析失敗: ${payload.error ?? ""}`);
          } else if (payload.status === "done") {
            get().log("info", "解析完了 — 結果取得中");
            void api
              .getResult(payload.id)
              .then((r) => {
                const proj = get().project;
                let autoScale = 1;
                if (proj) {
                  const sx = proj.bboxMax[0] - proj.bboxMin[0];
                  const sy = proj.bboxMax[1] - proj.bboxMin[1];
                  const sz = proj.bboxMax[2] - proj.bboxMin[2];
                  const diag = Math.hypot(sx, sy, sz);
                  const target = diag * 0.05;
                  if (r.summary.dispMax > 1e-12) {
                    autoScale = target / r.summary.dispMax;
                  }
                }
                set({ result: r, showResult: true, dispScale: autoScale });
                get().log(
                  "info",
                  `結果: nodes=${r.summary.nodeCount}, σvM max=${r.summary.vonMisesMax.toFixed(2)} MPa, |U| max=${r.summary.dispMax.toExponential(3)} mm`
                );
              })
              .catch((e) => get().log("error", `結果取得失敗: ${String(e)}`));
          }
        } catch {
          /* ignore */
        }
      };
      ws.onerror = () => get().log("error", "WebSocket error");
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      set({ error: msg });
      get().log("error", msg);
    }
  },
}));

function dofName(d: { x: boolean; y: boolean; z: boolean }) {
  const on = [d.x && "X", d.y && "Y", d.z && "Z"].filter(Boolean).join("");
  return on === "XYZ" ? "完全固定" : `${on}方向`;
}
