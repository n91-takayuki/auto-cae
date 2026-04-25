# Auto-CAE ワークフロー詳細

このドキュメントは、現状の実装構造を新規開発のベースとして参照するための仕様まとめです。コードからは読み取りにくい設計判断・プロセス境界・データの受け渡しを明示します。

---

## 1. システム俯瞰

```
[Browser: React + R3F]
      │
      │  REST + WebSocket
      ▼
[FastAPI process (uvicorn)]
      ├─ projects router        (STEP アップロード, 面別ジオメトリ取得)
      ├─ jobs router            (ジョブ投入・状態・結果・CSV/INP 配信)
      ├─ jobs_ws (WebSocket)    (進捗ストリーム 250ms ポーリング)
      ├─ state (in-memory)      (Project / Job 辞書)
      └─ pipeline.run_job()     (BackgroundTasks スレッドで実行)
              │
              ├──► [Strategy Worker subprocess]   ※戦略ごとに新規プロセス
              │      gmsh.initialize → import STEP → mesh
              │      → flatten bad jacobian → write .inp/.npz/csv
              │
              └──► [CalculiX subprocess]
                     ccx <jobname>  (.inp → .frd)
                     stdout を pipeline 側でパース → 進捗化

成果物: workdir/jobs/<job_id>/ に集約 (.inp, .frd, mesh.npz, mesh_repair.csv, result.json)
```

**プロセス境界の意味**

| 境界 | 理由 |
|---|---|
| API ↔ Worker | gmsh の OCC エンジンは同一プロセス内で `clear() / finalize()+initialize()` してもコンテキスト汚染が残り、戦略フォールバックが silent fail する。subprocess 隔離で完全リセット |
| API ↔ CCX | 既存の subprocess 実行(stdout から STEP/INCREMENT 行をパース) |
| BackgroundTasks スレッドプール | gmsh.initialize() を main thread で行う必要がある(Python signal モジュール) ため、API 起動時に main で initialize。ジョブ実行は worker subprocess に委ねるので汚染なし |

---

## 2. データフロー(STEP → 結果可視化)

### 2.1 アップロード

```
POST /api/projects   (multipart, .step / .stp)
  └─ projects.create_project()
       1. 検証 (拡張子)
       2. workdir/<project_id>/input.step に保存
       3. load_step()  ← OCP STEPControl_Reader + BRepMesh
            - 面ごとに (positions, indices) を抽出
            - face_id = TopExp_Explorer 列挙順 (0,1,2,...)
       4. state.put(Project) で保存
       5. ProjectDTO 返却 (faceCount, triCount, bbox)
```

**面 ID は `load_step` を呼ぶたびに同じ順序になる**前提(TopExp_Explorer は決定論的)。Worker 側でも同じ STEP に対し同じ face_id 列が得られる。

### 2.2 ジオメトリ取得(3D ビュー描画用)

```
GET /api/projects/{id}/geometry
  └─ projects.get_geometry()
       FaceMeshDTO[] (faceId, positions, indices, triCount) を返却
```

フロント [scene/FaceMesh.tsx] で面ごとに `<mesh>` を生成しピッキング対象とする。

### 2.3 BC 設定

ユーザが面をクリック → `useProject.toggleSelect`。
右パネルで「拘束」「荷重」を追加 → `addFix` / `addLoad` がストアに `bcs: BC[]` を蓄積。

### 2.4 ジョブ投入

```
POST /api/jobs   (JobRequest: projectId, bcs, material, mesh)
  └─ jobs.create_job()
       1. 入力検証
            - projectId 実在
            - 少なくとも1つの拘束 (FixBC)
            - 少なくとも1つの荷重 (LoadBC)
       2. job_id 採番、Job(status="queued") を state に登録
       3. BackgroundTasks.add_task(run_job, job_id, req)
       4. JobDTO を即座に返却

      ※ BackgroundTasks は starlette のスレッドプールで sync 関数を実行
```

### 2.5 パイプライン (`solve.pipeline.run_job`)

スレッドプール内で以下を**順次実行**(同期):

