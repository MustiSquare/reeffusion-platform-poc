import React, {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createRoot } from "react-dom/client";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import {
  Database,
  Upload,
  Waves,
  Play,
  Tags,
  GitCompare,
  Brain,
  RotateCcw,
  Crosshair,
  Ruler,
  Eye,
  EyeOff,
  Trash2,
  MousePointer2,
  Search,
  ChevronDown,
  ChevronRight,
  FolderOpen,
  Activity,
  CalendarDays,
  MapPin,
  FileText,
  CheckCircle2,
  AlertTriangle,
  Download,
  FileDown,
  Sun,
  Moon,
} from "lucide-react";
import {
  getJson,
  postJson,
  putJson,
  deleteJson,
  uploadFiles,
  assetUrl,
} from "./api/client";
import "./styles.css";
import LiveSurvey from "./survey/LiveSurvey";
import { viewerFraming } from "./survey/viewerFraming";

type Theme = "dark" | "light";
const THEME_KEY = "reef-theme";

/* The 3D scene is drawn by WebGL, so it cannot read the CSS custom
   properties the rest of the UI uses. These mirror the --scene-* tokens
   in styles.css — keep the two in sync. */
const sceneColors: Record<Theme, Record<string, string>> = {
  dark: {
    background: "#05131f",
    reef: "#1a7182",
    wireframe: "#7dd3fc",
    grid: "#38bdf8",
    gridSub: "#164e63",
  },
  light: {
    background: "#dbeaf2",
    reef: "#2a94a8",
    wireframe: "#0e7490",
    grid: "#0e7490",
    gridSub: "#9cbccb",
  },
};

