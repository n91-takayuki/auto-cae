import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import type { ThreeEvent } from "@react-three/fiber";
import type { FaceMeshDTO, GeometryDTO } from "@/api/client";
import { useProject } from "@/store/useProject";

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
    </group>
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
    document.body.style.cursor = "pointer";
  };
  const onOut = (e: ThreeEvent<PointerEvent>) => {
    e.stopPropagation();
    setHovered(null);
    document.body.style.cursor = "auto";
  };
  const onClick = (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation();
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