```
1. status="meshing"   progress=0.02
2. mesh_and_write_inp(...)        ← 戦略ループ + subprocess
   - 戦略ごとに python apps/api/app/mesh/_worker.py <input.json> を起動
   - 成功した戦略の出力(job.inp / mesh.npz / result.json / mesh_repair.csv)を読み込み
3. status="solving"   progress=0.35
   run_ccx(inp_path)                ← ccx <jobname> をsubprocess実行
     - stdout の "STEP <n>" / "INCREMENT <n>" 行をパースし進捗 0.35→0.85 に補間
     - <jobname>.frd 生成
4. status="postprocess" progress=0.88
   parse_frd(frd_path)              ← 固定幅 ASCII を slice
     - DISP (Ux, Uy, Uz)
     - STRESS (Sxx Syy Szz Sxy Syz Szx)
     - von_mises は __post_init__ で算出
5. mesh.node_tags 順に disp / vonMises を整列
   (FRD 内の node id == gmsh tag == mesh.node_tags の値、同順)
6. ResultDTO を組み立て、Job.result に格納、status="done" progress=1.0
```

### 2.6 進捗ストリーミング

```
WS /ws/jobs/{job_id}
  └─ jobs_ws.job_ws()
       250ms 間隔で state.get_job(id) を読み、変化があれば JSON 送信
       status が done/failed/cancelled になった時点で close
```

### 2.7 結果取得 / ダウンロード

| エンドポイント | 内容 |
|---|---|
| `GET /api/jobs/{id}` | ステータス + 進捗 |
| `GET /api/jobs/{id}/result` | ResultDTO (nodes, disp, vonMises, surfaceIndices) |
| `GET /api/jobs/{id}/csv` | 全ノード CSV(座標+変位+応力テンソル+vM)、FRD を再パース |
| `GET /api/jobs/{id}/inp` | CalculiX 入力ファイル |
| `GET /api/jobs/{id}/repair-csv` | 補修・残存 bad 要素の重心リスト |

---

## 3. メッシングストラテジ(現行 4 戦略)

[apps/api/app/mesh/gmsh_runner.py](../apps/api/app/mesh/gmsh_runner.py)

| # | 名前 | algo2D | algo3D | 生成次数 | 昇格 |
|---|---|---|---|---|---|
| 1 | `fast tet10 (HXT)` | 6 (Frontal-Delaunay) | 10 (HXT) | 2 (tet10直接) | ✓ |
| 2 | `robust tet10 (HXT lin+elev)` | 6 | 10 | 1 (tet4) | ✓ (setOrder 2) |
| 3 | `Frontal tet10 (lin+elev)` | 6 | 4 (Frontal) | 1 | ✓ |
| 4 | `Frontal tet4 (C3D4)` | 6 | 4 | 1 | ✗ (tet4 のまま) |

**戦略の意図**

- **#1**: 大半の良性ジオメトリは即決(2〜4 秒)
- **#2**: tet10 直接生成で curved-edge 自己交差が出るケース。tet4 → setOrder(2) で curvature を後付けする方が安定
- **#3**: HXT が PLC error(surface 自己交差)で死ぬ場合の代替。Frontal は別の boundary recovery
- **#4**: 曲率なし → 構造的に**負ヤコビアン発生不可**。精度は落ちるが収束保証

**OCC healing は廃止**(以前の 9 戦略時に "Could not fix wire" を頻発させたため)。代わりに**生成後の品質補修**でカバー。

### 3.1 サブプロセス境界

各戦略は `apps/api/app/mesh/_worker.py` を `subprocess.run` で起動。

| 入力 | 形式 | パス |
|---|---|---|
| 引数 | JSON | `<out_dir>/_worker_input.json` |
| step_path, out_dir, target, strategy_name, bcs[], material | | |

| 出力 | 形式 | パス |
|---|---|---|
| `job.inp` | Abaqus/CalculiX text | CCX の入力 |
| `mesh.npz` | numpy zip | `node_tags`, `node_coords`, `tet_conn`, `surface_tris` |
| `mesh_repair.csv` | text/csv | `status,x,y,z` |
| `result.json` | JSON | element_count, strategy_used, repaired_*, dropped_* |

