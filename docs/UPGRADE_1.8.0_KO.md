# Aether EM 1.8.0 — 사용 안내

새 폴더에 압축 해제 후 `SETUP_WINDOWS.cmd` → `START_WINDOWS.cmd`. 완성된 예제는 `examples\*.warp`(File ▸ Open Project).
아래 수치는 이 릴리스를 만들면서 직접 측정한 값이고, 한계도 같이 적음.

---

## 0. 해석이 너무 오래 걸릴 때 (측정값)

3 GHz 2차 요소 다이폴(약 3.9만 미지수)을 이 환경(4코어)에서 풀었을 때:

| 직접 해법 | 시간 |
|---|---|
| SuperLU (이전 기본) | **18분 넘게 끝나지 않음** (COLAMD / MMD / METIS 정렬 모두 5분 이상) |
| **PARDISO (기본, 설치되어 있으면)** | 분해 약 **2 s**, 해석 전체 약 5 s (같은 행렬 잔차 2e-14, 지향성 2.245 dBi로 동일) |

SuperLU는 단일 스레드이고 3D 메시용 정렬이 약해서 미지수가 3~4만을 넘으면 급격히 느려지는 것이 정상임(표준 3D 라플라시안 2.7만도 44 s). `SETUP_WINDOWS.cmd`가 `pypardiso`를 같이 설치하며, 실패해도 설치는 계속되고 내장 해법(느림)으로 동작함. 이미 설치한 환경은 `.venv\Scripts\pip install pypardiso` 한 줄이면 됨. 설치 여부는 메시지 창의 `linear solver ready [direct/pardiso …]`에서 확인.

그 외 빨리 보는 방법: ① 기본 예제는 먼저 `Basis order = 1`, `Maximum passes = 1`, 스윕 점 수를 줄여 형태만 확인 ② 공기 영역(R, H)과 `max_element_size`를 키워 미지수를 줄임 ③ Interpolating 스윕 사용(전체 풀이 횟수가 줄어듦). 안테나 절대 이득·효율은 2차 요소와 충분한 공기 영역이 필요하므로 최종 확인은 줄이지 말 것.

## 1. 요청하신 항목별 정리

| 요청 | 1.8.0 상태 |
|---|---|
| 오브젝트 다중 선택 후 재료·색·투명도 일괄 변경 | **됨.** 2개 이상 선택하면 속성창이 일괄 편집 패널로 바뀜(재료, 색, 투명도, 표시, Solve inside). 한 번의 Undo로 전부 되돌림 |
| 색 지정은 기본 색 + 상세 설정 | **됨.** 12색 기본 팔레트(구리·금·은·회색·빨강·주황·노랑·초록·파랑·보라·흰색·검정) + `…` 버튼으로 전체 색 선택기 |
| 사각형이 XY로만 그려지던 문제 | **수정.** XY / YZ / ZX 작업 평면을 선택해 그림. 입력한 좌표가 그대로 형상이 됨(브라우저 테스트로 3개 평면 모두 확인) |
| 마우스로 위치 선택 + Tab으로 수치 입력 | **됨.** 아래 2장 |
| 면 그리기 → 포트 지정, Lumped / Wave Port | **됨.** Rectangle·Circle로 면을 그리고, 선택 후 우클릭 `Assign Lumped Port…` / `Assign Wave Port…`. 두 도체 면을 클릭하는 `Port (pick)`도 유지 |
| Setup(주파수 등) | **됨.** 3장 |
| E, H 필드, 전류 흐름, 안테나 방사 | **됨.** 4장 |
| 불필요한 기능·asset 제거 | 릴리스 패치/결과 XML/구버전 안내/스크린샷 일부 삭제 |
| 다이폴 안테나 완성 파일 + 여러 예제 | `examples/` 9개 프로젝트. 5장 |

## 2. 그리기: 마우스 + Tab

`Draw ▸ Draw Box / Rectangle / Cylinder / Circle / Sphere / Cone by Points`