function readStoredTheme(): Theme {
  try {
    const stored = window.localStorage.getItem(THEME_KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch {
    /* localStorage unavailable (private mode, blocked cookies) */
  }
  return "dark";
}

const ThemeContext = createContext<Theme>("dark");
const useTheme = () => useContext(ThemeContext);

type Dataset = {
  id: string;
  name: string;
  status: string;
  file_count?: number;
  metrics?: any;
  processing_version?: string;
  location?: string;
  survey_date?: string;
  metadata?: any;
  sensor_metadata?: any;
  coordinate_system?: any;
  quality_report?: any;
  processing_version_info?: any;
};
type DatasetAsset = {
  id: string;
  file_name: string;
  asset_type: string;
  media_type: string;
  size_bytes?: number;
  metadata?: any;
  url: string;
};
type AnnotationItem = {
  id: string;
  label: string;
  annotation_type: string;
  geometry_json: any;
  properties_json?: any;
};
type ReefPoint = {
  supported?: boolean;
  x: number;
  y: number;
  z: number;
  className?: string;
  health?: string;
};
type ViewerMode = "inspect" | "annotate" | "measure";
type AnnotationShape = "point" | "surface";

type ViewerProps = {
  dataset?: Dataset;
  annotationMode?: boolean;
  onAnnotationCreated?: () => void;
};

function AssetBrowser({ datasetId }: { datasetId?: string }) {
  const [assets, setAssets] = useState<DatasetAsset[]>([]);
  const [selected, setSelected] = useState<DatasetAsset | null>(null);
  const [preview, setPreview] = useState("");
  useEffect(() => {
    if (!datasetId) {
      setAssets([]);
      setSelected(null);
      return;
    }
    getJson(`/api/datasets/processed/${datasetId}`)
      .then((d) => {
        setAssets(d.assets || []);
        setSelected((d.assets || [])[0] || null);
      })
      .catch(() => setAssets([]));
  }, [datasetId]);
  useEffect(() => {
    if (!selected) {
      setPreview("");
      return;
    }
    const isText =
      selected.media_type?.startsWith("text/") ||
      selected.media_type === "application/json" ||
      selected.asset_type.includes("point_cloud") ||
      selected.asset_type.includes("texture_mapping");
    if (!isText) {
      setPreview("");
      return;
    }
    fetch(assetUrl(selected.url))
      .then((r) => r.text())
      .then((text) => setPreview(text.split("\n").slice(0, 18).join("\n")))
      .catch(() => setPreview(""));
  }, [selected?.id]);
  if (!datasetId || !assets.length) return null;
  return (
    <div className="assetBrowser">
      <div className="assetBrowserHeader">
        <h3>Processed Assets</h3>
        <span>{assets.length} outputs</span>
      </div>
      <div className="assetButtons">
        {assets.map((asset) => (
          <button
            key={asset.id}
            className={selected?.id === asset.id ? "active" : ""}
            onClick={() => setSelected(asset)}
          >
            <FileText size={14} />
            {asset.file_name}
          </button>
        ))}
      </div>
      {selected && (
        <div className="assetPreviewPanel">
          <div className="assetActions">
            <b>{selected.asset_type}</b>
            <a href={assetUrl(selected.url)} target="_blank" rel="noreferrer">
              <Eye size={14} />
              Preview
            </a>
            <a href={assetUrl(selected.url)} download={selected.file_name}>
              <Download size={14} />
              Download
            </a>
          </div>
          {selected.media_type?.startsWith("image/") ? (
            <img src={assetUrl(selected.url)} alt={selected.file_name} />
          ) : preview ? (
            <pre>{preview}</pre>
          ) : (
            <div className="binaryPreview">
              <FileDown size={18} />
              <span>{selected.file_name}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

const tabs = [
  "Raw Data Upload",
  "Raw Data Viewer",
  "Raw Data Processing",
  "Processed Data Viewer",
  "AI-Agents",
  "Data Archive",
  "Live Survey",
];
const benthicClasses = ["coral", "rock", "sand", "algae"];
const healthClasses = ["healthy", "bleached", "dead", "diseased"];
const labelColors: Record<string, string> = {
  coral: "#ff9f6e",
  rock: "#8d99ae",
  sand: "#e9d8a6",
  algae: "#52b788",
  healthy: "#2dd4bf",
  bleached: "#f8fafc",
  dead: "#6b7280",
  diseased: "#ef4444",
};

function classifyPoint(p: ReefPoint) {
  const r = Math.hypot(p.x, p.y);
  const cls =
    p.z > -6.9 ? "coral" : r > 3.5 ? "sand" : p.x > 1.0 ? "algae" : "rock";
  const health =
    cls === "coral"
      ? p.y > 1.4
        ? "bleached"
        : p.x < -1.8
          ? "diseased"
          : "healthy"
      : "healthy";
  return { ...p, className: cls, health };
}

function parseXYZ(text: string): ReefPoint[] {
  return text
    .split("\n")
    .slice(1)
    .map((line) => {
      const [x, y, z, supported] = line.split(",").map(Number);
      return { x, y, z, supported: supported !== 0 };
    })
    .filter(
      (p) =>
        Number.isFinite(p.x) && Number.isFinite(p.y) && Number.isFinite(p.z),
    )
    .map(classifyPoint);
}

function OrbitController({
  target,
  viewSignal,
  minDistance,
  maxDistance,
}: {
  target: THREE.Vector3;
  viewSignal: number;
  minDistance: number;
  maxDistance: number;
}) {
  const { camera, gl } = useThree();
  const controlsRef = useRef<OrbitControls | null>(null);
  useEffect(() => {
    const controls = new OrbitControls(camera, gl.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.screenSpacePanning = true;
    controls.minDistance = minDistance;
    controls.maxDistance = maxDistance;
    controls.target.copy(target);
    controls.update();
    controlsRef.current = controls;
    return () => controls.dispose();
  }, [camera, gl, target, minDistance, maxDistance]);
  useEffect(() => {
    controlsRef.current?.target.copy(target);
    controlsRef.current?.update();
  }, [target, viewSignal]);
  useFrame(() => controlsRef.current?.update());
  return null;
}

function buildPointGeometry(
  points: ReefPoint[],
  zScale: number,
  colorBy: "depth" | "benthic" | "health",
) {
  points = points.filter(p => p.supported !== false);
  if (!points.length) return new THREE.BufferGeometry();
  const positions = new Float32Array(points.length * 3);
  const colors = new Float32Array(points.length * 3);
  const color = new THREE.Color();
  const zVals = points.map((p) => p.z);
  const minZ = zVals.reduce((a,b)=>Math.min(a,b),Infinity);
  const maxZ = zVals.reduce((a,b)=>Math.max(a,b),-Infinity);
  const span = Math.max(maxZ - minZ, 0.001);
  points.forEach((p, i) => {
    positions[i * 3] = p.x;
    positions[i * 3 + 1] = p.z * zScale;
    positions[i * 3 + 2] = p.y;
    if (colorBy === "benthic") color.set(labelColors[p.className || "rock"]);
    else if (colorBy === "health")
      color.set(labelColors[p.health || "healthy"]);
    else color.setHSL(0.56 - ((p.z - minZ) / span) * 0.18, 0.75, 0.55);
    colors[i * 3] = color.r;
    colors[i * 3 + 1] = color.g;
    colors[i * 3 + 2] = color.b;
  });
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
  geometry.computeBoundingSphere();
  return geometry;
}

function buildSurfaceGeometry(points: ReefPoint[], zScale: number) {
  if (!points.length) return new THREE.BufferGeometry();
  const n = Math.round(Math.sqrt(points.length));
  const ordered = points.slice(0, n * n);
  const positions = new Float32Array(ordered.length * 3);
  ordered.forEach((p, i) => {
    positions[i * 3] = p.x;
    positions[i * 3 + 1] = p.z * zScale;
    positions[i * 3 + 2] = p.y;
  });
  const indices: number[] = [];
  for (let row = 0; row < n - 1; row++)
    for (let col = 0; col < n - 1; col++) {
      const a = row * n + col,
        b = a + 1,
        c = a + n,
        d = c + 1;
      if ([a,c,b].every(i => ordered[i].supported !== false)) indices.push(a,c,b);
      if ([b,c,d].every(i => ordered[i].supported !== false)) indices.push(b,c,d);
    }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  const uvs = new Float32Array(ordered.length * 2);
  const xs = ordered.map((p) => p.x),
    ys = ordered.map((p) => p.y);
  const minX = Math.min(...xs),
    maxX = Math.max(...xs),
    minY = Math.min(...ys),
    maxY = Math.max(...ys);
  ordered.forEach((p, i) => {
    uvs[i * 2] = (p.x - minX) / Math.max(maxX - minX, 0.001);
    uvs[i * 2 + 1] = (p.y - minY) / Math.max(maxY - minY, 0.001);
  });
  geometry.setAttribute("uv", new THREE.BufferAttribute(uvs, 2));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  geometry.computeBoundingBox();
  geometry.computeBoundingSphere();
  return geometry;
}

function transformGlbScene(scene: THREE.Object3D, zScale: number) {
  const clone = scene.clone(true);
  const matrix = new THREE.Matrix4().set(
    1, 0, 0, 0,
    0, 0, zScale, 0,
    0, 1, 0, 0,
    0, 0, 0, 1,
  );
  clone.traverse((child: any) => {
    if (child.isMesh) {
      child.geometry = child.geometry.clone();
      child.geometry.applyMatrix4(matrix);
      child.geometry.computeBoundingBox();
      child.geometry.computeBoundingSphere();
      child.material = child.material?.clone?.() || new THREE.MeshStandardMaterial({ color: "#38bdf8" });
      child.castShadow = false;
      child.receiveShadow = true;
    }
  });
  return clone;
}

function polygonPlanarArea(vertices: ReefPoint[]) {
  if (vertices.length < 3) return 0;
  let sum = 0;
  for (let i = 0; i < vertices.length; i++) {
    const a = vertices[i];
    const b = vertices[(i + 1) % vertices.length];
    sum += a.x * b.y - b.x * a.y;
  }
  return Math.abs(sum) / 2;
}

function PolygonAnnotationMesh({
  annotation,
  zScale,
  draft = false,
  onSelect,
}: {
  annotation: AnnotationItem;
  zScale: number;
  draft?: boolean;
  onSelect?: (a: AnnotationItem) => void;
}) {
  const coords = annotation.geometry_json?.coordinates || [];
  const vertices = Array.isArray(coords?.[0]?.[0]) ? coords[0] : coords;
  const geometry = useMemo(() => {
    const clean = vertices.filter(
      (c: any) => Array.isArray(c) && c.length >= 3,
    );
    const positions = new Float32Array(clean.length * 3);
    clean.forEach((c: number[], i: number) => {
      positions[i * 3] = c[0];
      positions[i * 3 + 1] = c[2] * zScale + 0.018;
      positions[i * 3 + 2] = c[1];
    });
    const indices: number[] = [];
    for (let i = 1; i < clean.length - 1; i++) indices.push(0, i, i + 1);
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    if (indices.length) g.setIndex(indices);
    g.computeVertexNormals();
    return g;
  }, [vertices, zScale]);
  const linePoints = useMemo(() => {
    const clean = vertices.filter(
      (c: any) => Array.isArray(c) && c.length >= 3,
    );
    return clean.map(
      (c: number[]) => new THREE.Vector3(c[0], c[2] * zScale + 0.035, c[1]),
    );
  }, [vertices, zScale]);
  const lineGeometry = useMemo(() => {
    const pts =
      linePoints.length >= 3 ? [...linePoints, linePoints[0]] : linePoints;
    return new THREE.BufferGeometry().setFromPoints(pts);
  }, [linePoints]);
  const label = annotation.label || "coral";
  const color = labelColors[label] || "#ffffff";
  const lineObject = useMemo(
    () =>
      new THREE.Line(
        lineGeometry,
        new THREE.LineBasicMaterial({ color, linewidth: 2 }),
      ),
    [lineGeometry, color],
  );
  if (vertices.length < 2) return null;
  return (
    <group
      onClick={(e) => {
        e.stopPropagation();
        if (onSelect) onSelect(annotation);
      }}
    >
      {vertices.length >= 3 && (
        <mesh geometry={geometry}>
          <meshStandardMaterial
            color={color}
            emissive={color}
            emissiveIntensity={draft ? 0.18 : 0.1}
            transparent
            opacity={draft ? 0.32 : 0.24}
            side={THREE.DoubleSide}
            depthWrite={false}
          />
        </mesh>
      )}
      {linePoints.length >= 2 && (
        <primitive object={lineObject} />
      )}
      {linePoints.map((pt, i) => (
        <mesh key={i} position={pt}>
          <sphereGeometry args={[draft ? 0.05 : 0.04, 12, 12]} />
          <meshStandardMaterial
            color={color}
            emissive={color}
            emissiveIntensity={0.4}
          />
        </mesh>
      ))}
    </group>
  );
}

function AnnotationMarkers({
  annotations,
  draftSurface,
  zScale,
  onSelect,
}: {
  annotations: AnnotationItem[];
  draftSurface?: ReefPoint[];
  zScale: number;
  onSelect: (a: AnnotationItem) => void;
}) {
  const draftAnnotation: AnnotationItem | null =
    draftSurface && draftSurface.length > 0
      ? {
          id: "draft-surface",
          label: "coral",
          annotation_type: "surface_area_draft",
          geometry_json: {
            type: "Polygon",
            coordinates: draftSurface.map((p) => [p.x, p.y, p.z]),
          },
        }
      : null;
  return (
    <group>
      {annotations.map((a) => {
        const type = a.geometry_json?.type || a.annotation_type;
        if (type === "Polygon" || a.annotation_type === "surface_area") {
          return (
            <PolygonAnnotationMesh
              key={a.id}
              annotation={a}
              zScale={zScale}
              onSelect={onSelect}
            />
          );
        }
        const c = a.geometry_json?.coordinates || [0, 0, 0];
        const label = a.label || "coral";
        return (
          <group
            key={a.id}
            position={[c[0], c[2] * zScale, c[1]]}
            onClick={(e) => {
              e.stopPropagation();
              onSelect(a);
            }}
          >
            <group rotation={[Math.PI / 2, Math.PI / 2, Math.PI / 2]}>
              <mesh position={[0, -0.12, 0]}>
                <cylinderGeometry args={[0.018, 0.018, 0.22, 12]} />
                <meshStandardMaterial
                  color={labelColors[label] || "#ffffff"}
                  emissive={labelColors[label] || "#ffffff"}
                  emissiveIntensity={0.35}
                />
              </mesh>
              <mesh position={[0, 0, 0]}>
                <coneGeometry args={[0.055, 0.12, 16]} />
                <meshStandardMaterial
                  color={labelColors[label] || "#ffffff"}
                  emissive={labelColors[label] || "#ffffff"}
                  emissiveIntensity={0.45}
                />
              </mesh>
            </group>
          </group>
        );
      })}
      {draftAnnotation && (
        <PolygonAnnotationMesh
          annotation={draftAnnotation}
          zScale={zScale}
          draft
        />
      )}
    </group>
  );
}

function ReefScene({
  points,
  annotations,
  layers,
  pointSize,
  zScale,
  mode,
  selectedLabel,
  colorBy,
  viewPreset,
  onPick,
  onMeasure,
  onSelectAnnotation,
  draftSurface,
  textureUrl,
  glbScene,
  theme,
}: {
  points: ReefPoint[];
  annotations: AnnotationItem[];
  layers: any;
  pointSize: number;
  zScale: number;
  mode: ViewerMode;
  selectedLabel: string;
  colorBy: "depth" | "benthic" | "health";
  viewPreset: string;
  onPick: (p: ReefPoint) => void;
  onMeasure: (p: ReefPoint) => void;
  onSelectAnnotation: (a: AnnotationItem) => void;
  draftSurface?: ReefPoint[];
  textureUrl?: string;
  glbScene?: THREE.Object3D | null;
  theme: Theme;
}) {
  const scene = sceneColors[theme];
  const pointGeometry = useMemo(
    () => buildPointGeometry(points, zScale, colorBy),
    [points, zScale, colorBy],
  );
  const meshGeometry = useMemo(
    () => glbScene ? new THREE.BufferGeometry() : buildSurfaceGeometry(points, zScale),
    [points, zScale, glbScene],
  );
  useEffect(() => () => {pointGeometry.dispose();}, [pointGeometry]);
  useEffect(() => () => {meshGeometry.dispose();}, [meshGeometry]);
  const [reefTexture, setReefTexture] = useState<THREE.Texture | null>(null);
  const transformedGlbScene = useMemo(
    () => (glbScene ? transformGlbScene(glbScene, zScale) : null),
    [glbScene, zScale],
  );
  useEffect(() => {
    if (!textureUrl) {
      setReefTexture(null);
      return;
    }
    const loader = new THREE.TextureLoader();
    loader.load(textureUrl, (tex) => {
      tex.wrapS = THREE.RepeatWrapping;
      tex.wrapT = THREE.RepeatWrapping;
      tex.repeat.set(2.4, 2.4);
      tex.colorSpace = THREE.SRGBColorSpace;
      setReefTexture(tex);
    });
  }, [textureUrl]);
  const wireScene = useMemo(() => {
    if (!transformedGlbScene) return null;
    const clone = transformedGlbScene.clone(true);
    clone.traverse((child:any) => {
      if (child.isMesh) child.material = new THREE.MeshBasicMaterial({color:scene.wireframe,wireframe:true,transparent:true,opacity:.3});
    });
    return clone;
  }, [transformedGlbScene, scene.wireframe]);
  useEffect(() => () => {wireScene?.traverse((child:any)=>{if(child.isMesh)child.material.dispose();});}, [wireScene]);
  useEffect(() => () => {transformedGlbScene?.traverse((child:any)=>{if(child.isMesh){child.geometry.dispose();child.material.dispose();}});}, [transformedGlbScene]);
  const sceneBounds = useMemo(() => {
    const box = new THREE.Box3();
    if (transformedGlbScene) {
      box.setFromObject(transformedGlbScene);
    }
    const geometryBox = meshGeometry.boundingBox;
    if (geometryBox) box.union(geometryBox);
    return box;
  }, [meshGeometry, transformedGlbScene, zScale]);
  const { camera, size: viewport } = useThree();
  const framing = useMemo(() => viewerFraming(sceneBounds, viewport.width / Math.max(1, viewport.height)), [sceneBounds, viewport.width, viewport.height]);
  const center = framing.center;
  const [viewSignal, setViewSignal] = useState(0);
  useEffect(() => {
    const dist = framing.distance;
    const direction = new THREE.Vector3(5, 4, 7).normalize();
    if (viewPreset === "top")
      direction.set(0, 1, 0.001).normalize();
    else if (viewPreset === "side")
      direction.set(1, 0, 0);
    else if (viewPreset === "front")
      direction.set(0, 0, 1);
    camera.position.copy(center).addScaledVector(direction, dist);
    camera.near = framing.near;
    camera.far = framing.far;
    camera.updateProjectionMatrix();
    camera.lookAt(center);
    setViewSignal((s) => s + 1);
  }, [viewPreset, camera, framing]);
  const handleMeshClick = (e: any) => {
    e.stopPropagation();
    const p = e.point as THREE.Vector3;
    const reefPoint = {
      x: p.x,
      y: p.z,
      z: p.y / zScale,
      className: selectedLabel,
      health: selectedLabel,
    };
    if (mode === "measure") onMeasure(reefPoint);
    else onPick(reefPoint);
  };
  return (
    <>
      <color attach="background" args={[scene.background]} />
      <ambientLight intensity={0.75} />
      <directionalLight position={[4, 8, 5]} intensity={1.4} />
      <pointLight position={[-4, -3, 2]} intensity={0.5} />
      <OrbitController target={center} viewSignal={viewSignal} minDistance={framing.minDistance} maxDistance={framing.maxDistance} />
      {layers.surface && transformedGlbScene && (
        <primitive object={transformedGlbScene} onClick={handleMeshClick} />
      )}
      {layers.surface && !transformedGlbScene && points.length > 0 && (
        <mesh
          geometry={meshGeometry}
          onClick={handleMeshClick}
          visible={layers.surface}
        >
          <meshStandardMaterial
            map={reefTexture || undefined}
            color={reefTexture ? "#ffffff" : scene.reef}
            transparent
            opacity={layers.pointCloud ? 0.55 : 0.92}
            side={THREE.DoubleSide}
            roughness={0.92}
            metalness={0.02}
          />
        </mesh>
      )}
      {layers.wireframe && wireScene && <primitive object={wireScene} onClick={handleMeshClick} />}
      {layers.wireframe && !wireScene && points.length > 0 && (
        <mesh geometry={meshGeometry}>
          <meshBasicMaterial
            color={scene.wireframe}
            wireframe
            transparent
            opacity={0.22}
          />
        </mesh>
      )}
      {layers.pointCloud && points.length > 0 && (
        <points geometry={pointGeometry}>
          <pointsMaterial
            size={pointSize}
            vertexColors
            sizeAttenuation
            transparent
            opacity={0.96}
          />
        </points>
      )}
      {layers.annotations && (
        <AnnotationMarkers
          annotations={annotations}
          draftSurface={draftSurface}
          zScale={zScale}
          onSelect={onSelectAnnotation}
        />
      )}
      {layers.grid && (
        <gridHelper
          args={[framing.gridSize, 20, scene.grid, scene.gridSub]}
          position={[center.x, framing.floor, center.z]}
        />
      )}
    </>
  );
}

function ProfessionalViewer({
  dataset,
  annotationMode = false,
  onAnnotationCreated,
}: ViewerProps) {
  const theme = useTheme();
  const [points, setPoints] = useState<ReefPoint[]>([]);
  const [annotations, setAnnotations] = useState<AnnotationItem[]>([]);
  const [textureUrl, setTextureUrl] = useState<string>("");
  const [glbScene, setGlbScene] = useState<THREE.Object3D | null>(null);
  const [geometrySource, setGeometrySource] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [picked, setPicked] = useState<ReefPoint | null>(null);
  const [selectedAnnotation, setSelectedAnnotation] =
    useState<AnnotationItem | null>(null);
  const [mode, setMode] = useState<ViewerMode>(
    annotationMode ? "annotate" : "inspect",
  );
  const [annotationShape, setAnnotationShape] =
    useState<AnnotationShape>("point");
  const [surfaceDraft, setSurfaceDraft] = useState<ReefPoint[]>([]);
  const [selectedLabel, setSelectedLabel] = useState("coral");
  const [pointSize, setPointSize] = useState(0.015);
  const [zScale, setZScale] = useState(0.52);
  const [colorBy, setColorBy] = useState<"depth" | "benthic" | "health">(
    "benthic",
  );
  const [viewPreset, setViewPreset] = useState("reset");
  const [measure, setMeasure] = useState<ReefPoint[]>([]);
  const [layers, setLayers] = useState({
    pointCloud: true,
    surface: true,
    wireframe: false,
    annotations: annotationMode,
    grid: false,
    benthic: true,
    health: true,
    videoLookup: true,
  });
  const metrics = dataset?.metrics || {};
  const reloadAnnotations = () =>
    dataset &&
    getJson(`/api/annotations/${dataset.id}`)
      .then(setAnnotations)
      .catch(() => setAnnotations([]));
  useEffect(() => {
    if (!dataset) {
      setPoints([]);
      setTextureUrl("");
      setGlbScene(null);
      setGeometrySource("");
      return;
    }
    let cancelled = false;
    let loadedScene:THREE.Object3D|null=null;
    const releaseScene=(scene:THREE.Object3D)=>scene.traverse((child:any)=>{
      if(!child.isMesh)return;
      child.geometry.dispose();
      for(const material of (Array.isArray(child.material)?child.material:[child.material])){
        for(const value of Object.values(material))if(value instanceof THREE.Texture)value.dispose();
        material.dispose();
      }
    });
    setLoading(true);
    setError("");
    setPicked(null);
    setMeasure([]);
    setAnnotations([]);
    setSurfaceDraft([]);
    setSelectedAnnotation(null);
    setTextureUrl("");
    setGlbScene(null);
    setGeometrySource("");
    setPoints([]);
    (async () => {
      try {
        const [d, anns] = await Promise.all([
          getJson(`/api/datasets/processed/${dataset.id}`),
          getJson(`/api/annotations/${dataset.id}`).catch(() => []),
        ]);
        if (cancelled) return;
        setAnnotations(anns);
        const texture = d.assets.find(
          (x: any) => x.asset_type === "coral_texture",
        );
        if (texture) setTextureUrl(assetUrl(texture.url));
        const glbAsset = d.assets.find((x: any) => x.asset_type === "mesh_glb");
        const pointAsset = d.assets.find(
          (x: any) => x.asset_type === "point_cloud_xyz",
        );
        if (!glbAsset && !pointAsset)
          throw new Error(
            "No browser-viewable geometry asset found for this processed dataset.",
          );
        if (glbAsset) {
          const loader = new GLTFLoader();
          const gltf = await loader.loadAsync(assetUrl(glbAsset.url));
          if (cancelled) {releaseScene(gltf.scene);return;}
          loadedScene=gltf.scene;
          if (!cancelled) {
            setGlbScene(gltf.scene);
            setGeometrySource(glbAsset.file_name);
          }
        }
        if (pointAsset) {
          const r = await fetch(assetUrl(pointAsset.url));
          if (!r.ok) throw new Error(`Could not load asset ${pointAsset.file_name}`);
          const text = await r.text();
          if (!cancelled) {
            setPoints(parseXYZ(text));
            setGeometrySource((prev) => prev || pointAsset.file_name);
          }
        } else if (!cancelled) {
          setPoints([]);
        }
      } catch (e: any) {
        if (!cancelled) setError(String(e.message || e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
      if(loadedScene)releaseScene(loadedScene);
    };
  }, [dataset?.id]);
  const bounds = useMemo(() => {
    if (!points.length) return null;
    const xs = points.map((p) => p.x),
      ys = points.map((p) => p.y),
      zs = points.map((p) => p.z);
    return {
      count: points.length,
      minZ: zs.reduce((a,b)=>Math.min(a,b),Infinity),
      maxZ: zs.reduce((a,b)=>Math.max(a,b),-Infinity),
      width: xs.reduce((a,b)=>Math.max(a,b),-Infinity) - xs.reduce((a,b)=>Math.min(a,b),Infinity),
      height: ys.reduce((a,b)=>Math.max(a,b),-Infinity) - ys.reduce((a,b)=>Math.min(a,b),Infinity),
    };
  }, [points]);
  const addAnnotationPick = (p: ReefPoint) => {
    if (mode !== "annotate") {
      setPicked(p);
      return;
    }
    if (annotationShape === "surface") {
      setSurfaceDraft((prev) => [...prev, p]);
      setPicked(p);
      return;
    }
    setPicked(p);
  };
  const undoSurfacePoint = () =>
    setSurfaceDraft((prev) => prev.slice(0, Math.max(prev.length - 1, 0)));
  const clearSurfaceDraft = () => setSurfaceDraft([]);
  const savePointAnnotation = async () => {
    if (!dataset || !picked) return;
    await postJson(`/api/annotations/${dataset.id}`, {
      label: selectedLabel,
      annotation_type: "point",
      geometry_json: {
        type: "Point",
        coordinates: [picked.x, picked.y, picked.z],
      },
      properties_json: {
        source: "interactive-viewer",
        picked_at: new Date().toISOString(),
        mode,
      },
    });
    setPicked(null);
    reloadAnnotations();
    onAnnotationCreated?.();
  };
  const saveSurfaceAnnotation = async () => {
    if (!dataset || surfaceDraft.length < 3) return;
    const planarArea = polygonPlanarArea(surfaceDraft);
    await postJson(`/api/annotations/${dataset.id}`, {
      label: selectedLabel,
      annotation_type: "surface_area",
      geometry_json: {
        type: "Polygon",
        coordinates: surfaceDraft.map((p) => [p.x, p.y, p.z]),
      },
      properties_json: {
        source: "interactive-viewer",
        picked_at: new Date().toISOString(),
        vertex_count: surfaceDraft.length,
        planar_area: planarArea,
        note: "Area calculated from the polygon footprint in model x/y units.",
      },
    });
    setPicked(null);
    setSurfaceDraft([]);
    reloadAnnotations();
    onAnnotationCreated?.();
  };
  const deleteAnnotation = async (id: string) => {
    await deleteJson(`/api/annotations/${id}`);
    reloadAnnotations();
    setSelectedAnnotation(null);
  };
  const onMeasure = (p: ReefPoint) =>
    setMeasure((prev) => (prev.length >= 2 ? [p] : [...prev, p]));
  const distance =
    measure.length === 2
      ? Math.hypot(
          measure[0].x - measure[1].x,
          measure[0].y - measure[1].y,
          measure[0].z - measure[1].z,
        )
      : null;
  return (
    <div className="proViewerShell">
      <div className="viewerToolbar">
        <div className="toolGroup">
          <b>{dataset?.name || "No processed dataset selected"}</b>
          <span>
            {bounds
              ? `${bounds.width.toFixed(1)} × ${bounds.height.toFixed(1)} m · ${bounds.count.toLocaleString()} points · depth ${bounds.minZ.toFixed(2)} to ${bounds.maxZ.toFixed(2)} m`
              : glbScene
                ? `GLB mesh loaded · ${geometrySource}`
                : "No geometry loaded"}
          </span>
        </div>
        <button
          className={mode === "inspect" ? "active" : ""}
          onClick={() => {
            setMode("inspect");
            setSurfaceDraft([]);
          }}
        >
          <MousePointer2 size={16} />
          Inspect
        </button>
        <button
          className={mode === "annotate" ? "active" : ""}
          onClick={() => setMode("annotate")}
        >
          <Crosshair size={16} />
          Annotate
        </button>
        <button
          className={mode === "measure" ? "active" : ""}
          onClick={() => {
            setMode("measure");
            setSurfaceDraft([]);
          }}
        >
          <Ruler size={16} />
          Measure
        </button>
        <button onClick={() => setViewPreset(`reset-${Date.now()}`)}>
          <RotateCcw size={16} />
          Fit dataset
        </button>
        <button onClick={() => setViewPreset("top")}>Top</button>
        <button onClick={() => setViewPreset("side")}>Side</button>
        <button onClick={() => setViewPreset("front")}>Front</button>
      </div>
      <div className="viewerLayout">
        <aside className="viewerSidePanel">
          <h3>Layers</h3>
          {Object.keys(layers).map((k) => (
            <label className="check" key={k}>
              <input
                type="checkbox"
                checked={(layers as any)[k]}
                onChange={(e) =>
                  setLayers({ ...layers, [k]: e.target.checked })
                }
              />
              {(layers as any)[k] ? <Eye size={15} /> : <EyeOff size={15} />}{" "}
              {k}
            </label>
          ))}
          <h3>Rendering</h3>
          <label>
            Point size{" "}
            <input
              type="range"
              min="0.01"
              max="0.16"
              step="0.005"
              value={pointSize}
              onChange={(e) => setPointSize(Number(e.target.value))}
            />
          </label>
          <label>
            Z exaggeration{" "}
            <input
              type="range"
              min="0.2"
              max="1.4"
              step="0.05"
              value={zScale}
              onChange={(e) => setZScale(Number(e.target.value))}
            />
          </label>
          <label>
            Color by{" "}
            <select
              value={colorBy}
              onChange={(e) => setColorBy(e.target.value as any)}
            >
              <option value="depth">depth</option>
              <option value="benthic">benthic class</option>
              <option value="health">health class</option>
            </select>
          </label>
          <h3>Annotation Type</h3>
          <div className="segmentedControl">
            <button
              type="button"
              className={annotationShape === "point" ? "active" : ""}
              onClick={() => {
                setAnnotationShape("point");
                setSurfaceDraft([]);
              }}
            >
              Point
            </button>
            <button
              type="button"
              className={annotationShape === "surface" ? "active" : ""}
              onClick={() => {
                setAnnotationShape("surface");
                setPicked(null);
              }}
            >
              Surface area
            </button>
          </div>
          <small className="helperText">
            Surface area: click 3+ reef positions, then save the polygon.
          </small>
          <h3>Annotation Label</h3>
          <select
            value={selectedLabel}
            onChange={(e) => setSelectedLabel(e.target.value)}
          >
            {[...benthicClasses, ...healthClasses].map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
          <div className="legend">
            {[...benthicClasses, ...healthClasses].map((c) => (
              <span key={c}>
                <i style={{ background: labelColors[c] }} /> {c}
              </span>
            ))}
          </div>
        </aside>
        <div className="viewerCanvasWrap">
          {loading && (
            <div className="viewerOverlay">Loading processed 3D asset…</div>
          )}
          {error && <div className="viewerOverlay error">{error}</div>}
          {!dataset && (
            <div className="viewerOverlay">
              Generate or process a reef survey first.
            </div>
          )}
          <Canvas
            camera={{ position: [5, -1, 7], fov: 55 }}
            onPointerMissed={() => setSelectedAnnotation(null)}
          >
            {(points.length > 0 || glbScene) && (
              <ReefScene
                points={points}
                annotations={annotations}
                layers={layers}
                pointSize={pointSize}
                zScale={zScale}
                mode={mode}
                selectedLabel={selectedLabel}
                colorBy={colorBy}
                viewPreset={viewPreset}
                onPick={addAnnotationPick}
                onMeasure={onMeasure}
                onSelectAnnotation={setSelectedAnnotation}
                draftSurface={surfaceDraft}
                textureUrl={textureUrl}
                glbScene={glbScene}
                theme={theme}
              />
            )}
          </Canvas>
          <div className="viewerHud">
            <b>Controls</b>
            <span>
              Left drag rotate · right drag pan · wheel zoom · click mesh to
              inspect, annotate points, draw surface polygons, or measure
            </span>
            {picked && (
              <span>
                Picked: x {picked.x.toFixed(2)}, y {picked.y.toFixed(2)}, depth{" "}
                {picked.z.toFixed(2)}
              </span>
            )}
            {distance !== null && (
              <span>3D distance: {distance.toFixed(2)} model units</span>
            )}
          </div>
        </div>
        <aside className="viewerSidePanel right">
          <h3>Selection</h3>
          {mode === "annotate" && annotationShape === "surface" ? (
            <div className="infoBox">
              <b>New surface-area annotation</b>
              <span>{surfaceDraft.length} polygon vertices selected</span>
              <span>
                area {polygonPlanarArea(surfaceDraft).toFixed(3)} model²
              </span>
              {picked && (
                <>
                  <span>last x {picked.x.toFixed(3)}</span>
                  <span>last y {picked.y.toFixed(3)}</span>
                  <span>last depth {picked.z.toFixed(3)}</span>
                </>
              )}
              <button
                onClick={saveSurfaceAnnotation}
                disabled={surfaceDraft.length < 3}
              >
                Save {selectedLabel} surface area
              </button>
              <button
                onClick={undoSurfacePoint}
                disabled={!surfaceDraft.length}
              >
                Undo last vertex
              </button>
              <button
                onClick={clearSurfaceDraft}
                disabled={!surfaceDraft.length}
              >
                Clear surface
              </button>
            </div>
          ) : picked ? (
            <div className="infoBox">
              <b>
                {mode === "annotate" ? "New annotation point" : "Picked point"}
              </b>
              <span>x {picked.x.toFixed(3)}</span>
              <span>y {picked.y.toFixed(3)}</span>
              <span>depth {picked.z.toFixed(3)}</span>
              <span>class {picked.className}</span>
              {mode === "annotate" && (
                <button onClick={savePointAnnotation}>
                  Save {selectedLabel} point annotation
                </button>
              )}
            </div>
          ) : (
            <p>
              Click the reef surface to inspect a coordinate, save a point, or
              draw a surface-area polygon.
            </p>
          )}
          {selectedAnnotation && (
            <div className="infoBox selected">
              <b>{selectedAnnotation.label}</b>
              <span>{selectedAnnotation.annotation_type}</span>
              <span>
                {selectedAnnotation.annotation_type === "surface_area"
                  ? `${selectedAnnotation.properties_json?.vertex_count || selectedAnnotation.geometry_json?.coordinates?.length || 0} vertices`
                  : JSON.stringify(
                      selectedAnnotation.geometry_json?.coordinates,
                    )}
              </span>
              {selectedAnnotation.properties_json?.planar_area !==
                undefined && (
                <span>
                  area{" "}
                  {Number(
                    selectedAnnotation.properties_json.planar_area,
                  ).toFixed(3)}{" "}
                  model²
                </span>
              )}
              <button
                className="danger"
                onClick={() => deleteAnnotation(selectedAnnotation.id)}
              >
                <Trash2 size={15} />
                Delete
              </button>
            </div>
          )}
          <h3>Dataset Metrics</h3>
          <div className="metricGrid">
            <span>Rugosity</span>
            <b>{metrics.rugosity?.toFixed?.(3) || "n/a"}</b>
            <span>Surface area</span>
            <b>{metrics.surface_area?.toFixed?.(1) || "n/a"}</b>
            <span>Planar area</span>
            <b>{metrics.planar_area?.toFixed?.(1) || "n/a"}</b>
          </div>
          <AssetBrowser datasetId={dataset?.id} />
          <h3>Annotations</h3>
          <div className="annotationList">
            {annotations.map((a) => (
              <button key={a.id} onClick={() => setSelectedAnnotation(a)}>
                <i style={{ background: labelColors[a.label] || "#fff" }} />{" "}
                {a.label}
                <small>{a.annotation_type}</small>
              </button>
            ))}
          </div>
        </aside>
      </div>
    </div>
  );
}

type TableColumn<T> = {
  key: string;
  label: string;
  render?: (row: T) => React.ReactNode;
  className?: string;
};

type InteractiveTableProps = {
  title: string;
  subtitle: string;
  data: Dataset[];
  type: "raw" | "processed" | "archiveRaw" | "archiveProcessed";
  selectedId?: string;
  onSelect?: (d: Dataset) => void;
  onOpen?: (d: Dataset) => void;
  onProcess?: (d: Dataset) => void;
};

function statusClass(status?: string) {
  const s = (status || "unknown").toLowerCase();
  if (s.includes("complete") || s.includes("processed")) return "ok";
  if (s.includes("fail")) return "bad";
  if (s.includes("processing") || s.includes("queued")) return "run";
  return "idle";
}
function formatDate(v?: string) {
  if (!v) return "not set";
  const d = new Date(v);
  return Number.isNaN(d.getTime())
    ? v
    : d.toLocaleDateString(undefined, {
        year: "numeric",
        month: "short",
        day: "2-digit",
      });
}
function surveyCode(d: Dataset, i = 0) {
  return d.name?.includes("Reef Survey")
    ? d.name
    : `Reef Survey ${String(i + 1).padStart(3, "0")}`;
}
function datasetFacts(d: Dataset) {
  const m = d.metrics || {};
  return [
    ["Survey ID", d.id],
    ["Location", d.location || "Unassigned reef/location"],
    ["Survey date", formatDate(d.survey_date)],
    ["Status", d.status || d.processing_version || "registered"],
    ["Files", String(d.file_count ?? 0)],
    ["Processing version", d.processing_version || "not processed"],
    ["Rugosity", m.rugosity?.toFixed?.(3) || "n/a"],
    ["Surface area", m.surface_area?.toFixed?.(1) || "n/a"],
    ["Planar area", m.planar_area?.toFixed?.(1) || "n/a"],
  ];
}

function InteractiveSurveyTable({
  title,
  subtitle,
  data,
  type,
  selectedId,
  onSelect,
  onOpen,
  onProcess,
}: InteractiveTableProps) {
  const [expanded, setExpanded] = useState<string | undefined>();
  const [query, setQuery] = useState("");
  const [isTableVisible, setIsTableVisible] = useState(true);
  const [sort, setSort] = useState<"newest" | "name" | "status" | "files">(
    "newest",
  );
  useEffect(() => {
    if (data.length && !expanded) setExpanded(undefined);
  }, [data.length, expanded]);
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const rows = data.filter(
      (d, i) =>
        !q ||
        `${surveyCode(d, i)} ${d.status} ${d.location} ${d.processing_version}`
          .toLowerCase()
          .includes(q),
    );
    return rows.sort((a, b) => {
      if (sort === "name") return (a.name || "").localeCompare(b.name || "");
      if (sort === "status")
        return (a.status || a.processing_version || "").localeCompare(
          b.status || b.processing_version || "",
        );
      if (sort === "files") return (b.file_count || 0) - (a.file_count || 0);
      return (
        new Date(b.survey_date || 0).getTime() -
        new Date(a.survey_date || 0).getTime()
      );
    });
  }, [data, query, sort]);
  const emptyText =
    type === "raw"
      ? "No raw reef surveys yet. Generate a survey or upload files first."
      : type === "processed"
        ? "No processed surveys yet. Start a processing job from Raw Data Processing."
        : "No archive entries yet.";
  return (
    <div className="tableCard">
      <div className="tableHeader">
        <div>
          <h2>{title}</h2>
          <p>{subtitle}</p>
        </div>

        <div className="tableTools">
          <button
            type="button"
            className="tableToggleButton"
            onClick={() => setIsTableVisible((v) => !v)}
          >
            {isTableVisible ? <EyeOff size={15} /> : <Eye size={15} />}
            {isTableVisible ? "Hide table" : "Show table"}
          </button>

          {isTableVisible && (
            <>
              <label>
                <Search size={15} />
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search Reef Survey XYZ…"
                />
              </label>

              <select
                value={sort}
                onChange={(e) => setSort(e.target.value as any)}
              >
                <option value="newest">Newest survey date</option>
                <option value="name">Survey name</option>
                <option value="status">Status</option>
                <option value="files">File count</option>
              </select>
            </>
          )}
        </div>
      </div>
      {isTableVisible && (
        <div className="surveyTableWrap">
          <table className="surveyTable">
            <thead>
              <tr>
                <th></th>
                <th>Survey</th>
                <th>Location</th>
                <th>Date</th>
                <th>Status</th>
                <th>Files</th>
                <th>Version</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((d, i) => {
                const isOpen = expanded === d.id;
                const isSelected = selectedId === d.id;
                const display = surveyCode(d, i);
                return (
                  <React.Fragment key={d.id}>
                    <tr
                      className={`${isOpen ? "expanded" : ""} ${isSelected ? "selected" : ""}`}
                      onClick={() => {
                        setExpanded(isOpen ? undefined : d.id);
                        onSelect?.(d);
                      }}
                    >
                      <td className="expander">
                        {isOpen ? (
                          <ChevronDown size={16} />
                        ) : (
                          <ChevronRight size={16} />
                        )}
                      </td>
                      <td>
                        <b>{display}</b>
                        <small>
                          {d.id.slice(0, 8)} ·{" "}
                          {type.includes("Processed") || type === "processed"
                            ? "processed model"
                            : "raw acquisition"}
                        </small>
                      </td>
                      <td>
                        <MapPin size={14} />
                        {d.location || "Unknown reef"}
                      </td>
                      <td>
                        <CalendarDays size={14} />
                        {formatDate(d.survey_date)}
                      </td>
                      <td>
                        <span
                          className={`pill ${statusClass(d.status || d.processing_version)}`}
                        >
                          {d.status || d.processing_version || "registered"}
                        </span>
                      </td>
                      <td>{d.file_count ?? 0}</td>
                      <td>{d.processing_version || "—"}</td>
                      <td className="rowActions">
                        {onOpen && (
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              onOpen(d);
                            }}
                          >
                            <FolderOpen size={14} />
                            Open
                          </button>
                        )}
                        {onProcess && (
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              onProcess(d);
                            }}
                          >
                            <Play size={14} />
                            Process
                          </button>
                        )}
                      </td>
                    </tr>
                    {isOpen && (
                      <tr className="detailsRow">
                        <td colSpan={8}>
                          <div className="detailsPanel">
                            <div className="detailsGrid">
                              {datasetFacts(d).map(([k, v]) => (
                                <div key={k} className="fact">
                                  <span>{k}</span>
                                  <b>{v}</b>
                                </div>
                              ))}
                            </div>
                            <div className="detailNarrative">
                              <h3>{display} details</h3>
                              <p>
                                This survey row represents one complete reef
                                acquisition package. Open it to inspect assets,
                                start processing, or jump to the 3D viewer
                                depending on the current tab.
                              </p>
                              <div className="detailBadges">
                                <span>
                                  <FileText size={14} /> images/video/sonar
                                  metadata placeholder
                                </span>
                                <span>
                                  <Activity size={14} /> rugosity + class layers
                                  ready after processing
                                </span>
                                <span>
                                  {statusClass(d.status) === "ok" ? (
                                    <CheckCircle2 size={14} />
                                  ) : (
                                    <AlertTriangle size={14} />
                                  )}{" "}
                                  expandable survey details
                                </span>
                              </div>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
          {!filtered.length && <div className="emptyState">{emptyText}</div>}
        </div>
      )}
    </div>
  );
}

export function App() {
  const [theme, setTheme] = useState<Theme>(readStoredTheme);
  const [tab, setTab] = useState(tabs[0]);
  const [surveyOpened, setSurveyOpened] = useState(false);
  const [raw, setRaw] = useState<Dataset[]>([]);
  const [proc, setProc] = useState<Dataset[]>([]);
  const [selected, setSelected] = useState<Dataset | undefined>();
  const [job, setJob] = useState<any>();
  const refresh = () => {
    getJson("/api/datasets/raw").then(setRaw);
    getJson("/api/datasets/processed").then((d) => {
      setProc(d);
      setSelected(current => current || d[0]);
    });
  };
  useEffect(refresh, []);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      window.localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* localStorage unavailable — theme still applies for this session */
    }
  }, [theme]);
  useEffect(() => {
    if (job?.job_id || job?.id) {
      const id = job.job_id || job.id;
      const t = setInterval(
        () => getJson(`/api/jobs/${id}`).then(setJob).then(refresh),
        1000,
      );
      return () => clearInterval(t);
    }
  }, [job?.job_id, job?.id]);
  return (
    <ThemeContext.Provider value={theme}>
      <main>
        <header>
          <div>
            <h1>
              <Waves /> ReefFusion Platform
            </h1>
            <p>
              Integrated workspace for sonar bathymetry, downward-facing
              imagery, GPS metadata, AI-assisted reconstruction and temporal
              reef comparison.
            </p>
          </div>
          <div className="headerActions">
            <button
              aria-label="Toggle theme"
              aria-pressed={theme === "light"}
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            >
              {theme === "dark" ? <Moon /> : <Sun />}
              {theme === "dark" ? "Dark mode" : "Light mode"}
            </button>
            <button
              onClick={() =>
                postJson("/api/datasets/survey/generate").then(refresh)
              }
            >
              Generate Reef Survey
            </button>
          </div>
        </header>
        <nav>
          {tabs.map((t, i) => (
            <button
              className={tab === t ? "active" : ""}
              onClick={() => { setTab(t); if (t === "Live Survey") setSurveyOpened(true); }}
              key={t}
            >
              {
                [
                  <Upload />,
                  <Database />,
                  <Play />,
                  <Waves />,
                  <Brain />,
                  <Tags />,
                  <MapPin />,
                ][i]
              }
              {t}
            </button>
          ))}
        </nav>
        <section className="card">
          {surveyOpened && <div hidden={tab !== "Live Survey"}>
            <LiveSurvey visible={tab === "Live Survey"} refresh={refresh} openArea={async (ids) => {
              const result = await postJson('/api/survey/combined-area', {dataset_ids:ids});
              const dataset = await getJson(`/api/datasets/processed/${result.dataset_id}`);
              setSelected(dataset);
              setTab("Processed Data Viewer");
              refresh();
            }} openProcessed={async (id) => {
              const dataset = await getJson(`/api/datasets/processed/${id}`);
              setSelected(dataset);
              setTab("Processed Data Viewer");
              refresh();
            }} />
          </div>}
          {tab === "Raw Data Upload" && <UploadTab refresh={refresh} />}{" "}
          {tab === "Raw Data Viewer" && <RawViewer raw={raw} />}{" "}
          {tab === "Raw Data Processing" && (
            <Processing raw={raw} job={job} setJob={setJob} />
          )}{" "}
          {tab === "Processed Data Viewer" && (
            <>
              <div className="survey-controls">
                <button onClick={() => { setSurveyOpened(true); setTab("Live Survey"); }}>Back to survey map</button>
                <button onClick={() => setTab("Data Archive")}>Browse other datasets</button>
              </div>
              <ProfessionalViewer dataset={selected || proc[0]} />
            </>
          )}{" "}
          {tab === "Data Archive" && (
            <Archive
              raw={raw}
              proc={proc}
              open={(d: Dataset) => {
                  setSelected(d);
                setTab("Processed Data Viewer");
              }}
              openRaw={(d: Dataset) => {
                setSelected(d);
                setTab("Raw Data Viewer");
              }}
            />
          )}{" "}
          {tab === "AI-Agents" && <AiAgents proc={proc} />}
        </section>
      </main>
    </ThemeContext.Provider>
  );
}
function UploadTab({ refresh }: any) {
  const [msg, setMsg] = useState("");
  const [uploading, setUploading] = useState(false);
  const [metadata, setMetadata] = useState<Record<string, string>>({
    survey_name: "",
    location_name: "",
    latitude: "",
    longitude: "",
    acquisition_started_at: "",
    acquisition_ended_at: "",
    camera_model: "",
    sonar_model: "",
    gps_model: "",
    platform_name: "",
    crs: "",
    vertical_datum: "",
  });
  const setField = (key: string, value: string) =>
    setMetadata((prev) => ({ ...prev, [key]: value }));
  const handleUpload = async (files: FileList | null) => {
    if (!files) return;
    setUploading(true);
    setMsg("");
    try {
      const r = await uploadFiles(files, metadata);
      setMsg(
        `Uploaded ${r.file_count} files as ${r.name}${r.warnings?.length ? ` · ${r.warnings.join(" · ")}` : ""}`,
      );
      refresh();
    } catch (e: any) {
      setMsg(String(e.message || e));
    } finally {
      setUploading(false);
    }
  };
  return (
    <>
      <h2>Raw Data Upload</h2>
      <p>
        Accepts jpg/png, mp4/mov,
        csv/xyz/las/laz/geojson/tif/netcdf-placeholder, gpx/json metadata.
      </p>
      <div className="uploadMetadataGrid">
        <label>
          Survey name
          <input
            value={metadata.survey_name}
            onChange={(e) => setField("survey_name", e.target.value)}
          />
        </label>
        <label>
          Location name
          <input
            value={metadata.location_name}
            onChange={(e) => setField("location_name", e.target.value)}
          />
        </label>
        <label>
          Latitude
          <input
            type="number"
            step="any"
            value={metadata.latitude}
            onChange={(e) => setField("latitude", e.target.value)}
          />
        </label>
        <label>
          Longitude
          <input
            type="number"
            step="any"
            value={metadata.longitude}
            onChange={(e) => setField("longitude", e.target.value)}
          />
        </label>
        <label>
          Acquisition start
          <input
            type="datetime-local"
            value={metadata.acquisition_started_at}
            onChange={(e) => setField("acquisition_started_at", e.target.value)}
          />
        </label>
        <label>
          Acquisition end
          <input
            type="datetime-local"
            value={metadata.acquisition_ended_at}
            onChange={(e) => setField("acquisition_ended_at", e.target.value)}
          />
        </label>
        <label>
          Camera model
          <input
            value={metadata.camera_model}
            onChange={(e) => setField("camera_model", e.target.value)}
          />
        </label>
        <label>
          Sonar model
          <input
            value={metadata.sonar_model}
            onChange={(e) => setField("sonar_model", e.target.value)}
          />
        </label>
        <label>
          GPS model
          <input
            value={metadata.gps_model}
            onChange={(e) => setField("gps_model", e.target.value)}
          />
        </label>
        <label>
          Platform
          <input
            value={metadata.platform_name}
            onChange={(e) => setField("platform_name", e.target.value)}
          />
        </label>
        <label>
          CRS
          <input
            value={metadata.crs}
            onChange={(e) => setField("crs", e.target.value)}
          />
        </label>
        <label>
          Vertical datum
          <input
            value={metadata.vertical_datum}
            onChange={(e) => setField("vertical_datum", e.target.value)}
          />
        </label>
      </div>
      <input
        type="file"
        multiple
        disabled={uploading}
        onChange={(e) => handleUpload(e.target.files)}
      />
      <p>{msg}</p>
    </>
  );
}
function RawViewer({ raw }: any) {
  const [selected, setSelected] = useState<Dataset | undefined>();
  return (
    <>
      <InteractiveSurveyTable
        title="Raw Data Viewer"
        subtitle="Structured raw survey table. Click a Reef Survey row to expand uploaded assets, survey metadata, coordinates and acquisition status."
        data={raw}
        type="raw"
        selectedId={selected?.id}
        onSelect={setSelected}
      />
      {selected && (
        <div className="assetPreview">
          <h3>Selected raw survey preview</h3>
          <p>
            <b>{selected.name}</b> contains {selected.file_count ?? 0}{" "}
            registered raw files. Detailed per-file preview is available from
            GET /api/datasets/raw/{selected.id} and is ready for images, video,
            bathymetry grids, GPS tracks and metadata tables.
          </p>
        </div>
      )}
    </>
  );
}
function Processing({ raw, job, setJob }: any) {
  const [selected, setSelected] = useState<Dataset | undefined>();
  const start = (d: Dataset) => {
    setSelected(d);
    postJson(`/api/jobs/process/${d.id}`).then(setJob);
  };
  const pipelineSteps = [
    ["queued", "Queued"],
    ["extracting video frames", "Extract Frames"],
    ["validating sonar / GPS / image metadata", "Validate Metadata"],
    ["running image quality assessment", "Image QA"],
    ["AI coral image segmentation", "AI Segmentation"],
    ["AI benthic cover classification", "Benthic Classifier"],
    ["AI coral health classification", "Health Classifier"],
    ["building bathymetry-derived point cloud", "Point Cloud"],
    [
      "fusing sonar bathymetry with image-derived features",
      "Sonar/Image Fusion",
    ],
    ["building textured 3D reef mesh", "Textured Mesh"],
    [
      "projecting AI segmentation masks onto 3D model",
      "3D AI Layer Projection",
    ],
    ["computing rugosity and habitat metrics", "Habitat Metrics"],
    ["generating AI-ready viewer layers", "AI Viewer Layers"],
    ["completed", "Completed"],
  ];
  const stepDetails = Array.isArray(job?.step_details) ? job.step_details : [];
  const detailByName = new Map<string, any>(
    stepDetails.map((s: any) => [s.name, s]),
  );
  const warningText = (detail: any) => {
    const warnings =
      detail?.output?.dataset_metadata?.warnings ||
      detail?.output?.warnings ||
      detail?.output?.quality_report?.warnings ||
      [];
    return Array.isArray(warnings) ? warnings.join(" · ") : "";
  };
  return (
    <>
      <InteractiveSurveyTable
        title="Raw Data Processing"
        subtitle="Choose one Reef Survey row, expand its metadata, then start the hybrid AI-assisted processing pipeline for that survey."
        data={raw}
        type="raw"
        selectedId={selected?.id}
        onSelect={setSelected}
        onProcess={start}
      />
      <div className="pipelinePanel">
        <h3>
          {selected
            ? `Pipeline for ${selected.name}`
            : "AI-assisted processing pipeline"}
        </h3>
        <div className="timeline">
          {pipelineSteps.map(([step, label]) => {
            const detail = detailByName.get(step);
            const warnings = warningText(detail);
            return (
              <span
                key={step}
                title={detail?.error || warnings || ""}
                className={`${job?.steps?.includes(step) || job?.current_step === step ? "done" : ""} ${detail?.error ? "failed" : ""} ${warnings ? "warning" : ""} ${step.startsWith("AI") || step.includes("image quality") || step.includes("projecting AI") || step.includes("AI-ready") ? "aiStage" : ""}`}
              >
                {label}
                {detail?.error && <AlertTriangle size={13} />}
                {!detail?.error && warnings && <AlertTriangle size={13} />}
              </span>
            );
          })}
        </div>
        <h3>
          {job
            ? `${job.current_step} ${job.progress}%`
            : "Select a row and click Process to start"}
        </h3>
        {job?.error && <p className="errorText">{job.error}</p>}
        {!!stepDetails.length && (
          <div className="stepDetails">
            {stepDetails.map((step: any, i: number) => (
              <div key={`${step.name}-${i}`} className={`stepDetail ${step.status}`}>
                <b>{step.name}</b>
                <span>{step.status} · {step.progress}%</span>
                {warningText(step) && <small>{warningText(step)}</small>}
                {step.error && <small className="errorText">{step.error}</small>}
              </div>
            ))}
          </div>
        )}
        <div className="aiExplain">
          <h3>AI-assisted 3D Reef Reconstruction</h3>
          <p>
            The processing pipeline combines traditional SfM / mesh generation
            with AI stages for coral image segmentation, benthic classification
            and coral health assessment. These stages are modular and can be
            connected to trained segmentation and classification services.
          </p>
          <p>
            <b>AI processing:</b> model services create 3D viewer layers and
            coral-health metrics while keeping the local runtime lightweight.
          </p>
        </div>
      </div>
    </>
  );
}
function DatasetPicker({ data, setSelected }: any) {
  return (
    <InteractiveSurveyTable
      title="Processed survey selector"
      subtitle="Click a processed Reef Survey row to load it into the 3D viewer."
      data={data}
      type="processed"
      onSelect={setSelected}
      onOpen={setSelected}
    />
  );
}

function MetricBars({
  title,
  values,
}: {
  title: string;
  values: Record<string, number>;
}) {
  const entries = Object.entries(values || {});
  return (
    <div className="reportChartCard">
      <h4>{title}</h4>
      <div className="metricBars">
        {entries.map(([label, value]) => (
          <div className="metricBarRow" key={label}>
            <span>{label}</span>
            <div className="metricBarTrack">
              <div
                className="metricBarFill"
                style={{ width: `${Math.max(0, Math.min(100, value))}%` }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function RugosityGauge({ value }: { value: number }) {
  const normalized = Math.max(0, Math.min(100, (value - 1) * 1000));
  return (
    <div className="rugosityGauge">
      <div className="gaugeTrack">
        <div className="gaugeNeedle" style={{ left: `${normalized}%` }} />
      </div>
      <small>Low complexity</small>
      <small>High complexity</small>
    </div>
  );
}

function TemporalChangeChart({ values }: { values: any }) {
  const cover = values?.coral_cover_change || {};
  return (
    <div className="temporalChart">
      {Object.entries(cover).map(([label, value]: any) => {
        const width = Math.min(100, Math.abs(Number(value || 0)) * 8);
        return (
          <div className="temporalRow" key={label}>
            <span>{label}</span>
            <div className="temporalTrack">
              <div
                className={Number(value) >= 0 ? "positive" : "negative"}
                style={{ width: `${width}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
function csvEscape(value: any) {
  const s = String(value ?? "");
  return `"${s.replace(/"/g, '""')}"`;
}

function downloadFile(filename: string, content: string, mimeType: string) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename.replace(/ /g, "_").toLowerCase();
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
function AiAgents({ proc }: any) {
  const [models, setModels] = useState<any[]>([]);
  const [activeSubTab, setActiveSubTab] = useState("Available AI agents");
  const [primary, setPrimary] = useState<string>("");
  const [comparison, setComparison] = useState<string>("");
  const [report, setReport] = useState<any>();
  const [question, setQuestion] = useState("How healthy is this reef?");
  const [answer, setAnswer] = useState<any>();
  const [compareResult, setCompareResult] = useState<any>();
  const [classification, setClassification] = useState<any>();

  useEffect(() => {
    getJson("/api/ml/models").then(setModels);
  }, []);

  useEffect(() => {
    if (proc.length && !primary) setPrimary(proc[0].id);
  }, [proc.length, primary]);

  useEffect(() => {
    if (!primary) {
      setClassification(undefined);
      return;
    }
    getJson(`/api/ml/classify/${primary}`).then(setClassification).catch(() => setClassification(undefined));
  }, [primary]);

  const selected = proc.find((d: Dataset) => d.id === primary);
  const comparisonDataset = proc.find((d: Dataset) => d.id === comparison);

  const subTabs = [
    "Available AI agents",
    "Run Temporal Change Agent",

    "Ask AI Agent",
    "Generate AI Reef Report",
  ];

  const agents = [
    [
      "Reef Health Analyst Agent",
      "Summarizes coral health, bleaching and disease-like signals",
      "metrics_json.health + AI health classifier",
      "risk / health summary",
    ],
    [
      "Coral Coverage Agent",
      "Explains benthic cover: coral, rock, sand and algae",
      "metrics_json.cover + segmentation layers",
      "cover overview",
    ],
    [
      "Temporal Change Agent",
      "Compares two processed reef surveys over time",
      "two processed datasets",
      "change metrics",
    ],
    [
      "Data QA Agent",
      "Checks whether data quality is sufficient for scientific review",
      "image QA + metadata",
      "quality notes",
    ],

    [
      "Scientific Report Agent",
      "Generates a structured reef-health report",
      "processed metrics + optional comparison",
      "AI reef report",
    ],
  ];

  const generateReport = () =>
    postJson("/api/ai-agents/report", {
      dataset_id: primary,
      comparison_dataset_id: comparison || null,
    }).then(setReport);

  const ask = () =>
    postJson("/api/ai-agents/question", {
      dataset_id: primary,
      question,
      comparison_dataset_id: comparison || null,
    }).then(setAnswer);

  const runCompare = () =>
    comparison &&
    postJson("/api/comparison", {
      dataset_a_id: comparison,
      dataset_b_id: primary,
    }).then(setCompareResult);

  const tabIcon = (name: string) => {
    if (name === "Generate AI Reef Report") return <FileText size={16} />;
    if (name === "Ask AI Agent") return <Brain size={16} />;
    if (name === "Run Temporal Change Agent") return <GitCompare size={16} />;
    return <Database size={16} />;
  };
  const reportRef = useRef<HTMLDivElement | null>(null);

  const exportJson = () => {
    const payload = {
      dataset: selected,
      baseline: comparisonDataset || null,
      report,
      comparison: compareResult?.metrics || null,
      exported_at: new Date().toISOString(),
    };
    downloadFile(
      `reef-report-${selected?.name || "dataset"}.json`,
      JSON.stringify(payload, null, 2),
      "application/json",
    );
  };

  const exportCsv = () => {
    const rows = [
      ["section", "metric", "value"],
      ...Object.entries(selected?.metrics?.cover || {}).map(([k, v]) => [
        "benthic_cover",
        k,
        String(v),
      ]),
      ...Object.entries(selected?.metrics?.health || {}).map(([k, v]) => [
        "reef_health",
        k,
        String(v),
      ]),
      ["rugosity", "rugosity", String(selected?.metrics?.rugosity || "")],
    ];

    downloadFile(
      `reef-report-${selected?.name || "dataset"}.csv`,
      rows.map((r) => r.map(csvEscape).join(",")).join("\n"),
      "text/csv",
    );
  };

  const exportPdf = () => {
    window.print();
  };

  return (
    <div className="agentsDashboard">
      <div className="agentsHero">
        <div>
          <span className="eyebrow">AI reef intelligence workspace</span>
          <h2>AI-Agents</h2>
          <p>
            Generate reef-health reports, ask dataset questions and compare
            processed reef surveys using lightweight metric-driven agents.
          </p>
        </div>

        <div className="agentHeroStats">
          <div>
            <b>{proc.length}</b>
            <span>Processed datasets</span>
          </div>
          <div>
            <b>{models.length}</b>
            <span>Model endpoints</span>
          </div>
          <div>
            <b>{agents.length}</b>
            <span>AI agents</span>
          </div>
        </div>
      </div>

      <div className="agentWorkspaceGrid">
        <aside className="agentContextPanel">
          <h3>Dataset context</h3>

          <label>
            Primary processed dataset
            <select
              value={primary}
              onChange={(e) => setPrimary(e.target.value)}
            >
              {proc.map((d: Dataset) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
          </label>

          <label>
            Temporal comparison baseline
            <select
              value={comparison}
              onChange={(e) => setComparison(e.target.value)}
            >
              <option value="">No comparison</option>
              {proc
                .filter((d: Dataset) => d.id !== primary)
                .map((d: Dataset) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
            </select>
          </label>

          {selected && (
            <div className="agentDatasetCard">
              <span>Selected dataset</span>
              <b>{selected.name}</b>
              <div className="agentMetricStrip">
                <small>
                  Coral{" "}
                  {(selected.metrics?.cover?.coral ?? 0).toFixed?.(1) || 0}%
                </small>
                <small>
                  Healthy{" "}
                  {(selected.metrics?.health?.healthy ?? 0).toFixed?.(1) || 0}%
                </small>
                <small>
                  Rugosity {selected.metrics?.rugosity?.toFixed?.(3) || "n/a"}
                </small>
              </div>
              {comparisonDataset && (
                <small className="baselineText">
                  Baseline: {comparisonDataset.name}
                </small>
              )}
            </div>
          )}
        </aside>

        <section className="agentMainPanel">
          <div
            className="agentToggleTabs"
            role="tablist"
            aria-label="AI Agent workflow tabs"
          >
            {subTabs.map((name, index) => (
              <button
                key={name}
                type="button"
                role="tab"
                aria-selected={activeSubTab === name}
                className={activeSubTab === name ? "active" : ""}
                onClick={() => setActiveSubTab(name)}
              >
                <div className="tabIndexBadge">
                  {String(index + 1).padStart(2, "0")}
                </div>
                {tabIcon(name)}
                <span>{name}</span>
              </button>
            ))}
          </div>

          {activeSubTab === "Available AI agents" && (
            <div className="agentTabPanel">
              <div className="agentSectionHeader">
                <h3>Available AI agents</h3>
                <span>
                  {agents.length} active agents connected to processed metrics
                </span>
              </div>

              <div className="agentCardsGrid">
                {agents.map(([name, purpose, input, output]) => (
                  <div className="agentCapabilityCard" key={name}>
                    <div className="agentCardIcon">
                      <Brain size={18} />
                    </div>
                    <b>{name}</b>
                    <p>{purpose}</p>
                    <small>Input: {input}</small>
                    <small>Output: {output}</small>
                  </div>
                ))}
              </div>

              {classification && (
                <>
                  <div className="agentSectionHeader">
                    <h3>Current classification</h3>
                    <span>{classification.model_version}</span>
                  </div>
                  <div className="classificationGrid">
                    <MetricBars
                      title="Benthic cover"
                      values={classification.benthic_cover || {}}
                    />
                    <MetricBars
                      title="Coral health"
                      values={classification.health || {}}
                    />
                  </div>
                </>
              )}

              <div className="agentSectionHeader">
                <h3>Model registry</h3>
                <span>{models.length} registered model endpoints</span>
              </div>

              <div className="modelRegistryGrid">
                {models.map((m) => (
                  <div className="modelRegistryCard" key={m.id}>
                    <b>{m.name}</b>
                    <span>{m.task}</span>
                    <small>
                      {String(m.version || "").replace(/-|AI-/gi, "")}
                    </small>
                  </div>
                ))}
              </div>
            </div>
          )}

          {activeSubTab === "Generate AI Reef Report" && (
            <section className="agentTabPanel reportPanel">
              <div className="agentPanelHeader">
                <div>
                  <h3>Generate AI Reef Report</h3>
                  <p>
                    Create a structured reef-health dashboard from benthic
                    cover, coral health, rugosity and optional temporal
                    comparison.
                  </p>
                </div>
                <button disabled={!primary} onClick={generateReport}>
                  <FileText size={16} /> Generate Report
                </button>
              </div>

              {report && selected && (
                <article ref={reportRef} className="scientificReport">
                  <header className="scientificReportHeader">
                    <div>
                      <span className="reportLabel">
                        AI-assisted reef report
                      </span>
                      <h2>{selected.name}</h2>
                      <p>
                        Automated reef-health interpretation based on processed
                        survey metrics, benthic cover classes, coral health
                        classes and habitat complexity.
                      </p>
                    </div>

                    <div className="reportExportActions noPrint">
                      <button onClick={exportPdf}>
                        <FileText size={16} /> Export PDF
                      </button>
                      <button onClick={exportCsv}>Export CSV</button>
                      <button onClick={exportJson}>Export JSON</button>
                    </div>
                  </header>

                  <section className="reportMetadataGrid">
                    <div>
                      <span>Dataset</span>
                      <b>{selected.name}</b>
                    </div>
                    <div>
                      <span>Processing version</span>
                      <b>{selected.processing_version || "n/a"}</b>
                    </div>
                    <div>
                      <span>Location</span>
                      <b>{selected.location || "n/a"}</b>
                    </div>
                    <div>
                      <span>Generated</span>
                      <b>{new Date().toLocaleString()}</b>
                    </div>
                    <div>
                      <span>Temporal baseline</span>
                      <b>{comparisonDataset?.name || "Not selected"}</b>
                    </div>
                  </section>

                  <section className="scientificSection">
                    <h3>1. Executive summary</h3>
                    <p>{report.report.executive_summary}</p>
                  </section>

                  <section className="scientificSection">
                    <h3>2. Methods and data basis</h3>
                    <p>
                      The report uses processed ReefFusion outputs including
                      benthic cover classification, coral-health classes,
                      rugosity metrics and optional temporal comparison. The
                      analysis is generated from processed survey metrics and
                      should be validated by reef scientists before operational
                      use.
                    </p>
                  </section>

                  <section className="scientificFigureGrid">
                    <MetricBars
                      title="Figure 1 · Benthic cover composition"
                      values={selected.metrics?.cover || {}}
                    />
                    <MetricBars
                      title="Figure 2 · Coral health classification"
                      values={selected.metrics?.health || {}}
                    />
                  </section>

                  <section className="scientificSection">
                    <h3>3. Habitat complexity</h3>
                    <p>{report.report.rugosity_and_habitat}</p>
                    <RugosityGauge value={selected.metrics?.rugosity || 0} />
                  </section>

                  {comparison && (
                    <section className="scientificSection">
                      <h3>4. Temporal change analysis</h3>
                      <TemporalChangeChart
                        values={
                          compareResult?.metrics ||
                          report.report.temporal_change ||
                          {}
                        }
                      />
                    </section>
                  )}

                  <section className="scientificSection">
                    <h3>5. Risk indicators</h3>
                    <ul>
                      {(report.report.risk_indicators || []).map(
                        (x: any, i: number) => (
                          <li key={i}>{String(x)}</li>
                        ),
                      )}
                    </ul>
                  </section>

                  <section className="scientificSection">
                    <h3>6. Data quality notes</h3>
                    <ul>
                      {(report.report.data_quality_notes || []).map(
                        (x: any, i: number) => (
                          <li key={i}>{String(x)}</li>
                        ),
                      )}
                    </ul>
                  </section>

                  <section className="scientificSection limitationsSection">
                    <h3>7. Limitations</h3>
                    <p>{report.report.limitations}</p>
                  </section>
                </article>
              )}
            </section>
          )}

          {activeSubTab === "Ask AI Agent" && (
            <section className="agentTabPanel qaPanel">
              <div className="agentPanelHeader">
                <div>
                  <h3>Ask AI Agent</h3>
                  <p>
                    Ask metric-based questions about reef condition, risks and
                    data quality.
                  </p>
                </div>
              </div>

              <div className="qaInput">
                <input
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  placeholder="How healthy is this reef?"
                />
                <button disabled={!primary || !question.trim()} onClick={ask}>
                  <Brain size={16} /> Ask
                </button>
              </div>

              <div className="exampleQs">
                <span>Examples:</span>
                {[
                  "How healthy is this reef?",
                  "Which area shows signs of bleaching?",
                  "Has coral cover increased or decreased?",
                  "What are the main risks in this survey?",
                  "Is this dataset good enough for scientific analysis?",
                ].map((q) => (
                  <button key={q} onClick={() => setQuestion(q)}>
                    {q}
                  </button>
                ))}
              </div>

              {answer && (
                <div className="answerBox">
                  <b>{answer.agent}</b>
                  <p>{answer.answer}</p>
                  <pre>{JSON.stringify(answer.evidence, null, 2)}</pre>
                  <small>{answer.disclaimer}</small>
                </div>
              )}
            </section>
          )}

          {activeSubTab === "Run Temporal Change Agent" && (
            <section className="agentTabPanel">
              <div className="agentPanelHeader">
                <div>
                  <h3>Temporal Change Agent</h3>
                  <p>
                    Compare the selected survey against the baseline dataset.
                  </p>
                </div>
                <button disabled={!comparison} onClick={runCompare}>
                  <GitCompare size={16} /> Run Comparison
                </button>
              </div>

              {!comparison && (
                <div className="emptyState">
                  Select a temporal comparison baseline in the dataset context
                  panel.
                </div>
              )}

              {compareResult && (
                <div className="reportSection">
                  <TemporalChangeChart values={compareResult.metrics} />
                  <pre>{JSON.stringify(compareResult.metrics, null, 2)}</pre>
                </div>
              )}
            </section>
          )}
        </section>
      </div>

      <p className="disclaimer">
        <AlertTriangle size={16} /> Generated insights are automated summaries
        based on processed survey metrics and should be reviewed by a reef
        scientist.
      </p>
    </div>
  );
}

function Archive({ raw, proc, open, openRaw }: any) {
  return (
    <>
      <h2>Data Archive</h2>
      <p>
        Archive rows are grouped by lifecycle state. Click any Reef Survey row
        to expand details, then use Open to navigate to the matching viewer.
      </p>
      <InteractiveSurveyTable
        title="Raw Survey Archive"
        subtitle="Uploaded and generated raw acquisition packages."
        data={raw}
        type="archiveRaw"
        onSelect={() => {}}
        onOpen={openRaw}
      />
      <InteractiveSurveyTable
        title="Processed Survey Archive"
        subtitle="Processed mesh, point-cloud and viewer-ready reef model outputs."
        data={proc}
        type="archiveProcessed"
        onSelect={() => {}}
        onOpen={open}
      />
    </>
  );
}
const rootElement = document.getElementById("root");
if (rootElement) createRoot(rootElement).render(<App />);