worker は **exit code 0 で成功**、それ以外は失敗(stderr 末尾行を `last_err` として親が記録、次戦略へ)。

タイムアウト: 戦略あたり **300 秒**(`_WORKER_TIMEOUT_S`)。

---

## 4. 負ヤコビアン補修ワークフロー

二次要素 tet10 では曲面に沿わせる際、curved edge が自己交差して `minSJ < 0` の要素が混じることがある(CalculiX が収束しない直接原因)。

### 4.1 防御層

| レイヤ | 対応 |
|---|---|
| 生成時 | `Mesh.HighOrderOptimize=2` (elastic optimization), `Mesh.OptimizeNetgen=1`, `Mesh.OptimizeThreshold=0.3` |
| 生成後 | `_flatten_bad_midside_nodes()` で bad tet10 の中間節点を edge midpoint へ移動 |
| 補修後 | `_try_repair_high_order()` で高次最適化(elastic + smoothing)再パス |
| 残存チェック | `_check_quality()`: 残存 1% 超なら次戦略 |

### 4.2 平坦化アルゴリズム

```
for 各 tet10:
    if minSJ <= 1e-6:
        for 6 本の edge:
            mid_tag が未処理なら
                mid_tag の座標 = 0.5 * (corner_a + corner_b)
                gmsh.model.mesh.setNode(mid_tag, midpoint, [])
        重心を repaired_centroids に記録
```

中間節点は隣接要素と共有されるので、bad 要素の連鎖が一括で修正される(平坦化された tet10 は tet4 と同じ幾何ヤコビアンになる)。

精度トレードオフ: 平坦化された要素では curved edge による曲率近似が失われる。ただし対象は「もともと自己交差していた要素」なので元から精度ゼロの領域。

### 4.3 出力(座標含む)

```
mesh_repair.csv:
    status,x,y,z
    repaired,12.5,3.4,-1.2     ← 平坦化した要素の重心
    repaired,...
    still_bad,8.1,4.2,0.0       ← 1%閾値超で次戦略へ移行する前の残存(参考情報)
```

ジョブメッセージにも `meshed: 6072 tet10 [fast tet10 (HXT)] · repaired 198` のように出る。

---

## 5. 主要モジュール責務一覧

### 5.1 バックエンド

| モジュール | 役割 |
|---|---|
| `app/main.py` | FastAPI エントリ。CORS、ルータ登録、起動時 `gmsh.initialize()` |
| `app/config.py` | `WORKDIR`, `CCX_PATH`, `ALLOWED_ORIGINS` の env 読み出し |
| `app/state.py` | スレッドセーフな in-memory ストア(`Project`, `Job`) |
| `app/cad/step_loader.py` | OCP で STEP 読み込み + 面別三角化 |
| `app/mesh/gmsh_runner.py` | 戦略ループ + subprocess 起動 + 補修ヘルパ群 + .inp 書き出し |
| `app/mesh/_worker.py` | サブプロセスエントリ。1 戦略を新プロセスで実行 |
| `app/solve/ccx_runner.py` | ccx の subprocess 実行 + 進捗パース + タイムアウト監視 |
| `app/solve/pipeline.py` | mesh → solve → post の全体オーケストレーション |
| `app/frd/parser.py` | FRD (固定幅 ASCII) パーサ。DISP / STRESS / vM |
| `app/routers/projects.py` | アップロード + ジオメトリ配信 |
| `app/routers/jobs.py` | ジョブ投入 + 履歴 + 結果取得 + CSV/INP/repair-CSV 配信 |
| `app/ws/jobs_ws.py` | WebSocket 進捗ストリーム |
| `app/schemas/jobs.py` | Pydantic: `BC` (FixBC/LoadBC), `Material`, `MeshOptions`, `JobRequest`, `JobDTO`, `ResultDTO` |
| `app/schemas/geometry.py` | Pydantic: `FaceMeshDTO`, `GeometryDTO`, `ProjectDTO` |