1. 패널의 **Plane**에서 XY / YZ / ZX 선택(또는 `P` 키로 순환). **Offset**은 평면의 위치.
2. 첫 점: 클릭하거나 **Tab**을 눌러 X, Y, Z를 입력(다음 칸은 Tab, 이전은 Shift+Tab).
3. 둘째 점·크기: 클릭하거나 Tab → `dX, dY`(Box는 높이 포함) 입력. 원형 도형은 Radius, 원기둥/원뿔은 Height(, Top radius).
4. **Enter**로 확정, **클릭**도 지금까지 입력한 값을 확정. 입력 중에는 마우스를 움직여도 숫자가 덮어써지지 않음.
5. `Esc`: 입력 칸 안에서는 마우스로 제어권을 되돌리고, 칸 밖에서는 한 점 뒤로(한 번 더 누르면 취소). `S` 스냅 토글.
6. **Plane from face**(기본 켜짐): 첫 점을 찍기 전에 평평한 면 위로 마우스를 가져가면 그 면이 작업 평면이 됨(기판 윗면에 패치 그리기). 평면 버튼을 직접 누르면 꺼짐.

높이는 항상 작업 평면의 법선 방향임(YZ 평면의 Box는 X 방향으로, ZX 평면의 원기둥 축은 Y).

## 3. Setup / Sweep

`Simulation ▸ Add Solution Setup…`, 트리의 Setup 우클릭 `Edit Setup…`

| 항목 | 의미 |
|---|---|
| Solution frequency | 적응형 메시를 세분화하는 주파수 |
| Maximum number of passes / Minimum number of passes | 패스 수 범위 |
| Minimum converged passes | 목표 ΔS를 연속으로 만족해야 하는 패스 수 |
| Maximum delta S | 패스 간 최대 \|ΔS\| 목표 |
| Refinement per pass [%] | 패스마다 세분화하는 요소 비율(기본 30) |
| Basis function order | 1차(Whitney) / 2차 |

`Add Frequency Sweep…`, 트리의 Sweep 우클릭 `Edit Sweep…`

| 항목 | 의미 |
|---|---|
| Sweep type | **Discrete**(모든 점 풀이) / **Interpolating** / **Fast** |
| Frequency setup | **Linear count** / **Linear step** / Log scale / Single point |
| Error tolerance, Max solutions | Interpolating·Fast의 허용 오차와 최대 풀이 수 |
| Save fields in this sweep | 필드 저장(필드·방사패턴에 필요) |

**Interpolating / Fast는 이제 실제로 동작함.** 이전 버전에서는 라벨만 있고 모든 점을 풀었음. WR-90 81점 스윕은 Interpolating에서 전체 풀이 20회로 같은 정확도(|ΔS| < 1e-3)를 냄. 7점 미만의 짧은 스윕은 그냥 모든 점을 풂. 컷오프를 가로지르는 대역은 √ 분기점 때문에 풀이가 더 필요함(161점에 40회).

## 4. 결과 보기

**필드 플롯** — `Results ▸ E Field / H Field / Surface Current |Js| / Field on Cut Plane` (해석 전에 *Save fields*)

- 양: |E|, |H|, **|Js|**(= n × H, 도체 표면 전류).
- 대상: 모든 외곽면(전류는 모든 도체), 선택한 객체, 또는 **컷 플레인**(축 + 위치 슬라이더).
- **Instantaneous**: RF 주기의 임의 위상에서의 값. `▶ Animate`로 돌리면 전류가 흐르는 것이 보임.
- **Vector arrows**: 방향 표시. 스케일은 Linear 또는 dB(40 dB 범위).

**선택한 금속에서만 필드/전류 보기** — 필드 패널(`Results ▸ E Field` 등)에서 `Plot on ▸ Chosen metals`를 고르면 도체 객체와 시트가 체크 목록으로 나타남. 체크한 금속에서만 E, H, 표면 전류 |Js|가 그려지고 나머지 모델은 흐리게 뒤에 남음(`Model opacity`로 조절). `selection / all / none` 버튼과 `Follow viewport selection`(3D 뷰나 프로젝트 트리에서 금속을 클릭하면 그 금속의 필드/전류가 바로 표시)이 있음. 색 범위는 선택한 금속의 최댓값 기준임. 내보낸 three.js 뷰어에도 같은 금속 목록이 있음.

**결과 목록·중간 결과·마커** — 

