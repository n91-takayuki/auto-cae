import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import type { ThreeEvent } from "@react-three/fiber";
import type { FaceMeshDTO, GeometryDTO } from "@/api/client";
import { useProject, type LoadBC } from "@/store/useProject";

type Props = { geometry: GeometryDTO };

export function FaceMeshGroup({ geometry }: Props) {
  const { faces, bboxMin, bboxMax } = geometry;

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

  return (
    <group
      scale={scale}
      position={[-center[0] * scale, -center[1] * scale, -center[2] * scale]}
    >
      {faces.map((face) => (
        <FaceMesh key={face.faceId} face={face} />
      ))}
      <PlacementMarker />
      <BCLoadMarkers />
      <LoadArrows geometry={geometry} />
    </group>
  );
}

function PlacementMarker() {
  const placementPoint = useProject((s) => s.placementPoint);
  const placementMode = useProject((s) => s.placementMode);
  const placementRadius = useProject((s) => s.placementRadius);
  if (!placementPoint) return null;
  const isRegion = placementMode === "region";
  return (
    <group position={placementPoint}>
      <mesh>
        <sphereGeometry args={[Math.max(placementRadius * 0.05, 0.2), 16, 12]} />
        <meshStandardMaterial
          color="#f59e0b"
          emissive="#f59e0b"
          emissiveIntensity={1.2}
        />
      </mesh>
      {isRegion && (
        <mesh>
          <sphereGeometry args={[placementRadius, 24, 16]} />
          <meshBasicMaterial
            color="#fbbf24"
            wireframe
            transparent
            opacity={0.35}
            depthWrite={false}
          />
        </mesh>
      )}
    </group>
  );
}

// -------------------------------------------------------- Load direction arrows

function LoadArrows({ geometry }: { geometry: GeometryDTO }) {
  const bcs = useProject((s) => s.bcs);

  const bboxDiag = useMemo(() => {
    const sx = geometry.bboxMax[0] - geometry.bboxMin[0];
    const sy = geometry.bboxMax[1] - geometry.bboxMin[1];
    const sz = geometry.bboxMax[2] - geometry.bboxMin[2];
    return Math.hypot(sx, sy, sz);
  }, [geometry.bboxMin, geometry.bboxMax]);

  const faceMap = useMemo(() => {
    const m = new Map<number, FaceMeshDTO>();
    for (const f of geometry.faces) m.set(f.faceId, f);
    return m;
  }, [geometry.faces]);

  return (
    <>
      {bcs.map((b) => {
        if (b.type !== "load") return null;
        const info = computeLoadArrow(b as LoadBC, faceMap, bboxDiag);
        if (!info) return null;
        return <ArrowPrimitive key={b.id} {...info} />;
      })}
    </>
  );
}

type ArrowInfo = {
  origin: [number, number, number];
  direction: [number, number, number]; // unit
  length: number;
  color: number;
};

function ArrowPrimitive({ origin, direction, length, color }: ArrowInfo) {
  const helper = useMemo(() => {
    const dir = new THREE.Vector3(...direction).normalize();
    const org = new THREE.Vector3(...origin);
    const headLen = length * 0.28;
    const headWidth = length * 0.14;
    return new THREE.ArrowHelper(dir, org, length, color, headLen, headWidth);
  }, [origin, direction, length, color]);
  useEffect(() => {
    return () => {
      helper.dispose?.();
    };
  }, [helper]);
  return <primitive object={helper} />;
}

function computeLoadArrow(
  load: LoadBC,
  faceMap: Map<number, FaceMeshDTO>,
  bboxDiag: number,
): ArrowInfo | null {

  // Aggregate area-weighted normal + area-weighted centroid from all faces
  const normal = new THREE.Vector3();
  const centroid = new THREE.Vector3();
  let totalArea = 0;
  const pa = new THREE.Vector3();
  const pb = new THREE.Vector3();
  const pc = new THREE.Vector3();
  const ab = new THREE.Vector3();
  const ac = new THREE.Vector3();
  const cross = new THREE.Vector3();

  for (const fid of load.faceIds) {
    const face = faceMap.get(fid);
    if (!face) continue;
    const pos = face.positions;
    const idx = face.indices;
    for (let i = 0; i < idx.length; i += 3) {
      const a = idx[i] * 3;
      const b = idx[i + 1] * 3;
      const c = idx[i + 2] * 3;
      pa.set(pos[a], pos[a + 1], pos[a + 2]);
      pb.set(pos[b], pos[b + 1], pos[b + 2]);
      pc.set(pos[c], pos[c + 1], pos[c + 2]);
      ab.subVectors(pb, pa);
      ac.subVectors(pc, pa);
      cross.crossVectors(ab, ac);
      const area = 0.5 * cross.length();
      if (area <= 0) continue;
      totalArea += area;
      // area-weighted cross (not yet unit) accumulated
      normal.addScaledVector(cross, 0.5);
      // tri centroid weighted by area
      const cx = (pa.x + pb.x + pc.x) / 3;
      const cy = (pa.y + pb.y + pc.y) / 3;
      const cz = (pa.z + pb.z + pc.z) / 3;
      centroid.x += cx * area;
      centroid.y += cy * area;
      centroid.z += cz * area;
    }
  }

  if (totalArea <= 0) return null;
  centroid.multiplyScalar(1 / totalArea);
  const nLen = normal.length();
  const unitNormal = nLen > 1e-12
    ? normal.clone().multiplyScalar(1 / nLen)
    : new THREE.Vector3(0, 0, 1);

  // Resolve direction
  let dir: THREE.Vector3;
  if (load.direction === "normal") {
    // Backend convention: positive magnitude pushes INTO the surface
    dir = unitNormal.clone().multiplyScalar(-1);
  } else {
    dir = new THREE.Vector3(
      load.direction.x || 0,
      load.direction.y || 0,
      load.direction.z || 0,
    );
    if (dir.lengthSq() < 1e-18) return null;
    dir.normalize();
  }
  // Negative magnitude reverses the arrow
  if (load.magnitude < 0) dir.multiplyScalar(-1);

  // Resolve origin
  let origin: THREE.Vector3;
  if (load.application.mode === "face") {
    origin = centroid;
  } else {
    origin = new THREE.Vector3(...load.application.point);
  }

  const length = Math.max(bboxDiag * 0.12, 1e-3);
  // Draw arrow so its HEAD lands at the origin (force pointing AT the surface)
  const tail = origin.clone().addScaledVector(dir, -length);

  return {
    origin: [tail.x, tail.y, tail.z],
    direction: [dir.x, dir.y, dir.z],
    length,
    color: 0xf97316, // orange
  };
}

