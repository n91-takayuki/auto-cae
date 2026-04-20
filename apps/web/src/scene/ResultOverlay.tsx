import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import type { ResultDTO } from "@/api/client";
import { useProject } from "@/store/useProject";

type Props = { result: ResultDTO };

export function ResultOverlay({ result }: Props) {
  const dispScale = useProject((s) => s.dispScale);
  const showMeshEdges = useProject((s) => s.showMeshEdges);

  const {
    positions, displaced, vm, indices, lineIndices,
    bboxMin, bboxMax, vmMin, vmMax,
  } = useMemo(() => computeBuffers(result), [result]);

  const matRef = useRef<THREE.ShaderMaterial>(null);
  const lineMatRef = useRef<THREE.ShaderMaterial>(null);

  useEffect(() => {
    if (matRef.current) {
      matRef.current.uniforms.uVmMin.value = vmMin;
      matRef.current.uniforms.uVmMax.value = vmMax;
    }
  }, [vmMin, vmMax]);

  useEffect(() => {
    if (matRef.current) matRef.current.uniforms.uDispScale.value = dispScale;
    if (lineMatRef.current) lineMatRef.current.uniforms.uDispScale.value = dispScale;
  }, [dispScale]);

  const { center, scale } = useMemo(() => {
    const cx = (bboxMin[0] + bboxMax[0]) / 2;
    const cy = (bboxMin[1] + bboxMax[1]) / 2;
    const cz = (bboxMin[2] + bboxMax[2]) / 2;
    const sx = bboxMax[0] - bboxMin[0];
    const sy = bboxMax[1] - bboxMin[1];
    const sz = bboxMax[2] - bboxMin[2];
    const maxSpan = Math.max(sx, sy, sz, 1e-6);
    return { center: [cx, cy, cz] as const, scale: 2 / maxSpan };
  }, [bboxMin, bboxMax]);

  const geomRef = useRef<THREE.BufferGeometry>(null);
  const lineGeomRef = useRef<THREE.BufferGeometry>(null);

  useEffect(() => {
    const g = geomRef.current;
    if (!g) return;
    g.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    g.setAttribute("aDisp", new THREE.BufferAttribute(displaced, 3));
    g.setAttribute("aVm", new THREE.BufferAttribute(vm, 1));
    g.setIndex(new THREE.BufferAttribute(indices, 1));
    g.computeBoundingSphere();
  }, [positions, displaced, vm, indices]);

  useEffect(() => {
    const g = lineGeomRef.current;
    if (!g) return;
    g.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    g.setAttribute("aDisp", new THREE.BufferAttribute(displaced, 3));
    g.setIndex(new THREE.BufferAttribute(lineIndices, 1));
    g.computeBoundingSphere();
  }, [positions, displaced, lineIndices]);

  return (
    <group
      scale={scale}
      position={[-center[0] * scale, -center[1] * scale, -center[2] * scale]}
    >
      <mesh castShadow receiveShadow>
        <bufferGeometry ref={geomRef} />
        <shaderMaterial
          ref={matRef}
          vertexShader={VERT}
          fragmentShader={FRAG}
          uniforms={{
            uDispScale: { value: dispScale },
            uVmMin: { value: vmMin },
            uVmMax: { value: vmMax },
            uLightDir: { value: new THREE.Vector3(0.4, 0.8, 0.5).normalize() },
          }}
        />
      </mesh>
      {showMeshEdges && (
        <lineSegments renderOrder={1}>
          <bufferGeometry ref={lineGeomRef} />
          <shaderMaterial
            ref={lineMatRef}
            vertexShader={LINE_VERT}
            fragmentShader={LINE_FRAG}
            transparent
            depthTest
            uniforms={{
              uDispScale: { value: dispScale },
              uColor: { value: new THREE.Color(0.08, 0.12, 0.16) },
              uOpacity: { value: 0.85 },
            }}
          />
        </lineSegments>
      )}
    </group>
  );
}