- 왼쪽 프로젝트 트리의 `Results` 아래에 해석 후 `S Parameter Plot 1`, `Port Modes`, `Convergence`, `E Field`, `H Field`, `Surface Current`(방사 경계가 있으면 `Radiation Pattern`, `3D Radiation Pattern`)가 나열됨. 클릭하면 그 결과가 저장된 설정 그대로 열리고, `Results` 메뉴로 새로 만들면 목록에 추가됨. 우클릭: Duplicate / Rename / Delete.
- **해석 도중에도** 적응형 패스가 끝날 때마다, 주파수 점이 풀릴 때마다 Results가 열리고 열려 있는 플롯이 자동으로 갱신됨(트리에 `running…` 표시). 중간에 실패/취소해도 그때까지의 결과는 남음.
- 플롯은 **창 크기에 맞게 가득 차게** 그려짐. 위쪽 상자에서 X/Y 최소·최대를 직접 입력, 휠로 확대/축소, 드래그로 이동, 더블클릭 또는 `Auto`로 복귀.
- **마커**: 플롯을 클릭하면 가장 가까운 곡선 위 점에 `m1, m2…`가 찍히고, 표에 X, Y, m1과의 차이(ΔX, ΔY)가 표시됨. 마커는 곡선을 따라 드래그, 더블클릭/× 로 삭제, `Marker ▲ Peak / ▼ Min`으로 극값에 바로 지정. 극좌표 패턴은 `Max [dB]`, `Range [dB]`를 입력해 스케일 조정.
- 필드 패널의 `Plot opacity`, `Model opacity`로 방사 패턴 안쪽의 안테나가 보이도록 투명도를 조절.
- **결과 저장**: 해석을 마친 프로젝트를 저장하면 `프로젝트.warp.wres`가 함께 저장되고, 다시 열면 재해석 없이 결과가 복원됨. `.warp`를 수정했다면(다른 파일로 바뀐 것이므로) 결과는 불러오지 않음. 두 파일을 함께 옮겨야 함.

**포트 방향 — New Line (Warps 방식)** — Lumped/Wave 포트 모두 같은 방법임: 포트 면을 선택하고 `Assign Lumped Port…`(또는 Wave)에서 `🖱 New Line…`을 누르면 대화상자가 잠시 사라지고, 3D 뷰에서 **signal 쪽 점 → ground 쪽 점** 순서로 클릭함.

- 점은 꼭짓점/모서리 중점에 달라붙고(12 px 이내), 두 번째 점을 정하는 동안 **signal → ground 화살표가 미리 보임**. 좌표는 패널에 실시간으로 표시됨.
- **Tab**을 누르면 좌표 입력 칸으로 이동해 직접 입력할 수 있고 `Enter`로 확정, `Esc`로 취소. `⇄ Swap`으로 방향을 뒤집음.
- 선은 signal에서 ground로 향하며 **포트의 전계(E)가 그 방향**임(전계는 + 에서 − 로). Wave 포트의 모드 극성 규칙(∫e·l̂ > 0, Warps 규약)과 같은 방향임. 대화상자의 `Detect from selection`은 선택한 면의 크기로 축 방향 끝점을 채움.
- 이미 만든 포트는 속성창 또는 우클릭의 `Reverse Polarity` / `Edit Polarity…`(여기에서도 New Line 사용). Undo 한 번으로 복구되고 `.warp`에 저장됨. 3D 뷰에는 모든 Lumped 포트의 화살표가 그려짐.
- **주의(동작 변경):** 두 면을 클릭하는 `Lumped / Wave Port (pick)` 도구로 만든 포트는 이제 signal → ground 방향임(이전 ground → signal). 두 포트를 가진 구조에서 S21의 부호(위상 180°)가 1.7.x와 달라질 수 있음. 방향을 직접 지정한 기존 프로젝트의 계산값은 그대로이고 대화상자의 끝점 이름만 새 규약을 따름. 두 포트의 방향이 서로 반대이면 S21 위상이 180° 틀어지므로 확인해야 함.