### 5.2 フロントエンド

| ファイル | 役割 |
|---|---|
| `src/App.tsx` | レイアウト(ヘッダ/左/右/下/中央 Canvas/凡例/トースト) |
| `src/scene/Viewer.tsx` | R3F Canvas、ライティング、グリッド、ギズモ。result.show 切替 |
| `src/scene/FaceMesh.tsx` | 面別 mesh + ピッキング(hover/select) + BC タグ着色 |
| `src/scene/ResultOverlay.tsx` | 結果メッシュを ShaderMaterial で描画。jet LUT, displaced position, edges 重ね描き |
| `src/store/useProject.ts` | zustand。project, geometry, bcs, history, material, dispScale, showResult, showMeshEdges, meshSizeMm, runAnalysis() |
| `src/api/client.ts` | 型付き fetch ラッパ + WebSocket 接続 |
| `src/data/materials.ts` | プリセット材料(S45C, SUS304, A5052, C1020, Ti-6Al-4V, custom) |
| `src/panels/Toolbar.tsx` | ヘッダーのフローティング pill。STEP 読込/解析実行 + 進捗バー |
| `src/panels/LeftTree.tsx` | プロジェクト/拘束/荷重/ジョブ履歴のツリー表示 |
| `src/panels/RightProps.tsx` | 選択面情報、BC 作成フォーム、材料 editor、メッシュサイズ |
| `src/panels/BottomLog.tsx` | スクロール可能なログパネル |
| `src/panels/ResultLegend.tsx` | von Mises カラーバー、変形倍率、エッジ表示、CSV/INP DL |
| `src/panels/Toasts.tsx` | error レベルのログを 6 秒トースト表示 |

---

## 6. 主要データ構造

### 6.1 Pydantic スキーマ

```python
class FixBC(BaseModel):
    type: Literal["fix"]
    faceIds: list[int]
    dofs: dict[str, bool]      # {"x": bool, "y": bool, "z": bool}

class LoadApplication = ...    # face / point / region (将来拡張)

class LoadBC(BaseModel):
    type: Literal["load"]
    faceIds: list[int]
    magnitude: float
    kind: Literal["force", "pressure"]
    direction: "normal" | {x, y, z}
    application: LoadApplication = LoadApplicationFace()

class Material(BaseModel):
    name: str
    young: float       # MPa
    poisson: float
    density: float     # t/mm^3

class MeshOptions(BaseModel):
    element: Literal["tet10"]
    sizeMm: float | None       # mm 絶対値(指定時はこちらが優先)
    sizeFactor: float          # 旧パラメータ(後方互換)

class JobRequest(BaseModel):
    projectId: str
    bcs: list[FixBC | LoadBC]
    material: Material
    mesh: MeshOptions
```

### 6.2 メッシュ生成結果(MeshResult)

dataclass で in-process 専用:

```python
@dataclass
class MeshResult:
    inp_path: Path
    node_count: int
    element_count: int
    node_tags: np.ndarray            # int64 (N,)  gmsh の tag = .inp の node label
    node_coords: np.ndarray          # float64 (N, 3)  mm
    tet_conn: np.ndarray             # int64 (E, 10|4)  0-based index into node_tags
    surface_tris: np.ndarray         # int64 (T, 3)
    strategy_used: str
    repaired_count: int
    repaired_centroids: list[(x,y,z)]
    dropped_count: int
    dropped_centroids: list[(x,y,z)]
    repair_csv_path: Path
```

### 6.3 .inp 形式(CalculiX)

```
*HEADING
auto_cae job
*NODE
1, x, y, z
...
*ELEMENT, TYPE=C3D10, ELSET=SOLID    ← または C3D4
1, n1, n2, n3, n4, n5, n6, n7, n8, n10, n9   ← 9,10 swap (gmsh→Abaqus)
...
*NSET, NSET=BC0
<BC0 を構成する node tag>
*NSET, NSET=BC1
*MATERIAL, NAME=MAT1
*ELASTIC
206000, 0.3
*DENSITY
7.85e-09
*SOLID SECTION, ELSET=SOLID, MATERIAL=MAT1
*STEP
*STATIC
*BOUNDARY
BC0, 1, 1, 0.       ← X方向固定
BC0, 2, 2, 0.
BC0, 3, 3, 0.
*CLOAD
<node>, <dof>, <force>          ← 等分布した節点力
*NODE FILE
U
*EL FILE
S
*END STEP
```