function BCLoadMarkers() {
  const bcs = useProject((s) => s.bcs);
  return (
    <>
      {bcs.map((b) =>
        b.type === "load" && b.application.mode !== "face" ? (
          <group key={b.id} position={b.application.point}>
            <mesh>
              <sphereGeometry
                args={[
                  b.application.mode === "region"
                    ? Math.max(b.application.radius * 0.05, 0.2)
                    : 0.5,
                  16,
                  12,
                ]}
              />
              <meshStandardMaterial
                color="#c4b5fd"
                emissive="#8b5cf6"
                emissiveIntensity={1.0}
              />
            </mesh>
            {b.application.mode === "region" && (
              <mesh>
                <sphereGeometry args={[b.application.radius, 24, 16]} />
                <meshBasicMaterial
                  color="#a78bfa"
                  wireframe
                  transparent
                  opacity={0.25}
                  depthWrite={false}
                />
              </mesh>
            )}
          </group>
        ) : null,
      )}
    </>
  );
}

type FaceState = "default" | "hover" | "selected" | "fix" | "load" | "fix+hover" | "load+hover";

const PALETTE: Record<FaceState, { color: string; emissive: string; emissiveIntensity: number }> = {
  default:       { color: "#cbd5e1", emissive: "#000000", emissiveIntensity: 0 },
  hover:         { color: "#cbd5e1", emissive: "#22d3ee", emissiveIntensity: 0.5 },
  selected:      { color: "#22d3ee", emissive: "#0e7490", emissiveIntensity: 0.9 },
  fix:           { color: "#22c55e", emissive: "#16a34a", emissiveIntensity: 0.85 },
  "fix+hover":   { color: "#4ade80", emissive: "#22c55e", emissiveIntensity: 1.1 },
  load:          { color: "#8b5cf6", emissive: "#7c3aed", emissiveIntensity: 0.85 },
  "load+hover":  { color: "#a78bfa", emissive: "#8b5cf6", emissiveIntensity: 1.1 },
};

function FaceMesh({ face }: { face: FaceMeshDTO }) {
  const geomRef = useRef<THREE.BufferGeometry>(null);

  const hovered = useProject((s) => s.hoveredFaceId === face.faceId);
  const selected = useProject((s) => s.selectedFaceIds.has(face.faceId));
  const bcTag = useProject((s) => {
    for (const bc of s.bcs) {
      if (bc.faceIds.includes(face.faceId)) return bc.type;
    }
    return null;
  });

  const setHovered = useProject((s) => s.setHovered);
  const toggleSelect = useProject((s) => s.toggleSelect);
  const placementMode = useProject((s) => s.placementMode);
  const setPlacementPoint = useProject((s) => s.setPlacementPoint);
  const setPlacementMode = useProject((s) => s.setPlacementMode);

  useEffect(() => {
    const g = geomRef.current;
    if (!g) return;
    g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(face.positions), 3));
    g.setIndex(new THREE.BufferAttribute(new Uint32Array(face.indices), 1));
    g.computeVertexNormals();
    g.computeBoundingSphere();
  }, [face]);

  const state: FaceState = selected
    ? "selected"
    : bcTag === "fix"
    ? hovered ? "fix+hover" : "fix"
    : bcTag === "load"
    ? hovered ? "load+hover" : "load"
    : hovered
    ? "hover"
    : "default";
  const style = PALETTE[state];

  const onOver = (e: ThreeEvent<PointerEvent>) => {
    e.stopPropagation();
    setHovered(face.faceId);
    document.body.style.cursor = placementMode ? "crosshair" : "pointer";
  };
  const onOut = (e: ThreeEvent<PointerEvent>) => {
    e.stopPropagation();
    setHovered(null);
    document.body.style.cursor = "auto";
  };
  const onClick = (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation();
    if (placementMode) {
      // Convert world-space hit point → mesh-local (which = model/mm space,
      // since only the parent group applies scale/position, not the mesh)
      const local = e.object.worldToLocal(e.point.clone());
      setPlacementPoint([local.x, local.y, local.z]);
      setPlacementMode(null);
      return;
    }
    toggleSelect(face.faceId, e.shiftKey || e.metaKey || e.ctrlKey);
  };

  return (
    <mesh
      userData={{ faceId: face.faceId }}
      onPointerOver={onOver}
      onPointerOut={onOut}
      onClick={onClick}
      castShadow
      receiveShadow
    >
      <bufferGeometry ref={geomRef} />
      <meshStandardMaterial
        color={style.color}
        emissive={style.emissive}
        emissiveIntensity={style.emissiveIntensity}
        metalness={0.05}
        roughness={0.55}
      />
    </mesh>
  );
}