**안테나 성능 vs 주파수** — `Results ▸ Antenna Parameters vs Frequency…`: Directivity, Gain(Total), **Realized gain**(= Gain × (1−|S11|²)), Radiation/Total efficiency, |S11|을 주파수에 대해 플롯함. 각 주파수의 최댓값 방향 또는 고정 (θ, φ), 전체/θ/φ 편파를 고를 수 있고 마커와 표가 있음. 주파수마다 저장된 필드가 필요하므로 이산(Discrete) 스윕에서 *Save fields*를 켜야 함.

**기타 사용성** — 프로젝트를 닫거나 새로 만들면 이전 해석의 결과 탭·필드 표시·범례·Results 목록이 모두 사라짐. 파일 열기/저장 창은 이름·최신순·크기·종류로 정렬(드롭다운 또는 열 머리 클릭, 선택 기억). 대화상자와 필드/그리기/New Line 패널은 제목줄을 끌어 이동(더블클릭으로 원위치, 위치 기억), 대화상자는 크기 조절도 됨. 필드 패널의 `Show plane`(컷 플레인 표시/숨김)과 뷰포트의 `Grid plane` 버튼으로 평면을 켜고 끔.

**시간 애니메이션** — 필드 패널(`Results ▸ E Field` 등)에서 주파수를 고르고 `▶ Animate`.

- E, H, 표면 전류 |Js|와 **Far field(방사)** 모두 RF 한 주기 동안 움직임. `Speed`(느리게/보통/빠르게)와 위상 슬라이더 제공.
- `Component`를 X / Y / Z로 하면 부호 있는 순시 성분이 나와 파동이 이동하는 모양이 보임(|V|는 맥동으로만 보임).
- Far field는 순시 원거리 |E|가 3D 곡면으로 커졌다 작아졌다 함. 정적 이득(dBi)도 선택 가능.
- 주파수 선택은 항상 보임. 저장된 주파수가 하나뿐이면 비활성이며, 여러 주파수를 보려면 이산(Discrete) 스윕에서 *Save fields in this sweep*을 켜야 함.
- **Radiation 경계는 기본으로 숨김**(필드·패턴을 가리지 않도록). `Results ▸ Show Radiation Boundary`로 켜고 끔.

**3D 뷰어 내보내기 (three.js)** — `File ▸ Save Project As…`에서 파일 형식을 *three.js 3D viewer (\*.html)*로 고르거나 `File ▸ Export 3D Viewer (three.js)…`.

- 결과는 **하나의 HTML 파일**이며 three.js가 내장되어 있어 인터넷 없이 더블클릭으로 열림. 파이썬/Aether가 필요 없음.
- 모델: 객체별 색·투명도·표시 토글, 포트·경계·모서리 표시, 마우스로 회전/이동/확대, XY·YZ·ZX·Iso 시점, 배경 전환, PNG 저장, 객체에 마우스를 올리면 이름·재료 표시.
- 결과(해석 후, *Save fields* 필요): 표면과 X/Y/Z 중심 단면의 E, H, 도체 표면 전류, 방사패턴, S-파라미터 그래프(점을 눌러 주파수 이동), 안테나 파라미터 표.
- 필드는 **복소수 그대로 저장**하므로 뷰어에서 위상 슬라이더, 애니메이션, |V|/X/Y/Z, 주파수·여기 선택이 모두 실시간으로 동작함(동영상이 아니라 데이터).
- 한계: 저장하는 것은 내보낼 때의 해석 결과 하나임(주파수는 최대 6개, 여기 4개가 기본값이며 내보내기 창에서 조정). 단면은 모델 중심 한 위치에 고정이고, 메시가 클수록 파일이 커짐. 오프라인에서 열리도록 three.js(MIT) r149를 `aether/gui/vendor`에 포함함.

**방사패턴** — `Results ▸ Far Field Radiation Pattern…`

- 극좌표 / 직교 플롯(φ 컷 2개, 큰 원으로 φ와 φ+180° 반평면), Gain(θ/φ 성분)·Directivity 선택, `3D pattern`.
- 표: 최대 지향성·이득, 실현 이득(mismatch 반영), 최대 방향, **복사 효율**, 전후방비, 축비, 그리고 **영역 점검**(경계 흡수전력 / 원거리장 전력, 1에 가까워야 함 — 크게 어긋나면 공기 영역이 너무 작거나 메시가 거칠다는 경고).
- Radiation 경계가 있어야 하고 필드가 저장되어 있어야 함.