**面 ID → ノード集合の対応付け**

1. OCP で `face_id` を採番(TopExp_Explorer 順)
2. gmsh で同 STEP を `importShapes` し surface tag を取得
3. `_map_faces_to_gmsh`: OCP face centroid と gmsh `getCenterOfMass` の最近傍マッチ
4. BC ごとに `addPhysicalGroup(2, gmsh_tags)` を作成
5. `getNodesForPhysicalGroup` で含まれる節点 tag を取得 → BC0/BC1 NSET に列挙

**荷重の節点分配**(現行: 等分布)

- `kind="force"` `direction="normal"`:
  - 面の area-weighted normal を算出 → 内向きを正
  - `total = magnitude / n_nodes` を全節点に CLOAD
- `kind="pressure"` `direction="normal"`:
  - `total = magnitude × area / n_nodes` を全節点に CLOAD
- `direction={x,y,z}`:
  - 指定方向の単位ベクトル × 上記に従って分配

将来拡張: 面積按分(tributary area)で精度向上、`*DSLOAD` (面圧)対応など

---

## 7. UI ステート遷移(zustand)

```
project: ProjectDTO | null               ← upload 後に充填
geometry: GeometryDTO | null             ← /geometry 取得後
bcs: BC[]                                ← 編集中の BC リスト
selectedFaceIds: Set<number>             ← 選択中の面
hoveredFaceId: number | null

job: JobDTO | null                       ← 解析中・直近のジョブ
result: ResultDTO | null                 ← 完了結果
history: JobDTO[]                        ← プロジェクトの過去ジョブ

dispScale: number                        ← 結果表示の変形倍率
showResult: boolean                      ← 結果 ↔ 元モデル切替
showMeshEdges: boolean
meshSizeMm: number                       ← 1〜10 mm 絶対指定
material: MaterialSpec
```

主要アクション: `uploadStep`, `addFix`, `addLoad`, `removeBc`, `runAnalysis`, `loadJobResult`, `setMaterial`, `setMeshSizeMm` など。

---

## 8. 拡張時の参考ポイント

### 8.1 新しい解析タイプを追加する場合

例: 線形動解析、熱伝導、接触

- `app/schemas/jobs.py` に解析設定を追加(`JobRequest.analysis: Linear | Modal | Heat`)
- `app/mesh/gmsh_runner._write_inp` を解析タイプで分岐(`*FREQUENCY`, `*HEAT TRANSFER` 等)
- `app/frd/parser` を新しい変数(温度、固有モードなど)対応に拡張
- フロントは結果表示モード(モード形状アニメーション、温度マップ等)を追加

### 8.2 新しいメッシングアルゴリズムを試す場合

`_STRATEGIES` リストに `_Strategy` を追加するだけで自動的に試行ループに組み込まれる。

```python
_Strategy("custom name", algo2d, algo3d, order_at_gen, elevate)
```

既存戦略の前後どちらに置くかで優先度が決まる(戦略は前から順に試行)。

### 8.3 別のメッシャ(Netgen/TetGen等)を導入する場合

`_worker.py` のメッシング部分を分岐するか、別 worker 用意。MeshResult と `mesh.npz` の形式を維持すれば pipeline 以降は変更不要。

### 8.4 BC タイプを追加する場合(例: 強制変位、温度境界)

- `schemas/jobs.py` に新 BC クラス + `BC = Union[...]` に追加
- `gmsh_runner._collect_bc_payloads` でデータ収集
- `gmsh_runner._write_inp` で対応する CalculiX 句(`*BOUNDARY` の値指定 `*TEMPERATURE` 等)を出力
- フロント `RightProps.tsx` に作成フォームを追加