function computeBuffers(r: ResultDTO) {
  const n = r.nodes.length / 3;
  const positions = new Float32Array(r.nodes);
  const disp = new Float32Array(r.disp);
  const vm = new Float32Array(r.vonMises);
  const tri = r.surfaceIndices;
  const useUint32 = n >= 65535;
  const indices = useUint32 ? new Uint32Array(tri) : new Uint16Array(tri);

  // Build deduped edge index buffer
  const seen = new Set<number>();
  const edgeList: number[] = [];
  for (let i = 0; i < tri.length; i += 3) {
    const a = tri[i], b = tri[i + 1], c = tri[i + 2];
    addEdge(a, b, n, seen, edgeList);
    addEdge(b, c, n, seen, edgeList);
    addEdge(c, a, n, seen, edgeList);
  }
  const lineIndices = useUint32
    ? new Uint32Array(edgeList)
    : new Uint16Array(edgeList);

  let xmin = Infinity, ymin = Infinity, zmin = Infinity;
  let xmax = -Infinity, ymax = -Infinity, zmax = -Infinity;
  for (let i = 0; i < n; i++) {
    const x = positions[i * 3];
    const y = positions[i * 3 + 1];
    const z = positions[i * 3 + 2];
    if (x < xmin) xmin = x; if (x > xmax) xmax = x;
    if (y < ymin) ymin = y; if (y > ymax) ymax = y;
    if (z < zmin) zmin = z; if (z > zmax) zmax = z;
  }

  return {
    positions,
    displaced: disp,
    vm,
    indices,
    lineIndices,
    bboxMin: [xmin, ymin, zmin] as const,
    bboxMax: [xmax, ymax, zmax] as const,
    vmMin: r.summary.vonMisesMin,
    vmMax: r.summary.vonMisesMax,
  };
}

function addEdge(a: number, b: number, n: number, seen: Set<number>, out: number[]) {
  const lo = a < b ? a : b;
  const hi = a < b ? b : a;
  const key = lo * n + hi;
  if (seen.has(key)) return;
  seen.add(key);
  out.push(a, b);
}

// Matplotlib "jet" rainbow: blue -> cyan -> green -> yellow -> red
const JET = `
vec3 jet(float t) {
  t = clamp(t, 0.0, 1.0);
  float r = clamp(1.5 - abs(4.0 * t - 3.0), 0.0, 1.0);
  float g = clamp(1.5 - abs(4.0 * t - 2.0), 0.0, 1.0);
  float b = clamp(1.5 - abs(4.0 * t - 1.0), 0.0, 1.0);
  return vec3(r, g, b);
}
`;

const VERT = `
attribute vec3 aDisp;
attribute float aVm;
uniform float uDispScale;
varying float vVm;
varying vec3 vWorldPos;

void main() {
  vec3 displaced = position + aDisp * uDispScale;
  vec4 worldPos = modelMatrix * vec4(displaced, 1.0);
  vWorldPos = worldPos.xyz;
  vVm = aVm;
  gl_Position = projectionMatrix * viewMatrix * worldPos;
}
`;

const FRAG = `
precision highp float;
uniform float uVmMin;
uniform float uVmMax;
uniform vec3 uLightDir;
varying float vVm;
varying vec3 vWorldPos;

${JET}

void main() {
  vec3 dx = dFdx(vWorldPos);
  vec3 dy = dFdy(vWorldPos);
  vec3 n = normalize(cross(dx, dy));
  if (!gl_FrontFacing) n = -n;

  float denom = max(uVmMax - uVmMin, 1e-9);
  float t = (vVm - uVmMin) / denom;
  vec3 col = jet(t);

  float nd = max(dot(n, normalize(uLightDir)), 0.0);
  vec3 lit = col * (0.35 + 0.75 * nd);
  gl_FragColor = vec4(lit, 1.0);
}
`;

const LINE_VERT = `
attribute vec3 aDisp;
uniform float uDispScale;
void main() {
  vec3 displaced = position + aDisp * uDispScale;
  vec4 worldPos = modelMatrix * vec4(displaced, 1.0);
  // Push lines slightly toward camera to avoid z-fighting with the filled mesh
  vec4 viewPos = viewMatrix * worldPos;
  viewPos.z += 0.0015;
  gl_Position = projectionMatrix * viewPos;
}
`;

const LINE_FRAG = `
precision highp float;
uniform vec3 uColor;
uniform float uOpacity;
void main() {
  gl_FragColor = vec4(uColor, uOpacity);
}
`;