**S-파라미터** — `Results ▸ Create Modal S-Parameter Report`: dB, \|S\|, 위상, **Smith chart**, VSWR, **Re/Im/\|Z\|**(입력 임피던스), Re/Im(S), 군지연.

**Eigenmode** — `Project ▸ Insert Warps Eigenmode Design` → Eigenmode Setup(모드 수, 최소 주파수, 최대 Δf) → Analyze → `Results ▸ Eigenmode Data`(주파수, Q, 수렴 표, 모드별 필드).

**최적화** — `Tools ▸ Optimization…`: 변수 범위, 목표(S 파라미터 대역 조건, 노치 주파수, 고유모드 주파수, 최대 이득), 옵티마이저 선택. 매 시도는 복사본에서 실제 풀이를 하며 `Apply best values`가 한 번의 Undo 단계임. 변수는 치수에 연결되어 있어야 함(`Tools ▸ Design Variables…` + 치수 편집).

### 포트 자동 설정 (좌표 입력 없이)

1. 금속 설정 후 **신호선**을 선택(객체 또는 면/모서리) → 우클릭 ▸ **Mark as Signal (+)**
2. **GND**를 선택 → 우클릭 ▸ **Mark as Ground (−)** (여러 개는 *Add Selection to …*)
3. 우클릭 ▸ **Assign Lumped Port (auto)** / **Assign Wave Port (auto)** / **Assign Port (auto type)**
   - Lumped: 신호선 끝(모델 경계에 가까운 쪽)에서 신호↔GND 간극을 잇는 시트가 자동 생성되고 적분선은 signal → ground. 폭은 두 도체 중 좁은 쪽. 같은 선에 두 번째 포트는 반대쪽 끝에 만들어짐.
   - Wave: 신호선 끝단에 단면을 잡고 창은 GND 단면 전체(또는 신호폭의 약 10배)로 자동 결정, 적분선은 마주 보는 도체 면에 맞춤.
   - Auto type: 도체가 모델 경계까지 나가 있으면 Wave, 내부에 있으면 Lumped.
   - 객체 2개를 선택하면 **Lumped/Wave Port between the two selected**(먼저 선택 = signal)로 한 번에 생성.
4. 간극이 λ/10보다 크면 Lumped 정확도 경고가 나옴 → Wave 포트 사용.

검증: 직선 마이크로스트립에 자동 Wave 포트 2개 → \|S21\| > 0.7, \|S11\| < 0.6.

### 포트가 "말도 안 되게" 생기던 문제 (수정됨)

자동 포트가 신호 도체 **전체의 바운딩 박스**로 크기를 정해서, 패치와 급전선이 한 객체이면 3 mm 선에 30 mm 폭의 포트가 만들어졌음. 이제:

- **급전 끝**을 "모델 경계에 가장 가까운 도체의 끝"으로 찾고, 그 끝면의 **실제 꼭짓점**에서 선폭을 읽음 → Lumped 시트 폭 = 그 선폭, Wave 포트 창 = 선폭의 10배(중심은 선 중심).
- 시트는 그라운드 위에 놓이도록 잘리고, 신호와 그라운드가 겹쳐 있는(예: 코플래나 선로) 경우도 가장 가까운 간극을 잇음. 경계에 닿지 않는 도체(다이폴 팔)는 도체 가운데로 급전.
- **금속 두 개를 선택**하고 Lumped/Wave Port를 고르면 `Assign Port between two metals` 창이 열림: Signal/Ground 지정(Swap), 포트 종류, 그리고 "무엇이 만들어질지" 설명이 즉시 표시됨.

### Lumped RLC

