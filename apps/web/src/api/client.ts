export type FaceMeshDTO = {
  faceId: number;
  positions: number[];
  indices: number[];
  triCount: number;
};

export type GeometryDTO = {
  bboxMin: [number, number, number];
  bboxMax: [number, number, number];
  linDeflection: number;
  faces: FaceMeshDTO[];
};

export type ProjectDTO = {
  id: string;
  filename: string;
  faceCount: number;
  triCount: number;
  bboxMin: [number, number, number];
  bboxMax: [number, number, number];
};

export type FixBCInput = {
  type: "fix";
  faceIds: number[];
  dofs: { x: boolean; y: boolean; z: boolean };
};

export type LoadBCInput = {
  type: "load";
  faceIds: number[];
  magnitude: number;
  kind: "force" | "pressure";
  direction: "normal" | { x: number; y: number; z: number };
};

export type BCInput = FixBCInput | LoadBCInput;

export type MaterialInput = {
  name?: string;
  young?: number;
  poisson?: number;
  density?: number;
};

export type JobRequestDTO = {
  projectId: string;
  bcs: BCInput[];
  material?: MaterialInput;
  mesh?: { element?: "tet10"; sizeFactor?: number };
};

export type JobStatus =
  | "queued"
  | "meshing"
  | "solving"
  | "postprocess"
  | "done"
  | "failed"
  | "cancelled";

export type JobDTO = {
  id: string;
  projectId: string;
  status: JobStatus;
  progress: number;
  message: string;
  error: string | null;
};

export type ResultSummary = {
  nodeCount: number;
  elementCount: number;
  dispMax: number;
  vonMisesMax: number;
  vonMisesMin: number;
};

export type ResultDTO = {
  jobId: string;
  summary: ResultSummary;
  nodes: number[];
  disp: number[];
  vonMises: number[];
  surfaceIndices: number[];
};

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => fetch("/api/health").then(json<Record<string, unknown>>),
  capabilities: () => fetch("/api/capabilities").then(json<Record<string, boolean>>),
  uploadStep: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetch("/api/projects", { method: "POST", body: fd }).then(json<ProjectDTO>);
  },
  getGeometry: (id: string) =>
    fetch(`/api/projects/${id}/geometry`).then(json<GeometryDTO>),
  createJob: (req: JobRequestDTO) =>
    fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    }).then(json<JobDTO>),
  getJob: (id: string) => fetch(`/api/jobs/${id}`).then(json<JobDTO>),
  listJobs: (projectId?: string) =>
    fetch(`/api/jobs${projectId ? `?projectId=${projectId}` : ""}`).then(
      json<JobDTO[]>
    ),
  getResult: (id: string) => fetch(`/api/jobs/${id}/result`).then(json<ResultDTO>),
  jobWs: (id: string) => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    return new WebSocket(`${proto}://${location.host}/ws/jobs/${id}`);
  },
};
