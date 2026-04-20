import { Canvas } from "@react-three/fiber";
import { OrbitControls, Environment, GizmoHelper, GizmoViewport, Grid } from "@react-three/drei";
import { useProject } from "@/store/useProject";
import { FaceMeshGroup } from "./FaceMesh";
import { ResultOverlay } from "./ResultOverlay";

export function Viewer() {
  const geometry = useProject((s) => s.geometry);
  const result = useProject((s) => s.result);
  const showResult = useProject((s) => s.showResult);
  const clearSelection = useProject((s) => s.clearSelection);
  const showingResult = !!result && showResult;

  return (
    <Canvas
      className="absolute inset-0"
      camera={{ position: [3, 2.5, 4], fov: 45, near: 0.01, far: 1000 }}
      dpr={[1, 2]}
      gl={{ antialias: true, alpha: true }}
      onPointerMissed={() => clearSelection()}
    >
      <color attach="background" args={["#020617"]} />
      <hemisphereLight args={["#a5f3fc", "#312e81", 0.6]} />
      <directionalLight position={[5, 8, 5]} intensity={1.2} castShadow />
      <directionalLight position={[-4, 3, -2]} intensity={0.3} color="#c4b5fd" />
      <Environment preset="city" background={false} />

      {showingResult && result ? (
        <ResultOverlay result={result} />
      ) : geometry ? (
        <FaceMeshGroup geometry={geometry} />
      ) : (
        <Placeholder />
      )}

      <Grid
        args={[20, 20]}
        cellSize={0.5}
        cellThickness={0.6}
        cellColor="#1e293b"
        sectionSize={2.5}
        sectionThickness={1}
        sectionColor="#334155"
        fadeDistance={18}
        fadeStrength={1.5}
        infiniteGrid
        position={[0, -1.01, 0]}
      />

      <OrbitControls makeDefault enableDamping dampingFactor={0.08} />
      <GizmoHelper alignment="bottom-right" margin={[360, 140]}>
        <GizmoViewport labelColor="white" axisHeadScale={1} />
      </GizmoHelper>
    </Canvas>
  );
}

function Placeholder() {
  return (
    <mesh position={[0, 0, 0]}>
      <boxGeometry args={[1, 1, 1]} />
      <meshStandardMaterial
        color="#475569"
        metalness={0.1}
        roughness={0.6}
        transparent
        opacity={0.35}
        wireframe
      />
    </mesh>
  );
}