`Simulation ▸ Boundaries ▸ Lumped RLC` 또는 금속 두 개 선택/마킹 후 우클릭 ▸ **Assign Lumped RLC…**. R, L, C는 `2.2n`, `0.5p`처럼 접미사 사용 가능, 병렬/직렬 선택. 이전 버전은 R(Ω)을 면저항(Ω/sq)으로 취급해 값이 시트의 가로세로비만큼 틀렸고 두 방향 성분을 모두 부하했음. 이제 시트 폭 w, 길이 L에 대해 Zs = Z·w/L 이고 전류는 지정한 방향(기본: 시트의 짧은 변)으로만 흐름. 평행판 선로 해석해(Γ = (Z−Z0)/(Z+Z0), 위상 포함)와 비교 검증.

### 그리기 스냅 · Hide/Show · 불투명 로드 · 속도

- 점을 찍을 때(Box/Rectangle/Cylinder… by points, Move by two points) 커서가 12 px 안의 **꼭짓점 / 모서리 중점 / 면 중심**으로 이동하고 힌트에 종류가 표시됨. 그리기 패널의 *Snap to model*로 끔.
- 오브젝트 우클릭(뷰포트·트리) ▸ **Hide / Show / Hide Others / Show All** (선택 전체에 적용).
- 파일 열기·CAD 가져오기 후 부품은 **불투명**으로 표시(air/vacuum/radiation 영역은 안이 보이도록 투명 유지). 직접 지정한 투명도는 유지됨.
- 열기 속도: 표시용 메쉬를 CAD 커널이 두께에 맞춰 잘게 만들던 것을 수식 기반 삼각분할로 대체. 299개 부품 프로젝트 기하 구성 22.8 s → 1.4 s, 전송 데이터 107 MB → 6.6 MB. STEP 299개 가져오기 19 s → 13 s (그중 6 s는 STEP 읽기 자체).

### 상대 좌표계 (Relative CS)

`Draw ▸ Coordinate System ▸ Relative CS…`에서 객체의 **꼭짓점 / 모서리 중점 / 면 중심**을 클릭(스냅)하거나 좌표를 직접 입력하면 그 점이 원점인 작업 CS가 됨. 이후 그리기·포트·New Line의 입력값과 상태바 좌표가 모두 이 CS 기준으로 표시·입력되고, 모델과 파일은 전역 좌표(m)로 저장됨. 상태바 칩에서 작업 CS 변경, 이름 변경, 삭제, Global 복귀. `.warp`에 저장됨. **한계: 평행이동만 지원** (회전 CS, Face CS 없음).

### HFSS 100 Tips 반영 · 속성 패널 편집 · 자유 회전 · 저장 문제

자세한 표는 [HFSS_TIPS_COVERAGE_KO.md](HFSS_TIPS_COVERAGE_KO.md). 요약:

- **모델링**: Sweep(축/벡터/경로), Equation Based Curve(타원·헬릭스·스파이럴), Cover Lines, Line Pattern, Split, Move Edges, **Copy & Move / Mirror / Mirror Copy**(두 점 클릭), Paste & Move.
- **경계/포트가 형상을 따라감**: 이동·회전·대칭·크기 변경 시 함께 이동, 복사/붙여넣기/Duplicate 시 함께 복사(기본 켜짐).
- **영역 선택**: 왼→오 드래그는 걸친 개체까지, 오→왼은 완전히 포함된 것만. Edit ▸ Select by Area Filter…
- **결과**: Expression Plot / Output Variables(`1e9*im(Z(1,1))/2/pi/Freq` 등), Field on Line. **단축키**: Tools ▸ Keyboard Shortcuts…
- **3D 회전**이 극점에서 멈추지 않음. **three.js 저장**이 기존 파일 위에 덮어쓸 때 조용히 취소되던 문제 수정(브라우저 `confirm()` 의존 제거).
- **좌측 속성 패널**에서 Sweep 주파수 범위를 포함해 수정 가능한 값은 모두 입력란으로 수정.

## 5. 예제

| 프로젝트 | 확인한 결과 |
|---|---|
| `dipole_antenna.warp` | 예제 자체 설정(2패스 적응형 + Interpolating 17점, 풀이 12회·약 3분)으로 공진 2.95 GHz, Zin = 69 − 1j Ω, 최적 S11 −17 dB, 지향성 2.18 dBi(이론 2.15) @ θ=90°, 축 방향 −50 dBi, 전후방비 0.01 dB |
| `wr90_waveguide.warp` | 차단주파수 6.558 GHz(해석 6.557), 43점 Interpolating |
| `iris_filter.warp` | 9.46 GHz에서 S11 −75 dB(공진 대역통과), Fast sweep, 풀이 약 40초 |
| `cavity_eigenmode.warp` | TE101 9.0078 GHz(해석 9.0076) 외 4개 모드 |
| `copper_cavity_eigenmode.warp` | Q = 9178(Pozar 9182, 0.04 %) |

