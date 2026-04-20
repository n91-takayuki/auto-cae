export type MaterialSpec = {
  key: string;
  name: string;
  young: number;     // MPa
  poisson: number;
  density: number;   // t/mm^3
};

export const MATERIALS: MaterialSpec[] = [
  { key: "s45c",    name: "構造用鋼 S45C",     young: 206_000, poisson: 0.30, density: 7.85e-9 },
  { key: "sus304",  name: "ステンレス SUS304", young: 193_000, poisson: 0.30, density: 7.93e-9 },
  { key: "a5052",   name: "アルミ A5052",      young: 70_300,  poisson: 0.33, density: 2.68e-9 },
  { key: "c1020",   name: "銅 C1020",          young: 117_000, poisson: 0.33, density: 8.94e-9 },
  { key: "ti64",    name: "チタン Ti-6Al-4V",  young: 110_000, poisson: 0.34, density: 4.43e-9 },
  { key: "custom",  name: "カスタム",          young: 206_000, poisson: 0.30, density: 7.85e-9 },
];

export const DEFAULT_MATERIAL = MATERIALS[0];