### 8.5 結果のエクスポート形式追加

- `app/routers/jobs.py` に新エンドポイント
- VTU(ParaView)、CSV(現行)、JSON 等を増やせる
- フロント [ResultLegend.tsx] にダウンロードボタン追加

### 8.6 サブプロセス worker をマルチコア活用したい場合

現行は 1 戦略ずつ順次。複数戦略を並列実行して最初の成功を採用する戦略レースが可能(CPU 使用率↑、最速時間↓)。`concurrent.futures.ProcessPoolExecutor` で実装可能。

---

## 9. 既知の限界・注意点

| 事項 | 詳細 |
|---|---|
| OCC healing 廃止 | `Could not fix wire` 多発のため。代わりに「補修ワークフロー」で吸収 |
| 一部の螺旋形状 | PG7 Cable Gland のような threaded 部品は gmsh の 2D サーフェスメッシャがそもそも自己交差を生む。STL 再構築も createGeometry で失敗。CAD 側で thread suppress が必要 |
| 単位系 | mm-N-MPa 強制。Material 値は MPa / t/mm³ で定義 |
| 単一プロジェクト・単一ジョブ前提 | state は in-memory dict。永続化なし。複数ユーザ同時実行は未考慮 |
| ASCII パス | workdir パスに日本語/空白を含めると ccx が落ちる可能性。`config.WORKDIR` は ASCII 推奨 |
| node_tags はジョブ内で連続 | gmsh の node tag は 1..N で連続することを前提に補修ロジックが書かれている |

---

## 10. デバッグ手段

| やりたいこと | 手段 |
|---|---|
| 失敗ジョブの再現 | `workdir/jobs/<id>/_worker_input.json` を python で worker に直接渡す: `python apps/api/app/mesh/_worker.py <input.json>` |
| 戦略を一つだけ試す | `_worker_input.json` の `strategy_name` を書き換えて再実行 |
| 補修対象要素の場所を確認 | `mesh_repair.csv` を CSV ビューワで開く |
| .inp の構造確認 | `grep -nE "NSET|BOUNDARY|CLOAD|MATERIAL" job.inp` |
| FRD の中身を Python から | `from app.frd.parser import parse_frd; r = parse_frd("job.frd"); print(r.von_mises.max())` |
| メッシュ単独テスト | `scripts/test_mesh_pipeline.py <step> <size>` |
| エンドツーエンド単独テスト | `scripts/test_e2e.py`(test.step 固定) |
| 戦略隔離テスト | `scripts/diag_one.py <step> <size> <algo3d> <order> [curvN] [defeat]` |

各種診断スクリプトは [scripts/](../scripts/) 配下。

---

## 11. ディレクトリ構造(再掲)

```
apps/
  web/                              # Vite + React + TS
    src/
      App.tsx
      scene/{Viewer,FaceMesh,ResultOverlay}.tsx
      panels/{Toolbar,LeftTree,RightProps,BottomLog,ResultLegend,Toasts}.tsx
      store/useProject.ts
      api/client.ts
      data/materials.ts
      styles/globals.css
  api/
    app/
      main.py                       # FastAPI エントリ
      config.py
      state.py
      cad/step_loader.py
      mesh/
        gmsh_runner.py              # 戦略 + subprocess dispatch + helpers
        _worker.py                  # subprocess エントリ
      solve/{ccx_runner,pipeline}.py
      frd/parser.py
      routers/{projects,jobs}.py
      ws/jobs_ws.py
      schemas/{geometry,jobs}.py
    pyproject.toml
docs/
  WORKFLOW.md                       # 本ドキュメント
scripts/
  doctor.py                         # 依存診断
  test_mesh_pipeline.py             # メッシュ単独
  test_e2e.py                       # E2E (mesh+ccx+post)
  diag_*.py                         # 戦略診断
  stress_repair.py                  # 補修ロジック検証
workdir/                            # ジョブ成果物 (gitignore)
  <project_id>/input.step
  jobs/<job_id>/{job.inp, job.frd, mesh.npz, mesh_repair.csv, result.json, _worker_input.json}
```