자세한 목록과 GUI 작업 순서는 [examples/README.md](../examples/README.md). `python examples/build_examples.py --verify`로 모두 다시 만들고 실제로 풀어 확인할 수 있음.

## 6. 이번에 찾아 고친 버그(결과 정확도에 영향)

1. **Radiation 경계가 안테나 금속에 걸림.** `OuterSelector`("모든 외곽면")가 해석 영역에서 빠진 PEC 몸체의 표면까지 선택해, 안테나 도체 표면에 흡수 경계가 설정되고 있었음. 다이폴의 입력저항이 약 2배로 나오고 방사 전력 수지가 맞지 않던 원인. 이제 공기 영역의 바깥면만 뜻함. **안테나/코일 해석 결과가 이전 버전과 달라질 수 있음.**
2. 직접 솔버가 대칭 패턴 행렬에 COLAMD(AᵀA용) 정렬을 써서 느렸음 → MMD_AT_PLUS_A로 바꿔 8.7k 미지수에서 38 s → 0.45 s.
3. 시트(면) 객체에 대한 Mesh Operation이 gmsh를 중단시키던 문제, 작은 포트 시트가 있는 모델에서 Netgen 최적화가 프로세스를 죽이던 문제.
4. `Circle` 경계상자가 축 방향으로 부풀려져 측정/범위가 틀리던 문제, 다중 편집이 실패했을 때 `solve_inside` 롤백이 안 되던 문제.

## 7. 한계 (숨기지 않고 적음)

- **PML, 주기 경계/Floquet 포트, Terminal(차동) 솔루션은 없음.** 안테나는 Radiation(1차 흡수) 경계로 푸므로 경계를 방사체에서 λ/4 이상 띄우고, 이득·효율의 **영역 점검** 값을 확인해야 함. 지향성·패턴 형태는 작은 영역에서도 비교적 잘 나오지만 절대 이득·효율은 그렇지 않음.
- **Eigenmode는 Radiation 경계를 지원하지 않음**(해가 신뢰할 수 없어 검증 단계에서 거부). PEC, 유한 도전율, 표면 임피던스, 유전체 손실은 해석해로 검증됨.
- 1차 요소는 얇은 와이어 안테나에서 입력 저항이 크게 나옴(같은 메시에서 1차 126 Ω vs 2차 92 Ω → 길이 튜닝 후 2차 적응형 69 Ω). **안테나는 2차 요소를 권장.** 예제 다이폴은 2차로 설정됨.
- Fast sweep은 주파수마다 포트 2D 모드 해석을 하므로 작은 모델에서는 시간이 크게 줄지 않음(큰 3D 모델에서 이득). Interpolating은 포트 해석도 건너뜀.
- 최적화의 국소 옵티마이저는 시작점이 해 근처여야 함(좁은 노치는 평탄 구간에서 못 내려옴). 이 경우 Differential evolution을 사용.
- 면에서 작업 평면을 가져오는 기능은 축 정렬 면만 지원.
- 해석 시간은 이 환경(Linux, 4코어)에서 측정한 값이며, 이 도구는 외부 해석 도구와의 수치 일치를 보증하지 않음. 중요한 설계는 실측 또는 독립 솔버로 검증해야 함.

## 8. 검증

- 파이썬 테스트(브라우저 제외) 전체 통과 + 브라우저(Chromium) 테스트 전체 통과. 신규: 스윕, Eigenmode, 원거리장, 최적화, 다중 선택, 작업 평면 드로잉, Setup 필드, 필드 플롯, 리포트 형식.
- 해석해 비교: 직사각 공동 공진, 유전체 Q, 구리 Q, Hertz 다이폴 원거리장, 반파 다이폴 입력저항·지향성, WR-90 모드·차단주파수.
